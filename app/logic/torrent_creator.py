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


HASH_READ_SIZE = 1024 * 1024
MIN_PIECE_LENGTH = 16 * 1024
MAX_PIECE_LENGTH = 16 * 1024 * 1024


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


class TorrentCreator:
    """Creates standard v1 SHA-1 .torrent metainfo files.

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

        tracker_list = cls.normalise_trackers(trackers)
        if not tracker_list:
            tracker_list = list(FALLBACK_TRACKERS)

        if cancel_event and cancel_event.is_set():
            raise TorrentCreationCancelled()

        pieces: List[bytes] = []
        piece_hasher = hashlib.sha1()
        bytes_in_piece = 0
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

        for source_file in files:
            if cancel_event and cancel_event.is_set():
                raise TorrentCreationCancelled()

            current_name = os.path.join(*source_file.relative_parts)
            with open(source_file.absolute_path, "rb") as file_handle:
                remaining_file = source_file.length

                while remaining_file > 0:
                    if cancel_event and cancel_event.is_set():
                        raise TorrentCreationCancelled()

                    room = resolved_piece_length - bytes_in_piece
                    read_size = min(HASH_READ_SIZE, room, remaining_file)
                    chunk = file_handle.read(read_size)
                    if len(chunk) != read_size:
                        raise OSError(
                            f"Source file changed or became unreadable while hashing: {current_name}"
                        )

                    piece_hasher.update(chunk)
                    bytes_in_piece += len(chunk)
                    bytes_hashed += len(chunk)
                    remaining_file -= len(chunk)

                    if bytes_in_piece == resolved_piece_length:
                        pieces.append(piece_hasher.digest())
                        piece_hasher = hashlib.sha1()
                        bytes_in_piece = 0

                    emit("Hashing", current_name)

            after = os.stat(source_file.absolute_path)
            if (
                after.st_size != source_file.length
                or after.st_mtime_ns != source_file.mtime_ns
            ):
                raise RuntimeError(
                    f"Source changed while the torrent was being created: {current_name}"
                )

        if bytes_in_piece > 0:
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

        info = {
            b"name": source.name,
            b"piece length": resolved_piece_length,
            b"pieces": b"".join(pieces),
        }

        if private:
            info[b"private"] = 1

        if is_multi_file:
            info[b"files"] = [
                {
                    b"length": item.length,
                    b"path": list(item.relative_parts),
                }
                for item in files
            ]
        else:
            info[b"length"] = files[0].length

        metainfo = {
            b"announce": tracker_list[0],
            b"announce-list": [[tracker] for tracker in tracker_list],
            b"created by": "SalixTorrent (Salix_T)",
            b"creation date": int(time.time()),
            b"info": info,
        }

        clean_comment = str(comment).strip()
        if clean_comment:
            metainfo[b"comment"] = clean_comment

        encoded_info = Bencode.encode(info)
        encoded_torrent = Bencode.encode(metainfo)
        info_hash = hashlib.sha1(encoded_info).hexdigest()

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

        return TorrentCreationResult(
            output_path=output_abs,
            info_hash=info_hash,
            torrent_name=source.name,
            total_bytes=total_bytes,
            file_count=len(files),
            piece_length=resolved_piece_length,
            piece_count=len(pieces),
            tracker_count=len(tracker_list),
            skipped_symlinks=skipped_symlinks,
            is_multi_file=is_multi_file,
        )
