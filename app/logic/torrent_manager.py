# app/logic/torrent_manager.py

import asyncio
import queue
import threading
from typing import Dict, Optional
from app.logic.session import TorrentSession, SessionState


class TorrentCommand:
    START = "START"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    STOP = "STOP"


class TorrentManager:
    _instance: Optional["TorrentManager"] = None

    def __new__(cls, ui_queue: Optional[queue.Queue] = None):
        if cls._instance is None:
            cls._instance = super(TorrentManager, cls).__new__(cls)
            cls._instance.ui_queue = ui_queue or queue.Queue()
            cls._instance.sessions: Dict[str, TorrentSession] = {}
            cls._instance._cmd_queue: Optional[asyncio.Queue] = None
            cls._instance._loop: Optional[asyncio.AbstractEventLoop] = None
            cls._instance._thread: Optional[threading.Thread] = None
            cls._instance._running = False
            cls._instance._engine_ready = threading.Event()
            cls._instance._sessions_lock = threading.Lock()
        elif ui_queue is not None:
            # Keep the singleton attached to the application's real UI queue.
            cls._instance.ui_queue = ui_queue

        return cls._instance

    @classmethod
    def get_instance(cls) -> "TorrentManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start_engine(self):
        if self._running:
            self._engine_ready.wait(timeout=5.0)
            return

        self._running = True
        self._engine_ready.clear()
        self._thread = threading.Thread(
            target=self._run_event_loop,
            daemon=True,
            name="SalixTorrentAsyncEngine",
        )
        self._thread.start()

        # main.py sends its first START command immediately after start_engine().
        # Waiting here removes the startup race where that command could be lost
        # before _loop/_cmd_queue existed.
        if not self._engine_ready.wait(timeout=5.0):
            raise RuntimeError("Salix_T async engine did not become ready.")

    def _run_event_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._engine_main())
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()

            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )

            self._loop.close()
            self._engine_ready.clear()

    async def _engine_main(self):
        self._cmd_queue = asyncio.Queue()
        self._engine_ready.set()

        while self._running:
            action, info_hash = await self._cmd_queue.get()

            try:
                with self._sessions_lock:
                    session = self.sessions.get(info_hash)

                if not session:
                    continue

                if action == TorrentCommand.START:
                    if not session.is_running:
                        asyncio.create_task(session.start())

                elif action == TorrentCommand.PAUSE:
                    session.pause()

                elif action == TorrentCommand.RESUME:
                    if session.state == SessionState.PAUSED:
                        session.resume()

                    # A paused session can outlive its main coroutine (for
                    # example after every peer disconnects). In that case,
                    # Resume must both restore the state and start a new run.
                    if not session.is_running:
                        asyncio.create_task(session.start())

                elif action == TorrentCommand.STOP:
                    session.stop()

            finally:
                self._cmd_queue.task_done()

    def add_torrent(self, torrent_path: str, max_peers: int = 25) -> TorrentSession:
        # TorrentSession construction is now lightweight: it parses .torrent
        # metadata and creates Piece descriptors, but does not hash the payload
        # file or allocate every block.
        new_session = TorrentSession(
            torrent_path,
            ui_queue=self.ui_queue,
            max_peers=max_peers,
        )
        info_hash = new_session.torrent.hex_info_hash

        with self._sessions_lock:
            existing_session = self.sessions.get(info_hash)
            if existing_session:
                existing_session.emit_snapshot()
                return existing_session

            self.sessions[info_hash] = new_session

        # Put an Idle row into the UI immediately.  The background engine will
        # later change it to Checking/Downloading/Paused/Stopped as appropriate.
        new_session.emit_snapshot()
        return new_session

    def _send_cmd(self, action: str, info_hash: str):
        if not self._running:
            self.start_engine()

        if not self._engine_ready.wait(timeout=5.0):
            return

        if self._loop and self._cmd_queue and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(
                self._cmd_queue.put_nowait,
                (action, info_hash),
            )

    def start_torrent(self, info_hash: str):
        self._send_cmd(TorrentCommand.START, info_hash)

    def pause_torrent(self, info_hash: str):
        self._send_cmd(TorrentCommand.PAUSE, info_hash)

    def resume_torrent(self, info_hash: str):
        self._send_cmd(TorrentCommand.RESUME, info_hash)

    def stop_torrent(self, info_hash: str):
        self._send_cmd(TorrentCommand.STOP, info_hash)
