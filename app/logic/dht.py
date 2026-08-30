# app/logic/dht.py

from __future__ import annotations

import asyncio
import hashlib
import heapq
import ipaddress
import secrets
import socket
import struct
import time
from typing import Dict, List, Optional, Set, Tuple

from app.logic.bencode import Bencode
from app.logic.network_binding import default_route_address, ip_family, normalise_bind_address, wildcard_for_family


DHT_BOOTSTRAP_NODES = (
    ("router.bittorrent.com", 6881),
    ("router.utorrent.com", 6881),
    ("dht.transmissionbt.com", 6881),
)
DHT_QUERY_TIMEOUT = 2.5
DHT_REFRESH_INTERVAL = 5 * 60
DHT_MAX_QUERIES = 64
DHT_BATCH_SIZE = 8


class _DHTProtocol(asyncio.DatagramProtocol):
    def __init__(self, owner: "DHTClient", family: int):
        self.owner = owner
        self.family = family

    def datagram_received(self, data: bytes, addr):
        self.owner._handle_datagram(data, addr, self.family)

    def error_received(self, exc):
        self.owner.last_error = str(exc)


class DHTClient:
    """Compact dual-stack BEP-5/BEP-32 DHT peer-discovery client.

    IPv4 and IPv6 are separate DHT address spaces, so an unbound SalixTorrent
    session owns at most one UDP socket per family. Both sockets share the same
    transaction table and iterative scheduler; there is no per-family polling
    loop. A specific Network Interface / VPN address constrains DHT to that
    address family, matching the application's fail-closed binding semantics.
    """

    def __init__(
        self,
        info_hash: bytes,
        *,
        private: bool = False,
        bootstrap_nodes: Optional[Tuple[Tuple[str, int], ...]] = None,
        preferred_port: int = 0,
        bind_address: str = "",
    ):
        self.info_hash = bytes(info_hash)
        if len(self.info_hash) != 20:
            raise ValueError("DHT info hash must be exactly 20 bytes.")

        self.private = bool(private)
        try:
            requested_port = int(preferred_port or 0)
        except (TypeError, ValueError):
            requested_port = 0
        self.preferred_port = requested_port if 0 < requested_port <= 65535 else 0
        self.bind_address = normalise_bind_address(bind_address)
        self.bootstrap_nodes = tuple(bootstrap_nodes or DHT_BOOTSTRAP_NODES)
        self.node_id = secrets.token_bytes(20)
        self._token_secret = secrets.token_bytes(20)

        self._transports: Dict[int, asyncio.DatagramTransport] = {}
        self._protocols: Dict[int, _DHTProtocol] = {}
        # Compatibility aliases retained for existing code/tests. Prefer IPv4
        # when both are active, otherwise expose the available family.
        self.transport: Optional[asyncio.DatagramTransport] = None
        self.protocol: Optional[_DHTProtocol] = None
        self.local_udp_port: int = 0
        self.local_udp_port_v4: int = 0
        self.local_udp_port_v6: int = 0
        self.announce_port: int = 0
        self.enabled: bool = False
        self._closed: bool = False

        self._pending: Dict[bytes, asyncio.Future] = {}
        self._transaction_counter: int = secrets.randbelow(65536)
        self._announced_peer_queue: asyncio.Queue[Tuple[str, int]] = asyncio.Queue()
        self._announced_seen: Set[Tuple[str, int]] = set()
        self._extra_bootstrap: Set[Tuple[str, int]] = set()

        self.status: str = "Disabled" if self.private else "Waiting"
        self.last_error: str = ""
        self.started_at: float = 0.0
        self.last_attempt_at: float = 0.0
        self.last_update_at: float = 0.0
        self.last_success_at: float = 0.0
        self.last_response_ms: Optional[float] = None
        self.query_count: int = 0
        self.nodes_queried: int = 0
        self.nodes_responded: int = 0
        self.nodes_queried_v4: int = 0
        self.nodes_queried_v6: int = 0
        self.nodes_responded_v4: int = 0
        self.nodes_responded_v6: int = 0
        self.announce_count: int = 0
        self.peers_seen: Set[Tuple[str, int]] = set()
        self.peers_seen_v4: Set[Tuple[str, int]] = set()
        self.peers_seen_v6: Set[Tuple[str, int]] = set()

    # ------------------------------------------------------------------
    # Socket lifecycle / KRPC framing
    # ------------------------------------------------------------------

    def _desired_families(self) -> Tuple[int, ...]:
        if self.bind_address:
            family = ip_family(self.bind_address)
            return (family,) if family in {socket.AF_INET, socket.AF_INET6} else ()
        return (socket.AF_INET, socket.AF_INET6)

    def _make_udp_socket(self, family: int, port: int) -> socket.socket:
        sock = socket.socket(family, socket.SOCK_DGRAM)
        try:
            if family == socket.AF_INET6 and hasattr(socket, "IPV6_V6ONLY"):
                # Keep IPv4 and IPv6 as explicit independent sockets even on
                # platforms where an IPv6 wildcard would otherwise absorb v4.
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            if self.bind_address:
                host = self.bind_address
            elif family == socket.AF_INET6:
                # BEP-32 recommends a stable concrete global-unicast source
                # rather than ::, especially on multi-homed hosts. If the OS
                # has no routable IPv6 source, skip IPv6 DHT while preserving
                # the IPv4 DHT instead of opening a misleading wildcard socket.
                host = default_route_address(socket.AF_INET6)
                if not host:
                    raise OSError("No routable IPv6 source address is available for BEP-32 DHT")
            else:
                host = wildcard_for_family(family)
            endpoint = (host, port, 0, 0) if family == socket.AF_INET6 else (host, port)
            sock.bind(endpoint)
            sock.setblocking(False)
            return sock
        except Exception:
            sock.close()
            raise

    async def _start_family(self, family: int) -> bool:
        if family in self._transports:
            return True
        loop = asyncio.get_running_loop()
        last_error: Optional[BaseException] = None
        for requested_port in (self.preferred_port, 0):
            # Avoid making two identical port=0 attempts.
            if requested_port == 0 and self.preferred_port == 0 and last_error is not None:
                break
            try:
                sock = self._make_udp_socket(family, requested_port)
                transport, protocol = await loop.create_datagram_endpoint(
                    lambda: _DHTProtocol(self, family),
                    sock=sock,
                )
            except (OSError, RuntimeError) as exc:
                last_error = exc
                continue
            self._transports[family] = transport
            self._protocols[family] = protocol
            sockname = transport.get_extra_info("sockname")
            port = int(sockname[1]) if isinstance(sockname, tuple) and len(sockname) >= 2 else 0
            if family == socket.AF_INET6:
                self.local_udp_port_v6 = port
            else:
                self.local_udp_port_v4 = port
            return True
        if self.bind_address and ip_family(self.bind_address) == family and last_error:
            self.last_error = str(last_error)
        return False

    def _refresh_compat_aliases(self):
        family = socket.AF_INET if socket.AF_INET in self._transports else socket.AF_INET6
        self.transport = self._transports.get(family)
        self.protocol = self._protocols.get(family)
        self.local_udp_port = (
            self.local_udp_port_v4 or self.local_udp_port_v6
        )

    async def start(self, announce_port: int = 0) -> bool:
        self.announce_port = max(0, min(65535, int(announce_port or 0)))
        if self.private:
            self.enabled = False
            self.status = "Disabled"
            self.last_error = "Private torrent: DHT disabled"
            return False

        desired = self._desired_families()
        if self._transports and all(family in self._transports for family in desired):
            self.enabled = True
            return True

        self._closed = False
        started = []
        for family in desired:
            try:
                if await self._start_family(family):
                    started.append(family)
            except OSError as exc:
                self.last_error = str(exc)

        self._refresh_compat_aliases()
        if not started and not self._transports:
            self.enabled = False
            self.status = "Error"
            self.last_error = self.last_error or "Could not open an IPv4 or IPv6 DHT socket"
            return False

        self.enabled = True
        self.status = "Waiting"
        self.last_error = ""
        self.started_at = time.monotonic()
        return True

    def update_announce_port(self, announce_port: int):
        self.announce_port = max(0, min(65535, int(announce_port or 0)))

    def set_bind_address(self, bind_address: str):
        self.bind_address = normalise_bind_address(bind_address)

    def set_preferred_port(self, preferred_port: int):
        try:
            port = int(preferred_port or 0)
        except (TypeError, ValueError):
            port = 0
        self.preferred_port = port if 0 < port <= 65535 else 0

    def _next_transaction_id(self) -> bytes:
        for _ in range(65536):
            self._transaction_counter = (self._transaction_counter + 1) & 0xFFFF
            tid = struct.pack(">H", self._transaction_counter)
            if tid not in self._pending:
                return tid
        return secrets.token_bytes(2)

    def _send(self, payload: dict, endpoint: Tuple[str, int]):
        if self._closed:
            raise RuntimeError("DHT socket is not active.")
        family = ip_family(endpoint[0])
        transport = self._transports.get(family)
        if transport is None:
            raise RuntimeError(
                "IPv6 DHT socket is not active."
                if family == socket.AF_INET6
                else "IPv4 DHT socket is not active."
            )
        transport.sendto(Bencode.encode(payload), endpoint)

    async def _query(
        self,
        endpoint: Tuple[str, int],
        query_name: bytes,
        arguments: dict,
        timeout: float = DHT_QUERY_TIMEOUT,
    ) -> dict:
        family = ip_family(endpoint[0])
        if family not in self._transports:
            raise RuntimeError("DHT socket for endpoint family is not active.")

        tid = self._next_transaction_id()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[tid] = future
        started = time.monotonic()
        self.query_count += 1
        try:
            self._send(
                {b"t": tid, b"y": b"q", b"q": bytes(query_name), b"a": arguments},
                endpoint,
            )
            response = await asyncio.wait_for(future, timeout=timeout)
            self.last_response_ms = max(0.0, (time.monotonic() - started) * 1000.0)
            return response
        finally:
            self._pending.pop(tid, None)

    def _handle_datagram(self, data: bytes, addr, family: int):
        try:
            message = Bencode.decode(data)
        except Exception:
            return
        if not isinstance(message, dict):
            return

        transaction = message.get(b"t")
        message_type = message.get(b"y")
        if message_type in (b"r", b"e") and isinstance(transaction, bytes):
            future = self._pending.get(transaction)
            if future is not None and not future.done():
                if message_type == b"r":
                    result = message.get(b"r")
                    future.set_result(result if isinstance(result, dict) else {})
                else:
                    error = message.get(b"e")
                    future.set_exception(RuntimeError(f"DHT error response: {error!r}"))
            return

        if message_type == b"q" and isinstance(transaction, bytes):
            self._handle_query(message, addr, transaction, family)

    # ------------------------------------------------------------------
    # Minimal server-side KRPC participation
    # ------------------------------------------------------------------

    def _token_for_ip(self, ip: str) -> bytes:
        return hashlib.sha1(self._token_secret + str(ip).encode("utf-8")).digest()[:8]

    def _reply(self, transaction: bytes, endpoint, result: dict):
        try:
            self._send({b"t": transaction, b"y": b"r", b"r": result}, endpoint)
        except Exception:
            pass

    def _handle_query(self, message: dict, addr, transaction: bytes, family: int):
        query_name = message.get(b"q")
        arguments = message.get(b"a")
        if not isinstance(arguments, dict):
            arguments = {}

        endpoint = (str(addr[0]), int(addr[1]))
        base = {b"id": self.node_id}
        if query_name == b"ping":
            self._reply(transaction, endpoint, base)
            return

        def add_requested_node_sets(result: dict):
            want = arguments.get(b"want")
            if isinstance(want, list):
                if b"n4" in want:
                    result[b"nodes"] = b""
                if b"n6" in want:
                    result[b"nodes6"] = b""
                return
            # BEP-32 default: reply with the node form matching the transport
            # family when no explicit want list is present.
            if family == socket.AF_INET6:
                result[b"nodes6"] = b""
            else:
                result[b"nodes"] = b""

        if query_name == b"find_node":
            add_requested_node_sets(base)
            self._reply(transaction, endpoint, base)
            return
        if query_name == b"get_peers":
            base[b"token"] = self._token_for_ip(endpoint[0])
            add_requested_node_sets(base)
            self._reply(transaction, endpoint, base)
            return
        if query_name == b"announce_peer":
            token = arguments.get(b"token")
            if token != self._token_for_ip(endpoint[0]):
                return
            implied = int(arguments.get(b"implied_port", 0) or 0)
            try:
                peer_port = endpoint[1] if implied else int(arguments.get(b"port", 0) or 0)
            except (TypeError, ValueError):
                peer_port = 0
            remote_hash = arguments.get(b"info_hash")
            if remote_hash == self.info_hash and 0 < peer_port <= 65535:
                peer_endpoint = (endpoint[0], peer_port)
                if peer_endpoint not in self._announced_seen:
                    self._announced_seen.add(peer_endpoint)
                    try:
                        self._announced_peer_queue.put_nowait(peer_endpoint)
                    except asyncio.QueueFull:
                        pass
            self._reply(transaction, endpoint, base)

    # ------------------------------------------------------------------
    # Compact peer/node helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_compact_peers(values, family: int = socket.AF_INET) -> List[Tuple[str, int]]:
        """Parse BEP-5/BEP-32 peer values, including legal hybrid lists.

        BEP-32 requires receivers to accept a ``values`` list containing an
        arbitrary mixture of 6-byte IPv4 and 18-byte IPv6 entries. The family
        argument is therefore only a fallback for non-standard concatenated
        blobs; exact entry lengths always determine their own address family.
        """
        peers: List[Tuple[str, int]] = []
        if isinstance(values, (bytes, bytearray)):
            values = [bytes(values)]
        if not isinstance(values, list):
            return peers

        for value in values:
            if not isinstance(value, (bytes, bytearray)):
                continue
            raw = bytes(value)
            if len(raw) == 6:
                chunks = [(socket.AF_INET, raw)]
            elif len(raw) == 18:
                chunks = [(socket.AF_INET6, raw)]
            else:
                width = 18 if family == socket.AF_INET6 else 6
                if not raw or len(raw) % width:
                    continue
                chunks = [(family, raw[offset:offset + width]) for offset in range(0, len(raw), width)]

            for chunk_family, chunk in chunks:
                address_size = 16 if chunk_family == socket.AF_INET6 else 4
                try:
                    ip = socket.inet_ntop(chunk_family, chunk[:address_size])
                    port = struct.unpack(">H", chunk[address_size:])[0]
                except (OSError, struct.error):
                    continue
                if port:
                    peers.append((ip, port))
        return peers

    @staticmethod
    def _parse_compact_nodes(raw_nodes, family: int = socket.AF_INET) -> List[Tuple[bytes, str, int]]:
        nodes: List[Tuple[bytes, str, int]] = []
        if not isinstance(raw_nodes, (bytes, bytearray)):
            return nodes
        raw = bytes(raw_nodes)
        width = 38 if family == socket.AF_INET6 else 26
        address_size = 16 if family == socket.AF_INET6 else 4
        for offset in range(0, len(raw) - (width - 1), width):
            chunk = raw[offset:offset + width]
            node_id = chunk[:20]
            try:
                ip = socket.inet_ntop(family, chunk[20:20 + address_size])
                port = struct.unpack(">H", chunk[20 + address_size:width])[0]
            except (OSError, struct.error):
                continue
            if port:
                nodes.append((node_id, ip, port))
        return nodes

    @staticmethod
    def _xor_distance(left: bytes, right: bytes) -> int:
        return int.from_bytes(left, "big") ^ int.from_bytes(right, "big")

    def add_known_node(self, endpoint: Tuple[str, int]):
        if self.private:
            return
        try:
            ip = str(endpoint[0]).strip()
            port = int(endpoint[1])
        except (TypeError, ValueError, IndexError):
            return
        if ip_family(ip) not in {socket.AF_INET, socket.AF_INET6} or not (0 < port <= 65535):
            return
        # Ignore a family that cannot be used under a specific source bind.
        if self.bind_address and ip_family(ip) != ip_family(self.bind_address):
            return
        self._extra_bootstrap.add((ip, port))

    async def _resolve_bootstrap(self) -> List[Tuple[str, int]]:
        loop = asyncio.get_running_loop()
        endpoints: List[Tuple[str, int]] = []
        seen: Set[Tuple[str, int]] = set()
        active_families = set(self._transports)

        for endpoint in sorted(self._extra_bootstrap):
            if ip_family(endpoint[0]) in active_families and endpoint not in seen:
                seen.add(endpoint)
                endpoints.append(endpoint)

        resolve_family = ip_family(self.bind_address) if self.bind_address else socket.AF_UNSPEC
        for host, port in self.bootstrap_nodes:
            try:
                infos = await loop.getaddrinfo(
                    host,
                    port,
                    family=resolve_family,
                    type=socket.SOCK_DGRAM,
                )
            except OSError:
                continue
            for info in infos:
                family = info[0]
                if family not in active_families:
                    continue
                sockaddr = info[4]
                endpoint = (str(sockaddr[0]), int(sockaddr[1]))
                if endpoint not in seen:
                    seen.add(endpoint)
                    endpoints.append(endpoint)
        return endpoints

    async def _get_peers_from_node(self, endpoint: Tuple[str, int]):
        started = time.monotonic()
        response = await self._query(
            endpoint,
            b"get_peers",
            {
                b"id": self.node_id,
                b"info_hash": self.info_hash,
                # BEP-32 steady-state guidance prefers requesting node data
                # for the same family as the queried DHT. The separately
                # bootstrapped sockets already cover both address spaces.
                b"want": [b"n6"] if ip_family(endpoint[0]) == socket.AF_INET6 else [b"n4"],
            },
        )
        elapsed_ms = max(0.0, (time.monotonic() - started) * 1000.0)
        return endpoint, response, elapsed_ms

    async def _announce_to_node(self, endpoint: Tuple[str, int], token: bytes):
        if not self.announce_port or not token:
            return
        try:
            await self._query(
                endpoint,
                b"announce_peer",
                {
                    b"id": self.node_id,
                    b"info_hash": self.info_hash,
                    b"port": self.announce_port,
                    b"token": bytes(token),
                    b"implied_port": 0,
                },
                timeout=DHT_QUERY_TIMEOUT,
            )
            self.announce_count += 1
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public peer discovery API
    # ------------------------------------------------------------------

    async def discover_peers(self, announce_port: Optional[int] = None) -> List[Tuple[str, int]]:
        if announce_port is not None:
            self.update_announce_port(announce_port)
        if self.private:
            self.status = "Disabled"
            self.last_error = "Private torrent: DHT disabled"
            return []
        if not await self.start(self.announce_port):
            return []

        self.status = "Announcing"
        self.last_error = ""
        self.last_attempt_at = time.monotonic()
        self.nodes_queried = 0
        self.nodes_responded = 0
        self.nodes_queried_v4 = 0
        self.nodes_queried_v6 = 0
        self.nodes_responded_v4 = 0
        self.nodes_responded_v6 = 0

        bootstrap = await self._resolve_bootstrap()
        if not bootstrap:
            self.status = "Error"
            self.last_error = "Could not resolve any IPv4/IPv6 DHT bootstrap node"
            self.last_update_at = time.monotonic()
            return []

        candidates: List[Tuple[int, int, Tuple[str, int]]] = []
        queued: Set[Tuple[str, int]] = set()
        queried: Set[Tuple[str, int]] = set()
        tie_breaker = 0
        for endpoint in bootstrap:
            heapq.heappush(candidates, ((1 << 160) - 1, tie_breaker, endpoint))
            tie_breaker += 1
            queued.add(endpoint)

        found_peers: Set[Tuple[str, int]] = set()
        announce_jobs: List[asyncio.Task] = []
        response_latencies: List[float] = []

        while candidates and len(queried) < DHT_MAX_QUERIES:
            batch: List[Tuple[str, int]] = []
            while candidates and len(batch) < DHT_BATCH_SIZE and len(queried) < DHT_MAX_QUERIES:
                _, _, endpoint = heapq.heappop(candidates)
                if endpoint in queried:
                    continue
                queried.add(endpoint)
                batch.append(endpoint)
            if not batch:
                break

            self.nodes_queried += len(batch)
            for endpoint in batch:
                if ip_family(endpoint[0]) == socket.AF_INET6:
                    self.nodes_queried_v6 += 1
                else:
                    self.nodes_queried_v4 += 1

            results = await asyncio.gather(
                *(self._get_peers_from_node(endpoint) for endpoint in batch),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    continue
                endpoint, response, elapsed_ms = result
                family = ip_family(endpoint[0])
                self.nodes_responded += 1
                if family == socket.AF_INET6:
                    self.nodes_responded_v6 += 1
                else:
                    self.nodes_responded_v4 += 1
                response_latencies.append(elapsed_ms)

                for peer_endpoint in self._parse_compact_peers(response.get(b"values"), family):
                    try:
                        ipaddress.ip_address(peer_endpoint[0])
                    except ValueError:
                        continue
                    found_peers.add(peer_endpoint)
                    self.peers_seen.add(peer_endpoint)
                    if ip_family(peer_endpoint[0]) == socket.AF_INET6:
                        self.peers_seen_v6.add(peer_endpoint)
                    else:
                        self.peers_seen_v4.add(peer_endpoint)

                token = response.get(b"token")
                if self.announce_port and isinstance(token, bytes) and token:
                    announce_jobs.append(asyncio.create_task(self._announce_to_node(endpoint, token)))

                for node_family, key in (
                    (socket.AF_INET, b"nodes"),
                    (socket.AF_INET6, b"nodes6"),
                ):
                    if node_family not in self._transports:
                        continue
                    for node_id, ip, port in self._parse_compact_nodes(response.get(key), node_family):
                        node_endpoint = (ip, port)
                        if node_endpoint in queued or node_endpoint in queried:
                            continue
                        queued.add(node_endpoint)
                        distance = self._xor_distance(node_id, self.info_hash)
                        heapq.heappush(candidates, (distance, tie_breaker, node_endpoint))
                        tie_breaker += 1

            if found_peers and self.nodes_queried >= 24:
                break

        if announce_jobs:
            await asyncio.gather(*announce_jobs, return_exceptions=True)
        found_peers.update(self.drain_peers())

        now = time.monotonic()
        self.last_update_at = now
        if response_latencies:
            self.last_response_ms = response_latencies[-1]
        if self.nodes_responded:
            self.last_success_at = now
            self.status = "Active" if found_peers else "No Peers"
            self.last_error = ""
        else:
            self.status = "Error"
            self.last_error = "No IPv4/IPv6 DHT nodes responded"
        return sorted(found_peers)

    def drain_peers(self) -> List[Tuple[str, int]]:
        peers: List[Tuple[str, int]] = []
        while True:
            try:
                endpoint = self._announced_peer_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            peers.append(endpoint)
            self.peers_seen.add(endpoint)
            if ip_family(endpoint[0]) == socket.AF_INET6:
                self.peers_seen_v6.add(endpoint)
            else:
                self.peers_seen_v4.add(endpoint)
        return peers

    def get_source_snapshot(self) -> dict:
        now = time.monotonic()
        last_update = self.last_update_at or self.last_attempt_at
        if self.private:
            detail = "Private torrent: BEP-5/BEP-32 disabled"
        else:
            v4 = f"IPv4 UDP {self.local_udp_port_v4 or '--'} nodes {self.nodes_responded_v4}/{self.nodes_queried_v4}"
            v6 = f"IPv6 UDP {self.local_udp_port_v6 or '--'} nodes {self.nodes_responded_v6}/{self.nodes_queried_v6}"
            detail = f"BEP-5/BEP-32 | {v4} | {v6} | announces {self.announce_count}"
        return {
            "id": "dht",
            "source": "Distributed Hash Table",
            "type": "DHT",
            "status": self.status,
            "peers": len(self.peers_seen),
            "ipv4_peers": len(self.peers_seen_v4),
            "ipv6_peers": len(self.peers_seen_v6),
            "seeders": None,
            "leechers": None,
            "interval": DHT_REFRESH_INTERVAL,
            "response_ms": self.last_response_ms,
            "last_error": str(self.last_error or ""),
            "last_event": "get_peers",
            "query_count": int(self.query_count),
            "last_update_seconds": max(0.0, now - last_update) if last_update else None,
            "last_success_seconds": max(0.0, now - self.last_success_at) if self.last_success_at else None,
            "detail": detail,
        }

    async def close(self):
        self._closed = True
        self.enabled = False
        for future in list(self._pending.values()):
            if not future.done():
                future.cancel()
        self._pending.clear()
        for transport in list(self._transports.values()):
            transport.close()
        self._transports.clear()
        self._protocols.clear()
        self.transport = None
        self.protocol = None
        self.local_udp_port = 0
        self.local_udp_port_v4 = 0
        self.local_udp_port_v6 = 0
        if not self.private:
            self.status = "Disabled"
