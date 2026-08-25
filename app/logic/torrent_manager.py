# app/logic/torrent_manager.py

import asyncio
import json
import os
import queue
import shutil
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional

from app.logic.session import (
    TorrentSession,
    SessionState,
    TORRENT_PRIORITY_HIGH,
    TORRENT_PRIORITY_NORMAL,
    TORRENT_PRIORITY_LOW,
    TORRENT_PRIORITIES,
)


class TorrentCommand:
    START = "START"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    STOP = "STOP"
    REMOVE = "REMOVE"
    SET_LIMITS = "SET_LIMITS"
    SET_FILE_PRIORITY = "SET_FILE_PRIORITY"
    SET_TORRENT_PRIORITY = "SET_TORRENT_PRIORITY"
    SET_QUEUE_LIMIT = "SET_QUEUE_LIMIT"
    REBALANCE_QUEUE = "REBALANCE_QUEUE"
    SHUTDOWN = "SHUTDOWN"


class SessionIntent:
    """Persistent user intent for a torrent between application launches."""

    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    IDLE = "idle"

    VALID = {ACTIVE, PAUSED, STOPPED, IDLE}


class TorrentManager:
    _instance: Optional["TorrentManager"] = None
    SESSION_STATE_VERSION = 4
    DEFAULT_MAX_ACTIVE_DOWNLOADS = 2
    PRIORITY_RANK = {
        TORRENT_PRIORITY_HIGH: 0,
        TORRENT_PRIORITY_NORMAL: 1,
        TORRENT_PRIORITY_LOW: 2,
    }

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
            cls._instance._state_file_lock = threading.Lock()

            # Persistent session metadata.  This is deliberately separate from
            # TorrentSession.state because application shutdown must stop network
            # tasks without turning an "active" torrent into a persistently
            # "stopped" torrent for the next launch.
            cls._instance._desired_states: Dict[str, str] = {}
            cls._instance._queue_order: List[str] = []
            cls._instance._selected_info_hash: str = ""
            cls._instance._source_paths: Dict[str, str] = {}
            cls._instance._restoring_state = False

            # Queue scheduler. 0 means unlimited active downloads. Completed
            # torrents that are seeding do not consume download slots.
            cls._instance._max_active_downloads: int = cls.DEFAULT_MAX_ACTIVE_DOWNLOADS
            cls._instance._explicit_start_requests = set()

            cls._instance._state_dir = cls._instance._get_state_directory()
            cls._instance._state_file = cls._instance._state_dir / "session.json"
            cls._instance._torrent_cache_dir = cls._instance._state_dir / "torrents"
        elif ui_queue is not None:
            # Keep the singleton attached to the application's real UI queue.
            cls._instance.ui_queue = ui_queue

        return cls._instance

    @classmethod
    def get_instance(cls) -> "TorrentManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Persistent session storage
    # ------------------------------------------------------------------

    @staticmethod
    def _get_state_directory() -> Path:
        """Return a native per-user state directory without extra dependencies.

        SALIX_T_STATE_DIR is intentionally supported for development/testing.
        """
        override = os.environ.get("SALIX_T_STATE_DIR")
        if override:
            return Path(override).expanduser().resolve()

        if os.name == "nt":
            base = os.environ.get("LOCALAPPDATA")
            if base:
                return Path(base) / "SalixTorrent"
            return Path.home() / "AppData" / "Local" / "SalixTorrent"

        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "SalixTorrent"

        xdg_state_home = os.environ.get("XDG_STATE_HOME")
        if xdg_state_home:
            return Path(xdg_state_home) / "SalixTorrent"
        return Path.home() / ".local" / "state" / "SalixTorrent"

    @property
    def session_state_path(self) -> str:
        return str(self._state_file)

    def _ensure_state_directories(self):
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._torrent_cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_torrent_file(self, info_hash: str, torrent_path: str) -> str:
        """Keep a private metainfo copy so restore survives a moved .torrent."""
        try:
            self._ensure_state_directories()
            source = Path(torrent_path).expanduser().resolve()
            destination = self._torrent_cache_dir / f"{info_hash}.torrent"

            if source != destination:
                shutil.copy2(source, destination)

            return str(destination)
        except OSError as exc:
            print(f"[Salix_T Notice] Could not cache torrent metadata: {exc}")
            return ""

    @staticmethod
    def _normalise_intent(value: object) -> str:
        value = str(value or "").lower()
        if value in SessionIntent.VALID:
            return value
        return SessionIntent.IDLE

    @staticmethod
    def _infer_intent(session: TorrentSession) -> str:
        if session.state in (
            SessionState.CHECKING,
            SessionState.FAST_RESUME,
            SessionState.DOWNLOADING,
            SessionState.SEEDING,
            SessionState.QUEUED,
        ):
            return SessionIntent.ACTIVE
        if session.state == SessionState.PAUSED:
            return SessionIntent.PAUSED
        if session.state in (SessionState.STOPPED, SessionState.COMPLETED):
            return SessionIntent.STOPPED
        return SessionIntent.IDLE

    def _build_persistent_state(self) -> dict:
        with self._sessions_lock:
            sessions = dict(self.sessions)
            desired_states = dict(self._desired_states)
            source_paths = dict(self._source_paths)
            selected_info_hash = self._selected_info_hash

            order = [h for h in self._queue_order if h in sessions]
            order.extend(h for h in sessions if h not in order)

        entries = []
        for info_hash in order:
            session = sessions[info_hash]
            source_path = source_paths.get(info_hash, session.torrent_path)
            cache_path = str(self._torrent_cache_dir / f"{info_hash}.torrent")
            intent = desired_states.get(info_hash, self._infer_intent(session))

            paused_from_state = getattr(session, "_paused_from_state", None)
            if paused_from_state not in (
                SessionState.CHECKING,
                SessionState.DOWNLOADING,
                SessionState.SEEDING,
            ):
                paused_from_state = None

            entries.append(
                {
                    "info_hash": info_hash,
                    "torrent_path": source_path,
                    "cached_torrent_path": cache_path,
                    "max_peers": int(session.max_peers),
                    "intent": intent,
                    "paused_from_state": paused_from_state,
                    "download_limit_value": float(session.download_limit_value),
                    "download_limit_unit": session.download_limit_unit,
                    "upload_limit_value": float(session.upload_limit_value),
                    "upload_limit_unit": session.upload_limit_unit,
                    "uploaded_bytes": int(session.uploaded_bytes),
                    "seed_source_path": session.seed_source_path,
                    "file_priorities": session.piece_mgr.get_file_priorities(),
                    "queue_priority": session.queue_priority,
                }
            )

        if selected_info_hash not in sessions:
            selected_info_hash = order[0] if order else ""

        return {
            "version": self.SESSION_STATE_VERSION,
            "selected_info_hash": selected_info_hash,
            "max_active_downloads": int(self._max_active_downloads),
            "torrents": entries,
        }

    def save_session_state(self, force: bool = False):
        """Atomically persist the current queue and the user's lifecycle intent."""
        if self._restoring_state and not force:
            return

        try:
            data = self._build_persistent_state()
            self._ensure_state_directories()

            with self._state_file_lock:
                temp_path = self._state_file.with_suffix(".json.tmp")
                temp_path.write_text(
                    json.dumps(data, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                os.replace(temp_path, self._state_file)
        except OSError as exc:
            print(f"[Salix_T Notice] Could not save previous session: {exc}")

    def _load_session_state(self) -> Optional[dict]:
        if not self._state_file.exists():
            return None

        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[Salix_T Notice] Could not read previous session: {exc}")
            return None

        if not isinstance(data, dict):
            return None
        if data.get("version") not in (1, 2, 3, self.SESSION_STATE_VERSION):
            print("[Salix_T Notice] Previous session uses an unsupported format.")
            return None
        if not isinstance(data.get("torrents", []), list):
            return None
        return data

    def _resolve_restore_path(self, entry: dict) -> Optional[str]:
        source_path = str(entry.get("torrent_path") or "")
        cached_path = str(entry.get("cached_torrent_path") or "")

        if source_path and os.path.isfile(source_path):
            return os.path.abspath(source_path)
        if cached_path and os.path.isfile(cached_path):
            return os.path.abspath(cached_path)

        # Older state files or manually moved state directories can still use
        # the deterministic cache path derived from the info hash.
        info_hash = str(entry.get("info_hash") or "")
        if info_hash:
            fallback = self._torrent_cache_dir / f"{info_hash}.torrent"
            if fallback.is_file():
                return str(fallback)

        return None

    def restore_previous_session(self) -> int:
        """Restore queue contents and restart torrents that were active on exit.

        Paused torrents stay paused.  Stopped/idle torrents stay inactive.
        Active torrents are started only after every row has emitted its initial
        snapshot, preserving the saved queue order in the UI.
        """
        data = self._load_session_state()
        if not data:
            return 0

        entries = data.get("torrents", [])
        if not entries:
            return 0

        try:
            self._max_active_downloads = max(
                0,
                int(data.get("max_active_downloads", self.DEFAULT_MAX_ACTIVE_DOWNLOADS)),
            )
        except (TypeError, ValueError):
            self._max_active_downloads = self.DEFAULT_MAX_ACTIVE_DOWNLOADS

        restored_order: List[str] = []
        active_hashes: List[str] = []

        self._restoring_state = True
        try:
            for entry in entries:
                if not isinstance(entry, dict):
                    continue

                restore_path = self._resolve_restore_path(entry)
                if not restore_path:
                    name = entry.get("torrent_path") or entry.get("info_hash") or "unknown torrent"
                    print(f"[Salix_T Notice] Previous torrent is unavailable and was skipped: {name}")
                    continue

                try:
                    max_peers = max(1, int(entry.get("max_peers", 25)))
                except (TypeError, ValueError):
                    max_peers = 25

                try:
                    seed_source_path = str(entry.get("seed_source_path") or "")
                    session = TorrentSession(
                        restore_path,
                        ui_queue=self.ui_queue,
                        max_peers=max_peers,
                        seed_source_path=seed_source_path or None,
                    )
                except Exception as exc:
                    print(f"[Salix_T Notice] Could not restore '{restore_path}': {exc}")
                    continue

                info_hash = session.torrent.hex_info_hash
                expected_hash = str(entry.get("info_hash") or "")
                if expected_hash and expected_hash != info_hash:
                    print(
                        "[Salix_T Notice] Cached torrent metadata no longer matches "
                        f"the saved info hash and was skipped: {restore_path}"
                    )
                    continue

                intent = self._normalise_intent(entry.get("intent"))
                source_path = str(entry.get("torrent_path") or restore_path)

                with self._sessions_lock:
                    if info_hash in self.sessions:
                        continue
                    self.sessions[info_hash] = session
                    self._desired_states[info_hash] = intent
                    self._source_paths[info_hash] = source_path
                    restored_order.append(info_hash)

                # Recreate the visual lifecycle state before the first snapshot.
                if intent == SessionIntent.PAUSED:
                    session.state = SessionState.PAUSED
                    paused_from = entry.get("paused_from_state")
                    if paused_from in (
                        SessionState.CHECKING,
                        SessionState.DOWNLOADING,
                        SessionState.SEEDING,
                    ):
                        session._paused_from_state = paused_from
                elif intent == SessionIntent.STOPPED:
                    session.state = SessionState.STOPPED
                elif intent == SessionIntent.ACTIVE:
                    session.state = SessionState.QUEUED
                else:
                    session.state = SessionState.IDLE

                try:
                    uploaded_bytes = max(0, int(entry.get("uploaded_bytes", 0)))
                except (TypeError, ValueError):
                    uploaded_bytes = 0
                session.uploaded_bytes = uploaded_bytes

                session.set_file_priorities(
                    entry.get("file_priorities", []),
                    emit=False,
                )
                session.set_queue_priority(
                    entry.get("queue_priority", TORRENT_PRIORITY_NORMAL),
                    emit=False,
                )

                session.set_transfer_limits(
                    entry.get("download_limit_value", 0.0),
                    entry.get("download_limit_unit", "KB/s"),
                    entry.get("upload_limit_value", 0.0),
                    entry.get("upload_limit_unit", "KB/s"),
                )

                # Refresh/repair the cache while the original metainfo file is
                # still available.  Failure is non-fatal.
                self._cache_torrent_file(info_hash, restore_path)

                if intent == SessionIntent.ACTIVE:
                    active_hashes.append(info_hash)

            with self._sessions_lock:
                self._queue_order = restored_order[:]
                selected = str(data.get("selected_info_hash") or "")
                self._selected_info_hash = (
                    selected if selected in self.sessions else (restored_order[0] if restored_order else "")
                )

        finally:
            self._restoring_state = False

        # Rewrite the state once to drop entries whose .torrent metadata can no
        # longer be found, then resume everything that was active at shutdown.
        self.save_session_state()

        for info_hash in active_hashes:
            self.start_torrent(info_hash)

        if restored_order:
            print(
                f"[Salix_T] Restored {len(restored_order)} torrent(s) from the previous session "
                f"({len(active_hashes)} active)."
            )

        return len(restored_order)

    def set_queue_order(self, info_hashes: List[str]):
        with self._sessions_lock:
            valid = [h for h in info_hashes if h in self.sessions]
            valid.extend(h for h in self.sessions if h not in valid)
            self._queue_order = valid
        self.save_session_state()
        if self._running:
            self._send_cmd(TorrentCommand.REBALANCE_QUEUE, "")

    def get_max_active_downloads(self) -> int:
        return int(self._max_active_downloads)

    def set_max_active_downloads(self, value: int):
        try:
            value = max(0, int(value))
        except (TypeError, ValueError):
            value = self.DEFAULT_MAX_ACTIVE_DOWNLOADS

        self._max_active_downloads = value
        self.save_session_state()
        self._send_cmd(
            TorrentCommand.SET_QUEUE_LIMIT,
            "",
            {"max_active_downloads": value},
        )

    def set_selected_torrent(self, info_hash: str):
        with self._sessions_lock:
            if info_hash and info_hash in self.sessions:
                self._selected_info_hash = info_hash
            elif not info_hash:
                self._selected_info_hash = ""
            else:
                return
        self.save_session_state()

    def get_selected_torrent(self) -> str:
        with self._sessions_lock:
            return self._selected_info_hash

    def _set_intent(self, info_hash: str, intent: str):
        with self._sessions_lock:
            if info_hash not in self.sessions:
                return False
            self._desired_states[info_hash] = self._normalise_intent(intent)
        self.save_session_state()
        return True

    # ------------------------------------------------------------------
    # Torrent removal / downloaded-data cleanup
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_payload_path(session: TorrentSession) -> Path:
        """Return the payload path only when it is safely inside downloads/.

        Torrent names come from untrusted metainfo, so deletion must never be
        allowed to escape the configured download directory.
        """
        download_root = Path(session.piece_mgr.download_dir).expanduser().resolve()
        payload_path = Path(session.piece_mgr.output_path).expanduser().resolve()

        try:
            payload_path.relative_to(download_root)
        except ValueError as exc:
            raise RuntimeError(
                "Refusing to delete payload outside the SalixTorrent download directory."
            ) from exc

        if payload_path == download_root:
            raise RuntimeError("Refusing to delete the download directory itself.")
        if payload_path.name == ".salix_resume":
            raise RuntimeError("Refusing to delete SalixTorrent's resume-state directory.")

        return payload_path

    @staticmethod
    def _remove_path_with_retries(path: Path, timeout: float = 4.0):
        """Delete a file/directory, briefly retrying Windows sharing violations."""
        import time

        deadline = time.monotonic() + max(0.0, timeout)
        last_error: Optional[OSError] = None

        while True:
            try:
                if not path.exists() and not path.is_symlink():
                    return

                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                return

            except OSError as exc:
                last_error = exc
                if time.monotonic() >= deadline:
                    raise last_error
                time.sleep(0.1)

    def _delete_downloaded_data(self, session: TorrentSession) -> str:
        """Delete this torrent's payload and resume sidecar.

        Returns an empty string on success, otherwise a human-readable error.
        The user's original .torrent file is never deleted here.
        """
        try:
            payload_path = self._safe_payload_path(session)
            self._remove_path_with_retries(payload_path)

            resume_path = Path(session.piece_mgr.resume_path).expanduser()
            try:
                if resume_path.exists() or resume_path.is_symlink():
                    resume_path.unlink()
            except OSError as exc:
                # Payload deletion succeeded.  A stale resume sidecar is small,
                # but report it so the user knows cleanup was not perfect.
                return f"Downloaded data was deleted, but resume metadata could not be removed: {exc}"

            return ""

        except (OSError, RuntimeError) as exc:
            return str(exc)

    def _delete_cached_torrent(self, info_hash: str):
        """Remove SalixTorrent's private cached metainfo copy only."""
        cache_path = self._torrent_cache_dir / f"{info_hash}.torrent"
        try:
            if cache_path.exists() or cache_path.is_symlink():
                cache_path.unlink()
        except OSError as exc:
            print(f"[Salix_T Notice] Could not remove cached torrent metadata: {exc}")

    def _finalize_torrent_removal(self, info_hash: str) -> str:
        """Remove manager/session persistence records and choose a new selection."""
        with self._sessions_lock:
            try:
                old_index = self._queue_order.index(info_hash)
            except ValueError:
                old_index = 0

            self.sessions.pop(info_hash, None)
            self._desired_states.pop(info_hash, None)
            self._source_paths.pop(info_hash, None)
            self._explicit_start_requests.discard(info_hash)
            self._queue_order = [h for h in self._queue_order if h != info_hash]

            if self._selected_info_hash == info_hash:
                if self._queue_order:
                    new_index = min(old_index, len(self._queue_order) - 1)
                    self._selected_info_hash = self._queue_order[new_index]
                else:
                    self._selected_info_hash = ""

            selected = self._selected_info_hash

        self._delete_cached_torrent(info_hash)
        self.save_session_state()
        return selected

    # ------------------------------------------------------------------
    # Background asyncio engine
    # ------------------------------------------------------------------

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
            self._running = False
            self._engine_ready.clear()
            self._cmd_queue = None
            self._loop = None

    def _queue_sort_key(self, info_hash: str, order_index: Dict[str, int]):
        session = self.sessions.get(info_hash)
        priority = (
            session.queue_priority
            if session is not None
            else TORRENT_PRIORITY_NORMAL
        )
        return (
            self.PRIORITY_RANK.get(priority, self.PRIORITY_RANK[TORRENT_PRIORITY_NORMAL]),
            order_index.get(info_hash, 10**9),
        )

    def _rebalance_queue(self):
        """Start waiting torrents when download slots become available.

        Running downloads are intentionally not pre-empted when the user
        changes order or priority. Queue position decides who starts *next*.
        Completed torrents that are seeding do not consume download slots.
        """
        with self._sessions_lock:
            sessions = dict(self.sessions)
            desired = dict(self._desired_states)
            order = [h for h in self._queue_order if h in sessions]
            order.extend(h for h in sessions if h not in order)

        order_index = {info_hash: index for index, info_hash in enumerate(order)}
        active_downloads = 0
        candidates: List[str] = []

        for info_hash in order:
            if desired.get(info_hash) != SessionIntent.ACTIVE:
                continue

            session = sessions[info_hash]

            # A fully complete torrent is a seeding candidate and does not
            # consume one of the download slots. Start it whenever requested.
            if session.piece_mgr.is_finished:
                can_retry_error = info_hash in self._explicit_start_requests
                if (
                    not session.is_running
                    and (session.state != SessionState.ERROR or can_retry_error)
                ):
                    asyncio.create_task(session.start())
                    self._explicit_start_requests.discard(info_hash)
                continue

            # Selective-download completion has no remaining wanted work.
            if session.piece_mgr.wanted_is_finished and session.piece_mgr.storage_prepared:
                continue

            if session.is_running and session.state in (
                SessionState.CHECKING,
                SessionState.FAST_RESUME,
                SessionState.DOWNLOADING,
            ):
                active_downloads += 1
                continue

            # Errors are not automatically retried every scheduler tick. A
            # fresh explicit Start/Resume request grants one retry attempt.
            if (
                session.state == SessionState.ERROR
                and info_hash not in self._explicit_start_requests
            ):
                continue

            candidates.append(info_hash)

        candidates.sort(key=lambda h: self._queue_sort_key(h, order_index))

        if self._max_active_downloads <= 0:
            available_slots = len(candidates)
        else:
            available_slots = max(0, self._max_active_downloads - active_downloads)

        for info_hash in candidates:
            session = sessions[info_hash]

            if available_slots <= 0:
                # Fresh/stopped sessions become visibly queued. A paused live
                # coroutine can also remain suspended in Queued until promoted.
                session.mark_queued()
                continue

            promoted = False
            if session.is_running:
                if session.state == SessionState.QUEUED:
                    promoted = session.resume_from_queue()
                elif session.state == SessionState.PAUSED:
                    session.resume()
                    promoted = True
            else:
                asyncio.create_task(session.start())
                promoted = True

            if promoted:
                self._explicit_start_requests.discard(info_hash)
                available_slots -= 1

    async def _engine_main(self):
        self._cmd_queue = asyncio.Queue()
        self._engine_ready.set()

        while self._running:
            try:
                command = await asyncio.wait_for(
                    self._cmd_queue.get(),
                    timeout=0.5,
                )
            except asyncio.TimeoutError:
                # Completion/seeding transitions happen inside TorrentSession,
                # so a light periodic rebalance lets the next queued download
                # start without waiting for another UI command.
                self._rebalance_queue()
                continue

            if len(command) == 2:
                action, info_hash = command
                payload = None
            else:
                action, info_hash, payload = command

            try:
                if action == TorrentCommand.SHUTDOWN:
                    # save_session_state() is called before this command. Stop
                    # only tears down live work; it must not alter persisted
                    # ACTIVE/PAUSED/STOPPED intent.
                    with self._sessions_lock:
                        sessions = list(self.sessions.values())

                    for session in sessions:
                        try:
                            session.stop()
                        except Exception:
                            pass

                    self._running = False
                    await asyncio.sleep(0)
                    break

                if action == TorrentCommand.SET_QUEUE_LIMIT:
                    payload = payload or {}
                    try:
                        self._max_active_downloads = max(
                            0,
                            int(payload.get("max_active_downloads", self.DEFAULT_MAX_ACTIVE_DOWNLOADS)),
                        )
                    except (TypeError, ValueError):
                        self._max_active_downloads = self.DEFAULT_MAX_ACTIVE_DOWNLOADS
                    self.save_session_state()
                    self._rebalance_queue()
                    continue

                if action == TorrentCommand.REBALANCE_QUEUE:
                    self._rebalance_queue()
                    continue

                with self._sessions_lock:
                    session = self.sessions.get(info_hash)

                if not session:
                    continue

                if action == TorrentCommand.START:
                    self._explicit_start_requests.add(info_hash)
                    self._rebalance_queue()

                elif action == TorrentCommand.PAUSE:
                    session.pause()
                    self._rebalance_queue()

                elif action == TorrentCommand.RESUME:
                    self._explicit_start_requests.add(info_hash)
                    self._rebalance_queue()

                elif action == TorrentCommand.STOP:
                    self._explicit_start_requests.discard(info_hash)
                    session.stop()
                    self._rebalance_queue()

                elif action == TorrentCommand.REMOVE:
                    payload = payload or {}
                    delete_data = bool(payload.get("delete_data", False))

                    # Stop the live session first so sockets, peer tasks and
                    # disk-check cancellation are triggered before cleanup.
                    self._explicit_start_requests.discard(info_hash)
                    session.stop()
                    await asyncio.sleep(0)

                    # Give the cancelled session coroutine a chance to execute
                    # its finally block and close file/network resources.
                    main_task = getattr(session, "_main_task", None)
                    if main_task and main_task is not asyncio.current_task() and not main_task.done():
                        try:
                            await asyncio.wait_for(
                                asyncio.shield(main_task),
                                timeout=2.0,
                            )
                        except (asyncio.TimeoutError, asyncio.CancelledError):
                            pass

                    cleanup_error = ""
                    if delete_data:
                        cleanup_error = await asyncio.to_thread(
                            self._delete_downloaded_data,
                            session,
                        )

                    selected = self._finalize_torrent_removal(info_hash)
                    self.ui_queue.put(
                        {
                            "type": "TORRENT_REMOVED",
                            "info_hash": info_hash,
                            "delete_data": delete_data,
                            "cleanup_error": cleanup_error,
                            "selected_info_hash": selected,
                        }
                    )
                    self._rebalance_queue()

                elif action == TorrentCommand.SET_LIMITS:
                    payload = payload or {}
                    session.set_transfer_limits(
                        payload.get("download_value", 0.0),
                        payload.get("download_unit", "KB/s"),
                        payload.get("upload_value", 0.0),
                        payload.get("upload_unit", "KB/s"),
                    )
                    self.save_session_state()

                elif action == TorrentCommand.SET_FILE_PRIORITY:
                    payload = payload or {}
                    changed = session.set_file_priority(
                        payload.get("file_index", -1),
                        payload.get("priority", "Normal"),
                    )
                    if changed:
                        self.save_session_state()

                elif action == TorrentCommand.SET_TORRENT_PRIORITY:
                    payload = payload or {}
                    changed = session.set_queue_priority(
                        payload.get("priority", TORRENT_PRIORITY_NORMAL),
                    )
                    if changed:
                        self.save_session_state()
                    self._rebalance_queue()

            finally:
                self._cmd_queue.task_done()

    # ------------------------------------------------------------------
    # Torrent lifecycle API
    # ------------------------------------------------------------------

    def add_torrent(
        self,
        torrent_path: str,
        max_peers: int = 25,
        persist: bool = True,
        seed_source_path: Optional[str] = None,
    ) -> TorrentSession:
        torrent_path = os.path.abspath(os.path.expanduser(torrent_path))
        seed_source_path = (
            os.path.abspath(os.path.expanduser(seed_source_path))
            if seed_source_path
            else ""
        )

        # TorrentSession construction is lightweight: it parses .torrent
        # metadata and creates Piece descriptors, but does not hash the payload
        # file or allocate every block. External seed sources are read-only and
        # are verified only after Start is requested.
        new_session = TorrentSession(
            torrent_path,
            ui_queue=self.ui_queue,
            max_peers=max_peers,
            seed_source_path=seed_source_path or None,
        )
        info_hash = new_session.torrent.hex_info_hash

        if seed_source_path:
            if new_session.torrent.is_multi_file and not os.path.isdir(seed_source_path):
                raise ValueError("A multi-file torrent must be seeded from its source folder.")
            if not new_session.torrent.is_multi_file and not os.path.isfile(seed_source_path):
                raise ValueError("A single-file torrent must be seeded from its source file.")

        replacement_limits = None
        replacement_uploaded = 0
        replacement_priorities = None
        replacement_queue_priority = TORRENT_PRIORITY_NORMAL
        replaced_existing = False

        with self._sessions_lock:
            existing_session = self.sessions.get(info_hash)

            if existing_session and seed_source_path:
                same_source = (
                    existing_session.seed_source_path
                    and os.path.normcase(existing_session.seed_source_path)
                    == os.path.normcase(seed_source_path)
                )

                if same_source:
                    if persist:
                        self._source_paths[info_hash] = torrent_path
                    existing_session.emit_snapshot()
                    session = existing_session
                else:
                    if existing_session.is_running:
                        raise RuntimeError(
                            "This torrent is already active. Stop it before attaching "
                            "a different local seed source."
                        )

                    replacement_limits = (
                        existing_session.download_limit_value,
                        existing_session.download_limit_unit,
                        existing_session.upload_limit_value,
                        existing_session.upload_limit_unit,
                    )
                    replacement_uploaded = existing_session.uploaded_bytes
                    replacement_priorities = existing_session.piece_mgr.get_file_priorities()
                    replacement_queue_priority = existing_session.queue_priority
                    self.sessions[info_hash] = new_session
                    self._desired_states[info_hash] = SessionIntent.IDLE
                    self._source_paths[info_hash] = torrent_path
                    if info_hash not in self._queue_order:
                        self._queue_order.append(info_hash)
                    session = new_session
                    replaced_existing = True

            elif existing_session:
                if persist:
                    self._source_paths[info_hash] = torrent_path
                existing_session.emit_snapshot()
                session = existing_session

            else:
                self.sessions[info_hash] = new_session
                self._desired_states[info_hash] = SessionIntent.IDLE
                self._source_paths[info_hash] = torrent_path
                if info_hash not in self._queue_order:
                    self._queue_order.append(info_hash)
                session = new_session

        if existing_session and not replaced_existing:
            if persist:
                self._cache_torrent_file(info_hash, torrent_path)
                self.save_session_state()
            return session

        if replacement_limits:
            new_session.uploaded_bytes = replacement_uploaded
            new_session.set_transfer_limits(*replacement_limits)
        if replacement_priorities:
            new_session.set_file_priorities(replacement_priorities, emit=False)
        new_session.set_queue_priority(replacement_queue_priority, emit=False)

        self._cache_torrent_file(info_hash, torrent_path)

        # Put an Idle row into the UI immediately. The background engine will
        # later change it to Checking/Downloading/Seeding as appropriate.
        new_session.emit_snapshot()

        if persist:
            self.save_session_state()
        return new_session

    def add_seed_torrent(
        self,
        torrent_path: str,
        seed_source_path: str,
        max_peers: int = 25,
    ) -> TorrentSession:
        """Attach a locally-created torrent to its original payload read-only."""
        return self.add_torrent(
            torrent_path,
            max_peers=max_peers,
            persist=True,
            seed_source_path=seed_source_path,
        )

    def _send_cmd(self, action: str, info_hash: str, payload=None):
        if not self._running:
            self.start_engine()

        if not self._engine_ready.wait(timeout=5.0):
            return

        if self._loop and self._cmd_queue and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(
                self._cmd_queue.put_nowait,
                (action, info_hash, payload),
            )

    def start_torrent(self, info_hash: str):
        if self._set_intent(info_hash, SessionIntent.ACTIVE):
            self._send_cmd(TorrentCommand.START, info_hash)

    def pause_torrent(self, info_hash: str):
        with self._sessions_lock:
            session = self.sessions.get(info_hash)
            can_pause = bool(
                session
                and session.state in (
                    SessionState.CHECKING,
                    SessionState.DOWNLOADING,
                    SessionState.SEEDING,
                )
            )

        if can_pause:
            self._set_intent(info_hash, SessionIntent.PAUSED)
        self._send_cmd(TorrentCommand.PAUSE, info_hash)

    def resume_torrent(self, info_hash: str):
        if self._set_intent(info_hash, SessionIntent.ACTIVE):
            self._send_cmd(TorrentCommand.RESUME, info_hash)

    def stop_torrent(self, info_hash: str):
        if self._set_intent(info_hash, SessionIntent.STOPPED):
            self._send_cmd(TorrentCommand.STOP, info_hash)

    def remove_torrent(self, info_hash: str, delete_data: bool = False):
        """Remove a torrent from SalixTorrent, optionally deleting its payload.

        The original .torrent selected by the user is deliberately never
        deleted.  Only SalixTorrent's private cache/session metadata is cleaned.
        """
        with self._sessions_lock:
            if info_hash not in self.sessions:
                return False

        self._send_cmd(
            TorrentCommand.REMOVE,
            info_hash,
            {"delete_data": bool(delete_data)},
        )
        return True

    def set_transfer_limits(
        self,
        info_hash: str,
        download_value: float,
        download_unit: str,
        upload_value: float,
        upload_unit: str,
    ):
        self._send_cmd(
            TorrentCommand.SET_LIMITS,
            info_hash,
            {
                "download_value": download_value,
                "download_unit": download_unit,
                "upload_value": upload_value,
                "upload_unit": upload_unit,
            },
        )

    def set_file_priority(
        self,
        info_hash: str,
        file_index: int,
        priority: str,
    ):
        """Set one payload file's scheduler priority for a torrent."""
        self._send_cmd(
            TorrentCommand.SET_FILE_PRIORITY,
            info_hash,
            {
                "file_index": int(file_index),
                "priority": str(priority),
            },
        )

    def set_torrent_priority(self, info_hash: str, priority: str):
        """Set High / Normal / Low queue priority for one torrent."""
        value = str(priority or TORRENT_PRIORITY_NORMAL).strip().title()
        if value not in TORRENT_PRIORITIES:
            value = TORRENT_PRIORITY_NORMAL
        self._send_cmd(
            TorrentCommand.SET_TORRENT_PRIORITY,
            info_hash,
            {"priority": value},
        )

    def shutdown(self, timeout: float = 5.0):
        """Persist intent, then cleanly stop the async engine before process exit."""
        # This snapshot is the important one: it captures ACTIVE before the
        # shutdown command invokes session.stop() for network cleanup.
        self.save_session_state(force=True)

        if not self._running:
            return

        if self._engine_ready.wait(timeout=2.0):
            loop = self._loop
            cmd_queue = self._cmd_queue
            if loop and cmd_queue and not loop.is_closed():
                loop.call_soon_threadsafe(
                    cmd_queue.put_nowait,
                    (TorrentCommand.SHUTDOWN, "", None),
                )

        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)

        if thread and thread.is_alive():
            print("[Salix_T Notice] Async engine did not finish shutdown before timeout.")
