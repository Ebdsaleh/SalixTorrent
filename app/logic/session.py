# app/logic/session.py

import asyncio
import queue
import random
import threading
from typing import List, Optional
from app.logic.torrent_file import TorrentFile
from app.logic.tracker import TrackerClient
from app.logic.peer import PeerConnection
from app.logic.piece_manager import Block, PieceManager


class SessionState:
    IDLE = "Idle"
    CHECKING = "Checking"
    DOWNLOADING = "Downloading"
    PAUSED = "Paused"
    STOPPED = "Stopped"
    COMPLETED = "Completed"


class TorrentSession:
    def __init__(
        self,
        torrent_path: str,
        ui_queue: Optional[queue.Queue] = None,
        max_peers: int = 25,
    ):
        self.torrent_path = torrent_path
        self.torrent = TorrentFile(torrent_path)
        self.ui_queue = ui_queue or queue.Queue()
        self.max_peers = max_peers

        random_id = "".join(str(random.randint(0, 9)) for _ in range(12)).encode("ascii")
        self.peer_id = b"-ST0001-" + random_id

        # PieceManager construction is now intentionally cheap.  Disk checking
        # happens later in a worker thread from start().
        self.piece_mgr = PieceManager(self.torrent)
        self.tracker = TrackerClient(self.torrent, self.peer_id)

        self.active_peers: List[PeerConnection] = []
        self._worker_tasks: List[asyncio.Task] = []
        self._telemetry_task: Optional[asyncio.Task] = None
        self._main_task: Optional[asyncio.Task] = None
        self._prepare_cancel_event: Optional[threading.Event] = None
        self._prepare_pause_event: Optional[threading.Event] = None
        self._paused_from_state: Optional[str] = None

        self.state = SessionState.IDLE
        self.is_running = False

        self._pause_event = asyncio.Event()
        self._pause_event.set()

        # Every start/stop transition changes this token.  Old async work can
        # therefore never overwrite the state of a newer run.
        self._run_token = 0

    def emit_snapshot(self):
        self._emit_snapshot()

    def pause(self):
        if self.state not in (SessionState.CHECKING, SessionState.DOWNLOADING):
            return

        self._paused_from_state = self.state
        self.state = SessionState.PAUSED
        self._pause_event.clear()

        # The disk checker runs in asyncio.to_thread(), so it needs a normal
        # threading.Event rather than an asyncio.Event.
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
        # Invalidate the currently running start() coroutine before cancelling
        # its tasks.  This prevents an old finally block from changing a new run.
        self._run_token += 1
        self.state = SessionState.STOPPED
        self.is_running = False
        self._paused_from_state = None
        self._pause_event.set()

        if self._prepare_cancel_event:
            self._prepare_cancel_event.set()
        if self._prepare_pause_event:
            # Wake a paused checker so it can observe cancellation immediately.
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

        for peer in list(self.active_peers):
            if peer.writer:
                try:
                    peer.writer.close()
                except Exception:
                    pass

        # A stopped peer no longer owns any outstanding block request.
        self.piece_mgr.reset_inflight_requests()
        self.piece_mgr.save_resume_state()
        self._emit_snapshot()

    def _is_current_run(self, run_token: int) -> bool:
        return self.is_running and run_token == self._run_token

    def _state_label(self) -> str:
        check_percent = self.piece_mgr.check_progress * 100.0

        if self.state == SessionState.CHECKING:
            return f"Checking {check_percent:.0f}%"

        if (
            self.state == SessionState.PAUSED
            and self._paused_from_state == SessionState.CHECKING
        ):
            return f"Paused (Checking {check_percent:.0f}%)"

        return self.state

    def _build_snapshot(self, speed_kbps: float = 0.0) -> dict:
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
            "total_bytes": self.torrent.total_length,
            "speed_kbps": speed_kbps,
            "connected_peers": (
                len(self.active_peers)
                if self.state == SessionState.DOWNLOADING
                else 0
            ),
            "completed_pieces": self.piece_mgr.completed_pieces,
            "total_pieces": len(self.piece_mgr.pieces),
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

        local_worker_tasks: List[asyncio.Task] = []
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

                if not prepared or not self._is_current_run(run_token):
                    return

            if self.piece_mgr.is_finished:
                self.state = SessionState.COMPLETED
                self.is_running = False
                self._emit_snapshot()
                return

            # If the user paused while the disk check was running, wait here.
            if self.state != SessionState.PAUSED:
                self.state = SessionState.DOWNLOADING
                self._pause_event.set()
                self._emit_snapshot()

            await self._pause_event.wait()
            if not self._is_current_run(run_token):
                return

            if self.state != SessionState.PAUSED:
                self.state = SessionState.DOWNLOADING

            local_telemetry_task = asyncio.create_task(
                self._telemetry_loop(run_token)
            )
            self._telemetry_task = local_telemetry_task

            downloaded = self.piece_mgr.downloaded_bytes
            left = max(0, self.torrent.total_length - downloaded)

            discovered_peers = await self.tracker.fetch_peers(
                downloaded=downloaded,
                left=left,
            )

            if not self._is_current_run(run_token):
                return

            # Pause may have been pressed while trackers were being queried.
            await self._pause_event.wait()
            if not self._is_current_run(run_token):
                return

            local_worker_tasks = [
                asyncio.create_task(self._peer_worker(run_token, ip, port))
                for ip, port in discovered_peers[:self.max_peers]
            ]
            self._worker_tasks = local_worker_tasks

            if local_worker_tasks:
                await asyncio.gather(*local_worker_tasks, return_exceptions=True)

        except asyncio.CancelledError:
            # STOP intentionally cancels the session task.  State was already
            # set by stop(), so no noisy traceback is required.
            pass

        finally:
            for task in local_worker_tasks:
                if not task.done():
                    task.cancel()

            if local_worker_tasks:
                await asyncio.gather(*local_worker_tasks, return_exceptions=True)

            if local_telemetry_task and not local_telemetry_task.done():
                local_telemetry_task.cancel()
                await asyncio.gather(local_telemetry_task, return_exceptions=True)

            if self._telemetry_task is local_telemetry_task:
                self._telemetry_task = None

            if run_token == self._run_token:
                self.is_running = False
                self._worker_tasks = []

                if self.piece_mgr.is_finished:
                    self.state = SessionState.COMPLETED
                elif self.state not in (SessionState.PAUSED, SessionState.STOPPED):
                    self.state = SessionState.STOPPED

                self.piece_mgr.reset_inflight_requests()
                self.piece_mgr.save_resume_state()
                self._emit_snapshot()

            if self._main_task is asyncio.current_task():
                self._main_task = None

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

        try:
            await peer.send_request(block.piece_index, block.offset, block.length)
        except Exception:
            block.is_requested = False
            return False

        owned_requests.append(block)
        return True

    async def _peer_worker(self, run_token: int, ip: str, port: int):
        peer = PeerConnection(ip, port, self.torrent.info_hash, self.peer_id)
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

                    # This block is no longer owned by this peer request list.
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

    async def _telemetry_loop(self, run_token: int):
        last_downloaded = self.piece_mgr.downloaded_bytes

        try:
            while self._is_current_run(run_token):
                await asyncio.sleep(0.5)
                current_downloaded = self.piece_mgr.downloaded_bytes

                if self.state == SessionState.DOWNLOADING:
                    speed_bps = max(0.0, (current_downloaded - last_downloaded) / 0.5)
                else:
                    speed_bps = 0.0

                last_downloaded = current_downloaded

                self.ui_queue.put(
                    self._build_snapshot(speed_kbps=speed_bps / 1024)
                )

        except asyncio.CancelledError:
            pass
