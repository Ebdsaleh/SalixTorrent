# app/logic/torrent_creator.py

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from app.logic.bencode import Bencode
from app.logic.torrent_file import FALLBACK_TRACKERS
from app.logic.torrent_v2 import (
    MERKLE_BLOCK_SIZE,
    merkle_root_from_hashes,
    piece_layer_depth,
    validate_piece_length as validate_v2_piece_length,
    zero_hash,
)


HASH_READ_SIZE = 1024 * 1024
MIN_PIECE_LENGTH = 16 * 1024
MAX_PIECE_LENGTH = 16 * 1024 * 1024

TORRENT_GENERATION_HYBRID = "Hybrid v1/v2 (Recommended)"
TORRENT_GENERATION_V1 = "BitTorrent v1"
TORRENT_GENERATION_V2 = "BitTorrent v2"
TORRENT_GENERATIONS = (
    TORRENT_GENERATION_HYBRID,
    TORRENT_GENERATION_V1,
    TORRENT_GENERATION_V2,
)


def normalise_torrent_generation(value: object) -> str:
    text = str(value or TORRENT_GENERATION_HYBRID).strip()
    aliases = {
        "hybrid": TORRENT_GENERATION_HYBRID,
        "hybrid v1/v2": TORRENT_GENERATION_HYBRID,
        "hybrid v1/v2 (recommended)": TORRENT_GENERATION_HYBRID,
        "v1": TORRENT_GENERATION_V1,
        "bittorrent v1": TORRENT_GENERATION_V1,
        "v2": TORRENT_GENERATION_V2,
        "bittorrent v2": TORRENT_GENERATION_V2,
    }
    return aliases.get(text.lower(), text if text in TORRENT_GENERATIONS else TORRENT_GENERATION_HYBRID)


class TorrentCreationCancelled(Exception):
    """Raised when a torrent creation operation is cancelled by the user."""


@dataclass(frozen=True)
class SourceFile:
    absolute_path: str
    relative_parts: Tuple[str, ...]
    length: int
    mtime_ns: int


@dataclass(frozen=True)
class TorrentCreationProgress:
    phase: str
    bytes_hashed: int
    total_bytes: int
    pieces_hashed: int
    current_file: str

    @property
    def fraction(self) -> float:
        if self.total_bytes <= 0:
            return 1.0
        return max(0.0, min(1.0, self.bytes_hashed / self.total_bytes))


@dataclass(frozen=True)
class TorrentCreationResult:
    output_path: str
    info_hash: str
    torrent_name: str
    total_bytes: int
    file_count: int
    piece_length: int
    piece_count: int
    tracker_count: int
    skipped_symlinks: int
    is_multi_file: bool
    generation: str = TORRENT_GENERATION_V1
    v1_info_hash: str = ""
    v2_info_hash: str = ""


class TorrentCreator:
    """Creates BitTorrent v1, BEP-52 v2, or BEP-52/BEP-47 hybrid metainfo.

    Files (including archives such as .zip, .7z and .iso) become normal
    single-file torrents. Directories become standard multi-file torrents whose
    piece stream spans files in deterministic relative-path order.
    """

    @staticmethod
    def choose_piece_length(total_bytes: int) -> int:
        """Choose a conventional piece size from the source payload size."""
        mib = 1024 * 1024
        gib = 1024 * mib

        if total_bytes <= 64 * mib:
            return 256 * 1024
        if total_bytes <= 512 * mib:
            return 512 * 1024
        if total_bytes <= 2 * gib:
            return 1 * mib
        if total_bytes <= 8 * gib:
            return 2 * mib
        if total_bytes <= 32 * gib:
            return 4 * mib
        if total_bytes <= 128 * gib:
            return 8 * mib
        return 16 * mib

    @staticmethod
    def normalise_trackers(trackers: Optional[Iterable[str]]) -> List[str]:
        result: List[str] = []
        for tracker in trackers or []:
            tracker = str(tracker).strip()
            if not tracker or tracker.startswith("#"):
                continue
            if tracker not in result:
                result.append(tracker)
        return result

    @staticmethod
    def _validate_piece_length(piece_length: int):
        if piece_length < MIN_PIECE_LENGTH or piece_length > MAX_PIECE_LENGTH:
            raise ValueError(
                "Piece size must be between 16 KiB and 16 MiB."
            )
        if piece_length & (piece_length - 1):
            raise ValueError("Piece size must be a power of two.")

    @classmethod
    def _scan_source(
        cls,
        source_path: str,
        exclusions: Optional[Sequence[str]] = None,
    ) -> Tuple[Path, bool, List[SourceFile], int]:
        source = Path(source_path).expanduser().resolve()
        excluded = {
            os.path.normcase(os.path.abspath(path))
            for path in (exclusions or [])
            if path
        }

        if not source.exists():
            raise FileNotFoundError(f"Source does not exist: {source}")

        skipped_symlinks = 0

        if source.is_file():
            if source.is_symlink():
                raise ValueError("A symbolic link cannot be used as the source file.")
            stat = source.stat()
            return (
                source,
                False,
                [
                    SourceFile(
                        absolute_path=str(source),
                        relative_parts=(source.name,),
                        length=stat.st_size,
                        mtime_ns=stat.st_mtime_ns,
                    )
                ],
                0,
            )

        if not source.is_dir():
            raise ValueError("Source must be a regular file or directory.")

        files: List[SourceFile] = []

        for root, dirnames, filenames in os.walk(source, followlinks=False):
            # Do not traverse directory symlinks. os.walk exposes them through
            # dirnames when followlinks=False, so remove them explicitly and
            # report them to the user instead of silently hashing outside data.
            kept_dirs = []
            for dirname in dirnames:
                full_dir = Path(root) / dirname
                if full_dir.is_symlink():
                    skipped_symlinks += 1
                else:
                    kept_dirs.append(dirname)
            dirnames[:] = kept_dirs

            for filename in filenames:
                full_path = (Path(root) / filename)
                normalised = os.path.normcase(os.path.abspath(str(full_path)))
                if normalised in excluded:
                    continue
                if full_path.is_symlink():
                    skipped_symlinks += 1
                    continue
                if not full_path.is_file():
                    continue

                stat = full_path.stat()
                relative = full_path.relative_to(source)
                files.append(
                    SourceFile(
                        absolute_path=str(full_path),
                        relative_parts=tuple(relative.parts),
                        length=stat.st_size,
                        mtime_ns=stat.st_mtime_ns,
                    )
                )

        files.sort(
            key=lambda item: tuple(
                part.encode("utf-8", errors="surrogatepass")
                for part in item.relative_parts
            )
        )

        if not files:
            raise ValueError("The selected folder contains no regular files.")

        return source, True, files, skipped_symlinks

    @staticmethod
    def _source_snapshot(files: Sequence[SourceFile]) -> Tuple[Tuple[Tuple[str, ...], int, int], ...]:
        return tuple(
            (item.relative_parts, item.length, item.mtime_ns)
            for item in files
        )

    @classmethod
    def create(
        cls,
        source_path: str,
        output_path: str,
        trackers: Optional[Iterable[str]] = None,
        piece_length: Optional[int] = None,
        comment: str = "",
        private: bool = False,
        cancel_event: Optional[threading.Event] = None,
        progress_callback: Optional[Callable[[TorrentCreationProgress], None]] = None,
        generation: str = TORRENT_GENERATION_HYBRID,
    ) -> TorrentCreationResult:
        source_abs = os.path.abspath(os.path.expanduser(source_path))
        output_abs = os.path.abspath(os.path.expanduser(output_path))

        if os.path.normcase(source_abs) == os.path.normcase(output_abs):
            raise ValueError("The .torrent output cannot overwrite the source file.")

        if not output_abs.lower().endswith(".torrent"):
            output_abs += ".torrent"

        output_parent = os.path.dirname(output_abs) or os.getcwd()
        os.makedirs(output_parent, exist_ok=True)
        temp_output = f"{output_abs}.salix_tmp"

        source, is_multi_file, files, skipped_symlinks = cls._scan_source(
            source_abs,
            exclusions=[output_abs, temp_output],
        )
        initial_snapshot = cls._source_snapshot(files)
        total_bytes = sum(item.length for item in files)

        resolved_piece_length = piece_length or cls.choose_piece_length(total_bytes)
        cls._validate_piece_length(resolved_piece_length)
        generation = normalise_torrent_generation(generation)
        wants_v1 = generation in {TORRENT_GENERATION_HYBRID, TORRENT_GENERATION_V1}
        wants_v2 = generation in {TORRENT_GENERATION_HYBRID, TORRENT_GENERATION_V2}
        if wants_v2:
            validate_v2_piece_length(resolved_piece_length)

        tracker_list = cls.normalise_trackers(trackers)
        if not tracker_list:
            tracker_list = list(FALLBACK_TRACKERS)

        if cancel_event and cancel_event.is_set():
            raise TorrentCreationCancelled()

        pieces: List[bytes] = []
        piece_hasher = hashlib.sha1()
        bytes_in_piece = 0
        v2_file_records: List[dict] = []
        piece_layers: dict[bytes, bytes] = {}
        bytes_hashed = 0
        last_emit_time = 0.0
        last_percent = -1

        def emit(phase: str, current_file: str = "", force: bool = False):
            nonlocal last_emit_time, last_percent
            if not progress_callback:
                return

            percent = 100 if total_bytes <= 0 else int((bytes_hashed / total_bytes) * 100)
            now = time.monotonic()
            if not force and percent == last_percent and now - last_emit_time < 0.10:
                return

            progress_callback(
                TorrentCreationProgress(
                    phase=phase,
                    bytes_hashed=bytes_hashed,
                    total_bytes=total_bytes,
                    pieces_hashed=len(pieces),
                    current_file=current_file,
                )
            )
            last_emit_time = now
            last_percent = percent

        emit("Scanning source", force=True)

        def feed_v1(payload: bytes):
            nonlocal piece_hasher, bytes_in_piece
            if not wants_v1:
                return
            view = memoryview(payload)
            cursor = 0
            while cursor < len(view):
                room = resolved_piece_length - bytes_in_piece
                take = min(room, len(view) - cursor)
                piece_hasher.update(view[cursor:cursor + take])
                bytes_in_piece += take
                cursor += take
                if bytes_in_piece == resolved_piece_length:
                    pieces.append(piece_hasher.digest())
                    piece_hasher = hashlib.sha1()
                    bytes_in_piece = 0

        for source_index, source_file in enumerate(files):
            if cancel_event and cancel_event.is_set():
                raise TorrentCreationCancelled()

            current_name = os.path.join(*source_file.relative_parts)
            leaf_hashes: List[bytes] = []
            leaf_buffer = bytearray()
            with open(source_file.absolute_path, "rb") as file_handle:
                remaining_file = source_file.length

                while remaining_file > 0:
                    if cancel_event and cancel_event.is_set():
                        raise TorrentCreationCancelled()

                    read_size = min(HASH_READ_SIZE, remaining_file)
                    chunk = file_handle.read(read_size)
                    if len(chunk) != read_size:
                        raise OSError(
                            f"Source file changed or became unreadable while hashing: {current_name}"
                        )

                    feed_v1(chunk)
                    if wants_v2:
                        leaf_buffer.extend(chunk)
                        while len(leaf_buffer) >= MERKLE_BLOCK_SIZE:
                            block = bytes(leaf_buffer[:MERKLE_BLOCK_SIZE])
                            del leaf_buffer[:MERKLE_BLOCK_SIZE]
                            leaf_hashes.append(hashlib.sha256(block).digest())
                    bytes_hashed += len(chunk)
                    remaining_file -= len(chunk)

                    emit("Hashing", current_name)

            if wants_v2 and leaf_buffer:
                leaf_hashes.append(hashlib.sha256(bytes(leaf_buffer)).digest())

            if wants_v2:
                if source_file.length:
                    pieces_root = merkle_root_from_hashes(leaf_hashes, base_layer=0)
                    depth = piece_layer_depth(resolved_piece_length)
                    leaves_per_piece = 1 << depth
                    file_piece_hashes: List[bytes] = []
                    for start in range(0, len(leaf_hashes), leaves_per_piece):
                        group = list(leaf_hashes[start:start + leaves_per_piece])
                        if len(group) < leaves_per_piece:
                            group.extend([zero_hash(0)] * (leaves_per_piece - len(group)))
                        file_piece_hashes.append(merkle_root_from_hashes(group, base_layer=0))
                    if source_file.length > resolved_piece_length:
                        piece_layers[pieces_root] = b"".join(file_piece_hashes)
                else:
                    pieces_root = b""

                v2_file_records.append({
                    "source": source_file,
                    "pieces_root": pieces_root,
                })

            # Hybrid v1 piece space must match BEP-52's per-file alignment.
            if (
                generation == TORRENT_GENERATION_HYBRID
                and source_index < len(files) - 1
                and source_file.length % resolved_piece_length
            ):
                padding = (-source_file.length) % resolved_piece_length
                feed_v1(b"\x00" * padding)

            after = os.stat(source_file.absolute_path)
            if (
                after.st_size != source_file.length
                or after.st_mtime_ns != source_file.mtime_ns
            ):
                raise RuntimeError(
                    f"Source changed while the torrent was being created: {current_name}"
                )

        if wants_v1 and bytes_in_piece > 0:
            pieces.append(piece_hasher.digest())

        emit("Building metainfo", force=True)

        if cancel_event and cancel_event.is_set():
            raise TorrentCreationCancelled()

        # For folders, ensure files were not added/deleted/changed after the
        # initial scan. The torrent should describe one coherent source snapshot.
        if is_multi_file:
            _, _, final_files, _ = cls._scan_source(
                str(source),
                exclusions=[output_abs, temp_output],
            )
            if cls._source_snapshot(final_files) != initial_snapshot:
                raise RuntimeError(
                    "The source folder changed while it was being hashed. "
                    "Please try creating the torrent again."
                )

        info = {b"name": source.name, b"piece length": resolved_piece_length}

        if wants_v1:
            info[b"pieces"] = b"".join(pieces)

        if private:
            info[b"private"] = 1

        if wants_v1:
            if is_multi_file:
                v1_files = []
                for index, item in enumerate(files):
                    v1_files.append({b"length": item.length, b"path": list(item.relative_parts)})
                    if (
                        generation == TORRENT_GENERATION_HYBRID
                        and index < len(files) - 1
                        and item.length % resolved_piece_length
                    ):
                        padding = (-item.length) % resolved_piece_length
                        v1_files.append({
                            b"attr": b"p",
                            b"length": padding,
                            b"path": [
                                b".pad",
                                f"{padding}.{index}".encode("ascii"),
                            ],
                        })
                info[b"files"] = v1_files
            else:
                info[b"length"] = files[0].length

        if wants_v2:
            info[b"meta version"] = 2
            file_tree: dict = {}
            for record in v2_file_records:
                item: SourceFile = record["source"]
                node = file_tree
                for part in item.relative_parts:
                    key = part.encode("utf-8", errors="surrogatepass")
                    node = node.setdefault(key, {})
                props = {b"length": item.length}
                if item.length:
                    props[b"pieces root"] = record["pieces_root"]
                node[b""] = props
            info[b"file tree"] = file_tree

        metainfo = {
            b"announce": tracker_list[0],
            b"announce-list": [[tracker] for tracker in tracker_list],
            b"created by": "SalixTorrent (Salix_T)",
            b"creation date": int(time.time()),
            b"info": info,
        }
        if wants_v2:
            metainfo[b"piece layers"] = piece_layers

        clean_comment = str(comment).strip()
        if clean_comment:
            metainfo[b"comment"] = clean_comment

        encoded_info = Bencode.encode(info)
        encoded_torrent = Bencode.encode(metainfo)
        v1_info_hash = hashlib.sha1(encoded_info).hexdigest() if wants_v1 else ""
        v2_info_hash = hashlib.sha256(encoded_info).hexdigest() if wants_v2 else ""
        info_hash = v1_info_hash or v2_info_hash

        try:
            with open(temp_output, "wb") as file_handle:
                file_handle.write(encoded_torrent)
                file_handle.flush()
                os.fsync(file_handle.fileno())
            os.replace(temp_output, output_abs)
        finally:
            try:
                if os.path.exists(temp_output):
                    os.remove(temp_output)
            except OSError:
                pass

        bytes_hashed = total_bytes
        emit("Complete", force=True)

        v2_piece_count = sum(
            (item.length + resolved_piece_length - 1) // resolved_piece_length
            for item in files
            if item.length > 0
        )
        result_piece_count = len(pieces) if wants_v1 else v2_piece_count

        return TorrentCreationResult(
            output_path=output_abs,
            info_hash=info_hash,
            torrent_name=source.name,
            total_bytes=total_bytes,
            file_count=len(files),
            piece_length=resolved_piece_length,
            piece_count=result_piece_count,
            tracker_count=len(tracker_list),
            skipped_symlinks=skipped_symlinks,
            is_multi_file=is_multi_file,
            generation=generation,
            v1_info_hash=v1_info_hash,
            v2_info_hash=v2_info_hash,
        )


