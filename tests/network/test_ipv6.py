import asyncio
import hashlib
import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web

from app.logic.bencode import Bencode
from app.logic.connectivity import ConnectivityManager
from app.logic.dht import DHTClient
from app.logic.local_peer_discovery import LocalPeerDiscovery
from app.logic.network_binding import (
    format_endpoint,
    ip_family,
    mask_ip_for_display,
    normalise_bind_address,
)
from app.logic.peer import (
    PEER_ENCRYPTION_DISABLED,
    PeerConnection,
    build_reserved_bytes,
    encode_pex_payload,
    parse_pex_payload,
)
from app.logic.session import SessionState, TorrentSession
from app.logic.tracker import TrackerClient


PEER_ID_A = b"-STV6TS-123456789012"
PEER_ID_B = b"-STV6TS-210987654321"
INFO_HASH = hashlib.sha1(b"salix-ipv6-test").digest()


def _ipv6_available() -> bool:
    if not socket.has_ipv6:
        return False
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        sock.bind(("::1", 0))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _bt_handshake(info_hash: bytes, peer_id: bytes) -> bytes:
    return (
        b"\x13BitTorrent protocol"
        + build_reserved_bytes(enable_extensions=True, enable_dht=True)
        + info_hash
        + peer_id
    )


def _write_torrent(path: Path) -> None:
    payload = b"phase-five-ipv6-payload"
    info = {
        b"name": b"ipv6.bin",
        b"piece length": 16 * 1024,
        b"pieces": hashlib.sha1(payload).digest(),
        b"length": len(payload),
    }
    path.write_bytes(Bencode.encode({b"info": info}))


def _free_ipv6_port() -> int:
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        sock.bind(("::1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


class TestIPv6Helpers(unittest.TestCase):
    def test_ipv6_binding_endpoint_and_masking_helpers(self):
        self.assertEqual(normalise_bind_address("2001:0db8::0001"), "2001:db8::1")
        self.assertEqual(ip_family("2001:db8::1"), socket.AF_INET6)
        self.assertEqual(format_endpoint("2001:db8::1", 6881), "[2001:db8::1]:6881")
        self.assertEqual(format_endpoint("192.0.2.10", 6881), "192.0.2.10:6881")
        masked = mask_ip_for_display("2001:db8:abcd:1234::5")
        self.assertNotEqual(masked, "2001:db8:abcd:1234::5")
        self.assertIn(":", masked)

    def test_pex_round_trips_ipv4_and_ipv6_endpoints(self):
        endpoints = [("192.0.2.4", 6881), ("2001:db8::7", 6882)]
        payload = encode_pex_payload(endpoints)
        decoded = Bencode.decode(payload)
        self.assertIn(b"added", decoded)
        self.assertIn(b"added6", decoded)
        self.assertEqual(len(decoded[b"added"]), 6)
        self.assertEqual(len(decoded[b"added6"]), 18)
        parsed = parse_pex_payload(payload)
        self.assertEqual(set(parsed["added"]), set(endpoints))


@unittest.skipUnless(_ipv6_available(), "IPv6 loopback is not available")
class TestIPv6PeerTCP(unittest.IsolatedAsyncioTestCase):
    async def test_outgoing_peer_tcp_uses_explicit_ipv6_source_bind(self):
        accepted = asyncio.Event()

        async def handle(reader, writer):
            try:
                request = await asyncio.wait_for(reader.readexactly(68), 2.0)
                self.assertEqual(request[28:48], INFO_HASH)
                writer.write(_bt_handshake(INFO_HASH, PEER_ID_B))
                await writer.drain()
                accepted.set()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handle, host="::1", port=0, family=socket.AF_INET6)
        port = int(server.sockets[0].getsockname()[1])
        peer = PeerConnection(
            "::1",
            port,
            INFO_HASH,
            PEER_ID_A,
            encryption_policy=PEER_ENCRYPTION_DISABLED,
            bind_address="::1",
        )
        try:
            self.assertTrue(await peer.connect(timeout=2.0))
            self.assertTrue(await asyncio.wait_for(accepted.wait(), 2.0))
            sockname = peer.writer.get_extra_info("sockname")
            peername = peer.writer.get_extra_info("peername")
            self.assertEqual(sockname[0], "::1")
            self.assertEqual(peername[0], "::1")
        finally:
            await peer.close()
            server.close()
            await server.wait_closed()


@unittest.skipUnless(_ipv6_available(), "IPv6 loopback is not available")
class TestIPv6Trackers(unittest.IsolatedAsyncioTestCase):
    async def test_http_tracker_over_ipv6_consumes_peers6(self):
        compact6 = socket.inet_pton(socket.AF_INET6, "2001:db8::22") + struct.pack(">H", 51413)

        async def announce(_request):
            return web.Response(
                body=Bencode.encode({
                    b"interval": 120,
                    b"complete": 4,
                    b"incomplete": 2,
                    b"peers": b"",
                    b"peers6": compact6,
                }),
                content_type="application/octet-stream",
            )

        app = web.Application()
        app.router.add_get("/announce", announce)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "::1", 0)
        await site.start()
        port = int(site._server.sockets[0].getsockname()[1])

        torrent = SimpleNamespace(info_hash=INFO_HASH, announce_list=[])
        tracker = TrackerClient(torrent, PEER_ID_A, bind_address="::1")
        try:
            peers, meta = await tracker._query_http_tracker(
                f"http://[::1]:{port}/announce", 0, 0, 1, None
            )
            self.assertEqual(peers, [("2001:db8::22", 51413)])
            self.assertEqual(meta["ipv4_peers"], 0)
            self.assertEqual(meta["ipv6_peers"], 1)
            self.assertEqual(meta["announce_families"], ["IPv6"])
        finally:
            await runner.cleanup()

    async def test_udp_tracker_over_ipv6_returns_18_byte_compact_peers(self):
        server = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        server.bind(("::1", 0))
        server.settimeout(3.0)
        port = int(server.getsockname()[1])
        errors = []

        def tracker_server():
            try:
                data, addr = server.recvfrom(4096)
                _conn_id, action, tx = struct.unpack(">QII", data[:16])
                if action != 0:
                    raise AssertionError("expected connect action")
                connection_id = 0x123456789ABCDEF0
                server.sendto(struct.pack(">IIQ", 0, tx, connection_id), addr)

                data, addr = server.recvfrom(4096)
                action = struct.unpack(">I", data[8:12])[0]
                tx = struct.unpack(">I", data[12:16])[0]
                if action != 1:
                    raise AssertionError("expected announce action")
                compact = socket.inet_pton(socket.AF_INET6, "2001:db8::33") + struct.pack(">H", 6889)
                server.sendto(struct.pack(">IIIII", 1, tx, 180, 3, 7) + compact, addr)
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=tracker_server, daemon=True)
        thread.start()
        torrent = SimpleNamespace(info_hash=INFO_HASH, announce_list=[])
        tracker = TrackerClient(torrent, PEER_ID_A, bind_address="::1")
        try:
            peers, meta = await tracker._query_udp_tracker(
                f"udp://[::1]:{port}/announce",
                0,
                0,
                1,
                None,
            )
            thread.join(timeout=3.0)
            if errors:
                raise errors[0]
            self.assertEqual(peers, [("2001:db8::33", 6889)])
            self.assertEqual(meta["ipv6_peers"], 1)
            self.assertEqual(meta["ipv4_peers"], 0)
            self.assertEqual(meta["announce_families"], ["IPv6"])
        finally:
            server.close()


@unittest.skipUnless(_ipv6_available(), "IPv6 loopback is not available")
class TestIPv6DHT(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_ipv6_bind_opens_only_bep32_socket(self):
        dht = DHTClient(INFO_HASH, bind_address="::1", preferred_port=0)
        try:
            self.assertTrue(await dht.start())
            self.assertEqual(dht.local_udp_port_v4, 0)
            self.assertGreater(dht.local_udp_port_v6, 0)
            self.assertIn(socket.AF_INET6, dht._transports)
            self.assertNotIn(socket.AF_INET, dht._transports)
            source = dht.get_source_snapshot()
            self.assertIn("BEP-5/BEP-32", source["detail"])
        finally:
            await dht.close()

    async def test_bep32_query_replies_follow_transport_family_and_want(self):
        dht = DHTClient(INFO_HASH, bind_address="::1")
        replies = []
        dht._reply = lambda transaction, endpoint, result: replies.append(dict(result))

        dht._handle_query(
            {b"q": b"get_peers", b"a": {b"id": b"x" * 20, b"info_hash": INFO_HASH}},
            ("::1", 6881, 0, 0),
            b"aa",
            socket.AF_INET6,
        )
        self.assertIn(b"nodes6", replies[-1])
        self.assertNotIn(b"nodes", replies[-1])

        dht._handle_query(
            {b"q": b"find_node", b"a": {b"id": b"x" * 20, b"target": INFO_HASH, b"want": [b"n4", b"n6"]}},
            ("::1", 6881, 0, 0),
            b"ab",
            socket.AF_INET6,
        )
        self.assertIn(b"nodes", replies[-1])
        self.assertIn(b"nodes6", replies[-1])

    async def test_bep32_compact_nodes_values_and_want(self):
        peer_raw = socket.inet_pton(socket.AF_INET6, "2001:db8::44") + struct.pack(">H", 6999)
        node_id = b"n" * 20
        node_raw = node_id + socket.inet_pton(socket.AF_INET6, "2001:db8::55") + struct.pack(">H", 7000)
        peer4_raw = socket.inet_pton(socket.AF_INET, "192.0.2.44") + struct.pack(">H", 6998)
        self.assertEqual(
            DHTClient._parse_compact_peers([peer4_raw, peer_raw], socket.AF_INET6),
            [("192.0.2.44", 6998), ("2001:db8::44", 6999)],
        )
        self.assertEqual(
            DHTClient._parse_compact_nodes(node_raw, socket.AF_INET6),
            [(node_id, "2001:db8::55", 7000)],
        )

        class CaptureDHT(DHTClient):
            async def _query(self, endpoint, query_name, arguments, timeout=0):
                self.captured = (endpoint, query_name, arguments)
                return {}

        dht = CaptureDHT(INFO_HASH, bind_address="::1")
        endpoint, response, _elapsed = await dht._get_peers_from_node(("::1", 6881))
        self.assertEqual(endpoint, ("::1", 6881))
        self.assertEqual(response, {})
        self.assertEqual(dht.captured[1], b"get_peers")
        self.assertEqual(dht.captured[2][b"want"], [b"n6"])


@unittest.skipUnless(_ipv6_available(), "IPv6 loopback is not available")
class TestIPv6SessionListener(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_ipv6_listener_accepts_real_peer_handshake(self):
        with tempfile.TemporaryDirectory() as tmp:
            torrent_path = Path(tmp) / "ipv6.torrent"
            _write_torrent(torrent_path)
            port = _free_ipv6_port()
            session = TorrentSession(
                str(torrent_path),
                download_dir=tmp,
                listen_port=port,
                enable_dht=False,
                enable_pex=False,
                enable_lan_discovery=False,
                encryption_policy=PEER_ENCRYPTION_DISABLED,
                network_bind_address="::1",
            )
            session._run_token = 1
            session.is_running = True
            session.state = SessionState.SEEDING
            try:
                await session._open_seed_server(1)
                self.assertIn(socket.AF_INET6, session._seed_servers)
                self.assertNotIn(socket.AF_INET, session._seed_servers)
                self.assertEqual(session._seed_listener_addresses[socket.AF_INET6], "::1")

                reader, writer = await asyncio.open_connection("::1", session._seed_port, family=socket.AF_INET6)
                writer.write(_bt_handshake(session.torrent.info_hash, PEER_ID_B))
                await writer.drain()
                response = await asyncio.wait_for(reader.readexactly(68), 2.0)
                self.assertEqual(response[28:48], session.torrent.info_hash)
                await asyncio.sleep(0.05)
                self.assertEqual(session.incoming_connections_total, 1)
                record = next(iter(session._inbound_peer_records.values()))
                self.assertEqual(record["ip_family"], "IPv6")
                self.assertTrue(record["address"].startswith("[::1]:"))
                writer.close()
                await writer.wait_closed()
            finally:
                session.is_running = False
                await session._close_seed_server()
                await session._dht.close()

    async def test_any_interface_uses_same_numeric_port_for_ipv4_and_ipv6(self):
        with tempfile.TemporaryDirectory() as tmp:
            torrent_path = Path(tmp) / "ipv6-any.torrent"
            _write_torrent(torrent_path)
            # Pick an IPv4 candidate; TorrentSession will fall forward if a race
            # claims it before the listeners open.
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
            probe.close()
            session = TorrentSession(
                str(torrent_path),
                download_dir=tmp,
                listen_port=port,
                enable_dht=False,
                enable_pex=False,
                enable_lan_discovery=False,
                encryption_policy=PEER_ENCRYPTION_DISABLED,
                network_bind_address="",
            )
            session._run_token = 1
            session.is_running = True
            session.state = SessionState.SEEDING
            try:
                await session._open_seed_server(1)
                self.assertIn(socket.AF_INET, session._seed_servers)
                self.assertIn(socket.AF_INET6, session._seed_servers)
                p4 = int(session._seed_servers[socket.AF_INET].sockets[0].getsockname()[1])
                p6 = int(session._seed_servers[socket.AF_INET6].sockets[0].getsockname()[1])
                self.assertEqual(p4, p6)
                self.assertEqual(p4, session._seed_port)
            finally:
                session.is_running = False
                await session._close_seed_server()
                await session._dht.close()


class _NoIPv4MappingForIPv6(ConnectivityManager):
    def _map_upnp(self, port, local_ip, *, map_udp):
        raise AssertionError("UPnP must not be called for an IPv6-only bind")

    def _map_natpmp(self, port, *, map_udp):
        raise AssertionError("NAT-PMP must not be called for an IPv6-only bind")


class TestIPv6BindingPolicy(unittest.IsolatedAsyncioTestCase):
    async def test_ipv6_connectivity_skips_ipv4_nat_mapping(self):
        manager = _NoIPv4MappingForIPv6()
        try:
            request = manager._request_for_port(
                {
                    "network_bind_address": "2001:db8::10",
                    "enable_upnp": True,
                    "enable_natpmp": True,
                    "enable_dht": True,
                },
                6881,
            )
            result, mapping = manager._perform_refresh(request)
            self.assertIsNone(mapping)
            self.assertEqual(result["status"], "IPv6 Direct")
            self.assertEqual(result["method"], "IPv6")
            self.assertEqual(result["upnp_status"], "Not applicable")
            self.assertEqual(result["natpmp_status"], "Not applicable")
            decorated = manager._decorate_guidance(result)
            self.assertIn("firewall", decorated["action_hint"].lower())
        finally:
            manager.close()

    async def test_lpd_fails_closed_under_explicit_ipv6_bind(self):
        lpd = LocalPeerDiscovery(INFO_HASH, bind_address="::1")
        try:
            self.assertFalse(await lpd.start(6881))
            self.assertFalse(lpd.enabled)
            self.assertIn("IPv4-only", lpd.last_error)
        finally:
            await lpd.close()


class TestUDPTrackerTimeoutClassification(unittest.IsolatedAsyncioTestCase):
    def _client(self):
        torrent = SimpleNamespace(
            announce_list=["udp://tracker.example:80/announce"],
            info_hash=INFO_HASH,
            total_length=1,
        )
        return TrackerClient(torrent, PEER_ID_A, port=6881)

    def test_candidate_failover_preserves_all_timeout_result(self):
        client = self._client()

        def timeout_endpoint(*_args, **_kwargs):
            raise socket.timeout("timed out")

        client._query_udp_tracker_endpoint = timeout_endpoint
        candidates = [
            (socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP, ("192.0.2.1", 80)),
            (socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP, ("192.0.2.2", 80)),
        ]
        with self.assertRaises(socket.timeout):
            client._query_udp_candidates_blocking(candidates, 0, 0, 1, "started")

    async def test_fetch_peers_classifies_udp_timeout_as_warning_state(self):
        client = self._client()

        async def timeout_query(*_args, **_kwargs):
            raise socket.timeout("timed out")

        client._query_udp_tracker = timeout_query
        peers = await client.fetch_peers(left=1, event="started")
        self.assertEqual(peers, [])
        snapshot = client.get_source_snapshots()[0]
        self.assertEqual(snapshot["status"], "Timeout")
        self.assertIn("timed out", snapshot["last_error"].lower())


if __name__ == "__main__":
    unittest.main()
