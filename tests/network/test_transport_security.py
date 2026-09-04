import asyncio
import hashlib
import struct
import tempfile
import time
import unittest
from pathlib import Path

from aiohttp import web

from app.logic.bencode import Bencode
from app.logic.connectivity import ConnectivityManager, PortMappingFailure
from app.logic.dht import DHTClient
from app.logic.local_peer_discovery import LocalPeerDiscovery
from app.logic.mse import _RC4Context, mse_initiator_handshake, mse_responder_handshake
from app.logic.peer import (
    PEER_ENCRYPTION_DISABLED,
    PEER_ENCRYPTION_PREFER,
    PEER_ENCRYPTION_REQUIRE,
    PeerConnection,
    PeerMessageID,
    build_reserved_bytes,
)
from app.logic.session import SessionState, TorrentSession
from app.logic.torrent_file import TorrentFile
from app.logic.torrent_manager import TorrentManager
from app.logic.tracker import TrackerClient


PEER_ID_A = b"-STTEST-123456789012"
PEER_ID_B = b"-STTEST-210987654321"


def _write_torrent(path: Path) -> TorrentFile:
    payload = b"transport-security-test"
    info = {
        b"name": b"transport.bin",
        b"piece length": 16 * 1024,
        b"pieces": hashlib.sha1(payload).digest(),
        b"length": len(payload),
    }
    path.write_bytes(Bencode.encode({b"info": info}))
    return TorrentFile(str(path))


def _bt_handshake(info_hash: bytes, peer_id: bytes) -> bytes:
    return (
        b"\x13BitTorrent protocol"
        + build_reserved_bytes(enable_extensions=True, enable_dht=False)
        + bytes(info_hash)
        + bytes(peer_id)
    )


class _UploadPeerStub:
    def __init__(self):
        self.is_connected = True
        self.sent = []

    async def send_piece(self, piece_index, begin, data):
        self.sent.append((piece_index, begin, bytes(data)))
        return True


class _FakeConnectivityManager(ConnectivityManager):
    def __init__(self):
        self.removed_ports = []
        super().__init__()

    @staticmethod
    def _local_ip() -> str:
        return "127.0.0.1"

    def _map_upnp(self, port: int, local_ip: str, *, map_udp: bool):
        return {
            "method": "UPnP",
            "service_type": "test",
            "control_url": "http://127.0.0.1/test",
            "internal_port": port,
            "external_port": port,
            "external_ip": "198.51.100.10",
            "mapped_tcp": True,
            "mapped_udp": bool(map_udp),
        }

    def _remove_mapping(self, mapping):
        if mapping:
            self.removed_ports.append(int(mapping.get("internal_port") or 0))


class _RenewConnectivityManager(_FakeConnectivityManager):
    def __init__(self):
        self.map_calls = 0
        self.fail_mapping = False
        super().__init__()

    def _map_upnp(self, port: int, local_ip: str, *, map_udp: bool):
        self.map_calls += 1
        if self.fail_mapping:
            raise RuntimeError("temporary router failure")
        return super()._map_upnp(port, local_ip, map_udp=map_udp)


class _FallbackConnectivityManager(ConnectivityManager):
    @staticmethod
    def _local_ip() -> str:
        return "192.0.2.10"

    def _map_upnp(self, port: int, local_ip: str, *, map_udp: bool):
        raise RuntimeError("no IGD discovered")

    def _map_natpmp(self, port: int, *, map_udp: bool):
        return {
            "method": "NAT-PMP",
            "gateway": "192.0.2.1",
            "internal_port": port,
            "external_port": port,
            "external_ip": "198.51.100.20",
            "mapped_tcp": True,
            "mapped_udp": bool(map_udp),
        }


class _FailedConnectivityManager(_FallbackConnectivityManager):
    def _map_natpmp(self, port: int, *, map_udp: bool):
        raise RuntimeError("gateway did not respond")


class _StructuredFailureConnectivityManager(ConnectivityManager):
    @staticmethod
    def _local_ip() -> str:
        return "192.0.2.10"

    def _map_upnp(self, port: int, local_ip: str, *, map_udp: bool):
        raise PortMappingFailure(
            "Discovery",
            "No UPnP Internet Gateway Device replied to SSDP discovery.",
            code="NO_IGD",
            advice="Enable UPnP or use manual forwarding.",
        )

    def _map_natpmp(self, port: int, *, map_udp: bool):
        raise PortMappingFailure(
            "Gateway public-address query",
            "NAT-PMP gateway 192.0.2.1 did not respond.",
            code="NO_RESPONSE",
            advice="Enable NAT-PMP or use manual forwarding.",
        )


class _PermanentLeaseUpnpManager(ConnectivityManager):
    def __init__(self):
        self.soap_calls = []
        super().__init__()

    @staticmethod
    def _local_ip() -> str:
        return "192.0.2.10"

    @staticmethod
    def _discover_upnp_locations(timeout: float = 1.4):
        return ["http://192.0.2.1/root.xml"]

    @staticmethod
    def _upnp_control_from_description(location: str):
        return (
            "urn:schemas-upnp-org:service:WANIPConnection:1",
            "http://192.0.2.1/control",
        )

    def _soap(self, control_url: str, service_type: str, action: str, args: dict):
        self.soap_calls.append((action, dict(args)))
        if action == "AddPortMapping" and int(args.get("LeaseDuration", 0) or 0) > 0:
            raise PortMappingFailure(
                "SOAP AddPortMapping",
                "OnlyPermanentLeasesSupported",
                code="725",
                advice="Use a permanent mapping lease.",
            )
        if action == "GetExternalIPAddress":
            return b"<NewExternalIPAddress>198.51.100.42</NewExternalIPAddress>"
        return b""

    def _remove_mapping(self, mapping):
        return None


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


class TestMultiTorrentConnectivity(unittest.TestCase):
    def test_each_active_listener_keeps_its_own_mapping_and_snapshot(self):
        manager = _FakeConnectivityManager()
        settings = {
            "listen_port": 6881,
            "enable_upnp": True,
            "enable_natpmp": False,
            "enable_dht": True,
        }
        try:
            manager.register_port(settings, 6881)
            manager.register_port(settings, 6882)
            self.assertTrue(
                _wait_until(lambda: manager.snapshot().get("mapping_count") == 2)
            )

            aggregate = manager.snapshot()
            self.assertEqual(aggregate["active_listener_ports"], [6881, 6882])
            self.assertEqual(aggregate["mapped_ports"], [6881, 6882])
            self.assertEqual(manager.snapshot(6881)["internal_port"], 6881)
            self.assertEqual(manager.snapshot(6882)["internal_port"], 6882)
            self.assertEqual(manager.snapshot(6881)["status"], "Mapped")
            self.assertEqual(manager.snapshot(6882)["status"], "Mapped")

            manager.mark_incoming(6881, "203.0.113.7")
            self.assertEqual(manager.snapshot(6881)["status"], "Incoming Confirmed")
            self.assertEqual(manager.snapshot(6881)["last_incoming_peer"], "203.0.113.7")
            self.assertEqual(manager.snapshot(6882)["status"], "Mapped")

            manager.release_port(6881)
            self.assertTrue(
                _wait_until(
                    lambda: manager.snapshot().get("active_listener_ports") == [6882]
                    and manager.snapshot().get("mapping_count") == 1
                )
            )
            self.assertIn(6881, manager.removed_ports)
            self.assertNotIn(6882, manager.removed_ports)
            self.assertEqual(manager.snapshot(6882)["status"], "Mapped")
        finally:
            manager.close()

    def test_mapping_lease_renews_with_one_scheduled_timer(self):
        manager = _RenewConnectivityManager()
        settings = {
            "listen_port": 6881,
            "enable_upnp": True,
            "enable_natpmp": False,
            "enable_dht": True,
        }
        try:
            manager.register_port(settings, 6881)
            self.assertTrue(_wait_until(lambda: manager.map_calls >= 1))
            first = manager.snapshot(6881)
            self.assertEqual(first["status"], "Mapped")
            self.assertIsNotNone(first["next_mapping_refresh_seconds"])

            with manager._lock:
                manager._refresh_deadlines[6881] = time.monotonic() + 0.05
                manager._schedule_renewal_locked()

            self.assertTrue(_wait_until(lambda: manager.map_calls >= 2))
            renewed = manager.snapshot(6881)
            self.assertEqual(renewed["mapping_count"], 1)
            self.assertEqual(renewed["status"], "Mapped")
            self.assertGreater(renewed["next_mapping_refresh_seconds"], 60.0)
        finally:
            manager.close()

    def test_failed_lease_refresh_retains_previous_mapping(self):
        manager = _RenewConnectivityManager()
        settings = {
            "listen_port": 6881,
            "enable_upnp": True,
            "enable_natpmp": False,
            "enable_dht": False,
        }
        try:
            manager.register_port(settings, 6881)
            self.assertTrue(_wait_until(lambda: manager.map_calls >= 1))
            self.assertEqual(manager.snapshot(6881)["mapping_count"], 1)

            manager.fail_mapping = True
            manager.register_port(settings, 6881)
            self.assertTrue(_wait_until(lambda: manager.map_calls >= 2))
            retained = manager.snapshot(6881)
            self.assertEqual(retained["mapping_count"], 1)
            self.assertEqual(retained["status"], "Mapped (refresh failed)")
            self.assertIn("previous mapping retained", retained["last_error"])
            self.assertIsNotNone(retained["next_mapping_refresh_seconds"])
            self.assertLessEqual(retained["next_mapping_refresh_seconds"], 300.0)
        finally:
            manager.close()

    def test_mapping_method_diagnostics_preserve_fallback_reason(self):
        manager = _FallbackConnectivityManager()
        result, mapping = manager._perform_refresh({
            "port": 6881,
            "enable_upnp": True,
            "enable_natpmp": True,
            "map_udp": True,
        })
        self.assertIsNotNone(mapping)
        self.assertEqual(result["status"], "Mapped")
        self.assertEqual(result["method"], "NAT-PMP")
        self.assertEqual(result["upnp_status"], "Failed")
        self.assertIn("IGD", result["upnp_error"])
        self.assertEqual(result["natpmp_status"], "Mapped")
        self.assertEqual(result["natpmp_error"], "")

    def test_unmapped_snapshot_explains_both_mapping_failures(self):
        manager = _FailedConnectivityManager()
        result, mapping = manager._perform_refresh({
            "port": 6881,
            "enable_upnp": True,
            "enable_natpmp": True,
            "map_udp": False,
        })
        self.assertIsNone(mapping)
        self.assertEqual(result["status"], "Unmapped")
        self.assertEqual(result["upnp_status"], "Failed")
        self.assertEqual(result["natpmp_status"], "Failed")
        self.assertIn("UPnP: no IGD discovered", result["last_error"])
        self.assertIn("NAT-PMP: gateway did not respond", result["last_error"])


    def test_structured_unmapped_diagnosis_is_actionable_without_polling(self):
        manager = _StructuredFailureConnectivityManager()
        result, mapping = manager._perform_refresh({
            "port": 6881,
            "enable_upnp": True,
            "enable_natpmp": True,
            "map_udp": True,
        })
        self.assertIsNone(mapping)
        decorated = manager._with_ages(result)
        self.assertEqual(decorated["upnp_stage"], "Discovery")
        self.assertEqual(decorated["upnp_code"], "NO_IGD")
        self.assertEqual(decorated["natpmp_code"], "NO_RESPONSE")
        self.assertIn("No supported automatic port-mapping service", decorated["diagnosis"])
        self.assertIn("TCP port 6881", decorated["action_hint"])
        self.assertIn("outbound seeding", decorated["action_hint"].lower())

    def test_upnp_permanent_lease_fallback_avoids_renewal_timer(self):
        manager = _PermanentLeaseUpnpManager()
        settings = {
            "listen_port": 6881,
            "enable_upnp": True,
            "enable_natpmp": False,
            "enable_dht": False,
        }
        try:
            manager.register_port(settings, 6881)
            self.assertTrue(_wait_until(lambda: manager.snapshot(6881)["status"] == "Mapped"))
            mapping = manager._mappings[6881]
            self.assertEqual(mapping.get("lease_seconds"), 0)
            lease_values = [
                int(args.get("LeaseDuration", -1))
                for action, args in manager.soap_calls
                if action == "AddPortMapping" and args.get("Protocol") == "TCP"
            ]
            self.assertEqual(lease_values[:2], [3600, 0])
            snapshot = manager.snapshot(6881)
            self.assertTrue(snapshot["mapping_permanent"])
            self.assertEqual(snapshot["mapping_lease_seconds"], 0)
            self.assertIsNone(snapshot["next_mapping_refresh_seconds"])
        finally:
            manager.close()

    def test_external_address_scope_is_conservative(self):
        self.assertEqual(ConnectivityManager._external_scope("8.8.8.8"), "Public")
        self.assertEqual(ConnectivityManager._external_scope("192.168.1.10"), "Private")
        self.assertEqual(ConnectivityManager._external_scope("100.64.12.3"), "Shared/CGNAT")
        self.assertEqual(ConnectivityManager._external_scope(""), "Unknown")


class TestRC4Compatibility(unittest.TestCase):
    def test_standard_rc4_known_vector(self):
        # Classic RC4 test vector from the published algorithm examples.
        # This validates interoperability independently from SalixTorrent using
        # the same implementation on both ends of a local MSE test.
        ctx = _RC4Context(b"Key")
        self.assertEqual(
            ctx.update(b"Plaintext").hex().upper(),
            "BBF316E8D940AF0AD3",
        )


class _TrackerStub:
    def __init__(self, announce_url: str):
        self.announce_list = [announce_url]
        self.info_hash = hashlib.sha1(b"tracker-bind-test").digest()
        self.total_length = 1234


class TestDiscoveryBinding(unittest.IsolatedAsyncioTestCase):
    async def test_http_tracker_binding_and_require_crypto_flags(self):
        observed = {}

        async def announce(request):
            observed["remote"] = request.remote
            observed["supportcrypto"] = request.query.get("supportcrypto")
            observed["requirecrypto"] = request.query.get("requirecrypto")
            return web.Response(body=Bencode.encode({b"interval": 1800, b"peers": b""}))

        app = web.Application()
        app.router.add_get("/announce", announce)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        sockets = site._server.sockets
        port = sockets[0].getsockname()[1]

        try:
            tracker = TrackerClient(
                _TrackerStub(f"http://127.0.0.1:{port}/announce"),
                PEER_ID_A,
                bind_address="127.0.0.1",
                encryption_policy=PEER_ENCRYPTION_REQUIRE,
            )
            peers = await tracker.fetch_peers(event="started")
            self.assertEqual(peers, [])
            self.assertEqual(observed.get("remote"), "127.0.0.1")
            self.assertEqual(observed.get("supportcrypto"), "1")
            self.assertEqual(observed.get("requirecrypto"), "1")
        finally:
            await runner.cleanup()

    async def test_dht_udp_socket_binds_selected_address(self):
        client = DHTClient(
            hashlib.sha1(b"dht-bind-test").digest(),
            private=False,
            bootstrap_nodes=(),
            bind_address="127.0.0.1",
        )
        try:
            self.assertTrue(await client.start())
            sockname = client.transport.get_extra_info("sockname")
            self.assertEqual(sockname[0], "127.0.0.1")
        finally:
            await client.close()

    async def test_lpd_socket_binds_selected_address(self):
        lpd = LocalPeerDiscovery(
            hashlib.sha1(b"lpd-bind-test").digest(),
            bind_address="127.0.0.1",
        )
        try:
            sock = lpd._make_socket()
            self.assertEqual(sock.getsockname()[0], "127.0.0.1")
            sock.close()
        finally:
            await lpd.close()


class TestMSEProtocol(unittest.IsolatedAsyncioTestCase):
    async def test_mse_initiator_and_responder_exchange_encrypted_application_data(self):
        info_hash = hashlib.sha1(b"mse-local-test").digest()
        server_done = asyncio.Event()
        server_error = []

        async def handler(reader, writer):
            try:
                first = await reader.readexactly(20)
                stream = await mse_responder_handshake(
                    reader, writer, info_hash, first_bytes=first, timeout=2.0
                )
                self.assertEqual(stream.transport_security, "MSE/RC4")
                self.assertEqual(await stream.readexactly(5), b"hello")
                stream.write(b"world")
                await stream.drain()
            except Exception as exc:  # surfaced below with useful traceback context
                server_error.append(exc)
            finally:
                writer.close()
                await writer.wait_closed()
                server_done.set()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            stream = await mse_initiator_handshake(
                reader, writer, info_hash, initial_payload=b"hello", timeout=2.0
            )
            self.assertEqual(stream.transport_security, "MSE/RC4")
            self.assertEqual(await asyncio.wait_for(stream.readexactly(5), 2.0), b"world")
            writer.close()
            await writer.wait_closed()
            await asyncio.wait_for(server_done.wait(), 2.0)
            if server_error:
                raise server_error[0]
        finally:
            server.close()
            await server.wait_closed()


class TestPeerEncryptionPolicies(unittest.IsolatedAsyncioTestCase):
    async def test_require_encryption_and_source_binding(self):
        info_hash = hashlib.sha1(b"peer-require").digest()
        observed_peer_ips = []
        server_error = []

        async def handler(reader, writer):
            try:
                observed_peer_ips.append(writer.get_extra_info("peername")[0])
                first = await reader.readexactly(20)
                stream = await mse_responder_handshake(
                    reader, writer, info_hash, first_bytes=first, timeout=2.0
                )
                request = await stream.readexactly(68)
                self.assertEqual(request[28:48], info_hash)
                stream.write(_bt_handshake(info_hash, PEER_ID_B))
                await stream.drain()
                await asyncio.sleep(0.05)
            except Exception as exc:
                server_error.append(exc)
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        peer = PeerConnection(
            "127.0.0.1",
            port,
            info_hash,
            PEER_ID_A,
            encryption_policy=PEER_ENCRYPTION_REQUIRE,
            bind_address="127.0.0.1",
        )
        try:
            self.assertTrue(await peer.connect(timeout=2.0))
            self.assertEqual(peer.transport_security, "MSE/RC4")
            self.assertEqual(observed_peer_ips, ["127.0.0.1"])
        finally:
            await peer.close()
            server.close()
            await server.wait_closed()
        if server_error:
            raise server_error[0]

    async def test_prefer_encryption_uses_fresh_plaintext_fallback(self):
        info_hash = hashlib.sha1(b"peer-prefer").digest()
        connections = 0

        async def handler(reader, writer):
            nonlocal connections
            connections += 1
            try:
                first = await asyncio.wait_for(reader.readexactly(20), 2.0)
                if first != b"\x13BitTorrent protocol":
                    # Simulate a peer that rejects/does not understand MSE.
                    return
                rest = await asyncio.wait_for(reader.readexactly(48), 2.0)
                request = first + rest
                self.assertEqual(request[28:48], info_hash)
                writer.write(_bt_handshake(info_hash, PEER_ID_B))
                await writer.drain()
                await asyncio.sleep(0.05)
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        peer = PeerConnection(
            "127.0.0.1",
            port,
            info_hash,
            PEER_ID_A,
            encryption_policy=PEER_ENCRYPTION_PREFER,
        )
        try:
            self.assertTrue(await peer.connect(timeout=1.0))
            self.assertEqual(connections, 2)
            self.assertTrue(peer.plaintext_fallback_used)
            self.assertEqual(peer.transport_security, "Plaintext")
        finally:
            await peer.close()
            server.close()
            await server.wait_closed()

    async def test_require_encryption_never_falls_back_to_plaintext(self):
        info_hash = hashlib.sha1(b"peer-require-no-fallback").digest()
        connections = 0

        async def handler(reader, writer):
            nonlocal connections
            connections += 1
            try:
                await asyncio.wait_for(reader.readexactly(20), 2.0)
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        peer = PeerConnection(
            "127.0.0.1",
            port,
            info_hash,
            PEER_ID_A,
            encryption_policy=PEER_ENCRYPTION_REQUIRE,
        )
        try:
            self.assertFalse(await peer.connect(timeout=1.0))
            self.assertEqual(connections, 1)
            self.assertFalse(peer.plaintext_fallback_used)
        finally:
            await peer.close()
            server.close()
            await server.wait_closed()


class TestTorrentSessionTransport(unittest.IsolatedAsyncioTestCase):
    async def test_outgoing_peer_request_updates_event_driven_upload_telemetry(self):
        payload = b"transport-security-test"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            torrent_path = root / "outgoing-upload.torrent"
            _write_torrent(torrent_path)
            download_dir = root / "downloads"
            download_dir.mkdir(parents=True, exist_ok=True)
            (download_dir / "transport.bin").write_bytes(payload)

            session = TorrentSession(
                str(torrent_path),
                download_dir=str(download_dir),
                enable_dht=False,
                enable_pex=False,
                enable_lan_discovery=False,
                encryption_policy=PEER_ENCRYPTION_DISABLED,
            )
            self.assertTrue(session.piece_mgr.prepare_storage())
            session.state = SessionState.SEEDING
            session.is_running = True
            session._run_token = 8
            peer = _UploadPeerStub()

            served = await session._serve_piece_request(
                peer, 8, 0, 0, len(payload)
            )
            self.assertTrue(served)
            self.assertEqual(peer.sent, [(0, 0, payload)])
            self.assertEqual(session.uploaded_bytes, len(payload))
            self.assertEqual(session.uploaded_this_session_bytes, len(payload))
            self.assertEqual(session.upload_requests_received, 1)
            self.assertEqual(session.upload_requests_served, 1)
            self.assertGreater(session._last_upload_at, 0.0)

    async def test_incoming_mse_peer_receives_encrypted_bitfield(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            torrent = _write_torrent(root / "incoming.torrent")
            session = TorrentSession(
                str(root / "incoming.torrent"),
                download_dir=str(root / "downloads"),
                enable_dht=False,
                enable_pex=False,
                enable_lan_discovery=False,
                encryption_policy=PEER_ENCRYPTION_REQUIRE,
                network_bind_address="127.0.0.1",
            )
            session.piece_mgr._storage_prepared = True
            session.state = SessionState.DOWNLOADING
            session.is_running = True
            session._run_token = 9

            handler_tasks = set()

            def dispatch(reader, writer):
                task = asyncio.create_task(
                    session._handle_inbound_seed_peer(9, reader, writer)
                )
                handler_tasks.add(task)
                task.add_done_callback(handler_tasks.discard)

            server = await asyncio.start_server(dispatch, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            session._seed_port = port
            session._seed_server = server

            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                stream = await mse_initiator_handshake(
                    reader,
                    writer,
                    torrent.info_hash,
                    initial_payload=_bt_handshake(torrent.info_hash, PEER_ID_A),
                    timeout=2.0,
                )
                response = await asyncio.wait_for(stream.readexactly(68), 2.0)
                self.assertEqual(response[28:48], torrent.info_hash)

                length = struct.unpack(">I", await stream.readexactly(4))[0]
                payload = await stream.readexactly(length)
                self.assertGreaterEqual(length, 1)
                self.assertEqual(payload[0], PeerMessageID.BITFIELD)

                await asyncio.sleep(0.05)
                snapshot = session._build_snapshot(force_detail_refresh=True)
                self.assertEqual(snapshot["encrypted_peer_count"], 1)
                self.assertEqual(snapshot["plaintext_peer_count"], 0)
                self.assertEqual(snapshot["peers"][0]["transport_security"], "MSE/RC4")

                writer.close()
                await writer.wait_closed()
            finally:
                session.is_running = False
                server.close()
                await server.wait_closed()
                for writer in list(session._seed_client_writers):
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
                if handler_tasks:
                    await asyncio.wait(handler_tasks, timeout=1.0)

    async def test_listener_callback_releases_mapping_when_server_closes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_torrent(root / "listener.torrent")
            events = []

            session = TorrentSession(
                str(root / "listener.torrent"),
                download_dir=str(root / "downloads"),
                enable_dht=False,
                enable_pex=False,
                enable_lan_discovery=False,
                encryption_policy=PEER_ENCRYPTION_DISABLED,
                network_bind_address="127.0.0.1",
                listen_port_callback=lambda port, active: events.append((port, active)),
            )
            session.state = SessionState.DOWNLOADING
            session.is_running = True
            session._run_token = 17

            await session._open_seed_server(17)
            opened_port = session._seed_port
            self.assertIn((opened_port, True), events)
            self.assertIsNotNone(session._seed_server)
            snapshot = session._build_snapshot(force_detail_refresh=True)
            self.assertEqual(snapshot["listener_address"], "127.0.0.1")

            await session._close_seed_server()
            self.assertIn((opened_port, False), events)
            self.assertIsNone(session._seed_server)

    async def test_completed_seed_serves_requested_piece_to_inbound_leecher(self):
        payload = b"transport-security-test"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            torrent_path = root / "seed-upload.torrent"
            torrent = _write_torrent(torrent_path)
            download_dir = root / "downloads"
            download_dir.mkdir(parents=True, exist_ok=True)
            (download_dir / "transport.bin").write_bytes(payload)

            session = TorrentSession(
                str(torrent_path),
                download_dir=str(download_dir),
                enable_dht=False,
                enable_pex=False,
                enable_lan_discovery=False,
                encryption_policy=PEER_ENCRYPTION_DISABLED,
                network_bind_address="127.0.0.1",
            )
            self.assertTrue(session.piece_mgr.prepare_storage())
            self.assertTrue(session.piece_mgr.is_finished)
            session.state = SessionState.SEEDING
            session.is_running = True
            session._run_token = 19

            handler_tasks = set()

            def dispatch(reader, writer):
                task = asyncio.create_task(
                    session._handle_inbound_seed_peer(19, reader, writer)
                )
                handler_tasks.add(task)
                task.add_done_callback(handler_tasks.discard)

            server = await asyncio.start_server(dispatch, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            session._seed_port = port
            session._seed_server = server

            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.write(_bt_handshake(torrent.info_hash, PEER_ID_A))
                await writer.drain()

                response = await asyncio.wait_for(reader.readexactly(68), 2.0)
                self.assertEqual(response[28:48], torrent.info_hash)

                # Initial BITFIELD then UNCHOKE. The remote handshake advertises
                # extensions, so an extended handshake may follow afterwards.
                length = struct.unpack(">I", await reader.readexactly(4))[0]
                initial = await reader.readexactly(length)
                self.assertEqual(initial[0], PeerMessageID.BITFIELD)
                length = struct.unpack(">I", await reader.readexactly(4))[0]
                initial = await reader.readexactly(length)
                self.assertEqual(initial[0], PeerMessageID.UNCHOKE)

                request_body = struct.pack(">III", 0, 0, len(payload))
                writer.write(
                    struct.pack(">IB", 1 + len(request_body), PeerMessageID.REQUEST)
                    + request_body
                )
                await writer.drain()

                piece_data = None
                for _ in range(4):
                    length = struct.unpack(
                        ">I", await asyncio.wait_for(reader.readexactly(4), 2.0)
                    )[0]
                    message = await asyncio.wait_for(reader.readexactly(length), 2.0)
                    if message and message[0] == PeerMessageID.PIECE:
                        piece_index, begin = struct.unpack(">II", message[1:9])
                        self.assertEqual((piece_index, begin), (0, 0))
                        piece_data = message[9:]
                        break

                self.assertEqual(piece_data, payload)
                self.assertEqual(session.uploaded_bytes, len(payload))
                snapshot = session._build_snapshot(force_detail_refresh=True)
                self.assertEqual(snapshot["uploaded_this_session_bytes"], len(payload))
                self.assertEqual(snapshot["upload_requests_received"], 1)
                self.assertEqual(snapshot["upload_requests_served"], 1)
                self.assertIsNotNone(snapshot["last_upload_seconds"])
                self.assertLess(snapshot["last_upload_seconds"], 2.0)
                self.assertEqual(snapshot["incoming_peers"], 1)
                self.assertEqual(snapshot["incoming_connections_total"], 1)

                writer.close()
                await writer.wait_closed()
            finally:
                session.is_running = False
                server.close()
                await server.wait_closed()
                for client_writer in list(session._seed_client_writers):
                    client_writer.close()
                    try:
                        await client_writer.wait_closed()
                    except Exception:
                        pass
                if handler_tasks:
                    await asyncio.wait(handler_tasks, timeout=1.0)

    async def test_interface_lock_fails_closed_before_network_start(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_torrent(root / "lock.torrent")
            session = TorrentSession(
                str(root / "lock.torrent"),
                download_dir=str(root / "downloads"),
                enable_dht=False,
                enable_pex=False,
                enable_lan_discovery=False,
                network_bind_address="203.0.113.254",
                interface_lock=True,
            )
            await session.start()
            self.assertEqual(session.state, SessionState.ERROR)
            self.assertFalse(session.is_running)
            self.assertIn("Interface Lock", session.error_message)
            self.assertIsNone(session._main_task)

    def test_ip_masking_is_display_only_telemetry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_torrent(root / "mask.torrent")
            session = TorrentSession(
                str(root / "mask.torrent"),
                download_dir=str(root / "downloads"),
                mask_peer_ips=True,
            )
            self.assertEqual(session._display_peer_ip("192.168.50.123"), "192.168.x.x")
            self.assertEqual(session.network_bind_address, "")


class TestDiscoverySourceSeverity(unittest.TestCase):
    def test_source_summary_separates_pending_warning_and_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_torrent(root / "sources.torrent")
            session = TorrentSession(
                str(root / "sources.torrent"),
                download_dir=str(root / "downloads"),
                enable_dht=True,
                enable_pex=True,
                enable_lan_discovery=True,
            )
            session.tracker.get_source_snapshots = lambda: [
                {"source": "udp://timeout", "type": "UDP", "status": "Timeout", "peers": 0},
                {"source": "http://active", "type": "HTTP", "status": "Active", "peers": 12},
            ]
            session._dht.get_source_snapshot = lambda: {
                "source": "Distributed Hash Table", "type": "DHT", "status": "Active", "peers": 20
            }
            session._build_pex_source_snapshot = lambda: {
                "source": "Peer Exchange", "type": "PEX", "status": "Waiting", "peers": 0
            }
            session._lpd.get_source_snapshot = lambda: {
                "source": "Local Peer Discovery", "type": "LAN", "status": "Error", "peers": 0
            }

            summary = session._build_sources_view_snapshot()
            self.assertEqual(summary["active_count"], 2)
            self.assertEqual(summary["pending_count"], 1)
            self.assertEqual(summary["warning_count"], 1)
            self.assertEqual(summary["error_count"], 1)
            self.assertEqual(summary["problem_count"], 2)
            self.assertEqual(summary["tracker_peers_last_seen"], 12)


class TestTransportSettings(unittest.TestCase):
    def test_transport_defaults_and_lock_requires_specific_bind(self):
        defaults = TorrentManager._normalise_app_settings({})
        self.assertEqual(defaults["peer_encryption"], "Prefer Encryption")
        self.assertEqual(defaults["network_bind_address"], "")
        self.assertFalse(defaults["interface_lock"])
        self.assertFalse(defaults["mask_peer_ips"])

        unbound_lock = TorrentManager._normalise_app_settings({"interface_lock": True})
        self.assertFalse(unbound_lock["interface_lock"])

        bound_lock = TorrentManager._normalise_app_settings({
            "network_bind_address": "127.0.0.1",
            "interface_lock": True,
            "peer_encryption": "Require Encryption",
        })
        self.assertEqual(bound_lock["network_bind_address"], "127.0.0.1")
        self.assertTrue(bound_lock["interface_lock"])
        self.assertEqual(bound_lock["peer_encryption"], "Require Encryption")


if __name__ == "__main__":
    unittest.main(verbosity=2)
