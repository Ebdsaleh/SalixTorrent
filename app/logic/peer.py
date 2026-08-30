# app/logic/peer.py

from __future__ import annotations

import asyncio
import socket
import struct
import time
from typing import Dict, Iterable, List, Optional, Tuple

from app.logic.bencode import Bencode
from app.logic.mse import MSEError, PeerWireStream, mse_initiator_handshake
from app.logic.network_binding import (
    format_endpoint,
    ip_family,
    normalise_bind_address,
)


class PeerMessageID:
    CHOKE = 0
    UNCHOKE = 1
    INTERESTED = 2
    NOT_INTERESTED = 3
    HAVE = 4
    BITFIELD = 5
    REQUEST = 6
    PIECE = 7
    CANCEL = 8
    PORT = 9
    EXTENDED = 20


# BEP-10 uses bit 0x10 in reserved byte 5 to advertise the extension protocol.
# BEP-5 uses bit 0x01 in the final reserved byte to advertise DHT support.
# Extensions remain enabled because BEP-9 magnet metadata uses BEP-10 even when
# the user disables PEX. DHT can be advertised independently.
EXTENSION_RESERVED_BYTES = b"\x00\x00\x00\x00\x00\x10\x00\x01"


def build_reserved_bytes(*, enable_extensions: bool = True, enable_dht: bool = True) -> bytes:
    reserved = bytearray(8)
    if enable_extensions:
        reserved[5] |= 0x10
    if enable_dht:
        reserved[7] |= 0x01
    return bytes(reserved)
UT_PEX_EXTENSION_NAME = b"ut_pex"
UT_METADATA_EXTENSION_NAME = b"ut_metadata"
LOCAL_UT_PEX_ID = 1
LOCAL_UT_METADATA_ID = 2
METADATA_BLOCK_SIZE = 16 * 1024
PEX_SEND_INTERVAL = 60.0
PEX_MAX_PEERS_PER_MESSAGE = 50

PEER_ENCRYPTION_DISABLED = "Disabled"
PEER_ENCRYPTION_PREFER = "Prefer Encryption"
PEER_ENCRYPTION_REQUIRE = "Require Encryption"
PEER_ENCRYPTION_POLICIES = (
    PEER_ENCRYPTION_DISABLED,
    PEER_ENCRYPTION_PREFER,
    PEER_ENCRYPTION_REQUIRE,
)


def normalise_peer_encryption_policy(value: object) -> str:
    text = str(value or PEER_ENCRYPTION_PREFER).strip()
    aliases = {
        "disabled": PEER_ENCRYPTION_DISABLED,
        "off": PEER_ENCRYPTION_DISABLED,
        "plaintext": PEER_ENCRYPTION_DISABLED,
        "prefer": PEER_ENCRYPTION_PREFER,
        "prefer encryption": PEER_ENCRYPTION_PREFER,
        "preferred": PEER_ENCRYPTION_PREFER,
        "require": PEER_ENCRYPTION_REQUIRE,
        "require encryption": PEER_ENCRYPTION_REQUIRE,
        "required": PEER_ENCRYPTION_REQUIRE,
    }
    return aliases.get(text.lower(), text if text in PEER_ENCRYPTION_POLICIES else PEER_ENCRYPTION_PREFER)


_AZUREUS_CLIENTS = {
    "AZ": "Azureus / Vuze",
    "BI": "BiglyBT",
    "BT": "BitTorrent",
    "DE": "Deluge",
    "KT": "KTorrent",
    "LT": "libtorrent",
    "qB": "qBittorrent",
    "TR": "Transmission",
    "UT": "uTorrent",
    "ST": "Salix_T",
}


def identify_peer_client(peer_id: bytes) -> str:
    """Return a friendly client name for common peer-ID conventions.

    BitTorrent peer IDs are self-reported. This decoder is intentionally
    conservative: if an ID does not match a known convention, SalixTorrent
    reports ``Unknown`` instead of guessing.
    """
    if not peer_id:
        return "Unknown"

    try:
        raw = bytes(peer_id)
    except Exception:
        return "Unknown"

    # Azureus-style peer IDs look like: -XX1234-.............
    if len(raw) >= 8 and raw[0:1] == b"-" and raw[7:8] == b"-":
        try:
            code = raw[1:3].decode("ascii")
            version_raw = raw[3:7].decode("ascii")
        except UnicodeDecodeError:
            code = ""
            version_raw = ""

        name = _AZUREUS_CLIENTS.get(code)
        if name:
            if code == "ST":
                return "Salix_T 1.0"

            if version_raw and version_raw.isdigit():
                parts = list(version_raw)
                while len(parts) > 2 and parts[-1] == "0":
                    parts.pop()
                version = ".".join(parts)
                return f"{name} {version}"

            return name

    try:
        printable = raw.decode("ascii", errors="ignore").strip("\x00 -_")
    except Exception:
        printable = ""

    if printable.startswith("M") and len(printable) >= 4:
        return "Mainline BitTorrent"
    if printable.startswith("S") and "shadow" in printable.lower():
        return "Shadow"

    return "Unknown"


# ---------------------------------------------------------------------------
# BEP-10 / BEP-11 helpers
# ---------------------------------------------------------------------------


def reserved_supports_extensions(reserved: bytes) -> bool:
    try:
        raw = bytes(reserved)
    except Exception:
        return False
    return len(raw) >= 6 and bool(raw[5] & 0x10)


def reserved_supports_dht(reserved: bytes) -> bool:
    try:
        raw = bytes(reserved)
    except Exception:
        return False
    return len(raw) >= 8 and bool(raw[7] & 0x01)


def build_extended_message(extension_id: int, payload: bytes) -> bytes:
    body = bytes([int(extension_id) & 0xFF]) + bytes(payload)
    return struct.pack(">IB", 1 + len(body), PeerMessageID.EXTENDED) + body


def build_extended_handshake_payload(
    listen_port: int = 0,
    metadata_size: int = 0,
    enable_pex: bool = True,
) -> bytes:
    extension_map = {UT_METADATA_EXTENSION_NAME: LOCAL_UT_METADATA_ID}
    if enable_pex:
        extension_map[UT_PEX_EXTENSION_NAME] = LOCAL_UT_PEX_ID
    payload = {
        b"m": extension_map,
        b"v": b"Salix_T 1.0",
        b"reqq": 64,
    }
    try:
        port = int(listen_port or 0)
    except (TypeError, ValueError):
        port = 0
    if 0 < port <= 65535:
        payload[b"p"] = port

    try:
        size = int(metadata_size or 0)
    except (TypeError, ValueError):
        size = 0
    if size > 0:
        payload[b"metadata_size"] = size

    return Bencode.encode(payload)


def parse_extended_handshake(payload: bytes) -> dict:
    try:
        decoded = Bencode.decode(bytes(payload))
    except Exception:
        return {}
    if not isinstance(decoded, dict):
        return {}
    return decoded


def parse_metadata_payload(payload: bytes) -> dict:
    """Split a BEP-9 metadata message into its bencoded header and raw data."""
    try:
        header, remaining = Bencode._decode_item(bytes(payload))
    except Exception:
        return {"header": {}, "data": b""}
    if not isinstance(header, dict):
        return {"header": {}, "data": b""}
    return {"header": header, "data": bytes(remaining)}


def _compact_ipv4(endpoint: Tuple[str, int]) -> bytes:
    ip, port = endpoint
    try:
        packed_ip = socket.inet_pton(socket.AF_INET, str(ip))
        packed_port = struct.pack(">H", int(port))
    except (OSError, TypeError, ValueError, struct.error):
        return b""
    if int(port) <= 0 or int(port) > 65535:
        return b""
    return packed_ip + packed_port


def _compact_ipv6(endpoint: Tuple[str, int]) -> bytes:
    ip, port = endpoint
    try:
        packed_ip = socket.inet_pton(socket.AF_INET6, str(ip))
        packed_port = struct.pack(">H", int(port))
    except (OSError, TypeError, ValueError, struct.error):
        return b""
    if int(port) <= 0 or int(port) > 65535:
        return b""
    return packed_ip + packed_port


def encode_pex_payload(endpoints: Iterable[Tuple[str, int]]) -> bytes:
    """Encode BEP-11 PEX endpoints for both address families.

    IPv4 peers use ``added`` (6-byte compact endpoints) while IPv6 peers use
    ``added6`` (18-byte endpoints). The total advertised set remains bounded
    to avoid oversized extension messages.
    """
    compact_v4: List[bytes] = []
    compact_v6: List[bytes] = []
    seen = set()
    accepted = 0
    for endpoint in endpoints:
        if accepted >= PEX_MAX_PEERS_PER_MESSAGE:
            break
        try:
            normalized = (str(endpoint[0]), int(endpoint[1]))
        except (TypeError, ValueError, IndexError):
            continue
        if normalized in seen:
            continue
        family = ip_family(normalized[0])
        raw = (
            _compact_ipv6(normalized)
            if family == socket.AF_INET6
            else _compact_ipv4(normalized)
            if family == socket.AF_INET
            else b""
        )
        if not raw:
            continue
        seen.add(normalized)
        accepted += 1
        if family == socket.AF_INET6:
            compact_v6.append(raw)
        else:
            compact_v4.append(raw)

    payload = {
        b"added": b"".join(compact_v4),
        b"added.f": b"\x00" * len(compact_v4),
        b"added6": b"".join(compact_v6),
        b"added6.f": b"\x00" * len(compact_v6),
        b"dropped": b"",
        b"dropped6": b"",
    }
    return Bencode.encode(payload)


def _parse_compact_ipv4(raw: object) -> List[Tuple[str, int]]:
    if not isinstance(raw, (bytes, bytearray)):
        return []
    data = bytes(raw)
    peers: List[Tuple[str, int]] = []
    for offset in range(0, len(data) - 5, 6):
        chunk = data[offset:offset + 6]
        try:
            ip = socket.inet_ntoa(chunk[:4])
            port = struct.unpack(">H", chunk[4:])[0]
        except (OSError, struct.error):
            continue
        if port:
            peers.append((ip, port))
    return peers


def _parse_compact_ipv6(raw: object) -> List[Tuple[str, int]]:
    if not isinstance(raw, (bytes, bytearray)):
        return []
    data = bytes(raw)
    peers: List[Tuple[str, int]] = []
    for offset in range(0, len(data) - 17, 18):
        chunk = data[offset:offset + 18]
        try:
            ip = socket.inet_ntop(socket.AF_INET6, chunk[:16])
            port = struct.unpack(">H", chunk[16:18])[0]
        except (OSError, struct.error):
            continue
        if port:
            peers.append((ip, port))
    return peers


def parse_pex_payload(payload: bytes) -> dict:
    try:
        decoded = Bencode.decode(bytes(payload))
    except Exception:
        return {"added": [], "dropped": []}
    if not isinstance(decoded, dict):
        return {"added": [], "dropped": []}

    added = _parse_compact_ipv4(decoded.get(b"added"))
    added.extend(_parse_compact_ipv6(decoded.get(b"added6")))
    dropped = _parse_compact_ipv4(decoded.get(b"dropped"))
    dropped.extend(_parse_compact_ipv6(decoded.get(b"dropped6")))

    return {
        "added": added,
        "dropped": dropped,
    }


class PeerConnection:
    """Manages an asynchronous TCP socket connection to one BitTorrent peer."""

    def __init__(
        self,
        ip: str,
        port: int,
        info_hash: bytes,
        peer_id: bytes,
        source: str = "Unknown",
        direction: str = "Outgoing",
        advertise_dht: bool = True,
        enable_pex: bool = True,
        encryption_policy: str = PEER_ENCRYPTION_PREFER,
        bind_address: str = "",
    ):
        self.ip = ip
        self.port = port
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.remote_peer_id: bytes = b""

        self.source = source
        self.direction = direction
        self.advertise_dht = bool(advertise_dht)
        self.enable_pex = bool(enable_pex)
        self.encryption_policy = normalise_peer_encryption_policy(encryption_policy)
        self.bind_address = normalise_bind_address(bind_address)

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.stream: Optional[PeerWireStream] = None
        self.transport_security: str = "Plaintext"
        self.encryption_attempted: bool = False
        self.plaintext_fallback_used: bool = False

        # Peer protocol state.
        self.am_choking: bool = True
        self.am_interested: bool = False
        self.peer_choking: bool = True
        self.peer_interested: bool = False
        self.bitfield: bytearray = bytearray()
        self.is_connected: bool = False

        # BEP-10 / BEP-11 extension state.
        self.remote_reserved: bytes = b"\x00" * 8
        self.supports_extensions: bool = False
        self.supports_dht: bool = False
        self.remote_extensions: Dict[bytes, int] = {}
        self.remote_client_version: str = ""
        self.remote_listen_port: int = 0
        self.extended_handshake_sent: bool = False
        self.extended_handshake_received: bool = False
        self.pex_messages_received: int = 0
        self.pex_messages_sent: int = 0
        self.last_pex_sent_at: float = 0.0
        self.last_pex_received_at: float = 0.0
        self.remote_metadata_size: int = 0

        # Per-peer telemetry used by the Peers view.
        self.connected_at: float = 0.0
        self.last_activity_at: float = time.monotonic()
        self.downloaded_bytes: int = 0
        self.uploaded_bytes: int = 0
        self.download_speed_kbps: float = 0.0
        self.upload_speed_kbps: float = 0.0
        self._last_sample_downloaded: int = 0
        self._last_sample_uploaded: int = 0

    @property
    def client_name(self) -> str:
        return identify_peer_client(self.remote_peer_id)

    @property
    def pex_supported(self) -> bool:
        if not self.enable_pex:
            return False
        try:
            return int(self.remote_extensions.get(UT_PEX_EXTENSION_NAME, 0)) > 0
        except (TypeError, ValueError):
            return False

    @property
    def metadata_supported(self) -> bool:
        try:
            return int(self.remote_extensions.get(UT_METADATA_EXTENSION_NAME, 0)) > 0
        except (TypeError, ValueError):
            return False

    def _mark_activity(self):
        self.last_activity_at = time.monotonic()

    async def _write_and_drain(self, payload: bytes) -> bool:
        """Write one peer-wire frame without leaking normal disconnects.

        Public BitTorrent peers routinely disappear between handshake and the
        first protocol message.  On Windows that commonly arrives as
        ``ConnectionResetError(10054)`` from ``StreamWriter.drain()``.  A peer
        disconnect is ordinary swarm churn, not an application error, so mark
        the connection closed and let the worker retire quietly.
        """
        if not self.is_connected or not self.writer:
            return False

        try:
            if self.stream is not None:
                self.stream.write(bytes(payload))
                await self.stream.drain()
            else:
                self.writer.write(bytes(payload))
                await self.writer.drain()
            self._mark_activity()
            return True
        except asyncio.CancelledError:
            raise
        except (ConnectionError, OSError):
            await self.close()
            return False
        except Exception:
            # StreamWriter implementations can surface transport failures as
            # RuntimeError or another transport-specific exception.  Treat the
            # failed peer as disconnected rather than leaking an unobserved task
            # exception into the console.
            await self.close()
            return False

    def _build_handshake(self) -> bytes:
        pstr = b"BitTorrent protocol"
        return (
            bytes([len(pstr)])
            + pstr
            + build_reserved_bytes(enable_extensions=True, enable_dht=self.advertise_dht)
            + self.info_hash
            + self.peer_id
        )

    async def _open_tcp(self, timeout: float):
        kwargs = {}
        remote_family = ip_family(self.ip)
        bind_family = ip_family(self.bind_address) if self.bind_address else socket.AF_UNSPEC

        # A selected interface is a hard routing choice. Do not silently escape
        # through the other address family if the remote endpoint is incompatible.
        if self.bind_address:
            kwargs["local_addr"] = (self.bind_address, 0)
            kwargs["family"] = bind_family
        elif remote_family in {socket.AF_INET, socket.AF_INET6}:
            kwargs["family"] = remote_family

        return await asyncio.wait_for(
            asyncio.open_connection(self.ip, self.port, **kwargs),
            timeout=timeout,
        )

    async def _finish_peer_handshake(self, response: bytes) -> bool:
        if len(response) != 68 or response[:20] != b"\x13BitTorrent protocol":
            return False
        if response[28:48] != self.info_hash:
            return False

        self.remote_reserved = bytes(response[20:28])
        self.supports_extensions = reserved_supports_extensions(self.remote_reserved)
        self.supports_dht = reserved_supports_dht(self.remote_reserved)
        self.remote_peer_id = bytes(response[48:68])
        self.is_connected = True
        self.connected_at = time.monotonic()
        self._mark_activity()
        return True

    async def _connect_plaintext(self, timeout: float) -> bool:
        self.reader, self.writer = await self._open_tcp(timeout)
        self.stream = PeerWireStream(
            reader=self.reader,
            writer=self.writer,
            transport_security="Plaintext",
        )
        handshake = self._build_handshake()
        self.writer.write(handshake)
        await self.writer.drain()
        response = await asyncio.wait_for(self.reader.readexactly(68), timeout=timeout)
        if not await self._finish_peer_handshake(response):
            await self.close()
            return False
        self.transport_security = "Plaintext"
        return True

    async def _connect_mse(self, timeout: float) -> bool:
        self.encryption_attempted = True
        self.reader, self.writer = await self._open_tcp(timeout)
        handshake = self._build_handshake()
        self.stream = await mse_initiator_handshake(
            self.reader,
            self.writer,
            self.info_hash,
            initial_payload=handshake,
            timeout=timeout,
        )
        response = await asyncio.wait_for(self.stream.readexactly(68), timeout=timeout)
        if not await self._finish_peer_handshake(response):
            await self.close()
            return False
        self.transport_security = self.stream.transport_security
        return True

    async def connect(self, timeout: float = 8.0) -> bool:
        """Establish TCP and negotiate the configured peer transport policy.

        Prefer Encryption makes one MSE/RC4 attempt first.  If that negotiation
        fails, the socket is discarded and a completely fresh plaintext TCP
        connection is opened.  Require Encryption never falls back.
        """
        policy = normalise_peer_encryption_policy(self.encryption_policy)
        self.encryption_policy = policy
        self.plaintext_fallback_used = False

        if policy == PEER_ENCRYPTION_DISABLED:
            try:
                return await self._connect_plaintext(timeout)
            except asyncio.CancelledError:
                raise
            except Exception:
                await self.close()
                return False

        try:
            if await self._connect_mse(timeout):
                return True
        except asyncio.CancelledError:
            raise
        except (MSEError, ConnectionError, OSError, asyncio.TimeoutError):
            pass
        except Exception:
            pass

        await self.close()
        if policy == PEER_ENCRYPTION_REQUIRE:
            return False

        self.plaintext_fallback_used = True
        try:
            return await self._connect_plaintext(timeout)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.close()
            return False

    async def send_interested(self) -> bool:
        if not self.is_connected or not self.writer:
            return False
        sent = await self._write_and_drain(
            struct.pack(">IB", 1, PeerMessageID.INTERESTED)
        )
        if sent:
            self.am_interested = True
        return sent

    async def send_request(
        self,
        piece_index: int,
        block_offset: int,
        length: int = 16384,
    ) -> bool:
        if not self.is_connected or not self.writer or self.peer_choking:
            return False
        return await self._write_and_drain(
            struct.pack(
                ">IBIII",
                13,
                PeerMessageID.REQUEST,
                piece_index,
                block_offset,
                length,
            )
        )

    async def send_cancel(
        self,
        piece_index: int,
        block_offset: int,
        length: int = 16384,
    ) -> bool:
        """Cancel one previously issued peer-wire REQUEST (message ID 8)."""
        if not self.is_connected or not self.writer:
            return False
        try:
            piece_index = int(piece_index)
            block_offset = int(block_offset)
            length = int(length)
        except (TypeError, ValueError):
            return False
        if piece_index < 0 or block_offset < 0 or length <= 0:
            return False
        return await self._write_and_drain(
            struct.pack(
                ">IBIII",
                13,
                PeerMessageID.CANCEL,
                piece_index,
                block_offset,
                length,
            )
        )

    async def send_bitfield(self, bitfield: bytes) -> bool:
        if not self.is_connected or not self.writer:
            return False
        payload = bytes(bitfield)
        return await self._write_and_drain(
            struct.pack(">IB", 1 + len(payload), PeerMessageID.BITFIELD) + payload
        )

    async def send_unchoke(self) -> bool:
        if not self.is_connected or not self.writer:
            return False
        sent = await self._write_and_drain(
            struct.pack(">IB", 1, PeerMessageID.UNCHOKE)
        )
        if sent:
            self.am_choking = False
        return sent

    async def send_have(self, piece_index: int) -> bool:
        if not self.is_connected or not self.writer:
            return False
        try:
            piece_index = int(piece_index)
        except (TypeError, ValueError):
            return False
        if piece_index < 0:
            return False
        return await self._write_and_drain(
            struct.pack(">IBI", 5, PeerMessageID.HAVE, piece_index)
        )

    async def send_piece(
        self,
        piece_index: int,
        block_offset: int,
        data: bytes,
    ) -> bool:
        if not self.is_connected or not self.writer:
            return False
        block_data = bytes(data)
        payload = struct.pack(">II", piece_index, block_offset) + block_data
        sent = await self._write_and_drain(
            struct.pack(">IB", 1 + len(payload), PeerMessageID.PIECE) + payload
        )
        if sent:
            self.uploaded_bytes += len(block_data)
        return sent

    async def send_port(self, dht_port: int) -> bool:
        if not self.is_connected or not self.writer or not self.supports_dht:
            return False
        try:
            port = int(dht_port or 0)
        except (TypeError, ValueError):
            return False
        if port <= 0 or port > 65535:
            return False
        return await self._write_and_drain(
            struct.pack(">IBH", 3, PeerMessageID.PORT, port)
        )

    async def send_extended_handshake(
        self,
        listen_port: int = 0,
        metadata_size: int = 0,
    ) -> bool:
        if (
            not self.is_connected
            or not self.writer
            or not self.supports_extensions
        ):
            return False
        sent = await self._write_and_drain(
            build_extended_message(
                0,
                build_extended_handshake_payload(
                    listen_port=listen_port,
                    metadata_size=metadata_size,
                    enable_pex=self.enable_pex,
                ),
            )
        )
        if sent:
            self.extended_handshake_sent = True
        return sent

    async def send_metadata_request(self, piece_index: int) -> bool:
        if not self.is_connected or not self.writer or not self.metadata_supported:
            return False
        try:
            remote_id = int(self.remote_extensions.get(UT_METADATA_EXTENSION_NAME, 0))
            piece = int(piece_index)
        except (TypeError, ValueError):
            return False
        if remote_id <= 0 or remote_id > 255 or piece < 0:
            return False
        payload = Bencode.encode({b"msg_type": 0, b"piece": piece})
        return await self._write_and_drain(build_extended_message(remote_id, payload))

    async def send_metadata_piece(
        self,
        piece_index: int,
        metadata: bytes,
    ) -> bool:
        if not self.is_connected or not self.writer or not self.metadata_supported:
            return False
        try:
            remote_id = int(self.remote_extensions.get(UT_METADATA_EXTENSION_NAME, 0))
            piece = int(piece_index)
        except (TypeError, ValueError):
            return False
        if remote_id <= 0 or remote_id > 255 or piece < 0:
            return False

        raw_metadata = bytes(metadata)
        start = piece * METADATA_BLOCK_SIZE
        if start >= len(raw_metadata):
            return await self.send_metadata_reject(piece)
        block = raw_metadata[start:start + METADATA_BLOCK_SIZE]
        header = Bencode.encode(
            {b"msg_type": 1, b"piece": piece, b"total_size": len(raw_metadata)}
        )
        return await self._write_and_drain(
            build_extended_message(remote_id, header + block)
        )

    async def send_metadata_reject(self, piece_index: int) -> bool:
        if not self.is_connected or not self.writer or not self.metadata_supported:
            return False
        try:
            remote_id = int(self.remote_extensions.get(UT_METADATA_EXTENSION_NAME, 0))
            piece = int(piece_index)
        except (TypeError, ValueError):
            return False
        if remote_id <= 0 or remote_id > 255 or piece < 0:
            return False
        payload = Bencode.encode({b"msg_type": 2, b"piece": piece})
        return await self._write_and_drain(build_extended_message(remote_id, payload))

    async def send_pex(self, endpoints: Iterable[Tuple[str, int]]) -> bool:
        if not self.is_connected or not self.writer or not self.pex_supported:
            return False
        try:
            remote_id = int(self.remote_extensions.get(UT_PEX_EXTENSION_NAME, 0))
        except (TypeError, ValueError):
            return False
        if remote_id <= 0 or remote_id > 255:
            return False

        payload = encode_pex_payload(endpoints)
        sent = await self._write_and_drain(
            build_extended_message(remote_id, payload)
        )
        if sent:
            self.pex_messages_sent += 1
            self.last_pex_sent_at = time.monotonic()
        return sent

    def _handle_extended_message(self, body: bytes) -> tuple:
        if not body:
            return ("UNKNOWN", body)

        extension_id = int(body[0])
        extension_payload = bytes(body[1:])

        if extension_id == 0:
            handshake = parse_extended_handshake(extension_payload)
            mapping = handshake.get(b"m")
            if isinstance(mapping, dict):
                extensions: Dict[bytes, int] = {}
                for name, value in mapping.items():
                    if not isinstance(name, bytes):
                        continue
                    try:
                        extension_number = int(value)
                    except (TypeError, ValueError):
                        continue
                    if 0 <= extension_number <= 255:
                        extensions[name] = extension_number
                self.remote_extensions = extensions

            version = handshake.get(b"v")
            if isinstance(version, bytes):
                self.remote_client_version = version.decode("utf-8", errors="replace")
            elif version is not None:
                self.remote_client_version = str(version)

            try:
                listen_port = int(handshake.get(b"p", 0) or 0)
            except (TypeError, ValueError):
                listen_port = 0
            self.remote_listen_port = listen_port if 0 < listen_port <= 65535 else 0
            try:
                metadata_size = int(handshake.get(b"metadata_size", 0) or 0)
            except (TypeError, ValueError):
                metadata_size = 0
            self.remote_metadata_size = max(0, metadata_size)
            self.extended_handshake_received = True
            return ("EXTENDED_HANDSHAKE", handshake)

        # Incoming extension IDs are interpreted using the mapping *we*
        # advertised. SalixTorrent advertises ut_pex as local extension ID 1
        # and ut_metadata as local extension ID 2.
        if extension_id == LOCAL_UT_PEX_ID:
            parsed = parse_pex_payload(extension_payload)
            self.pex_messages_received += 1
            self.last_pex_received_at = time.monotonic()
            return ("PEX", parsed)

        if extension_id == LOCAL_UT_METADATA_ID:
            return ("METADATA", parse_metadata_payload(extension_payload))

        return ("EXTENDED", (extension_id, extension_payload))

    async def _readexactly(self, length: int) -> bytes:
        if self.stream is not None:
            return await self.stream.readexactly(length)
        if self.reader is None:
            raise asyncio.IncompleteReadError(b"", int(length))
        return await self.reader.readexactly(length)

    async def read_message(self) -> Optional[tuple]:
        """Read and parse the next framed BitTorrent peer message."""
        if not self.is_connected or not self.reader:
            return None

        try:
            length_bytes = await self._readexactly(4)
            (length,) = struct.unpack(">I", length_bytes)

            if length == 0:
                self._mark_activity()
                return ("KEEP_ALIVE", None)

            # Protect the client from a nonsensical peer-wire allocation. Large
            # piece messages are never needed because SalixTorrent requests at
            # most 16 KiB blocks.
            if length > 2 * 1024 * 1024:
                await self.close()
                return None

            payload = await self._readexactly(length)
            msg_id = payload[0]
            body = payload[1:]
            self._mark_activity()

            if msg_id == PeerMessageID.CHOKE:
                self.peer_choking = True
                return ("CHOKE", None)
            if msg_id == PeerMessageID.UNCHOKE:
                self.peer_choking = False
                return ("UNCHOKE", None)
            if msg_id == PeerMessageID.INTERESTED:
                self.peer_interested = True
                return ("INTERESTED", None)
            if msg_id == PeerMessageID.NOT_INTERESTED:
                self.peer_interested = False
                return ("NOT_INTERESTED", None)
            if msg_id == PeerMessageID.HAVE:
                if len(body) != 4:
                    return ("UNKNOWN", body)
                (piece_idx,) = struct.unpack(">I", body)
                return ("HAVE", piece_idx)
            if msg_id == PeerMessageID.BITFIELD:
                self.bitfield = bytearray(body)
                return ("BITFIELD", self.bitfield)
            if msg_id == PeerMessageID.REQUEST:
                if len(body) != 12:
                    return ("UNKNOWN", body)
                index, begin, req_length = struct.unpack(">III", body)
                return ("REQUEST", (index, begin, req_length))
            if msg_id == PeerMessageID.CANCEL:
                if len(body) != 12:
                    return ("UNKNOWN", body)
                index, begin, req_length = struct.unpack(">III", body)
                return ("CANCEL", (index, begin, req_length))
            if msg_id == PeerMessageID.PIECE:
                if len(body) < 8:
                    return ("UNKNOWN", body)
                index, begin = struct.unpack(">II", body[:8])
                block_data = body[8:]
                self.downloaded_bytes += len(block_data)
                return ("PIECE", (index, begin, block_data))
            if msg_id == PeerMessageID.PORT:
                if len(body) != 2:
                    return ("UNKNOWN", body)
                (dht_port,) = struct.unpack(">H", body)
                return ("PORT", dht_port)
            if msg_id == PeerMessageID.EXTENDED:
                return self._handle_extended_message(body)

            return ("UNKNOWN", body)

        except Exception:
            await self.close()
            return None

    async def close(self):
        self.is_connected = False
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
        self.reader = None
        self.writer = None
        self.stream = None




