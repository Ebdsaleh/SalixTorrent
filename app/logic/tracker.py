# app/logic/tracker.py

import asyncio
import random
import socket
import struct
import urllib.parse
from typing import Any, List, Optional, Tuple

import aiohttp

from app.logic.bencode import Bencode
from app.logic.torrent_file import TorrentFile


class TrackerClient:
    """Handles HTTP, HTTPS, and UDP announces for a torrent session."""

    def __init__(self, torrent: TorrentFile, peer_id: bytes, port: int = 6881):
        self.torrent = torrent
        self.peer_id = peer_id
        self.port = port

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

            try:
                if tracker_url.startswith(("http://", "https://")):
                    peers = await self._query_http_tracker(
                        tracker_url,
                        uploaded,
                        downloaded,
                        left,
                        event,
                    )
                elif tracker_url.startswith("udp://"):
                    peers = await self._query_udp_tracker(
                        tracker_url,
                        uploaded,
                        downloaded,
                        left,
                        event,
                    )

                if peers:
                    print(f"[{tracker_url}] Found {len(peers)} peers")
                    all_peers.extend(peers)
                    break

            except asyncio.CancelledError:
                raise
            except Exception:
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
    ) -> List[Tuple[str, int]]:
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
                    return []
                response_data = await response.read()

        decoded = Bencode.decode(response_data)
        if not isinstance(decoded, dict):
            return []

        return self._parse_peers(decoded.get(b"peers", b""))

    async def _query_udp_tracker(
        self,
        tracker_url: str,
        uploaded: int,
        downloaded: int,
        left: int,
        event: Optional[str],
    ) -> List[Tuple[str, int]]:
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
    ) -> List[Tuple[str, int]]:
        parsed = urllib.parse.urlparse(tracker_url)
        host = parsed.hostname
        port = parsed.port or 80

        if not host:
            return []

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

            if len(response) < 16:
                return []

            res_action, res_trans_id, connection_id = struct.unpack(
                ">IIQ", response[:16]
            )
            if res_trans_id != transaction_id or res_action != 0:
                return []

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

            if len(response) < 20:
                return []

            res_action, res_trans_id, _interval, _leechers, _seeders = struct.unpack(
                ">IIIII", response[:20]
            )
            if res_trans_id != transaction_id or res_action != 1:
                return []

            return self._parse_peers(response[20:])

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
                    ip = peer[b"ip"].decode("utf-8", errors="ignore")
                    port = int(peer[b"port"])
                    peers.append((ip, port))

        return peers
