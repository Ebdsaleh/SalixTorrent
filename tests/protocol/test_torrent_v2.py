import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from app.logic.bencode import Bencode
from app.logic.session import TorrentSession
from app.logic.torrent_file import TorrentFile, UnsupportedTorrentVersionError
from app.logic.torrent_v2 import (
    MERKLE_BLOCK_SIZE,
    TorrentIdentity,
    file_merkle_root,
    hash_block,
    piece_layer_hashes_from_data,
    piece_layer_depth,
    verify_block,
    verify_piece_layer,
    zero_hash,
)


class V2Fixture:
    @staticmethod
    def metainfo(name: str, data: bytes, piece_length: int = 32768, *, corrupt_layer=False):
        root = file_merkle_root(data) if data else b""
        props = {b"length": len(data)}
        if data:
            props[b"pieces root"] = root
        info = {
            b"file tree": {name.encode(): {b"": props}},
            b"meta version": 2,
            b"name": name,
            b"piece length": piece_length,
        }
        meta = {b"info": info}
        if len(data) > piece_length:
            layer = piece_layer_hashes_from_data(data, piece_length)
            blob = b"".join(layer)
            if corrupt_layer:
                blob = (bytes([blob[0] ^ 1]) + blob[1:]) if blob else blob
            meta[b"piece layers"] = {root: blob}
        else:
            meta[b"piece layers"] = {}
        return meta

    @staticmethod
    def write(path: Path, meta: dict):
        path.write_bytes(Bencode.encode(meta))
        return str(path)


class TestV2MerkleFoundation(unittest.TestCase):
    def test_zero_subtrees_are_layer_specific(self):
        self.assertEqual(zero_hash(0), b"\0" * 32)
        self.assertEqual(zero_hash(1), hashlib.sha256((b"\0" * 32) * 2).digest())
        self.assertNotEqual(zero_hash(1), b"\0" * 32)

    def test_file_root_and_piece_layer_verify(self):
        data = (b"A" * MERKLE_BLOCK_SIZE) + (b"B" * MERKLE_BLOCK_SIZE) + b"tail"
        piece_length = MERKLE_BLOCK_SIZE * 2
        root = file_merkle_root(data)
        layer = piece_layer_hashes_from_data(data, piece_length)
        self.assertEqual(len(layer), 2)
        self.assertEqual(piece_layer_depth(piece_length), 1)
        self.assertTrue(
            verify_piece_layer(root, layer, file_length=len(data), piece_length=piece_length)
        )

    def test_merkle_proof_verifies_one_block(self):
        left = b"left" * 100
        right = b"right" * 100
        left_hash = hash_block(left)
        right_hash = hash_block(right)
        root = hashlib.sha256(left_hash + right_hash).digest()
        self.assertTrue(
            verify_block(left, block_index=0, sibling_hashes=[right_hash], pieces_root=root)
        )
        self.assertFalse(
            verify_block(left + b"x", block_index=0, sibling_hashes=[right_hash], pieces_root=root)
        )


class TestV2MetainfoFoundation(unittest.TestCase):
    def test_v2_identity_uses_exact_sha256_info_bytes(self):
        data = b"x" * (70000)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v2.torrent"
            meta = V2Fixture.metainfo("payload.bin", data)
            V2Fixture.write(path, meta)
            torrent = TorrentFile(str(path))
            expected = hashlib.sha256(TorrentFile._extract_raw_info_bytes(path.read_bytes())).digest()
            self.assertTrue(torrent.is_v2)
            self.assertFalse(torrent.is_v1)
            self.assertFalse(torrent.is_hybrid)
            self.assertEqual(torrent.v2_info_hash, expected)
            self.assertEqual(torrent.canonical_info_hash, expected)
            self.assertEqual(len(torrent.hex_info_hash), 64)
            self.assertEqual(torrent.protocol_label, "BitTorrent v2 (BEP-52)")

    def test_v2_file_tree_and_piece_layers_are_exposed(self):
        data = bytes(range(251)) * 400
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tree.torrent"
            V2Fixture.write(path, V2Fixture.metainfo("payload.bin", data, 32768))
            torrent = TorrentFile(str(path))
            self.assertEqual(torrent.total_length, len(data))
            self.assertEqual(len(torrent.files), 1)
            entry = torrent.files[0]
            self.assertEqual(entry["path_parts"], ["payload.bin"])
            self.assertEqual(entry["pieces_root"], file_merkle_root(data))
            self.assertEqual(len(entry["piece_layer"]), torrent.num_pieces)
            self.assertEqual(torrent.num_pieces, (len(data) + 32767) // 32768)

    def test_v2_rejects_piece_layer_that_does_not_reconstruct_root(self):
        data = b"z" * 90000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-layer.torrent"
            V2Fixture.write(path, V2Fixture.metainfo("payload.bin", data, corrupt_layer=True))
            with self.assertRaisesRegex(ValueError, "does not reconstruct"):
                TorrentFile(str(path))

    def test_v2_rejects_unsafe_file_tree_component(self):
        info = {
            b"file tree": {b"..": {b"": {b"length": 0}}},
            b"meta version": 2,
            b"name": b"safe-root",
            b"piece length": 16384,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unsafe.torrent"
            V2Fixture.write(path, {b"info": info, b"piece layers": {}})
            with self.assertRaisesRegex(ValueError, "unsafe"):
                TorrentFile(str(path))

    def test_newer_meta_version_fails_before_generic_v2_validation(self):
        info = {b"meta version": 3, b"name": b"x", b"piece length": 16384}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "future.torrent"
            V2Fixture.write(path, {b"info": info})
            with self.assertRaisesRegex(UnsupportedTorrentVersionError, "meta version 3"):
                TorrentFile(str(path))

    def test_hybrid_identity_carries_both_hashes(self):
        data = b"H" * 1000
        meta = V2Fixture.metainfo("payload.bin", data, 16384)
        meta[b"info"][b"pieces"] = hashlib.sha1(data).digest()
        meta[b"info"][b"length"] = len(data)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hybrid.torrent"
            V2Fixture.write(path, meta)
            torrent = TorrentFile(str(path))
            self.assertTrue(torrent.is_hybrid)
            self.assertEqual(len(torrent.identity.v1_sha1), 20)
            self.assertEqual(len(torrent.identity.v2_sha256), 32)
            self.assertEqual(torrent.hex_info_hash, torrent.identity.v1_hex)


    def test_v2_requires_top_level_piece_layers_even_when_empty(self):
        data = b"small"
        meta = V2Fixture.metainfo("payload.bin", data, 16384)
        meta.pop(b"piece layers")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing-layers.torrent"
            V2Fixture.write(path, meta)
            with self.assertRaisesRegex(ValueError, "missing required top-level 'piece layers'"):
                TorrentFile(str(path))

    def test_empty_v2_file_must_not_declare_pieces_root(self):
        info = {
            b"file tree": {b"empty.bin": {b"": {b"length": 0, b"pieces root": b"x" * 32}}},
            b"meta version": 2,
            b"name": b"empty.bin",
            b"piece length": 16384,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty-root.torrent"
            V2Fixture.write(path, {b"info": info, b"piece layers": {}})
            with self.assertRaisesRegex(ValueError, "must not declare a pieces root"):
                TorrentFile(str(path))

    def test_v2_session_uses_truncated_sha256_wire_swarm(self):
        data = b"Q" * 1000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v2.torrent"
            V2Fixture.write(path, V2Fixture.metainfo("payload.bin", data, 16384))
            session = TorrentSession(
                str(path),
                download_dir=os.path.join(tmp, "downloads"),
                enable_dht=False,
                enable_pex=False,
                enable_lan_discovery=False,
            )
            self.assertEqual(session.active_generations, ("v2",))
            self.assertEqual(session.swarm_hashes["v2"], session.torrent.v2_info_hash[:20])
            self.assertEqual(len(session.torrent.v2_info_hash), 32)

    def test_v2_only_magnet_generation_uses_btmh(self):
        data = b"Q" * 1000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v2.torrent"
            V2Fixture.write(path, V2Fixture.metainfo("payload.bin", data, 16384))
            torrent = TorrentFile(str(path))
            uri = torrent.magnet_uri
            self.assertIn("xt=urn:btmh:1220" + torrent.v2_info_hash.hex(), uri)
            self.assertNotIn("urn:btih:", uri)


class TestTorrentIdentity(unittest.TestCase):
    def test_identity_tracks_canonical_and_wire_forms_without_truncating_storage(self):
        sha1 = b"1" * 20
        sha256 = b"2" * 32
        identity = TorrentIdentity(v1_sha1=sha1, v2_sha256=sha256)
        self.assertTrue(identity.is_hybrid)
        self.assertEqual(identity.canonical_bytes, sha256)
        self.assertEqual(identity.v2_wire_hash, sha256[:20])
        self.assertEqual(len(identity.canonical_hex), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
