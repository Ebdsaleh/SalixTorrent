"""BitTorrent v2/hybrid peer-wire regressions.

Regression lineage:
- introduced during the Phase 9 v2 peer-wire milestone.
"""

import asyncio
import struct
import tempfile
import unittest
from pathlib import Path

from app.logic.peer import (
    PEER_ENCRYPTION_DISABLED,
    PeerConnection,
    PeerMessageID,
    build_hash_request_payload,
    build_reserved_bytes,
    parse_hashes_payload,
)
from app.logic.session import SessionState, TorrentSession
from app.logic.torrent_creator import (
    TORRENT_GENERATION_HYBRID,
    TORRENT_GENERATION_V2,
    TorrentCreator,
)
from app.logic.torrent_file import TorrentFile
from app.logic.torrent_v2 import piece_layer_depth


PEER_ID = b"-P90000-123456789012"


def _handshake(info_hash: bytes, *, enable_v2: bool = False) -> bytes:
    return (
        b"\x13BitTorrent protocol"
        + build_reserved_bytes(enable_v2=enable_v2)
        + bytes(info_hash)
        + PEER_ID
    )


async def _read_frame(reader: asyncio.StreamReader, timeout: float = 2.0):
    length_raw = await asyncio.wait_for(reader.readexactly(4), timeout)
    (length,) = struct.unpack(">I", length_raw)
    if length == 0:
        return None, b""
    payload = await asyncio.wait_for(reader.readexactly(length), timeout)
    return int(payload[0]), bytes(payload[1:])


class V2PeerWireTests(unittest.IsolatedAsyncioTestCase):
    async def _start_inbound_session(self, session: TorrentSession, token: int):
        tasks = set()

        def dispatch(reader, writer):
            task = asyncio.create_task(
                session._handle_inbound_seed_peer(token, reader, writer)
            )
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        server = await asyncio.start_server(dispatch, "127.0.0.1", 0)
        session._seed_port = server.sockets[0].getsockname()[1]
        session._seed_server = server
        return server, tasks

    async def _close_inbound_session(self, session, server, tasks):
        session.is_running = False
        server.close()
        await server.wait_closed()
        for writer in list(session._seed_client_writers):
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        if tasks:
            await asyncio.wait(tasks, timeout=1.0)

    async def test_v2_seed_serves_hash_layer_and_piece_over_real_tcp(self):
        payload = bytes(range(251)) * 300
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "payload.bin"
            source.write_bytes(payload)
            torrent_path = root / "v2.torrent"
            TorrentCreator.create(
                str(source),
                str(torrent_path),
                trackers=["http://tracker.invalid/announce"],
                piece_length=32768,
                generation=TORRENT_GENERATION_V2,
            )
            session = TorrentSession(
                str(torrent_path),
                seed_source_path=str(source),
                enable_dht=False,
                enable_pex=False,
                enable_lan_discovery=False,
                encryption_policy=PEER_ENCRYPTION_DISABLED,
                network_bind_address="127.0.0.1",
            )
            self.assertTrue(session.piece_mgr.prepare_storage())
            session.state = SessionState.SEEDING
            session.is_running = True
            session._run_token = 91
            server, tasks = await self._start_inbound_session(session, 91)

            try:
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", session._seed_port
                )
                writer.write(_handshake(session.swarm_hashes["v2"], enable_v2=True))
                await writer.drain()
                response = await asyncio.wait_for(reader.readexactly(68), 2.0)
                self.assertEqual(response[28:48], session.swarm_hashes["v2"])
                self.assertTrue(response[27] & 0x10)

                root_hash = session.torrent.v2_files[0]["pieces_root"]
                request = build_hash_request_payload(
                    root_hash,
                    piece_layer_depth(session.torrent.piece_length),
                    0,
                    2,
                    0,
                )
                writer.write(
                    struct.pack(">IB", 1 + len(request), PeerMessageID.HASH_REQUEST)
                    + request
                )
                await writer.drain()

                hashes = None
                for _ in range(8):
                    msg_id, body = await _read_frame(reader)
                    if msg_id == PeerMessageID.HASHES:
                        hashes = parse_hashes_payload(body)
                        break
                self.assertIsNotNone(hashes)
                self.assertEqual(hashes["pieces_root"], root_hash)
                self.assertEqual(len(hashes["hashes"]), 2)

                request_body = struct.pack(">III", 0, 0, 16384)
                writer.write(
                    struct.pack(">IB", 13, PeerMessageID.REQUEST) + request_body
                )
                await writer.drain()
                piece_data = None
                for _ in range(8):
                    msg_id, body = await _read_frame(reader)
                    if msg_id == PeerMessageID.PIECE:
                        index, begin = struct.unpack(">II", body[:8])
                        self.assertEqual((index, begin), (0, 0))
                        piece_data = body[8:]
                        break
                self.assertEqual(piece_data, payload[:16384])
                writer.close()
                await writer.wait_closed()
            finally:
                await self._close_inbound_session(session, server, tasks)

    async def test_hybrid_v1_connection_upgrades_to_v2_wire_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "payload.bin"
            source.write_bytes(b"hybrid-upgrade" * 3000)
            torrent_path = root / "hybrid.torrent"
            TorrentCreator.create(
                str(source),
                str(torrent_path),
                trackers=["http://tracker.invalid/announce"],
                piece_length=16384,
                generation=TORRENT_GENERATION_HYBRID,
            )
            session = TorrentSession(
                str(torrent_path),
                seed_source_path=str(source),
                enable_dht=False,
                enable_pex=False,
                enable_lan_discovery=False,
                encryption_policy=PEER_ENCRYPTION_DISABLED,
                network_bind_address="127.0.0.1",
            )
            self.assertTrue(session.piece_mgr.prepare_storage())
            session.state = SessionState.SEEDING
            session.is_running = True
            session._run_token = 92
            server, tasks = await self._start_inbound_session(session, 92)
            peer = PeerConnection(
                "127.0.0.1",
                session._seed_port,
                session.torrent.v1_info_hash,
                PEER_ID,
                encryption_policy=PEER_ENCRYPTION_DISABLED,
                v1_info_hash=session.torrent.v1_info_hash,
                v2_info_hash=session.torrent.v2_info_hash,
                protocol_generation="v1",
            )
            try:
                self.assertTrue(await peer.connect(timeout=2.0))
                self.assertEqual(peer.protocol_generation, "v2")
                self.assertEqual(peer.remote_reserved[7] & 0x10, 0x10)
            finally:
                await peer.close()
                await self._close_inbound_session(session, server, tasks)

    async def test_v2_download_completes_over_real_peer_wire(self):
        payload = bytes(range(251)) * 250
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "payload.bin"
            source.write_bytes(payload)
            torrent_path = root / "v2.torrent"
            TorrentCreator.create(
                str(source),
                str(torrent_path),
                trackers=["http://tracker.invalid/announce"],
                piece_length=32768,
                generation=TORRENT_GENERATION_V2,
            )
            torrent = TorrentFile(str(torrent_path))
            server_tasks = set()

            async def seed_handler(reader, writer):
                try:
                    handshake = await reader.readexactly(68)
                    self.assertEqual(handshake[28:48], torrent.v2_info_hash[:20])
                    writer.write(_handshake(torrent.v2_info_hash[:20], enable_v2=True))
                    bitfield = bytearray((torrent.num_pieces + 7) // 8)
                    for index in range(torrent.num_pieces):
                        bitfield[index // 8] |= 1 << (7 - (index % 8))
                    writer.write(
                        struct.pack(">IB", 1 + len(bitfield), PeerMessageID.BITFIELD)
                        + bitfield
                    )
                    writer.write(struct.pack(">IB", 1, PeerMessageID.UNCHOKE))
                    await writer.drain()

                    while True:
                        msg_id, body = await _read_frame(reader, timeout=4.0)
                        if msg_id != PeerMessageID.REQUEST:
                            continue
                        piece_index, begin, length = struct.unpack(">III", body)
                        descriptor = torrent.v2_piece_map[piece_index]
                        file_offset = int(descriptor["file_offset"]) + begin
                        block = payload[file_offset:file_offset + length]
                        piece_body = struct.pack(">II", piece_index, begin) + block
                        writer.write(
                            struct.pack(">IB", 1 + len(piece_body), PeerMessageID.PIECE)
                            + piece_body
                        )
                        await writer.drain()
                except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
                    pass
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass

            def dispatch(reader, writer):
                task = asyncio.create_task(seed_handler(reader, writer))
                server_tasks.add(task)
                task.add_done_callback(server_tasks.discard)

            server = await asyncio.start_server(dispatch, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            download_dir = root / "downloads"
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
            await session.piece_mgr.start_disk_io()
            session.state = SessionState.DOWNLOADING
            session.is_running = True
            session._run_token = 94
            try:
                await asyncio.wait_for(
                    session._peer_worker(
                        94, "127.0.0.1", port, source="Test", generation="v2"
                    ),
                    timeout=8.0,
                )
                self.assertTrue(session.piece_mgr.wanted_is_finished)
                self.assertTrue(await session.piece_mgr.flush_disk_writes())
                self.assertEqual((download_dir / "payload.bin").read_bytes(), payload)
            finally:
                session.is_running = False
                await session.piece_mgr.shutdown_disk_io(flush=True)
                server.close()
                await server.wait_closed()
                if server_tasks:
                    await asyncio.wait(server_tasks, timeout=1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
