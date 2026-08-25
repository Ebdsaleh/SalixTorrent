# app/logic/session.py

import asyncio
import os
import queue
import random
import struct
import threading
import time
from typing import Dict, List, Optional, Set, Tuple

from app.logic.local_peer_discovery import LocalPeerDiscovery
from app.logic.peer import PeerConnection, PeerMessageID, identify_peer_client
from app.logic.piece_manager import BLOCK_SIZE, Block, PieceManager
from app.logic.torrent_file import TorrentFile
from app.logic.tracker import TrackerClient

RATE_UNIT_MULTIPLIERS = {
    "KB/s": 1024.0,
    "MB/s": 1024.0 * 1024.0,
    "kbps": 1000.0 / 8.0,
    "Mbps": 1000.0 * 1000.0 / 8.0,
}


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
        self._seed_port: int = 6881

        self._lpd = LocalPeerDiscovery(self.torrent.info_hash)
        self.local_peers_discovered: int = 0
        self.error_message: str = ""

        self.uploaded_bytes: int = 0

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

        self.state = SessionState.IDLE
        self.is_running = False

        self._pause_event = asyncio.Event()
        self._pause_event.set()

        # Old asynchronous work is prevented from overwriting a newer run.
        self._run_token = 0
        self._fast_resume_notice_shown = False

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
        self._emit_snapshot()

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

    def _build_snapshot(
        self,
        speed_kbps: float = 0.0,
        upload_speed_kbps: float = 0.0,
    ) -> dict:
        return {
            "type": "TRANSFER_STATS",
            "info_hash": self.torrent.hex_info_hash,
            "torrent_name": self.torrent.name,
            "state": self.state,
            "state_label": self._state_label(),
            "progress": self.piece_mgr.progress,
            "checking_progress": self.piece_mgr.check_progress,
            "checked_pieces": self.piece_mgr.check_checked_pieces,
            "check_total_pieces": self.piece_mgr.check_total_pieces,
            "fast_resume_used": self.piece_mgr.fast_resume_used,
            "downloaded_bytes": self.piece_mgr.downloaded_bytes,
            "uploaded_bytes": self.uploaded_bytes,
            "total_bytes": self.torrent.total_length,
            "speed_kbps": speed_kbps,
            "upload_speed_kbps": upload_speed_kbps,
            "connected_peers": self._connected_peer_count(),
            "peers": self._build_peer_snapshots(),
            "completed_pieces": self.piece_mgr.completed_pieces,
            "total_pieces": len(self.piece_mgr.pieces),
            "listen_port": self._seed_port if self._seed_server else 0,
            "storage_mode": self.piece_mgr.storage_mode,
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
        }

    def _emit_snapshot(self):
        self.ui_queue.put(self._build_snapshot())

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
                elif self.state not in (SessionState.PAUSED, SessionState.STOPPED):
                    self.state = SessionState.STOPPED

                self.piece_mgr.reset_inflight_requests()
                self.piece_mgr.save_resume_state(force=True)
                self._emit_snapshot()

            if self._main_task is asyncio.current_task():
                self._main_task = None

    async def _run_downloading(self, run_token: int):
        """Keep discovering peers while a torrent is incomplete.

        Tracker requests run in the background so a slow/dead tracker cannot
        prevent a LAN peer discovered through BEP-14 multicast from being used
        immediately. Unlike the original one-shot peer fetch, this loop keeps
        a stopped swarm alive long enough for peers to appear later.
        """
        self.state = SessionState.DOWNLOADING
        self._pause_event.set()
        await self._lpd.start(listen_port=0)
        self._emit_snapshot()

        tracker_task: Optional[asyncio.Task] = None
        next_tracker_announce = 0.0
        tracker_event: Optional[str] = "started"

        try:
            while self._is_current_run(run_token) and not self.piece_mgr.is_finished:
                await self._pause_event.wait()
                if not self._is_current_run(run_token):
                    break

                if self.state != SessionState.PAUSED:
                    self.state = SessionState.DOWNLOADING

                # Local peers are available without Internet tracker access.
                local_peers = self._lpd.drain_peers()
                if local_peers:
                    self.local_peers_discovered += len(local_peers)
                    self._start_download_workers(run_token, local_peers, source="LAN")
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

                self._worker_tasks = [
                    task for task in self._worker_tasks if not task.done()
                ]
                await asyncio.sleep(0.20)

        finally:
            if tracker_task is not None and not tracker_task.done():
                tracker_task.cancel()
                await asyncio.gather(tracker_task, return_exceptions=True)

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
            await self._download_limiter.throttle(block.length)

            if self.state != SessionState.DOWNLOADING or not peer.is_connected:
                block.is_requested = False
                if block in owned_requests:
                    owned_requests.remove(block)
                return False

            await peer.send_request(block.piece_index, block.offset, block.length)
        except asyncio.CancelledError:
            raise
        except Exception:
            block.is_requested = False
            if block in owned_requests:
                owned_requests.remove(block)
            return False

        return True

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
        )
        owned_requests: List[Block] = []

        if not await peer.connect(timeout=4.0):
            return

        if not self._is_current_run(run_token):
            await peer.close()
            return

        self.active_peers.append(peer)
        await peer.send_interested()

        try:
            while self._is_current_run(run_token) and not self.piece_mgr.is_finished:
                await self._pause_event.wait()

                if not self._is_current_run(run_token):
                    break

                if self.state == SessionState.DOWNLOADING:
                    await self._request_one_block(peer, owned_requests)

                try:
                    message = await asyncio.wait_for(peer.read_message(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if not message:
                    break

                msg_type, data = message

                if msg_type == "PIECE":
                    piece_idx, offset, block_bytes = data
                    self.piece_mgr.handle_block_received(
                        piece_idx,
                        offset,
                        block_bytes,
                    )

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

        except asyncio.CancelledError:
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
        await self._lpd.start(listen_port=self._seed_port if self._seed_server else 0)
        self._lpd.update_listen_port(self._seed_port if self._seed_server else 0)
        self._emit_snapshot()

        first_event = "completed" if completion_event else "started"
        next_announce = 0.0
        announce_event: Optional[str] = first_event

        while self._is_current_run(run_token):
            await self._pause_event.wait()
            if not self._is_current_run(run_token):
                break

            # Resume returns us to the state that was paused.
            if self.state != SessionState.PAUSED:
                self.state = SessionState.SEEDING

            local_peers = self._lpd.drain_peers()
            if local_peers:
                self.local_peers_discovered += len(local_peers)
                self._start_outbound_seed_workers(run_token, local_peers, source="LAN")
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

            # Remove completed outbound tasks from the manager list.
            self._worker_tasks = [task for task in self._worker_tasks if not task.done()]
            await asyncio.sleep(0.5)

    async def _open_seed_server(self, run_token: int):
        if self._seed_server:
            return

        # Try the conventional BitTorrent port first, then a small fallback
        # range in case another application already owns it.
        for port in range(6881, 6892):
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
            return

        # Outbound seeding can still work even if no inbound listening port is
        # available. Keep the conventional announce port as a fallback value.
        self._seed_port = self.tracker.port

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
        )

        try:
            if not await peer.connect(timeout=4.0):
                return
            if not self._is_current_run(run_token):
                return

            self.active_peers.append(peer)
            await peer.send_bitfield(self.piece_mgr.completed_bitfield())
            await peer.send_unchoke()

            while self._is_current_run(run_token):
                await self._pause_event.wait()
                if not self._is_current_run(run_token):
                    break

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

                if msg_type == "REQUEST" and self.state == SessionState.SEEDING:
                    piece_index, begin, length = data
                    block_data = await asyncio.to_thread(
                        self.piece_mgr.read_block,
                        piece_index,
                        begin,
                        length,
                    )
                    if block_data:
                        await self._upload_limiter.throttle(len(block_data))

                        if (
                            self._is_current_run(run_token)
                            and self.state == SessionState.SEEDING
                            and peer.is_connected
                        ):
                            await peer.send_piece(piece_index, begin, block_data)
                            self.uploaded_bytes += len(block_data)

        except asyncio.CancelledError:
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
            info_hash = remainder[pstrlen + 8:pstrlen + 28]
            remote_peer_id = bytes(remainder[pstrlen + 28:pstrlen + 48])

            if protocol != b"BitTorrent protocol" or info_hash != self.torrent.info_hash:
                return
            if not self._is_current_run(run_token) or not self.piece_mgr.is_finished:
                return

            response = (
                bytes([19])
                + b"BitTorrent protocol"
                + (b"\x00" * 8)
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

                if msg_id != PeerMessageID.REQUEST or len(body) != 12:
                    continue

                inbound_record["peer_interested"] = True
                await self._pause_event.wait()
                if not self._is_current_run(run_token):
                    break
                if self.state != SessionState.SEEDING:
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

                await self._upload_limiter.throttle(len(block_data))

                if not self._is_current_run(run_token) or self.state != SessionState.SEEDING:
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
                await asyncio.sleep(0.5)

                current_downloaded = self.piece_mgr.downloaded_bytes
                current_uploaded = self.uploaded_bytes

                if self.state == SessionState.DOWNLOADING:
                    download_speed_bps = max(
                        0.0,
                        (current_downloaded - last_downloaded) / 0.5,
                    )
                else:
                    download_speed_bps = 0.0

                if self.state == SessionState.SEEDING:
                    upload_speed_bps = max(
                        0.0,
                        (current_uploaded - last_uploaded) / 0.5,
                    )
                else:
                    upload_speed_bps = 0.0

                last_downloaded = current_downloaded
                last_uploaded = current_uploaded
                self._sample_peer_speeds(0.5)

                self.ui_queue.put(
                    self._build_snapshot(
                        speed_kbps=download_speed_bps / 1024,
                        upload_speed_kbps=upload_speed_bps / 1024,
                    )
                )

        except asyncio.CancelledError:
            pass


