# app/logic/magnet.py

from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import os
import time
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from app.logic.bencode import Bencode
from app.logic.dht import DHTClient
from app.logic.local_peer_discovery import LocalPeerDiscovery
from app.logic.peer import PeerConnection
from app.logic.tracker import TrackerClient


METADATA_BLOCK_SIZE = 16 * 1024
MAX_METADATA_SIZE = 16 * 1024 * 1024
MAGNET_RESOLVE_TIMEOUT = 75.0
MAGNET_PEER_TIMEOUT = 14.0
MAGNET_MAX_PARALLEL_PEERS = 10


class MagnetError(ValueError):
    """Raised when a magnet URI or metadata exchange is invalid."""


class MagnetCancelled(asyncio.CancelledError):
    """Raised when a metadata resolution is cancelled by the user."""


@dataclass(frozen=True)
class MagnetLink:
    uri: str
    info_hash: bytes
    display_name: str
    trackers: Tuple[str, ...]

    @property
    def hex_info_hash(self) -> str:
        return self.info_hash.hex()

    @classmethod
    def parse(cls, uri: str) -> "MagnetLink":
        raw_uri = str(uri or "").strip()
        if not raw_uri:
            raise MagnetError("Paste a magnet link first.")

        parsed = urlparse(raw_uri)
        if parsed.scheme.lower() != "magnet":
            raise MagnetError("The link must begin with magnet:?")

        params = parse_qs(parsed.query, keep_blank_values=False)
        xt_values = params.get("xt", [])
        info_hash = b""

        for value in xt_values:
            text = unquote(str(value or "")).strip()
            prefix = "urn:btih:"
            if not text.lower().startswith(prefix):
                continue
            encoded_hash = text[len(prefix):].strip()
            try:
                if len(encoded_hash) == 40:
                    info_hash = bytes.fromhex(encoded_hash)
                elif len(encoded_hash) == 32:
                    info_hash = base64.b32decode(encoded_hash.upper(), casefold=True)
            except (ValueError, base64.binascii.Error):
                info_hash = b""
            if len(info_hash) == 20:
                break

        if len(info_hash) != 20:
            raise MagnetError(
                "This magnet does not contain a supported BitTorrent v1 btih info hash."
            )

        display_name = ""
        dn_values = params.get("dn", [])
        if dn_values:
            display_name = unquote(str(dn_values[0] or "")).strip()

        trackers: List[str] = []
        for value in params.get("tr", []):
            tracker = unquote(str(value or "")).strip()
            if tracker and tracker not in trackers:
                trackers.append(tracker)

        return cls(
            uri=raw_uri,
            info_hash=info_hash,
            display_name=display_name,
            trackers=tuple(trackers),
        )


class _MagnetTorrentStub:
    """Minimal TorrentFile-like shape required by TrackerClient."""

    def __init__(self, magnet: MagnetLink):
        self.info_hash = magnet.info_hash
        self.announce_list = list(magnet.trackers)
        self.total_length = 1  # Metadata retrieval is a leecher announce, not a seed announce.


class MagnetMetadataFetcher:
    """Resolve a v1 magnet URI into the raw BEP-9 info dictionary bytes."""

    def __init__(
        self,
        magnet: MagnetLink,
        peer_id: bytes,
        *,
        max_peers: int = 25,
        progress_callback: Optional[Callable[[str, float, str], None]] = None,
    ):
        self.magnet = magnet
        self.peer_id = bytes(peer_id)
        self.max_peers = max(1, min(200, int(max_peers)))
        self.progress_callback = progress_callback

        self._cancelled = False
        self._dht = DHTClient(self.magnet.info_hash, private=False)
        self._lpd = LocalPeerDiscovery(self.magnet.info_hash)
        self._tracker = (
            TrackerClient(_MagnetTorrentStub(self.magnet), self.peer_id)
            if self.magnet.trackers
            else None
        )
        self._peer_tasks: set[asyncio.Task] = set()

    def cancel(self):
        self._cancelled = True
        for task in list(self._peer_tasks):
            task.cancel()

    def _check_cancelled(self):
        if self._cancelled:
            raise MagnetCancelled()

    def _progress(self, stage: str, fraction: float, message: str):
        callback = self.progress_callback
        if callback is None:
            return
        try:
            callback(
                str(stage),
                max(0.0, min(1.0, float(fraction))),
                str(message or ""),
            )
        except Exception:
            pass

    @staticmethod
    def _dedupe_endpoints(endpoints: Iterable[Tuple[str, int]]) -> List[Tuple[str, int]]:
        out: List[Tuple[str, int]] = []
        seen = set()
        for endpoint in endpoints:
            try:
                normalized = (str(endpoint[0]), int(endpoint[1]))
            except (TypeError, ValueError, IndexError):
                continue
            if not normalized[0] or not (0 < normalized[1] <= 65535):
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
        return out

    async def _discover_once(self) -> List[Tuple[str, int]]:
        self._check_cancelled()
        self._progress("Discovering", 0.04, "Looking for peers through trackers, DHT and LAN...")

        jobs: List[asyncio.Task] = []
        if self._tracker is not None:
            jobs.append(
                asyncio.create_task(
                    self._tracker.fetch_peers(
                        uploaded=0,
                        downloaded=0,
                        left=1,
                        event="started",
                    )
                )
            )
        jobs.append(asyncio.create_task(self._dht.discover_peers(announce_port=0)))

        discovered: List[Tuple[str, int]] = []
        pending = set(jobs)
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    try:
                        result = task.result()
                    except (asyncio.CancelledError, Exception):
                        result = []
                    if isinstance(result, list):
                        discovered.extend(result)

                # A tracker can return usable peers much sooner than an
                # iterative DHT lookup. Start BEP-9 immediately rather than
                # forcing the user to wait for every discovery source first.
                if discovered:
                    for task in pending:
                        task.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
                    pending.clear()
                    break
        finally:
            for task in pending:
                task.cancel()

        discovered.extend(self._lpd.drain_peers())
        return self._dedupe_endpoints(discovered)

    async def _wait_for_extended_handshake(self, peer: PeerConnection) -> bool:
        deadline = time.monotonic() + 5.0
        while peer.is_connected and time.monotonic() < deadline:
            self._check_cancelled()
            try:
                message = await asyncio.wait_for(peer.read_message(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if not message:
                return False
            msg_type, _data = message
            if msg_type == "EXTENDED_HANDSHAKE":
                return peer.metadata_supported and peer.remote_metadata_size > 0
        return False

    async def _fetch_from_peer(self, endpoint: Tuple[str, int]) -> Optional[bytes]:
        peer = PeerConnection(
            endpoint[0],
            endpoint[1],
            self.magnet.info_hash,
            self.peer_id,
            source="Magnet",
            direction="Outgoing",
        )

        try:
            if not await peer.connect(timeout=5.0):
                return None
            if not peer.supports_extensions:
                return None
            if not await peer.send_extended_handshake(listen_port=0, metadata_size=0):
                return None
            if not await self._wait_for_extended_handshake(peer):
                return None

            metadata_size = int(peer.remote_metadata_size or 0)
            if metadata_size <= 0 or metadata_size > MAX_METADATA_SIZE:
                return None

            piece_count = int(math.ceil(metadata_size / METADATA_BLOCK_SIZE))
            pieces: List[Optional[bytes]] = [None] * piece_count
            received = 0

            for piece_index in range(piece_count):
                self._check_cancelled()
                if not await peer.send_metadata_request(piece_index):
                    return None

                piece_deadline = time.monotonic() + 6.0
                while peer.is_connected and time.monotonic() < piece_deadline:
                    self._check_cancelled()
                    try:
                        message = await asyncio.wait_for(peer.read_message(), timeout=1.5)
                    except asyncio.TimeoutError:
                        continue
                    if not message:
                        return None

                    msg_type, data = message
                    if msg_type != "METADATA":
                        continue

                    header = data.get("header", {}) if isinstance(data, dict) else {}
                    block = data.get("data", b"") if isinstance(data, dict) else b""
                    try:
                        message_type = int(header.get(b"msg_type", -1))
                        response_piece = int(header.get(b"piece", -1))
                        total_size = int(header.get(b"total_size", metadata_size) or metadata_size)
                    except (TypeError, ValueError):
                        continue

                    if message_type == 2 and response_piece == piece_index:
                        return None
                    if message_type != 1 or response_piece != piece_index:
                        continue
                    if total_size != metadata_size:
                        return None

                    expected_length = min(
                        METADATA_BLOCK_SIZE,
                        metadata_size - (piece_index * METADATA_BLOCK_SIZE),
                    )
                    if len(block) != expected_length:
                        return None

                    pieces[piece_index] = bytes(block)
                    received += len(block)
                    self._progress(
                        "Metadata",
                        0.20 + 0.78 * (received / metadata_size),
                        f"Receiving metadata from {endpoint[0]}:{endpoint[1]} — "
                        f"{received / metadata_size * 100:.0f}%",
                    )
                    break

                if pieces[piece_index] is None:
                    return None

            metadata = b"".join(piece or b"" for piece in pieces)[:metadata_size]
            if hashlib.sha1(metadata).digest() != self.magnet.info_hash:
                return None

            try:
                decoded = Bencode.decode(metadata)
            except Exception:
                return None
            if not isinstance(decoded, dict):
                return None

            return metadata

        except MagnetCancelled:
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            return None
        finally:
            await peer.close()

    async def _try_peer_batch(self, endpoints: Sequence[Tuple[str, int]]) -> Optional[bytes]:
        semaphore = asyncio.Semaphore(MAGNET_MAX_PARALLEL_PEERS)

        async def worker(endpoint):
            async with semaphore:
                return await self._fetch_from_peer(endpoint)

        tasks = [asyncio.create_task(worker(endpoint)) for endpoint in endpoints]
        self._peer_tasks.update(tasks)
        try:
            pending = set(tasks)
            while pending:
                self._check_cancelled()
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    try:
                        result = task.result()
                    except (asyncio.CancelledError, MagnetCancelled):
                        raise MagnetCancelled()
                    except Exception:
                        result = None
                    if result:
                        for other in pending:
                            other.cancel()
                        if pending:
                            await asyncio.gather(*pending, return_exceptions=True)
                        return result
            return None
        finally:
            leftovers = [task for task in tasks if not task.done()]
            for task in leftovers:
                task.cancel()
            if leftovers:
                await asyncio.gather(*leftovers, return_exceptions=True)
            for task in tasks:
                self._peer_tasks.discard(task)

    async def resolve(self, timeout: float = MAGNET_RESOLVE_TIMEOUT) -> bytes:
        started = time.monotonic()
        attempted = set()
        await self._lpd.start(listen_port=0)

        try:
            round_index = 0
            while time.monotonic() - started < max(10.0, float(timeout)):
                self._check_cancelled()
                round_index += 1

                candidates = await self._discover_once()
                candidates.extend(self._lpd.drain_peers())
                candidates = [
                    endpoint
                    for endpoint in self._dedupe_endpoints(candidates)
                    if endpoint not in attempted
                ]

                if candidates:
                    candidates = candidates[: self.max_peers]
                    attempted.update(candidates)
                    self._progress(
                        "Connecting",
                        0.12,
                        f"Found {len(candidates)} new peer(s); requesting torrent metadata...",
                    )
                    metadata = await self._try_peer_batch(candidates)
                    if metadata:
                        self._progress("Complete", 1.0, "Torrent metadata verified.")
                        return metadata
                else:
                    self._progress(
                        "Discovering",
                        0.08,
                        "No metadata peers yet; continuing DHT/LAN discovery...",
                    )

                # A short wait gives LAN announcements and newly reachable DHT
                # peers time to arrive without spinning or blocking the GUI.
                for _ in range(4):
                    self._check_cancelled()
                    await asyncio.sleep(0.5)
                    lpd_peers = [
                        endpoint
                        for endpoint in self._lpd.drain_peers()
                        if endpoint not in attempted
                    ]
                    if lpd_peers:
                        attempted.update(lpd_peers)
                        metadata = await self._try_peer_batch(lpd_peers[: self.max_peers])
                        if metadata:
                            self._progress("Complete", 1.0, "Torrent metadata verified.")
                            return metadata

            raise MagnetError(
                "Could not retrieve torrent metadata before the magnet lookup timed out."
            )

        finally:
            for task in list(self._peer_tasks):
                task.cancel()
            if self._peer_tasks:
                await asyncio.gather(*self._peer_tasks, return_exceptions=True)
            self._peer_tasks.clear()
            await self._lpd.close()
            await self._dht.close()


def build_torrent_bytes(magnet: MagnetLink, raw_info: bytes) -> bytes:
    """Build a .torrent while preserving the exact info bytes used by btih."""
    raw_info = bytes(raw_info)
    if hashlib.sha1(raw_info).digest() != magnet.info_hash:
        raise MagnetError("Resolved metadata does not match the magnet info hash.")

    try:
        info_dict = Bencode.decode(raw_info)
    except Exception as exc:
        raise MagnetError(f"Resolved metadata is not valid bencode: {exc}") from exc
    if not isinstance(info_dict, dict):
        raise MagnetError("Resolved metadata is not an info dictionary.")

    entries: List[Tuple[bytes, bytes]] = []
    if magnet.trackers:
        first = magnet.trackers[0]
        entries.append((b"announce", Bencode.encode(first)))
        entries.append(
            (
                b"announce-list",
                Bencode.encode([[tracker] for tracker in magnet.trackers]),
            )
        )
    entries.append((b"created by", Bencode.encode("Salix_T magnet metadata resolver")))
    entries.append((b"info", raw_info))

    parts = [b"d"]
    for key, encoded_value in sorted(entries, key=lambda item: item[0]):
        parts.append(Bencode.encode(key))
        parts.append(encoded_value)
    parts.append(b"e")
    return b"".join(parts)
