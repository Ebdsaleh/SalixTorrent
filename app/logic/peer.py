# app/logic/peer.py

import asyncio
import struct
from typing import Optional, Callable


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


class PeerConnection:
    """Manages an asynchronous TCP socket connection to a single BitTorrent peer."""

    def __init__(self, ip: str, port: int, info_hash: bytes, peer_id: bytes):
        self.ip = ip
        self.port = port
        self.info_hash = info_hash
        self.peer_id = peer_id

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None

        # Peer State
        self.am_choking: bool = True
        self.am_interested: bool = False
        self.peer_choking: bool = True
        self.peer_interested: bool = False
        self.bitfield: bytearray = bytearray()
        self.is_connected: bool = False

    async def connect(self, timeout: float = 8.0) -> bool:
        """Establishes TCP connection and performs BitTorrent protocol handshake."""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.ip, self.port),
                timeout=timeout
            )
            
            # Send BitTorrent Handshake
            pstr = b"BitTorrent protocol"
            pstrlen = bytes([len(pstr)])
            reserved = b"\x00" * 8
            handshake = pstrlen + pstr + reserved + self.info_hash + self.peer_id
            
            self.writer.write(handshake)
            await self.writer.drain()

            # Read Handshake Response (68 bytes total)
            response = await asyncio.wait_for(self.reader.readexactly(68), timeout=timeout)
            
            # Verify Info Hash match
            resp_info_hash = response[28:48]
            if resp_info_hash != self.info_hash:
                await self.close()
                return False

            self.is_connected = True
            return True

        except Exception:
            await self.close()
            return False

    async def send_interested(self):
        """Notifies the peer that we want to download pieces from them."""
        if not self.is_connected or not self.writer:
            return
        # Length = 1, ID = 2
        msg = struct.pack(">IB", 1, PeerMessageID.INTERESTED)
        self.writer.write(msg)
        await self.writer.drain()
        self.am_interested = True

    async def send_request(self, piece_index: int, block_offset: int, length: int = 16384):
        """Requests a specific 16KB block from a piece."""
        if not self.is_connected or not self.writer or self.peer_choking:
            return
        # Length = 13, ID = 6, piece_index (4B), offset (4B), length (4B)
        msg = struct.pack(
            ">IBIII", 13, PeerMessageID.REQUEST, piece_index, block_offset, length
        )
        self.writer.write(msg)
        await self.writer.drain()

    async def read_message(self) -> Optional[tuple]:
        """Reads and parses the next framing message from the TCP socket."""
        if not self.is_connected or not self.reader:
            return None

        try:
            # 4-byte big-endian message length prefix
            length_bytes = await self.reader.readexactly(4)
            (length,) = struct.unpack(">I", length_bytes)

            # Keep-Alive message (0 bytes)
            if length == 0:
                return ("KEEP_ALIVE", None)

            # Read message payload
            payload = await self.reader.readexactly(length)
            msg_id = payload[0]
            body = payload[1:]

            if msg_id == PeerMessageID.CHOKE:
                self.peer_choking = True
                return ("CHOKE", None)
            elif msg_id == PeerMessageID.UNCHOKE:
                self.peer_choking = False
                return ("UNCHOKE", None)
            elif msg_id == PeerMessageID.INTERESTED:
                self.peer_interested = True
                return ("INTERESTED", None)
            elif msg_id == PeerMessageID.NOT_INTERESTED:
                self.peer_interested = False
                return ("NOT_INTERESTED", None)
            elif msg_id == PeerMessageID.HAVE:
                (piece_idx,) = struct.unpack(">I", body)
                return ("HAVE", piece_idx)
            elif msg_id == PeerMessageID.BITFIELD:
                self.bitfield = bytearray(body)
                return ("BITFIELD", self.bitfield)
            elif msg_id == PeerMessageID.PIECE:
                # Body format: 4B piece index, 4B offset, followed by raw block data
                index, begin = struct.unpack(">II", body[:8])
                block_data = body[8:]
                return ("PIECE", (index, begin, block_data))

            return ("UNKNOWN", body)

        except Exception:
            await self.close()
            return None

    async def close(self):
        """Terminates the TCP connection."""
        self.is_connected = False
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
        self.reader = None
        self.writer = None
