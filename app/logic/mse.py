"""BitTorrent Message Stream Encryption / Protocol Encryption helpers.

This module implements the legacy MSE/PE handshake used by BitTorrent peers.
It intentionally negotiates RC4 only when MSE is used.  Plaintext fallback is
handled at the connection-policy layer by opening a *fresh* TCP connection.

MSE/PE is traffic obfuscation, not modern authenticated encryption.  It can
make basic BitTorrent protocol signatures less obvious on the wire, but it does
not hide IP addresses or prevent traffic analysis.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import struct
from dataclasses import dataclass
from typing import Optional

class _RC4Context:
    """Small stateful RC4 stream used only for BitTorrent MSE/PE.

    MSE mandates the legacy RC4 cipher and discards the first 1024 bytes of
    keystream.  Keeping this tiny implementation local avoids adding a runtime
    dependency solely for an algorithm modern crypto libraries intentionally
    classify as deprecated/decrepit.
    """

    __slots__ = ("_s", "_i", "_j")

    def __init__(self, key: bytes):
        key = bytes(key)
        if not key:
            raise ValueError("RC4 key must not be empty.")

        state = list(range(256))
        j = 0
        for i in range(256):
            j = (j + state[i] + key[i % len(key)]) & 0xFF
            state[i], state[j] = state[j], state[i]

        self._s = state
        self._i = 0
        self._j = 0

    def update(self, data: bytes) -> bytes:
        data = bytes(data)
        if not data:
            return b""

        state = self._s
        i = self._i
        j = self._j
        output = bytearray(len(data))

        for offset, value in enumerate(data):
            i = (i + 1) & 0xFF
            j = (j + state[i]) & 0xFF
            state[i], state[j] = state[j], state[i]
            key_byte = state[(state[i] + state[j]) & 0xFF]
            output[offset] = value ^ key_byte

        self._i = i
        self._j = j
        return bytes(output)


MSE_DH_KEY_BYTES = 96
MSE_MAX_PADDING = 512
MSE_VC = b"\x00" * 8
MSE_CRYPTO_PLAINTEXT = 0x01
MSE_CRYPTO_RC4 = 0x02
MSE_RC4_DROP_BYTES = 1024

# 768-bit MODP group used by BitTorrent MSE/PE.
MSE_DH_PRIME = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A63A36210000000000090563",
    16,
)
MSE_DH_GENERATOR = 2


class MSEError(ConnectionError):
    """Raised when MSE/PE negotiation fails."""


class MSEUnsupported(MSEError):
    """Raised when the peer cannot negotiate an RC4-protected MSE stream."""


def _sha1(*parts: bytes) -> bytes:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(bytes(part))
    return digest.digest()


def _xor_bytes(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def _dh_private_key() -> int:
    # The original MSE design uses a short random exponent with the 768-bit
    # public group.  160 random bits matches interoperable implementations.
    value = int.from_bytes(secrets.token_bytes(20), "big")
    return max(2, value)


def _dh_public_key(private_key: int) -> bytes:
    public = pow(MSE_DH_GENERATOR, int(private_key), MSE_DH_PRIME)
    return public.to_bytes(MSE_DH_KEY_BYTES, "big")


def _dh_shared_secret(remote_public: bytes, private_key: int) -> bytes:
    if len(remote_public) != MSE_DH_KEY_BYTES:
        raise MSEError("Invalid MSE Diffie-Hellman public-key length.")
    remote = int.from_bytes(remote_public, "big")
    if remote <= 1 or remote >= MSE_DH_PRIME - 1:
        raise MSEError("Invalid MSE Diffie-Hellman public key.")
    shared = pow(remote, int(private_key), MSE_DH_PRIME)
    if shared <= 1:
        raise MSEError("Invalid MSE Diffie-Hellman shared secret.")
    return shared.to_bytes(MSE_DH_KEY_BYTES, "big")


def _rc4_context(key: bytes):
    ctx = _RC4Context(bytes(key))
    # MSE discards the first 1024 RC4 keystream bytes.
    ctx.update(b"\x00" * MSE_RC4_DROP_BYTES)
    return ctx


def _mse_keys(shared_secret: bytes, info_hash: bytes, *, initiator: bool):
    if len(info_hash) != 20:
        raise MSEError("MSE requires a 20-byte BitTorrent v1 info hash.")
    key_a = _sha1(b"keyA", shared_secret, info_hash)
    key_b = _sha1(b"keyB", shared_secret, info_hash)
    if initiator:
        return key_a, key_b  # encrypt, decrypt
    return key_b, key_a  # encrypt, decrypt


async def _scan_for_marker(
    reader: asyncio.StreamReader,
    marker: bytes,
    *,
    max_padding: int = MSE_MAX_PADDING,
    timeout: float = 8.0,
) -> bytes:
    """Consume up to max_padding bytes plus marker and return the marker.

    MSE inserts an unknown amount of plaintext padding before a sync marker.
    Reading one byte at a time avoids over-consuming bytes that belong to the
    encrypted stream immediately following the marker.
    """
    marker = bytes(marker)
    if not marker:
        return b""

    window = bytearray()
    limit = int(max_padding) + len(marker)
    for _ in range(limit):
        try:
            chunk = await asyncio.wait_for(reader.readexactly(1), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise MSEError("Timed out while synchronising the MSE handshake.") from exc
        window += chunk
        if len(window) > len(marker):
            del window[0]
        if bytes(window) == marker:
            return marker
    raise MSEError("MSE synchronisation marker was not found.")


async def _read_encrypted_exactly(
    reader: asyncio.StreamReader,
    decryptor,
    length: int,
    *,
    timeout: float,
) -> bytes:
    try:
        raw = await asyncio.wait_for(reader.readexactly(length), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise MSEError("Timed out during encrypted MSE handshake data.") from exc
    return decryptor.update(raw)


@dataclass
class PeerWireStream:
    """Transparent plaintext-or-RC4 wrapper over asyncio streams."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    encryptor: object | None = None
    decryptor: object | None = None
    initial_plaintext: bytes = b""
    transport_security: str = "Plaintext"

    def __post_init__(self):
        self._initial = bytearray(self.initial_plaintext or b"")

    @property
    def encrypted(self) -> bool:
        return self.encryptor is not None and self.decryptor is not None

    async def readexactly(self, length: int) -> bytes:
        length = int(length)
        if length <= 0:
            return b""

        output = bytearray()
        if self._initial:
            take = min(length, len(self._initial))
            output += self._initial[:take]
            del self._initial[:take]

        remaining = length - len(output)
        if remaining:
            raw = await self.reader.readexactly(remaining)
            if self.decryptor is not None:
                raw = self.decryptor.update(raw)
            output += raw
        return bytes(output)

    def encode(self, payload: bytes) -> bytes:
        data = bytes(payload)
        if self.encryptor is None:
            return data
        return self.encryptor.update(data)

    def write(self, payload: bytes):
        self.writer.write(self.encode(payload))

    async def drain(self):
        await self.writer.drain()


async def mse_initiator_handshake(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    info_hash: bytes,
    *,
    initial_payload: bytes = b"",
    timeout: float = 8.0,
) -> PeerWireStream:
    """Negotiate an RC4-protected MSE stream as connection initiator."""
    info_hash = bytes(info_hash)
    private_key = _dh_private_key()
    public_key = _dh_public_key(private_key)
    pad_a = secrets.token_bytes(secrets.randbelow(MSE_MAX_PADDING + 1))

    writer.write(public_key + pad_a)
    await writer.drain()

    try:
        remote_public = await asyncio.wait_for(
            reader.readexactly(MSE_DH_KEY_BYTES), timeout=timeout
        )
    except asyncio.TimeoutError as exc:
        raise MSEUnsupported("Peer did not answer the MSE Diffie-Hellman greeting.") from exc

    shared = _dh_shared_secret(remote_public, private_key)
    encrypt_key, decrypt_key = _mse_keys(shared, info_hash, initiator=True)
    encryptor = _rc4_context(encrypt_key)
    decryptor = _rc4_context(decrypt_key)

    req1 = _sha1(b"req1", shared)
    req2_xor_req3 = _xor_bytes(
        _sha1(b"req2", info_hash),
        _sha1(b"req3", shared),
    )

    pad_c = b""
    initial_payload = bytes(initial_payload or b"")
    if len(initial_payload) > 0xFFFF:
        raise MSEError("MSE initial application payload is too large.")

    encrypted_offer = (
        MSE_VC
        + struct.pack(">I", MSE_CRYPTO_RC4)
        + struct.pack(">H", len(pad_c))
        + pad_c
        + struct.pack(">H", len(initial_payload))
        + initial_payload
    )
    writer.write(req1 + req2_xor_req3 + encryptor.update(encrypted_offer))
    await writer.drain()

    # PadB is plaintext but has unknown length.  The encrypted VC is the first
    # eight bytes generated by keyB after RC4-drop1024, so it can be scanned for
    # without consuming the real decryptor state.
    marker_ctx = _rc4_context(decrypt_key)
    encrypted_vc_marker = marker_ctx.update(MSE_VC)
    await _scan_for_marker(
        reader,
        encrypted_vc_marker,
        max_padding=MSE_MAX_PADDING,
        timeout=timeout,
    )

    # Advance the real decryptor over the VC bytes already consumed by the scan.
    if decryptor.update(encrypted_vc_marker) != MSE_VC:
        raise MSEError("MSE verification constant mismatch.")

    response_header = await _read_encrypted_exactly(
        reader, decryptor, 6, timeout=timeout
    )
    crypto_select, pad_d_length = struct.unpack(">IH", response_header)
    if crypto_select != MSE_CRYPTO_RC4:
        raise MSEUnsupported("Peer did not select RC4 for the MSE payload stream.")
    if pad_d_length > MSE_MAX_PADDING:
        raise MSEError("Peer supplied an invalid MSE PadD length.")
    if pad_d_length:
        await _read_encrypted_exactly(
            reader, decryptor, pad_d_length, timeout=timeout
        )

    return PeerWireStream(
        reader=reader,
        writer=writer,
        encryptor=encryptor,
        decryptor=decryptor,
        transport_security="MSE/RC4",
    )


async def mse_responder_handshake(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    info_hash: bytes,
    *,
    first_bytes: bytes = b"",
    timeout: float = 8.0,
) -> PeerWireStream:
    """Negotiate an RC4-protected MSE stream as connection responder.

    ``first_bytes`` contains bytes already consumed while distinguishing a
    plaintext BitTorrent handshake from an MSE public key.
    """
    info_hash = bytes(info_hash)
    prefix = bytes(first_bytes or b"")
    if len(prefix) > MSE_DH_KEY_BYTES:
        raise MSEError("Too many prefetched bytes for MSE responder handshake.")

    try:
        remote_public = prefix + await asyncio.wait_for(
            reader.readexactly(MSE_DH_KEY_BYTES - len(prefix)), timeout=timeout
        )
    except asyncio.TimeoutError as exc:
        raise MSEError("Timed out receiving the MSE Diffie-Hellman public key.") from exc

    private_key = _dh_private_key()
    public_key = _dh_public_key(private_key)
    pad_b = secrets.token_bytes(secrets.randbelow(MSE_MAX_PADDING + 1))
    writer.write(public_key + pad_b)
    await writer.drain()

    shared = _dh_shared_secret(remote_public, private_key)
    req1 = _sha1(b"req1", shared)
    await _scan_for_marker(reader, req1, max_padding=MSE_MAX_PADDING, timeout=timeout)

    try:
        obfuscated = await asyncio.wait_for(reader.readexactly(20), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise MSEError("Timed out receiving the MSE torrent selector.") from exc

    recovered_req2 = _xor_bytes(obfuscated, _sha1(b"req3", shared))
    if recovered_req2 != _sha1(b"req2", info_hash):
        raise MSEError("MSE initiator requested a different torrent info hash.")

    encrypt_key, decrypt_key = _mse_keys(shared, info_hash, initiator=False)
    encryptor = _rc4_context(encrypt_key)
    decryptor = _rc4_context(decrypt_key)

    offer_header = await _read_encrypted_exactly(reader, decryptor, 14, timeout=timeout)
    vc = offer_header[:8]
    crypto_provide = struct.unpack(">I", offer_header[8:12])[0]
    pad_c_length = struct.unpack(">H", offer_header[12:14])[0]
    if vc != MSE_VC:
        raise MSEError("MSE verification constant mismatch.")
    if not (crypto_provide & MSE_CRYPTO_RC4):
        raise MSEUnsupported("Initiator did not offer RC4 MSE payload protection.")
    if pad_c_length > MSE_MAX_PADDING:
        raise MSEError("Peer supplied an invalid MSE PadC length.")
    if pad_c_length:
        await _read_encrypted_exactly(
            reader, decryptor, pad_c_length, timeout=timeout
        )

    ia_length_raw = await _read_encrypted_exactly(
        reader, decryptor, 2, timeout=timeout
    )
    (ia_length,) = struct.unpack(">H", ia_length_raw)
    initial_payload = b""
    if ia_length:
        initial_payload = await _read_encrypted_exactly(
            reader, decryptor, ia_length, timeout=timeout
        )

    pad_d = b""
    response = (
        MSE_VC
        + struct.pack(">I", MSE_CRYPTO_RC4)
        + struct.pack(">H", len(pad_d))
        + pad_d
    )
    writer.write(encryptor.update(response))
    await writer.drain()

    return PeerWireStream(
        reader=reader,
        writer=writer,
        encryptor=encryptor,
        decryptor=decryptor,
        initial_plaintext=initial_payload,
        transport_security="MSE/RC4",
    )
