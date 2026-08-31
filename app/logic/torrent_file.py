import hashlib
import os
from urllib.parse import quote
from typing import Any, Dict, List

from app.logic.bencode import Bencode
from app.logic.torrent_v2 import (
    SHA256_SIZE,
    TorrentIdentity,
    V2_META_VERSION,
    expected_piece_layer_count,
    validate_piece_length as validate_v2_piece_length,
    verify_piece_layer,
)


FALLBACK_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "http://tracker.opentrackr.org:1337/announce",
]


class UnsupportedTorrentVersionError(ValueError):
    """Raised when metainfo advertises a newer incompatible meta version."""


class TorrentFile:
    """Parse v1 and BEP-52 v2 metainfo without assuming a 20-byte identity.

    Phase 8 parses and cryptographically validates the v2 metainfo foundation.
    The live peer/session engine remains v1-only until Phase 9.
    """

    def __init__(self, file_path: str):
        self.file_path = os.path.abspath(file_path)
        self.announce: str = ""
        self.announce_list: List[str] = []
        self.raw_info_bytes: bytes = b""

        # Version-aware identity. Legacy ``info_hash`` remains the v1 SHA-1
        # hash for v1 torrents and the BEP-52 truncated SHA-256 wire form for a
        # v2-only torrent. New code should use ``identity`` explicitly.
        self.identity: TorrentIdentity | None = None
        self.info_hash: bytes = b""
        self.v1_info_hash: bytes = b""
        self.v2_info_hash: bytes = b""
        self.meta_version: int = 1
        self.is_v1: bool = False
        self.is_v2: bool = False
        self.is_hybrid: bool = False

        self.piece_length: int = 0
        self.pieces: List[bytes] = []
        self.v2_piece_layers: Dict[bytes, List[bytes]] = {}
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
        """Return the exact bencoded top-level ``info`` value bytes."""
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
        if len(component) >= 2 and component[1] == ":":
            raise ValueError(f"Torrent contains an unsafe drive-qualified {label} component.")
        return component

    def _parse_trackers_and_common_root(self, raw_dict: dict):
        if b"announce" in raw_dict and raw_dict[b"announce"]:
            self.announce = self._decode_text(raw_dict[b"announce"])
            if self.announce and self.announce not in self.announce_list:
                self.announce_list.append(self.announce)

        if b"announce-list" in raw_dict and raw_dict[b"announce-list"]:
            for tier in raw_dict[b"announce-list"]:
                candidates = tier if isinstance(tier, list) else [tier]
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

    def _parse_v1_payload(self, info_dict: dict):
        raw_pieces = info_dict.get(b"pieces")
        if not isinstance(raw_pieces, bytes):
            raise ValueError("Torrent missing valid 'pieces' SHA-1 data.")
        if len(raw_pieces) % 20 != 0:
            raise ValueError("Corrupt 'pieces' binary string: not a multiple of 20 bytes.")
        self.pieces = [raw_pieces[index:index + 20] for index in range(0, len(raw_pieces), 20)]

        self.files = []
        self.total_length = 0
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
                canonical_key = tuple(path_parts)
                if canonical_key in seen_paths:
                    raise ValueError("Multi-file torrent contains duplicate file paths.")
                seen_paths.add(canonical_key)
                self.files.append({
                    "length": length,
                    "path": os.path.join(*path_parts),
                    "path_parts": path_parts,
                })
                self.total_length += length
        else:
            self.is_multi_file = False
            try:
                self.total_length = int(info_dict[b"length"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Single-file torrent missing a valid 'length'.") from exc
            if self.total_length < 0:
                raise ValueError("Torrent length cannot be negative.")
            self.files.append({
                "length": self.total_length,
                "path": self.name,
                "path_parts": [self.name],
            })

        expected_piece_count = (
            (self.total_length + self.piece_length - 1) // self.piece_length
            if self.total_length > 0 else 0
        )
        if len(self.pieces) != expected_piece_count:
            raise ValueError("Torrent piece hash count does not match its declared payload size.")

    def _walk_v2_file_tree(self, node: object, prefix: list[str], out: list[dict]):
        if not isinstance(node, dict):
            raise ValueError("BEP-52 file tree entries must be dictionaries.")
        if b"" in node:
            if len(node) != 1:
                raise ValueError("A BEP-52 file node cannot also contain child entries.")
            props = node[b""]
            if not isinstance(props, dict) or b"length" not in props:
                raise ValueError("BEP-52 file properties must contain a valid length.")
            try:
                length = int(props[b"length"])
            except (TypeError, ValueError) as exc:
                raise ValueError("BEP-52 file length must be an integer.") from exc
            if length < 0:
                raise ValueError("BEP-52 file lengths cannot be negative.")
            if not prefix:
                raise ValueError("The BEP-52 file-tree root cannot itself be a file.")

            root = props.get(b"pieces root")
            if length == 0:
                if root is not None:
                    raise ValueError("An empty BEP-52 file must not declare a pieces root.")
                root_bytes = b""
            else:
                if not isinstance(root, bytes) or len(root) != SHA256_SIZE:
                    raise ValueError("Every non-empty BEP-52 file requires a 32-byte pieces root.")
                root_bytes = bytes(root)

            out.append({
                "length": length,
                "path": os.path.join(*prefix),
                "path_parts": list(prefix),
                "pieces_root": root_bytes,
                "attributes": bytes(props.get(b"attr", b"")) if isinstance(props.get(b"attr", b""), bytes) else b"",
            })
            return

        for raw_name, child in node.items():
            if not isinstance(raw_name, bytes) or not raw_name:
                raise ValueError("BEP-52 directory entries require non-empty byte-string names.")
            name = self._validate_component(self._decode_text(raw_name), "file")
            self._walk_v2_file_tree(child, prefix + [name], out)

    def _parse_v2_payload(self, raw_dict: dict, info_dict: dict):
        self.piece_length = validate_v2_piece_length(self.piece_length)
        tree = info_dict.get(b"file tree")
        if not isinstance(tree, dict) or not tree:
            raise ValueError("BEP-52 torrent missing a valid 'file tree'.")
        if b"" in tree:
            raise ValueError("The BEP-52 file-tree root cannot itself describe a file.")

        v2_files: list[dict] = []
        self._walk_v2_file_tree(tree, [], v2_files)
        if not v2_files:
            raise ValueError("BEP-52 file tree contains no files.")

        seen = set()
        for entry in v2_files:
            key = tuple(entry["path_parts"])
            if key in seen:
                raise ValueError("BEP-52 file tree contains duplicate file paths.")
            seen.add(key)

        if b"piece layers" not in raw_dict:
            raise ValueError("BEP-52 torrent missing required top-level 'piece layers' dictionary.")
        raw_layers = raw_dict[b"piece layers"]
        if not isinstance(raw_layers, dict):
            raise ValueError("BEP-52 'piece layers' must be a dictionary.")

        required_roots: set[bytes] = set()
        parsed_layers: Dict[bytes, List[bytes]] = {}
        for entry in v2_files:
            length = entry["length"]
            root = entry["pieces_root"]
            if length > self.piece_length:
                required_roots.add(root)
                layer_blob = raw_layers.get(root)
                if not isinstance(layer_blob, bytes):
                    raise ValueError("BEP-52 piece layers are missing for a file larger than one piece.")
                expected_count = expected_piece_layer_count(length, self.piece_length)
                if len(layer_blob) != expected_count * SHA256_SIZE:
                    raise ValueError("BEP-52 piece layer length does not match the file size.")
                hashes = [
                    layer_blob[offset:offset + SHA256_SIZE]
                    for offset in range(0, len(layer_blob), SHA256_SIZE)
                ]
                if not verify_piece_layer(
                    root,
                    hashes,
                    file_length=length,
                    piece_length=self.piece_length,
                ):
                    raise ValueError("BEP-52 piece layer does not reconstruct its declared pieces root.")
                parsed_layers[root] = hashes
                entry["piece_layer"] = hashes
            else:
                entry["piece_layer"] = []

        for key, blob in raw_layers.items():
            if not isinstance(key, bytes) or len(key) != SHA256_SIZE:
                raise ValueError("BEP-52 piece-layer keys must be 32-byte pieces roots.")
            if not isinstance(blob, bytes) or len(blob) % SHA256_SIZE:
                raise ValueError("BEP-52 piece-layer values must contain whole SHA-256 hashes.")
            if key not in required_roots:
                raise ValueError("BEP-52 metainfo contains an unreferenced piece layer.")

        self.v2_piece_layers = parsed_layers
        self.total_length = sum(entry["length"] for entry in v2_files)
        self.files = v2_files
        self.is_multi_file = len(v2_files) != 1 or v2_files[0]["path_parts"] != [self.name]

    def _load_and_parse(self):
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Metainfo file not found: {self.file_path}")

        with open(self.file_path, "rb") as file_handle:
            raw_bytes = file_handle.read()

        raw_dict = Bencode.decode(raw_bytes)
        if not isinstance(raw_dict, dict):
            raise ValueError("Root bencoded element must be a dictionary.")
        self._parse_trackers_and_common_root(raw_dict)

        info_dict = raw_dict.get(b"info")
        if not isinstance(info_dict, dict):
            raise ValueError("Torrent missing valid 'info' dictionary.")

        self.raw_info_bytes = self._extract_raw_info_bytes(raw_bytes)
        try:
            self.meta_version = int(info_dict.get(b"meta version", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError("Torrent contains an invalid meta version.") from exc
        if self.meta_version not in (1, V2_META_VERSION):
            raise UnsupportedTorrentVersionError(
                f"Unsupported BitTorrent meta version {self.meta_version}; SalixTorrent understands v1 and BEP-52 meta version 2."
            )

        self.is_v2 = self.meta_version == V2_META_VERSION
        self.is_v1 = isinstance(info_dict.get(b"pieces"), bytes)
        if not self.is_v1 and not self.is_v2:
            raise ValueError("Torrent does not contain v1 pieces or BEP-52 v2 metadata.")
        self.is_hybrid = self.is_v1 and self.is_v2

        self.v1_info_hash = hashlib.sha1(self.raw_info_bytes).digest() if self.is_v1 else b""
        self.v2_info_hash = hashlib.sha256(self.raw_info_bytes).digest() if self.is_v2 else b""
        self.identity = TorrentIdentity(
            v1_sha1=self.v1_info_hash or None,
            v2_sha256=self.v2_info_hash or None,
        )
        self.info_hash = self.v1_info_hash or self.identity.v2_wire_hash

        try:
            self.piece_length = int(info_dict[b"piece length"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Torrent missing a valid 'piece length'.") from exc
        if self.piece_length <= 0:
            raise ValueError("Torrent piece length must be greater than zero.")

        raw_name = self._decode_text(info_dict.get(b"name", b"unnamed_download"))
        self.name = self._validate_component(raw_name, "root")
        self.private = bool(int(info_dict.get(b"private", 0) or 0))

        # Parse v2 first so the v2 identity and piece layers are always checked.
        # Hybrid cross-format equivalence and networking are intentionally Phase 9.
        v2_files: list[dict] | None = None
        if self.is_v2:
            self._parse_v2_payload(raw_dict, info_dict)
            v2_files = list(self.files)

        if self.is_v1:
            self._parse_v1_payload(info_dict)
            if self.is_hybrid:
                # Retain v2 representation for Phase 9 while leaving the public
                # legacy ``files`` view v1-compatible for existing code paths.
                self.v2_files = v2_files or []
            else:
                self.v2_files = []
        else:
            self.v2_files = list(self.files)

        if not self.announce_list and not self.private:
            self.announce_list.extend(FALLBACK_TRACKERS)
            self.announce = self.announce_list[0]

    @property
    def num_pieces(self) -> int:
        if self.is_v1:
            return len(self.pieces)
        return sum(
            expected_piece_layer_count(entry["length"], self.piece_length)
            for entry in self.files
            if entry["length"] > 0
        )

    @property
    def hex_info_hash(self) -> str:
        """Legacy session key. v2-only callers receive the full SHA-256 hex."""
        if self.v1_info_hash:
            return self.v1_info_hash.hex()
        return self.v2_info_hash.hex()

    @property
    def canonical_info_hash(self) -> bytes:
        assert self.identity is not None
        return self.identity.canonical_bytes

    @property
    def canonical_hex_info_hash(self) -> str:
        assert self.identity is not None
        return self.identity.canonical_hex

    @property
    def protocol_label(self) -> str:
        if self.is_hybrid:
            return "BitTorrent v1/v2 Hybrid"
        if self.is_v2:
            return "BitTorrent v2 (BEP-52)"
        return "BitTorrent v1"

    @property
    def magnet_uri(self) -> str:
        """Return the currently supported v1 magnet representation.

        BEP-52 ``btmh`` generation is Phase 9. Hybrid torrents may still expose
        their v1 ``btih`` identity, but v2-only torrents intentionally fail
        explicitly instead of generating an incorrect URI.
        """
        if not self.v1_info_hash:
            raise NotImplementedError("v2-only btmh magnet generation is scheduled for Phase 9.")
        parts = [f"magnet:?xt=urn:btih:{self.v1_info_hash.hex()}"]
        if self.name:
            parts.append(f"dn={quote(self.name, safe='')}")
        for tracker in self.announce_list:
            url = str(tracker or "").strip()
            if url:
                parts.append(f"tr={quote(url, safe='')}")
        return "&".join(parts)
