"""Torrent-generation and swarm-selection regressions.

Regression lineage:
- introduced during the Phase 9 v1/v2/hybrid generation milestone.
"""

import tempfile
import unittest
from pathlib import Path

from app.logic.session import TorrentSession
from app.logic.torrent_creator import (
    TORRENT_GENERATION_HYBRID,
    TORRENT_GENERATION_V1,
    TORRENT_GENERATION_V2,
    TorrentCreator,
)
from app.logic.torrent_file import TorrentFile
from app.logic.transfer_add import (
    TORRENT_PROTOCOL_AUTO,
    TORRENT_PROTOCOL_V1_ONLY,
    TORRENT_PROTOCOL_V2_ONLY,
)


class TorrentGenerationTests(unittest.TestCase):
    def test_creator_round_trips_v1_v2_and_hybrid(self):
        payload = bytes(range(251)) * 300
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "payload.bin"
            source.write_bytes(payload)

            for generation, expected in (
                (TORRENT_GENERATION_V1, (True, False, False)),
                (TORRENT_GENERATION_V2, (False, True, False)),
                (TORRENT_GENERATION_HYBRID, (True, True, True)),
            ):
                out = root / f"{generation.split()[1].lower()}.torrent"
                result = TorrentCreator.create(
                    str(source),
                    str(out),
                    trackers=["http://tracker.invalid/announce"],
                    piece_length=32768,
                    generation=generation,
                )
                torrent = TorrentFile(result.output_path)
                self.assertEqual(
                    (torrent.is_v1, torrent.is_v2, torrent.is_hybrid), expected
                )
                self.assertGreater(result.piece_count, 0)
                if torrent.is_v1:
                    self.assertEqual(len(torrent.v1_info_hash), 20)
                if torrent.is_v2:
                    self.assertEqual(len(torrent.v2_info_hash), 32)

    def test_hybrid_virtual_padding_is_not_written_but_is_serviceable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "payload"
            source.mkdir()
            (source / "a.bin").write_bytes(b"A" * 1000)
            (source / "b.bin").write_bytes(b"B" * 1000)
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
            )
            self.assertTrue(session.piece_mgr.prepare_storage())
            self.assertTrue(session.piece_mgr.is_finished)
            first_piece = session.piece_mgr.pieces[0]
            self.assertEqual(first_piece.length, 1000)
            self.assertEqual(first_piece.padding_length, 15384)
            self.assertEqual(
                session.piece_mgr.read_block(0, 1000, 16, "v1"), b"\x00" * 16
            )
            self.assertEqual(session.piece_mgr.read_block(0, 1000, 16, "v2"), b"")
            self.assertFalse(any(path.name == ".pad" for path in source.rglob("*")))

    def test_protocol_policy_selects_compatible_swarms(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "payload.bin"
            source.write_bytes(b"policy" * 5000)
            path = root / "hybrid.torrent"
            TorrentCreator.create(
                str(source),
                str(path),
                trackers=["http://tracker.invalid/announce"],
                piece_length=16384,
                generation=TORRENT_GENERATION_HYBRID,
            )
            auto = TorrentSession(str(path), protocol_policy=TORRENT_PROTOCOL_AUTO)
            v1 = TorrentSession(str(path), protocol_policy=TORRENT_PROTOCOL_V1_ONLY)
            v2 = TorrentSession(str(path), protocol_policy=TORRENT_PROTOCOL_V2_ONLY)
            self.assertEqual(auto.active_generations, ("v1", "v2"))
            self.assertEqual(v1.active_generations, ("v1",))
            self.assertEqual(v2.active_generations, ("v2",))


if __name__ == "__main__":
    unittest.main(verbosity=2)
