# app/logic/torrent_file.py

import hashlib
import os
from typing import List, Dict, Any
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
        self.piece_length: int = 0
        self.pieces: List[bytes] = []
        self.name: str = ""
        self.total_length: int = 0
        self.is_multi_file: bool = False
        self.files: List[Dict[str, Any]] = []
        self.comment: str = ""
        self.created_by: str = ""

        self._load_and_parse()

    def _load_and_parse(self):
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Metainfo file not found: {self.file_path}")

        with open(self.file_path, "rb") as f:
            raw_bytes = f.read()

        raw_dict = Bencode.decode(raw_bytes)
        if not isinstance(raw_dict, dict):
            raise ValueError("Root bencoded element must be a dictionary.")

        # Capture primary announce URL
        if b"announce" in raw_dict and raw_dict[b"announce"]:
            self.announce = raw_dict[b"announce"].decode("utf-8", errors="ignore")
            if self.announce not in self.announce_list:
                self.announce_list.append(self.announce)

        # Capture announce-list
        if b"announce-list" in raw_dict and raw_dict[b"announce-list"]:
            for tier in raw_dict[b"announce-list"]:
                if isinstance(tier, list):
                    for tracker in tier:
                        url = tracker.decode("utf-8", errors="ignore") if isinstance(tracker, bytes) else str(tracker)
                        if url and url not in self.announce_list:
                            self.announce_list.append(url)
                elif isinstance(tier, bytes):
                    url = tier.decode("utf-8", errors="ignore")
                    if url and url not in self.announce_list:
                        self.announce_list.append(url)

        # If torrent is trackerless, inject fallback public trackers
        if not self.announce_list:
            for fallback in FALLBACK_TRACKERS:
                self.announce_list.append(fallback)
            self.announce = self.announce_list[0]

        if b"comment" in raw_dict:
            self.comment = raw_dict[b"comment"].decode("utf-8", errors="ignore")
        if b"created by" in raw_dict:
            self.created_by = raw_dict[b"created by"].decode("utf-8", errors="ignore")

        # Info Dictionary Processing
        info_dict = raw_dict.get(b"info")
        if not info_dict or not isinstance(info_dict, dict):
            raise ValueError("Torrent missing valid 'info' dictionary.")

        raw_info = Bencode.encode(info_dict)
        self.info_hash = hashlib.sha1(raw_info).digest()

        self.piece_length = info_dict[b"piece length"]
        self.name = info_dict.get(b"name", b"unnamed_download").decode("utf-8", errors="ignore")

        raw_pieces = info_dict[b"pieces"]
        if len(raw_pieces) % 20 != 0:
            raise ValueError("Corrupt 'pieces' binary string: not a multiple of 20 bytes.")
        self.pieces = [raw_pieces[i:i + 20] for i in range(0, len(raw_pieces), 20)]

        if b"files" in info_dict:
            self.is_multi_file = True
            for file_entry in info_dict[b"files"]:
                length = file_entry[b"length"]
                path_parts = [p.decode("utf-8", errors="ignore") for p in file_entry[b"path"]]
                relative_path = os.path.join(*path_parts)
                self.files.append({"length": length, "path": relative_path})
                self.total_length += length
        else:
            self.is_multi_file = False
            self.total_length = info_dict[b"length"]
            self.files.append({"length": self.total_length, "path": self.name})

    @property
    def num_pieces(self) -> int:
        return len(self.pieces)

    @property
    def hex_info_hash(self) -> str:
        return self.info_hash.hex()
