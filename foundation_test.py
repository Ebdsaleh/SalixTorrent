# foundation_test.py

import hashlib
import unittest
from app.logic.bencode import Bencode, BencodeDecodeError
from app.logic.piece_manager import Piece, BLOCK_SIZE


class TestSalixFoundation(unittest.TestCase):

    def test_01_bencode_integers(self):
        self.assertEqual(Bencode.decode(b"i42e"), 42)
        self.assertEqual(Bencode.decode(b"i-42e"), -42)
        self.assertEqual(Bencode.decode(b"i0e"), 0)
        self.assertEqual(Bencode.encode(42), b"i42e")
        self.assertEqual(Bencode.encode(-42), b"i-42e")
        
        # Test malformed integers
        with self.assertRaises(BencodeDecodeError):
            Bencode.decode(b"i03e")  # Leading zero forbidden
        with self.assertRaises(BencodeDecodeError):
            Bencode.decode(b"i-0e")  # Negative zero forbidden

    def test_02_bencode_strings(self):
        self.assertEqual(Bencode.decode(b"4:spam"), b"spam")
        self.assertEqual(Bencode.decode(b"0:"), b"")
        self.assertEqual(Bencode.encode(b"spam"), b"4:spam")
        self.assertEqual(Bencode.encode("spam"), b"4:spam")

    def test_03_bencode_nested_structures(self):
        payload = {b"cow": b"moo", b"spam": [b"a", 42, {b"inner": 100}]}
        encoded = Bencode.encode(payload)
        decoded = Bencode.decode(encoded)
        self.assertEqual(decoded[b"cow"], b"moo")
        self.assertEqual(decoded[b"spam"][1], 42)
        self.assertEqual(decoded[b"spam"][2][b"inner"], 100)

    def test_04_piece_block_reassembly_and_hash(self):
        # Generate dummy 64 KB piece data
        test_payload = b"X" * (BLOCK_SIZE * 4)
        expected_hash = hashlib.sha1(test_payload).digest()

        piece = Piece(index=0, length=len(test_payload), expected_hash=expected_hash)
        self.assertEqual(len(piece.blocks), 4)

        # Simulate receiving 4 separate 16KB blocks
        for block in piece.blocks:
            block.data = test_payload[block.offset:block.offset + block.length]

        self.assertTrue(piece.is_all_blocks_received())
        self.assertTrue(piece.verify_hash())
        self.assertEqual(piece.get_data(), test_payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
