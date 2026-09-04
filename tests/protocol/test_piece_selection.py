"""Piece-selection regressions.

Regression lineage:
- introduced during the Phase 1 rarest-first scheduling milestone.
"""

import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.logic.piece_manager import (
    FILE_PRIORITY_HIGH,
    FILE_PRIORITY_LOW,
    FILE_PRIORITY_NORMAL,
    PieceManager,
)


PIECE_LENGTH = 64 * 1024


def _bitfield(piece_count, *piece_indices):
    raw = bytearray((piece_count + 7) // 8)
    for piece_index in piece_indices:
        raw[piece_index // 8] |= 1 << (7 - (piece_index % 8))
    return bytes(raw)


def _torrent(piece_count=4, *, multi_file=False):
    total_length = piece_count * PIECE_LENGTH
    files = []
    if multi_file:
        files = [
            {"length": PIECE_LENGTH, "path": f"file_{index}.bin"}
            for index in range(piece_count)
        ]
    return SimpleNamespace(
        name="piece-selection-test.bin" if not multi_file else "piece-selection-test",
        total_length=total_length,
        piece_length=PIECE_LENGTH,
        pieces=[bytes([index + 1]) * 20 for index in range(piece_count)],
        is_multi_file=multi_file,
        files=files,
        hex_info_hash="00" * 20,
    )


class TestPieceSelection(unittest.TestCase):
    def _manager(self, piece_count=4, *, multi_file=False):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        manager = PieceManager(
            _torrent(piece_count, multi_file=multi_file),
            download_dir=temp_dir.name,
        )
        return manager

    def test_incremental_availability_tracks_bitfield_have_and_disconnect(self):
        manager = self._manager(4)
        manager.register_peer_bitfield("peer-a", _bitfield(4, 0, 1, 2))
        manager.register_peer_bitfield("peer-b", _bitfield(4, 0, 2))

        self.assertEqual(
            [manager.availability_count(index) for index in range(4)],
            [2, 1, 2, 0],
        )

        self.assertTrue(manager.record_peer_have("peer-b", 1))
        self.assertFalse(manager.record_peer_have("peer-b", 1))
        self.assertEqual(manager.availability_count(1), 2)

        manager.unregister_peer("peer-a")
        self.assertEqual(
            [manager.availability_count(index) for index in range(4)],
            [1, 1, 1, 0],
        )

    def test_rarest_first_selects_scarcest_piece_within_priority(self):
        manager = self._manager(3)
        target = _bitfield(3, 0, 1, 2)
        manager.register_peer_bitfield("target", target)
        manager.register_peer_bitfield("peer-b", _bitfield(3, 0, 2))
        manager.register_peer_bitfield("peer-c", _bitfield(3, 2))

        # Availability is piece 0=2, piece 1=1, piece 2=3.
        block = manager.get_next_request(target, peer_key="target")
        self.assertIsNotNone(block)
        self.assertEqual(block.piece_index, 1)


    def test_rarest_buckets_react_to_peer_departure_without_rebuild(self):
        manager = self._manager(2)
        target = _bitfield(2, 0, 1)
        manager.register_peer_bitfield("target", target)
        manager.register_peer_bitfield("peer-b", _bitfield(2, 0))

        first = manager.get_next_request(target, peer_key="target")
        self.assertIsNotNone(first)
        self.assertEqual(first.piece_index, 1)
        manager.release_requests([first])

        # HAVE/bitfield events make piece 1 common, then peer-b leaving makes
        # piece 0 the unique rarest piece. No full availability rebuild is
        # needed; each event updates only the pieces it changes.
        manager.register_peer_bitfield("peer-c", _bitfield(2, 1))
        manager.register_peer_bitfield("peer-d", _bitfield(2, 1))
        manager.unregister_peer("peer-b")
        manager._active_piece_indices.clear()
        second = manager.get_next_request(target, peer_key="target")
        self.assertIsNotNone(second)
        self.assertEqual(second.piece_index, 0)

    def test_file_priority_remains_stronger_than_rarity(self):
        manager = self._manager(3, multi_file=True)
        manager.set_file_priorities([
            FILE_PRIORITY_LOW,
            FILE_PRIORITY_HIGH,
            FILE_PRIORITY_NORMAL,
        ])

        target = _bitfield(3, 0, 1, 2)
        manager.register_peer_bitfield("target", target)
        manager.register_peer_bitfield("peer-b", _bitfield(3, 1, 2))
        manager.register_peer_bitfield("peer-c", _bitfield(3, 1))

        # Piece 0 is rarest (1 copy), but piece 1 belongs to a High-priority
        # file and must therefore win before Normal/Low rarity is considered.
        block = manager.get_next_request(target, peer_key="target")
        self.assertIsNotNone(block)
        self.assertEqual(block.piece_index, 1)

    def test_equal_rarity_ties_are_randomised(self):
        manager = self._manager(3)
        target = _bitfield(3, 0, 1, 2)
        manager.register_peer_bitfield("target", target)

        state = random.getstate()
        random.seed(12345)
        try:
            chosen = set()
            for _ in range(24):
                trial = self._manager(3)
                trial.register_peer_bitfield("target", target)
                block = trial.get_next_request(target, peer_key="target")
                self.assertIsNotNone(block)
                chosen.add(block.piece_index)
        finally:
            random.setstate(state)

        self.assertGreater(len(chosen), 1)


    def test_equal_rarity_pipeline_stays_on_started_piece(self):
        manager = self._manager(3)
        target = _bitfield(3, 0, 1, 2)
        manager.register_peer_bitfield("target", target)

        first = manager.get_next_request(target, peer_key="target")
        second = manager.get_next_request(target, peer_key="target")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(second.piece_index, first.piece_index)
        self.assertNotEqual(second.offset, first.offset)

    def test_piece_telemetry_uses_incremental_availability_cache(self):
        manager = self._manager(3)
        manager.register_peer_bitfield("peer-a", _bitfield(3, 0, 2))
        manager.register_peer_bitfield("peer-b", _bitfield(3, 2))

        snapshot = manager.build_piece_telemetry(detail_limit=3, map_cell_limit=3)
        availability = {
            item["index"]: item["availability"]
            for item in snapshot["details"]
        }
        self.assertEqual(availability, {0: 1, 1: 0, 2: 2})


    def test_piece_telemetry_keeps_legacy_bitfield_fallback(self):
        manager = self._manager(3)
        snapshot = manager.build_piece_telemetry(
            peer_bitfields=[_bitfield(3, 0, 2), _bitfield(3, 2)],
            detail_limit=3,
            map_cell_limit=3,
        )
        availability = {
            item["index"]: item["availability"]
            for item in snapshot["details"]
        }
        self.assertEqual(availability, {0: 1, 1: 0, 2: 2})


if __name__ == "__main__":
    unittest.main(verbosity=2)
