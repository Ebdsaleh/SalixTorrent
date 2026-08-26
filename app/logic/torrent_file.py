# app/logic/torrent_file.py

import hashlib
import os
from urllib.parse import quote
from typing import Any, Dict, List

from app.logic.bencode import Bencode


FALLBACK_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "http://tracker.opentrackr.org:1337/announce",
]


class TorrentFile:
    """Parses and exposes structured metadata from a .torrent file."""

    def __init__(self, file_path: str):
        self.file_path = os.path.abspath(file_path)
        self.announce: str = ""
        self.announce_list: List[str] = []
        self.info_hash: bytes = b""
        self.raw_info_bytes: bytes = b""
        self.piece_length: int = 0
        self.pieces: List[bytes] = []
        self.name: str = ""
        self.total_length: int = 0
        self.is_multi_file: bool = False
        self.files: List[Dict[str, Any]] = []
        self.comment: str = ""
        self.created_by: str = ""
        self.creation_date: int = 0
        self.private: bool = False

        self._load_and_parse()

    @staticmethod
    def _decode_text(value: object, default: str = "") -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if value is None:
            return default
        return str(value)

    @staticmethod
    def _extract_raw_info_bytes(raw_bytes: bytes) -> bytes:
        """Return the exact bencoded top-level ``info`` value bytes.

        The v1 BitTorrent info hash is SHA-1 over the original encoded info
        dictionary, not over a decoded/re-encoded approximation. Preserving the
        exact bytes also makes BEP-9 magnet metadata verification correct for
        torrents whose metainfo was encoded unusually but validly.
        """
        data = bytes(raw_bytes)
        if not data.startswith(b"d"):
            raise ValueError("Root bencoded element must be a dictionary.")

        rest = data[1:]
        while rest and not rest.startswith(b"e"):
            key, after_key = Bencode._decode_item(rest)
            if not isinstance(key, bytes):
                raise ValueError("Torrent root dictionary contains a non-bytes key.")
            value_start = after_key
            _value, after_value = Bencode._decode_item(value_start)
            consumed = len(value_start) - len(after_value)
            if key == b"info":
                return value_start[:consumed]
            rest = after_value

        raise ValueError("Torrent missing valid 'info' dictionary.")

    @staticmethod
    def _validate_component(component: str, label: str) -> str:
        """Reject metainfo path traversal before it reaches the filesystem."""
        if not component:
            raise ValueError(f"Torrent contains an empty {label} path component.")
        if component in (".", ".."):
            raise ValueError(f"Torrent contains unsafe {label} path component: {component!r}")
        if "\x00" in component:
            raise ValueError(f"Torrent contains a NUL byte in {label} metadata.")
        if "/" in component or "\\" in component:
            raise ValueError(
                f"Torrent {label} path components must not contain path separators."
            )
        # Windows drive-relative forms such as C: can escape normal join
        # expectations on that platform. Reject them cross-platform so one
        # .torrent has consistent storage semantics everywhere Salix_T runs.
        if len(component) >= 2 and component[1] == ":":
            raise ValueError(f"Torrent contains an unsafe drive-qualified {label} component.")
        return component

    def _load_and_parse(self):
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Metainfo file not found: {self.file_path}")

        with open(self.file_path, "rb") as file_handle:
            raw_bytes = file_handle.read()

        raw_dict = Bencode.decode(raw_bytes)
        if not isinstance(raw_dict, dict):
            raise ValueError("Root bencoded element must be a dictionary.")

        if b"announce" in raw_dict and raw_dict[b"announce"]:
            self.announce = self._decode_text(raw_dict[b"announce"])
            if self.announce and self.announce not in self.announce_list:
                self.announce_list.append(self.announce)

        if b"announce-list" in raw_dict and raw_dict[b"announce-list"]:
            for tier in raw_dict[b"announce-list"]:
                if isinstance(tier, list):
                    candidates = tier
                else:
                    candidates = [tier]

                for tracker in candidates:
                    url = self._decode_text(tracker).strip()
                    if url and url not in self.announce_list:
                        self.announce_list.append(url)

        if b"comment" in raw_dict:
            self.comment = self._decode_text(raw_dict[b"comment"])
        if b"created by" in raw_dict:
            self.created_by = self._decode_text(raw_dict[b"created by"])
        if b"creation date" in raw_dict:
            try:
                self.creation_date = max(0, int(raw_dict[b"creation date"] or 0))
            except (TypeError, ValueError):
                self.creation_date = 0

        info_dict = raw_dict.get(b"info")
        if not info_dict or not isinstance(info_dict, dict):
            raise ValueError("Torrent missing valid 'info' dictionary.")

        self.raw_info_bytes = self._extract_raw_info_bytes(raw_bytes)
        self.info_hash = hashlib.sha1(self.raw_info_bytes).digest()

        try:
            self.piece_length = int(info_dict[b"piece length"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Torrent missing a valid 'piece length'.") from exc
        if self.piece_length <= 0:
            raise ValueError("Torrent piece length must be greater than zero.")

        raw_name = self._decode_text(info_dict.get(b"name", b"unnamed_download"))
        self.name = self._validate_component(raw_name, "root")

        raw_pieces = info_dict.get(b"pieces")
        if not isinstance(raw_pieces, bytes):
            raise ValueError("Torrent missing valid 'pieces' SHA-1 data.")
        if len(raw_pieces) % 20 != 0:
            raise ValueError("Corrupt 'pieces' binary string: not a multiple of 20 bytes.")
        self.pieces = [
            raw_pieces[index:index + 20]
            for index in range(0, len(raw_pieces), 20)
        ]

        self.private = bool(int(info_dict.get(b"private", 0) or 0))

        # Trackerless public torrents may use SalixTorrent's convenience
        # fallback trackers. Private torrents must never be injected into
        # arbitrary public trackers: their peer discovery is intentionally
        # restricted to tracker metadata supplied by the torrent itself.
        if not self.announce_list and not self.private:
            self.announce_list.extend(FALLBACK_TRACKERS)
            self.announce = self.announce_list[0]

        if b"files" in info_dict:
            self.is_multi_file = True
            raw_files = info_dict[b"files"]
            if not isinstance(raw_files, list):
                raise ValueError("Multi-file torrent has an invalid 'files' list.")

            seen_paths = set()
            for file_entry in raw_files:
                if not isinstance(file_entry, dict):
                    raise ValueError("Multi-file torrent contains an invalid file entry.")

                try:
                    length = int(file_entry[b"length"])
                    raw_path = file_entry[b"path"]
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError("Multi-file torrent contains malformed file metadata.") from exc

                if length < 0:
                    raise ValueError("Torrent file lengths cannot be negative.")
                if not isinstance(raw_path, list) or not raw_path:
                    raise ValueError("Multi-file torrent contains an empty file path.")

                path_parts = [
                    self._validate_component(self._decode_text(part), "file")
                    for part in raw_path
                ]
                relative_path = os.path.join(*path_parts)
                canonical_key = tuple(path_parts)
                if canonical_key in seen_paths:
                    raise ValueError("Multi-file torrent contains duplicate file paths.")
                seen_paths.add(canonical_key)

                self.files.append(
                    {
                        "length": length,
                        "path": relative_path,
                        "path_parts": path_parts,
                    }
                )
                self.total_length += length
        else:
            self.is_multi_file = False
            try:
                self.total_length = int(info_dict[b"length"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Single-file torrent missing a valid 'length'.") from exc
            if self.total_length < 0:
                raise ValueError("Torrent length cannot be negative.")
            self.files.append(
                {
                    "length": self.total_length,
                    "path": self.name,
                    "path_parts": [self.name],
                }
            )

        # A non-empty torrent must have enough piece hashes to cover its byte
        # stream. The final piece may be shorter than piece_length.
        expected_piece_count = (
            (self.total_length + self.piece_length - 1) // self.piece_length
            if self.total_length > 0
            else 0
        )
        if len(self.pieces) != expected_piece_count:
            raise ValueError(
                "Torrent piece hash count does not match its declared payload size."
            )

    @property
    def num_pieces(self) -> int:
        return len(self.pieces)

    @property
    def hex_info_hash(self) -> str:
        return self.info_hash.hex()

    @property
    def magnet_uri(self) -> str:
        """Return a standard BitTorrent v1 magnet URI for this torrent."""
        parts = [f"magnet:?xt=urn:btih:{self.hex_info_hash}"]
        if self.name:
            parts.append(f"dn={quote(self.name, safe='')}")
        for tracker in self.announce_list:
            url = str(tracker or "").strip()
            if url:
                parts.append(f"tr={quote(url, safe='')}")
        return "&".join(parts)
