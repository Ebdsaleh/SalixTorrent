"""Magnet metadata-resolution regressions.

Regression lineage:
- introduced during the Phase 9 btmh/v2 metadata milestone.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.logic.magnet import MagnetLink, MagnetMetadataFetcher
from app.logic.peer import PEER_ENCRYPTION_DISABLED
from app.logic.session import SessionState, TorrentSession
from app.logic.torrent_creator import TORRENT_GENERATION_V2, TorrentCreator


PEER_ID = b"-P90000-123456789012"


class MagnetMetadataTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_btmh_metadata_resolution_acquires_verified_piece_layers(self):
        payload = bytes(range(251)) * 350
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
            session._run_token = 93
            server, tasks = await self._start_inbound_session(session, 93)
            magnet = MagnetLink.parse(session.torrent.magnet_uri)
            fetcher = MagnetMetadataFetcher(
                magnet,
                PEER_ID,
                encryption_policy=PEER_ENCRYPTION_DISABLED,
                bind_address="127.0.0.1",
            )
            try:
                raw_info = await fetcher._fetch_from_peer(
                    ("127.0.0.1", session._seed_port), "v2"
                )
                self.assertEqual(raw_info, session.torrent.raw_info_bytes)
                self.assertTrue(fetcher.resolved_piece_layers)
                self.assertEqual(
                    fetcher.resolved_piece_layers,
                    {
                        root: b"".join(hashes)
                        for root, hashes in session.torrent.v2_piece_layers.items()
                    },
                )
            finally:
                for dht in fetcher._dht_by_generation.values():
                    await dht.close()
                for lpd in fetcher._lpd_by_generation.values():
                    await lpd.close()
                await self._close_inbound_session(session, server, tasks)


if __name__ == "__main__":
    unittest.main(verbosity=2)
