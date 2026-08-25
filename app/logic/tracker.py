# app/logic/tracker.py

from __future__ import annotations

import asyncio
import random
import socket
import struct
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from app.logic.bencode import Bencode
from app.logic.torrent_file import TorrentFile


class TrackerQueryError(RuntimeError):
    """Raised for a tracker response that completed but was not usable."""


class TrackerClient:
    """Handles HTTP, HTTPS, and UDP announces for a torrent session.

    The client also keeps lightweight per-tracker telemetry for the Sources
    detail view. The telemetry records only tracker protocol activity; it does
    not fabricate peer counts for trackers that have not actually replied.
    """

    def __init__(self, torrent: TorrentFile, peer_id: bytes, port: int = 6881):
        self.torrent = torrent
        self.peer_id = peer_id
        self.port = port

        self._source_records: Dict[str, dict] = {}
        for tracker_url in self.torrent.announce_list:
            self._ensure_source_record(tracker_url)

    @staticmethod
    def _tracker_type(tracker_url: str) -> str:
        scheme = urllib.parse.urlparse(str(tracker_url)).scheme.lower()
        if scheme == "udp":
            return "UDP"
        if scheme == "https":
            return "HTTPS"
        if scheme == "http":
            return "HTTP"
        return scheme.upper() if scheme else "Unknown"

    def _ensure_source_record(self, tracker_url: str) -> dict:
        tracker_url = str(tracker_url)
        record = self._source_records.get(tracker_url)
        if record is not None:
            return record

        record = {
            "id": f"tracker:{tracker_url}",
            "source": tracker_url,
            "type": self._tracker_type(tracker_url),
            "status": "Waiting",
            "peers": 0,
            "seeders": None,
            "leechers": None,
            "interval": None,
            "response_ms": None,
            "last_error": "",
            "last_event": "",
            "query_count": 0,
            "last_attempt_at": 0.0,
            "last_update_at": 0.0,
            "last_success_at": 0.0,
        }
        self._source_records[tracker_url] = record
        return record

    def _begin_source_query(self, tracker_url: str, event: Optional[str]) -> float:
        now = time.monotonic()
        record = self._ensure_source_record(tracker_url)
        record["status"] = "Announcing"
        record["last_error"] = ""
        record["last_event"] = str(event or "update")
        record["query_count"] = int(record.get("query_count", 0)) + 1
        record["last_attempt_at"] = now
        return now

    def _finish_source_query(
        self,
        tracker_url: str,
        started_at: float,
        *,
        peers: Optional[List[Tuple[str, int]]] = None,
        metadata: Optional[dict] = None,
        status: Optional[str] = None,
        error: str = "",
    ):
        now = time.monotonic()
        record = self._ensure_source_record(tracker_url)
        metadata = metadata or {}

        peer_list = list(peers or [])
        if status is None:
            status = "Active" if peer_list else "No Peers"

        record["status"] = status
        record["peers"] = len(peer_list)
        record["response_ms"] = max(0.0, (now - started_at) * 1000.0)
        record["last_update_at"] = now
        record["last_error"] = str(error or metadata.get("warning") or "")

        if metadata.get("seeders") is not None:
            record["seeders"] = int(metadata["seeders"])
        if metadata.get("leechers") is not None:
            record["leechers"] = int(metadata["leechers"])
        if metadata.get("interval") is not None:
            record["interval"] = int(metadata["interval"])

        if status in {"Active", "No Peers"}:
            record["last_success_at"] = now

    def get_source_snapshots(self) -> List[dict]:
        """Return immutable-ish tracker telemetry dictionaries for the UI."""
        now = time.monotonic()
        snapshots: List[dict] = []

        # Preserve the torrent's announce-list order in the table.
        for tracker_url in self.torrent.announce_list:
            record = self._ensure_source_record(tracker_url)
            last_update_at = float(record.get("last_update_at", 0.0) or 0.0)
            last_success_at = float(record.get("last_success_at", 0.0) or 0.0)

            snapshot = dict(record)
            snapshot["last_update_seconds"] = (
                max(0.0, now - last_update_at) if last_update_at else None
            )
            snapshot["last_success_seconds"] = (
                max(0.0, now - last_success_at) if last_success_at else None
            )
            snapshots.append(snapshot)

        return snapshots

    async def fetch_peers(
        self,
        uploaded: int = 0,
        downloaded: int = 0,
        left: Optional[int] = None,
        event: Optional[str] = "started",
    ) -> List[Tuple[str, int]]:
        if left is None:
            left = self.torrent.total_length

        all_peers: List[Tuple[str, int]] = []

        for tracker_url in self.torrent.announce_list:
            peers: List[Tuple[str, int]] = []
            metadata: dict = {}
            started_at = self._begin_source_query(tracker_url, event)

            try:
                if tracker_url.startswith(("http://", "https://")):
                    peers, metadata = await self._query_http_tracker(
                        tracker_url,
                        uploaded,
                        downloaded,
                        left,
                        event,
                    )
                elif tracker_url.startswith("udp://"):
                    peers, metadata = await self._query_udp_tracker(
                        tracker_url,
                        uploaded,
                        downloaded,
                        left,
                        event,
                    )
                else:
                    self._finish_source_query(
                        tracker_url,
                        started_at,
                        status="Unsupported",
                        error="Unsupported tracker URL scheme",
                    )
                    continue

                self._finish_source_query(
                    tracker_url,
                    started_at,
                    peers=peers,
                    metadata=metadata,
                )

                if peers:
                    print(f"[{tracker_url}] Found {len(peers)} peers")
                    all_peers.extend(peers)
                    # Preserve SalixTorrent's existing fallback behaviour: stop
                    # after the first tracker that actually supplies peers.
                    break

            except asyncio.CancelledError:
                self._finish_source_query(
                    tracker_url,
                    started_at,
                    status="Cancelled",
                    error="Announce cancelled",
                )
                raise
            except (asyncio.TimeoutError, TimeoutError, socket.timeout) as exc:
                self._finish_source_query(
                    tracker_url,
                    started_at,
                    status="Timeout",
                    error=str(exc) or "Tracker timed out",
                )
                continue
            except Exception as exc:
                self._finish_source_query(
                    tracker_url,
                    started_at,
                    status="Error",
                    error=str(exc) or exc.__class__.__name__,
                )
                continue

        # Preserve order while removing duplicate endpoints.
        return list(dict.fromkeys(all_peers))

    async def announce(
        self,
        uploaded: int = 0,
        downloaded: int = 0,
        left: Optional[int] = None,
        event: Optional[str] = None,
    ) -> List[Tuple[str, int]]:
        """Alias used by the seeding lifecycle for periodic announces."""
        return await self.fetch_peers(
            uploaded=uploaded,
            downloaded=downloaded,
            left=left,
            event=event,
        )

    async def _query_http_tracker(
        self,
        tracker_url: str,
        uploaded: int,
        downloaded: int,
        left: int,
        event: Optional[str],
    ) -> Tuple[List[Tuple[str, int]], dict]:
        params = [
            ("info_hash", urllib.parse.quote_from_bytes(self.torrent.info_hash, safe="")),
            ("peer_id", urllib.parse.quote_from_bytes(self.peer_id, safe="")),
            ("port", str(self.port)),
            ("uploaded", str(max(0, int(uploaded)))),
            ("downloaded", str(max(0, int(downloaded)))),
            ("left", str(max(0, int(left)))),
            ("compact", "1"),
        ]
        if event:
            params.append(("event", event))

        # info_hash and peer_id are already percent encoded binary strings, so
        # build the query manually rather than letting urlencode escape '%' a
        # second time.
        query = "&".join(f"{key}={value}" for key, value in params)
        separator = "&" if "?" in tracker_url else "?"
        full_url = f"{tracker_url}{separator}{query}"

        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(full_url) as response:
                if response.status != 200:
                    raise TrackerQueryError(f"HTTP {response.status}")
                response_data = await response.read()

        decoded = Bencode.decode(response_data)
        if not isinstance(decoded, dict):
            raise TrackerQueryError("Malformed tracker response")

        failure_reason = decoded.get(b"failure reason")
        if failure_reason:
            if isinstance(failure_reason, bytes):
                failure_reason = failure_reason.decode("utf-8", errors="replace")
            raise TrackerQueryError(str(failure_reason))

        warning = decoded.get(b"warning message", b"")
        if isinstance(warning, bytes):
            warning = warning.decode("utf-8", errors="replace")

        metadata = {
            "interval": decoded.get(b"interval"),
            "seeders": decoded.get(b"complete"),
            "leechers": decoded.get(b"incomplete"),
            "warning": str(warning or ""),
        }
        return self._parse_peers(decoded.get(b"peers", b"")), metadata

    async def _query_udp_tracker(
        self,
        tracker_url: str,
        uploaded: int,
        downloaded: int,
        left: int,
        event: Optional[str],
    ) -> Tuple[List[Tuple[str, int]], dict]:
        # The BEP 0015 socket calls are blocking. Keep them off the asyncio
        # engine thread so Pause/Stop/Resume remain responsive.
        return await asyncio.to_thread(
            self._query_udp_tracker_blocking,
            tracker_url,
            uploaded,
            downloaded,
            left,
            event,
        )

    def _query_udp_tracker_blocking(
        self,
        tracker_url: str,
        uploaded: int,
        downloaded: int,
        left: int,
        event: Optional[str],
    ) -> Tuple[List[Tuple[str, int]], dict]:
        parsed = urllib.parse.urlparse(tracker_url)
        host = parsed.hostname
        port = parsed.port or 80

        if not host:
            raise TrackerQueryError("Tracker host is missing")

        event_code = {
            None: 0,
            "completed": 1,
            "started": 2,
            "stopped": 3,
        }.get(event, 0)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5.0)

        try:
            conn_id = 0x41727101980
            transaction_id = random.randint(0, 0x7FFFFFFF)
            packet = struct.pack(">QII", conn_id, 0, transaction_id)

            sock.sendto(packet, (host, port))
            response, _ = sock.recvfrom(2048)

            if len(response) < 8:
                raise TrackerQueryError("Short UDP connect response")

            res_action, res_trans_id = struct.unpack(">II", response[:8])
            if res_action == 3:
                message = response[8:].decode("utf-8", errors="replace")
                raise TrackerQueryError(message or "UDP tracker error")
            if len(response) < 16:
                raise TrackerQueryError("Short UDP connect response")

            res_action, res_trans_id, connection_id = struct.unpack(
                ">IIQ", response[:16]
            )
            if res_trans_id != transaction_id or res_action != 0:
                raise TrackerQueryError("Invalid UDP connect response")

            transaction_id = random.randint(0, 0x7FFFFFFF)
            key = random.randint(0, 0xFFFFFFFF)
            num_want = 50

            announce_packet = struct.pack(
                ">QII20s20sQQQIIIiH",
                connection_id,
                1,
                transaction_id,
                self.torrent.info_hash,
                self.peer_id,
                max(0, int(downloaded)),
                max(0, int(left)),
                max(0, int(uploaded)),
                event_code,
                0,
                key,
                num_want,
                self.port,
            )

            sock.sendto(announce_packet, (host, port))
            response, _ = sock.recvfrom(2048)

            if len(response) < 8:
                raise TrackerQueryError("Short UDP announce response")

            res_action, res_trans_id = struct.unpack(">II", response[:8])
            if res_action == 3:
                message = response[8:].decode("utf-8", errors="replace")
                raise TrackerQueryError(message or "UDP tracker error")
            if len(response) < 20:
                raise TrackerQueryError("Short UDP announce response")

            res_action, res_trans_id, interval, leechers, seeders = struct.unpack(
                ">IIIII", response[:20]
            )
            if res_trans_id != transaction_id or res_action != 1:
                raise TrackerQueryError("Invalid UDP announce response")

            metadata = {
                "interval": interval,
                "seeders": seeders,
                "leechers": leechers,
                "warning": "",
            }
            return self._parse_peers(response[20:]), metadata

        finally:
            sock.close()

    def _parse_peers(self, raw_peers: Any) -> List[Tuple[str, int]]:
        peers: List[Tuple[str, int]] = []

        if isinstance(raw_peers, (bytes, bytearray)):
            num_peers = len(raw_peers) // 6
            for i in range(num_peers):
                offset = i * 6
                ip = socket.inet_ntoa(raw_peers[offset:offset + 4])
                port = struct.unpack(">H", raw_peers[offset + 4:offset + 6])[0]
                peers.append((ip, port))

        elif isinstance(raw_peers, list):
            for peer in raw_peers:
                if isinstance(peer, dict) and b"ip" in peer and b"port" in peer:
                    ip_value = peer[b"ip"]
                    if isinstance(ip_value, bytes):
                        ip = ip_value.decode("utf-8", errors="ignore")
                    else:
                        ip = str(ip_value)
                    port = int(peer[b"port"])
                    peers.append((ip, port))

        return peers
