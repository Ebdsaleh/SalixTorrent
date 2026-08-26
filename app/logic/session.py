# app/logic/session.py

import asyncio
import os
import queue
import random
import struct
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Set, Tuple

from app.logic.dht import DHTClient, DHT_REFRESH_INTERVAL
from app.logic.local_peer_discovery import LocalPeerDiscovery
from app.logic.peer import (
    build_reserved_bytes,
    LOCAL_UT_METADATA_ID,
    LOCAL_UT_PEX_ID,
    METADATA_BLOCK_SIZE,
    PEX_SEND_INTERVAL,
    PeerConnection,
    PeerMessageID,
    build_extended_handshake_payload,
    build_extended_message,
    encode_pex_payload,
    identify_peer_client,
    parse_extended_handshake,
    parse_metadata_payload,
    parse_pex_payload,
    reserved_supports_dht,
    reserved_supports_extensions,
)
from app.logic.piece_manager import BLOCK_SIZE, Block, PieceManager
from app.logic.torrent_file import TorrentFile
from app.logic.tracker import TrackerClient

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
        global_download_limiter: Optional[AsyncBandwidthLimiter] = None,
        global_upload_limiter: Optional[AsyncBandwidthLimiter] = None,
        listen_port_callback: Optional[Callable[[int], None]] = None,
        incoming_peer_callback: Optional[Callable[[int, str], None]] = None,
    ):
        self.torrent_path = torrent_path
        self.torrent = TorrentFile(torrent_path)
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
        self.tracker = TrackerClient(self.torrent, self.peer_id)

        self.active_peers: List[PeerConnection] = []
        self._worker_tasks: List[asyncio.Task] = []
        self._telemetry_task: Optional[asyncio.Task] = None
        self._main_task: Optional[asyncio.Task] = None
        self._prepare_cancel_event: Optional[threading.Event] = None
        self._prepare_pause_event: Optional[threading.Event] = None
        self._paused_from_state: Optional[str] = None

        self._seed_server: Optional[asyncio.AbstractServer] = None
        self._seed_client_writers: Set[asyncio.StreamWriter] = set()
        self._inbound_peer_records: Dict[int, dict] = {}
        self._seed_outbound_endpoints: Set[Tuple[str, int]] = set()
        self._download_endpoints: Set[Tuple[str, int]] = set()
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

        self._lpd = LocalPeerDiscovery(self.torrent.info_hash)
        self._dht = DHTClient(
            self.torrent.info_hash,
            private=self.torrent.private or not self.enable_dht,
            preferred_port=self.preferred_listen_port,
        )
        self.local_peers_discovered: int = 0
        self.error_message: str = ""

        # BEP-10/11 Peer Exchange telemetry and deduplication. PEX is disabled
        # for private torrents, matching the conventional private-torrent rule.
        self._pex_seen_endpoints: Set[Tuple[str, int]] = set()
        self._pex_last_at: float = 0.0
        self._pex_messages_received: int = 0
        self._pex_messages_sent: int = 0

        self.uploaded_bytes: int = 0

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

    def emit_snapshot(self):
        self._emit_snapshot()

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
    ):
        """Apply networking preferences to a live session.

        DHT/LPD can be started or stopped without tearing down peer workers. A
        changed TCP listen port is rebound while seeding; existing outbound
        peers remain untouched. PEX is toggled immediately for future exchange.
        """
        try:
            port = int(listen_port or 6881)
        except (TypeError, ValueError):
            port = 6881
        port = max(1, min(65535, port))

        port_changed = port != self.preferred_listen_port
        self.preferred_listen_port = port
        self.enable_dht = bool(enable_dht) and not self.torrent.private
        self.enable_pex = bool(enable_pex) and not self.torrent.private
        self.enable_lan_discovery = bool(enable_lan_discovery)

        for peer in list(self.active_peers):
            peer.enable_pex = self.enable_pex
            peer.advertise_dht = self.enable_dht

        # DHT's private flag is also used as its hard-disable switch.
        self._dht.private = bool(self.torrent.private or not self.enable_dht)
        self._dht.set_preferred_port(self.preferred_listen_port)

        if not self.enable_lan_discovery:
            await self._lpd.close()
        elif self.is_running and self.state in (SessionState.DOWNLOADING, SessionState.SEEDING):
            await self._lpd.start(
                listen_port=self._seed_port if self.state == SessionState.SEEDING else 0
            )

        if not self.enable_dht:
            await self._dht.close()
            self._dht.status = "Disabled"
            self._dht.last_error = "Disabled in Preferences"
        elif self.is_running and self.state in (SessionState.DOWNLOADING, SessionState.SEEDING):
            await self._dht.start(
                announce_port=self._seed_port if self.state == SessionState.SEEDING else 0
            )

        if (
            port_changed
            and self.is_running
            and self.state in (SessionState.DOWNLOADING, SessionState.SEEDING)
        ):
            await self._close_seed_server()
            await self._open_seed_server(self._run_token)
            if self.enable_lan_discovery:
                self._lpd.update_listen_port(self._seed_port)
            if self.enable_dht:
                self._dht.update_announce_port(self._seed_port)

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

        if self._seed_server:
            self._seed_server.close()

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

        self.piece_mgr.reset_inflight_requests()
        self.piece_mgr.save_resume_state(force=True)
        self._pause_activity_clock()
        self._record_speed_sample(0.0, 0.0)
        self._emit_snapshot()

    async def manual_announce(self) -> int:
        """Ask trackers for a fresh peer list without restarting the torrent."""
        if self.state not in (SessionState.DOWNLOADING, SessionState.SEEDING):
            return 0

        try:
            downloaded = self.piece_mgr.downloaded_bytes
            peers = await self.tracker.announce(
                uploaded=self.uploaded_bytes,
                downloaded=downloaded,
                left=max(0, self.torrent.total_length - downloaded),
                event=None,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # TrackerClient records per-source failures for the Sources tab. A
            # manual announce failure is not a terminal torrent error.
            self._emit_snapshot()
            return 0

        if self.state == SessionState.DOWNLOADING:
            self._start_download_workers(self._run_token, peers, source="Tracker")
        elif self.state == SessionState.SEEDING:
            self._start_outbound_seed_workers(self._run_token, peers, source="Tracker")
        self._emit_snapshot()
        return len(peers)

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
            down_kbps = float(getattr(peer, "download_speed_kbps", 0.0))
            up_kbps = float(getattr(peer, "upload_speed_kbps", 0.0))
            connected_at = float(getattr(peer, "connected_at", 0.0) or now)

            peers.append({
                "connection_id": f"out:{id(peer)}",
                "ip": str(peer.ip),
                "port": int(peer.port),
                "address": f"{peer.ip}:{peer.port}",
                "client": peer.client_name,
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
            down_kbps = float(record.get("download_speed_kbps", 0.0))
            up_kbps = float(record.get("upload_speed_kbps", 0.0))
            connected_at = float(record.get("connected_at", now))
            am_interested = bool(record.get("am_interested", False))
            peer_interested = bool(record.get("peer_interested", False))
            peer_choking = bool(record.get("peer_choking", True))
            am_choking = bool(record.get("am_choking", False))

            peers.append({
                "connection_id": str(record.get("connection_id", "")),
                "ip": str(record.get("ip", "?")),
                "port": int(record.get("port", 0) or 0),
                "address": str(record.get("address", "?")),
                "client": str(record.get("client", "Unknown")),
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

    def _piece_peer_bitfields(self) -> List[bytes]:
        bitfields: List[bytes] = []

        for peer in list(self.active_peers):
            if peer.bitfield:
                bitfields.append(bytes(peer.bitfield))

        for record in list(self._inbound_peer_records.values()):
            bitfield = record.get("bitfield", bytearray())
            if bitfield:
                try:
                    bitfields.append(bytes(bitfield))
                except Exception:
                    pass

        return bitfields

    def _build_piece_view_snapshot(self) -> dict:
        return self.piece_mgr.build_piece_telemetry(
            peer_bitfields=self._piece_peer_bitfields(),
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
        tracker_sources = self.tracker.get_source_snapshots()
        dht_source = self._dht.get_source_snapshot()
        if not self.enable_dht and not self.torrent.private:
            dht_source = dict(dht_source)
            dht_source.update(
                status="Disabled",
                last_error="Disabled in Preferences",
                detail="Disabled in Preferences",
            )
        pex_source = self._build_pex_source_snapshot()
        lan_source = self._lpd.get_source_snapshot()
        if not self.enable_lan_discovery:
            lan_source = dict(lan_source)
            lan_source.update(
                status="Disabled",
                last_error="Disabled in Preferences",
                detail="Disabled in Preferences",
            )
        sources = list(tracker_sources) + [dht_source, pex_source, lan_source]

        active_statuses = {"Active", "No Peers"}
        active_count = sum(
            1 for source in sources
            if str(source.get("status", "")) in active_statuses
        )
        problem_count = sum(
            1 for source in sources
            if str(source.get("status", "")) in {"Timeout", "Error"}
        )
        tracker_peer_count = sum(
            max(0, int(source.get("peers", 0) or 0))
            for source in tracker_sources
        )

        return {
            "sources": sources,
            "tracker_count": len(tracker_sources),
            "active_count": active_count,
            "problem_count": problem_count,
            "tracker_peers_last_seen": tracker_peer_count,
            "dht_peers_seen": int(dht_source.get("peers", 0) or 0),
            "pex_peers_seen": int(pex_source.get("peers", 0) or 0),
            "lan_peers_seen": int(lan_source.get("peers", 0) or 0),
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

    def _record_pex_payload(self, payload: dict) -> List[Tuple[str, int]]:
        if self.torrent.private or not self.enable_pex or not isinstance(payload, dict):
            return []
        added = self._normalise_peer_endpoints(payload.get("added", []))
        if added:
            self._pex_seen_endpoints.update(added)
        self._pex_messages_received += 1
        self._pex_last_at = time.monotonic()
        return added

    def _pex_export_endpoints(
        self,
        exclude: Optional[Tuple[str, int]] = None,
    ) -> List[Tuple[str, int]]:
        if self.torrent.private or not self.enable_pex:
            return []

        endpoints: List[Tuple[str, int]] = []
        seen: Set[Tuple[str, int]] = set()
        for peer in self.active_peers:
            if not peer.is_connected:
                continue
            endpoint = (str(peer.ip), int(peer.port))
            if exclude and endpoint == exclude:
                continue
            if endpoint in seen:
                continue
            seen.add(endpoint)
            endpoints.append(endpoint)

        # Include useful endpoints learned from other discovery mechanisms even
        # when a TCP connection has already ended. The PEX encoder itself caps
        # messages to a conservative maximum.
        for endpoint in list(self._pex_seen_endpoints):
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
        endpoints = self._pex_export_endpoints(exclude=(str(peer.ip), int(peer.port)))
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

        tracker_sources = [
            source
            for source in list(sources_view.get("sources") or [])
            if str(source.get("type", "")).upper() in {"HTTP", "UDP"}
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
            "total_bytes": total_bytes,
            "speed_kbps": speed_kbps,
            "upload_speed_kbps": upload_speed_kbps,
            "eta_seconds": eta_seconds,
            "elapsed_seconds": self.elapsed_active_seconds,
            "share_ratio": share_ratio,
            "connected_peers": self._connected_peer_count(),
            "swarm_seeders": swarm_seeders,
            "swarm_leechers": swarm_leechers,
            "swarm_availability": float(piece_view.get("swarm_availability", 0.0) or 0.0),
            "discovery_summary": " + ".join(discovery_parts) if discovery_parts else "None",
            "peers": peer_snapshots,
            "piece_view": piece_view,
            "file_view": file_view,
            "sources_view": sources_view,
            "speed_view": speed_view,
            "completed_pieces": self.piece_mgr.completed_pieces,
            "total_pieces": len(self.piece_mgr.pieces),
            "piece_length": int(self.torrent.piece_length),
            "listen_port": self._seed_port if self._seed_server else 0,
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
            await self._lpd.close()
            await self._dht.close()

            if local_telemetry_task and not local_telemetry_task.done():
                local_telemetry_task.cancel()
                await asyncio.gather(local_telemetry_task, return_exceptions=True)

            if self._telemetry_task is local_telemetry_task:
                self._telemetry_task = None

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
        """Keep discovering peers while a torrent is incomplete.

        Tracker, DHT, PEX and LAN discovery all feed the same peer-worker
        scheduler. Slow/dead public infrastructure therefore cannot block a
        peer learned from another source.
        """
        self.state = SessionState.DOWNLOADING
        self._pause_event.set()

        # Accept inbound BitTorrent peers while downloading as well as while
        # seeding. This makes automatic port mapping useful during the entire
        # transfer lifecycle and lets us upload already-verified pieces to the
        # swarm instead of remaining an outbound-only downloader.
        await self._open_seed_server(run_token)
        listen_port = self._seed_port if self._seed_server else 0

        if self.enable_lan_discovery:
            await self._lpd.start(listen_port=listen_port)
            self._lpd.update_listen_port(listen_port)
        if self.enable_dht:
            await self._dht.start(announce_port=listen_port)
            self._dht.update_announce_port(listen_port)
        self._emit_snapshot()

        tracker_task: Optional[asyncio.Task] = None
        dht_task: Optional[asyncio.Task] = None
        next_tracker_announce = 0.0
        next_dht_lookup = 0.0
        tracker_event: Optional[str] = "started"

        try:
            while self._is_current_run(run_token) and not self.piece_mgr.wanted_is_finished:
                await self._pause_event.wait()
                if not self._is_current_run(run_token):
                    break

                if self.state != SessionState.PAUSED:
                    self.state = SessionState.DOWNLOADING

                # Local peers are available without Internet tracker access.
                local_peers = self._lpd.drain_peers() if self.enable_lan_discovery else []
                if local_peers:
                    self.local_peers_discovered += len(local_peers)
                    self._start_download_workers(run_token, local_peers, source="LAN")
                    self._emit_snapshot()

                # Our minimal DHT listener can also receive direct announce_peer
                # traffic while an iterative lookup is not currently running.
                announced_dht_peers = self._dht.drain_peers() if self.enable_dht else []
                if announced_dht_peers:
                    self._start_download_workers(
                        run_token,
                        announced_dht_peers,
                        source="DHT",
                    )
                    self._emit_snapshot()

                now = time.monotonic()
                if tracker_task is None and now >= next_tracker_announce:
                    downloaded = self.piece_mgr.downloaded_bytes
                    left = max(0, self.torrent.total_length - downloaded)
                    tracker_task = asyncio.create_task(
                        self.tracker.fetch_peers(
                            uploaded=self.uploaded_bytes,
                            downloaded=downloaded,
                            left=left,
                            event=tracker_event,
                        )
                    )

                if (
                    self.enable_dht
                    and not self.torrent.private
                    and dht_task is None
                    and now >= next_dht_lookup
                ):
                    dht_task = asyncio.create_task(
                        self._dht.discover_peers(announce_port=listen_port)
                    )

                if tracker_task is not None and tracker_task.done():
                    try:
                        tracker_peers = tracker_task.result()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        tracker_peers = []

                    tracker_task = None
                    tracker_event = None
                    next_tracker_announce = time.monotonic() + 5 * 60
                    self._start_download_workers(run_token, tracker_peers, source="Tracker")

                if dht_task is not None and dht_task.done():
                    try:
                        dht_peers = dht_task.result()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        dht_peers = []

                    dht_task = None
                    next_dht_lookup = time.monotonic() + DHT_REFRESH_INTERVAL
                    self._start_download_workers(run_token, dht_peers, source="DHT")
                    self._emit_snapshot()

                self._worker_tasks = [
                    task for task in self._worker_tasks if not task.done()
                ]
                await asyncio.sleep(0.20)

        finally:
            for discovery_task in (tracker_task, dht_task):
                if discovery_task is not None and not discovery_task.done():
                    discovery_task.cancel()
                    await asyncio.gather(discovery_task, return_exceptions=True)


    def _start_download_workers(
        self,
        run_token: int,
        peers: List[Tuple[str, int]],
        source: str = "Tracker",
    ):
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

            endpoint = (str(ip), port)
            if endpoint in self._download_endpoints:
                continue

            self._download_endpoints.add(endpoint)
            task = asyncio.create_task(
                self._peer_worker(
                    run_token,
                    endpoint[0],
                    endpoint[1],
                    source=source,
                )
            )
            task.add_done_callback(
                lambda _task, ep=endpoint: self._download_endpoints.discard(ep)
            )
            self._worker_tasks.append(task)
            available_slots -= 1

    async def _request_one_block(
        self,
        peer: PeerConnection,
        owned_requests: List[Block],
    ) -> bool:
        if self.state != SessionState.DOWNLOADING:
            return False
        if peer.peer_choking or not peer.bitfield:
            return False

        block = self.piece_mgr.get_next_request(peer.bitfield)
        if not block:
            return False

        # Reserve ownership before waiting on the shared limiter so cancellation
        # or Stop cannot leave a throttled block permanently marked requested.
        owned_requests.append(block)

        try:
            if self._global_download_limiter is not None:
                await self._global_download_limiter.throttle(block.length)
            await self._download_limiter.throttle(block.length)

            if (
                self.state != SessionState.DOWNLOADING
                or not peer.is_connected
                or not self.piece_mgr.is_piece_wanted(block.piece_index)
            ):
                block.is_requested = False
                if block in owned_requests:
                    owned_requests.remove(block)
                return False

            if not await peer.send_request(
                block.piece_index,
                block.offset,
                block.length,
            ):
                block.is_requested = False
                if block in owned_requests:
                    owned_requests.remove(block)
                return False
        except asyncio.CancelledError:
            raise
        except Exception:
            block.is_requested = False
            if block in owned_requests:
                owned_requests.remove(block)
            return False

        return True

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

        if length <= 0 or length > BLOCK_SIZE:
            return False
        if not self._is_current_run(run_token):
            return False
        if self.state not in {SessionState.DOWNLOADING, SessionState.SEEDING}:
            return False

        block_data = await asyncio.to_thread(
            self.piece_mgr.read_block,
            piece_index,
            begin,
            length,
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
        ):
            return False

        if await peer.send_piece(piece_index, begin, block_data):
            self.uploaded_bytes += len(block_data)
            return True
        return False

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
                writer.write(frame)
                await writer.drain()
            except (ConnectionError, OSError, RuntimeError):
                stale_writers.append(writer)
            except Exception:
                stale_writers.append(writer)

        for writer in stale_writers:
            self._seed_client_writers.discard(writer)
            self._inbound_peer_records.pop(id(writer), None)

    async def _peer_worker(
        self,
        run_token: int,
        ip: str,
        port: int,
        source: str = "Tracker",
    ):
        peer = PeerConnection(
            ip,
            port,
            self.torrent.info_hash,
            self.peer_id,
            source=source,
            direction="Outgoing",
            advertise_dht=self.enable_dht,
            enable_pex=self.enable_pex,
        )
        owned_requests: List[Block] = []

        if not await peer.connect(timeout=4.0):
            return

        if not self._is_current_run(run_token):
            await peer.close()
            return

        self.active_peers.append(peer)

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
                    await peer.send_port(self._dht.local_udp_port)
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

                if self.state == SessionState.DOWNLOADING:
                    await self._request_one_block(peer, owned_requests)

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
                    piece_completed = self.piece_mgr.handle_block_received(
                        piece_idx,
                        offset,
                        block_bytes,
                    )
                    if piece_completed:
                        await self._broadcast_have(piece_idx, exclude_peer=peer)

                    owned_requests[:] = [
                        block
                        for block in owned_requests
                        if not (
                            block.piece_index == piece_idx
                            and block.offset == offset
                        )
                    ]

                    if self.state == SessionState.DOWNLOADING:
                        await self._request_one_block(peer, owned_requests)

                elif msg_type == "HAVE":
                    self._apply_have_to_peer(peer, int(data))

                elif msg_type == "UNCHOKE":
                    for _ in range(4):
                        if self.state != SessionState.DOWNLOADING:
                            break
                        if not await self._request_one_block(peer, owned_requests):
                            break

                elif msg_type == "REQUEST":
                    piece_index, begin, length = data
                    await self._serve_piece_request(
                        peer,
                        run_token,
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
                    pex_peers = self._record_pex_payload(data)
                    if pex_peers:
                        self._start_download_workers(
                            run_token,
                            pex_peers,
                            source="PEX",
                        )
                        self._emit_snapshot()

                elif msg_type == "EXTENDED_HANDSHAKE":
                    await self._maybe_send_pex(peer)

                elif msg_type == "PORT":
                    if self.enable_dht and not self.torrent.private:
                        self._dht.add_known_node((str(peer.ip), int(data)))

        except asyncio.CancelledError:
            pass
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            # Remote peers can disconnect at any point.  That is normal swarm
            # churn and should retire this worker quietly.
            pass

        finally:
            self.piece_mgr.release_requests(owned_requests)

            if peer in self.active_peers:
                self.active_peers.remove(peer)

            await peer.close()

    async def _run_seeding(self, run_token: int, completion_event: bool):
        if not self._is_current_run(run_token) or not self.piece_mgr.is_finished:
            return

        self.state = SessionState.SEEDING
        self._pause_event.set()
        await self._open_seed_server(run_token)
        listen_port = self._seed_port if self._seed_server else 0
        if self.enable_lan_discovery:
            await self._lpd.start(listen_port=listen_port)
            self._lpd.update_listen_port(listen_port)
        if self.enable_dht:
            await self._dht.start(announce_port=listen_port)
            self._dht.update_announce_port(listen_port)
        self._emit_snapshot()

        first_event = "completed" if completion_event else "started"
        next_announce = 0.0
        next_dht_lookup = 0.0
        announce_event: Optional[str] = first_event
        dht_task: Optional[asyncio.Task] = None

        try:
            while self._is_current_run(run_token):
                await self._pause_event.wait()
                if not self._is_current_run(run_token):
                    break

                if self.state != SessionState.PAUSED:
                    self.state = SessionState.SEEDING

                local_peers = self._lpd.drain_peers() if self.enable_lan_discovery else []
                if local_peers:
                    self.local_peers_discovered += len(local_peers)
                    self._start_outbound_seed_workers(run_token, local_peers, source="LAN")
                    self._emit_snapshot()

                announced_dht_peers = self._dht.drain_peers() if self.enable_dht else []
                if announced_dht_peers:
                    self._start_outbound_seed_workers(
                        run_token,
                        announced_dht_peers,
                        source="DHT",
                    )
                    self._emit_snapshot()

                now = time.monotonic()
                if now >= next_announce:
                    try:
                        peers = await self.tracker.announce(
                            uploaded=self.uploaded_bytes,
                            downloaded=self.piece_mgr.downloaded_bytes,
                            left=0,
                            event=announce_event,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        peers = []

                    announce_event = None
                    next_announce = time.monotonic() + 15 * 60
                    self._start_outbound_seed_workers(run_token, peers, source="Tracker")

                if (
                    self.enable_dht
                    and not self.torrent.private
                    and dht_task is None
                    and now >= next_dht_lookup
                ):
                    dht_task = asyncio.create_task(
                        self._dht.discover_peers(announce_port=listen_port)
                    )

                if dht_task is not None and dht_task.done():
                    try:
                        dht_peers = dht_task.result()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        dht_peers = []
                    dht_task = None
                    next_dht_lookup = time.monotonic() + DHT_REFRESH_INTERVAL
                    self._start_outbound_seed_workers(run_token, dht_peers, source="DHT")
                    self._emit_snapshot()

                self._worker_tasks = [task for task in self._worker_tasks if not task.done()]
                await asyncio.sleep(0.5)

        finally:
            if dht_task is not None and not dht_task.done():
                dht_task.cancel()
                await asyncio.gather(dht_task, return_exceptions=True)


    async def _open_seed_server(self, run_token: int):
        if self._seed_server:
            return

        # Try the user-configured listening port first, then ten consecutive
        # fallbacks if another application already owns it.
        preferred = max(1, min(65535, int(self.preferred_listen_port or 6881)))
        candidates = [preferred]
        for offset in range(1, 11):
            candidate = preferred + offset
            if candidate <= 65535:
                candidates.append(candidate)

        for port in candidates:
            try:
                server = await asyncio.start_server(
                    lambda reader, writer: asyncio.create_task(
                        self._handle_inbound_seed_peer(run_token, reader, writer)
                    ),
                    host="0.0.0.0",
                    port=port,
                )
            except OSError:
                continue

            self._seed_server = server
            self._seed_port = port
            self.tracker.port = port
            if self._listen_port_callback:
                try:
                    self._listen_port_callback(port)
                except Exception:
                    pass
            return

        # Outbound seeding can still work if no inbound listener is available.
        self._seed_port = preferred
        self.tracker.port = preferred
        if self._listen_port_callback:
            try:
                self._listen_port_callback(0)
            except Exception:
                pass

    async def _close_seed_server(self):
        if self._seed_server:
            self._seed_server.close()
            try:
                await self._seed_server.wait_closed()
            except Exception:
                pass
            self._seed_server = None

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
    ):
        available_slots = max(0, self.max_peers - self._connected_peer_count())
        if available_slots <= 0:
            return

        for endpoint in peers:
            if available_slots <= 0:
                break
            if endpoint in self._seed_outbound_endpoints:
                continue

            ip, port = endpoint
            self._seed_outbound_endpoints.add(endpoint)
            task = asyncio.create_task(
                self._seed_peer_worker(run_token, ip, port, source=source)
            )
            self._worker_tasks.append(task)
            available_slots -= 1

    async def _seed_peer_worker(
        self,
        run_token: int,
        ip: str,
        port: int,
        source: str = "Tracker",
    ):
        endpoint = (ip, port)
        peer = PeerConnection(
            ip,
            port,
            self.torrent.info_hash,
            self.peer_id,
            source=source,
            direction="Outgoing",
            advertise_dht=self.enable_dht,
            enable_pex=self.enable_pex,
        )

        try:
            if not await peer.connect(timeout=4.0):
                return
            if not self._is_current_run(run_token):
                return

            self.active_peers.append(peer)
            if not self.torrent.private:
                await peer.send_extended_handshake(
                    listen_port=self._seed_port if self._seed_server else 0,
                    metadata_size=len(self.torrent.raw_info_bytes),
                )
                if not peer.is_connected:
                    return
                if self.enable_dht:
                    await peer.send_port(self._dht.local_udp_port)
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
                if msg_type == "HAVE":
                    self._apply_have_to_peer(peer, int(data))
                    continue

                if msg_type == "METADATA":
                    await self._handle_metadata_message(peer, data)
                    continue

                if msg_type == "PEX":
                    pex_peers = self._record_pex_payload(data)
                    if pex_peers:
                        self._start_outbound_seed_workers(
                            run_token,
                            pex_peers,
                            source="PEX",
                        )
                        self._emit_snapshot()
                    continue

                if msg_type == "EXTENDED_HANDSHAKE":
                    await self._maybe_send_pex(peer)
                    continue

                if msg_type == "PORT":
                    if self.enable_dht and not self.torrent.private:
                        self._dht.add_known_node((str(peer.ip), int(data)))
                    continue

                if msg_type == "REQUEST" and self.state == SessionState.SEEDING:
                    piece_index, begin, length = data
                    await self._serve_piece_request(
                        peer,
                        run_token,
                        piece_index,
                        begin,
                        length,
                    )

        except asyncio.CancelledError:
            pass
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            if peer in self.active_peers:
                self.active_peers.remove(peer)
            await peer.close()
            self._seed_outbound_endpoints.discard(endpoint)

    async def _handle_inbound_seed_peer(
        self,
        run_token: int,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        registered = False

        try:
            pstrlen_raw = await asyncio.wait_for(reader.readexactly(1), timeout=8.0)
            pstrlen = pstrlen_raw[0]
            if pstrlen != 19:
                return

            remainder = await asyncio.wait_for(
                reader.readexactly(pstrlen + 48),
                timeout=8.0,
            )
            protocol = remainder[:pstrlen]
            remote_reserved = bytes(remainder[pstrlen:pstrlen + 8])
            remote_supports_extensions = reserved_supports_extensions(remote_reserved)
            remote_supports_dht = reserved_supports_dht(remote_reserved)
            info_hash = remainder[pstrlen + 8:pstrlen + 28]
            remote_peer_id = bytes(remainder[pstrlen + 28:pstrlen + 48])

            if protocol != b"BitTorrent protocol" or info_hash != self.torrent.info_hash:
                return
            if not self._is_current_run(run_token):
                return
            if self.state not in {SessionState.DOWNLOADING, SessionState.SEEDING}:
                return

            response_reserved = build_reserved_bytes(
                enable_extensions=not self.torrent.private,
                enable_dht=self.enable_dht and not self.torrent.private,
            )
            response = (
                bytes([19])
                + b"BitTorrent protocol"
                + response_reserved
                + self.torrent.info_hash
                + self.peer_id
            )
            writer.write(response)

            bitfield = self.piece_mgr.completed_bitfield()
            writer.write(
                struct.pack(">IB", 1 + len(bitfield), PeerMessageID.BITFIELD)
                + bitfield
            )
            writer.write(struct.pack(">IB", 1, PeerMessageID.UNCHOKE))
            if remote_supports_extensions and not self.torrent.private:
                writer.write(
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
                and self._dht.local_udp_port
            ):
                writer.write(
                    struct.pack(">IBH", 3, PeerMessageID.PORT, self._dht.local_udp_port)
                )
            await writer.drain()

            self._seed_client_writers.add(writer)

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
                "address": f"{peer_ip}:{peer_port}" if peer_port else peer_ip,
                "client": identify_peer_client(remote_peer_id),
                "source": "Incoming",
                "direction": "Incoming",
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
                length_raw = await asyncio.wait_for(reader.readexactly(4), timeout=120.0)
                (message_length,) = struct.unpack(">I", length_raw)

                if message_length == 0:
                    continue
                if message_length > 1024 * 1024:
                    break

                payload = await asyncio.wait_for(
                    reader.readexactly(message_length),
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
                    continue
                if msg_id == PeerMessageID.HAVE and len(body) == 4:
                    (piece_index,) = struct.unpack(">I", body)
                    total_pieces = len(self.piece_mgr.pieces)
                    if 0 <= piece_index < total_pieces:
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
                        self._dht.add_known_node((peer_ip, remote_dht_port))
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
                                    exclude=(peer_ip, peer_port) if peer_port else None
                                )
                            )
                            writer.write(build_extended_message(remote_pex_id, pex_payload))
                            await writer.drain()
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
                        pex_peers = self._record_pex_payload(pex_payload)
                        if pex_peers:
                            if self.state == SessionState.DOWNLOADING:
                                self._start_download_workers(
                                    run_token,
                                    pex_peers,
                                    source="PEX",
                                )
                            else:
                                self._start_outbound_seed_workers(
                                    run_token,
                                    pex_peers,
                                    source="PEX",
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
                                writer.write(
                                    build_extended_message(
                                        remote_metadata_id,
                                        header_bytes + block,
                                    )
                                )
                            else:
                                writer.write(
                                    build_extended_message(
                                        remote_metadata_id,
                                        Bencode.encode(
                                            {b"msg_type": 2, b"piece": metadata_piece}
                                        ),
                                    )
                                )
                            await writer.drain()
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
                if length <= 0 or length > BLOCK_SIZE:
                    continue

                block_data = await asyncio.to_thread(
                    self.piece_mgr.read_block,
                    piece_index,
                    begin,
                    length,
                )
                if not block_data:
                    continue

                if self._global_upload_limiter is not None:
                    await self._global_upload_limiter.throttle(len(block_data))
                await self._upload_limiter.throttle(len(block_data))

                if (
                    not self._is_current_run(run_token)
                    or self.state not in {SessionState.DOWNLOADING, SessionState.SEEDING}
                ):
                    continue

                piece_payload = struct.pack(">II", piece_index, begin) + block_data
                writer.write(
                    struct.pack(">IB", 1 + len(piece_payload), PeerMessageID.PIECE)
                    + piece_payload
                )
                await writer.drain()
                self.uploaded_bytes += len(block_data)
                inbound_record["uploaded_bytes"] = int(
                    inbound_record.get("uploaded_bytes", 0)
                ) + len(block_data)
                inbound_record["last_activity_at"] = time.monotonic()

        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
            pass
        except asyncio.CancelledError:
            pass
        finally:
            if registered:
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

                self._emit_snapshot(drop_if_ui_busy=True)

        except asyncio.CancelledError:
            pass
