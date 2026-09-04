"""Request-ownership, pipeline, Endgame, and CANCEL regressions.

Regression lineage:
- introduced during the Phase 2/3 request-scheduling milestones.
"""

import asyncio
import hashlib
import struct
import tempfile
import unittest
from types import SimpleNamespace

from app.logic.peer import PeerConnection, PeerMessageID
from app.logic.piece_manager import (
    BLOCK_SIZE,
    ENDGAME_BLOCK_THRESHOLD,
    ENDGAME_MAX_REQUESTERS_PER_BLOCK,
    PieceManager,
)
from app.logic.session import (
    REQUEST_PIPELINE_MAX,
    REQUEST_PIPELINE_MIN,
    REQUEST_TIMEOUT_SECONDS,
    TorrentSession,
    _UploadRequestState,
    request_pipeline_limit,
)


def _bitfield(piece_count, *piece_indices):
    raw = bytearray((piece_count + 7) // 8)
    for piece_index in piece_indices:
        raw[piece_index // 8] |= 1 << (7 - (piece_index % 8))
    return bytes(raw)


def _torrent(piece_length, payload=None):
    if payload is None:
        expected_hash = b"x" * 20
        total_length = piece_length
    else:
        expected_hash = hashlib.sha1(payload).digest()
        total_length = len(payload)
        piece_length = len(payload)
    return SimpleNamespace(
        name="request-scheduling-test.bin",
        total_length=total_length,
        piece_length=piece_length,
        pieces=[expected_hash],
        is_multi_file=False,
        files=[],
        hex_info_hash="23" * 20,
    )


class TestRequestOwnership(unittest.TestCase):
    def _manager(self, piece_length):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return PieceManager(_torrent(piece_length), download_dir=temp_dir.name)

    def _payload_manager(self, payload):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        manager = PieceManager(_torrent(len(payload), payload=payload), download_dir=temp_dir.name)
        manager._storage_prepared = True
        return manager

    def test_normal_mode_keeps_single_owner_per_block(self):
        manager = self._manager((ENDGAME_BLOCK_THRESHOLD + 8) * BLOCK_SIZE)
        bits = _bitfield(1, 0)
        manager.register_peer_bitfield("peer-a", bits)
        manager.register_peer_bitfield("peer-b", bits)

        first = manager.get_next_request(bits, peer_key="peer-a")
        self.assertIsNotNone(first)
        manager.mark_request_sent(first, "peer-a", sent_at=10.0)
        second = manager.get_next_request(bits, peer_key="peer-b")
        self.assertIsNotNone(second)

        self.assertNotEqual(first.offset, second.offset)
        self.assertEqual(len(first.requesters), 1)
        self.assertEqual(len(second.requesters), 1)
        self.assertFalse(manager.endgame_active)

    def test_endgame_duplicates_only_after_unique_tail_blocks_are_owned(self):
        manager = self._manager(2 * BLOCK_SIZE)
        bits = _bitfield(1, 0)
        for peer in ("peer-a", "peer-b", "peer-c"):
            manager.register_peer_bitfield(peer, bits)

        first = manager.get_next_request(bits, peer_key="peer-a")
        self.assertIsNotNone(first)
        manager.mark_request_sent(first, "peer-a", sent_at=10.0)

        second = manager.get_next_request(bits, peer_key="peer-b")
        self.assertIsNotNone(second)
        manager.mark_request_sent(second, "peer-b", sent_at=11.0)

        # The second peer must consume the other unrequested block before any
        # duplicate endgame request is permitted.
        self.assertNotEqual(first.offset, second.offset)

        duplicate = manager.get_next_request(bits, peer_key="peer-c")
        self.assertIsNotNone(duplicate)
        self.assertIn(duplicate.offset, {first.offset, second.offset})
        self.assertEqual(len(duplicate.requesters), 2)
        self.assertTrue(manager.endgame_active)

    def test_endgame_duplicate_fanout_is_bounded(self):
        manager = self._manager(BLOCK_SIZE)
        bits = _bitfield(1, 0)
        peers = [f"peer-{index}" for index in range(ENDGAME_MAX_REQUESTERS_PER_BLOCK + 1)]
        for peer in peers:
            manager.register_peer_bitfield(peer, bits)

        block = None
        for index, peer in enumerate(peers[:ENDGAME_MAX_REQUESTERS_PER_BLOCK]):
            chosen = manager.get_next_request(bits, peer_key=peer)
            self.assertIsNotNone(chosen)
            block = chosen
            manager.mark_request_sent(chosen, peer, sent_at=10.0 + index)

        self.assertIsNotNone(block)
        self.assertEqual(len(block.requesters), ENDGAME_MAX_REQUESTERS_PER_BLOCK)
        self.assertIsNone(
            manager.get_next_request(bits, peer_key=peers[-1])
        )

    def test_first_endgame_piece_cancels_other_block_owners(self):
        payload = b"E" * BLOCK_SIZE
        manager = self._payload_manager(payload)
        bits = _bitfield(1, 0)
        manager.register_peer_bitfield("peer-a", bits)
        manager.register_peer_bitfield("peer-b", bits)

        block_a = manager.get_next_request(bits, peer_key="peer-a")
        self.assertIsNotNone(block_a)
        manager.mark_request_sent(block_a, "peer-a", sent_at=10.0)
        block_b = manager.get_next_request(bits, peer_key="peer-b")
        self.assertIs(block_b, block_a)
        manager.mark_request_sent(block_b, "peer-b", sent_at=11.0)

        # Avoid touching the filesystem in this scheduler-focused unit test.
        manager._write_piece_to_disk = lambda piece: None
        result = manager.receive_block(0, 0, payload, peer_key="peer-a")

        self.assertTrue(result.accepted)
        self.assertTrue(result.piece_completed)
        self.assertEqual(result.cancel_peer_keys, ("peer-b",))
        self.assertEqual(manager.outstanding_request_count(), 0)
        self.assertEqual(manager.downloaded_bytes, len(payload))

    def test_timeout_releases_only_that_peers_ownership_for_reassignment(self):
        manager = self._manager(BLOCK_SIZE)
        bits = _bitfield(1, 0)
        manager.register_peer_bitfield("peer-a", bits)
        manager.register_peer_bitfield("peer-b", bits)

        block = manager.get_next_request(bits, peer_key="peer-a")
        self.assertIsNotNone(block)
        manager.mark_request_sent(block, "peer-a", sent_at=100.0)

        self.assertEqual(
            manager.expire_peer_requests(
                "peer-a",
                REQUEST_TIMEOUT_SECONDS,
                now=100.0 + REQUEST_TIMEOUT_SECONDS - 0.1,
            ),
            [],
        )
        expired = manager.expire_peer_requests(
            "peer-a",
            REQUEST_TIMEOUT_SECONDS,
            now=100.0 + REQUEST_TIMEOUT_SECONDS + 0.1,
        )
        self.assertEqual(expired, [block])
        self.assertFalse(block.requesters)

        # The worker keeps a short per-peer cooldown after a timeout so the
        # same stalled peer cannot instantly reacquire the exact same block.
        excluded = {(block.piece_index, block.offset): 999.0}
        self.assertIsNone(
            manager.get_next_request(
                bits,
                peer_key="peer-a",
                excluded_blocks=excluded,
            )
        )
        reassigned = manager.get_next_request(bits, peer_key="peer-b")
        self.assertIs(reassigned, block)

    def test_reserved_but_not_yet_sent_request_does_not_timeout(self):
        manager = self._manager(BLOCK_SIZE)
        bits = _bitfield(1, 0)
        manager.register_peer_bitfield("peer-a", bits)
        block = manager.get_next_request(bits, peer_key="peer-a")
        self.assertIsNotNone(block)
        self.assertEqual(block.requesters["peer-a"], 0.0)
        self.assertEqual(
            manager.expire_peer_requests("peer-a", 1.0, now=10_000.0),
            [],
        )

    def test_disconnect_cleanup_uses_peer_reverse_index(self):
        manager = self._manager(4 * BLOCK_SIZE)
        bits = _bitfield(1, 0)
        manager.register_peer_bitfield("peer-a", bits)
        blocks = [manager.get_next_request(bits, peer_key="peer-a") for _ in range(4)]
        self.assertTrue(all(blocks))
        self.assertEqual(manager.peer_outstanding_request_count("peer-a"), 4)

        manager.unregister_peer("peer-a")
        self.assertEqual(manager.peer_outstanding_request_count("peer-a"), 0)
        self.assertTrue(all(not block.requesters for block in blocks if block is not None))


class TestRequestPipeline(unittest.TestCase):
    def test_pipeline_is_adaptive_but_strictly_bounded(self):
        self.assertEqual(request_pipeline_limit(0.0), REQUEST_PIPELINE_MIN)
        self.assertEqual(request_pipeline_limit(-100.0), REQUEST_PIPELINE_MIN)
        self.assertGreaterEqual(request_pipeline_limit(2048.0), REQUEST_PIPELINE_MIN)
        self.assertLessEqual(request_pipeline_limit(2048.0), REQUEST_PIPELINE_MAX)
        self.assertEqual(request_pipeline_limit(10_000_000.0), REQUEST_PIPELINE_MAX)


class TestCancelWire(unittest.IsolatedAsyncioTestCase):
    async def test_send_cancel_uses_standard_message_id_8_frame(self):
        peer = PeerConnection(
            "127.0.0.1",
            6881,
            b"i" * 20,
            b"-ST0001-123456789012",
        )
        peer.is_connected = True
        peer.writer = object()
        captured = []

        async def capture(payload):
            captured.append(bytes(payload))
            return True

        peer._write_and_drain = capture
        self.assertTrue(await peer.send_cancel(7, 16384, 8192))
        self.assertEqual(
            captured,
            [struct.pack(">IBIII", 13, PeerMessageID.CANCEL, 7, 16384, 8192)],
        )

    async def test_read_message_parses_cancel(self):
        peer = PeerConnection(
            "127.0.0.1",
            6881,
            b"i" * 20,
            b"-ST0001-123456789012",
        )
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack(">IBIII", 13, PeerMessageID.CANCEL, 3, 0, BLOCK_SIZE))
        peer.reader = reader
        peer.is_connected = True

        message = await peer.read_message()
        self.assertEqual(message, ("CANCEL", (3, 0, BLOCK_SIZE)))

    async def test_receive_cancel_marks_pending_upload_as_inactive(self):
        state = _UploadRequestState()
        key = (1, 0, BLOCK_SIZE)
        state.active.add(key)
        state.queue.put_nowait(key)

        self.assertTrue(
            TorrentSession._cancel_queued_upload(state, 1, 0, BLOCK_SIZE)
        )
        self.assertNotIn(key, state.active)
        # The tiny queued tuple is intentionally left in place; the one per-peer
        # worker skips it without performing a disk read.
        self.assertEqual(state.queue.get_nowait(), key)

    async def test_endgame_completion_targets_cancel_to_other_owner_only(self):
        class FakePeer:
            def __init__(self):
                self.is_connected = True
                self.cancelled = []

            async def send_cancel(self, piece_index, begin, length):
                self.cancelled.append((piece_index, begin, length))
                return True

        session = object.__new__(TorrentSession)
        other_peer = FakePeer()
        owner_key = 222
        block = SimpleNamespace(piece_index=4, offset=BLOCK_SIZE, length=BLOCK_SIZE)
        block_key = (4, BLOCK_SIZE)
        session._download_peer_connections = {owner_key: other_peer}
        session._download_request_owners = {owner_key: {block_key: block}}

        await TorrentSession._cancel_duplicate_download_requests(
            session,
            4,
            BLOCK_SIZE,
            BLOCK_SIZE,
            (owner_key,),
        )

        self.assertEqual(
            other_peer.cancelled,
            [(4, BLOCK_SIZE, BLOCK_SIZE)],
        )
        self.assertNotIn(block_key, session._download_request_owners[owner_key])


if __name__ == "__main__":
    unittest.main(verbosity=2)
