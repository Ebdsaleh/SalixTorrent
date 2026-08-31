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
from app.logic.peer import PeerConnection, normalise_peer_encryption_policy
from app.logic.network_binding import is_bind_address_available, normalise_bind_address
from app.logic.tracker import TrackerClient
from app.logic.torrent_v2 import (
    expected_piece_layer_count,
    piece_layer_depth,
    validate_piece_length as validate_v2_piece_length,
    verify_piece_layer,
)


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
    display_name: str
    trackers: Tuple[str, ...]
    v1_info_hash: bytes = b""
    v2_info_hash: bytes = b""

    @property
    def info_hash(self) -> bytes:
        """Legacy 20-byte wire identity used by discovery helpers."""
        return self.v1_info_hash or self.v2_info_hash[:20]

    @property
    def hex_info_hash(self) -> str:
        return (self.v1_info_hash or self.v2_info_hash).hex()

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
        v1_info_hash = b""
        v2_info_hash = b""

        for value in xt_values:
            text = unquote(str(value or "")).strip()
            lower = text.lower()
            if lower.startswith("urn:btih:"):
                encoded_hash = text[len("urn:btih:"):].strip()
                try:
                    if len(encoded_hash) == 40:
                        candidate = bytes.fromhex(encoded_hash)
                    elif len(encoded_hash) == 32:
                        candidate = base64.b32decode(encoded_hash.upper(), casefold=True)
                    else:
                        candidate = b""
                except (ValueError, base64.binascii.Error):
                    candidate = b""
                if len(candidate) == 20:
                    v1_info_hash = candidate
                continue

            if lower.startswith("urn:btmh:"):
                encoded_hash = text[len("urn:btmh:"):].strip()
                try:
                    tagged = bytes.fromhex(encoded_hash)
                except ValueError:
                    tagged = b""
                # Multihash function 0x12 = sha2-256, digest length 0x20.
                if len(tagged) == 34 and tagged[:2] == b"\x12\x20":
                    v2_info_hash = tagged[2:]

        if not v1_info_hash and not v2_info_hash:
            raise MagnetError("This magnet does not contain a supported btih or btmh info hash.")

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
            display_name=display_name,
            trackers=tuple(trackers),
            v1_info_hash=v1_info_hash,
            v2_info_hash=v2_info_hash,
        )


class _MagnetTorrentStub:
    """Minimal TorrentFile-like shape required by TrackerClient."""

    def __init__(self, magnet: MagnetLink):
        self.info_hash = magnet.info_hash
        self.announce_list = list(magnet.trackers)
        self.total_length = 1  # Metadata retrieval is a leecher announce, not a seed announce.


class MagnetMetadataFetcher:
    """Resolve v1/v2/hybrid magnets into verified BEP-9 metadata."""

    def __init__(
        self,
        magnet: MagnetLink,
        peer_id: bytes,
        *,
        max_peers: int = 25,
        progress_callback: Optional[Callable[[str, float, str], None]] = None,
        encryption_policy: str = "Prefer Encryption",
        bind_address: str = "",
        interface_lock: bool = False,
    ):
        self.magnet = magnet
        self.peer_id = bytes(peer_id)
        self.max_peers = max(1, min(200, int(max_peers)))
        self.progress_callback = progress_callback
        self.encryption_policy = normalise_peer_encryption_policy(encryption_policy)
        self.bind_address = normalise_bind_address(bind_address)
        self.interface_lock = bool(interface_lock)

        self._cancelled = False
        self.generations = tuple(
            generation
            for generation, present in (
                ("v1", bool(self.magnet.v1_info_hash)),
                ("v2", bool(self.magnet.v2_info_hash)),
            )
            if present
        )
        self.swarm_hashes = {
            generation: (
                self.magnet.v1_info_hash
                if generation == "v1"
                else self.magnet.v2_info_hash[:20]
            )
            for generation in self.generations
        }
        self._dht_by_generation = {
            generation: DHTClient(
                info_hash,
                private=False,
                bind_address=self.bind_address,
            )
            for generation, info_hash in self.swarm_hashes.items()
        }
        self._lpd_by_generation = {
            generation: LocalPeerDiscovery(
                info_hash,
                bind_address=self.bind_address,
            )
            for generation, info_hash in self.swarm_hashes.items()
        }
        stub = _MagnetTorrentStub(self.magnet)
        self._trackers_by_generation = (
            {
                generation: TrackerClient(
                    stub,
                    self.peer_id,
                    bind_address=self.bind_address,
                    encryption_policy=self.encryption_policy,
                    info_hash=info_hash,
                    generation=generation,
                )
                for generation, info_hash in self.swarm_hashes.items()
            }
            if self.magnet.trackers
            else {}
        )
        # Backward-compatible aliases for callers/tests that inspect the helper.
        first_generation = self.generations[0]
        self._dht = self._dht_by_generation[first_generation]
        self._lpd = self._lpd_by_generation[first_generation]
        self._tracker = self._trackers_by_generation.get(first_generation)
        self._peer_tasks: set[asyncio.Task] = set()
        self.resolved_piece_layers: dict[bytes, bytes] = {}

    def cancel(self):
        self._cancelled = True
        for task in list(self._peer_tasks):
            task.cancel()

    def _check_cancelled(self):
        if self._cancelled:
            raise MagnetCancelled()
        if (
            self.interface_lock
            and self.bind_address
            and not is_bind_address_available(self.bind_address)
        ):
            raise MagnetError(
                f"Interface Lock: bound address {self.bind_address} is no longer available."
            )

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

    async def _discover_once(self) -> List[Tuple[str, int, str]]:
        self._check_cancelled()
        self._progress(
            "Discovering",
            0.04,
            "Looking for peers through v1/v2 trackers, DHT and LAN...",
        )

        jobs: dict[asyncio.Task, str] = {}
        for generation in self.generations:
            tracker = self._trackers_by_generation.get(generation)
            if tracker is not None:
                task = asyncio.create_task(
                    tracker.fetch_peers(
                        uploaded=0,
                        downloaded=0,
                        left=1,
                        event="started",
                    )
                )
                jobs[task] = generation
            task = asyncio.create_task(
                self._dht_by_generation[generation].discover_peers(announce_port=0)
            )
            jobs[task] = generation

        discovered: List[Tuple[str, int, str]] = []
        pending = set(jobs)
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    generation = jobs[task]
                    try:
                        result = task.result()
                    except (asyncio.CancelledError, Exception):
                        result = []
                    if isinstance(result, list):
                        discovered.extend(
                            (ip, port, generation)
                            for ip, port in self._dedupe_endpoints(result)
                        )

                # Preserve the original fast-start behaviour: as soon as any
                # swarm produces usable peers, begin metadata exchange. Later
                # rounds continue discovery in the other swarm if necessary.
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

        for generation, lpd in self._lpd_by_generation.items():
            discovered.extend(
                (ip, port, generation)
                for ip, port in self._dedupe_endpoints(lpd.drain_peers())
            )

        out: List[Tuple[str, int, str]] = []
        seen = set()
        for ip, port, generation in discovered:
            key = (str(ip), int(port), str(generation))
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out

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

    async def _fetch_from_peer(
        self,
        endpoint: Tuple[str, int],
        generation: str,
    ) -> Optional[bytes]:
        generation = "v2" if str(generation).lower() == "v2" else "v1"
        if generation not in self.generations:
            return None
        wire_hash = (
            self.magnet.v1_info_hash
            if generation == "v1"
            else self.magnet.v2_info_hash[:20]
        )
        peer = PeerConnection(
            endpoint[0],
            endpoint[1],
            wire_hash,
            self.peer_id,
            source="Magnet",
            direction="Outgoing",
            encryption_policy=self.encryption_policy,
            bind_address=self.bind_address,
            v1_info_hash=self.magnet.v1_info_hash,
            v2_info_hash=self.magnet.v2_info_hash,
            protocol_generation=generation,
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
            if self.magnet.v1_info_hash:
                if hashlib.sha1(metadata).digest() != self.magnet.v1_info_hash:
                    return None
            if self.magnet.v2_info_hash:
                if hashlib.sha256(metadata).digest() != self.magnet.v2_info_hash:
                    return None

            try:
                decoded = Bencode.decode(metadata)
            except Exception:
                return None
            if not isinstance(decoded, dict):
                return None

            if self.magnet.v2_info_hash:
                layers = await self._fetch_v2_piece_layers(peer, decoded)
                if layers is None:
                    return None
                self.resolved_piece_layers = layers

            return metadata

        except MagnetCancelled:
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            return None
        finally:
            await peer.close()

    @staticmethod
    def _v2_file_roots(info_dict: dict) -> tuple[int, list[tuple[bytes, int]]]:
        try:
            piece_length = validate_v2_piece_length(int(info_dict[b"piece length"]))
        except Exception as exc:
            raise MagnetError(f"Resolved v2 metadata has an invalid piece length: {exc}") from exc
        if int(info_dict.get(b"meta version", 0) or 0) != 2:
            raise MagnetError("The btmh metadata does not declare meta version 2.")
        tree = info_dict.get(b"file tree")
        if not isinstance(tree, dict):
            raise MagnetError("Resolved v2 metadata is missing its file tree.")
        roots: list[tuple[bytes, int]] = []

        def walk(node: object):
            if not isinstance(node, dict):
                raise MagnetError("Resolved v2 file tree is malformed.")
            if b"" in node:
                props = node[b""]
                if not isinstance(props, dict):
                    raise MagnetError("Resolved v2 file properties are malformed.")
                length = int(props.get(b"length", -1))
                if length < 0:
                    raise MagnetError("Resolved v2 file length is invalid.")
                root = props.get(b"pieces root", b"")
                if length and (not isinstance(root, bytes) or len(root) != 32):
                    raise MagnetError("Resolved v2 file is missing a pieces root.")
                if length > piece_length:
                    roots.append((bytes(root), length))
                return
            for child in node.values():
                walk(child)

        walk(tree)
        return piece_length, roots

    async def _fetch_v2_piece_layers(
        self,
        peer: PeerConnection,
        info_dict: dict,
    ) -> Optional[dict[bytes, bytes]]:
        piece_length, roots = self._v2_file_roots(info_dict)
        if not roots:
            return {}
        if peer.protocol_generation != "v2":
            return None

        depth = piece_layer_depth(piece_length)
        result: dict[bytes, bytes] = {}
        for root, file_length in roots:
            count = expected_piece_layer_count(file_length, piece_length)
            hashes: list[bytes] = []
            for index in range(0, count, 2):
                if not await peer.send_hash_request(root, depth, index, 2, 0):
                    return None
                deadline = time.monotonic() + 6.0
                response_hashes: Optional[list[bytes]] = None
                while peer.is_connected and time.monotonic() < deadline:
                    try:
                        message = await asyncio.wait_for(peer.read_message(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    if not message:
                        return None
                    msg_type, data = message
                    if msg_type == "HASH_REJECT":
                        if data and data.get("pieces_root") == root and data.get("index") == index:
                            return None
                        continue
                    if msg_type != "HASHES" or not isinstance(data, dict):
                        continue
                    if (
                        data.get("pieces_root") != root
                        or int(data.get("base_layer", -1)) != depth
                        or int(data.get("index", -1)) != index
                    ):
                        continue
                    response_hashes = list(data.get("hashes", []))
                    break
                if not response_hashes:
                    return None
                hashes.extend(response_hashes[: min(2, count - index)])

            hashes = hashes[:count]
            if not verify_piece_layer(
                root,
                hashes,
                file_length=file_length,
                piece_length=piece_length,
            ):
                return None
            result[root] = b"".join(hashes)
        return result

    async def _try_peer_batch(
        self,
        endpoints: Sequence[Tuple[str, int, str]],
    ) -> Optional[bytes]:
        semaphore = asyncio.Semaphore(MAGNET_MAX_PARALLEL_PEERS)

        async def worker(endpoint):
            async with semaphore:
                ip, port, generation = endpoint
                return await self._fetch_from_peer((ip, port), generation)

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
        attempted: set[Tuple[str, int, str]] = set()
        for lpd in self._lpd_by_generation.values():
            await lpd.start(listen_port=0)

        try:
            while time.monotonic() - started < max(10.0, float(timeout)):
                self._check_cancelled()

                candidates = await self._discover_once()
                for generation, lpd in self._lpd_by_generation.items():
                    candidates.extend(
                        (ip, port, generation)
                        for ip, port in self._dedupe_endpoints(lpd.drain_peers())
                    )

                unique: List[Tuple[str, int, str]] = []
                seen = set()
                for ip, port, generation in candidates:
                    key = (str(ip), int(port), str(generation))
                    if key in seen or key in attempted:
                        continue
                    seen.add(key)
                    unique.append(key)

                if unique:
                    unique = unique[: self.max_peers]
                    attempted.update(unique)
                    generations = "/".join(sorted({item[2] for item in unique}))
                    self._progress(
                        "Connecting",
                        0.12,
                        f"Found {len(unique)} new {generations} peer(s); requesting torrent metadata...",
                    )
                    metadata = await self._try_peer_batch(unique)
                    if metadata:
                        self._progress("Complete", 1.0, "Torrent metadata verified.")
                        return metadata
                else:
                    self._progress(
                        "Discovering",
                        0.08,
                        "No metadata peers yet; continuing tracker/DHT/LAN discovery...",
                    )

                for _ in range(4):
                    self._check_cancelled()
                    await asyncio.sleep(0.5)
                    lpd_peers: List[Tuple[str, int, str]] = []
                    for generation, lpd in self._lpd_by_generation.items():
                        for ip, port in self._dedupe_endpoints(lpd.drain_peers()):
                            key = (ip, port, generation)
                            if key not in attempted:
                                lpd_peers.append(key)
                    if lpd_peers:
                        attempted.update(lpd_peers)
                        metadata = await self._try_peer_batch(
                            lpd_peers[: self.max_peers]
                        )
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
            for lpd in self._lpd_by_generation.values():
                await lpd.close()
            for dht in self._dht_by_generation.values():
                await dht.close()


def build_torrent_bytes(
    magnet: MagnetLink,
    raw_info: bytes,
    *,
    piece_layers: Optional[dict[bytes, bytes]] = None,
) -> bytes:
    """Build a .torrent while preserving the exact raw info dictionary bytes."""
    raw_info = bytes(raw_info)
    if magnet.v1_info_hash and hashlib.sha1(raw_info).digest() != magnet.v1_info_hash:
        raise MagnetError("Resolved metadata does not match the magnet btih info hash.")
    if magnet.v2_info_hash and hashlib.sha256(raw_info).digest() != magnet.v2_info_hash:
        raise MagnetError("Resolved metadata does not match the magnet btmh info hash.")

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
    if magnet.v2_info_hash:
        entries.append((b"piece layers", Bencode.encode(piece_layers or {})))

    parts = [b"d"]
    for key, encoded_value in sorted(entries, key=lambda item: item[0]):
        parts.append(Bencode.encode(key))
        parts.append(encoded_value)
    parts.append(b"e")
    return b"".join(parts)


