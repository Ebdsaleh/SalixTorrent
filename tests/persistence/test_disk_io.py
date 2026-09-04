"""Asynchronous disk pipeline and cache regressions.

Regression lineage:
- introduced during the Phase 4 disk-I/O milestone.
"""

import asyncio
import hashlib
import os
import tempfile
import threading
import unittest
from types import SimpleNamespace

from app.logic.piece_manager import BLOCK_SIZE, PieceManager


def _torrent(payloads):
    piece_length = len(payloads[0])
    assert all(len(payload) == piece_length for payload in payloads)
    return SimpleNamespace(
        name="disk-pipeline-test.bin",
        total_length=piece_length * len(payloads),
        piece_length=piece_length,
        pieces=[hashlib.sha1(payload).digest() for payload in payloads],
        is_multi_file=False,
        files=[],
        hex_info_hash="44" * 20,
    )


class TestDiskPipeline(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def _manager(self, payloads):
        manager = PieceManager(_torrent(payloads), download_dir=self.temp_dir.name)
        manager._storage_prepared = True
        # Materialize an empty target so persisted-only resume state can also be
        # written while a verified piece is still waiting in the async buffer.
        os.makedirs(self.temp_dir.name, exist_ok=True)
        open(manager.output_path, "ab").close()
        return manager

    @staticmethod
    def _complete_piece(manager, piece_index, payload, peer_key="peer-a"):
        result = manager.receive_block(piece_index, 0, payload, peer_key=peer_key)
        if len(payload) > BLOCK_SIZE:
            raise AssertionError("test helper expects one-block pieces")
        return result

    async def test_write_behind_keeps_event_loop_responsive_and_persists(self):
        payload = b"A" * BLOCK_SIZE
        manager = self._manager([payload])
        await manager.start_disk_io()

        entered = threading.Event()
        release = threading.Event()
        original_write = manager._write_range

        def slow_write(offset, data):
            entered.set()
            release.wait(timeout=2.0)
            original_write(offset, data)

        manager._write_range = slow_write
        result = self._complete_piece(manager, 0, payload)
        self.assertTrue(result.piece_completed)
        self.assertFalse(manager.pieces[0].is_persisted)

        await manager.enqueue_completed_piece(0)
        await asyncio.to_thread(entered.wait, 1.0)

        # The disk thread is blocked, but asyncio remains free to run other work.
        heartbeat = False

        async def tick():
            nonlocal heartbeat
            await asyncio.sleep(0.01)
            heartbeat = True

        await tick()
        self.assertTrue(heartbeat)

        # Pending verified data is immediately seedable from memory.
        self.assertEqual(manager.read_block(0, 0, BLOCK_SIZE), payload)

        release.set()
        await manager.flush_disk_writes()
        self.assertTrue(manager.pieces[0].is_persisted)
        with open(manager.output_path, "rb") as handle:
            self.assertEqual(handle.read(), payload)

        stats = manager.disk_io_snapshot()
        self.assertEqual(stats["writes_completed"], 1)
        self.assertEqual(stats["bytes_written"], len(payload))
        self.assertGreaterEqual(stats["cache_hits"], 1)
        await manager.shutdown_disk_io()

    async def test_byte_bounded_buffer_applies_async_backpressure(self):
        payload_a = b"A" * BLOCK_SIZE
        payload_b = b"B" * BLOCK_SIZE
        manager = self._manager([payload_a, payload_b])
        manager._disk_write_buffer_limit = BLOCK_SIZE
        await manager.start_disk_io()

        first_entered = threading.Event()
        release_first = threading.Event()
        original_write = manager._write_range
        calls = 0

        def gated_write(offset, data):
            nonlocal calls
            calls += 1
            if calls == 1:
                first_entered.set()
                release_first.wait(timeout=2.0)
            original_write(offset, data)

        manager._write_range = gated_write

        self.assertTrue(self._complete_piece(manager, 0, payload_a).piece_completed)
        await manager.enqueue_completed_piece(0)
        await asyncio.to_thread(first_entered.wait, 1.0)

        self.assertTrue(self._complete_piece(manager, 1, payload_b, peer_key="peer-b").piece_completed)
        second_enqueue = asyncio.create_task(manager.enqueue_completed_piece(1))
        await asyncio.sleep(0.03)
        self.assertFalse(second_enqueue.done())
        self.assertEqual(manager.disk_io_snapshot()["backpressure_events"], 1)

        release_first.set()
        self.assertTrue(await asyncio.wait_for(second_enqueue, timeout=1.0))
        await manager.flush_disk_writes()
        stats = manager.disk_io_snapshot()
        self.assertEqual(stats["writes_completed"], 2)
        self.assertEqual(stats["pending_bytes"], 0)
        self.assertEqual(stats["pending_writes"], 0)
        self.assertGreater(stats["backpressure_seconds"], 0.0)
        await manager.shutdown_disk_io()

    async def test_recent_piece_cache_can_be_disabled_without_affecting_pending_reads(self):
        payload = b"H" * BLOCK_SIZE
        manager = PieceManager(
            _torrent([payload]),
            download_dir=self.temp_dir.name,
            enable_recent_piece_cache=False,
        )
        manager._storage_prepared = True
        open(manager.output_path, "ab").close()
        await manager.start_disk_io()

        self.assertTrue(self._complete_piece(manager, 0, payload).piece_completed)
        await manager.enqueue_completed_piece(0)
        # Pending write-behind data remains seedable even though the optional
        # post-write LRU cache itself is disabled.
        self.assertEqual(manager.read_block(0, 0, BLOCK_SIZE), payload)
        await manager.flush_disk_writes()
        stats = manager.disk_io_snapshot()
        self.assertFalse(stats["cache_enabled"])
        self.assertEqual(stats["cache_entries"], 0)
        await manager.shutdown_disk_io()

    async def test_recent_piece_cache_avoids_read_after_write_disk_io(self):
        payload = b"C" * BLOCK_SIZE
        manager = self._manager([payload])
        await manager.start_disk_io()
        self.assertTrue(self._complete_piece(manager, 0, payload).piece_completed)
        await manager.enqueue_completed_piece(0)
        await manager.flush_disk_writes()

        # If this falls through to storage the test should fail; a recently
        # written piece is expected to be served directly from the LRU cache.
        manager._read_range = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected disk read")
        )
        self.assertEqual(manager.read_block(0, 0, BLOCK_SIZE), payload)
        stats = manager.disk_io_snapshot()
        self.assertEqual(stats["cache_hits"], 1)
        self.assertEqual(stats["cache_misses"], 0)
        self.assertEqual(stats["cache_entries"], 1)
        await manager.shutdown_disk_io()

    async def test_resume_bitfield_excludes_verified_but_unpersisted_piece(self):
        payload = b"D" * BLOCK_SIZE
        manager = self._manager([payload])
        await manager.start_disk_io()
        self.assertTrue(self._complete_piece(manager, 0, payload).piece_completed)

        self.assertEqual(manager.completed_bitfield(), b"\x80")
        self.assertEqual(manager._build_persisted_bitfield(), b"\x00")
        self.assertEqual(manager.persisted_pieces, 0)

        await manager.enqueue_completed_piece(0)
        await manager.flush_disk_writes()
        self.assertEqual(manager._build_persisted_bitfield(), b"\x80")
        self.assertEqual(manager.persisted_pieces, 1)
        await manager.shutdown_disk_io()

    async def test_completion_waits_until_verified_piece_is_enqueued(self):
        payload = b"F" * BLOCK_SIZE
        manager = self._manager([payload])
        await manager.start_disk_io()

        self.assertTrue(self._complete_piece(manager, 0, payload).piece_completed)
        # Hash verification alone must not let the session lifecycle race ahead
        # of the byte-capacity reservation/enqueue step.
        self.assertFalse(manager.is_finished)
        self.assertFalse(manager.wanted_is_finished)

        await manager.enqueue_completed_piece(0)
        self.assertTrue(manager.is_finished)
        self.assertTrue(manager.wanted_is_finished)
        await manager.flush_disk_writes()
        await manager.shutdown_disk_io()

    async def test_shutdown_preserves_verified_piece_waiting_for_enqueue(self):
        payload = b"G" * BLOCK_SIZE
        manager = self._manager([payload])
        await manager.start_disk_io()
        self.assertTrue(self._complete_piece(manager, 0, payload).piece_completed)
        self.assertFalse(manager.is_finished)

        # Simulate Stop cancelling the peer task before it reaches its enqueue
        # await. Shutdown must recover that small staged set and persist it.
        await manager.shutdown_disk_io(flush=True)
        self.assertTrue(manager.pieces[0].is_persisted)
        with open(manager.output_path, "rb") as handle:
            self.assertEqual(handle.read(), payload)

    async def test_disk_failure_is_fail_closed_and_releases_buffer(self):
        payload = b"E" * BLOCK_SIZE
        manager = self._manager([payload])
        await manager.start_disk_io()

        def fail_write(_offset, _data):
            raise OSError("simulated disk full")

        manager._write_range = fail_write
        self.assertTrue(self._complete_piece(manager, 0, payload).piece_completed)
        await manager.enqueue_completed_piece(0)
        with self.assertRaises(OSError):
            await manager.flush_disk_writes()

        stats = manager.disk_io_snapshot()
        self.assertEqual(stats["write_failures"], 1)
        self.assertIn("simulated disk full", stats["error"])
        self.assertEqual(stats["pending_bytes"], 0)
        self.assertFalse(manager.pieces[0].is_complete)
        self.assertEqual(manager.downloaded_bytes, 0)
        with self.assertRaises(OSError):
            await manager.shutdown_disk_io()


if __name__ == "__main__":
    unittest.main(verbosity=2)
