# app/logic/tracker.py

import asyncio
import socket
import struct
import random
import urllib.parse
from typing import List, Tuple, Optional, Any
import aiohttp
from app.logic.bencode import Bencode
from app.logic.torrent_file import TorrentFile


class TrackerClient:
    """Handles HTTP, HTTPS, and UDP announce queries to retrieve active swarm peers."""

    def __init__(self, torrent: TorrentFile, peer_id: bytes, port: int = 6881):
        self.torrent = torrent
        self.peer_id = peer_id
        self.port = port

    async def fetch_peers(
        self,
        uploaded: int = 0,
        downloaded: int = 0,
        left: Optional[int] = None
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
                    )
                elif tracker_url.startswith("udp://"):
                    peers = await self._query_udp_tracker(
                        tracker_url,
                        uploaded,
                        downloaded,
                        left,
                    )

                if peers:
                    print(f"[{tracker_url}] Found {len(peers)} peers")
                    all_peers.extend(peers)
                    break

            except asyncio.CancelledError:
                raise
            except Exception:
                # Silently advance to the next tracker tier.
                continue

        return list(set(all_peers))

    async def _query_http_tracker(
        self,
        tracker_url: str,
        uploaded: int,
        downloaded: int,
        left: int
    ) -> List[Tuple[str, int]]:
        params = {
            "info_hash": self.torrent.info_hash,
            "peer_id": self.peer_id,
            "port": self.port,
            "uploaded": uploaded,
            "downloaded": downloaded,
            "left": left,
            "compact": 1,
            "event": "started"
        }

        query_string = urllib.parse.urlencode(
            {k: v for k, v in params.items() if not isinstance(v, bytes)}
        )
        binary_query = (
            f"?info_hash={urllib.parse.quote(self.torrent.info_hash)}"
            f"&peer_id={urllib.parse.quote(self.peer_id)}&{query_string}"
        )

        full_url = tracker_url + binary_query

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
        left: int
    ) -> List[Tuple[str, int]]:
        """
        Run the existing BEP 0015 blocking UDP implementation in a worker
        thread so recvfrom() can never freeze Salix_T's asyncio engine.
        """
        return await asyncio.to_thread(
            self._query_udp_tracker_blocking,
            tracker_url,
            uploaded,
            downloaded,
            left,
        )

    def _query_udp_tracker_blocking(
        self,
        tracker_url: str,
        uploaded: int,
        downloaded: int,
        left: int
    ) -> List[Tuple[str, int]]:
        """Blocking BEP 0015 implementation.  Never call directly on asyncio."""
        parsed = urllib.parse.urlparse(tracker_url)
        host = parsed.hostname
        port = parsed.port or 80

        if not host:
            return []

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5.0)

        try:
            # 1. Connect Action (action = 0, magic connection_id = 0x41727101980)
            conn_id = 0x41727101980
            action = 0
            transaction_id = random.randint(0, 0x7FFFFFFF)
            packet = struct.pack(">QII", conn_id, action, transaction_id)

            sock.sendto(packet, (host, port))
            response, _ = sock.recvfrom(2048)

            if len(response) < 16:
                return []

            res_action, res_trans_id, connection_id = struct.unpack(
                ">IIQ",
                response[:16],
            )

            if res_trans_id != transaction_id or res_action != 0:
                return []

            # 2. Announce Action (action = 1)
            action = 1
            transaction_id = random.randint(0, 0x7FFFFFFF)
            key = random.randint(0, 0xFFFFFFFF)
            num_want = 50
            event = 2  # started

            announce_packet = struct.pack(
                ">QII20s20sQQQIIIiH",
                connection_id,
                action,
                transaction_id,
                self.torrent.info_hash,
                self.peer_id,
                downloaded,
                left,
                uploaded,
                event,
                0,  # IP address default
                key,
                num_want,
                self.port,
            )

            sock.sendto(announce_packet, (host, port))
            response, _ = sock.recvfrom(2048)

            if len(response) < 20:
                return []

            res_action, res_trans_id, interval, leechers, seeders = struct.unpack(
                ">IIIII",
                response[:20],
            )

            if res_trans_id != transaction_id or res_action != 1:
                return []

            raw_peers = response[20:]
            return self._parse_peers(raw_peers)

        finally:
            sock.close()

    def _parse_peers(self, raw_peers: Any) -> List[Tuple[str, int]]:
        peers: List[Tuple[str, int]] = []

        if isinstance(raw_peers, (bytes, bytearray)):
            num_peers = len(raw_peers) // 6

            for i in range(num_peers):
                offset = i * 6
                ip_bytes = raw_peers[offset:offset + 4]
                port_bytes = raw_peers[offset + 4:offset + 6]
                ip = socket.inet_ntoa(ip_bytes)
                port = struct.unpack(">H", port_bytes)[0]
                peers.append((ip, port))

        elif isinstance(raw_peers, list):
            for peer in raw_peers:
                if isinstance(peer, dict) and b"ip" in peer and b"port" in peer:
                    ip = peer[b"ip"].decode("utf-8")
                    port = int(peer[b"port"])
                    peers.append((ip, port))

        return peers
