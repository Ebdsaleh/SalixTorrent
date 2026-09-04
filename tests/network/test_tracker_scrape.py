# test_tracker_scrape.py

import asyncio
import socket
import struct
import threading
import unittest
from types import SimpleNamespace

from app.logic.bencode import Bencode
from app.logic.torrent_manager import TorrentManager
from app.logic.tracker import TrackerClient
from app.logic.tracker_scrape import (
    TrackerScrapeCoordinator,
    decode_http_scrape_response,
    derive_http_scrape_url,
)


class _FakeScrapeSession:
    def __init__(self, info_hash: bytes, tracker_url: str):
        self.is_running = True
        self.state = "Seeding"
        self.torrent = SimpleNamespace(info_hash=info_hash, announce_list=[tracker_url])
        self.results = []

    def apply_tracker_scrape_result(self, tracker_url, result):
        self.results.append((tracker_url, dict(result)))


class TestHTTPTrackerScrape(unittest.IsolatedAsyncioTestCase):
    def test_bep48_endpoint_derivation_preserves_tracker_query(self):
        url = "https://tracker.example/a/announce?passkey=abc123"
        self.assertEqual(
            derive_http_scrape_url(url),
            "https://tracker.example/a/scrape?passkey=abc123",
        )
        self.assertIsNone(derive_http_scrape_url("https://tracker.example/tracker"))

    def test_http_scrape_decoder_returns_slc(self):
        h1 = b"A" * 20
        payload = Bencode.encode({
            b"files": {
                h1: {b"complete": 11, b"incomplete": 19, b"downloaded": 13772}
            }
        })
        decoded = decode_http_scrape_response(payload)
        self.assertEqual(decoded[h1], {"seeders": 11, "leechers": 19, "completed": 13772})

    async def test_shared_coordinator_batches_two_torrents_into_one_http_scrape(self):
        hashes = [b"A" * 20, b"B" * 20]
        request_lines = []

        async def handler(reader, writer):
            line = await reader.readline()
            request_lines.append(line.decode("ascii", errors="replace"))
            while True:
                header = await reader.readline()
                if header in {b"\r\n", b""}:
                    break
            body = Bencode.encode({
                b"files": {
                    hashes[0]: {b"complete": 5, b"incomplete": 2, b"downloaded": 91},
                    hashes[1]: {b"complete": 8, b"incomplete": 3, b"downloaded": 144},
                }
            })
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: "
                + str(len(body)).encode("ascii") + b"\r\nConnection: close\r\n\r\n" + body
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        tracker = f"http://127.0.0.1:{port}/announce"
        sessions = [_FakeScrapeSession(h, tracker) for h in hashes]
        coordinator = TrackerScrapeCoordinator(lambda: sessions)
        try:
            await coordinator._refresh_all()
        finally:
            server.close()
            await server.wait_closed()

        self.assertEqual(len(request_lines), 1)
        self.assertEqual(request_lines[0].count("info_hash="), 2)
        self.assertEqual(sessions[0].results[-1][1]["batch_size"], 2)
        self.assertEqual(sessions[0].results[-1][1]["seeders"], 5)
        self.assertEqual(sessions[1].results[-1][1]["completed"], 144)


    async def test_http_scrape_over_ipv6_loopback(self):
        info_hash = b"V" * 20
        try:
            server = await asyncio.start_server(lambda r, w: None, "::1", 0)
        except OSError:
            self.skipTest("IPv6 loopback is unavailable")
        server.close()
        await server.wait_closed()

        async def handler(reader, writer):
            await reader.readline()
            while True:
                header = await reader.readline()
                if header in {b"\r\n", b""}:
                    break
            body = Bencode.encode({
                b"files": {info_hash: {b"complete": 4, b"incomplete": 1, b"downloaded": 33}}
            })
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n" + body
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handler, "::1", 0)
        port = server.sockets[0].getsockname()[1]
        coordinator = TrackerScrapeCoordinator(lambda: [], bind_address="::1")
        try:
            result = await coordinator._scrape_http(
                f"http://[::1]:{port}/scrape", [info_hash]
            )
        finally:
            server.close()
            await server.wait_closed()
        self.assertEqual(result[info_hash]["completed"], 33)

    async def test_http_tracker_without_announce_path_reports_scrape_unsupported(self):
        session = _FakeScrapeSession(b"C" * 20, "http://127.0.0.1:1/tracker")
        coordinator = TrackerScrapeCoordinator(lambda: [session])
        await coordinator._refresh_all()
        self.assertEqual(session.results[-1][1]["status"], "Unsupported")


class TestUDPTrackerScrape(unittest.TestCase):
    def test_udp_scrape_batches_hashes_under_one_connection(self):
        info_hashes = [b"D" * 20, b"E" * 20]
        received = []
        ready = threading.Event()
        done = threading.Event()
        endpoint = {}

        def server_thread():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("127.0.0.1", 0))
            endpoint["port"] = sock.getsockname()[1]
            ready.set()
            try:
                data, addr = sock.recvfrom(4096)
                received.append(data)
                _protocol, action, tx = struct.unpack(">QII", data[:16])
                self.assertEqual(action, 0)
                connection_id = 0x1122334455667788
                sock.sendto(struct.pack(">IIQ", 0, tx, connection_id), addr)

                data, addr = sock.recvfrom(4096)
                received.append(data)
                recv_conn, action, tx = struct.unpack(">QII", data[:16])
                self.assertEqual(recv_conn, connection_id)
                self.assertEqual(action, 2)
                self.assertEqual(data[16:], b"".join(info_hashes))
                response = struct.pack(">II", 2, tx)
                response += struct.pack(">III", 12, 100, 4)
                response += struct.pack(">III", 22, 200, 7)
                sock.sendto(response, addr)
            finally:
                sock.close()
                done.set()

        thread = threading.Thread(target=server_thread, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(2.0))
        coordinator = TrackerScrapeCoordinator(lambda: [])
        result = coordinator._scrape_udp_blocking(
            f"udp://127.0.0.1:{endpoint['port']}/announce", info_hashes
        )
        self.assertTrue(done.wait(2.0))
        self.assertEqual(len(received), 2)  # one connect + one batched scrape
        self.assertEqual(result[info_hashes[0]], {"seeders": 12, "completed": 100, "leechers": 4})
        self.assertEqual(result[info_hashes[1]], {"seeders": 22, "completed": 200, "leechers": 7})

    def test_udp_scrape_chunks_large_sets_without_reconnecting(self):
        info_hashes = [bytes([index]) * 20 for index in range(1, 62)]
        ready = threading.Event()
        done = threading.Event()
        endpoint = {}
        packet_sizes = []

        def server_thread():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("127.0.0.1", 0))
            endpoint["port"] = sock.getsockname()[1]
            ready.set()
            try:
                data, addr = sock.recvfrom(4096)
                packet_sizes.append(len(data))
                _protocol, _action, tx = struct.unpack(">QII", data[:16])
                connection_id = 0x123456789ABCDEF0
                sock.sendto(struct.pack(">IIQ", 0, tx, connection_id), addr)

                remaining = len(info_hashes)
                next_value = 0
                while remaining:
                    data, addr = sock.recvfrom(4096)
                    packet_sizes.append(len(data))
                    _conn, action, tx = struct.unpack(">QII", data[:16])
                    self.assertEqual(action, 2)
                    count = (len(data) - 16) // 20
                    response = struct.pack(">II", 2, tx)
                    for _ in range(count):
                        next_value += 1
                        response += struct.pack(">III", next_value, next_value + 100, next_value + 200)
                    sock.sendto(response, addr)
                    remaining -= count
            finally:
                sock.close()
                done.set()

        threading.Thread(target=server_thread, daemon=True).start()
        self.assertTrue(ready.wait(2.0))
        coordinator = TrackerScrapeCoordinator(lambda: [])
        result = coordinator._scrape_udp_blocking(
            f"udp://127.0.0.1:{endpoint['port']}/announce", info_hashes
        )
        self.assertTrue(done.wait(2.0))
        self.assertEqual(len(result), 61)
        self.assertEqual(len(packet_sizes), 3)  # connect + two scrape batches
        self.assertLessEqual(max(packet_sizes[1:]), 16 + 20 * 60)

    def test_udp_scrape_over_ipv6_loopback(self):
        info_hash = b"W" * 20
        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        try:
            sock.bind(("::1", 0))
        except OSError:
            sock.close()
            self.skipTest("IPv6 loopback is unavailable")
        port = sock.getsockname()[1]
        done = threading.Event()

        def server_thread():
            try:
                data, addr = sock.recvfrom(4096)
                _protocol, action, tx = struct.unpack(">QII", data[:16])
                self.assertEqual(action, 0)
                connection_id = 0x8877665544332211
                sock.sendto(struct.pack(">IIQ", 0, tx, connection_id), addr)
                data, addr = sock.recvfrom(4096)
                _conn, action, tx = struct.unpack(">QII", data[:16])
                self.assertEqual(action, 2)
                sock.sendto(struct.pack(">IIIII", 2, tx, 9, 77, 2), addr)
            finally:
                sock.close()
                done.set()

        threading.Thread(target=server_thread, daemon=True).start()
        coordinator = TrackerScrapeCoordinator(lambda: [], bind_address="::1")
        result = coordinator._scrape_udp_blocking(
            f"udp://[::1]:{port}/announce", [info_hash]
        )
        self.assertTrue(done.wait(2.0))
        self.assertEqual(result[info_hash], {"seeders": 9, "completed": 77, "leechers": 2})


class TestScrapeTelemetry(unittest.TestCase):
    def test_scrape_telemetry_does_not_overwrite_announce_health(self):
        url = "http://tracker.example/announce"
        client = TrackerClient.__new__(TrackerClient)
        client.torrent = SimpleNamespace(announce_list=[url])
        client._source_records = {}
        started = client._begin_source_query(url, "started")
        client._finish_source_query(
            url,
            started,
            peers=[("127.0.0.1", 6881)],
            metadata={"seeders": 3, "leechers": 1},
        )
        client.apply_scrape_result(url, {
            "status": "Active",
            "seeders": 7,
            "leechers": 2,
            "completed": 99,
            "batch_size": 4,
            "protocol": "HTTP",
            "endpoint": "http://tracker.example/scrape",
            "response_ms": 12.5,
        })
        source = client.get_source_snapshots()[0]
        self.assertEqual(source["status"], "Active")
        self.assertEqual(source["seeders"], 3)
        self.assertEqual(source["scrape_seeders"], 7)
        self.assertEqual(source["scrape_completed"], 99)
        self.assertEqual(source["scrape_batch_size"], 4)


class TestWindowsShutdownResetHandling(unittest.TestCase):
    def test_windows_10054_peer_reset_is_expected_transport_noise(self):
        exc = ConnectionResetError(10054, "An existing connection was forcibly closed")
        self.assertTrue(TorrentManager._is_expected_transport_reset({"exception": exc}))

    def test_other_asyncio_errors_are_not_suppressed(self):
        self.assertFalse(
            TorrentManager._is_expected_transport_reset({"exception": RuntimeError("boom")})
        )
        self.assertFalse(
            TorrentManager._is_expected_transport_reset({"exception": ConnectionResetError(104, "reset")})
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
