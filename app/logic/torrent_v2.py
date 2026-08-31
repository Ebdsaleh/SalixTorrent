"""BitTorrent v2 (BEP-52) identity, file-tree and Merkle primitives.

Phase 8 deliberately keeps this module presentation- and peer-wire-neutral.
It validates metainfo foundations that Phase 9 can consume without changing
or weakening the existing v1 engine.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Optional, Sequence

V2_META_VERSION = 2
MERKLE_BLOCK_SIZE = 16 * 1024
SHA256_SIZE = 32


@dataclass(frozen=True)
class TorrentIdentity:
    """Version-aware torrent identity without assuming a 20-byte hash."""

    v1_sha1: Optional[bytes] = None
    v2_sha256: Optional[bytes] = None

    def __post_init__(self):
        if self.v1_sha1 is not None and len(self.v1_sha1) != 20:
            raise ValueError("A BitTorrent v1 SHA-1 identity must be 20 bytes.")
        if self.v2_sha256 is not None and len(self.v2_sha256) != SHA256_SIZE:
            raise ValueError("A BitTorrent v2 SHA-256 identity must be 32 bytes.")
        if self.v1_sha1 is None and self.v2_sha256 is None:
            raise ValueError("At least one torrent identity must be present.")

    @property
    def is_v1(self) -> bool:
        return self.v1_sha1 is not None

    @property
    def is_v2(self) -> bool:
        return self.v2_sha256 is not None

    @property
    def is_hybrid(self) -> bool:
        return self.is_v1 and self.is_v2

    @property
    def canonical_bytes(self) -> bytes:
        return self.v2_sha256 if self.v2_sha256 is not None else self.v1_sha1  # type: ignore[return-value]

    @property
    def canonical_hex(self) -> str:
        return self.canonical_bytes.hex()

    @property
    def v1_hex(self) -> str:
        return self.v1_sha1.hex() if self.v1_sha1 is not None else ""

    @property
    def v2_hex(self) -> str:
        return self.v2_sha256.hex() if self.v2_sha256 is not None else ""

    @property
    def v2_wire_hash(self) -> bytes:
        """BEP-52 tracker/peer handshake form: first 20 bytes of SHA-256."""
        if self.v2_sha256 is None:
            return b""
        return self.v2_sha256[:20]


def validate_piece_length(piece_length: int) -> int:
    try:
        value = int(piece_length)
    except (TypeError, ValueError) as exc:
        raise ValueError("BEP-52 piece length must be an integer.") from exc
    if value < MERKLE_BLOCK_SIZE or value & (value - 1):
        raise ValueError("BEP-52 piece length must be a power of two and at least 16 KiB.")
    return value


def piece_layer_depth(piece_length: int) -> int:
    value = validate_piece_length(piece_length)
    return int(math.log2(value // MERKLE_BLOCK_SIZE))


@lru_cache(maxsize=64)
def zero_hash(layer: int) -> bytes:
    """Return the BEP-52 all-padding subtree hash for ``layer``.

    Layer zero is the special 32-byte all-zero leaf specified by BEP-52.
    Higher layers are normal SHA-256 parent hashes of two lower zero subtrees.
    """
    layer = int(layer)
    if layer < 0:
        raise ValueError("Merkle layer cannot be negative.")
    if layer == 0:
        return b"\x00" * SHA256_SIZE
    child = zero_hash(layer - 1)
    return hashlib.sha256(child + child).digest()


def hash_block(data: bytes) -> bytes:
    return hashlib.sha256(bytes(data)).digest()


def _next_power_of_two(value: int) -> int:
    if value <= 1:
        return 1
    return 1 << (value - 1).bit_length()


def merkle_root_from_hashes(
    hashes: Sequence[bytes],
    *,
    base_layer: int = 0,
    logical_count: Optional[int] = None,
) -> bytes:
    """Reduce hashes from one Merkle layer to a single BEP-52 root.

    ``logical_count`` is the number of real hashes represented. Missing hashes
    needed to balance the tree are filled with the correct zero-subtree hash
    for ``base_layer`` rather than raw zeros at every level.
    """
    base_layer = int(base_layer)
    if base_layer < 0:
        raise ValueError("Merkle base layer cannot be negative.")
    values = [bytes(item) for item in hashes]
    if any(len(item) != SHA256_SIZE for item in values):
        raise ValueError("Every BEP-52 Merkle hash must be exactly 32 bytes.")

    count = len(values) if logical_count is None else int(logical_count)
    if count < 0 or count != len(values):
        raise ValueError("logical_count must match the number of supplied real hashes.")
    if count == 0:
        return zero_hash(base_layer)

    target = _next_power_of_two(count)
    values.extend([zero_hash(base_layer)] * (target - count))

    layer = base_layer
    while len(values) > 1:
        values = [
            hashlib.sha256(values[index] + values[index + 1]).digest()
            for index in range(0, len(values), 2)
        ]
        layer += 1
    return values[0]


def file_merkle_root(data: bytes) -> bytes:
    """Calculate a BEP-52 file root from 16 KiB leaf blocks."""
    payload = bytes(data)
    if not payload:
        # Empty files do not carry a pieces-root in BEP-52. Returning the base
        # zero hash is useful for pure Merkle tests but callers should omit it
        # from metainfo for a zero-length file.
        return zero_hash(0)
    leaves = [
        hash_block(payload[offset:offset + MERKLE_BLOCK_SIZE])
        for offset in range(0, len(payload), MERKLE_BLOCK_SIZE)
    ]
    return merkle_root_from_hashes(leaves, base_layer=0)


def piece_layer_hashes_from_data(data: bytes, piece_length: int) -> list[bytes]:
    """Return the BEP-52 piece layer for one file.

    Only hashes covering real file data are returned. Balancing hashes beyond
    EOF are intentionally omitted, matching the metainfo representation.
    """
    piece_length = validate_piece_length(piece_length)
    payload = bytes(data)
    if not payload:
        return []

    leaves = [
        hash_block(payload[offset:offset + MERKLE_BLOCK_SIZE])
        for offset in range(0, len(payload), MERKLE_BLOCK_SIZE)
    ]
    depth = piece_layer_depth(piece_length)
    if depth == 0:
        return leaves

    leaves_per_piece = 1 << depth
    out: list[bytes] = []
    for start in range(0, len(leaves), leaves_per_piece):
        group = leaves[start:start + leaves_per_piece]
        # Each piece-layer hash represents a full piece-sized subtree. The
        # final short piece therefore needs zero leaves *inside that subtree*
        # before it is reduced to the piece layer.
        if len(group) < leaves_per_piece:
            group = group + [zero_hash(0)] * (leaves_per_piece - len(group))
        out.append(merkle_root_from_hashes(group, base_layer=0))
    return out


def expected_piece_layer_count(file_length: int, piece_length: int) -> int:
    piece_length = validate_piece_length(piece_length)
    length = int(file_length)
    if length < 0:
        raise ValueError("BEP-52 file length cannot be negative.")
    if length == 0:
        return 0
    return (length + piece_length - 1) // piece_length


def verify_piece_layer(
    pieces_root: bytes,
    layer_hashes: Sequence[bytes],
    *,
    file_length: int,
    piece_length: int,
) -> bool:
    root = bytes(pieces_root)
    if len(root) != SHA256_SIZE:
        return False
    count = expected_piece_layer_count(file_length, piece_length)
    if len(layer_hashes) != count:
        return False
    if count == 0:
        return False
    try:
        calculated = merkle_root_from_hashes(
            layer_hashes,
            base_layer=piece_layer_depth(piece_length),
        )
    except ValueError:
        return False
    return calculated == root


def verify_hash_path(
    subject_hash: bytes,
    *,
    index: int,
    sibling_hashes: Iterable[bytes],
    expected_root: bytes,
) -> bool:
    """Verify one SHA-256 Merkle hash against an ordered sibling proof."""
    current = bytes(subject_hash)
    root = bytes(expected_root)
    if len(current) != SHA256_SIZE or len(root) != SHA256_SIZE:
        return False
    try:
        position = int(index)
    except (TypeError, ValueError):
        return False
    if position < 0:
        return False

    for sibling in sibling_hashes:
        sibling = bytes(sibling)
        if len(sibling) != SHA256_SIZE:
            return False
        if position & 1:
            current = hashlib.sha256(sibling + current).digest()
        else:
            current = hashlib.sha256(current + sibling).digest()
        position >>= 1
    return current == root


def verify_block(
    block_data: bytes,
    *,
    block_index: int,
    sibling_hashes: Iterable[bytes],
    pieces_root: bytes,
) -> bool:
    return verify_hash_path(
        hash_block(block_data),
        index=block_index,
        sibling_hashes=sibling_hashes,
        expected_root=pieces_root,
    )
