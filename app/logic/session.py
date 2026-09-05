# app/logic/session.py

import asyncio
import math
import os
import queue
import random
import socket
import struct
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Set, Tuple

from app.logic.bencode import Bencode
from app.logic.dht import DHTClient, DHT_REFRESH_INTERVAL
from app.logic.local_peer_discovery import LocalPeerDiscovery
from app.logic.peer import (
    build_reserved_bytes,
    LOCAL_UT_METADATA_ID,
    LOCAL_UT_PEX_ID,
    METADATA_BLOCK_SIZE,
    PEX_SEND_INTERVAL,
    PEER_ENCRYPTION_DISABLED,
    PEER_ENCRYPTION_PREFER,
    PEER_ENCRYPTION_REQUIRE,
    PeerConnection,
    PeerMessageID,
    build_extended_handshake_payload,
    build_extended_message,
    build_hash_request_payload,
    encode_pex_payload,
    identify_peer_client,
    parse_extended_handshake,
    parse_metadata_payload,
    parse_pex_payload,
    parse_hash_request_payload,
    reserved_supports_dht,
    reserved_supports_extensions,
    reserved_supports_v2,
    normalise_peer_encryption_policy,
)
from app.logic.mse import MSEError, PeerWireStream, mse_responder_handshake
from app.logic.network_binding import (
    format_endpoint,
    ip_family,
    is_bind_address_available,
    mask_ip_for_display,
    normalise_bind_address,
    wildcard_for_family,
)
from app.logic.piece_manager import (
    BLOCK_SIZE,
    ENDGAME_BLOCK_THRESHOLD,
    Block,
    PieceManager,
)
from app.logic.torrent_file import TorrentFile
from app.logic.seeding_policy import (
    DEFAULT_SEEDING_RATIO,
    DEFAULT_SEEDING_TIME_MINUTES,
    SEEDING_GOAL_FOREVER,
    evaluate_seeding_goal,
    normalise_seeding_goal_mode,
    normalise_seeding_ratio,
    normalise_seeding_time_component,
    normalise_seeding_time_minutes,
    seeding_goal_uses_time,
    seeding_time_components_from_minutes,
    seeding_time_components_to_minutes,
)
from app.logic.torrent_v2 import expected_piece_layer_count, piece_layer_depth, zero_hash
from app.logic.tracker import TrackerClient
from app.logic.transfer_add import (
    TORRENT_PROTOCOL_AUTO,
    TORRENT_PROTOCOL_V1_ONLY,
    TORRENT_PROTOCOL_V2_ONLY,
    normalise_torrent_protocol_policy,
)

RATE_UNIT_MULTIPLIERS = {
    "KB/s": 1024.0,
    "MB/s": 1024.0 * 1024.0,
    "kbps": 1000.0 / 8.0,
    "Mbps": 1000.0 * 1000.0 / 8.0,
}

SPEED_HISTORY_SECONDS = 120.0
SPEED_SAMPLE_INTERVAL = 0.5
SPEED_HISTORY_MAX_SAMPLES = int(SPEED_HISTORY_SECONDS / SPEED_SAMPLE_INTERVAL) + 8

# UI telemetry is intentionally lossy. State transitions still emit immediately,
# but periodic 0.5-second snapshots are skipped while the UI queue is backed up.
# A stale speed sample is less valuable than keeping Dear PyGui responsive.
UI_QUEUE_BACKPRESSURE_LIMIT = 8

# Piece/file/source telemetry is much more expensive than the lightweight
# transfer counters. Cache it briefly so peer churn or other state events do not
# rebuild thousands of piece/file calculations several times in one second.
DETAIL_TELEMETRY_INTERVAL = 1.0

# Phase 2/3 download request pipeline. The window grows with measured peer
# throughput but remains strictly bounded. Request timeout checks piggyback on
# the existing peer worker; no separate polling task is created.
REQUEST_PIPELINE_MIN = 8
REQUEST_PIPELINE_MAX = 64
REQUEST_PIPELINE_TARGET_SECONDS = 0.25
REQUEST_REFILL_BURST = 4
REQUEST_TIMEOUT_SECONDS = 30.0
REQUEST_TIMEOUT_CHECK_INTERVAL = 1.0
REQUEST_RETRY_COOLDOWN_SECONDS = 60.0
MAX_PENDING_UPLOAD_REQUESTS_PER_PEER = 64


def request_pipeline_limit(download_speed_kbps: float) -> int:
    """Return a bounded per-peer pipeline depth from observed throughput."""
    try:
        speed_bps = max(0.0, float(download_speed_kbps)) * 1024.0
    except (TypeError, ValueError):
        speed_bps = 0.0
    if speed_bps <= 0.0:
        return REQUEST_PIPELINE_MIN
    target_blocks = int(
        math.ceil((speed_bps * REQUEST_PIPELINE_TARGET_SECONDS) / BLOCK_SIZE)
    )
    return max(REQUEST_PIPELINE_MIN, min(REQUEST_PIPELINE_MAX, target_blocks))


TORRENT_PRIORITY_HIGH = "High"
TORRENT_PRIORITY_NORMAL = "Normal"
TORRENT_PRIORITY_LOW = "Low"
TORRENT_PRIORITIES = (
    TORRENT_PRIORITY_HIGH,
    TORRENT_PRIORITY_NORMAL,
    TORRENT_PRIORITY_LOW,
)


class AsyncBandwidthLimiter:
    """
    Shared aggregate rate limiter for all peers in one torrent session.

    The limiter schedules byte-sized transfer slots across every peer instead
    of sleeping independently per connection, so a 1 MB/s torrent limit is
    approximately 1 MB/s total rather than 1 MB/s per peer. Runtime changes
    are noticed within 100 ms. A rate of 0 means unlimited.
    """

    def __init__(self):
        self.rate_bps: float = 0.0
        self._next_slot: float = time.monotonic()
        self._version: int = 0
        self._lock = asyncio.Lock()

    def set_rate(self, rate_bps: float):
        self.rate_bps = max(0.0, float(rate_bps))
        self._next_slot = time.monotonic()
        self._version += 1

    async def throttle(self, byte_count: int):
        byte_count = int(byte_count)
        if byte_count <= 0 or self.rate_bps <= 0:
            return

        while True:
            async with self._lock:
                rate_bps = self.rate_bps
                version = self._version

                if rate_bps <= 0:
                    return

                now = time.monotonic()
                scheduled_start = max(now, self._next_slot)
                self._next_slot = scheduled_start + (byte_count / rate_bps)

            delay = scheduled_start - time.monotonic()

            while delay > 0:
                await asyncio.sleep(min(0.10, delay))

                # A live limit change invalidates the old reservation. Re-book
                # the transfer against the new rate instead of waiting for a
                # stale schedule created by the previous limit.
                if version != self._version:
                    break

                delay = scheduled_start - time.monotonic()

            if version == self._version:
                return


def _rate_to_bps(value: float, unit: str) -> int:
    try:
        numeric_value = max(0.0, float(value))
    except (TypeError, ValueError):
        numeric_value = 0.0

    multiplier = RATE_UNIT_MULTIPLIERS.get(unit, RATE_UNIT_MULTIPLIERS["KB/s"])
    return int(numeric_value * multiplier)


class SessionState:
    IDLE = "Idle"
    QUEUED = "Queued"
    CHECKING = "Checking"
    FAST_RESUME = "Fast Resume"
    DOWNLOADING = "Downloading"
    SEEDING = "Seeding"
    PAUSED = "Paused"
    STOPPED = "Stopped"
    COMPLETED = "Completed"
    ERROR = "Error"


class _UploadRequestState:
    """One bounded, sleeping upload queue per connected peer.

    A single worker serializes disk reads and PIECE writes for that connection.
    CANCEL removes the key from ``active``; queued work is skipped and in-flight
    work re-checks the key before sending. No task is created per REQUEST.
    """

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue(
            maxsize=MAX_PENDING_UPLOAD_REQUESTS_PER_PEER
        )
        self.active: set[Tuple[int, int, int]] = set()
        self.task: Optional[asyncio.Task] = None


class TorrentSession:
    def __init__(
        self,
        torrent_path: str,
        ui_queue: Optional[queue.Queue] = None,
        max_peers: int = 25,
        download_dir: str = "downloads",
        seed_source_path: Optional[str] = None,
        listen_port: int = 6881,
        enable_dht: bool = True,
        enable_pex: bool = True,
        enable_lan_discovery: bool = True,
        encryption_policy: str = PEER_ENCRYPTION_PREFER,
        network_bind_address: str = "",
        interface_lock: bool = False,
        mask_peer_ips: bool = False,
        protocol_policy: str = TORRENT_PROTOCOL_AUTO,
        global_download_limiter: Optional[AsyncBandwidthLimiter] = None,
        global_upload_limiter: Optional[AsyncBandwidthLimiter] = None,
        listen_port_callback: Optional[Callable[..., None]] = None,
        incoming_peer_callback: Optional[Callable[[int, str], None]] = None,
        seeding_goal_mode: str = SEEDING_GOAL_FOREVER,
        seeding_ratio_limit: float = DEFAULT_SEEDING_RATIO,
        seeding_time_limit_minutes: int = DEFAULT_SEEDING_TIME_MINUTES,
        seeding_elapsed_seconds: float = 0.0,
        seeding_time_goal_baseline_seconds: float = 0.0,
        seeding_time_days: Optional[int] = None,
        seeding_time_hours: Optional[int] = None,
        seeding_time_minutes_component: Optional[int] = None,
        seeding_goal_callback: Optional[Callable[[str, str], None]] = None,
    ):
        self.torrent_path = torrent_path
        self.torrent = TorrentFile(torrent_path)
        self.protocol_policy = normalise_torrent_protocol_policy(protocol_policy)
        if self.protocol_policy == TORRENT_PROTOCOL_V1_ONLY and not self.torrent.is_v1:
            raise ValueError("BitTorrent v1 Only was selected, but this torrent has no v1 identity.")
        if self.protocol_policy == TORRENT_PROTOCOL_V2_ONLY and not self.torrent.is_v2:
            raise ValueError("BitTorrent v2 Only was selected, but this torrent has no v2 identity.")

        generations = []
        if self.torrent.is_v1 and self.protocol_policy != TORRENT_PROTOCOL_V2_ONLY:
            generations.append("v1")
        if self.torrent.is_v2 and self.protocol_policy != TORRENT_PROTOCOL_V1_ONLY:
            generations.append("v2")
        if not generations:
            raise ValueError("The selected torrent protocol policy has no compatible swarm identity.")
        self.active_generations = tuple(generations)
        self.swarm_hashes = {
            "v1": self.torrent.v1_info_hash,
            "v2": self.torrent.v2_info_hash[:20] if self.torrent.v2_info_hash else b"",
        }
        self.ui_queue = ui_queue or queue.Queue()
        self.max_peers = max_peers

        random_id = "".join(str(random.randint(0, 9)) for _ in range(12)).encode("ascii")
        self.peer_id = b"-ST0001-" + random_id

        self.seed_source_path = (
            os.path.abspath(os.path.expanduser(seed_source_path))
            if seed_source_path
            else ""
        )
        self.piece_mgr = PieceManager(
            self.torrent,
            download_dir=download_dir,
            seed_source_path=self.seed_source_path or None,
        )
        self.encryption_policy = normalise_peer_encryption_policy(encryption_policy)
        self.network_bind_address = normalise_bind_address(network_bind_address)
        self.interface_lock = bool(interface_lock)
        self.mask_peer_ips = bool(mask_peer_ips)
        self._last_interface_check_at: float = 0.0
        self._trackers_by_generation = {
            generation: TrackerClient(
                self.torrent,
                self.peer_id,
                bind_address=self.network_bind_address,
                encryption_policy=self.encryption_policy,
                info_hash=self.swarm_hashes[generation],
                generation=generation,
            )
            for generation in self.active_generations
        }
        self.tracker = self._trackers_by_generation[self.active_generations[0]]

        self.active_peers: List[PeerConnection] = []
        self._worker_tasks: List[asyncio.Task] = []

        # Outgoing download request ownership mirrors PieceManager's reverse
        # index so endgame completion can target CANCEL frames directly without
        # searching every connected peer or block.
        self._download_peer_connections: Dict[int, PeerConnection] = {}
        self._download_request_owners: Dict[int, Dict[Tuple[int, int], Block]] = {}
        self._telemetry_task: Optional[asyncio.Task] = None
        self._main_task: Optional[asyncio.Task] = None
        self._prepare_cancel_event: Optional[threading.Event] = None
        self._prepare_pause_event: Optional[threading.Event] = None
        self._paused_from_state: Optional[str] = None

        self._seed_server: Optional[asyncio.AbstractServer] = None
        self._seed_servers: Dict[int, asyncio.AbstractServer] = {}
        self._seed_listener_addresses: Dict[int, str] = {}
        self._seed_client_writers: Set[asyncio.StreamWriter] = set()
        self._inbound_peer_records: Dict[int, dict] = {}
        self._seed_outbound_endpoints: Set[Tuple[str, int, str]] = set()
        self._download_endpoints: Set[Tuple[str, int, str]] = set()
        try:
            requested_listen_port = int(listen_port or 6881)
        except (TypeError, ValueError):
            requested_listen_port = 6881
        self.preferred_listen_port: int = max(1, min(65535, requested_listen_port))
        self._seed_port: int = self.preferred_listen_port
        self.enable_dht: bool = bool(enable_dht) and not self.torrent.private
        self.enable_pex: bool = bool(enable_pex) and not self.torrent.private
        # BEP-27 private torrents must not advertise their info hash through
        # non-tracker peer-discovery channels. Treat LAN/LPD the same way as
        # DHT and PEX so private swarm membership stays tracker-controlled.
        self.enable_lan_discovery: bool = (
            bool(enable_lan_discovery) and not self.torrent.private
        )
        self._listen_port_callback = listen_port_callback
        self._incoming_peer_callback = incoming_peer_callback

        self._lpd_by_generation = {
            generation: LocalPeerDiscovery(
                self.swarm_hashes[generation],
                bind_address=self.network_bind_address,
            )
            for generation in self.active_generations
        }
        self._dht_by_generation = {
            generation: DHTClient(
                self.swarm_hashes[generation],
                private=self.torrent.private or not self.enable_dht,
                preferred_port=self.preferred_listen_port,
                bind_address=self.network_bind_address,
            )
            for generation in self.active_generations
        }
        self._lpd = self._lpd_by_generation[self.active_generations[0]]
        self._dht = self._dht_by_generation[self.active_generations[0]]
        self.local_peers_discovered: int = 0
        self.error_message: str = ""

        # BEP-10/11 Peer Exchange telemetry and deduplication. PEX is disabled
        # for private torrents, matching the conventional private-torrent rule.
        self._pex_seen_endpoints: Set[Tuple[str, int, str]] = set()
        self._pex_last_at: float = 0.0
        self._pex_messages_received: int = 0
        self._pex_messages_sent: int = 0

        # Persisted cumulative upload total. Lightweight per-run counters below
        # are intentionally event-driven and are not written to resume state.
        self.uploaded_bytes: int = 0
        self.uploaded_this_session_bytes: int = 0
        self.upload_requests_received: int = 0
        self.upload_requests_served: int = 0
        self._last_upload_at: float = 0.0
        self.incoming_connections_total: int = 0
        self._seed_bind_address: str = ""

        # Rolling transfer-rate telemetry used by the Speed detail view.
        # History is intentionally session-local and bounded: 120 seconds at
        # the existing 0.5 second telemetry cadence is only ~240 samples.
        self._current_download_speed_kbps: float = 0.0
        self._current_upload_speed_kbps: float = 0.0
        self._speed_history: Deque[Tuple[float, float, float]] = deque(
            maxlen=SPEED_HISTORY_MAX_SAMPLES
        )
        self._speed_history.append((time.monotonic(), 0.0, 0.0))

        self._detail_telemetry_cached_at: float = 0.0
        self._piece_view_cache: dict = {}
        self._file_view_cache: dict = {}
        self._sources_view_cache: dict = {}

        # User-facing active elapsed-time telemetry. Time spent intentionally
        # paused/stopped/queued is not counted.
        self._elapsed_active_seconds: float = 0.0
        self._activity_started_at: Optional[float] = None

        # Seeding goals are per-torrent policy copied from application defaults
        # when a torrent is added, then persisted with the session. The dedicated
        # seeding clock excludes downloading, checking, pause, queue and stop time.
        self.seeding_goal_mode = normalise_seeding_goal_mode(seeding_goal_mode)
        self.seeding_ratio_limit = normalise_seeding_ratio(seeding_ratio_limit)
        self.seeding_time_limit_minutes = normalise_seeding_time_minutes(
            seeding_time_limit_minutes
        )
        try:
            self._seeding_elapsed_seconds = max(0.0, float(seeding_elapsed_seconds or 0.0))
        except (TypeError, ValueError):
            self._seeding_elapsed_seconds = 0.0
        try:
            baseline = max(0.0, float(seeding_time_goal_baseline_seconds or 0.0))
        except (TypeError, ValueError):
            baseline = 0.0
        self._seeding_time_goal_baseline_seconds = min(
            baseline, self._seeding_elapsed_seconds
        )

        supplied_components = (
            seeding_time_days,
            seeding_time_hours,
            seeding_time_minutes_component,
        )
        if all(value is None for value in supplied_components):
            derived = seeding_time_components_from_minutes(
                self.seeding_time_limit_minutes
            )
            supplied_components = derived or (0, 0, 0)
        self.seeding_time_days = normalise_seeding_time_component(
            "days", supplied_components[0]
        )
        self.seeding_time_hours = normalise_seeding_time_component(
            "hours", supplied_components[1]
        )
        self.seeding_time_minutes_component = normalise_seeding_time_component(
            "minutes", supplied_components[2]
        )

        self._seeding_started_at: Optional[float] = None
        self._seeding_goal_callback = seeding_goal_callback
        self._seeding_goal_notified = False
        self._seeding_goal_last_reason = ""

        # Per-torrent transfer limits. The user-facing value/unit pair is kept
        # alongside canonical bytes-per-second values so the GUI can restore
        # exactly what the user entered when switching between torrents.
        self.download_limit_value: float = 0.0
        self.download_limit_unit: str = "KB/s"
        self.upload_limit_value: float = 0.0
        self.upload_limit_unit: str = "KB/s"
        self.download_limit_bps: int = 0
        self.upload_limit_bps: int = 0
        self._download_limiter = AsyncBandwidthLimiter()
        self._upload_limiter = AsyncBandwidthLimiter()
        # Manager-owned limiters are shared across every torrent session and
        # therefore implement *true aggregate* application bandwidth limits.
        self._global_download_limiter = global_download_limiter
        self._global_upload_limiter = global_upload_limiter

        self.state = SessionState.IDLE
        self.is_running = False

        # Torrent-level queue priority. The manager combines this with the
        # visible Move Up / Move Down order when choosing the next queued
        # download to start. Seeding is not limited by download queue slots.
        self.queue_priority: str = TORRENT_PRIORITY_NORMAL

        self._pause_event = asyncio.Event()
        self._pause_event.set()

        # Old asynchronous work is prevented from overwriting a newer run.
        self._run_token = 0
        self._fast_resume_notice_shown = False

    def _normalise_generation(self, generation: object = None) -> str:
        value = str(generation or self.active_generations[0]).strip().lower()
        return value if value in self.active_generations else self.active_generations[0]

    def _tracker_for_generation(self, generation: object = None) -> TrackerClient:
        return self._trackers_by_generation[self._normalise_generation(generation)]

    def _dht_for_generation(self, generation: object = None) -> DHTClient:
        return self._dht_by_generation[self._normalise_generation(generation)]

    def _lpd_for_generation(self, generation: object = None) -> LocalPeerDiscovery:
        return self._lpd_by_generation[self._normalise_generation(generation)]

    def _peer_connection_for_generation(
        self,
        ip: str,
        port: int,
        *,
        generation: object = None,
        source: str = "Unknown",
        direction: str = "Outgoing",
    ) -> PeerConnection:
        generation = self._normalise_generation(generation)
        return PeerConnection(
            ip,
            port,
            self.swarm_hashes[generation],
            self.peer_id,
            source=source,
            direction=direction,
            advertise_dht=self.enable_dht,
            enable_pex=self.enable_pex,
            encryption_policy=self.encryption_policy,
            bind_address=self.network_bind_address,
            v1_info_hash=self.torrent.v1_info_hash,
            v2_info_hash=self.torrent.v2_info_hash,
            protocol_generation=generation,
        )

    def _v2_hash_response(self, request: object) -> Optional[dict]:
        """Return a safe piece-layer HASHES response or ``None`` for reject.

        Phase 9 needs the BEP-52 piece layer for v2 magnet completion. The
        top-level .torrent already contains these hashes for normal torrent
        adds, so serving that validated layer is enough to bootstrap btmh
        metadata without re-hashing payload data on the network event loop.
        """
        if not self.torrent.is_v2 or not isinstance(request, dict):
            return None
        try:
            root = bytes(request.get("pieces_root", b""))
            base_layer = int(request.get("base_layer", -1))
            index = int(request.get("index", -1))
            length = int(request.get("length", 0))
            proof_layers = int(request.get("proof_layers", -1))
        except (TypeError, ValueError):
            return None
        if (
            len(root) != 32
            or index < 0
            or length < 2
            or length > 512
            or (length & (length - 1))
            or index % length
        ):
            return None
        if proof_layers != 0 or base_layer != piece_layer_depth(self.torrent.piece_length):
            return None

        file_entry = next(
            (entry for entry in self.torrent.v2_files if bytes(entry.get("pieces_root", b"")) == root),
            None,
        )
        if file_entry is None:
            return None
        count = expected_piece_layer_count(int(file_entry.get("length", 0)), self.torrent.piece_length)
        if count <= 0 or index >= count:
            return None
        if count == 1:
            hashes = [root]
        else:
            hashes = list(self.torrent.v2_piece_layers.get(root, ()))
        if len(hashes) != count:
            return None
        selected = list(hashes[index:min(count, index + length)])
        if not selected:
            return None
        if len(selected) < length:
            selected.extend([zero_hash(base_layer)] * (length - len(selected)))
        return {
            "pieces_root": root,
            "base_layer": base_layer,
            "index": index,
            "length": length,
            "proof_layers": 0,
            "hashes": selected,
        }

    async def _serve_peer_hash_request(self, peer: PeerConnection, request: object):
        response = self._v2_hash_response(request)
        if response is None:
            if isinstance(request, dict):
                await peer.send_hash_reject(
                    request.get("pieces_root", b""),
                    request.get("base_layer", 0),
                    request.get("index", 0),
                    request.get("length", 0),
                    request.get("proof_layers", 0),
                )
            return
        await peer.send_hashes(
            response["pieces_root"],
            response["base_layer"],
            response["index"],
            response["length"],
            response["proof_layers"],
            response["hashes"],
        )

    def _begin_activity_clock(self):
        if self._activity_started_at is None:
            self._activity_started_at = time.monotonic()

    def _pause_activity_clock(self):
        if self._activity_started_at is None:
            return
        self._elapsed_active_seconds += max(
            0.0, time.monotonic() - self._activity_started_at
        )
        self._activity_started_at = None

    @property
    def elapsed_active_seconds(self) -> float:
        elapsed = self._elapsed_active_seconds
        if self._activity_started_at is not None:
            elapsed += max(0.0, time.monotonic() - self._activity_started_at)
        return elapsed

    def _begin_seeding_clock(self):
        if self._seeding_started_at is None:
            self._seeding_started_at = time.monotonic()

    def _pause_seeding_clock(self):
        if self._seeding_started_at is None:
            return
        self._seeding_elapsed_seconds += max(
            0.0, time.monotonic() - self._seeding_started_at
        )
        self._seeding_started_at = None

    @property
    def seeding_elapsed_seconds(self) -> float:
        elapsed = self._seeding_elapsed_seconds
        if self._seeding_started_at is not None:
            elapsed += max(0.0, time.monotonic() - self._seeding_started_at)
        return elapsed

    @property
    def seeding_time_goal_baseline_seconds(self) -> float:
        return min(
            max(0.0, self._seeding_time_goal_baseline_seconds),
            self.seeding_elapsed_seconds,
        )

    @property
    def seeding_goal_elapsed_seconds(self) -> float:
        return max(
            0.0,
            self.seeding_elapsed_seconds - self.seeding_time_goal_baseline_seconds,
        )

    @property
    def seeding_time_components(self) -> tuple[int, int, int]:
        return (
            int(self.seeding_time_days),
            int(self.seeding_time_hours),
            int(self.seeding_time_minutes_component),
        )

    def seeding_goal_status(self):
        return evaluate_seeding_goal(
            self.seeding_goal_mode,
            self.seeding_ratio_limit,
            self.seeding_time_limit_minutes,
            uploaded_bytes=self.uploaded_bytes,
            payload_bytes=self.torrent.total_length,
            elapsed_seconds=self.seeding_elapsed_seconds,
            time_baseline_seconds=self.seeding_time_goal_baseline_seconds,
        )

    def set_seeding_goal(
        self,
        mode: object,
        ratio_limit: object,
        time_limit_minutes: object,
        *,
        time_components: Optional[tuple[object, object, object]] = None,
        restart_time_window: bool = False,
        emit: bool = True,
    ) -> bool:
        normalized_mode = normalise_seeding_goal_mode(mode)
        normalized_ratio = normalise_seeding_ratio(ratio_limit)
        normalized_time = normalise_seeding_time_minutes(time_limit_minutes)

        if time_components is None:
            if normalized_time != self.seeding_time_limit_minutes:
                derived = seeding_time_components_from_minutes(normalized_time)
                normalized_components = derived or (0, 0, 0)
            else:
                normalized_components = self.seeding_time_components
        else:
            normalized_components = (
                normalise_seeding_time_component("days", time_components[0]),
                normalise_seeding_time_component("hours", time_components[1]),
                normalise_seeding_time_component("minutes", time_components[2]),
            )
            component_minutes = seeding_time_components_to_minutes(
                *normalized_components
            )
            if component_minutes > 0:
                normalized_time = normalise_seeding_time_minutes(component_minutes)

        new_baseline = self.seeding_time_goal_baseline_seconds
        if restart_time_window and seeding_goal_uses_time(normalized_mode):
            # Snapshot cumulative seed time now. The timed policy counts only
            # seeding performed after this explicit user action.
            new_baseline = self.seeding_elapsed_seconds

        changed = (
            normalized_mode != self.seeding_goal_mode
            or normalized_ratio != self.seeding_ratio_limit
            or normalized_time != self.seeding_time_limit_minutes
            or tuple(normalized_components) != self.seeding_time_components
            or new_baseline != self.seeding_time_goal_baseline_seconds
        )
        self.seeding_goal_mode = normalized_mode
        self.seeding_ratio_limit = normalized_ratio
        self.seeding_time_limit_minutes = normalized_time
        (
            self.seeding_time_days,
            self.seeding_time_hours,
            self.seeding_time_minutes_component,
        ) = normalized_components
        self._seeding_time_goal_baseline_seconds = new_baseline
        self._seeding_goal_notified = False
        self._seeding_goal_last_reason = ""
        if emit:
            self._emit_snapshot()
        if self.state == SessionState.SEEDING:
            self._check_seeding_goal()
        return changed

    def _check_seeding_goal(self) -> bool:
        if self.state != SessionState.SEEDING or self._seeding_goal_notified:
            return False
        status = self.seeding_goal_status()
        if not status.reached:
            return False

        self._seeding_goal_notified = True
        self._seeding_goal_last_reason = status.reason
        self._emit_snapshot()
        if self._seeding_goal_callback is not None:
            try:
                self._seeding_goal_callback(self.torrent.hex_info_hash, status.reason)
            except Exception:
                pass
        return True

    def emit_snapshot(self):
        self._emit_snapshot()

    def _record_upload_request(self):
        """Record one valid peer-wire REQUEST without any polling/scanning."""
        self.upload_requests_received += 1

    def _record_upload_served(self, byte_count: int):
        """Record a successfully transmitted PIECE payload in O(1) time."""
        try:
            byte_count = max(0, int(byte_count))
        except (TypeError, ValueError):
            byte_count = 0
        if byte_count <= 0:
            return
        self.uploaded_bytes += byte_count
        self.uploaded_this_session_bytes += byte_count
        self.upload_requests_served += 1
        self._last_upload_at = time.monotonic()

    def set_transfer_limits(
        self,
        download_value: float,
        download_unit: str,
        upload_value: float,
        upload_unit: str,
    ):
        """Apply live per-torrent download and upload limits."""
        if download_unit not in RATE_UNIT_MULTIPLIERS:
            download_unit = "KB/s"
        if upload_unit not in RATE_UNIT_MULTIPLIERS:
            upload_unit = "KB/s"

        try:
            download_value = max(0.0, float(download_value))
        except (TypeError, ValueError):
            download_value = 0.0

        try:
            upload_value = max(0.0, float(upload_value))
        except (TypeError, ValueError):
            upload_value = 0.0

        self.download_limit_value = download_value
        self.download_limit_unit = download_unit
        self.upload_limit_value = upload_value
        self.upload_limit_unit = upload_unit

        self.download_limit_bps = _rate_to_bps(download_value, download_unit)
        self.upload_limit_bps = _rate_to_bps(upload_value, upload_unit)

        self._download_limiter.set_rate(self.download_limit_bps)
        self._upload_limiter.set_rate(self.upload_limit_bps)
        self._emit_snapshot()

    async def apply_runtime_preferences(
        self,
        *,
        listen_port: int,
        enable_dht: bool,
        enable_pex: bool,
        enable_lan_discovery: bool,
        encryption_policy: str = PEER_ENCRYPTION_PREFER,
        network_bind_address: str = "",
        interface_lock: bool = False,
        mask_peer_ips: bool = False,
    ):
        """Apply networking/privacy preferences to a live session.

        DHT/LPD and PEX can be toggled live. A listen-port change rebinds the
        incoming listener. Changing the selected network path or peer-encryption
        policy closes existing torrent sockets so new connections cannot retain
        the previous routing or transport policy.
        """
        try:
            port = int(listen_port or 6881)
        except (TypeError, ValueError):
            port = 6881
        port = max(1, min(65535, port))

        new_encryption_policy = normalise_peer_encryption_policy(encryption_policy)
        new_bind_address = normalise_bind_address(network_bind_address)
        port_changed = port != self.preferred_listen_port
        bind_changed = new_bind_address != self.network_bind_address
        encryption_changed = new_encryption_policy != self.encryption_policy

        self.preferred_listen_port = port
        self.enable_dht = bool(enable_dht) and not self.torrent.private
        self.enable_pex = bool(enable_pex) and not self.torrent.private
        self.enable_lan_discovery = bool(enable_lan_discovery) and not self.torrent.private
        self.encryption_policy = new_encryption_policy
        self.network_bind_address = new_bind_address
        self.interface_lock = bool(interface_lock)
        self.mask_peer_ips = bool(mask_peer_ips)

        for tracker in self._trackers_by_generation.values():
            tracker.set_bind_address(self.network_bind_address)
            tracker.set_encryption_policy(self.encryption_policy)
        for lpd in self._lpd_by_generation.values():
            lpd.set_bind_address(self.network_bind_address)
        for dht in self._dht_by_generation.values():
            dht.set_bind_address(self.network_bind_address)
            # DHT's private flag is also used as its hard-disable switch.
            dht.private = bool(self.torrent.private or not self.enable_dht)
            dht.set_preferred_port(self.preferred_listen_port)

        for peer in list(self.active_peers):
            peer.enable_pex = self.enable_pex
            peer.advertise_dht = self.enable_dht

        if (
            self.interface_lock
            and self.network_bind_address
            and not is_bind_address_available(self.network_bind_address)
        ):
            await self._trip_interface_lock()
            return

        # Existing TCP/UDP sockets cannot be rebound in place. Close them when
        # the selected path or peer-encryption policy changes so subsequent
        # discovery/worker activity uses the new policy rather than leaking over
        # the old interface.
        if bind_changed or encryption_changed:
            for peer in list(self.active_peers):
                await peer.close()
            for writer in list(self._seed_client_writers):
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
            self._seed_client_writers.clear()
            self._inbound_peer_records.clear()
            self.piece_mgr.clear_peer_availability()
            await self._close_seed_server()
            for lpd in self._lpd_by_generation.values():
                await lpd.close()
            for dht in self._dht_by_generation.values():
                await dht.close()

        if not self.enable_lan_discovery:
            for lpd in self._lpd_by_generation.values():
                await lpd.close()
        elif self.is_running and self.state in (SessionState.DOWNLOADING, SessionState.SEEDING):
            for lpd in self._lpd_by_generation.values():
                await lpd.start(listen_port=self._seed_port)

        if not self.enable_dht:
            for dht in self._dht_by_generation.values():
                await dht.close()
                dht.status = "Disabled"
                dht.last_error = "Disabled in Preferences"
        elif self.is_running and self.state in (SessionState.DOWNLOADING, SessionState.SEEDING):
            for dht in self._dht_by_generation.values():
                await dht.start(announce_port=self._seed_port)

        if (
            (port_changed or bind_changed or encryption_changed)
            and self.is_running
            and self.state in (SessionState.DOWNLOADING, SessionState.SEEDING)
        ):
            await self._close_seed_server()
            await self._open_seed_server(self._run_token)
            if self.enable_lan_discovery:
                for lpd in self._lpd_by_generation.values():
                    lpd.update_listen_port(self._seed_port)
            if self.enable_dht:
                for dht in self._dht_by_generation.values():
                    dht.update_announce_port(self._seed_port)

        self._detail_telemetry_cached_at = 0.0
        self._emit_snapshot(force_detail_refresh=True)

    def set_queue_priority(self, priority: object, emit: bool = True) -> bool:
        """Set this torrent's queue priority (High / Normal / Low)."""
        value = str(priority or TORRENT_PRIORITY_NORMAL).strip().title()
        if value not in TORRENT_PRIORITIES:
            value = TORRENT_PRIORITY_NORMAL

        if self.queue_priority == value:
            return False

        self.queue_priority = value
        if emit:
            self._emit_snapshot()
        return True

    def mark_queued(self):
        """Show that an ACTIVE torrent is waiting for a download slot.

        A user-resumed paused coroutine can remain alive while queued; its
        pause events stay cleared, so it consumes no download bandwidth until
        the queue scheduler promotes it again. Fresh/stopped torrents simply
        wait in the Queued state without creating network tasks.
        """
        if self.state == SessionState.QUEUED:
            return

        if self.state == SessionState.PAUSED and self.is_running:
            # pause() already cleared the relevant events. Keep
            # _paused_from_state so promotion can continue the same operation.
            self.state = SessionState.QUEUED
        elif not self.is_running:
            self.state = SessionState.QUEUED
        else:
            # Never pre-empt a currently active download just because the user
            # moved another item above it. Queue ordering controls who starts
            # next when a slot becomes free.
            return

        self._record_speed_sample(0.0, 0.0)
        self._emit_snapshot()

    def resume_from_queue(self) -> bool:
        """Resume a still-alive paused coroutine promoted from the queue."""
        if self.state != SessionState.QUEUED or not self.is_running:
            return False

        resume_state = self._paused_from_state or SessionState.DOWNLOADING
        self._paused_from_state = None
        self.state = resume_state

        if resume_state == SessionState.CHECKING and self._prepare_pause_event:
            self._prepare_pause_event.set()

        self._pause_event.set()
        self._begin_activity_clock()
        self._emit_snapshot()
        return True

    def set_file_priority(self, file_index: int, priority: object) -> bool:
        """Apply one file priority live and refresh the selected-torrent views."""
        changed = self.piece_mgr.set_file_priority(file_index, priority)
        if not changed:
            return False

        # A torrent may have previously completed only its selected files. If a
        # skipped file becomes wanted again, expose it as startable work.
        if (
            self.state == SessionState.COMPLETED
            and not self.piece_mgr.is_finished
            and not self.piece_mgr.wanted_is_finished
        ):
            self.state = SessionState.STOPPED

        self._emit_snapshot()
        return True

    def set_file_priorities(self, priorities: object, emit: bool = True) -> bool:
        changed = self.piece_mgr.set_file_priorities(priorities)
        if changed and emit:
            self._emit_snapshot()
        return changed

    def pause(self):
        if self.state not in (
            SessionState.CHECKING,
            SessionState.DOWNLOADING,
            SessionState.SEEDING,
        ):
            return

        self._paused_from_state = self.state
        self.state = SessionState.PAUSED
        self._pause_event.clear()

        if (
            self._paused_from_state == SessionState.CHECKING
            and self._prepare_pause_event
        ):
            self._prepare_pause_event.clear()

        self._pause_activity_clock()
        if self._paused_from_state == SessionState.SEEDING:
            self._pause_seeding_clock()
        self._record_speed_sample(0.0, 0.0)
        self._emit_snapshot()

    def resume(self):
        if self.state != SessionState.PAUSED:
            return

        resume_state = self._paused_from_state or SessionState.DOWNLOADING
        self._paused_from_state = None
        self.state = resume_state

        if resume_state == SessionState.CHECKING and self._prepare_pause_event:
            self._prepare_pause_event.set()

        self._pause_event.set()
        self._begin_activity_clock()
        if resume_state == SessionState.SEEDING:
            self._begin_seeding_clock()
        self._emit_snapshot()

    def stop(self):
        # Best-effort tracker notification. This is intentionally detached from
        # the main session task so Stop itself remains immediate.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self.tracker.announce(
                    uploaded=self.uploaded_bytes,
                    downloaded=self.piece_mgr.downloaded_bytes,
                    left=max(0, self.torrent.total_length - self.piece_mgr.downloaded_bytes),
                    event="stopped",
                )
            )
        except RuntimeError:
            pass

        self._run_token += 1
        self.state = SessionState.STOPPED
        self.is_running = False
        self._paused_from_state = None
        self._pause_event.set()

        if self._prepare_cancel_event:
            self._prepare_cancel_event.set()
        if self._prepare_pause_event:
            self._prepare_pause_event.set()

        current_task = asyncio.current_task()
        if (
            self._main_task
            and self._main_task is not current_task
            and not self._main_task.done()
        ):
            self._main_task.cancel()

        if self._telemetry_task and not self._telemetry_task.done():
            self._telemetry_task.cancel()

        for task in list(self._worker_tasks):
            if not task.done():
                task.cancel()

        for server in list(self._seed_servers.values()):
            server.close()

        for writer in list(self._seed_client_writers):
            try:
                writer.close()
            except Exception:
                pass

        for peer in list(self.active_peers):
            if peer.writer:
                try:
                    peer.writer.close()
                except Exception:
                    pass

        # Present Stop as an immediate terminal UI state. The cancelled worker
        # tasks still own and close their sockets in their finally blocks, but
        # the peer list should not continue displaying stale connections while
        # that asynchronous cleanup finishes.
        self.active_peers.clear()
        self._seed_client_writers.clear()
        self._inbound_peer_records.clear()
        self.piece_mgr.clear_peer_availability()

        self.piece_mgr.reset_inflight_requests()
        self.piece_mgr.save_resume_state(force=True)
        self._pause_activity_clock()
        self._pause_seeding_clock()
        self._record_speed_sample(0.0, 0.0)
        self._emit_snapshot()

    async def manual_announce(self) -> int:
        """Ask every active generation's trackers for fresh peers."""
        if self.state not in (SessionState.DOWNLOADING, SessionState.SEEDING):
            return 0

        downloaded = self.piece_mgr.downloaded_bytes
        left = max(0, self.torrent.total_length - downloaded)
        results: list[tuple[str, list[tuple[str, int]]]] = []
        for generation in self.active_generations:
            tracker = self._trackers_by_generation[generation]
            try:
                peers = await tracker.announce(
                    uploaded=self.uploaded_bytes,
                    downloaded=downloaded,
                    left=left,
                    event=None,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                peers = []
            results.append((generation, peers))

        total = 0
        for generation, peers in results:
            total += len(peers)
            if self.state == SessionState.DOWNLOADING:
                self._start_download_workers(
                    self._run_token, peers, source="Tracker", generation=generation
                )
            elif self.state == SessionState.SEEDING:
                self._start_outbound_seed_workers(
                    self._run_token, peers, source="Tracker", generation=generation
                )
        self._emit_snapshot()
        return total

    async def force_recheck(self) -> bool:
        """Hash existing payload data after fast-resume state is invalidated.

        This performs only the disk verification phase. The manager decides
        whether an active torrent should be started again afterward.
        """
        if self.is_running:
            return False

        self._run_token += 1
        run_token = self._run_token
        self.is_running = True
        self._main_task = asyncio.current_task()
        self._prepare_cancel_event = threading.Event()
        self._prepare_pause_event = threading.Event()
        self._prepare_pause_event.set()
        self._paused_from_state = None
        self.error_message = ""
        self.state = SessionState.CHECKING
        self._begin_activity_clock()
        self._emit_snapshot()

        success = False
        try:
            success = await asyncio.to_thread(
                self.piece_mgr.prepare_storage,
                self._prepare_cancel_event,
                self._emit_snapshot,
                self._prepare_pause_event,
            )
            if not self._is_current_run(run_token):
                return False

            if success:
                self.state = SessionState.STOPPED
                self.error_message = ""
            else:
                self.state = SessionState.ERROR
                self.error_message = (
                    self.piece_mgr.last_error or "Force recheck did not complete."
                )
            self._emit_snapshot()
            return success
        except asyncio.CancelledError:
            return False
        except Exception as exc:
            if run_token == self._run_token:
                self.state = SessionState.ERROR
                self.error_message = f"Force recheck failed: {exc}"
                self._emit_snapshot()
            return False
        finally:
            if run_token == self._run_token:
                self.is_running = False
                self._pause_activity_clock()
            if self._main_task is asyncio.current_task():
                self._main_task = None

    def _is_current_run(self, run_token: int) -> bool:
        return self.is_running and run_token == self._run_token

    def _state_label(self) -> str:
        check_percent = self.piece_mgr.check_progress * 100.0

        if self.state == SessionState.CHECKING:
            return f"Checking {check_percent:.0f}%"

        if self.state == SessionState.PAUSED:
            if self._paused_from_state == SessionState.CHECKING:
                return f"Paused (Checking {check_percent:.0f}%)"
            if self._paused_from_state:
                return f"Paused ({self._paused_from_state})"

        if (
            self.state == SessionState.COMPLETED
            and not self.piece_mgr.is_finished
            and self.piece_mgr.wanted_is_finished
        ):
            return "Completed (Selected Files)"

        return self.state

    def _connected_peer_count(self) -> int:
        return len(self.active_peers) + len(self._seed_client_writers)

    def _display_peer_ip(self, value: object) -> str:
        text = str(value or "?")
        return mask_ip_for_display(text) if self.mask_peer_ips else text

    @staticmethod
    def _bitfield_progress(bitfield: bytes, total_pieces: int) -> Optional[float]:
        if not bitfield or total_pieces <= 0:
            return None

        have_count = 0
        for piece_index in range(total_pieces):
            byte_index = piece_index // 8
            if byte_index >= len(bitfield):
                break
            bit_index = 7 - (piece_index % 8)
            if bitfield[byte_index] & (1 << bit_index):
                have_count += 1

        return have_count / total_pieces

    def _apply_have_to_peer(self, peer: PeerConnection, piece_index: int):
        total_pieces = len(self.piece_mgr.pieces)
        if piece_index < 0 or piece_index >= total_pieces:
            return

        self.piece_mgr.record_peer_have(id(peer), piece_index)

        needed_bytes = (total_pieces + 7) // 8
        if len(peer.bitfield) < needed_bytes:
            peer.bitfield.extend(b"\x00" * (needed_bytes - len(peer.bitfield)))

        byte_index = piece_index // 8
        bit_index = 7 - (piece_index % 8)
        peer.bitfield[byte_index] |= 1 << bit_index

    @staticmethod
    def _peer_flags(
        am_interested: bool,
        peer_interested: bool,
        peer_choking: bool,
        am_choking: bool,
    ) -> str:
        flags = []
        if am_interested:
            flags.append("I")
        if peer_interested:
            flags.append("i")
        if peer_choking:
            flags.append("C")
        if am_choking:
            flags.append("c")
        return " ".join(flags) if flags else "--"

    def _peer_state_label(
        self,
        *,
        am_interested: bool,
        peer_interested: bool,
        peer_choking: bool,
        am_choking: bool,
        down_kbps: float,
        up_kbps: float,
    ) -> str:
        if self.state == SessionState.DOWNLOADING:
            if down_kbps > 0.01:
                return "Downloading"
            if peer_choking:
                return "Choked"
            if am_interested:
                return "Ready"
            return "Connected"

        if self.state == SessionState.SEEDING:
            if up_kbps > 0.01:
                return "Uploading"
            if am_choking:
                return "Choking"
            if peer_interested:
                return "Ready"
            return "Connected"

        return "Connected"

    def _build_peer_snapshots(self) -> List[dict]:
        now = time.monotonic()
        total_pieces = len(self.piece_mgr.pieces)
        peers: List[dict] = []

        for peer in list(self.active_peers):
            progress = self._bitfield_progress(peer.bitfield, total_pieces)
            display_ip = self._display_peer_ip(peer.ip)
            down_kbps = float(getattr(peer, "download_speed_kbps", 0.0))
            up_kbps = float(getattr(peer, "upload_speed_kbps", 0.0))
            connected_at = float(getattr(peer, "connected_at", 0.0) or now)

            peers.append({
                "connection_id": f"out:{id(peer)}",
                "ip": display_ip,
                "port": int(peer.port),
                "address": (
                    f"[{display_ip}]:{peer.port}"
                    if ip_family(peer.ip) == socket.AF_INET6
                    else format_endpoint(display_ip, peer.port)
                ),
                "ip_family": "IPv6" if ip_family(peer.ip) == socket.AF_INET6 else "IPv4",
                "client": peer.client_name,
                "transport_security": str(getattr(peer, "transport_security", "Plaintext")),
                "protocol_generation": self._normalise_generation(getattr(peer, "protocol_generation", None)),
                "source": str(getattr(peer, "source", "Unknown")),
                "direction": str(getattr(peer, "direction", "Outgoing")),
                "progress": progress,
                "download_speed_kbps": down_kbps,
                "upload_speed_kbps": up_kbps,
                "downloaded_bytes": int(getattr(peer, "downloaded_bytes", 0)),
                "uploaded_bytes": int(getattr(peer, "uploaded_bytes", 0)),
                "state": self._peer_state_label(
                    am_interested=bool(peer.am_interested),
                    peer_interested=bool(peer.peer_interested),
                    peer_choking=bool(peer.peer_choking),
                    am_choking=bool(peer.am_choking),
                    down_kbps=down_kbps,
                    up_kbps=up_kbps,
                ),
                "flags": self._peer_flags(
                    bool(peer.am_interested),
                    bool(peer.peer_interested),
                    bool(peer.peer_choking),
                    bool(peer.am_choking),
                ),
                "connected_seconds": max(0.0, now - connected_at),
            })

        for record in list(self._inbound_peer_records.values()):
            bitfield = record.get("bitfield", bytearray())
            progress = self._bitfield_progress(bitfield, total_pieces)
            display_ip = self._display_peer_ip(record.get("ip", "?"))
            down_kbps = float(record.get("download_speed_kbps", 0.0))
            up_kbps = float(record.get("upload_speed_kbps", 0.0))
            connected_at = float(record.get("connected_at", now))
            am_interested = bool(record.get("am_interested", False))
            peer_interested = bool(record.get("peer_interested", False))
            peer_choking = bool(record.get("peer_choking", True))
            am_choking = bool(record.get("am_choking", False))

            peers.append({
                "connection_id": str(record.get("connection_id", "")),
                "ip": display_ip,
                "port": int(record.get("port", 0) or 0),
                "address": (
                    f"[{display_ip}]:{int(record.get('port', 0) or 0)}"
                    if ip_family(record.get("ip", "")) == socket.AF_INET6 and int(record.get("port", 0) or 0)
                    else format_endpoint(display_ip, int(record.get("port", 0) or 0))
                ),
                "ip_family": "IPv6" if ip_family(record.get("ip", "")) == socket.AF_INET6 else "IPv4",
                "client": str(record.get("client", "Unknown")),
                "transport_security": str(record.get("transport_security", "Plaintext")),
                "protocol_generation": self._normalise_generation(record.get("protocol_generation")),
                "source": str(record.get("source", "Incoming")),
                "direction": str(record.get("direction", "Incoming")),
                "progress": progress,
                "download_speed_kbps": down_kbps,
                "upload_speed_kbps": up_kbps,
                "downloaded_bytes": int(record.get("downloaded_bytes", 0)),
                "uploaded_bytes": int(record.get("uploaded_bytes", 0)),
                "state": self._peer_state_label(
                    am_interested=am_interested,
                    peer_interested=peer_interested,
                    peer_choking=peer_choking,
                    am_choking=am_choking,
                    down_kbps=down_kbps,
                    up_kbps=up_kbps,
                ),
                "flags": self._peer_flags(
                    am_interested,
                    peer_interested,
                    peer_choking,
                    am_choking,
                ),
                "connected_seconds": max(0.0, now - connected_at),
            })

        peers.sort(key=lambda item: (item.get("direction", ""), item.get("address", "")))
        return peers

    def _sample_peer_speeds(self, interval_seconds: float):
        if interval_seconds <= 0:
            return

        for peer in list(self.active_peers):
            downloaded = int(getattr(peer, "downloaded_bytes", 0))
            uploaded = int(getattr(peer, "uploaded_bytes", 0))
            last_downloaded = int(getattr(peer, "_last_sample_downloaded", 0))
            last_uploaded = int(getattr(peer, "_last_sample_uploaded", 0))

            peer.download_speed_kbps = max(
                0.0,
                (downloaded - last_downloaded) / interval_seconds / 1024.0,
            )
            peer.upload_speed_kbps = max(
                0.0,
                (uploaded - last_uploaded) / interval_seconds / 1024.0,
            )
            peer._last_sample_downloaded = downloaded
            peer._last_sample_uploaded = uploaded

        for record in list(self._inbound_peer_records.values()):
            downloaded = int(record.get("downloaded_bytes", 0))
            uploaded = int(record.get("uploaded_bytes", 0))
            last_downloaded = int(record.get("_last_sample_downloaded", 0))
            last_uploaded = int(record.get("_last_sample_uploaded", 0))

            record["download_speed_kbps"] = max(
                0.0,
                (downloaded - last_downloaded) / interval_seconds / 1024.0,
            )
            record["upload_speed_kbps"] = max(
                0.0,
                (uploaded - last_uploaded) / interval_seconds / 1024.0,
            )
            record["_last_sample_downloaded"] = downloaded
            record["_last_sample_uploaded"] = uploaded

    def _build_piece_view_snapshot(self) -> dict:
        return self.piece_mgr.build_piece_telemetry(
            detail_limit=80,
            map_cell_limit=384,
        )

    def _build_file_view_snapshot(self) -> dict:
        return self.piece_mgr.build_file_telemetry(detail_limit=250)

    def _cached_detail_snapshots(self, force: bool = False):
        now = time.monotonic()
        if (
            force
            or not self._piece_view_cache
            or now - self._detail_telemetry_cached_at >= DETAIL_TELEMETRY_INTERVAL
        ):
            self._piece_view_cache = self._build_piece_view_snapshot()
            self._file_view_cache = self._build_file_view_snapshot()
            self._sources_view_cache = self._build_sources_view_snapshot()
            self._detail_telemetry_cached_at = now

        return (
            self._piece_view_cache,
            self._file_view_cache,
            self._sources_view_cache,
        )

    def apply_tracker_scrape_result(
        self,
        tracker_url: str,
        result: dict,
        *,
        generation: Optional[str] = None,
    ):
        """Apply cached scrape telemetry to one generation-aware tracker."""
        tracker = self._tracker_for_generation(generation)
        tracker.apply_scrape_result(tracker_url, result)
        self._detail_telemetry_cached_at = 0.0

    def _build_pex_source_snapshot(self) -> dict:
        now = time.monotonic()
        if self.torrent.private:
            status = "Disabled"
            detail = "Private torrent: BEP-10/11 PEX disabled"
        elif not self.enable_pex:
            status = "Disabled"
            detail = "Disabled in Preferences"
        else:
            compatible = sum(1 for peer in self.active_peers if peer.pex_supported)
            compatible += sum(
                1
                for record in self._inbound_peer_records.values()
                if bool(record.get("pex_supported", False))
            )
            if self.state not in (SessionState.DOWNLOADING, SessionState.SEEDING):
                status = "Disabled"
            elif self._pex_messages_received or compatible:
                status = "Active"
            else:
                status = "Waiting"
            detail = (
                f"BEP-10/11 | compatible {compatible} | "
                f"rx {self._pex_messages_received} | tx {self._pex_messages_sent}"
            )

        return {
            "id": "pex",
            "source": "Peer Exchange",
            "type": "PEX",
            "status": status,
            "peers": len(self._pex_seen_endpoints),
            "seeders": None,
            "leechers": None,
            "interval": int(PEX_SEND_INTERVAL),
            "response_ms": None,
            "last_error": "",
            "last_event": "ut_pex",
            "query_count": int(self._pex_messages_received + self._pex_messages_sent),
            "last_update_seconds": (
                max(0.0, now - self._pex_last_at) if self._pex_last_at else None
            ),
            "last_success_seconds": (
                max(0.0, now - self._pex_last_at) if self._pex_last_at else None
            ),
            "detail": detail,
        }

    def _build_sources_view_snapshot(self) -> dict:
        tracker_sources: List[dict] = []
        dht_sources: List[dict] = []
        lan_sources: List[dict] = []

        for generation in self.active_generations:
            tracker = self._trackers_by_generation[generation]
            for source in tracker.get_source_snapshots():
                item = dict(source)
                item["generation"] = generation
                item["id"] = f"{item.get('id', item.get('source', 'tracker'))}:{generation}"
                item["source"] = f"{item.get('source', 'Tracker')} ({generation})"
                tracker_sources.append(item)

            dht = self._dht_by_generation[generation]
            dht_source = dict(dht.get_source_snapshot())
            dht_source["generation"] = generation
            dht_source["id"] = f"dht:{generation}"
            dht_source["source"] = f"DHT ({generation})"
            if not self.enable_dht and not self.torrent.private:
                dht_source.update(
                    status="Disabled",
                    last_error="Disabled in Preferences",
                    detail="Disabled in Preferences",
                )
            dht_sources.append(dht_source)

            lpd = self._lpd_by_generation[generation]
            lan_source = dict(lpd.get_source_snapshot())
            lan_source["generation"] = generation
            lan_source["id"] = f"lan:{generation}"
            lan_source["source"] = f"LAN Discovery ({generation})"
            if not self.enable_lan_discovery:
                lan_source.update(
                    status="Disabled",
                    last_error="Disabled in Preferences",
                    detail="Disabled in Preferences",
                )
            lan_sources.append(lan_source)

        pex_source = self._build_pex_source_snapshot()
        sources = list(tracker_sources) + dht_sources + [pex_source] + lan_sources

        active_statuses = {"Active", "No Peers"}
        pending_statuses = {"Waiting", "Announcing"}
        warning_statuses = {"Timeout"}
        error_statuses = {"Error", "Unsupported"}
        active_count = 0
        pending_count = 0
        warning_count = 0
        error_count = 0
        tracker_peer_count = 0
        scrape_active_count = 0
        scrape_pending_count = 0
        scrape_warning_count = 0
        scrape_error_count = 0
        freshest_scrape = None

        tracker_count = len(tracker_sources)
        for index, source in enumerate(sources):
            status = str(source.get("status", ""))
            if status in active_statuses:
                active_count += 1
            elif status in pending_statuses:
                pending_count += 1
            elif status in warning_statuses:
                warning_count += 1
            elif status in error_statuses:
                error_count += 1

            if index < tracker_count:
                try:
                    tracker_peer_count += max(0, int(source.get("peers", 0) or 0))
                except (TypeError, ValueError):
                    pass

                scrape_status = str(source.get("scrape_status") or "Waiting")
                if scrape_status == "Active":
                    scrape_active_count += 1
                    age = source.get("scrape_last_success_seconds")
                    try:
                        age_value = float(age) if age is not None else float("inf")
                    except (TypeError, ValueError):
                        age_value = float("inf")
                    if freshest_scrape is None or age_value < freshest_scrape[0]:
                        freshest_scrape = (age_value, source)
                elif scrape_status in {"Waiting", "Scraping"}:
                    scrape_pending_count += 1
                elif scrape_status in {"Timeout", "No Data"}:
                    scrape_warning_count += 1
                elif scrape_status == "Error":
                    scrape_error_count += 1

        scrape_source = freshest_scrape[1] if freshest_scrape is not None else {}
        return {
            "sources": sources,
            "tracker_count": tracker_count,
            "active_count": active_count,
            "pending_count": pending_count,
            "warning_count": warning_count,
            "error_count": error_count,
            "problem_count": warning_count + error_count,
            "tracker_peers_last_seen": tracker_peer_count,
            "scrape_active_count": scrape_active_count,
            "scrape_pending_count": scrape_pending_count,
            "scrape_warning_count": scrape_warning_count,
            "scrape_error_count": scrape_error_count,
            "scrape_seeders": scrape_source.get("scrape_seeders"),
            "scrape_leechers": scrape_source.get("scrape_leechers"),
            "scrape_completed": scrape_source.get("scrape_completed"),
            "scrape_source": scrape_source.get("source", ""),
            "scrape_age_seconds": scrape_source.get("scrape_last_success_seconds"),
            "scrape_batch_size": int(scrape_source.get("scrape_batch_size", 0) or 0),
            "dht_peers_seen": sum(int(source.get("peers", 0) or 0) for source in dht_sources),
            "pex_peers_seen": int(pex_source.get("peers", 0) or 0),
            "lan_peers_seen": sum(int(source.get("peers", 0) or 0) for source in lan_sources),
            "active_generations": list(self.active_generations),
            "protocol_policy": self.protocol_policy,
        }

    @staticmethod
    def _normalise_peer_endpoints(peers: object) -> List[Tuple[str, int]]:
        out: List[Tuple[str, int]] = []
        seen: Set[Tuple[str, int]] = set()
        if not isinstance(peers, (list, tuple, set)):
            return out

        for endpoint in peers:
            if not isinstance(endpoint, (list, tuple)) or len(endpoint) != 2:
                continue
            try:
                ip = str(endpoint[0]).strip()
                port = int(endpoint[1])
            except (TypeError, ValueError):
                continue
            if not ip or port <= 0 or port > 65535:
                continue
            normalized = (ip, port)
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
        return out

    def _record_pex_payload(
        self,
        payload: dict,
        generation: Optional[str] = None,
    ) -> List[Tuple[str, int]]:
        if self.torrent.private or not self.enable_pex or not isinstance(payload, dict):
            return []
        resolved_generation = self._normalise_generation(generation)
        added = self._normalise_peer_endpoints(payload.get("added", []))
        if added:
            self._pex_seen_endpoints.update(
                (ip, port, resolved_generation) for ip, port in added
            )
        self._pex_messages_received += 1
        self._pex_last_at = time.monotonic()
        return added

    def _pex_export_endpoints(
        self,
        exclude: Optional[Tuple[str, int]] = None,
        generation: Optional[str] = None,
    ) -> List[Tuple[str, int]]:
        if self.torrent.private or not self.enable_pex:
            return []

        resolved_generation = self._normalise_generation(generation)
        endpoints: List[Tuple[str, int]] = []
        seen: Set[Tuple[str, int]] = set()
        for peer in self.active_peers:
            if not peer.is_connected:
                continue
            peer_generation = self._normalise_generation(
                getattr(peer, "protocol_generation", resolved_generation)
            )
            if peer_generation != resolved_generation:
                continue
            endpoint = (str(peer.ip), int(peer.port))
            if exclude and endpoint == exclude:
                continue
            if endpoint in seen:
                continue
            seen.add(endpoint)
            endpoints.append(endpoint)

        for ip, port, endpoint_generation in list(self._pex_seen_endpoints):
            if self._normalise_generation(endpoint_generation) != resolved_generation:
                continue
            endpoint = (ip, port)
            if exclude and endpoint == exclude:
                continue
            if endpoint in seen:
                continue
            seen.add(endpoint)
            endpoints.append(endpoint)

        return endpoints

    async def _maybe_send_pex(self, peer: PeerConnection):
        if self.torrent.private or not self.enable_pex or not peer.pex_supported:
            return
        now = time.monotonic()
        if peer.last_pex_sent_at and now - peer.last_pex_sent_at < PEX_SEND_INTERVAL:
            return
        generation = self._normalise_generation(
            getattr(peer, "protocol_generation", None)
        )
        endpoints = self._pex_export_endpoints(
            exclude=(str(peer.ip), int(peer.port)),
            generation=generation,
        )
        if await peer.send_pex(endpoints):
            self._pex_messages_sent += 1
            self._pex_last_at = time.monotonic()

    def _record_speed_sample(self, download_kbps: float, upload_kbps: float):
        """Record one aggregate transfer-rate sample for this torrent."""
        down = max(0.0, float(download_kbps or 0.0))
        up = max(0.0, float(upload_kbps or 0.0))
        self._current_download_speed_kbps = down
        self._current_upload_speed_kbps = up
        self._speed_history.append((time.monotonic(), down, up))

    def _build_speed_view_snapshot(self) -> dict:
        now = time.monotonic()
        cutoff = now - SPEED_HISTORY_SECONDS
        samples = [sample for sample in self._speed_history if sample[0] >= cutoff]

        rendered_samples = [
            {
                "age_seconds": max(0.0, now - timestamp),
                "download_kbps": download_kbps,
                "upload_kbps": upload_kbps,
            }
            for timestamp, download_kbps, upload_kbps in samples
        ]

        if samples:
            down_values = [sample[1] for sample in samples]
            up_values = [sample[2] for sample in samples]
            average_download = sum(down_values) / len(down_values)
            average_upload = sum(up_values) / len(up_values)
            peak_download = max(down_values)
            peak_upload = max(up_values)
        else:
            average_download = 0.0
            average_upload = 0.0
            peak_download = 0.0
            peak_upload = 0.0

        return {
            "samples": rendered_samples,
            "history_seconds": SPEED_HISTORY_SECONDS,
            "sample_interval_seconds": SPEED_SAMPLE_INTERVAL,
            "current_download_kbps": self._current_download_speed_kbps,
            "current_upload_kbps": self._current_upload_speed_kbps,
            "average_download_kbps": average_download,
            "average_upload_kbps": average_upload,
            "peak_download_kbps": peak_download,
            "peak_upload_kbps": peak_upload,
            "download_limit_kbps": self.download_limit_bps / 1024.0,
            "upload_limit_kbps": self.upload_limit_bps / 1024.0,
            "global_download_limit_kbps": (
                self._global_download_limiter.rate_bps / 1024.0
                if self._global_download_limiter is not None else 0.0
            ),
            "global_upload_limit_kbps": (
                self._global_upload_limiter.rate_bps / 1024.0
                if self._global_upload_limiter is not None else 0.0
            ),
        }

    def _build_snapshot(
        self,
        speed_kbps: Optional[float] = None,
        upload_speed_kbps: Optional[float] = None,
        force_detail_refresh: bool = False,
    ) -> dict:
        if speed_kbps is None:
            speed_kbps = self._current_download_speed_kbps
        if upload_speed_kbps is None:
            upload_speed_kbps = self._current_upload_speed_kbps

        peer_snapshots = self._build_peer_snapshots()
        piece_view, file_view, sources_view = self._cached_detail_snapshots(
            force=force_detail_refresh
        )
        speed_view = self._build_speed_view_snapshot()
        disk_io = self.piece_mgr.disk_io_snapshot()

        tracker_sources = [
            source
            for source in list(sources_view.get("sources") or [])
            if str(source.get("type", "")).upper() in {"HTTP", "HTTPS", "UDP"}
        ]
        seed_counts = [
            int(source.get("seeders"))
            for source in tracker_sources
            if source.get("seeders") is not None
        ]
        leecher_counts = [
            int(source.get("leechers"))
            for source in tracker_sources
            if source.get("leechers") is not None
        ]
        swarm_seeders = max(seed_counts) if seed_counts else None
        swarm_leechers = max(leecher_counts) if leecher_counts else None

        downloaded_bytes = max(0, int(self.piece_mgr.downloaded_bytes))
        total_bytes = max(0, int(self.torrent.total_length))
        remaining_bytes = max(0, total_bytes - downloaded_bytes)
        down_bps = max(0.0, float(speed_kbps or 0.0)) * 1024.0
        eta_seconds = (remaining_bytes / down_bps) if remaining_bytes > 0 and down_bps > 1.0 else None
        share_ratio = (self.uploaded_bytes / downloaded_bytes) if downloaded_bytes > 0 else None
        seeding_goal_status = self.seeding_goal_status()
        encrypted_peer_count = sum(
            1 for peer in peer_snapshots
            if str(peer.get("transport_security")) == "MSE/RC4"
        )
        plaintext_peer_count = max(0, len(peer_snapshots) - encrypted_peer_count)
        ipv6_peer_count = sum(1 for peer in peer_snapshots if peer.get("ip_family") == "IPv6")
        ipv4_peer_count = max(0, len(peer_snapshots) - ipv6_peer_count)

        discovery_parts = []
        if int(sources_view.get("tracker_count", 0) or 0):
            discovery_parts.append("Tracker")
        dht_source = next((x for x in sources_view.get("sources", []) if x.get("type") == "DHT"), None)
        pex_source = next((x for x in sources_view.get("sources", []) if x.get("type") == "PEX"), None)
        lan_source = next((x for x in sources_view.get("sources", []) if x.get("type") == "LAN"), None)
        if dht_source and dht_source.get("status") != "Disabled":
            discovery_parts.append("DHT")
        if pex_source and pex_source.get("status") != "Disabled":
            discovery_parts.append("PEX")
        if lan_source and lan_source.get("status") != "Disabled":
            discovery_parts.append("LAN")

        return {
            "type": "TRANSFER_STATS",
            "info_hash": self.torrent.hex_info_hash,
            "magnet_uri": self.torrent.magnet_uri,
            "torrent_name": self.torrent.name,
            "torrent_path": os.path.abspath(self.torrent_path),
            "state": self.state,
            "state_label": self._state_label(),
            "progress": self.piece_mgr.progress,
            "wanted_progress": self.piece_mgr.wanted_progress,
            "wanted_completed_pieces": self.piece_mgr.completed_wanted_pieces,
            "wanted_total_pieces": self.piece_mgr.wanted_piece_count,
            "wanted_finished": self.piece_mgr.wanted_is_finished,
            "checking_progress": self.piece_mgr.check_progress,
            "checked_pieces": self.piece_mgr.check_checked_pieces,
            "check_total_pieces": self.piece_mgr.check_total_pieces,
            "fast_resume_used": self.piece_mgr.fast_resume_used,
            "downloaded_bytes": downloaded_bytes,
            "remaining_bytes": remaining_bytes,
            "uploaded_bytes": self.uploaded_bytes,
            "uploaded_this_session_bytes": self.uploaded_this_session_bytes,
            "upload_requests_received": self.upload_requests_received,
            "upload_requests_served": self.upload_requests_served,
            "endgame_active": bool(piece_view.get("endgame_active", False)),
            "remaining_wanted_blocks": int(piece_view.get("remaining_wanted_blocks", 0) or 0),
            "outstanding_download_requests": int(piece_view.get("outstanding_wire_requests", 0) or 0),
            "duplicate_download_requests": int(piece_view.get("duplicate_wire_requests", 0) or 0),
            "endgame_threshold_blocks": ENDGAME_BLOCK_THRESHOLD,
            "request_pipeline_min": REQUEST_PIPELINE_MIN,
            "request_pipeline_max": REQUEST_PIPELINE_MAX,
            "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "request_retry_cooldown_seconds": REQUEST_RETRY_COOLDOWN_SECONDS,
            "last_upload_seconds": (
                max(0.0, time.monotonic() - self._last_upload_at)
                if self._last_upload_at else None
            ),
            "incoming_peers": len(self._inbound_peer_records),
            "incoming_connections_total": self.incoming_connections_total,
            "total_bytes": total_bytes,
            "speed_kbps": speed_kbps,
            "upload_speed_kbps": upload_speed_kbps,
            "eta_seconds": eta_seconds,
            "elapsed_seconds": self.elapsed_active_seconds,
            "share_ratio": share_ratio,
            "seeding_goal_mode": self.seeding_goal_mode,
            "seeding_ratio_limit": self.seeding_ratio_limit,
            "seeding_time_limit_minutes": self.seeding_time_limit_minutes,
            "seeding_elapsed_seconds": self.seeding_elapsed_seconds,
            "seeding_goal_elapsed_seconds": seeding_goal_status.elapsed_seconds,
            "seeding_time_goal_baseline_seconds": self.seeding_time_goal_baseline_seconds,
            "seeding_time_days": int(self.seeding_time_days),
            "seeding_time_hours": int(self.seeding_time_hours),
            "seeding_time_minutes_component": int(self.seeding_time_minutes_component),
            "seeding_goal_ratio": seeding_goal_status.current_ratio,
            "seeding_goal_remaining_ratio": seeding_goal_status.remaining_ratio,
            "seeding_goal_remaining_seconds": seeding_goal_status.remaining_seconds,
            "seeding_goal_reached": seeding_goal_status.reached,
            "seeding_goal_reason": self._seeding_goal_last_reason,
            "connected_peers": self._connected_peer_count(),
            "encrypted_peer_count": encrypted_peer_count,
            "plaintext_peer_count": plaintext_peer_count,
            "ipv4_peer_count": ipv4_peer_count,
            "ipv6_peer_count": ipv6_peer_count,
            "encryption_policy": self.encryption_policy,
            "network_bind_address": self.network_bind_address,
            "interface_lock": bool(self.interface_lock),
            "interface_lock_active": bool(self.interface_lock and self.network_bind_address),
            "mask_peer_ips": bool(self.mask_peer_ips),
            "swarm_seeders": swarm_seeders,
            "swarm_leechers": swarm_leechers,
            # Scrape statistics are kept separate from announce-derived counts.
            # Trackers can represent different swarm populations, so the UI
            # labels this as the freshest individual tracker scrape rather than
            # pretending it is a mathematically global count.
            "scrape_seeders": sources_view.get("scrape_seeders"),
            "scrape_leechers": sources_view.get("scrape_leechers"),
            "scrape_completed": sources_view.get("scrape_completed"),
            "scrape_source": sources_view.get("scrape_source", ""),
            "scrape_age_seconds": sources_view.get("scrape_age_seconds"),
            "scrape_batch_size": int(sources_view.get("scrape_batch_size", 0) or 0),
            "swarm_availability": float(piece_view.get("swarm_availability", 0.0) or 0.0),
            "discovery_summary": " + ".join(discovery_parts) if discovery_parts else "None",
            "peers": peer_snapshots,
            "piece_view": piece_view,
            "file_view": file_view,
            "sources_view": sources_view,
            "speed_view": speed_view,
            "disk_io": disk_io,
            "completed_pieces": self.piece_mgr.completed_pieces,
            "total_pieces": len(self.piece_mgr.pieces),
            "piece_length": int(self.torrent.piece_length),
            "listen_port": self._seed_port if self._seed_servers else 0,
            "listener_address": self._seed_bind_address if self._seed_servers else "",
            "listener_ipv4_address": self._seed_listener_addresses.get(socket.AF_INET, ""),
            "listener_ipv6_address": self._seed_listener_addresses.get(socket.AF_INET6, ""),
            "listener_ipv4_endpoint": (
                format_endpoint(self._seed_listener_addresses.get(socket.AF_INET), self._seed_port)
                if socket.AF_INET in self._seed_servers else ""
            ),
            "listener_ipv6_endpoint": (
                format_endpoint(self._seed_listener_addresses.get(socket.AF_INET6), self._seed_port)
                if socket.AF_INET6 in self._seed_servers else ""
            ),
            "dht_udp_port_ipv4": int(self._dht.local_udp_port_v4 or 0),
            "dht_udp_port_ipv6": int(self._dht.local_udp_port_v6 or 0),
            "preferred_listen_port": self.preferred_listen_port,
            "dht_enabled": bool(self.enable_dht),
            "pex_enabled": bool(self.enable_pex),
            "lan_discovery_enabled": bool(self.enable_lan_discovery),
            "storage_mode": self.piece_mgr.storage_mode,
            "storage_path": os.path.abspath(self.piece_mgr.backing_path),
            "download_dir": os.path.abspath(self.piece_mgr.download_dir),
            "seed_source_path": self.seed_source_path,
            "local_discovery_enabled": bool(self._lpd.enabled),
            "local_peers_discovered": int(self.local_peers_discovered),
            "error_message": self.error_message or self.piece_mgr.last_error,
            "download_limit_value": self.download_limit_value,
            "download_limit_unit": self.download_limit_unit,
            "download_limit_bps": self.download_limit_bps,
            "upload_limit_value": self.upload_limit_value,
            "upload_limit_unit": self.upload_limit_unit,
            "upload_limit_bps": self.upload_limit_bps,
            "queue_priority": self.queue_priority,
            "max_peers": int(self.max_peers),
            "private": bool(self.torrent.private),
            "is_multi_file": bool(self.torrent.is_multi_file),
            "file_count": len(self.torrent.files),
            "comment": self.torrent.comment,
            "created_by": self.torrent.created_by,
            "creation_date": int(self.torrent.creation_date or 0),
            "trackers": list(self.torrent.announce_list),
        }

    def _emit_snapshot(
        self,
        *,
        drop_if_ui_busy: bool = False,
        force_detail_refresh: bool = False,
    ):
        if drop_if_ui_busy:
            try:
                if self.ui_queue.qsize() >= UI_QUEUE_BACKPRESSURE_LIMIT:
                    return
            except (AttributeError, NotImplementedError):
                pass

        self.ui_queue.put(
            self._build_snapshot(force_detail_refresh=force_detail_refresh)
        )

    async def _trip_interface_lock(self):
        """Fail closed when the explicitly bound interface disappears."""
        if not self.interface_lock or not self.network_bind_address:
            return

        self.error_message = (
            f"Interface Lock: bound address {self.network_bind_address} is no longer "
            "available. Torrent networking was stopped to prevent fallback to another path."
        )
        self.state = SessionState.ERROR
        self.is_running = False
        self._pause_event.set()

        for peer in list(self.active_peers):
            await peer.close()
        await self._close_seed_server()
        await self._lpd.close()
        await self._dht.close()
        self._record_speed_sample(0.0, 0.0)
        self._emit_snapshot(force_detail_refresh=True)

    async def start(self):
        if self.is_running:
            return

        self._run_token += 1
        run_token = self._run_token
        self.is_running = True
        self._main_task = asyncio.current_task()
        self._prepare_cancel_event = threading.Event()
        self._prepare_pause_event = threading.Event()
        self._prepare_pause_event.set()
        self._paused_from_state = None
        self.error_message = ""
        self._begin_activity_clock()

        local_telemetry_task: Optional[asyncio.Task] = None

        try:
            if (
                self.interface_lock
                and self.network_bind_address
                and not is_bind_address_available(self.network_bind_address)
            ):
                await self._trip_interface_lock()
                return

            if not self.piece_mgr.storage_prepared:
                self.state = SessionState.CHECKING
                self._pause_event.set()
                self._emit_snapshot()

                prepared = await asyncio.to_thread(
                    self.piece_mgr.prepare_storage,
                    self._prepare_cancel_event,
                    self._emit_snapshot,
                    self._prepare_pause_event,
                )

                if not prepared:
                    if (
                        self._is_current_run(run_token)
                        and self.piece_mgr.last_error
                    ):
                        self.error_message = self.piece_mgr.last_error
                        self.state = SessionState.ERROR
                        self._emit_snapshot()
                    return
                if not self._is_current_run(run_token):
                    return

            # An external source is a read-only seed, never a download target.
            # It must verify to 100% before any peer is allowed to request data.
            if self.seed_source_path and not self.piece_mgr.is_finished:
                self.error_message = (
                    self.piece_mgr.last_error
                    or "The external seed source is incomplete or does not match this torrent."
                )
                self.state = SessionState.ERROR
                self._emit_snapshot()
                return

            if (
                self.piece_mgr.fast_resume_used
                and not self._fast_resume_notice_shown
                and self._is_current_run(run_token)
            ):
                self._fast_resume_notice_shown = True
                self.state = SessionState.FAST_RESUME
                self._emit_snapshot()
                await asyncio.sleep(0.9)

                if not self._is_current_run(run_token):
                    return

            started_complete = self.piece_mgr.is_finished

            # Phase 4: live downloads use one bounded write-behind worker. It
            # sleeps when idle and moves filesystem writes/resume fsync work off
            # the peer/event-loop hot path. Complete seeds need no writer.
            if not started_complete and not self.seed_source_path:
                await self.piece_mgr.start_disk_io()

            # If every currently wanted file is already complete (including
            # the valid case where every file is marked Don't Download), there
            # is no network work to schedule. A fully complete torrent still
            # proceeds into seeding below.
            if not started_complete and self.piece_mgr.wanted_is_finished:
                self.state = SessionState.COMPLETED
                self._pause_activity_clock()
                self._emit_snapshot()
                return

            local_telemetry_task = asyncio.create_task(
                self._telemetry_loop(run_token)
            )
            self._telemetry_task = local_telemetry_task

            if started_complete:
                await self._run_seeding(run_token, completion_event=False)
                return

            await self._run_downloading(run_token)

            # A torrent is not announced complete until every verified piece in
            # the bounded write-behind buffer has reached filesystem storage.
            # This preserves crash-safe resume semantics while keeping each
            # individual peer receive path non-blocking on disk.
            if self._is_current_run(run_token) and self.piece_mgr.disk_error:
                self.error_message = self.piece_mgr.disk_error
                self.state = SessionState.ERROR
                self.is_running = False
            elif self._is_current_run(run_token):
                try:
                    await self.piece_mgr.flush_disk_writes()
                except OSError as exc:
                    self.error_message = str(exc)
                    self.state = SessionState.ERROR
                    self.is_running = False

            if self._is_current_run(run_token) and self.piece_mgr.is_finished:
                await self._run_seeding(run_token, completion_event=True)
            elif self._is_current_run(run_token) and self.piece_mgr.wanted_is_finished:
                self.state = SessionState.COMPLETED
                self._pause_activity_clock()
                self._record_speed_sample(0.0, 0.0)
                self._emit_snapshot()

        except asyncio.CancelledError:
            pass

        finally:
            for task in list(self._worker_tasks):
                if not task.done():
                    task.cancel()
            if self._worker_tasks:
                await asyncio.gather(*self._worker_tasks, return_exceptions=True)
            self._worker_tasks = []
            self._download_endpoints.clear()
            self._seed_outbound_endpoints.clear()

            await self._close_seed_server()
            for lpd in self._lpd_by_generation.values():
                await lpd.close()
            for dht in self._dht_by_generation.values():
                await dht.close()

            if local_telemetry_task and not local_telemetry_task.done():
                local_telemetry_task.cancel()
                await asyncio.gather(local_telemetry_task, return_exceptions=True)

            if self._telemetry_task is local_telemetry_task:
                self._telemetry_task = None

            try:
                await self.piece_mgr.shutdown_disk_io(flush=True)
            except OSError as exc:
                if run_token == self._run_token:
                    self.error_message = str(exc)
                    self.state = SessionState.ERROR

            if run_token == self._run_token:
                self.is_running = False

                if self.state == SessionState.ERROR:
                    pass
                elif self.piece_mgr.is_finished:
                    # This state is only reached if seeding exits unexpectedly.
                    # Normal completed torrents remain in SEEDING until Paused
                    # or Stopped by the user.
                    if self.state not in (SessionState.PAUSED, SessionState.STOPPED):
                        self.state = SessionState.COMPLETED
                elif self.piece_mgr.wanted_is_finished:
                    if self.state not in (SessionState.PAUSED, SessionState.STOPPED):
                        self.state = SessionState.COMPLETED
                elif self.state not in (SessionState.PAUSED, SessionState.STOPPED):
                    self.state = SessionState.STOPPED

                self.piece_mgr.reset_inflight_requests()
                self.piece_mgr.save_resume_state(force=True)
                if self.state not in (SessionState.DOWNLOADING, SessionState.SEEDING):
                    self._pause_activity_clock()
                self._emit_snapshot()

            if self._main_task is asyncio.current_task():
                self._main_task = None

    async def _run_downloading(self, run_token: int):
        """Discover and download independently from every active swarm generation."""
        self.state = SessionState.DOWNLOADING
        self._pause_event.set()

        await self._open_seed_server(run_token)
        listen_port = self._seed_port if self._seed_server else 0

        if self.enable_lan_discovery:
            for lpd in self._lpd_by_generation.values():
                await lpd.start(listen_port=listen_port)
                lpd.update_listen_port(listen_port)
        if self.enable_dht:
            for dht in self._dht_by_generation.values():
                await dht.start(announce_port=listen_port)
                dht.update_announce_port(listen_port)
        self._emit_snapshot()

        tracker_tasks: Dict[str, Optional[asyncio.Task]] = {
            generation: None for generation in self.active_generations
        }
        dht_tasks: Dict[str, Optional[asyncio.Task]] = {
            generation: None for generation in self.active_generations
        }
        next_tracker_announce = {generation: 0.0 for generation in self.active_generations}
        next_dht_lookup = {generation: 0.0 for generation in self.active_generations}
        tracker_events: Dict[str, Optional[str]] = {
            generation: "started" for generation in self.active_generations
        }

        try:
            while self._is_current_run(run_token) and not self.piece_mgr.wanted_is_finished:
                await self._pause_event.wait()
                if not self._is_current_run(run_token):
                    break

                if self.piece_mgr.disk_error:
                    self.error_message = self.piece_mgr.disk_error
                    self.state = SessionState.ERROR
                    self.is_running = False
                    break

                if self.state != SessionState.PAUSED:
                    self.state = SessionState.DOWNLOADING

                for generation in self.active_generations:
                    if self.enable_lan_discovery:
                        local_peers = self._lpd_by_generation[generation].drain_peers()
                        if local_peers:
                            self.local_peers_discovered += len(local_peers)
                            self._start_download_workers(
                                run_token, local_peers, source="LAN", generation=generation
                            )
                            self._emit_snapshot()

                    if self.enable_dht:
                        announced = self._dht_by_generation[generation].drain_peers()
                        if announced:
                            self._start_download_workers(
                                run_token, announced, source="DHT", generation=generation
                            )
                            self._emit_snapshot()

                now = time.monotonic()
                downloaded = self.piece_mgr.downloaded_bytes
                left = max(0, self.torrent.total_length - downloaded)

                for generation in self.active_generations:
                    if (
                        tracker_tasks[generation] is None
                        and now >= next_tracker_announce[generation]
                    ):
                        tracker_tasks[generation] = asyncio.create_task(
                            self._trackers_by_generation[generation].fetch_peers(
                                uploaded=self.uploaded_bytes,
                                downloaded=downloaded,
                                left=left,
                                event=tracker_events[generation],
                            )
                        )

                    if (
                        self.enable_dht
                        and not self.torrent.private
                        and dht_tasks[generation] is None
                        and now >= next_dht_lookup[generation]
                    ):
                        dht_tasks[generation] = asyncio.create_task(
                            self._dht_by_generation[generation].discover_peers(
                                announce_port=listen_port
                            )
                        )

                for generation in self.active_generations:
                    tracker_task = tracker_tasks[generation]
                    if tracker_task is not None and tracker_task.done():
                        try:
                            tracker_peers = tracker_task.result()
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            tracker_peers = []
                        tracker_tasks[generation] = None
                        tracker_events[generation] = None
                        next_tracker_announce[generation] = time.monotonic() + 5 * 60
                        self._start_download_workers(
                            run_token, tracker_peers, source="Tracker", generation=generation
                        )

                    dht_task = dht_tasks[generation]
                    if dht_task is not None and dht_task.done():
                        try:
                            dht_peers = dht_task.result()
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            dht_peers = []
                        dht_tasks[generation] = None
                        next_dht_lookup[generation] = time.monotonic() + DHT_REFRESH_INTERVAL
                        self._start_download_workers(
                            run_token, dht_peers, source="DHT", generation=generation
                        )
                        self._emit_snapshot()

                self._worker_tasks = [task for task in self._worker_tasks if not task.done()]
                await asyncio.sleep(0.20)

        finally:
            tasks = [
                task
                for task in list(tracker_tasks.values()) + list(dht_tasks.values())
                if task is not None and not task.done()
            ]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)


    def _start_download_workers(
        self,
        run_token: int,
        peers: List[Tuple[str, int]],
        source: str = "Tracker",
        generation: Optional[str] = None,
    ):
        generation = self._normalise_generation(generation)
        available_slots = max(0, self.max_peers - len(self._download_endpoints))
        if available_slots <= 0:
            return

        for endpoint in peers:
            if available_slots <= 0:
                break
            if not isinstance(endpoint, tuple) or len(endpoint) != 2:
                continue

            ip, port = endpoint
            try:
                port = int(port)
            except (TypeError, ValueError):
                continue
            if port <= 0 or port > 65535:
                continue

            endpoint_key = (str(ip), port, generation)
            if endpoint_key in self._download_endpoints:
                continue

            self._download_endpoints.add(endpoint_key)
            task = asyncio.create_task(
                self._peer_worker(
                    run_token,
                    endpoint_key[0],
                    endpoint_key[1],
                    source=source,
                    generation=generation,
                )
            )
            task.add_done_callback(
                lambda _task, ep=endpoint_key: self._download_endpoints.discard(ep)
            )
            self._worker_tasks.append(task)
            available_slots -= 1

    @staticmethod
    def _block_key(block: Block) -> Tuple[int, int]:
        return int(block.piece_index), int(block.offset)

    @staticmethod
    def _wire_block_key(piece_index: int, begin: int) -> Tuple[int, int]:
        return int(piece_index), int(begin)

    def _peer_pipeline_limit(self, peer: PeerConnection) -> int:
        return request_pipeline_limit(getattr(peer, "download_speed_kbps", 0.0))

    async def _request_one_block(
        self,
        peer: PeerConnection,
        owned_requests: Dict[Tuple[int, int], Block],
        retry_after: Dict[Tuple[int, int], float],
    ) -> bool:
        if self.state != SessionState.DOWNLOADING:
            return False
        if peer.peer_choking or not peer.bitfield:
            return False
        if len(owned_requests) >= self._peer_pipeline_limit(peer):
            return False

        peer_key = id(peer)
        block = self.piece_mgr.get_next_request(
            peer.bitfield,
            peer_key=peer_key,
            excluded_blocks=retry_after,
        )
        if not block:
            return False

        block_key = self._block_key(block)
        owned_requests[block_key] = block

        try:
            if self._global_download_limiter is not None:
                await self._global_download_limiter.throttle(block.length)
            await self._download_limiter.throttle(block.length)

            if (
                self.state != SessionState.DOWNLOADING
                or not peer.is_connected
                or peer.peer_choking
                or not self.piece_mgr.is_piece_wanted(block.piece_index)
            ):
                self.piece_mgr.release_request(block, peer_key)
                owned_requests.pop(block_key, None)
                return False

            if not await peer.send_request(
                block.piece_index,
                block.offset,
                block.length,
            ):
                self.piece_mgr.release_request(block, peer_key)
                owned_requests.pop(block_key, None)
                return False

            self.piece_mgr.mark_request_sent(block, peer_key)
        except asyncio.CancelledError:
            self.piece_mgr.release_request(block, peer_key)
            owned_requests.pop(block_key, None)
            raise
        except Exception:
            self.piece_mgr.release_request(block, peer_key)
            owned_requests.pop(block_key, None)
            return False

        return True

    async def _fill_request_pipeline(
        self,
        peer: PeerConnection,
        owned_requests: Dict[Tuple[int, int], Block],
        retry_after: Dict[Tuple[int, int], float],
        *,
        burst_limit: int = REQUEST_REFILL_BURST,
    ) -> int:
        """Fill a bounded peer pipeline without monopolising the read loop."""
        if self.state != SessionState.DOWNLOADING or peer.peer_choking:
            return 0

        pipeline_limit = self._peer_pipeline_limit(peer)
        available = max(0, pipeline_limit - len(owned_requests))
        to_add = min(max(0, int(burst_limit)), available)
        added = 0
        for _ in range(to_add):
            if not await self._request_one_block(peer, owned_requests, retry_after):
                break
            added += 1
        return added

    async def _expire_peer_download_requests(
        self,
        peer: PeerConnection,
        owned_requests: Dict[Tuple[int, int], Block],
        retry_after: Dict[Tuple[int, int], float],
    ) -> int:
        """Release stale requests so another peer can immediately own them."""
        expired = self.piece_mgr.expire_peer_requests(
            id(peer),
            REQUEST_TIMEOUT_SECONDS,
        )
        if not expired:
            return 0

        retry_until = time.monotonic() + REQUEST_RETRY_COOLDOWN_SECONDS
        for block in expired:
            block_key = self._block_key(block)
            owned_requests.pop(block_key, None)
            retry_after[block_key] = retry_until
            if peer.is_connected:
                await peer.send_cancel(
                    block.piece_index,
                    block.offset,
                    block.length,
                )
        return len(expired)

    def _release_peer_download_requests(
        self,
        peer: PeerConnection,
        owned_requests: Dict[Tuple[int, int], Block],
    ) -> int:
        """Release a choked/disconnected peer's pipeline for reassignment."""
        released = self.piece_mgr.release_peer_requests(id(peer))
        owned_requests.clear()
        return len(released)

    async def _cancel_duplicate_download_requests(
        self,
        piece_index: int,
        begin: int,
        length: int,
        peer_keys: tuple[object, ...],
    ):
        """Send targeted endgame CANCELs only to peers that own this block."""
        if not peer_keys:
            return

        block_key = self._wire_block_key(piece_index, begin)
        tasks = []
        for raw_key in peer_keys:
            try:
                peer_key = int(raw_key)
            except (TypeError, ValueError):
                continue
            owned = self._download_request_owners.get(peer_key)
            if owned is not None:
                owned.pop(block_key, None)
            peer = self._download_peer_connections.get(peer_key)
            if peer is not None and peer.is_connected:
                tasks.append(peer.send_cancel(piece_index, begin, length))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _cancel_piece_download_requests(self, piece_index: int):
        """Cancel residual requests after a failed piece hash (rare slow path)."""
        tasks = []
        for peer_key, owned in tuple(self._download_request_owners.items()):
            peer = self._download_peer_connections.get(peer_key)
            for key, block in tuple(owned.items()):
                if block.piece_index != piece_index:
                    continue
                self.piece_mgr.release_request(block, peer_key)
                owned.pop(key, None)
                if peer is not None and peer.is_connected:
                    tasks.append(
                        peer.send_cancel(block.piece_index, block.offset, block.length)
                    )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _upload_key(
        piece_index: int,
        begin: int,
        length: int,
    ) -> Optional[Tuple[int, int, int]]:
        try:
            piece_index = int(piece_index)
            begin = int(begin)
            length = int(length)
        except (TypeError, ValueError):
            return None
        if piece_index < 0 or begin < 0 or length <= 0 or length > BLOCK_SIZE:
            return None
        return piece_index, begin, length

    def _queue_peer_upload(
        self,
        peer: PeerConnection,
        run_token: int,
        piece_index: int,
        begin: int,
        length: int,
        state: _UploadRequestState,
    ) -> bool:
        key = self._upload_key(piece_index, begin, length)
        if key is None:
            return False

        # Telemetry counts protocol requests at arrival time, independently of
        # whether the bounded upload queue can service every duplicate request.
        self._record_upload_request()
        if key in state.active or state.queue.full():
            return False

        state.active.add(key)
        state.queue.put_nowait(key)
        if state.task is None or state.task.done():
            state.task = asyncio.create_task(
                self._peer_upload_worker(peer, run_token, state)
            )
        return True

    def _queue_inbound_upload(
        self,
        stream: PeerWireStream,
        inbound_record: dict,
        run_token: int,
        piece_index: int,
        begin: int,
        length: int,
        state: _UploadRequestState,
    ) -> bool:
        key = self._upload_key(piece_index, begin, length)
        if key is None:
            return False
        self._record_upload_request()
        if key in state.active or state.queue.full():
            return False

        state.active.add(key)
        state.queue.put_nowait(key)
        if state.task is None or state.task.done():
            state.task = asyncio.create_task(
                self._inbound_upload_worker(
                    stream,
                    inbound_record,
                    run_token,
                    state,
                )
            )
        return True

    @staticmethod
    def _cancel_queued_upload(
        state: _UploadRequestState,
        piece_index: int,
        begin: int,
        length: int,
    ) -> bool:
        try:
            key = (int(piece_index), int(begin), int(length))
        except (TypeError, ValueError):
            return False
        if key not in state.active:
            return False
        # Queue entries are tiny tuples. Removing from the active set is O(1);
        # the one sleeping worker skips the stale tuple when it reaches it. If
        # the request is already being read/throttled, the worker re-checks the
        # same set immediately before sending PIECE.
        state.active.discard(key)
        return True

    @staticmethod
    async def _finish_upload_state(state: _UploadRequestState):
        state.active.clear()
        task = state.task
        state.task = None
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def _peer_upload_worker(
        self,
        peer: PeerConnection,
        run_token: int,
        state: _UploadRequestState,
    ):
        try:
            while self._is_current_run(run_token) and peer.is_connected:
                key = await state.queue.get()
                try:
                    if key not in state.active:
                        continue
                    piece_index, begin, length = key
                    await self._serve_piece_request(
                        peer,
                        run_token,
                        piece_index,
                        begin,
                        length,
                        record_request=False,
                        upload_state=state,
                        upload_key=key,
                    )
                finally:
                    state.active.discard(key)
                    state.queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _inbound_upload_worker(
        self,
        stream: PeerWireStream,
        inbound_record: dict,
        run_token: int,
        state: _UploadRequestState,
    ):
        try:
            while self._is_current_run(run_token):
                key = await state.queue.get()
                try:
                    if key not in state.active:
                        continue
                    piece_index, begin, length = key
                    await self._serve_inbound_piece_request(
                        stream,
                        inbound_record,
                        run_token,
                        piece_index,
                        begin,
                        length,
                        record_request=False,
                        upload_state=state,
                        upload_key=key,
                    )
                finally:
                    state.active.discard(key)
                    state.queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _handle_metadata_message(
        self,
        peer: PeerConnection,
        data: object,
    ):
        """Serve BEP-9 metadata requests from connected peers when possible."""
        if self.torrent.private or not isinstance(data, dict):
            return
        header = data.get("header", {})
        if not isinstance(header, dict):
            return
        try:
            msg_type = int(header.get(b"msg_type", -1))
            piece_index = int(header.get(b"piece", -1))
        except (TypeError, ValueError):
            return
        if msg_type != 0 or piece_index < 0:
            return
        await peer.send_metadata_piece(piece_index, self.torrent.raw_info_bytes)

    async def _serve_piece_request(
        self,
        peer: PeerConnection,
        run_token: int,
        piece_index: int,
        begin: int,
        length: int,
        *,
        record_request: bool = True,
        upload_state: Optional[_UploadRequestState] = None,
        upload_key: Optional[Tuple[int, int, int]] = None,
    ) -> bool:
        """Serve a verified block on any established peer connection.

        BitTorrent TCP connections are bidirectional: a socket SalixTorrent
        opened for downloading can also carry upload requests from that same
        peer.  Restrict uploads to already-verified pieces and apply both the
        global and per-torrent upload limiters.
        """
        try:
            piece_index = int(piece_index)
            begin = int(begin)
            length = int(length)
        except (TypeError, ValueError):
            return False

        if record_request:
            self._record_upload_request()
        if length <= 0 or length > BLOCK_SIZE:
            return False
        if not self._is_current_run(run_token):
            return False
        if self.state not in {SessionState.DOWNLOADING, SessionState.SEEDING}:
            return False
        if upload_state is not None and upload_key not in upload_state.active:
            return False

        block_data = await asyncio.to_thread(
            self.piece_mgr.read_block,
            piece_index,
            begin,
            length,
            self._normalise_generation(getattr(peer, "protocol_generation", None)),
        )
        if not block_data:
            return False

        if self._global_upload_limiter is not None:
            await self._global_upload_limiter.throttle(len(block_data))
        await self._upload_limiter.throttle(len(block_data))

        if (
            not self._is_current_run(run_token)
            or self.state not in {SessionState.DOWNLOADING, SessionState.SEEDING}
            or not peer.is_connected
            or (upload_state is not None and upload_key not in upload_state.active)
        ):
            return False

        if await peer.send_piece(piece_index, begin, block_data):
            self._record_upload_served(len(block_data))
            return True
        return False

    async def _serve_inbound_piece_request(
        self,
        stream: PeerWireStream,
        inbound_record: dict,
        run_token: int,
        piece_index: int,
        begin: int,
        length: int,
        *,
        record_request: bool = True,
        upload_state: Optional[_UploadRequestState] = None,
        upload_key: Optional[Tuple[int, int, int]] = None,
    ) -> bool:
        """Serve one inbound REQUEST in a cancellable task."""
        try:
            piece_index = int(piece_index)
            begin = int(begin)
            length = int(length)
        except (TypeError, ValueError):
            return False

        if record_request:
            self._record_upload_request()
        if length <= 0 or length > BLOCK_SIZE:
            return False
        if not self._is_current_run(run_token):
            return False
        if self.state not in {SessionState.DOWNLOADING, SessionState.SEEDING}:
            return False
        if upload_state is not None and upload_key not in upload_state.active:
            return False

        block_data = await asyncio.to_thread(
            self.piece_mgr.read_block,
            piece_index,
            begin,
            length,
            self._normalise_generation(inbound_record.get("protocol_generation")),
        )
        if not block_data:
            return False

        if self._global_upload_limiter is not None:
            await self._global_upload_limiter.throttle(len(block_data))
        await self._upload_limiter.throttle(len(block_data))

        if (
            not self._is_current_run(run_token)
            or self.state not in {SessionState.DOWNLOADING, SessionState.SEEDING}
            or (upload_state is not None and upload_key not in upload_state.active)
        ):
            return False

        piece_payload = struct.pack(">II", piece_index, begin) + block_data
        stream.write(
            struct.pack(">IB", 1 + len(piece_payload), PeerMessageID.PIECE)
            + piece_payload
        )
        await stream.drain()
        self._record_upload_served(len(block_data))
        inbound_record["uploaded_bytes"] = int(
            inbound_record.get("uploaded_bytes", 0)
        ) + len(block_data)
        inbound_record["last_activity_at"] = time.monotonic()
        return True

    async def _broadcast_have(
        self,
        piece_index: int,
        exclude_peer: Optional[PeerConnection] = None,
    ):
        """Tell connected peers when a newly verified piece becomes available.

        Initial bitfields only describe pieces available at connection time.
        HAVE keeps both outgoing and incoming peers current as downloading
        continues, enabling sustained upload activity before completion.
        """
        try:
            piece_index = int(piece_index)
        except (TypeError, ValueError):
            return
        if piece_index < 0:
            return

        tasks = [
            peer.send_have(piece_index)
            for peer in list(self.active_peers)
            if peer is not exclude_peer and peer.is_connected
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        frame = struct.pack(">IBI", 5, PeerMessageID.HAVE, piece_index)
        stale_writers = []
        for writer in list(self._seed_client_writers):
            try:
                record = self._inbound_peer_records.get(id(writer), {})
                stream = record.get("stream")
                if isinstance(stream, PeerWireStream):
                    stream.write(frame)
                    await stream.drain()
                else:
                    writer.write(frame)
                    await writer.drain()
            except (ConnectionError, OSError, RuntimeError):
                stale_writers.append(writer)
            except Exception:
                stale_writers.append(writer)

        for writer in stale_writers:
            self.piece_mgr.unregister_peer(id(writer))
            self._seed_client_writers.discard(writer)
            self._inbound_peer_records.pop(id(writer), None)

    async def _peer_worker(
        self,
        run_token: int,
        ip: str,
        port: int,
        source: str = "Tracker",
        generation: Optional[str] = None,
    ):
        generation = self._normalise_generation(generation)
        peer = self._peer_connection_for_generation(
            ip,
            port,
            generation=generation,
            source=source,
            direction="Outgoing",
        )
        peer_key = id(peer)
        owned_requests: Dict[Tuple[int, int], Block] = {}
        retry_after: Dict[Tuple[int, int], float] = {}
        upload_state = _UploadRequestState()
        next_timeout_check = time.monotonic() + REQUEST_TIMEOUT_CHECK_INTERVAL

        if not await peer.connect(timeout=4.0):
            return

        if not self._is_current_run(run_token):
            await peer.close()
            return

        self.active_peers.append(peer)
        self._download_peer_connections[peer_key] = peer
        self._download_request_owners[peer_key] = owned_requests

        try:
            # A download connection is still a bidirectional BitTorrent
            # connection. Advertise pieces we already possess and unchoke the
            # remote side so it can request them while we continue downloading.
            # BITFIELD is sent first, as required by the peer-wire protocol.
            if not await peer.send_bitfield(self.piece_mgr.completed_bitfield()):
                return

            if not self.torrent.private:
                await peer.send_extended_handshake(
                    listen_port=self._seed_port if self._seed_server else 0,
                    metadata_size=len(self.torrent.raw_info_bytes),
                )
                if not peer.is_connected:
                    return
                if self.enable_dht:
                    await peer.send_port(
                        self._dht_port_for_peer(peer.ip, peer.protocol_generation)
                    )
                if not peer.is_connected:
                    return

            if not await peer.send_unchoke():
                return
            if not await peer.send_interested():
                return

            while self._is_current_run(run_token) and not self.piece_mgr.wanted_is_finished:
                await self._pause_event.wait()

                if not self._is_current_run(run_token):
                    break

                now = time.monotonic()
                if now >= next_timeout_check:
                    for block_key, retry_time in tuple(retry_after.items()):
                        if retry_time <= now:
                            retry_after.pop(block_key, None)
                    await self._expire_peer_download_requests(
                        peer,
                        owned_requests,
                        retry_after,
                    )
                    next_timeout_check = now + REQUEST_TIMEOUT_CHECK_INTERVAL

                if self.state == SessionState.DOWNLOADING and not peer.peer_choking:
                    await self._fill_request_pipeline(
                        peer,
                        owned_requests,
                        retry_after,
                    )

                await self._maybe_send_pex(peer)

                try:
                    message = await asyncio.wait_for(peer.read_message(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if not message:
                    break

                msg_type, data = message

                if msg_type == "PIECE":
                    piece_idx, offset, block_bytes = data
                    result = self.piece_mgr.receive_block(
                        piece_idx,
                        offset,
                        block_bytes,
                        peer_key=peer_key,
                    )
                    owned_requests.pop(self._wire_block_key(piece_idx, offset), None)

                    if result.cancel_peer_keys and result.block is not None:
                        await self._cancel_duplicate_download_requests(
                            piece_idx,
                            offset,
                            result.block.length,
                            result.cancel_peer_keys,
                        )
                    if result.hash_failed:
                        await self._cancel_piece_download_requests(piece_idx)
                    if result.piece_completed:
                        try:
                            await self.piece_mgr.enqueue_completed_piece(piece_idx)
                        except OSError as exc:
                            self.error_message = str(exc)
                            self.state = SessionState.ERROR
                            self.is_running = False
                            break
                        await self._broadcast_have(piece_idx, exclude_peer=peer)

                elif msg_type == "BITFIELD":
                    self.piece_mgr.register_peer_bitfield(id(peer), data)

                elif msg_type == "HAVE":
                    self._apply_have_to_peer(peer, int(data))

                elif msg_type == "CHOKE":
                    # A choke invalidates this peer as a useful owner now; free
                    # its pipeline immediately instead of waiting 30 seconds.
                    self._release_peer_download_requests(peer, owned_requests)

                elif msg_type == "UNCHOKE":
                    if self.state == SessionState.DOWNLOADING:
                        await self._fill_request_pipeline(
                            peer,
                            owned_requests,
                            retry_after,
                        )

                elif msg_type == "REQUEST":
                    piece_index, begin, length = data
                    self._queue_peer_upload(
                        peer,
                        run_token,
                        piece_index,
                        begin,
                        length,
                        upload_state,
                    )

                elif msg_type == "CANCEL":
                    piece_index, begin, length = data
                    self._cancel_queued_upload(
                        upload_state,
                        piece_index,
                        begin,
                        length,
                    )

                elif msg_type == "INTERESTED":
                    # We unchoke download peers proactively, but honour the
                    # state transition in case a future choking policy changes.
                    if peer.am_choking:
                        await peer.send_unchoke()

                elif msg_type == "METADATA":
                    await self._handle_metadata_message(peer, data)

                elif msg_type == "PEX":
                    pex_peers = self._record_pex_payload(
                        data, generation=peer.protocol_generation
                    )
                    if pex_peers:
                        self._start_download_workers(
                            run_token,
                            pex_peers,
                            source="PEX",
                            generation=peer.protocol_generation,
                        )
                        self._emit_snapshot()

                elif msg_type == "EXTENDED_HANDSHAKE":
                    await self._maybe_send_pex(peer)

                elif msg_type == "PORT":
                    if self.enable_dht and not self.torrent.private:
                        self._dht_for_generation(peer.protocol_generation).add_known_node(
                            (str(peer.ip), int(data))
                        )

                elif msg_type == "HASH_REQUEST":
                    if peer.protocol_generation == "v2":
                        await self._serve_peer_hash_request(peer, data)

        except asyncio.CancelledError:
            pass
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            # Remote peers can disconnect at any point.  That is normal swarm
            # churn and should retire this worker quietly.
            pass

        finally:
            await self._finish_upload_state(upload_state)
            self.piece_mgr.unregister_peer(peer_key)
            owned_requests.clear()
            self._download_request_owners.pop(peer_key, None)
            self._download_peer_connections.pop(peer_key, None)

            if peer in self.active_peers:
                self.active_peers.remove(peer)

            await peer.close()

    async def _run_seeding(self, run_token: int, completion_event: bool):
        if not self._is_current_run(run_token) or not self.piece_mgr.is_finished:
            return

        self.state = SessionState.SEEDING
        self._pause_event.set()
        self._seeding_goal_notified = False
        self._seeding_goal_last_reason = ""

        # A torrent restored or manually restarted with an already-satisfied
        # goal should not reopen listeners and announce to the swarm merely to
        # discover half a second later that it must stop again. Evaluate the
        # persisted ratio/time state before starting seeding networking.
        if self._check_seeding_goal():
            return

        await self._open_seed_server(run_token)
        listen_port = self._seed_port if self._seed_server else 0
        if self.enable_lan_discovery:
            for lpd in self._lpd_by_generation.values():
                await lpd.start(listen_port=listen_port)
                lpd.update_listen_port(listen_port)
        if self.enable_dht:
            for dht in self._dht_by_generation.values():
                await dht.start(announce_port=listen_port)
                dht.update_announce_port(listen_port)

        # Count only established Seeding-state lifetime, not listener/DHT/LPD
        # setup. If setup fails, no phantom seeding time can accumulate.
        self._begin_seeding_clock()
        self._emit_snapshot()

        first_event = "completed" if completion_event else "started"
        tracker_tasks: Dict[str, Optional[asyncio.Task]] = {
            generation: None for generation in self.active_generations
        }
        dht_tasks: Dict[str, Optional[asyncio.Task]] = {
            generation: None for generation in self.active_generations
        }
        next_announce = {generation: 0.0 for generation in self.active_generations}
        next_dht_lookup = {generation: 0.0 for generation in self.active_generations}
        announce_events: Dict[str, Optional[str]] = {
            generation: first_event for generation in self.active_generations
        }

        try:
            while self._is_current_run(run_token):
                await self._pause_event.wait()
                if not self._is_current_run(run_token):
                    break

                if self.state != SessionState.PAUSED:
                    self.state = SessionState.SEEDING

                for generation in self.active_generations:
                    if self.enable_lan_discovery:
                        local_peers = self._lpd_by_generation[generation].drain_peers()
                        if local_peers:
                            self.local_peers_discovered += len(local_peers)
                            self._start_outbound_seed_workers(
                                run_token, local_peers, source="LAN", generation=generation
                            )
                            self._emit_snapshot()

                    if self.enable_dht:
                        announced = self._dht_by_generation[generation].drain_peers()
                        if announced:
                            self._start_outbound_seed_workers(
                                run_token, announced, source="DHT", generation=generation
                            )
                            self._emit_snapshot()

                now = time.monotonic()
                for generation in self.active_generations:
                    if tracker_tasks[generation] is None and now >= next_announce[generation]:
                        tracker_tasks[generation] = asyncio.create_task(
                            self._trackers_by_generation[generation].announce(
                                uploaded=self.uploaded_bytes,
                                downloaded=self.piece_mgr.downloaded_bytes,
                                left=0,
                                event=announce_events[generation],
                            )
                        )
                    if (
                        self.enable_dht
                        and not self.torrent.private
                        and dht_tasks[generation] is None
                        and now >= next_dht_lookup[generation]
                    ):
                        dht_tasks[generation] = asyncio.create_task(
                            self._dht_by_generation[generation].discover_peers(
                                announce_port=listen_port
                            )
                        )

                for generation in self.active_generations:
                    tracker_task = tracker_tasks[generation]
                    if tracker_task is not None and tracker_task.done():
                        try:
                            peers = tracker_task.result()
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            peers = []
                        tracker_tasks[generation] = None
                        announce_events[generation] = None
                        next_announce[generation] = time.monotonic() + 15 * 60
                        self._start_outbound_seed_workers(
                            run_token, peers, source="Tracker", generation=generation
                        )

                    dht_task = dht_tasks[generation]
                    if dht_task is not None and dht_task.done():
                        try:
                            dht_peers = dht_task.result()
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            dht_peers = []
                        dht_tasks[generation] = None
                        next_dht_lookup[generation] = time.monotonic() + DHT_REFRESH_INTERVAL
                        self._start_outbound_seed_workers(
                            run_token, dht_peers, source="DHT", generation=generation
                        )
                        self._emit_snapshot()

                self._worker_tasks = [task for task in self._worker_tasks if not task.done()]
                await asyncio.sleep(0.5)

        finally:
            self._pause_seeding_clock()
            tasks = [
                task
                for task in list(tracker_tasks.values()) + list(dht_tasks.values())
                if task is not None and not task.done()
            ]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)


    def _dht_port_for_peer(
        self,
        peer_ip: object,
        generation: Optional[str] = None,
    ) -> int:
        """Return the generation-specific local DHT UDP port for a peer."""
        dht = self._dht_for_generation(generation)
        if ip_family(peer_ip) == socket.AF_INET6:
            return int(dht.local_udp_port_v6 or 0)
        return int(dht.local_udp_port_v4 or 0)

    def _listener_specs(self) -> List[Tuple[int, str]]:
        if self.network_bind_address:
            family = ip_family(self.network_bind_address)
            if family in {socket.AF_INET, socket.AF_INET6}:
                return [(family, self.network_bind_address)]
            return []
        return [
            (socket.AF_INET, wildcard_for_family(socket.AF_INET)),
            (socket.AF_INET6, wildcard_for_family(socket.AF_INET6)),
        ]

    async def _open_listener_socket(
        self,
        run_token: int,
        family: int,
        host: str,
        port: int,
    ) -> asyncio.AbstractServer:
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6 and hasattr(socket, "IPV6_V6ONLY"):
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            endpoint = (host, port, 0, 0) if family == socket.AF_INET6 else (host, port)
            sock.bind(endpoint)
            sock.listen(socket.SOMAXCONN)
            sock.setblocking(False)
            return await asyncio.start_server(
                lambda reader, writer: asyncio.create_task(
                    self._handle_inbound_seed_peer(run_token, reader, writer)
                ),
                sock=sock,
            )
        except Exception:
            sock.close()
            raise

    async def _open_seed_server(self, run_token: int):
        if self._seed_servers:
            return

        preferred = max(1, min(65535, int(self.preferred_listen_port or 6881)))
        candidates = [preferred] + [
            preferred + offset
            for offset in range(1, 11)
            if preferred + offset <= 65535
        ]
        specs = self._listener_specs()

        for port in candidates:
            servers: Dict[int, asyncio.AbstractServer] = {}
            addresses: Dict[int, str] = {}
            ipv4_failed = False
            for family, host in specs:
                try:
                    server = await self._open_listener_socket(run_token, family, host, port)
                except OSError:
                    # A specific source bind is all-or-nothing. For Any interface,
                    # preserve IPv4 compatibility if the platform has no IPv6
                    # stack, but do not accept an IPv6-only fallback when the v4
                    # port itself is occupied.
                    if self.network_bind_address or family == socket.AF_INET:
                        ipv4_failed = family == socket.AF_INET
                        break
                    continue
                except Exception:
                    if self.network_bind_address or family == socket.AF_INET:
                        ipv4_failed = family == socket.AF_INET
                        break
                    continue

                servers[family] = server
                try:
                    sockname = server.sockets[0].getsockname() if server.sockets else None
                    addresses[family] = str(sockname[0]) if sockname else host
                except Exception:
                    addresses[family] = host

            if ipv4_failed or not servers:
                for server in servers.values():
                    server.close()
                    try:
                        await server.wait_closed()
                    except Exception:
                        pass
                continue

            self._seed_servers = servers
            self._seed_listener_addresses = addresses
            self._seed_server = servers.get(socket.AF_INET) or next(iter(servers.values()))
            self._seed_port = port
            self._seed_bind_address = (
                addresses.get(ip_family(self.network_bind_address), self.network_bind_address)
                if self.network_bind_address
                else addresses.get(socket.AF_INET, addresses.get(socket.AF_INET6, ""))
            )
            for tracker in self._trackers_by_generation.values():
                tracker.port = port
            if self._listen_port_callback:
                try:
                    self._listen_port_callback(port, True)
                except TypeError:
                    try:
                        self._listen_port_callback(port)
                    except Exception:
                        pass
                except Exception:
                    pass
            return

        # Outbound transfers remain possible when no inbound listener is available.
        self._seed_port = preferred
        for tracker in self._trackers_by_generation.values():
            tracker.port = preferred

    async def _close_seed_server(self):
        closed_port = self._seed_port if self._seed_servers else 0
        servers = list(self._seed_servers.values())
        self._seed_servers.clear()
        self._seed_listener_addresses.clear()
        self._seed_server = None
        self._seed_bind_address = ""

        for server in servers:
            server.close()
        for server in servers:
            try:
                await server.wait_closed()
            except Exception:
                pass

        if closed_port and self._listen_port_callback:
            try:
                self._listen_port_callback(closed_port, False)
            except TypeError:
                pass
            except Exception:
                pass

        for writer in list(self._seed_client_writers):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self._seed_client_writers.clear()
        self._inbound_peer_records.clear()

    def _start_outbound_seed_workers(
        self,
        run_token: int,
        peers: List[Tuple[str, int]],
        source: str = "Tracker",
        generation: Optional[str] = None,
    ):
        resolved_generation = self._normalise_generation(generation)
        available_slots = max(0, self.max_peers - self._connected_peer_count())
        if available_slots <= 0:
            return

        for endpoint in peers:
            if available_slots <= 0:
                break
            ip, port = endpoint
            endpoint_key = (str(ip), int(port), resolved_generation)
            if endpoint_key in self._seed_outbound_endpoints:
                continue

            self._seed_outbound_endpoints.add(endpoint_key)
            task = asyncio.create_task(
                self._seed_peer_worker(
                    run_token,
                    str(ip),
                    int(port),
                    source=source,
                    generation=resolved_generation,
                )
            )
            self._worker_tasks.append(task)
            available_slots -= 1

    async def _seed_peer_worker(
        self,
        run_token: int,
        ip: str,
        port: int,
        source: str = "Tracker",
        generation: Optional[str] = None,
    ):
        resolved_generation = self._normalise_generation(generation)
        endpoint_key = (str(ip), int(port), resolved_generation)
        peer = self._peer_connection_for_generation(
            ip,
            port,
            generation=resolved_generation,
            source=source,
            direction="Outgoing",
        )
        upload_state = _UploadRequestState()

        try:
            if not await peer.connect(timeout=4.0):
                return
            if not self._is_current_run(run_token):
                return

            resolved_generation = self._normalise_generation(
                getattr(peer, "protocol_generation", resolved_generation)
            )
            self.active_peers.append(peer)
            if not self.torrent.private:
                await peer.send_extended_handshake(
                    listen_port=self._seed_port if self._seed_server else 0,
                    metadata_size=len(self.torrent.raw_info_bytes),
                )
                if not peer.is_connected:
                    return
                if self.enable_dht:
                    await peer.send_port(
                        self._dht_port_for_peer(peer.ip, resolved_generation)
                    )
                if not peer.is_connected:
                    return

            if not await peer.send_bitfield(self.piece_mgr.completed_bitfield()):
                return
            if not await peer.send_unchoke():
                return

            while self._is_current_run(run_token):
                await self._pause_event.wait()
                if not self._is_current_run(run_token):
                    break

                await self._maybe_send_pex(peer)

                try:
                    message = await asyncio.wait_for(peer.read_message(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue

                if not message:
                    break

                msg_type, data = message
                if msg_type == "BITFIELD":
                    self.piece_mgr.register_peer_bitfield(id(peer), data)
                    continue

                if msg_type == "HAVE":
                    self._apply_have_to_peer(peer, int(data))
                    continue

                if msg_type == "METADATA":
                    await self._handle_metadata_message(peer, data)
                    continue

                if msg_type == "PEX":
                    pex_peers = self._record_pex_payload(
                        data, generation=resolved_generation
                    )
                    if pex_peers:
                        self._start_outbound_seed_workers(
                            run_token,
                            pex_peers,
                            source="PEX",
                            generation=resolved_generation,
                        )
                        self._emit_snapshot()
                    continue

                if msg_type == "EXTENDED_HANDSHAKE":
                    await self._maybe_send_pex(peer)
                    continue

                if msg_type == "PORT":
                    if self.enable_dht and not self.torrent.private:
                        self._dht_for_generation(resolved_generation).add_known_node(
                            (str(peer.ip), int(data))
                        )
                    continue

                if msg_type == "HASH_REQUEST":
                    if resolved_generation == "v2":
                        await self._serve_peer_hash_request(peer, data)
                    else:
                        await peer.send_hash_reject(data)
                    continue

                if msg_type == "REQUEST" and self.state == SessionState.SEEDING:
                    piece_index, begin, length = data
                    self._queue_peer_upload(
                        peer,
                        run_token,
                        piece_index,
                        begin,
                        length,
                        upload_state,
                    )
                    continue

                if msg_type == "CANCEL":
                    piece_index, begin, length = data
                    self._cancel_queued_upload(
                        upload_state,
                        piece_index,
                        begin,
                        length,
                    )
                    continue

        except asyncio.CancelledError:
            pass
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            await self._finish_upload_state(upload_state)
            self.piece_mgr.unregister_peer(id(peer))
            if peer in self.active_peers:
                self.active_peers.remove(peer)
            await peer.close()
            self._seed_outbound_endpoints.discard(endpoint_key)

    async def _handle_inbound_seed_peer(
        self,
        run_token: int,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        registered = False
        stream: Optional[PeerWireStream] = None
        upload_state = _UploadRequestState()

        try:
            # A normal BitTorrent handshake has a deterministic 20-byte prefix.
            # Anything else is treated as an MSE Diffie-Hellman greeting when
            # encryption is enabled. Prefetched bytes are preserved by the
            # selected stream wrapper.
            first_bytes = await asyncio.wait_for(reader.readexactly(20), timeout=8.0)
            plaintext_prefix = b"\x13BitTorrent protocol"
            if first_bytes == plaintext_prefix:
                if self.encryption_policy == PEER_ENCRYPTION_REQUIRE:
                    return
                stream = PeerWireStream(
                    reader=reader,
                    writer=writer,
                    initial_plaintext=first_bytes,
                    transport_security="Plaintext",
                )
            else:
                if self.encryption_policy == PEER_ENCRYPTION_DISABLED:
                    return
                stream = await mse_responder_handshake(
                    reader,
                    writer,
                    [self.swarm_hashes[generation] for generation in self.active_generations],
                    first_bytes=first_bytes,
                    timeout=8.0,
                )

            handshake = await asyncio.wait_for(stream.readexactly(68), timeout=8.0)
            if handshake[:20] != plaintext_prefix:
                return

            remote_reserved = bytes(handshake[20:28])
            remote_supports_extensions = reserved_supports_extensions(remote_reserved)
            remote_supports_dht = reserved_supports_dht(remote_reserved)
            remote_supports_v2 = reserved_supports_v2(remote_reserved)
            info_hash = bytes(handshake[28:48])
            remote_peer_id = bytes(handshake[48:68])

            incoming_generation = next(
                (
                    generation
                    for generation in self.active_generations
                    if self.swarm_hashes[generation] == info_hash
                ),
                None,
            )
            if incoming_generation is None:
                return
            if stream.selected_info_hash and stream.selected_info_hash != info_hash:
                return

            negotiated_generation = incoming_generation
            response_hash = self.swarm_hashes[incoming_generation]
            if (
                incoming_generation == "v1"
                and "v2" in self.active_generations
                and remote_supports_v2
            ):
                # BEP-52 hybrid handshake upgrade: a connection discovered in
                # the v1 swarm can immediately switch to the v2 wire identity.
                negotiated_generation = "v2"
                response_hash = self.swarm_hashes["v2"]

            if not self._is_current_run(run_token):
                return
            if self.state not in {SessionState.DOWNLOADING, SessionState.SEEDING}:
                return

            peername = writer.get_extra_info("peername")
            if isinstance(peername, tuple) and len(peername) >= 2:
                peer_ip = str(peername[0])
                try:
                    peer_port = int(peername[1])
                except (TypeError, ValueError):
                    peer_port = 0
            else:
                peer_ip = "?"
                peer_port = 0

            response_reserved = build_reserved_bytes(
                enable_extensions=not self.torrent.private,
                enable_dht=self.enable_dht and not self.torrent.private,
                enable_v2=("v2" in self.active_generations),
            )
            response = (
                plaintext_prefix
                + response_reserved
                + response_hash
                + self.peer_id
            )
            stream.write(response)

            bitfield = self.piece_mgr.completed_bitfield()
            stream.write(
                struct.pack(">IB", 1 + len(bitfield), PeerMessageID.BITFIELD)
                + bitfield
            )
            stream.write(struct.pack(">IB", 1, PeerMessageID.UNCHOKE))
            if remote_supports_extensions and not self.torrent.private:
                stream.write(
                    build_extended_message(
                        0,
                        build_extended_handshake_payload(
                            listen_port=self._seed_port,
                            metadata_size=len(self.torrent.raw_info_bytes),
                            enable_pex=self.enable_pex,
                        ),
                    )
                )
            if (
                remote_supports_dht
                and self.enable_dht
                and not self.torrent.private
                and self._dht_port_for_peer(peer_ip, negotiated_generation)
            ):
                stream.write(
                    struct.pack(
                        ">IBH",
                        3,
                        PeerMessageID.PORT,
                        self._dht_port_for_peer(peer_ip, negotiated_generation),
                    )
                )
            await stream.drain()

            self._seed_client_writers.add(writer)

            self.incoming_connections_total += 1
            if self._incoming_peer_callback:
                try:
                    self._incoming_peer_callback(self._seed_port, peer_ip)
                except Exception:
                    pass

            record_key = id(writer)
            inbound_record = {
                "connection_id": f"in:{record_key}",
                "ip": peer_ip,
                "port": peer_port,
                "address": format_endpoint(peer_ip, peer_port),
                "ip_family": "IPv6" if ip_family(peer_ip) == socket.AF_INET6 else "IPv4",
                "client": identify_peer_client(remote_peer_id),
                "source": "Incoming",
                "direction": "Incoming",
                "transport_security": stream.transport_security,
                "protocol_generation": negotiated_generation,
                "stream": stream,
                "connected_at": time.monotonic(),
                "last_activity_at": time.monotonic(),
                "downloaded_bytes": 0,
                "uploaded_bytes": 0,
                "download_speed_kbps": 0.0,
                "upload_speed_kbps": 0.0,
                "_last_sample_downloaded": 0,
                "_last_sample_uploaded": 0,
                "am_choking": False,
                "am_interested": False,
                "peer_choking": True,
                "peer_interested": False,
                "bitfield": bytearray(),
                "supports_extensions": remote_supports_extensions,
                "supports_dht": remote_supports_dht,
                "remote_extensions": {},
                "pex_supported": False,
                "pex_messages_received": 0,
                "pex_messages_sent": 0,
            }
            self._inbound_peer_records[record_key] = inbound_record
            registered = True
            self._emit_snapshot()

            while self._is_current_run(run_token):
                length_raw = await asyncio.wait_for(stream.readexactly(4), timeout=120.0)
                (message_length,) = struct.unpack(">I", length_raw)

                if message_length == 0:
                    continue
                if message_length > 1024 * 1024:
                    break

                payload = await asyncio.wait_for(
                    stream.readexactly(message_length),
                    timeout=30.0,
                )
                msg_id = payload[0]
                body = payload[1:]
                inbound_record["last_activity_at"] = time.monotonic()

                if msg_id == PeerMessageID.CHOKE:
                    inbound_record["peer_choking"] = True
                    continue
                if msg_id == PeerMessageID.UNCHOKE:
                    inbound_record["peer_choking"] = False
                    continue
                if msg_id == PeerMessageID.INTERESTED:
                    inbound_record["peer_interested"] = True
                    continue
                if msg_id == PeerMessageID.NOT_INTERESTED:
                    inbound_record["peer_interested"] = False
                    continue
                if msg_id == PeerMessageID.BITFIELD:
                    inbound_record["bitfield"] = bytearray(body)
                    self.piece_mgr.register_peer_bitfield(record_key, body)
                    continue
                if msg_id == PeerMessageID.HAVE and len(body) == 4:
                    (piece_index,) = struct.unpack(">I", body)
                    total_pieces = len(self.piece_mgr.pieces)
                    if 0 <= piece_index < total_pieces:
                        self.piece_mgr.record_peer_have(record_key, piece_index)
                        needed_bytes = (total_pieces + 7) // 8
                        peer_bits = inbound_record.setdefault("bitfield", bytearray())
                        if len(peer_bits) < needed_bytes:
                            peer_bits.extend(b"\x00" * (needed_bytes - len(peer_bits)))
                        byte_index = piece_index // 8
                        bit_index = 7 - (piece_index % 8)
                        peer_bits[byte_index] |= 1 << bit_index
                    continue

                if (
                    msg_id == PeerMessageID.PORT
                    and len(body) == 2
                    and self.enable_dht
                    and not self.torrent.private
                ):
                    (remote_dht_port,) = struct.unpack(">H", body)
                    if peer_ip != "?" and remote_dht_port:
                        self._dht_for_generation(negotiated_generation).add_known_node(
                            (peer_ip, remote_dht_port)
                        )
                    continue

                if (
                    msg_id == PeerMessageID.EXTENDED
                    and body
                    and not self.torrent.private
                ):
                    extension_id = int(body[0])
                    extension_payload = bytes(body[1:])

                    if extension_id == 0:
                        handshake = parse_extended_handshake(extension_payload)
                        mapping = handshake.get(b"m")
                        remote_extensions = {}
                        if isinstance(mapping, dict):
                            for name, value in mapping.items():
                                if not isinstance(name, bytes):
                                    continue
                                try:
                                    extension_number = int(value)
                                except (TypeError, ValueError):
                                    continue
                                if 0 <= extension_number <= 255:
                                    remote_extensions[name] = extension_number

                        inbound_record["remote_extensions"] = remote_extensions
                        try:
                            remote_pex_id = int(remote_extensions.get(b"ut_pex", 0))
                        except (TypeError, ValueError):
                            remote_pex_id = 0
                        inbound_record["pex_supported"] = self.enable_pex and remote_pex_id > 0
                        try:
                            remote_metadata_id = int(
                                remote_extensions.get(b"ut_metadata", 0)
                            )
                        except (TypeError, ValueError):
                            remote_metadata_id = 0
                        inbound_record["metadata_extension_id"] = remote_metadata_id

                        if self.enable_pex and remote_pex_id > 0:
                            pex_payload = encode_pex_payload(
                                self._pex_export_endpoints(
                                    exclude=(peer_ip, peer_port) if peer_port else None,
                                    generation=negotiated_generation,
                                )
                            )
                            stream.write(build_extended_message(remote_pex_id, pex_payload))
                            await stream.drain()
                            inbound_record["pex_messages_sent"] = int(
                                inbound_record.get("pex_messages_sent", 0)
                            ) + 1
                            self._pex_messages_sent += 1
                            self._pex_last_at = time.monotonic()
                        self._emit_snapshot()
                        continue

                    if extension_id == LOCAL_UT_PEX_ID and self.enable_pex:
                        pex_payload = parse_pex_payload(extension_payload)
                        inbound_record["pex_messages_received"] = int(
                            inbound_record.get("pex_messages_received", 0)
                        ) + 1
                        pex_peers = self._record_pex_payload(
                            pex_payload, generation=negotiated_generation
                        )
                        if pex_peers:
                            if self.state == SessionState.DOWNLOADING:
                                self._start_download_workers(
                                    run_token,
                                    pex_peers,
                                    source="PEX",
                                    generation=negotiated_generation,
                                )
                            else:
                                self._start_outbound_seed_workers(
                                    run_token,
                                    pex_peers,
                                    source="PEX",
                                    generation=negotiated_generation,
                                )
                        self._emit_snapshot()
                        continue

                    if extension_id == LOCAL_UT_METADATA_ID:
                        metadata_message = parse_metadata_payload(extension_payload)
                        header = metadata_message.get("header", {})
                        try:
                            metadata_msg_type = int(header.get(b"msg_type", -1))
                            metadata_piece = int(header.get(b"piece", -1))
                        except (TypeError, ValueError):
                            metadata_msg_type = -1
                            metadata_piece = -1

                        remote_metadata_id = int(
                            inbound_record.get("metadata_extension_id", 0) or 0
                        )
                        if (
                            metadata_msg_type == 0
                            and metadata_piece >= 0
                            and remote_metadata_id > 0
                        ):
                            raw_metadata = self.torrent.raw_info_bytes
                            start = metadata_piece * METADATA_BLOCK_SIZE
                            if start < len(raw_metadata):
                                block = raw_metadata[start:start + METADATA_BLOCK_SIZE]
                                header_bytes = Bencode.encode(
                                    {
                                        b"msg_type": 1,
                                        b"piece": metadata_piece,
                                        b"total_size": len(raw_metadata),
                                    }
                                )
                                stream.write(
                                    build_extended_message(
                                        remote_metadata_id,
                                        header_bytes + block,
                                    )
                                )
                            else:
                                stream.write(
                                    build_extended_message(
                                        remote_metadata_id,
                                        Bencode.encode(
                                            {b"msg_type": 2, b"piece": metadata_piece}
                                        ),
                                    )
                                )
                            await stream.drain()
                        continue

                if msg_id == PeerMessageID.HASH_REQUEST:
                    request = parse_hash_request_payload(body)
                    if request is None:
                        continue
                    response = (
                        self._v2_hash_response(request)
                        if negotiated_generation == "v2"
                        else None
                    )
                    if response is None:
                        response_payload = build_hash_request_payload(
                            request["pieces_root"],
                            request["base_layer"],
                            request["index"],
                            request["length"],
                            request["proof_layers"],
                        )
                        stream.write(
                            struct.pack(
                                ">IB",
                                1 + len(response_payload),
                                PeerMessageID.HASH_REJECT,
                            )
                            + response_payload
                        )
                    else:
                        response_payload = build_hash_request_payload(
                            response["pieces_root"],
                            response["base_layer"],
                            response["index"],
                            response["length"],
                            response["proof_layers"],
                        ) + b"".join(response["hashes"])
                        stream.write(
                            struct.pack(
                                ">IB",
                                1 + len(response_payload),
                                PeerMessageID.HASHES,
                            )
                            + response_payload
                        )
                    await stream.drain()
                    continue

                if msg_id == PeerMessageID.CANCEL and len(body) == 12:
                    piece_index, begin, length = struct.unpack(">III", body)
                    self._cancel_queued_upload(
                        upload_state,
                        piece_index,
                        begin,
                        length,
                    )
                    continue

                if msg_id != PeerMessageID.REQUEST or len(body) != 12:
                    continue

                inbound_record["peer_interested"] = True
                await self._pause_event.wait()
                if not self._is_current_run(run_token):
                    break
                if self.state not in {SessionState.DOWNLOADING, SessionState.SEEDING}:
                    continue

                piece_index, begin, length = struct.unpack(">III", body)
                self._queue_inbound_upload(
                    stream,
                    inbound_record,
                    run_token,
                    piece_index,
                    begin,
                    length,
                    upload_state,
                )

        except (
            asyncio.IncompleteReadError,
            asyncio.TimeoutError,
            ConnectionError,
            OSError,
            MSEError,
        ):
            pass
        except asyncio.CancelledError:
            pass
        finally:
            await self._finish_upload_state(upload_state)
            if registered:
                self.piece_mgr.unregister_peer(id(writer))
                self._seed_client_writers.discard(writer)
                self._inbound_peer_records.pop(id(writer), None)
                self._emit_snapshot()

            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _telemetry_loop(self, run_token: int):
        last_downloaded = self.piece_mgr.downloaded_bytes
        last_uploaded = self.uploaded_bytes

        try:
            while self._is_current_run(run_token):
                await asyncio.sleep(SPEED_SAMPLE_INTERVAL)

                now = time.monotonic()
                if (
                    self.interface_lock
                    and self.network_bind_address
                    and now - self._last_interface_check_at >= 2.0
                ):
                    self._last_interface_check_at = now
                    if not is_bind_address_available(self.network_bind_address):
                        await self._trip_interface_lock()
                        return

                current_downloaded = self.piece_mgr.downloaded_bytes
                current_uploaded = self.uploaded_bytes

                if self.state == SessionState.DOWNLOADING:
                    download_speed_bps = max(
                        0.0,
                        (current_downloaded - last_downloaded) / SPEED_SAMPLE_INTERVAL,
                    )
                else:
                    download_speed_bps = 0.0

                if self.state in {SessionState.DOWNLOADING, SessionState.SEEDING}:
                    upload_speed_bps = max(
                        0.0,
                        (current_uploaded - last_uploaded) / SPEED_SAMPLE_INTERVAL,
                    )
                else:
                    upload_speed_bps = 0.0

                last_downloaded = current_downloaded
                last_uploaded = current_uploaded
                self._sample_peer_speeds(SPEED_SAMPLE_INTERVAL)
                self._record_speed_sample(
                    download_speed_bps / 1024.0,
                    upload_speed_bps / 1024.0,
                )

                self._check_seeding_goal()
                self._emit_snapshot(drop_if_ui_busy=True)

        except asyncio.CancelledError:
            pass
