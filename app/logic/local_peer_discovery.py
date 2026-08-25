# app/logic/local_peer_discovery.py

from __future__ import annotations

import asyncio
import socket
import struct
import time
from typing import List, Optional, Set, Tuple


LPD_MULTICAST_GROUP = "239.192.152.143"
LPD_PORT = 6771
LPD_ANNOUNCE_INTERVAL = 10.0


class _LocalPeerDiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, owner: "LocalPeerDiscovery"):
        self.owner = owner

    def datagram_received(self, data: bytes, addr):
        self.owner._handle_datagram(data, addr)

    def error_received(self, exc):
        # LPD is deliberately best-effort. Tracker/DHT-style discovery can
        # continue even if a platform/firewall rejects a multicast datagram.
        self.owner.last_error = str(exc)


class LocalPeerDiscovery:
    """Small BEP-14 compatible Local Peer Discovery helper.

    Each torrent session joins the standard IPv4 multicast group and listens
    for BT-SEARCH announcements containing the same info hash. Seeders publish
    their real TCP listen port; download-only sessions advertise port 0 so they
    can listen for local seeds without pretending to accept inbound peers.

    The implementation is intentionally self-contained and dependency-free.
    Failure to create/join the multicast socket is non-fatal.
    """

    def __init__(self, info_hash: bytes, announce_interval: float = LPD_ANNOUNCE_INTERVAL):
        self.info_hash = bytes(info_hash)
        self.info_hash_hex = self.info_hash.hex().upper()
        self.announce_interval = max(2.0, float(announce_interval))

        self.listen_port: int = 0
        self.transport: Optional[asyncio.DatagramTransport] = None
        self.protocol: Optional[_LocalPeerDiscoveryProtocol] = None
        self._announce_task: Optional[asyncio.Task] = None
        self._peer_queue: asyncio.Queue[Tuple[str, int]] = asyncio.Queue()
        self._seen: Set[Tuple[str, int]] = set()
        self.enabled: bool = False
        self.last_error: str = ""
        self._closed: bool = False
        self._last_query_response: float = 0.0

    @staticmethod
    def _make_socket() -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # SO_REUSEPORT improves coexistence on Unix. On Windows it may not be
        # available or may have different semantics, so it is best-effort only.
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass

        sock.bind(("", LPD_PORT))

        membership = socket.inet_aton(LPD_MULTICAST_GROUP) + socket.inet_aton("0.0.0.0")
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        sock.setblocking(False)
        return sock

    async def start(self, listen_port: int = 0) -> bool:
        self.listen_port = max(0, min(65535, int(listen_port or 0)))
        if self.transport is not None:
            self.enabled = True
            return True

        self._closed = False
        loop = asyncio.get_running_loop()
        try:
            sock = self._make_socket()
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: _LocalPeerDiscoveryProtocol(self),
                sock=sock,
            )
        except (OSError, RuntimeError) as exc:
            self.last_error = str(exc)
            self.enabled = False
            return False

        self.transport = transport
        self.protocol = protocol
        self.enabled = True
        self.last_error = ""
        self.announce()
        self._announce_task = asyncio.create_task(self._announce_loop())
        return True

    def update_listen_port(self, listen_port: int):
        self.listen_port = max(0, min(65535, int(listen_port or 0)))
        if self.enabled:
            self.announce()

    def _build_announcement(self) -> bytes:
        # BEP-14 uses an HTTP-like UDP datagram. Infohash is conventionally a
        # 40-character hexadecimal SHA-1 string.
        return (
            "BT-SEARCH * HTTP/1.1\r\n"
            f"Host: {LPD_MULTICAST_GROUP}:{LPD_PORT}\r\n"
            f"Port: {self.listen_port}\r\n"
            f"Infohash: {self.info_hash_hex}\r\n"
            "\r\n"
        ).encode("ascii")

    def announce(self):
        if not self.transport or self._closed:
            return
        try:
            self.transport.sendto(
                self._build_announcement(),
                (LPD_MULTICAST_GROUP, LPD_PORT),
            )
        except (OSError, RuntimeError) as exc:
            self.last_error = str(exc)

    async def _announce_loop(self):
        try:
            while not self._closed:
                await asyncio.sleep(self.announce_interval)
                self.announce()
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _parse_headers(data: bytes) -> dict:
        try:
            text = data.decode("ascii", errors="ignore")
        except Exception:
            return {}

        lines = text.replace("\r\n", "\n").split("\n")
        if not lines or lines[0].strip().upper() != "BT-SEARCH * HTTP/1.1":
            return {}

        headers = {}
        for line in lines[1:]:
            if not line.strip():
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        return headers

    def _handle_datagram(self, data: bytes, addr):
        headers = self._parse_headers(data)
        if not headers:
            return

        remote_hash = str(headers.get("infohash") or "").strip().upper()
        if remote_hash != self.info_hash_hex:
            return

        try:
            remote_port = int(headers.get("port", "0"))
        except (TypeError, ValueError):
            return

        # SalixTorrent download-only sessions advertise Port: 0 as a local
        # discovery query. A matching seeder answers once, which makes a LAN
        # transfer begin immediately instead of waiting for the next periodic
        # multicast announcement. Only port-0 queries trigger this response, so
        # two seeders cannot get stuck echoing announcements at each other.
        if remote_port == 0:
            now = time.monotonic()
            if self.listen_port > 0 and now - self._last_query_response >= 1.0:
                self._last_query_response = now
                self.announce()
            return

        if remote_port < 0 or remote_port > 65535:
            return

        remote_ip = str(addr[0])
        endpoint = (remote_ip, remote_port)

        # Ignore our own looped-back multicast announcement. Separate local
        # SalixTorrent processes use different TCP listen ports, so they are
        # still discoverable even when they share the same host address.
        if remote_port == self.listen_port and self.listen_port > 0:
            return

        if endpoint in self._seen:
            return
        self._seen.add(endpoint)

        try:
            self._peer_queue.put_nowait(endpoint)
        except asyncio.QueueFull:
            pass

    def drain_peers(self) -> List[Tuple[str, int]]:
        peers: List[Tuple[str, int]] = []
        while True:
            try:
                peers.append(self._peer_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return peers

    async def close(self):
        self._closed = True
        self.enabled = False

        if self._announce_task and not self._announce_task.done():
            self._announce_task.cancel()
            await asyncio.gather(self._announce_task, return_exceptions=True)
        self._announce_task = None

        if self.transport:
            self.transport.close()
            self.transport = None
        self.protocol = None
