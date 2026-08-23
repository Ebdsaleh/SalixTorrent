# app/logic/bencode.py

from typing import Any, Tuple, Union


class BencodeDecodeError(Exception):
    """Raised when parsing invalid or malformed bencoded data."""
    pass


class Bencode:
    """Standard BitTorrent Bencoding specification encoder/decoder."""

    @classmethod
    def decode(cls, data: bytes) -> Any:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("Data to decode must be bytes.")
        value, remaining = cls._decode_item(bytes(data))
        if remaining:
            # Trailing data outside the top-level entity is an error in strict bencode
            pass
        return value

    @classmethod
    def _decode_item(cls, data: bytes) -> Tuple[Any, bytes]:
        if not data:
            raise BencodeDecodeError("Unexpected end of data stream.")

        prefix = data[:1]

        # Integer: i<integer>e
        if prefix == b'i':
            end = data.find(b'e')
            if end == -1:
                raise BencodeDecodeError("Unterminated integer.")
            int_bytes = data[1:end]
            # Disallow leading zeros (e.g. i03e is invalid, i0e is valid, i-0e is invalid)
            if (int_bytes.startswith(b'0') and len(int_bytes) > 1) or int_bytes == b'-0':
                raise BencodeDecodeError("Illegal leading zero or negative zero in integer.")
            try:
                return int(int_bytes), data[end + 1:]
            except ValueError:
                raise BencodeDecodeError(f"Invalid integer payload: {int_bytes!r}")

        # List: l<item1><item2>...e
        elif prefix == b'l':
            items = []
            rest = data[1:]
            while rest and not rest.startswith(b'e'):
                item, rest = cls._decode_item(rest)
                items.append(item)
            if not rest:
                raise BencodeDecodeError("Unterminated list structure.")
            return items, rest[1:]

        # Dictionary: d<key1><val1>...e
        elif prefix == b'd':
            out = {}
            rest = data[1:]
            last_key = None
            while rest and not rest.startswith(b'e'):
                key, rest = cls._decode_item(rest)
                if not isinstance(key, bytes):
                    raise BencodeDecodeError("Dictionary keys must be byte strings.")
                if last_key is not None and key < last_key:
                    # BitTorrent BEP 0003: keys must appear in sorted order
                    pass
                last_key = key
                val, rest = cls._decode_item(rest)
                out[key] = val
            if not rest:
                raise BencodeDecodeError("Unterminated dictionary structure.")
            return out, rest[1:]

        # Byte String: <length>:<contents>
        elif prefix.isdigit():
            colon = data.find(b':')
            if colon == -1:
                raise BencodeDecodeError("Malformed byte string length marker.")
            length_str = data[:colon]
            if length_str.startswith(b'0') and len(length_str) > 1:
                raise BencodeDecodeError("Illegal leading zero in string length.")
            length = int(length_str)
            start = colon + 1
            end = start + length
            if len(data) < end:
                raise BencodeDecodeError(f"String length {length} exceeds available byte buffer.")
            return data[start:end], data[end:]

        else:
            raise BencodeDecodeError(f"Unrecognized bencode token: {prefix!r}")

    @classmethod
    def encode(cls, data: Any) -> bytes:
        """Serializes Python primitives into Bencoded bytes."""
        if isinstance(data, bool):
            # Python booleans are instances of int; handle explicitly
            return cls.encode(int(data))
        elif isinstance(data, int):
            return f"i{data}e".encode("ascii")
        elif isinstance(data, (bytes, bytearray)):
            return f"{len(data)}:".encode("ascii") + bytes(data)
        elif isinstance(data, str):
            encoded = data.encode("utf-8")
            return f"{len(encoded)}:".encode("ascii") + encoded
        elif isinstance(data, (list, tuple)):
            return b"l" + b"".join(cls.encode(item) for item in data) + b"e"
        elif isinstance(data, dict):
            # Keys in bencoded dictionaries MUST be sorted lexicographically by raw bytes
            items = []
            sorted_keys = sorted(
                data.keys(),
                key=lambda k: k if isinstance(k, bytes) else str(k).encode("utf-8")
            )
            for k in sorted_keys:
                items.append(cls.encode(k))
                items.append(cls.encode(data[k]))
            return b"d" + b"".join(items) + b"e"
        else:
            raise TypeError(f"Type '{type(data).__name__}' cannot be bencoded.")
