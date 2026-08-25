# app/logic/piece_manager.py

from __future__ import annotations

import base64
import bisect
import hashlib
import json
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional

from app.logic.torrent_file import TorrentFile

BLOCK_SIZE = 16384
RESUME_STATE_VERSION = 1
MULTI_FILE_RESUME_INTERVAL = 5.0


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

    def verify_hash(self) -> bool:
        return hashlib.sha1(self.get_data()).digest() == self.expected_hash


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

    def _initialize_pieces(self):
        total_remaining = self.torrent.total_length

        for index, expected_hash in enumerate(self.torrent.pieces):
            piece_len = min(self.torrent.piece_length, total_remaining)
            self.pieces.append(Piece(index, piece_len, expected_hash))
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
                    self.downloaded_bytes = 0
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
            file_offset = piece.index * self.torrent.piece_length
            data = self._read_range(file_offset, piece.length)

            if (
                len(data) == piece.length
                and hashlib.sha1(data).digest() == piece.expected_hash
            ):
                piece.is_complete = True
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
            if is_complete:
                downloaded_bytes += piece.length

        self.downloaded_bytes = downloaded_bytes
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
                bitfield = self._build_completed_bitfield()

                state = {
                    "version": RESUME_STATE_VERSION,
                    "info_hash": self.torrent.hex_info_hash,
                    "torrent_name": self.torrent.name,
                    "total_length": self.torrent.total_length,
                    "piece_length": self.torrent.piece_length,
                    "piece_count": len(self.pieces),
                    "completed_bitfield": base64.b64encode(bitfield).decode("ascii"),
                    "completed_pieces": self.completed_pieces,
                    "downloaded_bytes": self.downloaded_bytes,
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

    def get_next_request(self, peer_bitfield: bytearray) -> Optional[Block]:
        for piece in self.pieces:
            if piece.is_complete:
                continue

            byte_index = piece.index // 8
            bit_index = 7 - (piece.index % 8)
            if byte_index >= len(peer_bitfield):
                continue
            if not (peer_bitfield[byte_index] & (1 << bit_index)):
                continue

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
            self.save_resume_state()
            return True

        self.downloaded_bytes = max(0, self.downloaded_bytes - piece.received_byte_count())
        piece.reset()
        return False

    def _write_piece_to_disk(self, piece: Piece):
        file_offset = piece.index * self.torrent.piece_length
        self._write_range(file_offset, piece.get_data())

    def read_block(self, piece_index: int, offset: int, length: int) -> bytes:
        if piece_index < 0 or piece_index >= len(self.pieces):
            return b""

        piece = self.pieces[piece_index]
        if not piece.is_complete:
            return b""
        if offset < 0 or length <= 0:
            return b""
        if offset + length > piece.length or length > BLOCK_SIZE:
            return b""

        file_offset = piece.index * self.torrent.piece_length + offset
        return self._read_range(file_offset, length)

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

        availability = [0] * total_pieces
        usable_bitfields = []
        for bitfield in peer_bitfields:
            if not bitfield:
                continue
            try:
                raw = bytes(bitfield)
            except Exception:
                continue
            usable_bitfields.append(raw)
            for piece_index in range(total_pieces):
                byte_index = piece_index // 8
                if byte_index >= len(raw):
                    break
                bit_index = 7 - (piece_index % 8)
                if raw[byte_index] & (1 << bit_index):
                    availability[piece_index] += 1

        records = []
        state_codes = []
        verified_count = 0
        downloading_count = 0
        requested_count = 0
        missing_count = 0

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
            have_peer_availability = bool(usable_bitfields)

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
            "swarm_availability": swarm_availability,
            "pieces_per_map_cell": pieces_per_cell,
            "map_cells": map_cells,
            "details": details,
        }

    def completed_bitfield(self) -> bytes:
        return self._build_completed_bitfield()

    def release_requests(self, blocks: Iterable[Block]):
        for block in blocks:
            if block.data is None:
                block.is_requested = False

    def reset_inflight_requests(self):
        for piece in self.pieces:
            piece.reset_requests()

    @property
    def completed_pieces(self) -> int:
        return sum(1 for piece in self.pieces if piece.is_complete)

    @property
    def progress(self) -> float:
        if not self.pieces:
            return 1.0 if self.torrent.total_length == 0 else 0.0
        return self.completed_pieces / len(self.pieces)

    @property
    def is_finished(self) -> bool:
        if not self.pieces:
            return self.torrent.total_length == 0
        return all(piece.is_complete for piece in self.pieces)
