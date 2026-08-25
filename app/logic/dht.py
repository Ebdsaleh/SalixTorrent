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
    def __init__(self, owner: "DHTClient"):
        self.owner = owner

    def datagram_received(self, data: bytes, addr):
        self.owner._handle_datagram(data, addr)

    def error_received(self, exc):
        self.owner.last_error = str(exc)


class DHTClient:
    """Small dependency-free BEP-5 DHT peer discovery client.

    SalixTorrent does not try to be a full long-lived routing-table daemon yet.
    Instead each torrent session owns a compact iterative lookup engine:

    * bootstrap through well-known public DHT routers;
    * issue ``get_peers`` queries for the torrent info hash;
    * follow compact node lists returned by reachable nodes;
    * consume compact peer values returned by the DHT;
    * when a TCP listen port exists, use returned tokens to ``announce_peer``;
    * answer the basic KRPC queries required to behave politely as a DHT node.

    Private torrents disable this object entirely, as required by the private
    torrent convention.
    """

    def __init__(
        self,
        info_hash: bytes,
        *,
        private: bool = False,
        bootstrap_nodes: Optional[Tuple[Tuple[str, int], ...]] = None,
        preferred_port: int = 0,
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
        self.bootstrap_nodes = tuple(bootstrap_nodes or DHT_BOOTSTRAP_NODES)
        self.node_id = secrets.token_bytes(20)
        self._token_secret = secrets.token_bytes(20)

        self.transport: Optional[asyncio.DatagramTransport] = None
        self.protocol: Optional[_DHTProtocol] = None
        self.local_udp_port: int = 0
        self.announce_port: int = 0
        self.enabled: bool = False
        self._closed: bool = False

        self._pending: Dict[bytes, asyncio.Future] = {}
        self._transaction_counter: int = secrets.randbelow(65536)
        self._announced_peer_queue: asyncio.Queue[Tuple[str, int]] = asyncio.Queue()
        self._announced_seen: Set[Tuple[str, int]] = set()
        self._extra_bootstrap: Set[Tuple[str, int]] = set()

        # Sources-view telemetry.
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
        self.announce_count: int = 0
        self.peers_seen: Set[Tuple[str, int]] = set()

    # ------------------------------------------------------------------
    # Socket lifecycle / KRPC framing
    # ------------------------------------------------------------------

    async def start(self, announce_port: int = 0) -> bool:
        self.announce_port = max(0, min(65535, int(announce_port or 0)))
        if self.private:
            self.enabled = False
            self.status = "Disabled"
            self.last_error = "Private torrent: DHT disabled"
            return False

        if self.transport is not None:
            self.enabled = True
            return True

        self._closed = False
        loop = asyncio.get_running_loop()
        try:
            try:
                transport, protocol = await loop.create_datagram_endpoint(
                    lambda: _DHTProtocol(self),
                    local_addr=("0.0.0.0", self.preferred_port),
                    family=socket.AF_INET,
                )
            except OSError:
                # TCP and UDP may share the same numeric port. If another UDP
                # application already owns the configured port, keep DHT
                # functional by falling back to an ephemeral UDP port.
                transport, protocol = await loop.create_datagram_endpoint(
                    lambda: _DHTProtocol(self),
                    local_addr=("0.0.0.0", 0),
                    family=socket.AF_INET,
                )
        except (OSError, RuntimeError) as exc:
            self.enabled = False
            self.status = "Error"
            self.last_error = str(exc)
            return False

        self.transport = transport
        self.protocol = protocol
        sockname = transport.get_extra_info("sockname")
        if isinstance(sockname, tuple) and len(sockname) >= 2:
            try:
                self.local_udp_port = int(sockname[1])
            except (TypeError, ValueError):
                self.local_udp_port = 0

        self.enabled = True
        self.status = "Waiting"
        self.last_error = ""
        self.started_at = time.monotonic()
        return True

    def update_announce_port(self, announce_port: int):
        self.announce_port = max(0, min(65535, int(announce_port or 0)))

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
        if not self.transport or self._closed:
            raise RuntimeError("DHT socket is not active.")
        self.transport.sendto(Bencode.encode(payload), endpoint)

    async def _query(
        self,
        endpoint: Tuple[str, int],
        query_name: bytes,
        arguments: dict,
        timeout: float = DHT_QUERY_TIMEOUT,
    ) -> dict:
        if not self.transport:
            raise RuntimeError("DHT socket is not active.")

        tid = self._next_transaction_id()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[tid] = future
        started = time.monotonic()
        self.query_count += 1

        try:
            self._send(
                {
                    b"t": tid,
                    b"y": b"q",
                    b"q": bytes(query_name),
                    b"a": arguments,
                },
                endpoint,
            )
            response = await asyncio.wait_for(future, timeout=timeout)
            self.last_response_ms = max(0.0, (time.monotonic() - started) * 1000.0)
            return response
        finally:
            self._pending.pop(tid, None)

    def _handle_datagram(self, data: bytes, addr):
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
            self._handle_query(message, addr, transaction)

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

    def _handle_query(self, message: dict, addr, transaction: bytes):
        query_name = message.get(b"q")
        arguments = message.get(b"a")
        if not isinstance(arguments, dict):
            arguments = {}

        endpoint = (str(addr[0]), int(addr[1]))
        base = {b"id": self.node_id}

        if query_name == b"ping":
            self._reply(transaction, endpoint, base)
            return

        if query_name == b"find_node":
            base[b"nodes"] = b""
            self._reply(transaction, endpoint, base)
            return

        if query_name == b"get_peers":
            base[b"token"] = self._token_for_ip(endpoint[0])
            base[b"nodes"] = b""
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
            if (
                remote_hash == self.info_hash
                and 0 < peer_port <= 65535
            ):
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
    def _parse_compact_peers(values) -> List[Tuple[str, int]]:
        peers: List[Tuple[str, int]] = []
        if isinstance(values, (bytes, bytearray)):
            values = [bytes(values)]
        if not isinstance(values, list):
            return peers

        for value in values:
            if not isinstance(value, (bytes, bytearray)):
                continue
            raw = bytes(value)
            # BEP-5 values are normally one compact peer per list entry, but
            # tolerate implementations that concatenate multiple IPv4 peers.
            for offset in range(0, len(raw) - 5, 6):
                chunk = raw[offset:offset + 6]
                try:
                    ip = socket.inet_ntoa(chunk[:4])
                    port = struct.unpack(">H", chunk[4:])[0]
                except (OSError, struct.error):
                    continue
                if port:
                    peers.append((ip, port))
        return peers

    @staticmethod
    def _parse_compact_nodes(raw_nodes) -> List[Tuple[bytes, str, int]]:
        nodes: List[Tuple[bytes, str, int]] = []
        if not isinstance(raw_nodes, (bytes, bytearray)):
            return nodes
        raw = bytes(raw_nodes)
        for offset in range(0, len(raw) - 25, 26):
            chunk = raw[offset:offset + 26]
            node_id = chunk[:20]
            try:
                ip = socket.inet_ntoa(chunk[20:24])
                port = struct.unpack(">H", chunk[24:26])[0]
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
        if not ip or port <= 0 or port > 65535:
            return
        self._extra_bootstrap.add((ip, port))

    async def _resolve_bootstrap(self) -> List[Tuple[str, int]]:
        loop = asyncio.get_running_loop()
        endpoints: List[Tuple[str, int]] = []
        seen: Set[Tuple[str, int]] = set()

        for endpoint in sorted(self._extra_bootstrap):
            if endpoint not in seen:
                seen.add(endpoint)
                endpoints.append(endpoint)

        for host, port in self.bootstrap_nodes:
            try:
                infos = await loop.getaddrinfo(
                    host,
                    port,
                    family=socket.AF_INET,
                    type=socket.SOCK_DGRAM,
                )
            except OSError:
                continue

            for info in infos:
                sockaddr = info[4]
                endpoint = (str(sockaddr[0]), int(sockaddr[1]))
                if endpoint not in seen:
                    seen.add(endpoint)
                    endpoints.append(endpoint)
        return endpoints

    async def _get_peers_from_node(
        self,
        endpoint: Tuple[str, int],
    ) -> Tuple[Tuple[str, int], dict, float]:
        started = time.monotonic()
        response = await self._query(
            endpoint,
            b"get_peers",
            {b"id": self.node_id, b"info_hash": self.info_hash},
        )
        elapsed_ms = max(0.0, (time.monotonic() - started) * 1000.0)
        return endpoint, response, elapsed_ms

    async def _announce_to_node(
        self,
        endpoint: Tuple[str, int],
        token: bytes,
    ):
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
            # A failed announce does not invalidate a successful get_peers
            # response from the same node.
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

        bootstrap = await self._resolve_bootstrap()
        if not bootstrap:
            self.status = "Error"
            self.last_error = "Could not resolve any DHT bootstrap node"
            self.last_update_at = time.monotonic()
            return []

        # Priority queue entries are (distance, tie-breaker, endpoint). Bootstrap
        # nodes have no node ID yet, so they begin at maximum distance.
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
            results = await asyncio.gather(
                *(self._get_peers_from_node(endpoint) for endpoint in batch),
                return_exceptions=True,
            )

            for result in results:
                if isinstance(result, Exception):
                    continue

                endpoint, response, elapsed_ms = result
                self.nodes_responded += 1
                response_latencies.append(elapsed_ms)

                for peer_endpoint in self._parse_compact_peers(response.get(b"values")):
                    try:
                        ipaddress.ip_address(peer_endpoint[0])
                    except ValueError:
                        continue
                    found_peers.add(peer_endpoint)
                    self.peers_seen.add(peer_endpoint)

                token = response.get(b"token")
                if self.announce_port and isinstance(token, bytes) and token:
                    announce_jobs.append(
                        asyncio.create_task(self._announce_to_node(endpoint, token))
                    )

                for node_id, ip, port in self._parse_compact_nodes(response.get(b"nodes")):
                    node_endpoint = (ip, port)
                    if node_endpoint in queued or node_endpoint in queried:
                        continue
                    queued.add(node_endpoint)
                    distance = self._xor_distance(node_id, self.info_hash)
                    heapq.heappush(candidates, (distance, tie_breaker, node_endpoint))
                    tie_breaker += 1

            # Once peers have been found, a few extra batches improve diversity
            # without traversing the entire reachable DHT for every refresh.
            if found_peers and self.nodes_queried >= 24:
                break

        if announce_jobs:
            await asyncio.gather(*announce_jobs, return_exceptions=True)

        # Peers that directly announce to our minimal KRPC listener are valid
        # discoveries too.
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
            self.last_error = "No DHT nodes responded"

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
        return peers

    def get_source_snapshot(self) -> dict:
        now = time.monotonic()
        last_update = self.last_update_at or self.last_attempt_at
        return {
            "id": "dht",
            "source": "Distributed Hash Table",
            "type": "DHT",
            "status": self.status,
            "peers": len(self.peers_seen),
            "seeders": None,
            "leechers": None,
            "interval": DHT_REFRESH_INTERVAL,
            "response_ms": self.last_response_ms,
            "last_error": str(self.last_error or ""),
            "last_event": "get_peers",
            "query_count": int(self.query_count),
            "last_update_seconds": (
                max(0.0, now - last_update) if last_update else None
            ),
            "last_success_seconds": (
                max(0.0, now - self.last_success_at) if self.last_success_at else None
            ),
            "detail": (
                "Private torrent: BEP-5 disabled"
                if self.private
                else (
                    f"BEP-5 | nodes {self.nodes_responded}/{self.nodes_queried} | "
                    f"UDP {self.local_udp_port or '--'} | announces {self.announce_count}"
                )
            ),
        }

    async def close(self):
        self._closed = True
        self.enabled = False

        for future in list(self._pending.values()):
            if not future.done():
                future.cancel()
        self._pending.clear()

        if self.transport:
            self.transport.close()
            self.transport = None
        self.protocol = None
        self.local_udp_port = 0

        if not self.private:
            self.status = "Disabled"
