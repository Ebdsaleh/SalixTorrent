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
from app.logic.network_binding import ip_family, normalise_bind_address
from app.logic.peer import (
    PEER_ENCRYPTION_DISABLED,
    PEER_ENCRYPTION_REQUIRE,
    normalise_peer_encryption_policy,
)


class TrackerQueryError(RuntimeError):
    """Raised for a tracker response that completed but was not usable."""


class TrackerClient:
    """Handles HTTP, HTTPS, and UDP announces for a torrent session.

    The client also keeps lightweight per-tracker telemetry for the Sources
    detail view. The telemetry records only tracker protocol activity; it does
    not fabricate peer counts for trackers that have not actually replied.
    """

    def __init__(
        self,
        torrent: TorrentFile,
        peer_id: bytes,
        port: int = 6881,
        *,
        bind_address: str = "",
        encryption_policy: str = "Prefer Encryption",
    ):
        self.torrent = torrent
        self.peer_id = peer_id
        self.port = port
        self.bind_address = normalise_bind_address(bind_address)
        self.encryption_policy = normalise_peer_encryption_policy(encryption_policy)
        # BEP-7 recommends a stable per-session key so IPv4/IPv6 announces
        # from the same client can be correlated without changing peer_id.
        self._tracker_key = random.getrandbits(32)

        self._source_records: Dict[str, dict] = {}
        for tracker_url in self.torrent.announce_list:
            self._ensure_source_record(tracker_url)

    def set_bind_address(self, bind_address: str):
        self.bind_address = normalise_bind_address(bind_address)

    def set_encryption_policy(self, encryption_policy: str):
        self.encryption_policy = normalise_peer_encryption_policy(encryption_policy)

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
            "ipv4_peers": 0,
            "ipv6_peers": 0,
            "announce_families": [],
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
        if metadata.get("ipv4_peers") is not None:
            record["ipv4_peers"] = max(0, int(metadata.get("ipv4_peers") or 0))
        if metadata.get("ipv6_peers") is not None:
            record["ipv6_peers"] = max(0, int(metadata.get("ipv6_peers") or 0))
        if metadata.get("announce_families") is not None:
            record["announce_families"] = list(dict.fromkeys(
                str(value) for value in metadata.get("announce_families", []) if value
            ))

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
            ("key", str(self._tracker_key)),
        ]
        if self.encryption_policy != PEER_ENCRYPTION_DISABLED:
            params.append(("supportcrypto", "1"))
        if self.encryption_policy == PEER_ENCRYPTION_REQUIRE:
            params.append(("requirecrypto", "1"))
        if event:
            params.append(("event", event))

        query = "&".join(f"{key}={value}" for key, value in params)
        separator = "&" if "?" in tracker_url else "?"
        full_url = f"{tracker_url}{separator}{query}"
        parsed = urllib.parse.urlparse(tracker_url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        if not host:
            raise TrackerQueryError("Tracker host is missing")

        bind_family = ip_family(self.bind_address) if self.bind_address else socket.AF_UNSPEC
        families: List[int] = []
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, port, family=bind_family, type=socket.SOCK_STREAM
            )
        except OSError as exc:
            raise TrackerQueryError(f"Could not resolve HTTP tracker: {exc}") from exc
        for family, _socktype, _proto, _canonname, _sockaddr in infos:
            if family in {socket.AF_INET, socket.AF_INET6} and family not in families:
                families.append(family)
        if not families:
            raise TrackerQueryError("HTTP tracker has no usable IPv4/IPv6 address")

        async def query_family(family: int):
            timeout = aiohttp.ClientTimeout(total=8)
            connector_kwargs = {"family": family}
            if self.bind_address:
                if ip_family(self.bind_address) != family:
                    raise TrackerQueryError("Selected network bind address does not match tracker family")
                connector_kwargs["local_addr"] = (self.bind_address, 0)
            connector = aiohttp.TCPConnector(**connector_kwargs)
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.get(full_url) as response:
                    if response.status != 200:
                        raise TrackerQueryError(f"HTTP {response.status}")
                    response_data = await response.read()
            return family, self._decode_http_tracker_response(response_data)

        # BEP-7 recommends announcing over each usable address family. Run the
        # at-most-two requests concurrently so dual-stack support does not add
        # serial tracker latency. A specific bind naturally constrains this to
        # one family.
        results = await asyncio.gather(
            *(query_family(family) for family in families),
            return_exceptions=True,
        )
        successes = [result for result in results if not isinstance(result, Exception)]
        if not successes:
            error = next((result for result in results if isinstance(result, Exception)), None)
            if isinstance(error, BaseException):
                raise error
            raise TrackerQueryError("HTTP tracker did not respond")

        peers: List[Tuple[str, int]] = []
        metadata: dict = {}
        warnings: List[str] = []
        announce_families: List[str] = []
        for family, (family_peers, family_meta) in successes:
            peers.extend(family_peers)
            announce_families.append("IPv6" if family == socket.AF_INET6 else "IPv4")
            for key in ("interval", "seeders", "leechers"):
                if metadata.get(key) is None and family_meta.get(key) is not None:
                    metadata[key] = family_meta.get(key)
            warning = str(family_meta.get("warning") or "").strip()
            if warning and warning not in warnings:
                warnings.append(warning)

        peers = list(dict.fromkeys(peers))
        metadata.update({
            "warning": " | ".join(warnings),
            "ipv4_peers": sum(1 for host, _port in peers if ip_family(host) == socket.AF_INET),
            "ipv6_peers": sum(1 for host, _port in peers if ip_family(host) == socket.AF_INET6),
            "announce_families": announce_families,
        })
        return peers, metadata

    def _decode_http_tracker_response(self, response_data: bytes) -> Tuple[List[Tuple[str, int]], dict]:
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

        peers4 = self._parse_compact_peers(decoded.get(b"peers", b""), socket.AF_INET)
        peers6 = self._parse_compact_peers(decoded.get(b"peers6", b""), socket.AF_INET6)
        if isinstance(decoded.get(b"peers"), list):
            peers4 = self._parse_peer_dicts(decoded.get(b"peers"))

        peers = list(dict.fromkeys(peers4 + peers6))
        return peers, {
            "interval": decoded.get(b"interval"),
            "seeders": decoded.get(b"complete"),
            "leechers": decoded.get(b"incomplete"),
            "warning": str(warning or ""),
            "ipv4_peers": sum(1 for host, _port in peers if ip_family(host) == socket.AF_INET),
            "ipv6_peers": sum(1 for host, _port in peers if ip_family(host) == socket.AF_INET6),
        }

    async def _query_udp_tracker(
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

        bind_family = ip_family(self.bind_address) if self.bind_address else socket.AF_UNSPEC
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, port, family=bind_family, type=socket.SOCK_DGRAM, proto=socket.IPPROTO_UDP
            )
        except OSError as exc:
            raise TrackerQueryError(f"Could not resolve UDP tracker: {exc}") from exc
        candidates = self._normalise_udp_candidates(infos)
        if not candidates:
            raise TrackerQueryError("UDP tracker has no usable IPv4/IPv6 address")

        groups: Dict[int, list] = {}
        for candidate in candidates:
            groups.setdefault(candidate[0], []).append(candidate)

        # BEP-7 dual-stack announcing is at most one worker per address family.
        # Each worker handles same-family DNS failover internally; the two
        # families run concurrently instead of doubling tracker latency.
        results = await asyncio.gather(
            *(
                asyncio.to_thread(
                    self._query_udp_candidates_blocking,
                    family_candidates,
                    uploaded, downloaded, left, event,
                )
                for family_candidates in groups.values()
            ),
            return_exceptions=True,
        )
        successes = [result for result in results if not isinstance(result, Exception)]
        if not successes:
            error = next((result for result in results if isinstance(result, Exception)), None)
            if isinstance(error, BaseException):
                raise error
            raise TrackerQueryError("UDP tracker did not respond")

        peers: List[Tuple[str, int]] = []
        metadata: dict = {}
        warnings: List[str] = []
        announce_families: List[str] = []
        for family, family_peers, family_meta in successes:
            peers.extend(family_peers)
            announce_families.append("IPv6" if family == socket.AF_INET6 else "IPv4")
            for key in ("interval", "seeders", "leechers"):
                if metadata.get(key) is None and family_meta.get(key) is not None:
                    metadata[key] = family_meta.get(key)
            warning = str(family_meta.get("warning") or "").strip()
            if warning and warning not in warnings:
                warnings.append(warning)

        peers = list(dict.fromkeys(peers))
        metadata.update({
            "warning": " | ".join(warnings),
            "ipv4_peers": sum(1 for host, _port in peers if ip_family(host) == socket.AF_INET),
            "ipv6_peers": sum(1 for host, _port in peers if ip_family(host) == socket.AF_INET6),
            "announce_families": announce_families,
        })
        return peers, metadata

    @staticmethod
    def _normalise_udp_candidates(infos) -> List[tuple]:
        candidates = []
        seen = set()
        for family, socktype, proto, _canonname, sockaddr in infos:
            if family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            key = (family, str(sockaddr[0]), int(sockaddr[1]))
            if key in seen:
                continue
            seen.add(key)
            candidates.append((family, socktype, proto, sockaddr))
        return candidates

    def _query_udp_tracker_blocking(
        self,
        tracker_url: str,
        uploaded: int,
        downloaded: int,
        left: int,
        event: Optional[str],
    ) -> Tuple[List[Tuple[str, int]], dict]:
        """Compatibility synchronous path used by focused tests/older callers."""
        parsed = urllib.parse.urlparse(tracker_url)
        host = parsed.hostname
        port = parsed.port or 80
        if not host:
            raise TrackerQueryError("Tracker host is missing")

        bind_family = ip_family(self.bind_address) if self.bind_address else socket.AF_UNSPEC
        try:
            infos = socket.getaddrinfo(
                host, port, bind_family, socket.SOCK_DGRAM, socket.IPPROTO_UDP
            )
        except OSError as exc:
            raise TrackerQueryError(f"Could not resolve UDP tracker: {exc}") from exc
        candidates = self._normalise_udp_candidates(infos)
        if not candidates:
            raise TrackerQueryError("UDP tracker has no usable IPv4/IPv6 address")
        _family, peers, metadata = self._query_udp_candidates_blocking(
            candidates, uploaded, downloaded, left, event
        )
        return peers, metadata

    def _query_udp_candidates_blocking(
        self,
        candidates,
        uploaded: int,
        downloaded: int,
        left: int,
        event: Optional[str],
    ):
        last_error: Optional[BaseException] = None
        for family, socktype, proto, sockaddr in candidates:
            try:
                peers, metadata = self._query_udp_tracker_endpoint(
                    family, socktype, proto, sockaddr, uploaded, downloaded, left, event
                )
                return family, peers, metadata
            except (OSError, socket.timeout, TrackerQueryError) as exc:
                last_error = exc
                continue
        if isinstance(last_error, TrackerQueryError):
            raise last_error
        raise TrackerQueryError(str(last_error or "UDP tracker did not respond"))

    def _query_udp_tracker_endpoint(
        self,
        family: int,
        socktype: int,
        proto: int,
        sockaddr,
        uploaded: int,
        downloaded: int,
        left: int,
        event: Optional[str],
    ) -> Tuple[List[Tuple[str, int]], dict]:
        event_code = {
            None: 0,
            "completed": 1,
            "started": 2,
            "stopped": 3,
        }.get(event, 0)

        sock = socket.socket(family, socktype, proto)
        sock.settimeout(5.0)
        if self.bind_address:
            if ip_family(self.bind_address) != family:
                sock.close()
                raise TrackerQueryError("Selected network bind address does not match tracker family")
            bind_endpoint = (self.bind_address, 0, 0, 0) if family == socket.AF_INET6 else (self.bind_address, 0)
            sock.bind(bind_endpoint)

        try:
            conn_id = 0x41727101980
            transaction_id = random.randint(0, 0x7FFFFFFF)
            packet = struct.pack(">QII", conn_id, 0, transaction_id)

            sock.sendto(packet, sockaddr)
            response, _ = sock.recvfrom(4096)
            if len(response) < 8:
                raise TrackerQueryError("Short UDP connect response")

            res_action, res_trans_id = struct.unpack(">II", response[:8])
            if res_action == 3:
                message = response[8:].decode("utf-8", errors="replace")
                raise TrackerQueryError(message or "UDP tracker error")
            if len(response) < 16:
                raise TrackerQueryError("Short UDP connect response")

            res_action, res_trans_id, connection_id = struct.unpack(">IIQ", response[:16])
            if res_trans_id != transaction_id or res_action != 0:
                raise TrackerQueryError("Invalid UDP connect response")

            transaction_id = random.randint(0, 0x7FFFFFFF)
            key = self._tracker_key
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

            sock.sendto(announce_packet, sockaddr)
            response, _ = sock.recvfrom(64 * 1024)
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

            peers = self._parse_compact_peers(response[20:], family)
            metadata = {
                "interval": interval,
                "seeders": seeders,
                "leechers": leechers,
                "warning": "",
                "ipv4_peers": len(peers) if family == socket.AF_INET else 0,
                "ipv6_peers": len(peers) if family == socket.AF_INET6 else 0,
            }
            return peers, metadata
        finally:
            sock.close()

    @staticmethod
    def _parse_compact_peers(raw_peers: Any, family: int) -> List[Tuple[str, int]]:
        if not isinstance(raw_peers, (bytes, bytearray)):
            return []
        data = bytes(raw_peers)
        width = 18 if family == socket.AF_INET6 else 6
        addr_size = 16 if family == socket.AF_INET6 else 4
        peers: List[Tuple[str, int]] = []
        for offset in range(0, len(data) - (width - 1), width):
            chunk = data[offset:offset + width]
            try:
                ip = socket.inet_ntop(family, chunk[:addr_size])
                port = struct.unpack(">H", chunk[addr_size:width])[0]
            except (OSError, struct.error):
                continue
            if port:
                peers.append((ip, port))
        return peers

    @staticmethod
    def _parse_peer_dicts(raw_peers: Any) -> List[Tuple[str, int]]:
        peers: List[Tuple[str, int]] = []
        if not isinstance(raw_peers, list):
            return peers
        for peer in raw_peers:
            if not isinstance(peer, dict) or b"ip" not in peer or b"port" not in peer:
                continue
            ip_value = peer[b"ip"]
            ip = (
                ip_value.decode("utf-8", errors="ignore")
                if isinstance(ip_value, bytes)
                else str(ip_value)
            )
            try:
                port = int(peer[b"port"])
            except (TypeError, ValueError):
                continue
            if ip_family(ip) in {socket.AF_INET, socket.AF_INET6} and 0 < port <= 65535:
                peers.append((ip, port))
        return peers

    def _parse_peers(self, raw_peers: Any) -> List[Tuple[str, int]]:
        """Backward-compatible IPv4 compact/dictionary parser."""
        if isinstance(raw_peers, list):
            return self._parse_peer_dicts(raw_peers)
        return self._parse_compact_peers(raw_peers, socket.AF_INET)

