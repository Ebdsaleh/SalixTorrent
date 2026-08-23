# app/logic/piece_manager.py

import base64
import hashlib
import json
import math
import os
import threading
import time
from typing import Callable, Iterable, List, Optional

from app.logic.torrent_file import TorrentFile

BLOCK_SIZE = 16384
RESUME_STATE_VERSION = 1


class Block:
    def __init__(self, piece_index: int, offset: int, length: int):
        self.piece_index = piece_index
        self.offset = offset
        self.length = length
        self.data: Optional[bytes] = None
        self.is_requested: bool = False


class Piece:
    def __init__(self, index: int, length: int, expected_hash: bytes):
        self.index = index
        self.length = length
        self.expected_hash = expected_hash
        self._blocks: Optional[List[Block]] = None
        self.is_complete: bool = False

    @property
    def blocks(self) -> List[Block]:
        """Create this piece's blocks only when the piece is actually needed."""
        if self._blocks is None:
            self._blocks = []
            num_blocks = math.ceil(self.length / BLOCK_SIZE)

            for i in range(num_blocks):
                offset = i * BLOCK_SIZE
                block_len = min(BLOCK_SIZE, self.length - offset)
                self._blocks.append(Block(self.index, offset, block_len))

        return self._blocks

    @property
    def blocks_initialized(self) -> bool:
        return self._blocks is not None

    def reset(self):
        self.is_complete = False

        if self._blocks is None:
            return

        for block in self._blocks:
            block.data = None
            block.is_requested = False

    def reset_requests(self):
        """Release in-flight requests without allocating any new block objects."""
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

    def verify_hash(self) -> bool:
        piece_bytes = self.get_data()
        return hashlib.sha1(piece_bytes).digest() == self.expected_hash


class PieceManager:
    """
    Coordinates block dispatching, SHA-1 verification, disk writes, and
    persistent fast-resume state.
    """

    def __init__(self, torrent: TorrentFile, download_dir: str = "downloads"):
        self.torrent = torrent
        self.download_dir = download_dir
        self.output_path = os.path.join(download_dir, torrent.name)

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

        # Progress for the *checking operation*, separate from download progress.
        self.check_progress: float = 0.0
        self.check_checked_pieces: int = 0
        self.check_total_pieces: int = 0
        self.fast_resume_used: bool = False

        # Keep construction cheap. Do NOT allocate every 16 KiB block and do
        # NOT scan/hash an existing multi-gigabyte file on the GUI thread.
        self._initialize_pieces()

    def _initialize_pieces(self):
        total_remaining = self.torrent.total_length

        for idx, expected_hash in enumerate(self.torrent.pieces):
            piece_len = min(self.torrent.piece_length, total_remaining)
            self.pieces.append(Piece(idx, piece_len, expected_hash))
            total_remaining -= piece_len

    @property
    def storage_prepared(self) -> bool:
        return self._storage_prepared

    def _set_check_progress(self, checked: int, total: int):
        total = max(0, int(total))
        checked = max(0, min(int(checked), total if total else 0))

        self.check_checked_pieces = checked
        self.check_total_pieces = total

        if total == 0:
            self.check_progress = 1.0
        else:
            self.check_progress = max(0.0, min(1.0, checked / total))

    def _wait_if_paused(
        self,
        cancel_event: Optional[threading.Event],
        pause_event: Optional[threading.Event],
    ) -> bool:
        """
        Wait while checking is paused.

        Returns False if cancellation is requested while paused.
        """
        if pause_event is None:
            return not (cancel_event and cancel_event.is_set())

        while not pause_event.is_set():
            if cancel_event and cancel_event.is_set():
                return False
            pause_event.wait(timeout=0.1)

        return not (cancel_event and cancel_event.is_set())

    def prepare_storage(
        self,
        cancel_event: Optional[threading.Event] = None,
        progress_callback: Optional[Callable[[], None]] = None,
        pause_event: Optional[threading.Event] = None,
    ) -> bool:
        """
        Prepare the output file and verify any existing pieces.

        TorrentSession runs this method with asyncio.to_thread(), keeping disk
        I/O and SHA-1 hashing off both the Dear PyGui thread and the asyncio
        engine thread.

        Fast-resume behavior:
        - If a valid Salix resume sidecar exists and the payload file has not
          changed since that sidecar was written, verified piece state is
          restored immediately without hashing the entire payload again.
        - Otherwise a normal SHA-1 check runs and a fresh resume sidecar is
          saved when it completes.

        Returns True when preparation completed, or False when cancelled.
        """
        with self._prepare_lock:
            if self._storage_prepared:
                self._set_check_progress(
                    self.check_total_pieces,
                    self.check_total_pieces,
                )
                if progress_callback:
                    progress_callback()
                return True

            if cancel_event and cancel_event.is_set():
                return False

            if not self._wait_if_paused(cancel_event, pause_event):
                return False

            os.makedirs(self.download_dir, exist_ok=True)

            if not os.path.exists(self.output_path):
                # A stale sidecar without its payload is never valid.
                self._delete_resume_state()

                # Create an empty file only. Pieces extend it as they are
                # written, avoiding a synchronous multi-gigabyte preallocation.
                with open(self.output_path, "wb"):
                    pass

                self.downloaded_bytes = 0
                self.fast_resume_used = False
                self._set_check_progress(0, 0)
                self._storage_prepared = True

                if progress_callback:
                    progress_callback()
                return True

            # Fast path: trust only a resume sidecar whose torrent metadata and
            # payload file identity (size + nanosecond mtime) still match.
            if self._load_resume_state():
                self.fast_resume_used = True
                self._set_check_progress(len(self.pieces), len(self.pieces))
                self._storage_prepared = True

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
                self.save_resume_state()

            return completed

    def _pieces_physically_present(self, file_size: int) -> int:
        if file_size <= 0 or not self.pieces:
            return 0

        capped_size = min(file_size, self.torrent.total_length)
        pieces_present = (
            capped_size + self.torrent.piece_length - 1
        ) // self.torrent.piece_length

        return min(len(self.pieces), pieces_present)

    def _check_existing_pieces(
        self,
        cancel_event: Optional[threading.Event] = None,
        progress_callback: Optional[Callable[[], None]] = None,
        pause_event: Optional[threading.Event] = None,
    ) -> bool:
        """Scan an existing output file and mark SHA-1 verified pieces."""
        if not os.path.exists(self.output_path):
            self._set_check_progress(0, 0)
            return True

        # A cancelled/partial previous check may have marked some pieces. A
        # fresh check starts from a known state so counters cannot double.
        self.downloaded_bytes = 0
        for piece in self.pieces:
            piece.is_complete = False

        file_size = os.path.getsize(self.output_path)
        pieces_to_check = self._pieces_physically_present(file_size)
        self._set_check_progress(0, pieces_to_check)

        if progress_callback:
            progress_callback()

        if pieces_to_check == 0:
            return True

        # Throttle UI snapshots to roughly 10 Hz while still reporting integer
        # percentage changes immediately. This feels real-time without flooding
        # Dear PyGui with thousands of queued messages.
        last_callback_time = time.monotonic()
        last_reported_percent = -1

        with open(self.output_path, "rb") as file_handle:
            for scan_index in range(pieces_to_check):
                if cancel_event and cancel_event.is_set():
                    return False

                if not self._wait_if_paused(cancel_event, pause_event):
                    return False

                piece = self.pieces[scan_index]
                file_offset = piece.index * self.torrent.piece_length

                file_handle.seek(file_offset)
                data = file_handle.read(piece.length)

                if (
                    len(data) == piece.length
                    and hashlib.sha1(data).digest() == piece.expected_hash
                ):
                    piece.is_complete = True
                    self.downloaded_bytes += piece.length

                checked = scan_index + 1
                self._set_check_progress(checked, pieces_to_check)

                percent = int(self.check_progress * 100)
                now = time.monotonic()

                if progress_callback and (
                    percent != last_reported_percent
                    or now - last_callback_time >= 0.10
                ):
                    progress_callback()
                    last_callback_time = now
                    last_reported_percent = percent

        self._set_check_progress(pieces_to_check, pieces_to_check)

        if progress_callback:
            progress_callback()

        return True

    def _build_completed_bitfield(self) -> bytes:
        bitfield = bytearray(math.ceil(len(self.pieces) / 8))

        for piece in self.pieces:
            if not piece.is_complete:
                continue

            byte_idx = piece.index // 8
            bit_idx = 7 - (piece.index % 8)
            bitfield[byte_idx] |= 1 << bit_idx

        return bytes(bitfield)

    def _apply_completed_bitfield(self, raw_bitfield: bytes) -> bool:
        required_bytes = math.ceil(len(self.pieces) / 8)
        if len(raw_bitfield) != required_bytes:
            return False

        downloaded_bytes = 0

        for piece in self.pieces:
            byte_idx = piece.index // 8
            bit_idx = 7 - (piece.index % 8)
            is_complete = bool(raw_bitfield[byte_idx] & (1 << bit_idx))
            piece.is_complete = is_complete

            if is_complete:
                downloaded_bytes += piece.length

        self.downloaded_bytes = downloaded_bytes
        return True

    def _resume_metadata_matches(self, state: dict, file_stat: os.stat_result) -> bool:
        try:
            return (
                state.get("version") == RESUME_STATE_VERSION
                and state.get("info_hash") == self.torrent.hex_info_hash
                and state.get("torrent_name") == self.torrent.name
                and int(state.get("total_length", -1)) == self.torrent.total_length
                and int(state.get("piece_length", -1)) == self.torrent.piece_length
                and int(state.get("piece_count", -1)) == len(self.pieces)
                and int(state.get("file_size", -1)) == file_stat.st_size
                and int(state.get("file_mtime_ns", -1)) == file_stat.st_mtime_ns
            )
        except (TypeError, ValueError):
            return False

    def _load_resume_state(self) -> bool:
        if not os.path.exists(self.output_path):
            return False
        if not os.path.exists(self.resume_path):
            return False

        try:
            with open(self.resume_path, "r", encoding="utf-8") as file_handle:
                state = json.load(file_handle)

            if not isinstance(state, dict):
                return False

            file_stat = os.stat(self.output_path)
            if not self._resume_metadata_matches(state, file_stat):
                return False

            encoded_bitfield = state.get("completed_bitfield")
            if not isinstance(encoded_bitfield, str):
                return False

            raw_bitfield = base64.b64decode(
                encoded_bitfield.encode("ascii"),
                validate=True,
            )

            if not self._apply_completed_bitfield(raw_bitfield):
                return False

            return True

        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False

    def save_resume_state(self) -> bool:
        """
        Persist verified piece state atomically.

        This file is deliberately small: completed pieces are encoded as a
        compact bitfield instead of a large JSON list of piece numbers.

        A partially completed *checking* pass is intentionally not persisted:
        unchecked pieces must never be mistaken for verified resume state.
        """
        if not self._storage_prepared:
            return False
        if not os.path.exists(self.output_path):
            return False

        with self._resume_lock:
            try:
                os.makedirs(self.resume_dir, exist_ok=True)
                file_stat = os.stat(self.output_path)
                bitfield = self._build_completed_bitfield()

                state = {
                    "version": RESUME_STATE_VERSION,
                    "info_hash": self.torrent.hex_info_hash,
                    "torrent_name": self.torrent.name,
                    "total_length": self.torrent.total_length,
                    "piece_length": self.torrent.piece_length,
                    "piece_count": len(self.pieces),
                    "file_size": file_stat.st_size,
                    "file_mtime_ns": file_stat.st_mtime_ns,
                    "completed_bitfield": base64.b64encode(bitfield).decode("ascii"),
                    "completed_pieces": self.completed_pieces,
                    "downloaded_bytes": self.downloaded_bytes,
                }

                temp_path = f"{self.resume_path}.tmp"
                with open(temp_path, "w", encoding="utf-8") as file_handle:
                    json.dump(state, file_handle, separators=(",", ":"))
                    file_handle.flush()
                    os.fsync(file_handle.fileno())

                os.replace(temp_path, self.resume_path)
                return True

            except OSError:
                return False

    def _delete_resume_state(self):
        try:
            if os.path.exists(self.resume_path):
                os.remove(self.resume_path)
        except OSError:
            pass

    def get_next_request(self, peer_bitfield: bytearray) -> Optional[Block]:
        for piece in self.pieces:
            if piece.is_complete:
                continue

            byte_idx = piece.index // 8
            bit_idx = 7 - (piece.index % 8)

            if byte_idx >= len(peer_bitfield):
                continue
            if not (peer_bitfield[byte_idx] & (1 << bit_idx)):
                continue

            # Accessing piece.blocks here lazily creates blocks only for pieces
            # that a connected peer can actually provide.
            for block in piece.blocks:
                if not block.is_requested and block.data is None:
                    block.is_requested = True
                    return block

        return None

    def handle_block_received(self, piece_index: int, offset: int, data: bytes) -> bool:
        if piece_index < 0 or piece_index >= len(self.pieces):
            return False

        piece = self.pieces[piece_index]
        matched_block: Optional[Block] = None

        for block in piece.blocks:
            if block.offset == offset:
                matched_block = block
                break

        if matched_block is None:
            return False

        # Reject malformed block sizes and make the block available for retry.
        if len(data) != matched_block.length:
            matched_block.is_requested = False
            return False

        if matched_block.data is None:
            matched_block.data = data
            matched_block.is_requested = False
            self.downloaded_bytes += len(data)

        if not piece.is_all_blocks_received():
            return False

        if piece.verify_hash():
            self._write_piece_to_disk(piece)
            piece.is_complete = True

            # Keep fast-resume state current after every verified piece. The
            # sidecar is tiny and atomically replaced, so a normal restart can
            # skip an expensive full-file rehash.
            self.save_resume_state()
            return True

        # Bad piece: remove its received bytes from the counter and allow all
        # blocks in that piece to be requested again.
        self.downloaded_bytes = max(
            0,
            self.downloaded_bytes - piece.received_byte_count(),
        )
        piece.reset()
        return False

    def _write_piece_to_disk(self, piece: Piece):
        os.makedirs(self.download_dir, exist_ok=True)

        if not os.path.exists(self.output_path):
            with open(self.output_path, "wb"):
                pass

        file_offset = piece.index * self.torrent.piece_length
        with open(self.output_path, "r+b") as file_handle:
            file_handle.seek(file_offset)
            file_handle.write(piece.get_data())

    def read_block(self, piece_index: int, offset: int, length: int) -> bytes:
        """Read a verified block from disk for upload/seeding."""
        if piece_index < 0 or piece_index >= len(self.pieces):
            return b""

        piece = self.pieces[piece_index]
        if not piece.is_complete:
            return b""

        if offset < 0 or length <= 0:
            return b""
        if offset + length > piece.length:
            return b""
        if length > BLOCK_SIZE:
            return b""
        if not os.path.exists(self.output_path):
            return b""

        file_offset = piece.index * self.torrent.piece_length + offset

        try:
            with open(self.output_path, "rb") as file_handle:
                file_handle.seek(file_offset)
                data = file_handle.read(length)
            return data if len(data) == length else b""
        except OSError:
            return b""

    def completed_bitfield(self) -> bytes:
        """Return the wire-format piece bitfield advertised to peers."""
        return self._build_completed_bitfield()

    def release_requests(self, blocks: Iterable[Block]):
        """Release blocks owned by a peer that disconnected or was cancelled."""
        for block in blocks:
            if block.data is None:
                block.is_requested = False

    def reset_inflight_requests(self):
        """Release every outstanding request without defeating lazy blocks."""
        for piece in self.pieces:
            piece.reset_requests()

    @property
    def completed_pieces(self) -> int:
        return sum(1 for piece in self.pieces if piece.is_complete)

    @property
    def progress(self) -> float:
        return self.completed_pieces / len(self.pieces) if self.pieces else 0.0

    @property
    def is_finished(self) -> bool:
        return bool(self.pieces) and all(piece.is_complete for piece in self.pieces)
