# app/logic/piece_manager.py

from __future__ import annotations

import asyncio
import base64
import bisect
import hashlib
import itertools
import json
import math
import os
import random
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional

from app.logic.torrent_file import TorrentFile
from app.logic.torrent_v2 import file_merkle_root, piece_layer_hashes_from_data

BLOCK_SIZE = 16384
RESUME_STATE_VERSION = 1
MULTI_FILE_RESUME_INTERVAL = 5.0

# Phase 4 disk pipeline. Verified pieces are queued to one asynchronous writer
# instead of blocking a peer worker on filesystem I/O. Memory is bounded by
# bytes, not item count, so unusual piece sizes cannot silently blow up RAM.
DISK_WRITE_BUFFER_BYTES = 64 * 1024 * 1024
RECENT_PIECE_CACHE_BYTES = 32 * 1024 * 1024

# Phase 2/3 request scheduling. Endgame only activates once a small tail of
# wanted blocks remains. Duplicate tail requests are bounded so completion
# latency improves without turning the final blocks into a bandwidth storm.
ENDGAME_BLOCK_THRESHOLD = 32
ENDGAME_MAX_REQUESTERS_PER_BLOCK = 3

_ANONYMOUS_REQUESTER = object()

FILE_PRIORITY_SKIP = "Don't Download"
FILE_PRIORITY_LOW = "Low"
FILE_PRIORITY_NORMAL = "Normal"
FILE_PRIORITY_HIGH = "High"
FILE_PRIORITIES = (
    FILE_PRIORITY_HIGH,
    FILE_PRIORITY_NORMAL,
    FILE_PRIORITY_LOW,
    FILE_PRIORITY_SKIP,
)
FILE_PRIORITY_RANK = {
    FILE_PRIORITY_SKIP: 0,
    FILE_PRIORITY_LOW: 1,
    FILE_PRIORITY_NORMAL: 2,
    FILE_PRIORITY_HIGH: 3,
}


class Block:
    def __init__(self, piece_index: int, offset: int, length: int):
        self.piece_index = piece_index
        self.offset = offset
        self.length = length
        self.data: Optional[bytes] = None
        # requester -> monotonic timestamp of the wire REQUEST. A timestamp of
        # 0.0 means the block has been reserved by the scheduler but bandwidth
        # throttling has not yet allowed the REQUEST frame to be transmitted.
        self.requesters: dict[object, float] = {}

    @property
    def is_requested(self) -> bool:
        """Compatibility view for UI/older callers: any owner means requested."""
        return bool(self.requesters)

    @is_requested.setter
    def is_requested(self, value: bool):
        # Keep the historical attribute writable for external callers while the
        # scheduler itself uses explicit requester ownership. Internal code never
        # relies on the anonymous owner.
        if value:
            if not self.requesters:
                self.requesters[_ANONYMOUS_REQUESTER] = 0.0
        else:
            self.requesters.clear()

    def requested_by(self, peer_key: object) -> bool:
        owner = _ANONYMOUS_REQUESTER if peer_key is None else peer_key
        return owner in self.requesters


@dataclass(frozen=True)
class BlockReceiveResult:
    accepted: bool = False
    piece_completed: bool = False
    duplicate: bool = False
    hash_failed: bool = False
    cancel_peer_keys: tuple[object, ...] = ()
    block: Optional[Block] = None


class Piece:
    def __init__(
        self,
        index: int,
        length: int,
        expected_hash: bytes = b"",
        *,
        expected_v2_hash: bytes = b"",
        v2_file_root: bytes = b"",
        verify_v2_file_root: bool = False,
        piece_length: int = 0,
        padding_length: int = 0,
        storage_offset: Optional[int] = None,
    ):
        self.index = index
        self.length = length
        self.expected_hash = bytes(expected_hash or b"")
        self.expected_v2_hash = bytes(expected_v2_hash or b"")
        self.v2_file_root = bytes(v2_file_root or b"")
        self.verify_v2_file_root = bool(verify_v2_file_root)
        self.piece_length = max(0, int(piece_length or length or 0))
        self.padding_length = max(0, int(padding_length or 0))
        self.storage_offset = (
            int(storage_offset) if storage_offset is not None else index * self.piece_length
        )
        self._blocks: Optional[List[Block]] = None
        self.is_complete: bool = False
        # A verified piece may briefly live in the bounded write-behind buffer
        # before reaching disk. Resume metadata records only persisted pieces.
        self.is_persisted: bool = False

    @property
    def blocks(self) -> List[Block]:
        """Create this piece's blocks only when the piece is actually needed."""
        if self._blocks is None:
            self._blocks = []
            num_blocks = math.ceil(self.length / BLOCK_SIZE)

            for index in range(num_blocks):
                offset = index * BLOCK_SIZE
                block_len = min(BLOCK_SIZE, self.length - offset)
                self._blocks.append(Block(self.index, offset, block_len))

        return self._blocks

    @property
    def blocks_initialized(self) -> bool:
        return self._blocks is not None

    def reset(self):
        self.is_complete = False
        self.is_persisted = False

        if self._blocks is None:
            return

        for block in self._blocks:
            block.data = None
            block.is_requested = False

    def reset_requests(self):
        if self._blocks is None:
            return

        for block in self._blocks:
            if block.data is None:
                block.is_requested = False

    def is_all_blocks_received(self) -> bool:
        if self._blocks is None:
            return False
        return all(block.data is not None for block in self._blocks)

    def get_data(self) -> bytes:
        if self._blocks is None:
            return b""
        return b"".join(
            block.data
            for block in self._blocks
            if block.data is not None
        )

    def received_byte_count(self) -> int:
        if self._blocks is None:
            return 0
        return sum(
            len(block.data)
            for block in self._blocks
            if block.data is not None
        )

    def verify_data(self, data: bytes) -> bool:
        data = bytes(data)
        if len(data) != self.length:
            return False

        if self.expected_hash:
            v1_data = data + (b"\x00" * self.padding_length)
            if hashlib.sha1(v1_data).digest() != self.expected_hash:
                return False

        if self.verify_v2_file_root:
            if not self.v2_file_root or file_merkle_root(data) != self.v2_file_root:
                return False
        elif self.expected_v2_hash:
            hashes = piece_layer_hashes_from_data(data, self.piece_length)
            if len(hashes) != 1 or hashes[0] != self.expected_v2_hash:
                return False

        return bool(self.expected_hash or self.expected_v2_hash or self.verify_v2_file_root)

    def verify_hash(self) -> bool:
        return self.verify_data(self.get_data())

    def wire_length(self, generation: str = "v1") -> int:
        if str(generation).lower() == "v1":
            return self.length + self.padding_length
        return self.length


@dataclass(frozen=True)
class StorageFile:
    path: str
    relative_path: str
    length: int
    start: int
    end: int


class PieceManager:
    """Coordinates pieces, disk storage, verification and fast resume.

    Normal downloads use downloads/<torrent name>. A torrent created locally
    can instead be attached to an external read-only source file/folder; that
    source is verified and seeded in place without being copied to downloads/.
    Multi-file torrents are always treated as one contiguous BitTorrent byte
    stream when pieces cross file boundaries.
    """

    def __init__(
        self,
        torrent: TorrentFile,
        download_dir: str = "downloads",
        seed_source_path: Optional[str] = None,
        *,
        disk_write_buffer_bytes: int = DISK_WRITE_BUFFER_BYTES,
        recent_piece_cache_bytes: int = RECENT_PIECE_CACHE_BYTES,
        enable_recent_piece_cache: bool = True,
    ):
        self.torrent = torrent
        self.download_dir = download_dir
        self.output_path = os.path.join(download_dir, torrent.name)
        self.seed_source_path = (
            os.path.abspath(os.path.expanduser(seed_source_path))
            if seed_source_path
            else ""
        )
        self.read_only_seed_source = bool(self.seed_source_path)
        self.last_error: str = ""

        self.resume_dir = os.path.join(download_dir, ".salix_resume")
        self.resume_path = os.path.join(
            self.resume_dir,
            f"{torrent.hex_info_hash}.json",
        )

        self.pieces: List[Piece] = []
        self.downloaded_bytes: int = 0

        self._storage_prepared = False
        self._prepare_lock = threading.Lock()
        self._resume_lock = threading.Lock()
        self._last_resume_save_time = 0.0

        self.check_progress: float = 0.0
        self.check_checked_pieces: int = 0
        self.check_total_pieces: int = 0
        self.fast_resume_used: bool = False

        self._storage_files: List[StorageFile] = []
        self._storage_starts: List[int] = []

        self._initialize_pieces()
        self._initialize_storage_files()

        # Per-file download priorities. These are local user preferences rather
        # than .torrent metadata, so TorrentManager persists them in session
        # state and restores them when SalixTorrent starts again.
        self.file_priorities: List[str] = [
            FILE_PRIORITY_NORMAL for _ in self._storage_files
        ]
        self._piece_priority_ranks: List[int] = []

        # Phase 1 scheduler state. Peer availability is maintained incrementally
        # from BITFIELD/HAVE/connect/disconnect events. Rarity buckets let the
        # hot request path avoid rebuilding or sorting a torrent-wide histogram
        # for every 16 KiB block request.
        self._piece_availability: List[int] = [0] * len(self.pieces)
        self._peer_piece_sets: dict[object, set[int]] = {}
        self._persisted_bitfield = bytearray(math.ceil(len(self.pieces) / 8))
        self._persisted_pieces_count: int = 0
        self._persisted_bytes_count: int = 0
        self._active_piece_indices: set[int] = set()

        # Explicit block-request ownership. Each peer normally owns a block
        # exclusively; endgame can add a small bounded set of duplicate owners.
        # The reverse index means disconnect/timeout cleanup touches only that
        # peer's small pipeline rather than scanning the torrent.
        self._requests_by_peer: dict[object, set[Block]] = {}

        # Phase 4: bounded write-behind + recent-piece read cache. The asyncio
        # queue/condition exist only while a session run is active. Pending
        # piece bytes are pinned until their disk write completes; after that
        # they may move into the optional LRU read cache. Cache/state access can
        # also come from upload threads, so only the tiny dictionaries/counters
        # are protected by a normal lock.
        try:
            requested_write_buffer = max(1, int(disk_write_buffer_bytes))
        except (TypeError, ValueError):
            requested_write_buffer = DISK_WRITE_BUFFER_BYTES
        try:
            requested_read_cache = max(0, int(recent_piece_cache_bytes))
        except (TypeError, ValueError):
            requested_read_cache = RECENT_PIECE_CACHE_BYTES

        self._disk_write_buffer_limit = max(
            requested_write_buffer,
            int(getattr(self.torrent, "piece_length", 0) or 0),
        )
        self._recent_piece_cache_limit = requested_read_cache
        self._recent_piece_cache_enabled = bool(
            enable_recent_piece_cache and requested_read_cache > 0
        )
        self._disk_queue: Optional[asyncio.Queue] = None
        self._disk_condition: Optional[asyncio.Condition] = None
        self._disk_worker_task: Optional[asyncio.Task] = None
        self._disk_pending_bytes: int = 0
        self._disk_pending_writes: int = 0
        self._disk_state_lock = threading.Lock()
        self._pending_piece_data: dict[int, bytes] = {}
        self._disk_unqueued_verified: set[int] = set()
        self._recent_piece_cache: OrderedDict[int, bytes] = OrderedDict()
        self._recent_piece_cache_bytes: int = 0
        self._disk_writes_completed: int = 0
        self._disk_bytes_written: int = 0
        self._disk_write_failures: int = 0
        self._disk_write_latency_total: float = 0.0
        self._disk_write_latency_last: float = 0.0
        self._disk_write_latency_max: float = 0.0
        self._disk_backpressure_events: int = 0
        self._disk_backpressure_seconds: float = 0.0
        self._disk_cache_hits: int = 0
        self._disk_cache_misses: int = 0
        self._disk_error: str = ""

        self._rarity_buckets: dict[int, dict[int, set[int]]] = {
            FILE_PRIORITY_RANK[FILE_PRIORITY_HIGH]: {},
            FILE_PRIORITY_RANK[FILE_PRIORITY_NORMAL]: {},
            FILE_PRIORITY_RANK[FILE_PRIORITY_LOW]: {},
        }
        self._rebuild_piece_priority_cache()

    def _initialize_pieces(self):
        if bool(getattr(self.torrent, "is_v2", False)):
            for descriptor in self.torrent.v2_piece_map:
                index = int(descriptor["index"])
                expected_sha1 = (
                    self.torrent.pieces[index]
                    if bool(getattr(self.torrent, "is_v1", True)) and index < len(self.torrent.pieces)
                    else b""
                )
                padding = (
                    self.torrent.hybrid_piece_padding[index]
                    if self.torrent.is_hybrid and index < len(self.torrent.hybrid_piece_padding)
                    else 0
                )
                self.pieces.append(
                    Piece(
                        index,
                        int(descriptor["length"]),
                        expected_sha1,
                        expected_v2_hash=descriptor.get("expected_piece_hash", b""),
                        v2_file_root=descriptor.get("pieces_root", b""),
                        verify_v2_file_root=bool(descriptor.get("verify_file_root")),
                        piece_length=self.torrent.piece_length,
                        padding_length=padding,
                        storage_offset=int(descriptor["payload_offset"]),
                    )
                )
            return

        total_remaining = self.torrent.total_length
        for index, expected_hash in enumerate(self.torrent.pieces):
            piece_len = min(self.torrent.piece_length, total_remaining)
            self.pieces.append(
                Piece(
                    index,
                    piece_len,
                    expected_hash,
                    piece_length=self.torrent.piece_length,
                    storage_offset=index * self.torrent.piece_length,
                )
            )
            total_remaining -= piece_len

    def _initialize_storage_files(self):
        current_offset = 0
        backing_root = self.seed_source_path or self.output_path

        if not self.torrent.is_multi_file:
            single_path = self.seed_source_path or self.output_path
            self._storage_files = [
                StorageFile(
                    path=single_path,
                    relative_path=self.torrent.name,
                    length=self.torrent.total_length,
                    start=0,
                    end=self.torrent.total_length,
                )
            ]
            self._storage_starts = [0]
            return

        root = backing_root
        for file_entry in self.torrent.files:
            length = int(file_entry["length"])
            relative_path = str(file_entry["path"])
            full_path = os.path.join(root, relative_path)
            self._storage_files.append(
                StorageFile(
                    path=full_path,
                    relative_path=relative_path,
                    length=length,
                    start=current_offset,
                    end=current_offset + length,
                )
            )
            current_offset += length

        self._storage_starts = [item.start for item in self._storage_files]

    @staticmethod
    def normalise_file_priority(priority: object) -> str:
        value = str(priority or "").strip()
        return value if value in FILE_PRIORITY_RANK else FILE_PRIORITY_NORMAL

    def _file_indices_for_piece(self, piece_index: int) -> List[int]:
        """Return every payload file overlapped by one BitTorrent piece."""
        if piece_index < 0 or piece_index >= len(self.pieces) or not self._storage_files:
            return []

        if bool(getattr(self.torrent, "is_v2", False)) and piece_index < len(self.torrent.v2_piece_map):
            return [int(self.torrent.v2_piece_map[piece_index]["file_index"])]

        piece = self.pieces[piece_index]
        start = piece.storage_offset
        end = min(self.torrent.total_length, start + piece.length)
        index = self._storage_index_for_offset(start)
        result: List[int] = []

        while 0 <= index < len(self._storage_files):
            item = self._storage_files[index]
            if item.start >= end:
                break
            if item.end > start:
                result.append(index)
            index += 1

        return result

    def _rebuild_piece_priority_cache(self):
        """Collapse file preferences into one scheduler priority per piece.

        A piece can straddle file boundaries. The highest-priority wanted file
        wins. A piece is skipped only when every overlapping file is marked
        Don't Download, because boundary bytes may still be required to finish
        a wanted neighbouring file.
        """
        ranks: List[int] = [0] * len(self.pieces)

        for piece_index in range(len(self.pieces)):
            file_indices = self._file_indices_for_piece(piece_index)
            if not file_indices:
                ranks[piece_index] = FILE_PRIORITY_RANK[FILE_PRIORITY_NORMAL]
                continue

            ranks[piece_index] = max(
                FILE_PRIORITY_RANK.get(
                    self.file_priorities[file_index],
                    FILE_PRIORITY_RANK[FILE_PRIORITY_NORMAL],
                )
                for file_index in file_indices
            )

        self._piece_priority_ranks = ranks
        if hasattr(self, "_rarity_buckets"):
            self._rebuild_rarity_buckets()

    def _rebuild_rarity_buckets(self):
        """Rebuild scheduler buckets after bulk priority/completion changes.

        This is intentionally reserved for infrequent operations such as file-
        priority edits, fast-resume application, and force rechecks. Normal peer
        churn updates only the affected pieces incrementally.
        """
        self._rarity_buckets = {
            FILE_PRIORITY_RANK[FILE_PRIORITY_HIGH]: {},
            FILE_PRIORITY_RANK[FILE_PRIORITY_NORMAL]: {},
            FILE_PRIORITY_RANK[FILE_PRIORITY_LOW]: {},
        }

        for piece_index, piece in enumerate(self.pieces):
            if piece.is_complete:
                continue
            rank = self.piece_priority_rank(piece_index)
            if rank <= 0:
                continue
            availability = self._piece_availability[piece_index]
            self._rarity_buckets[rank].setdefault(availability, set()).add(piece_index)

    def _move_rarity_piece(self, piece_index: int, old_availability: int, new_availability: int):
        """Move one incomplete wanted piece between cached rarity buckets."""
        if piece_index < 0 or piece_index >= len(self.pieces):
            return
        piece = self.pieces[piece_index]
        if piece.is_complete:
            return
        rank = self.piece_priority_rank(piece_index)
        if rank <= 0:
            return

        buckets = self._rarity_buckets.setdefault(rank, {})
        old_bucket = buckets.get(old_availability)
        if old_bucket is not None:
            old_bucket.discard(piece_index)
            if not old_bucket:
                buckets.pop(old_availability, None)

        buckets.setdefault(new_availability, set()).add(piece_index)

    def _remove_from_rarity_buckets(self, piece_index: int):
        if piece_index < 0 or piece_index >= len(self.pieces):
            return
        rank = self.piece_priority_rank(piece_index)
        if rank <= 0:
            return
        availability = self._piece_availability[piece_index]
        bucket = self._rarity_buckets.get(rank, {}).get(availability)
        if bucket is None:
            return
        bucket.discard(piece_index)
        if not bucket:
            self._rarity_buckets.get(rank, {}).pop(availability, None)
        self._active_piece_indices.discard(piece_index)

    def _piece_set_from_bitfield(self, bitfield: object) -> set[int]:
        """Decode one peer bitfield once, without allocating per-piece objects."""
        if not bitfield or not self.pieces:
            return set()
        try:
            raw = bytes(bitfield)
        except Exception:
            return set()

        total_pieces = len(self.pieces)
        result: set[int] = set()
        max_bytes = min(len(raw), (total_pieces + 7) // 8)
        for byte_index in range(max_bytes):
            value = raw[byte_index]
            if not value:
                continue
            base_piece = byte_index * 8
            for bit_offset in range(8):
                piece_index = base_piece + bit_offset
                if piece_index >= total_pieces:
                    break
                if value & (1 << (7 - bit_offset)):
                    result.add(piece_index)
        return result

    def register_peer_bitfield(self, peer_key: object, bitfield: object):
        """Replace one peer's advertised pieces and update rarity incrementally."""
        if peer_key is None:
            return
        new_pieces = self._piece_set_from_bitfield(bitfield)
        old_pieces = self._peer_piece_sets.get(peer_key, set())

        for piece_index in old_pieces - new_pieces:
            old_value = self._piece_availability[piece_index]
            new_value = max(0, old_value - 1)
            self._piece_availability[piece_index] = new_value
            self._move_rarity_piece(piece_index, old_value, new_value)

        for piece_index in new_pieces - old_pieces:
            old_value = self._piece_availability[piece_index]
            new_value = old_value + 1
            self._piece_availability[piece_index] = new_value
            self._move_rarity_piece(piece_index, old_value, new_value)

        self._peer_piece_sets[peer_key] = new_pieces

    def record_peer_have(self, peer_key: object, piece_index: int) -> bool:
        """Record a BEP-3 HAVE event; duplicate HAVE messages are idempotent."""
        if peer_key is None or piece_index < 0 or piece_index >= len(self.pieces):
            return False
        peer_pieces = self._peer_piece_sets.setdefault(peer_key, set())
        if piece_index in peer_pieces:
            return False

        peer_pieces.add(piece_index)
        old_value = self._piece_availability[piece_index]
        new_value = old_value + 1
        self._piece_availability[piece_index] = new_value
        self._move_rarity_piece(piece_index, old_value, new_value)
        return True

    def unregister_peer(self, peer_key: object):
        """Remove one peer's availability and any outstanding block ownership."""
        self.release_peer_requests(peer_key)
        peer_pieces = self._peer_piece_sets.pop(peer_key, None)
        if not peer_pieces:
            return
        for piece_index in peer_pieces:
            old_value = self._piece_availability[piece_index]
            new_value = max(0, old_value - 1)
            self._piece_availability[piece_index] = new_value
            self._move_rarity_piece(piece_index, old_value, new_value)

    def clear_peer_availability(self):
        """Reset transient swarm rarity state when a session is torn down."""
        if not self._peer_piece_sets and not any(self._piece_availability):
            return
        self._peer_piece_sets.clear()
        self._piece_availability = [0] * len(self.pieces)
        self._rebuild_rarity_buckets()

    def availability_count(self, piece_index: int) -> int:
        if piece_index < 0 or piece_index >= len(self._piece_availability):
            return 0
        return int(self._piece_availability[piece_index])

    def get_file_priorities(self) -> List[str]:
        return list(self.file_priorities)

    def set_file_priorities(self, priorities: object) -> bool:
        """Restore/replace all file priorities from persistent session state."""
        if not isinstance(priorities, (list, tuple)):
            return False

        changed = False
        for index in range(len(self.file_priorities)):
            if index >= len(priorities):
                break
            priority = self.normalise_file_priority(priorities[index])
            if self.file_priorities[index] != priority:
                self.file_priorities[index] = priority
                changed = True

        if changed:
            self._rebuild_piece_priority_cache()
        return changed

    def set_file_priority(self, file_index: int, priority: object) -> bool:
        try:
            file_index = int(file_index)
        except (TypeError, ValueError):
            return False

        if file_index < 0 or file_index >= len(self.file_priorities):
            return False

        priority = self.normalise_file_priority(priority)
        if self.file_priorities[file_index] == priority:
            return False

        self.file_priorities[file_index] = priority
        self._rebuild_piece_priority_cache()
        return True

    def is_piece_wanted(self, piece_index: int) -> bool:
        return self.piece_priority_rank(piece_index) > 0

    def piece_priority_rank(self, piece_index: int) -> int:
        if piece_index < 0 or piece_index >= len(self._piece_priority_ranks):
            return 0
        return int(self._piece_priority_ranks[piece_index])

    def piece_priority_name(self, piece_index: int) -> str:
        rank = self.piece_priority_rank(piece_index)
        for name, value in FILE_PRIORITY_RANK.items():
            if value == rank:
                return name
        return FILE_PRIORITY_NORMAL

    @property
    def wanted_piece_count(self) -> int:
        return sum(1 for rank in self._piece_priority_ranks if rank > 0)

    @property
    def completed_wanted_pieces(self) -> int:
        with self._disk_state_lock:
            staged = set(self._disk_unqueued_verified)
        return sum(
            1
            for index, piece in enumerate(self.pieces)
            if self.piece_priority_rank(index) > 0
            and piece.is_complete
            and index not in staged
        )

    @property
    def wanted_progress(self) -> float:
        total = self.wanted_piece_count
        if total <= 0:
            return 1.0
        return self.completed_wanted_pieces / total

    @property
    def wanted_is_finished(self) -> bool:
        with self._disk_state_lock:
            staged = set(self._disk_unqueued_verified)
        return all(
            piece.is_complete and index not in staged
            for index, piece in enumerate(self.pieces)
            if self.piece_priority_rank(index) > 0
        )

    @property
    def storage_prepared(self) -> bool:
        return self._storage_prepared

    @property
    def storage_mode(self) -> str:
        return "External Seed" if self.read_only_seed_source else "Download"

    @property
    def backing_path(self) -> str:
        return self.seed_source_path or self.output_path

    def _set_check_progress(self, checked: int, total: int):
        total = max(0, int(total))
        checked = max(0, min(int(checked), total if total else 0))

        self.check_checked_pieces = checked
        self.check_total_pieces = total
        self.check_progress = 1.0 if total == 0 else max(0.0, min(1.0, checked / total))

    def _wait_if_paused(
        self,
        cancel_event: Optional[threading.Event],
        pause_event: Optional[threading.Event],
    ) -> bool:
        if pause_event is None:
            return not (cancel_event and cancel_event.is_set())

        while not pause_event.is_set():
            if cancel_event and cancel_event.is_set():
                return False
            pause_event.wait(timeout=0.1)

        return not (cancel_event and cancel_event.is_set())

    def _payload_exists(self) -> bool:
        if bool(getattr(self.torrent, "is_v2", False)):
            candidates = []
            for piece in self.pieces:
                if piece.index >= len(self.torrent.v2_piece_map):
                    continue
                descriptor = self.torrent.v2_piece_map[piece.index]
                file_index = int(descriptor["file_index"])
                if not (0 <= file_index < len(self._storage_files)):
                    continue
                item = self._storage_files[file_index]
                try:
                    actual = min(os.path.getsize(item.path), item.length)
                except OSError:
                    continue
                required = int(descriptor["file_offset"]) + piece.length
                if actual >= required:
                    candidates.append(piece.index)
            return candidates

        if not self.torrent.is_multi_file:
            return bool(self._storage_files) and os.path.isfile(self._storage_files[0].path)

        root = self.seed_source_path or self.output_path
        if not os.path.isdir(root):
            return False

        # A folder torrent may legitimately contain only zero-byte files.
        if not self._storage_files:
            return os.path.isdir(root)
        return any(os.path.exists(item.path) for item in self._storage_files)

    def _create_empty_storage(self):
        if self.read_only_seed_source:
            raise OSError("External seed sources are read-only and cannot be created by SalixTorrent.")

        os.makedirs(self.download_dir, exist_ok=True)

        if not self.torrent.is_multi_file:
            with open(self.output_path, "wb"):
                pass
            return

        os.makedirs(self.output_path, exist_ok=True)
        # Materialize zero-length files now. Non-empty files are created lazily
        # when their first verified piece segment is written.
        for item in self._storage_files:
            if item.length != 0:
                continue
            os.makedirs(os.path.dirname(item.path), exist_ok=True)
            with open(item.path, "ab"):
                pass

    def _storage_index_for_offset(self, offset: int) -> int:
        if not self._storage_files:
            return -1

        index = bisect.bisect_right(self._storage_starts, offset) - 1
        index = max(0, index)

        while index < len(self._storage_files) and self._storage_files[index].end <= offset:
            index += 1
        return index if index < len(self._storage_files) else -1

    def _read_range(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset + length > self.torrent.total_length:
            return b""
        if length == 0:
            return b""

        if not self.torrent.is_multi_file:
            single_path = self._storage_files[0].path if self._storage_files else self.output_path
            if not os.path.exists(single_path):
                return b""
            try:
                with open(single_path, "rb") as file_handle:
                    file_handle.seek(offset)
                    data = file_handle.read(length)
                return data if len(data) == length else b""
            except OSError:
                return b""

        result = bytearray()
        current = offset
        end = offset + length
        index = self._storage_index_for_offset(current)

        while current < end and index >= 0 and index < len(self._storage_files):
            item = self._storage_files[index]
            if item.length == 0 or current >= item.end:
                index += 1
                continue
            if current < item.start:
                return b""

            segment_end = min(end, item.end)
            segment_length = segment_end - current
            local_offset = current - item.start

            if not os.path.exists(item.path):
                return b""

            try:
                with open(item.path, "rb") as file_handle:
                    file_handle.seek(local_offset)
                    chunk = file_handle.read(segment_length)
            except OSError:
                return b""

            if len(chunk) != segment_length:
                return b""

            result.extend(chunk)
            current = segment_end
            index += 1

        return bytes(result) if len(result) == length else b""

    def _write_range(self, offset: int, data: bytes):
        if offset < 0 or offset + len(data) > self.torrent.total_length:
            raise ValueError("Attempted to write outside the torrent payload range.")
        if not data:
            return
        if self.read_only_seed_source:
            raise OSError("Refusing to write into an external seed source.")

        if not self.torrent.is_multi_file:
            os.makedirs(self.download_dir, exist_ok=True)
            if not os.path.exists(self.output_path):
                with open(self.output_path, "wb"):
                    pass
            with open(self.output_path, "r+b") as file_handle:
                file_handle.seek(offset)
                file_handle.write(data)
            return

        os.makedirs(self.output_path, exist_ok=True)
        current = offset
        data_offset = 0
        end = offset + len(data)
        index = self._storage_index_for_offset(current)

        while current < end and index >= 0 and index < len(self._storage_files):
            item = self._storage_files[index]
            if item.length == 0 or current >= item.end:
                index += 1
                continue
            if current < item.start:
                raise OSError("Torrent storage mapping contains a gap.")

            segment_end = min(end, item.end)
            segment_length = segment_end - current
            local_offset = current - item.start
            chunk = data[data_offset:data_offset + segment_length]

            os.makedirs(os.path.dirname(item.path), exist_ok=True)
            mode = "r+b" if os.path.exists(item.path) else "w+b"
            with open(item.path, mode) as file_handle:
                file_handle.seek(local_offset)
                file_handle.write(chunk)

            current = segment_end
            data_offset += segment_length
            index += 1

        if data_offset != len(data):
            raise OSError("Could not map the complete piece into torrent storage.")

    def _candidate_piece_indices(self) -> List[int]:
        if not self.pieces:
            return []

        if not self.torrent.is_multi_file:
            single_path = self._storage_files[0].path if self._storage_files else self.backing_path
            if not os.path.exists(single_path):
                return []
            file_size = os.path.getsize(single_path)
            if file_size <= 0:
                return []
            capped = min(file_size, self.torrent.total_length)
            count = (capped + self.torrent.piece_length - 1) // self.torrent.piece_length
            return list(range(min(len(self.pieces), count)))

        # BEP-52 addresses pieces per-file and aligns every file to a piece
        # boundary on the wire.  Our physical storage deliberately omits the
        # BEP-47 padding used by hybrid torrents, so a piece index can no longer
        # be derived from ``physical_offset // piece_length``.  Use the v2 piece
        # map instead: it retains the owning file and in-file byte range while
        # ``payload_offset`` remains the compact, padding-free disk offset.
        if bool(getattr(self.torrent, "is_v2", False)):
            candidates = []
            for descriptor in getattr(self.torrent, "v2_piece_map", ()):
                try:
                    piece_index = int(descriptor["index"])
                    file_index = int(descriptor["file_index"])
                    file_offset = int(descriptor["file_offset"])
                    piece_length = int(descriptor["length"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not (0 <= piece_index < len(self.pieces)):
                    continue
                if not (0 <= file_index < len(self._storage_files)):
                    continue
                item = self._storage_files[file_index]
                if item.length <= 0 or not os.path.exists(item.path):
                    continue
                try:
                    actual = min(os.path.getsize(item.path), item.length)
                except OSError:
                    continue
                if actual >= file_offset + piece_length:
                    candidates.append(piece_index)
            return candidates

        candidates = set()
        for item in self._storage_files:
            if item.length <= 0 or not os.path.exists(item.path):
                continue
            try:
                actual = min(os.path.getsize(item.path), item.length)
            except OSError:
                continue
            if actual <= 0:
                continue

            first = item.start // self.torrent.piece_length
            last_byte = item.start + actual - 1
            last = last_byte // self.torrent.piece_length
            for piece_index in range(first, min(last + 1, len(self.pieces))):
                candidates.add(piece_index)

        return sorted(candidates)

    def _multi_payload_signature(self) -> str:
        hasher = hashlib.sha256()

        for item in self._storage_files:
            relative = item.relative_path.replace("\\", "/").encode("utf-8", errors="surrogatepass")
            hasher.update(len(relative).to_bytes(4, "big"))
            hasher.update(relative)
            hasher.update(int(item.length).to_bytes(8, "big", signed=False))

            try:
                stat = os.stat(item.path)
                hasher.update(b"1")
                hasher.update(int(stat.st_size).to_bytes(8, "big", signed=False))
                hasher.update(int(stat.st_mtime_ns).to_bytes(8, "big", signed=False))
            except OSError:
                hasher.update(b"0")

        return hasher.hexdigest()

    def _multi_physical_bytes(self) -> int:
        total = 0
        for item in self._storage_files:
            try:
                total += min(os.path.getsize(item.path), item.length)
            except OSError:
                pass
        return total

    def prepare_storage(
        self,
        cancel_event: Optional[threading.Event] = None,
        progress_callback: Optional[Callable[[], None]] = None,
        pause_event: Optional[threading.Event] = None,
    ) -> bool:
        with self._prepare_lock:
            if self._storage_prepared:
                self._set_check_progress(self.check_total_pieces, self.check_total_pieces)
                if progress_callback:
                    progress_callback()
                return True

            if cancel_event and cancel_event.is_set():
                return False
            if not self._wait_if_paused(cancel_event, pause_event):
                return False

            os.makedirs(self.download_dir, exist_ok=True)

            if not self._payload_exists():
                self._delete_resume_state()
                self.downloaded_bytes = 0
                self.fast_resume_used = False
                self._set_check_progress(0, 0)

                if self.read_only_seed_source:
                    self.last_error = (
                        "Seed source is unavailable: "
                        f"{self.seed_source_path}"
                    )
                    if progress_callback:
                        progress_callback()
                    return False

                self._create_empty_storage()
                self._storage_prepared = True
                if progress_callback:
                    progress_callback()
                return True

            if self._load_resume_state():
                if self.read_only_seed_source and not self.is_finished:
                    # An external seed must represent the complete payload. A
                    # partial resume record is not sufficient evidence.
                    for piece in self.pieces:
                        piece.is_complete = False
                        piece.is_persisted = False
                    self.downloaded_bytes = 0
                    self._rebuild_persisted_cache()
                else:
                    self.fast_resume_used = True
                    self._set_check_progress(len(self.pieces), len(self.pieces))
                    self._storage_prepared = True
                    self.last_error = ""
                    if progress_callback:
                        progress_callback()
                    return True

            self.fast_resume_used = False
            completed = self._check_existing_pieces(
                cancel_event=cancel_event,
                progress_callback=progress_callback,
                pause_event=pause_event,
            )

            if completed:
                self._storage_prepared = True

                if self.read_only_seed_source and not self.is_finished:
                    self.last_error = (
                        "The selected seed source does not match every piece in "
                        "this .torrent. The source was left untouched."
                    )
                    return False

                self.last_error = ""
                self.save_resume_state(force=True)

            return completed

    def _check_existing_pieces(
        self,
        cancel_event: Optional[threading.Event] = None,
        progress_callback: Optional[Callable[[], None]] = None,
        pause_event: Optional[threading.Event] = None,
    ) -> bool:
        if not self._payload_exists():
            self._set_check_progress(0, 0)
            return True

        self.downloaded_bytes = 0
        for piece in self.pieces:
            piece.is_complete = False
            piece.is_persisted = False

        candidates = self._candidate_piece_indices()
        self._set_check_progress(0, len(candidates))

        if progress_callback:
            progress_callback()
        if not candidates:
            return True

        last_callback_time = time.monotonic()
        last_reported_percent = -1

        for scan_index, piece_index in enumerate(candidates):
            if cancel_event and cancel_event.is_set():
                return False
            if not self._wait_if_paused(cancel_event, pause_event):
                return False

            piece = self.pieces[piece_index]
            file_offset = piece.storage_offset
            data = self._read_range(file_offset, piece.length)

            verified = piece.verify_data(data) if len(data) == piece.length else False

            if verified:
                piece.is_complete = True
                piece.is_persisted = True
                self.downloaded_bytes += piece.length

            checked = scan_index + 1
            self._set_check_progress(checked, len(candidates))
            percent = int(self.check_progress * 100)
            now = time.monotonic()

            if progress_callback and (
                percent != last_reported_percent
                or now - last_callback_time >= 0.10
            ):
                progress_callback()
                last_callback_time = now
                last_reported_percent = percent

        self._set_check_progress(len(candidates), len(candidates))
        self._rebuild_persisted_cache()
        self._rebuild_rarity_buckets()
        if progress_callback:
            progress_callback()
        return True

    def _build_completed_bitfield(self) -> bytes:
        bitfield = bytearray(math.ceil(len(self.pieces) / 8))

        for piece in self.pieces:
            if not piece.is_complete:
                continue
            byte_index = piece.index // 8
            bit_index = 7 - (piece.index % 8)
            bitfield[byte_index] |= 1 << bit_index

        return bytes(bitfield)

    def _rebuild_persisted_cache(self):
        bitfield = bytearray(math.ceil(len(self.pieces) / 8))
        count = 0
        byte_count = 0
        for piece in self.pieces:
            if not piece.is_complete or not piece.is_persisted:
                continue
            byte_index = piece.index // 8
            bit_index = 7 - (piece.index % 8)
            bitfield[byte_index] |= 1 << bit_index
            count += 1
            byte_count += piece.length
        self._persisted_bitfield = bitfield
        self._persisted_pieces_count = count
        self._persisted_bytes_count = byte_count

    def _set_piece_persisted(self, piece: Piece, persisted: bool):
        persisted = bool(persisted) and bool(piece.is_complete)
        if piece.is_persisted == persisted:
            return
        piece.is_persisted = persisted
        byte_index = piece.index // 8
        bit_index = 7 - (piece.index % 8)
        mask = 1 << bit_index
        if persisted:
            self._persisted_bitfield[byte_index] |= mask
            self._persisted_pieces_count += 1
            self._persisted_bytes_count += piece.length
        else:
            self._persisted_bitfield[byte_index] &= ~mask
            self._persisted_pieces_count = max(0, self._persisted_pieces_count - 1)
            self._persisted_bytes_count = max(0, self._persisted_bytes_count - piece.length)

    def _build_persisted_bitfield(self) -> bytes:
        """Return cached disk-safe resume state without rescanning all pieces."""
        return bytes(self._persisted_bitfield)

    @property
    def persisted_pieces(self) -> int:
        return self._persisted_pieces_count

    @property
    def persisted_bytes(self) -> int:
        return self._persisted_bytes_count

    def _apply_completed_bitfield(self, raw_bitfield: bytes) -> bool:
        required_bytes = math.ceil(len(self.pieces) / 8)
        if len(raw_bitfield) != required_bytes:
            return False

        downloaded_bytes = 0
        for piece in self.pieces:
            byte_index = piece.index // 8
            bit_index = 7 - (piece.index % 8)
            is_complete = bool(raw_bitfield[byte_index] & (1 << bit_index))
            piece.is_complete = is_complete
            piece.is_persisted = is_complete
            if is_complete:
                downloaded_bytes += piece.length

        self.downloaded_bytes = downloaded_bytes
        self._rebuild_persisted_cache()
        self._rebuild_rarity_buckets()
        return True

    def _resume_metadata_matches(self, state: dict) -> bool:
        try:
            common = (
                state.get("version") == RESUME_STATE_VERSION
                and state.get("info_hash") == self.torrent.hex_info_hash
                and state.get("torrent_name") == self.torrent.name
                and int(state.get("total_length", -1)) == self.torrent.total_length
                and int(state.get("piece_length", -1)) == self.torrent.piece_length
                and int(state.get("piece_count", -1)) == len(self.pieces)
                and bool(state.get("external_seed", False)) == self.read_only_seed_source
            )
            if not common:
                return False

            if self.read_only_seed_source:
                saved_source = str(state.get("seed_source_path") or "")
                if os.path.normcase(os.path.abspath(saved_source)) != os.path.normcase(self.seed_source_path):
                    return False

            if self.torrent.is_multi_file:
                return (
                    bool(state.get("multi_file"))
                    and state.get("payload_signature") == self._multi_payload_signature()
                )

            if state.get("multi_file"):
                return False
            single_path = self._storage_files[0].path if self._storage_files else self.backing_path
            stat = os.stat(single_path)
            return (
                int(state.get("file_size", -1)) == stat.st_size
                and int(state.get("file_mtime_ns", -1)) == stat.st_mtime_ns
            )
        except (OSError, TypeError, ValueError):
            return False

    def _load_resume_state(self) -> bool:
        if not self._payload_exists() or not os.path.exists(self.resume_path):
            return False

        try:
            with open(self.resume_path, "r", encoding="utf-8") as file_handle:
                state = json.load(file_handle)
            if not isinstance(state, dict) or not self._resume_metadata_matches(state):
                return False

            encoded_bitfield = state.get("completed_bitfield")
            if not isinstance(encoded_bitfield, str):
                return False

            raw_bitfield = base64.b64decode(encoded_bitfield.encode("ascii"), validate=True)
            return self._apply_completed_bitfield(raw_bitfield)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False

    def save_resume_state(self, force: bool = False) -> bool:
        if not self._storage_prepared or not self._payload_exists():
            return False

        now = time.monotonic()
        if (
            self.torrent.is_multi_file
            and not force
            and now - self._last_resume_save_time < MULTI_FILE_RESUME_INTERVAL
        ):
            return True

        with self._resume_lock:
            try:
                os.makedirs(self.resume_dir, exist_ok=True)
                bitfield = self._build_persisted_bitfield()
                persisted_pieces = self.persisted_pieces
                persisted_bytes = self.persisted_bytes

                state = {
                    "version": RESUME_STATE_VERSION,
                    "info_hash": self.torrent.hex_info_hash,
                    "torrent_name": self.torrent.name,
                    "total_length": self.torrent.total_length,
                    "piece_length": self.torrent.piece_length,
                    "piece_count": len(self.pieces),
                    "completed_bitfield": base64.b64encode(bitfield).decode("ascii"),
                    "completed_pieces": persisted_pieces,
                    "downloaded_bytes": persisted_bytes,
                    "external_seed": self.read_only_seed_source,
                    "seed_source_path": self.seed_source_path if self.read_only_seed_source else "",
                }

                if self.torrent.is_multi_file:
                    state.update(
                        {
                            "multi_file": True,
                            "payload_signature": self._multi_payload_signature(),
                            "physical_bytes": self._multi_physical_bytes(),
                            "file_count": len(self._storage_files),
                        }
                    )
                else:
                    single_path = self._storage_files[0].path if self._storage_files else self.backing_path
                    stat = os.stat(single_path)
                    state.update(
                        {
                            "file_size": stat.st_size,
                            "file_mtime_ns": stat.st_mtime_ns,
                        }
                    )

                temp_path = f"{self.resume_path}.tmp"
                with open(temp_path, "w", encoding="utf-8") as file_handle:
                    json.dump(state, file_handle, separators=(",", ":"))
                    file_handle.flush()
                    os.fsync(file_handle.fileno())

                os.replace(temp_path, self.resume_path)
                self._last_resume_save_time = now
                return True
            except OSError:
                return False

    def _delete_resume_state(self):
        try:
            if os.path.exists(self.resume_path):
                os.remove(self.resume_path)
        except OSError:
            pass

    def invalidate_verification(self):
        """Forget cached piece verification without deleting payload data.

        This is used by the user-facing Force Recheck action. Existing files are
        left untouched; only trusted resume metadata and in-memory verification
        state are cleared so the next prepare/check hashes the payload again.
        """
        with self._prepare_lock:
            self._delete_resume_state()
            self._storage_prepared = False
            self.fast_resume_used = False
            self.downloaded_bytes = 0
            self.last_error = ""
            self._set_check_progress(0, 0)
            self.reset_inflight_requests()

            for piece in self.pieces:
                piece.is_complete = False
                piece.is_persisted = False
                if piece.blocks_initialized:
                    piece.reset()
            self._rebuild_persisted_cache()
            self._rebuild_rarity_buckets()

    @staticmethod
    def _request_owner(peer_key: object) -> object:
        return _ANONYMOUS_REQUESTER if peer_key is None else peer_key

    def _reserve_block_request(
        self,
        block: Block,
        peer_key: object,
        *,
        allow_duplicate: bool = False,
    ) -> bool:
        """Reserve one block for one peer without scanning unrelated requests."""
        if block.data is not None:
            return False

        owner = self._request_owner(peer_key)
        if owner in block.requesters:
            return False

        if block.requesters:
            if not allow_duplicate:
                return False
            if len(block.requesters) >= ENDGAME_MAX_REQUESTERS_PER_BLOCK:
                return False

        block.requesters[owner] = 0.0
        self._requests_by_peer.setdefault(owner, set()).add(block)
        self._active_piece_indices.add(block.piece_index)
        return True

    def mark_request_sent(
        self,
        block: Block,
        peer_key: object,
        *,
        sent_at: Optional[float] = None,
    ) -> bool:
        """Start the timeout clock only after the REQUEST reached the wire."""
        owner = self._request_owner(peer_key)
        if owner not in block.requesters:
            return False
        block.requesters[owner] = float(sent_at if sent_at is not None else time.monotonic())
        return True

    def release_request(self, block: Block, peer_key: object) -> bool:
        """Release one peer's ownership while preserving any endgame duplicates."""
        owner = self._request_owner(peer_key)
        if owner not in block.requesters:
            return False
        block.requesters.pop(owner, None)
        owned = self._requests_by_peer.get(owner)
        if owned is not None:
            owned.discard(block)
            if not owned:
                self._requests_by_peer.pop(owner, None)
        return True

    def _release_all_block_requests(self, block: Block) -> tuple[object, ...]:
        owners = tuple(block.requesters)
        if not owners:
            return ()
        block.requesters.clear()
        for owner in owners:
            owned = self._requests_by_peer.get(owner)
            if owned is None:
                continue
            owned.discard(block)
            if not owned:
                self._requests_by_peer.pop(owner, None)
        return owners

    def release_peer_requests(self, peer_key: object) -> List[Block]:
        """Release a disconnected/choked peer in O(size of its request pipeline)."""
        owner = self._request_owner(peer_key)
        blocks = list(self._requests_by_peer.pop(owner, ()))
        for block in blocks:
            block.requesters.pop(owner, None)
        return blocks

    def expire_peer_requests(
        self,
        peer_key: object,
        timeout_seconds: float,
        *,
        now: Optional[float] = None,
    ) -> List[Block]:
        """Release wire requests that have exceeded their response deadline."""
        owner = self._request_owner(peer_key)
        owned = self._requests_by_peer.get(owner)
        if not owned:
            return []

        current = float(now if now is not None else time.monotonic())
        timeout = max(0.0, float(timeout_seconds))
        expired: List[Block] = []
        for block in tuple(owned):
            sent_at = float(block.requesters.get(owner, 0.0) or 0.0)
            # 0.0 is a scheduler reservation still waiting on a bandwidth
            # limiter; it must not time out before its REQUEST has been sent.
            if sent_at <= 0.0 or current - sent_at < timeout:
                continue
            block.requesters.pop(owner, None)
            owned.discard(block)
            expired.append(block)

        if not owned:
            self._requests_by_peer.pop(owner, None)
        return expired

    def peer_outstanding_request_count(self, peer_key: object) -> int:
        owner = self._request_owner(peer_key)
        return len(self._requests_by_peer.get(owner, ()))

    def outstanding_request_count(self) -> int:
        """Return wire-request ownership count, including endgame duplicates."""
        return sum(len(blocks) for blocks in self._requests_by_peer.values())

    def remaining_wanted_block_count(self, limit: Optional[int] = None) -> int:
        """Count missing wanted blocks without forcing lazy block allocation.

        Far from endgame this exits as soon as ``limit`` is exceeded, so the hot
        scheduler only inspects enough pieces to prove that the tail is not yet
        small. Near endgame there are at most a few dozen missing blocks to count.
        """
        stop_after = None if limit is None else max(0, int(limit))
        remaining = 0
        for piece_index, piece in enumerate(self.pieces):
            if piece.is_complete or self.piece_priority_rank(piece_index) <= 0:
                continue

            if piece.blocks_initialized:
                remaining += sum(1 for block in (piece._blocks or ()) if block.data is None)
            else:
                remaining += math.ceil(piece.length / BLOCK_SIZE) if piece.length else 0

            if stop_after is not None and remaining > stop_after:
                return remaining
        return remaining

    @property
    def endgame_active(self) -> bool:
        remaining = self.remaining_wanted_block_count(limit=ENDGAME_BLOCK_THRESHOLD)
        return 0 < remaining <= ENDGAME_BLOCK_THRESHOLD

    def _reserve_random_candidate_block(
        self,
        candidates: set[int],
        peer_key: object,
        excluded_blocks: object = (),
    ) -> Optional[Block]:
        """Reserve one previously-unrequested block from a randomized piece set."""
        while candidates:
            offset = random.randrange(len(candidates))
            piece_index = next(itertools.islice(candidates, offset, None))
            candidates.remove(piece_index)
            piece = self.pieces[piece_index]

            if piece.is_complete:
                self._remove_from_rarity_buckets(piece_index)
                continue

            for block in piece.blocks:
                if (block.piece_index, block.offset) in excluded_blocks:
                    continue
                if block.data is None and not block.requesters:
                    if self._reserve_block_request(block, peer_key):
                        return block
        return None

    def _reserve_endgame_duplicate(
        self,
        candidates: set[int],
        peer_key: object,
        excluded_blocks: object = (),
    ) -> Optional[Block]:
        """Duplicate the oldest eligible tail request for this peer.

        Endgame is deliberately small (<= ENDGAME_BLOCK_THRESHOLD), so scanning
        the tail for its oldest outstanding request is bounded and gives better
        completion latency than randomly duplicating a freshly issued request.
        """
        owner = self._request_owner(peer_key)
        oldest_time: Optional[float] = None
        oldest_blocks: List[Block] = []

        for piece_index in candidates:
            piece = self.pieces[piece_index]
            if piece.is_complete or not piece.blocks_initialized:
                continue
            for block in piece._blocks or ():
                if (block.piece_index, block.offset) in excluded_blocks:
                    continue
                if block.data is not None or not block.requesters:
                    continue
                if owner in block.requesters:
                    continue
                if len(block.requesters) >= ENDGAME_MAX_REQUESTERS_PER_BLOCK:
                    continue

                sent_times = [
                    float(value)
                    for value in block.requesters.values()
                    if float(value or 0.0) > 0.0
                ]
                if not sent_times:
                    # Do not duplicate a reservation that has not actually been
                    # transmitted yet; the original peer may still be throttled.
                    continue
                request_time = min(sent_times)
                if oldest_time is None or request_time < oldest_time:
                    oldest_time = request_time
                    oldest_blocks = [block]
                elif request_time == oldest_time:
                    oldest_blocks.append(block)

        if not oldest_blocks:
            return None
        block = random.choice(oldest_blocks)
        return block if self._reserve_block_request(block, peer_key, allow_duplicate=True) else None

    def _select_unrequested_block(
        self,
        peer_pieces: set[int],
        peer_key: object,
        excluded_blocks: object = (),
    ) -> Optional[Block]:
        for wanted_rank in (
            FILE_PRIORITY_RANK[FILE_PRIORITY_HIGH],
            FILE_PRIORITY_RANK[FILE_PRIORITY_NORMAL],
            FILE_PRIORITY_RANK[FILE_PRIORITY_LOW],
        ):
            buckets = self._rarity_buckets.get(wanted_rank, {})
            for availability in sorted(buckets):
                bucket = buckets.get(availability)
                if not bucket:
                    continue

                active_candidates = self._active_piece_indices.intersection(
                    bucket,
                    peer_pieces,
                )
                if active_candidates:
                    block = self._reserve_random_candidate_block(
                        active_candidates,
                        peer_key,
                        excluded_blocks,
                    )
                    if block is not None:
                        return block

                candidates = bucket.intersection(peer_pieces)
                if active_candidates:
                    candidates.difference_update(active_candidates)
                block = self._reserve_random_candidate_block(
                    candidates, peer_key, excluded_blocks
                )
                if block is not None:
                    return block
        return None

    def _select_endgame_duplicate(
        self,
        peer_pieces: set[int],
        peer_key: object,
        excluded_blocks: object = (),
    ) -> Optional[Block]:
        for wanted_rank in (
            FILE_PRIORITY_RANK[FILE_PRIORITY_HIGH],
            FILE_PRIORITY_RANK[FILE_PRIORITY_NORMAL],
            FILE_PRIORITY_RANK[FILE_PRIORITY_LOW],
        ):
            buckets = self._rarity_buckets.get(wanted_rank, {})
            for availability in sorted(buckets):
                bucket = buckets.get(availability)
                if not bucket:
                    continue
                block = self._reserve_endgame_duplicate(
                    bucket.intersection(peer_pieces),
                    peer_key,
                    excluded_blocks,
                )
                if block is not None:
                    return block
        return None

    def get_next_request(
        self,
        peer_bitfield: bytearray,
        peer_key: object = None,
        excluded_blocks: object = (),
    ) -> Optional[Block]:
        """Reserve the next block using rarest-first plus bounded endgame mode.

        Normal scheduling never duplicates a block: file priority remains the
        primary ordering and rarity the secondary ordering. Once <=32 wanted
        blocks remain, all still-unrequested blocks are assigned first; only
        then may an already-outstanding tail block gain another peer owner.
        """
        peer_pieces = self._peer_piece_sets.get(peer_key)
        if peer_pieces is None:
            peer_pieces = self._piece_set_from_bitfield(peer_bitfield)
        if not peer_pieces:
            return None

        block = self._select_unrequested_block(
            peer_pieces, peer_key, excluded_blocks
        )
        if block is not None:
            return block

        if self.endgame_active:
            return self._select_endgame_duplicate(
                peer_pieces, peer_key, excluded_blocks
            )
        return None

    def receive_block(
        self,
        piece_index: int,
        offset: int,
        data: bytes,
        *,
        peer_key: object = None,
    ) -> BlockReceiveResult:
        """Accept one block and return ownership/cancellation information."""
        if piece_index < 0 or piece_index >= len(self.pieces):
            return BlockReceiveResult()

        piece = self.pieces[piece_index]
        matched_block: Optional[Block] = None
        for block in piece.blocks:
            if block.offset == offset:
                matched_block = block
                break

        if matched_block is None:
            return BlockReceiveResult()

        owner = self._request_owner(peer_key)
        if len(data) != matched_block.length:
            self.release_request(matched_block, owner)
            return BlockReceiveResult(block=matched_block)

        # A late PIECE can arrive after an endgame CANCEL. It is valid wire data
        # but must not be counted or written twice.
        if matched_block.data is not None:
            self.release_request(matched_block, owner)
            return BlockReceiveResult(
                accepted=False,
                duplicate=True,
                block=matched_block,
            )

        requesters = self._release_all_block_requests(matched_block)
        cancel_peer_keys = tuple(key for key in requesters if key != owner)

        matched_block.data = data
        self.downloaded_bytes += len(data)

        if not piece.is_all_blocks_received():
            return BlockReceiveResult(
                accepted=True,
                cancel_peer_keys=cancel_peer_keys,
                block=matched_block,
            )

        if piece.verify_hash():
            piece.is_complete = True
            piece.is_persisted = False
            self._remove_from_rarity_buckets(piece.index)

            # Preserve historical synchronous PieceManager behaviour for direct
            # callers/tests that are not running a TorrentSession disk worker.
            # Live transfers start the Phase 4 writer before peer traffic, so
            # their filesystem I/O never runs on the peer/event-loop hot path.
            if self._disk_worker_task is None:
                self._write_piece_to_disk(piece)
                self._set_piece_persisted(piece, True)
                self.save_resume_state()
            else:
                with self._disk_state_lock:
                    self._disk_unqueued_verified.add(piece.index)

            return BlockReceiveResult(
                accepted=True,
                piece_completed=True,
                cancel_peer_keys=cancel_peer_keys,
                block=matched_block,
            )

        # A failed piece hash invalidates all of its blocks. Clean any remaining
        # ownership reverse-index entries before Piece.reset clears the blocks.
        for block in piece.blocks:
            self._release_all_block_requests(block)
        self.downloaded_bytes = max(0, self.downloaded_bytes - piece.received_byte_count())
        piece.reset()
        return BlockReceiveResult(
            accepted=True,
            hash_failed=True,
            cancel_peer_keys=cancel_peer_keys,
            block=matched_block,
        )

    def handle_block_received(
        self,
        piece_index: int,
        offset: int,
        data: bytes,
        peer_key: object = None,
    ) -> bool:
        """Compatibility wrapper returning only whether the piece completed."""
        return self.receive_block(
            piece_index,
            offset,
            data,
            peer_key=peer_key,
        ).piece_completed

    @property
    def disk_error(self) -> str:
        return self._disk_error

    async def start_disk_io(self):
        """Start one sleeping asynchronous disk writer for this PieceManager."""
        if self.read_only_seed_source or self._disk_worker_task is not None:
            return

        self._disk_queue = asyncio.Queue()
        self._disk_condition = asyncio.Condition()
        self._disk_pending_bytes = 0
        self._disk_pending_writes = 0
        self._disk_error = ""
        self._disk_writes_completed = 0
        self._disk_bytes_written = 0
        self._disk_write_failures = 0
        self._disk_write_latency_total = 0.0
        self._disk_write_latency_last = 0.0
        self._disk_write_latency_max = 0.0
        self._disk_backpressure_events = 0
        self._disk_backpressure_seconds = 0.0
        self._disk_cache_hits = 0
        self._disk_cache_misses = 0
        with self._disk_state_lock:
            self._pending_piece_data.clear()
            self._disk_unqueued_verified.clear()
            self._recent_piece_cache.clear()
            self._recent_piece_cache_bytes = 0
        self._disk_worker_task = asyncio.create_task(self._disk_writer_loop())

    async def enqueue_completed_piece(self, piece_index: int) -> bool:
        """Queue one verified piece without blocking the event loop on disk I/O.

        Queue capacity is measured in bytes. If the buffer is full this coroutine
        sleeps on a condition until the writer frees space, applying true
        backpressure while allowing every unrelated asyncio task to keep running.
        """
        if piece_index < 0 or piece_index >= len(self.pieces):
            return False
        piece = self.pieces[piece_index]
        if not piece.is_complete or piece.is_persisted:
            return bool(piece.is_complete)

        # Direct callers retain the old synchronous semantics.
        if self._disk_worker_task is None or self._disk_queue is None or self._disk_condition is None:
            self._write_piece_to_disk(piece)
            self._set_piece_persisted(piece, True)
            self.save_resume_state()
            return True

        if self._disk_error:
            raise OSError(self._disk_error)

        size = int(piece.length)
        waited = False
        wait_started = 0.0
        condition = self._disk_condition
        async with condition:
            while (
                self._disk_pending_bytes > 0
                and self._disk_pending_bytes + size > self._disk_write_buffer_limit
            ):
                if self._disk_error:
                    raise OSError(self._disk_error)
                if not waited:
                    waited = True
                    wait_started = time.monotonic()
                    self._disk_backpressure_events += 1
                await condition.wait()

            if self._disk_error:
                raise OSError(self._disk_error)

            # Acquire byte capacity before joining block payloads into one piece
            # buffer. Waiting peers therefore do not each allocate another full
            # piece merely because the writer is saturated.
            self._disk_pending_bytes += size
            self._disk_pending_writes += 1

        if waited:
            self._disk_backpressure_seconds += max(0.0, time.monotonic() - wait_started)

        data = piece.get_data()
        if len(data) != piece.length:
            async with condition:
                self._disk_pending_bytes = max(0, self._disk_pending_bytes - size)
                self._disk_pending_writes = max(0, self._disk_pending_writes - 1)
                condition.notify_all()
            raise OSError(f"Verified piece {piece_index} no longer has its complete in-memory payload.")

        with self._disk_state_lock:
            self._pending_piece_data[piece_index] = data

        # Once the full pending buffer is pinned, individual block payloads are
        # redundant. Clearing them prevents the async write buffer from doubling
        # memory usage while the piece waits for disk.
        if piece.blocks_initialized:
            for block in piece._blocks or ():
                block.data = None
                block.requesters.clear()

        self._disk_queue.put_nowait((piece_index, data, time.monotonic()))
        with self._disk_state_lock:
            self._disk_unqueued_verified.discard(piece_index)
        return True

    async def _disk_writer_loop(self):
        queue_obj = self._disk_queue
        condition = self._disk_condition
        if queue_obj is None or condition is None:
            return

        while True:
            item = await queue_obj.get()
            if item is None:
                queue_obj.task_done()
                break

            piece_index, data, _queued_at = item
            write_started = time.monotonic()
            try:
                file_offset = self.pieces[piece_index].storage_offset
                await asyncio.to_thread(self._write_range, file_offset, data)
                latency = max(0.0, time.monotonic() - write_started)

                piece = self.pieces[piece_index]
                self._set_piece_persisted(piece, True)
                self._disk_writes_completed += 1
                self._disk_bytes_written += len(data)
                self._disk_write_latency_total += latency
                self._disk_write_latency_last = latency
                self._disk_write_latency_max = max(self._disk_write_latency_max, latency)

                with self._disk_state_lock:
                    self._pending_piece_data.pop(piece_index, None)
                    if self._recent_piece_cache_enabled and len(data) <= self._recent_piece_cache_limit:
                        old = self._recent_piece_cache.pop(piece_index, None)
                        if old is not None:
                            self._recent_piece_cache_bytes -= len(old)
                        self._recent_piece_cache[piece_index] = data
                        self._recent_piece_cache_bytes += len(data)
                        while (
                            self._recent_piece_cache
                            and self._recent_piece_cache_bytes > self._recent_piece_cache_limit
                        ):
                            _, evicted = self._recent_piece_cache.popitem(last=False)
                            self._recent_piece_cache_bytes -= len(evicted)

                # Resume JSON/fsync is also moved off the event loop. The
                # existing multi-file throttling still coalesces frequent saves.
                await asyncio.to_thread(self.save_resume_state)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._disk_write_failures += 1
                self._disk_error = f"Disk write failed for piece {piece_index}: {exc}"
                self.last_error = self._disk_error
                await self._invalidate_pending_disk_writes(piece_index)
                queue_obj.task_done()
                break
            else:
                async with condition:
                    self._disk_pending_bytes = max(0, self._disk_pending_bytes - len(data))
                    self._disk_pending_writes = max(0, self._disk_pending_writes - 1)
                    condition.notify_all()
                queue_obj.task_done()

    async def _invalidate_pending_disk_writes(self, failed_piece_index: int):
        """Fail closed on disk errors and release every buffered byte reservation."""
        queue_obj = self._disk_queue
        condition = self._disk_condition
        with self._disk_state_lock:
            pending_indices = {failed_piece_index, *self._disk_unqueued_verified}
            self._disk_unqueued_verified.clear()
        if queue_obj is not None:
            while True:
                try:
                    item = queue_obj.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is None:
                    queue_obj.task_done()
                    continue
                piece_index, _data, _queued_at = item
                pending_indices.add(piece_index)
                queue_obj.task_done()

        for piece_index in pending_indices:
            if 0 <= piece_index < len(self.pieces):
                piece = self.pieces[piece_index]
                if piece.is_complete and not piece.is_persisted:
                    self.downloaded_bytes = max(0, self.downloaded_bytes - piece.length)
                    piece.reset()

        # Disk failure is terminal for the current run, so a one-time O(n)
        # scheduler rebuild is preferable to maintaining a special hot-path
        # reinsertion branch for an exceptional condition.
        self._rebuild_persisted_cache()
        self._rebuild_rarity_buckets()

        with self._disk_state_lock:
            self._pending_piece_data.clear()

        if condition is not None:
            async with condition:
                self._disk_pending_bytes = 0
                self._disk_pending_writes = 0
                condition.notify_all()

    async def flush_disk_writes(self) -> bool:
        """Wait until every queued verified piece is persisted or a write fails."""
        if self._disk_queue is None:
            return not bool(self._disk_error)
        await self._disk_queue.join()
        if self._disk_error:
            raise OSError(self._disk_error)
        return True

    async def shutdown_disk_io(self, *, flush: bool = True):
        """Drain and stop the shared disk writer, then release cached payload memory."""
        task = self._disk_worker_task
        queue_obj = self._disk_queue
        if task is None or queue_obj is None:
            return

        flush_error: Optional[Exception] = None
        if flush:
            try:
                # A peer task can be cancelled while waiting for byte capacity.
                # Preserve any already-verified piece by enqueueing that tiny
                # staged set before draining the writer during Stop/shutdown.
                if not self._disk_error:
                    with self._disk_state_lock:
                        staged = tuple(self._disk_unqueued_verified)
                    for piece_index in staged:
                        await self.enqueue_completed_piece(piece_index)
                await self.flush_disk_writes()
            except Exception as exc:
                flush_error = exc

        if not task.done():
            queue_obj.put_nowait(None)
            await asyncio.gather(task, return_exceptions=True)

        self._disk_worker_task = None
        self._disk_queue = None
        self._disk_condition = None
        self._disk_pending_bytes = 0
        self._disk_pending_writes = 0
        with self._disk_state_lock:
            self._pending_piece_data.clear()
            self._disk_unqueued_verified.clear()
            self._recent_piece_cache.clear()
            self._recent_piece_cache_bytes = 0

        if flush_error is not None:
            raise flush_error

    def disk_io_snapshot(self) -> dict:
        """Return O(1) disk/cache telemetry; no file or piece scan is performed."""
        writes = self._disk_writes_completed
        average = self._disk_write_latency_total / writes if writes else 0.0
        with self._disk_state_lock:
            cache_bytes = self._recent_piece_cache_bytes
            cache_entries = len(self._recent_piece_cache)
            pending_cache_entries = len(self._pending_piece_data)
            staged_verified = len(self._disk_unqueued_verified)
            cache_hits = self._disk_cache_hits
            cache_misses = self._disk_cache_misses

        return {
            "writer_active": bool(self._disk_worker_task is not None and not self._disk_worker_task.done()),
            "buffer_limit_bytes": int(self._disk_write_buffer_limit),
            "pending_bytes": int(self._disk_pending_bytes),
            "pending_writes": int(self._disk_pending_writes),
            "pending_cached_pieces": pending_cache_entries,
            "staged_verified_pieces": staged_verified,
            "writes_completed": int(writes),
            "bytes_written": int(self._disk_bytes_written),
            "write_failures": int(self._disk_write_failures),
            "write_latency_last_ms": self._disk_write_latency_last * 1000.0,
            "write_latency_average_ms": average * 1000.0,
            "write_latency_max_ms": self._disk_write_latency_max * 1000.0,
            "backpressure_events": int(self._disk_backpressure_events),
            "backpressure_seconds": float(self._disk_backpressure_seconds),
            "cache_enabled": bool(self._recent_piece_cache_enabled),
            "cache_limit_bytes": int(self._recent_piece_cache_limit),
            "cache_bytes": int(cache_bytes),
            "cache_entries": int(cache_entries),
            "cache_hits": int(cache_hits),
            "cache_misses": int(cache_misses),
            "error": self._disk_error,
        }

    def _read_piece_from_memory(self, piece: Piece, offset: int, length: int) -> bytes:
        """Read a complete but not-yet-enqueued piece from its received blocks."""
        blocks = piece._blocks or ()
        end = offset + length
        result = bytearray()
        current = offset
        for block in blocks:
            block_end = block.offset + block.length
            if block_end <= current:
                continue
            if block.offset >= end:
                break
            if block.data is None:
                return b""
            local_start = max(current, block.offset) - block.offset
            local_end = min(end, block_end) - block.offset
            result.extend(block.data[local_start:local_end])
            current = block.offset + local_end
            if current >= end:
                break
        return bytes(result) if len(result) == length else b""

    def _write_piece_to_disk(self, piece: Piece):
        self._write_range(piece.storage_offset, piece.get_data())

    def read_block(
        self,
        piece_index: int,
        offset: int,
        length: int,
        generation: str = "v1",
    ) -> bytes:
        if piece_index < 0 or piece_index >= len(self.pieces):
            return b""

        piece = self.pieces[piece_index]
        if not piece.is_complete:
            return b""
        if offset < 0 or length <= 0 or length > BLOCK_SIZE:
            return b""

        generation = str(generation or "v1").lower()
        wire_length = piece.wire_length(generation)
        if offset + length > wire_length:
            return b""

        # BEP-47 hybrid padding is virtual storage. v1 peers are allowed to
        # request those bytes, but they are deterministic zeroes and are never
        # materialised as .pad files. v2 peers see only the real file bytes.
        if offset >= piece.length:
            if generation == "v1" and offset + length <= wire_length:
                return b"\x00" * length
            return b""

        payload_length = min(length, piece.length - offset)
        padding_length = length - payload_length

        # Pending verified pieces must be uploadable before their write-behind
        # reaches disk. Recently persisted pieces can also be served from the
        # bounded LRU cache, avoiding a read-after-write filesystem round trip.
        with self._disk_state_lock:
            cached = self._pending_piece_data.get(piece_index)
            if cached is not None:
                self._disk_cache_hits += 1
                data = cached[offset:offset + payload_length]
                return data + (b"\x00" * padding_length) if len(data) == payload_length else b""

            cached = self._recent_piece_cache.get(piece_index)
            if cached is not None:
                self._recent_piece_cache.move_to_end(piece_index)
                self._disk_cache_hits += 1
                data = cached[offset:offset + payload_length]
                return data + (b"\x00" * padding_length) if len(data) == payload_length else b""

        if not piece.is_persisted:
            data = self._read_piece_from_memory(piece, offset, payload_length)
            if data:
                with self._disk_state_lock:
                    self._disk_cache_hits += 1
                return data + (b"\x00" * padding_length)
            return b""

        with self._disk_state_lock:
            self._disk_cache_misses += 1
        file_offset = piece.storage_offset + offset
        data = self._read_range(file_offset, payload_length)
        if len(data) != payload_length:
            return b""
        return data + (b"\x00" * padding_length)

    def build_file_telemetry(self, detail_limit: int = 500) -> dict:
        """Build per-file progress without allocating untouched piece blocks.

        File progress is based on *verified* piece bytes, not raw file size. This
        matters because out-of-order writes can make a partially downloaded file
        look physically large even though many logical ranges are still missing.
        Active in-memory blocks are used only to label files as Downloading or
        Requested; they are not counted as verified until the owning piece passes
        its SHA-1 check.
        """
        storage_files = self._storage_files
        file_count = len(storage_files)
        detail_limit = max(1, int(detail_limit))

        verified_total = sum(piece.length for piece in self.pieces if piece.is_complete)

        # Prefix bytes let a file spanning many pieces calculate the verified
        # contribution of its fully-contained middle pieces in O(1). Only its
        # two edge pieces need special overlap handling.
        complete_prefix = [0]
        running = 0
        for piece in self.pieces:
            if piece.is_complete:
                running += piece.length
            complete_prefix.append(running)

        # Track only blocks that already exist. This preserves lazy allocation
        # and lets the Files view identify which actual file(s) an active block
        # overlaps, including a block that happens to cross a file boundary.
        active_files = {}
        for piece in self.pieces:
            if piece.is_complete or not piece.blocks_initialized:
                continue

            piece_start = piece.storage_offset
            blocks = piece._blocks or []
            for block in blocks:
                if block.data is not None:
                    activity = "received"
                elif block.is_requested:
                    activity = "requested"
                else:
                    continue

                block_start = piece_start + block.offset
                block_end = min(block_start + block.length, self.torrent.total_length)
                storage_index = self._storage_index_for_offset(block_start)

                while 0 <= storage_index < file_count:
                    item = storage_files[storage_index]
                    if item.start >= block_end:
                        break
                    if item.end > block_start:
                        flags = active_files.setdefault(
                            storage_index,
                            {"received": False, "requested": False},
                        )
                        flags[activity] = True
                    storage_index += 1

        # Huge folder torrents should not push thousands of live Dear PyGui rows
        # through the UI every telemetry tick. Show the beginning of the torrent,
        # a window around the current download position, and any active files.
        if file_count <= detail_limit:
            selected_indices = list(range(file_count))
        else:
            selected = set(range(min(20, file_count)))

            first_incomplete_piece = next(
                (piece for piece in self.pieces if not piece.is_complete),
                None,
            )
            if first_incomplete_piece is not None:
                current_offset = first_incomplete_piece.storage_offset
                current_file = self._storage_index_for_offset(current_offset)
            else:
                current_file = 0

            active_indices = sorted(active_files)
            active_reserve = min(len(active_indices), 64)
            window_budget = max(1, detail_limit - len(selected) - active_reserve)
            window_start = max(0, current_file - min(12, window_budget // 4))
            window_start = min(window_start, max(0, file_count - window_budget))

            for index in range(window_start, min(file_count, window_start + window_budget)):
                selected.add(index)

            for index in active_indices:
                if len(selected) >= detail_limit:
                    break
                selected.add(index)

            if len(selected) < detail_limit:
                for index in range(file_count):
                    selected.add(index)
                    if len(selected) >= detail_limit:
                        break

            selected_indices = sorted(selected)[:detail_limit]

        def verified_bytes_for_file(item: StorageFile) -> tuple[int, int, int]:
            if item.length <= 0 or not self.pieces:
                return (0, -1, -1)

            first_piece = min(
                len(self.pieces) - 1,
                item.start // self.torrent.piece_length,
            )
            last_piece = min(
                len(self.pieces) - 1,
                (item.end - 1) // self.torrent.piece_length,
            )

            if first_piece == last_piece:
                verified = item.length if self.pieces[first_piece].is_complete else 0
                return (verified, first_piece, last_piece)

            verified = 0

            first = self.pieces[first_piece]
            first_piece_start = first_piece * self.torrent.piece_length
            first_piece_end = first_piece_start + first.length
            if first.is_complete:
                verified += max(0, min(item.end, first_piece_end) - item.start)

            last = self.pieces[last_piece]
            last_piece_start = last_piece * self.torrent.piece_length
            if last.is_complete:
                verified += max(0, item.end - max(item.start, last_piece_start))

            if last_piece > first_piece + 1:
                verified += complete_prefix[last_piece] - complete_prefix[first_piece + 1]

            return (min(item.length, verified), first_piece, last_piece)

        records = []
        for index in selected_indices:
            item = storage_files[index]
            verified_bytes, first_piece, last_piece = verified_bytes_for_file(item)

            if item.length == 0:
                progress = 1.0
            else:
                progress = max(0.0, min(1.0, verified_bytes / item.length))

            priority = (
                self.file_priorities[index]
                if index < len(self.file_priorities)
                else FILE_PRIORITY_NORMAL
            )
            activity = active_files.get(index, {})
            if item.length == 0 or verified_bytes >= item.length:
                state = "Complete"
            elif priority == FILE_PRIORITY_SKIP:
                state = "Skipped"
            elif activity.get("received"):
                state = "Downloading"
            elif activity.get("requested"):
                state = "Requested"
            elif verified_bytes > 0:
                state = "Partial"
            else:
                state = "Missing"

            if first_piece < 0:
                piece_span = "--"
            elif first_piece == last_piece:
                piece_span = str(first_piece)
            else:
                piece_span = f"{first_piece}-{last_piece}"

            records.append({
                "index": index,
                "path": item.relative_path.replace("\\", "/"),
                "length": item.length,
                "verified_bytes": verified_bytes,
                "progress": progress,
                "first_piece": first_piece,
                "last_piece": last_piece,
                "piece_span": piece_span,
                "state": state,
                "priority": priority,
            })

        return {
            "file_count": file_count,
            "displayed_count": len(records),
            "truncated": file_count > len(records),
            "is_multi_file": bool(self.torrent.is_multi_file),
            "total_bytes": self.torrent.total_length,
            "verified_bytes": verified_total,
            "wanted_piece_count": self.wanted_piece_count,
            "completed_wanted_pieces": self.completed_wanted_pieces,
            "wanted_progress": self.wanted_progress,
            "wanted_finished": self.wanted_is_finished,
            "storage_mode": self.storage_mode,
            "backing_path": os.path.abspath(self.backing_path),
            "files": records,
        }

    def build_piece_telemetry(
        self,
        peer_bitfields: Iterable[bytes] = (),
        detail_limit: int = 120,
        map_cell_limit: int = 768,
    ) -> dict:
        """Build a compact read-only snapshot for the Pieces view.

        The method deliberately inspects only blocks that have already been
        initialized by the downloader. Merely opening the Pieces tab must not
        defeat lazy block allocation by creating blocks for thousands of
        untouched pieces.
        """
        total_pieces = len(self.pieces)
        detail_limit = max(1, int(detail_limit))
        map_cell_limit = max(1, int(map_cell_limit))

        # Phase 1 keeps availability incrementally from peer events. Copying
        # this compact integer array is cheaper than rescanning every connected
        # peer bitfield whenever the cached Pieces view refreshes. The legacy
        # peer_bitfields argument remains as a compatibility fallback for direct
        # callers that do not register peer identities.
        availability = list(self._piece_availability)
        have_peer_availability = bool(self._peer_piece_sets)
        if not have_peer_availability and peer_bitfields:
            availability = [0] * total_pieces
            for bitfield in peer_bitfields:
                pieces = self._piece_set_from_bitfield(bitfield)
                if pieces:
                    have_peer_availability = True
                for piece_index in pieces:
                    availability[piece_index] += 1

        records = []
        state_codes = []
        verified_count = 0
        downloading_count = 0
        requested_count = 0
        missing_count = 0
        outstanding_wire_requests = 0
        duplicate_wire_requests = 0
        remaining_wanted_blocks = 0

        for piece in self.pieces:
            total_blocks = math.ceil(piece.length / BLOCK_SIZE) if piece.length else 0
            received_blocks = 0
            requested_blocks = 0
            received_bytes = 0

            blocks = piece._blocks if piece.blocks_initialized else None
            if blocks is not None:
                for block in blocks:
                    if block.data is not None:
                        received_blocks += 1
                        received_bytes += len(block.data)
                    elif block.is_requested:
                        requested_blocks += 1
                        owner_count = len(block.requesters)
                        outstanding_wire_requests += owner_count
                        duplicate_wire_requests += max(0, owner_count - 1)

            if not piece.is_complete and self.piece_priority_rank(piece.index) > 0:
                remaining_wanted_blocks += max(0, total_blocks - received_blocks)

            if piece.is_complete:
                state = "Verified"
                code = "V"
                verified_count += 1
                progress = 1.0
                received_blocks = total_blocks
                received_bytes = piece.length
            elif received_blocks > 0:
                state = "Downloading"
                code = "D"
                downloading_count += 1
                progress = received_bytes / piece.length if piece.length else 0.0
            elif requested_blocks > 0:
                state = "Requested"
                code = "R"
                requested_count += 1
                progress = 0.0
            else:
                state = "Missing"
                code = "M"
                missing_count += 1
                progress = 0.0

            state_codes.append(code)
            records.append({
                "index": piece.index,
                "length": piece.length,
                "progress": max(0.0, min(1.0, progress)),
                "received_blocks": received_blocks,
                "requested_blocks": requested_blocks,
                "total_blocks": total_blocks,
                "availability": availability[piece.index] if piece.index < len(availability) else 0,
                "state": state,
            })

        # Traditional torrent availability is the minimum full-copy count plus
        # the fraction of pieces that have at least one additional copy. Count
        # our own verified pieces as one copy.
        swarm_availability = 0.0
        if total_pieces:
            copy_counts = [
                availability[index] + (1 if self.pieces[index].is_complete else 0)
                for index in range(total_pieces)
            ]
            minimum_copies = min(copy_counts)
            extra_fraction = sum(1 for count in copy_counts if count > minimum_copies) / total_pieces
            swarm_availability = float(minimum_copies) + extra_fraction

        # Keep the detailed table useful without sending/rendering thousands of
        # rows every telemetry tick. Active pieces are always included, then a
        # window around the first incomplete piece (or the tail when complete).
        selected_indices = []
        seen = set()

        def add_index(index: int):
            if 0 <= index < total_pieces and index not in seen and len(selected_indices) < detail_limit:
                seen.add(index)
                selected_indices.append(index)

        for record in records:
            if record["state"] in ("Downloading", "Requested"):
                add_index(record["index"])

        first_incomplete = next(
            (record["index"] for record in records if record["state"] != "Verified"),
            None,
        )
        if first_incomplete is None:
            window_start = max(0, total_pieces - detail_limit)
        else:
            window_start = max(0, first_incomplete - 8)

        for index in range(window_start, total_pieces):
            add_index(index)
            if len(selected_indices) >= detail_limit:
                break

        details = [records[index] for index in sorted(selected_indices)]

        # The map is bucketed for large torrents so an 8,000-piece torrent does
        # not require thousands of Dear PyGui draw items every half second. For
        # smaller torrents each cell still represents exactly one piece.
        map_cells = []
        if total_pieces:
            pieces_per_cell = max(1, math.ceil(total_pieces / map_cell_limit))
            for start in range(0, total_pieces, pieces_per_cell):
                end = min(total_pieces, start + pieces_per_cell)
                codes = state_codes[start:end]
                bucket_availability = max(availability[start:end], default=0)

                if codes and all(code == "V" for code in codes):
                    bucket_state = "verified"
                elif "D" in codes:
                    bucket_state = "downloading"
                elif "R" in codes:
                    bucket_state = "requested"
                elif "V" in codes:
                    bucket_state = "mixed"
                elif have_peer_availability and bucket_availability == 0:
                    bucket_state = "unavailable"
                else:
                    bucket_state = "missing"

                map_cells.append({
                    "start": start,
                    "end": end - 1,
                    "state": bucket_state,
                    "availability": bucket_availability,
                })
        else:
            pieces_per_cell = 1

        return {
            "total": total_pieces,
            "verified": verified_count,
            "downloading": downloading_count,
            "requested": requested_count,
            "missing": missing_count,
            "remaining_wanted_blocks": remaining_wanted_blocks,
            "outstanding_wire_requests": outstanding_wire_requests,
            "duplicate_wire_requests": duplicate_wire_requests,
            "endgame_active": bool(0 < remaining_wanted_blocks <= ENDGAME_BLOCK_THRESHOLD),
            "endgame_threshold_blocks": ENDGAME_BLOCK_THRESHOLD,
            "swarm_availability": swarm_availability,
            "pieces_per_map_cell": pieces_per_cell,
            "map_cells": map_cells,
            "details": details,
            "disk_io": self.disk_io_snapshot(),
        }

    def completed_bitfield(self) -> bytes:
        return self._build_completed_bitfield()

    def release_requests(self, blocks: Iterable[Block]):
        """Compatibility helper: release every owner of the supplied blocks."""
        for block in blocks:
            if block.data is None:
                self._release_all_block_requests(block)

    def reset_inflight_requests(self):
        """Clear all transient request ownership without allocating new blocks."""
        self._requests_by_peer.clear()
        for piece in self.pieces:
            if not piece.blocks_initialized:
                continue
            for block in piece._blocks or ():
                block.requesters.clear()

    @property
    def completed_pieces(self) -> int:
        with self._disk_state_lock:
            staged = set(self._disk_unqueued_verified)
        return sum(
            1 for piece in self.pieces
            if piece.is_complete and piece.index not in staged
        )

    @property
    def progress(self) -> float:
        if not self.pieces:
            return 1.0 if self.torrent.total_length == 0 else 0.0
        return self.completed_pieces / len(self.pieces)

    @property
    def is_finished(self) -> bool:
        if not self.pieces:
            return self.torrent.total_length == 0
        with self._disk_state_lock:
            if self._disk_unqueued_verified:
                return False
        return all(piece.is_complete for piece in self.pieces)


