# app/logic/peer.py

import asyncio
import struct
import time
from typing import Optional


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
    """Return a friendly client name for common Azureus-style peer IDs.

    BitTorrent does not require clients to identify themselves in a human-readable
    way, so this is intentionally best-effort. Unknown IDs remain perfectly
    valid peers and are reported as ``Unknown`` rather than rejected.
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

            # Most Azureus-style clients encode four compact version digits.
            # Keep the presentation conservative rather than pretending every
            # client uses exactly the same version convention.
            if version_raw and version_raw.isdigit():
                parts = list(version_raw)
                while len(parts) > 2 and parts[-1] == "0":
                    parts.pop()
                version = ".".join(parts)
                return f"{name} {version}"

            return name

    # Some old/mainline clients use textual prefixes instead of Azureus style.
    try:
        printable = raw.decode("ascii", errors="ignore").strip("\x00 -_")
    except Exception:
        printable = ""

    if printable.startswith("M") and len(printable) >= 4:
        return "Mainline BitTorrent"
    if printable.startswith("S") and "shadow" in printable.lower():
        return "Shadow"

    return "Unknown"


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
    ):
        self.ip = ip
        self.port = port
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.remote_peer_id: bytes = b""

        self.source = source
        self.direction = direction

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None

        # Peer protocol state.
        self.am_choking: bool = True
        self.am_interested: bool = False
        self.peer_choking: bool = True
        self.peer_interested: bool = False
        self.bitfield: bytearray = bytearray()
        self.is_connected: bool = False

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

    def _mark_activity(self):
        self.last_activity_at = time.monotonic()

    async def connect(self, timeout: float = 8.0) -> bool:
        """Establish TCP connection and perform the BitTorrent handshake."""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.ip, self.port),
                timeout=timeout,
            )

            pstr = b"BitTorrent protocol"
            handshake = (
                bytes([len(pstr)])
                + pstr
                + (b"\x00" * 8)
                + self.info_hash
                + self.peer_id
            )

            self.writer.write(handshake)
            await self.writer.drain()

            response = await asyncio.wait_for(
                self.reader.readexactly(68),
                timeout=timeout,
            )

            if response[28:48] != self.info_hash:
                await self.close()
                return False

            self.remote_peer_id = bytes(response[48:68])
            self.is_connected = True
            self.connected_at = time.monotonic()
            self._mark_activity()
            return True

        except Exception:
            await self.close()
            return False

    async def send_interested(self):
        """Notify the peer that we want to download pieces from them."""
        if not self.is_connected or not self.writer:
            return
        self.writer.write(struct.pack(">IB", 1, PeerMessageID.INTERESTED))
        await self.writer.drain()
        self.am_interested = True
        self._mark_activity()

    async def send_request(
        self,
        piece_index: int,
        block_offset: int,
        length: int = 16384,
    ):
        """Request a block from a piece."""
        if not self.is_connected or not self.writer or self.peer_choking:
            return
        self.writer.write(
            struct.pack(
                ">IBIII",
                13,
                PeerMessageID.REQUEST,
                piece_index,
                block_offset,
                length,
            )
        )
        await self.writer.drain()
        self._mark_activity()

    async def send_bitfield(self, bitfield: bytes):
        """Advertise the pieces we currently have."""
        if not self.is_connected or not self.writer:
            return
        payload = bytes(bitfield)
        self.writer.write(
            struct.pack(">IB", 1 + len(payload), PeerMessageID.BITFIELD) + payload
        )
        await self.writer.drain()
        self._mark_activity()

    async def send_unchoke(self):
        """Allow a remote peer to request blocks from us."""
        if not self.is_connected or not self.writer:
            return
        self.writer.write(struct.pack(">IB", 1, PeerMessageID.UNCHOKE))
        await self.writer.drain()
        self.am_choking = False
        self._mark_activity()

    async def send_piece(self, piece_index: int, block_offset: int, data: bytes):
        """Send a requested block to a remote peer while seeding."""
        if not self.is_connected or not self.writer:
            return
        block_data = bytes(data)
        payload = struct.pack(">II", piece_index, block_offset) + block_data
        self.writer.write(
            struct.pack(">IB", 1 + len(payload), PeerMessageID.PIECE) + payload
        )
        await self.writer.drain()
        self.uploaded_bytes += len(block_data)
        self._mark_activity()

    async def read_message(self) -> Optional[tuple]:
        """Read and parse the next framed BitTorrent peer message."""
        if not self.is_connected or not self.reader:
            return None

        try:
            length_bytes = await self.reader.readexactly(4)
            (length,) = struct.unpack(">I", length_bytes)

            if length == 0:
                self._mark_activity()
                return ("KEEP_ALIVE", None)

            payload = await self.reader.readexactly(length)
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
            if msg_id == PeerMessageID.PIECE:
                if len(body) < 8:
                    return ("UNKNOWN", body)
                index, begin = struct.unpack(">II", body[:8])
                block_data = body[8:]
                self.downloaded_bytes += len(block_data)
                return ("PIECE", (index, begin, block_data))

            return ("UNKNOWN", body)

        except Exception:
            await self.close()
            return None

    async def close(self):
        """Terminate the TCP connection."""
        self.is_connected = False
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
        self.reader = None
        self.writer = None
