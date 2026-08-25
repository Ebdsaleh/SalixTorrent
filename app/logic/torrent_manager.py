# app/logic/torrent_manager.py

import asyncio
import json
import os
import queue
import secrets
import shutil
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional

from app.logic.connectivity import ConnectivityManager
from app.logic.magnet import (
    MagnetCancelled,
    MagnetError,
    MagnetLink,
    MagnetMetadataFetcher,
    build_torrent_bytes,
)
from app.logic.session import (
    TorrentSession,
    SessionState,
    TORRENT_PRIORITY_HIGH,
    TORRENT_PRIORITY_NORMAL,
    TORRENT_PRIORITY_LOW,
    TORRENT_PRIORITIES,
    AsyncBandwidthLimiter,
    RATE_UNIT_MULTIPLIERS,
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
    FORCE_RECHECK = "FORCE_RECHECK"
    ANNOUNCE = "ANNOUNCE"
    ADD_MAGNET = "ADD_MAGNET"
    CANCEL_MAGNET = "CANCEL_MAGNET"
    APPLY_APP_SETTINGS = "APPLY_APP_SETTINGS"
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
    SESSION_STATE_VERSION = 5
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
            cls._instance._maintenance_tasks: Dict[str, asyncio.Task] = {}
            cls._instance._magnet_tasks: Dict[str, asyncio.Task] = {}
            cls._instance._magnet_fetchers: Dict[str, MagnetMetadataFetcher] = {}

            # Application-wide bandwidth limiters are shared by every torrent
            # session, unlike the existing per-torrent limiters.
            cls._instance._global_download_limiter = AsyncBandwidthLimiter()
            cls._instance._global_upload_limiter = AsyncBandwidthLimiter()
            cls._instance._connectivity = ConnectivityManager()

            cls._instance._state_dir = cls._instance._get_state_directory()
            cls._instance._state_file = cls._instance._state_dir / "session.json"
            cls._instance._torrent_cache_dir = cls._instance._state_dir / "torrents"
            cls._instance._settings_file = cls._instance._state_dir / "settings.json"
            cls._instance._settings = cls._instance._load_app_settings()
            cls._instance._max_active_downloads = int(
                cls._instance._settings.get(
                    "max_active_downloads", cls.DEFAULT_MAX_ACTIVE_DOWNLOADS
                )
            )
            cls._instance._apply_global_bandwidth_settings()
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

    @classmethod
    def _default_app_settings(cls) -> dict:
        return {
            "download_dir": os.path.abspath("downloads"),
            "default_max_peers": 25,
            "max_active_downloads": cls.DEFAULT_MAX_ACTIVE_DOWNLOADS,
            "auto_resume_active": True,
            "completion_notifications": True,
            "native_notifications": True,
            "system_tray_enabled": True,
            "minimize_to_tray": True,
            "listen_port": 6881,
            "enable_dht": True,
            "enable_pex": True,
            "enable_lan_discovery": True,
            "enable_upnp": True,
            "enable_natpmp": True,
            "global_download_limit_value": 0.0,
            "global_download_limit_unit": "KB/s",
            "global_upload_limit_value": 0.0,
            "global_upload_limit_unit": "KB/s",
            "default_download_limit_value": 0.0,
            "default_download_limit_unit": "KB/s",
            "default_upload_limit_value": 0.0,
            "default_upload_limit_unit": "KB/s",
            "default_queue_priority": TORRENT_PRIORITY_NORMAL,
        }

    @classmethod
    def _normalise_app_settings(cls, value: object) -> dict:
        defaults = cls._default_app_settings()
        data = dict(value) if isinstance(value, dict) else {}
        out = dict(defaults)

        raw_dir = str(data.get("download_dir") or defaults["download_dir"]).strip()
        out["download_dir"] = os.path.abspath(os.path.expanduser(raw_dir))

        try:
            out["default_max_peers"] = max(1, min(500, int(data.get("default_max_peers", 25))))
        except (TypeError, ValueError):
            out["default_max_peers"] = 25

        try:
            out["max_active_downloads"] = max(0, int(data.get("max_active_downloads", cls.DEFAULT_MAX_ACTIVE_DOWNLOADS)))
        except (TypeError, ValueError):
            out["max_active_downloads"] = cls.DEFAULT_MAX_ACTIVE_DOWNLOADS

        out["auto_resume_active"] = bool(data.get("auto_resume_active", True))
        out["completion_notifications"] = bool(data.get("completion_notifications", True))
        out["native_notifications"] = bool(data.get("native_notifications", True))
        out["system_tray_enabled"] = bool(data.get("system_tray_enabled", True))
        out["minimize_to_tray"] = bool(data.get("minimize_to_tray", True))
        out["enable_dht"] = bool(data.get("enable_dht", True))
        out["enable_pex"] = bool(data.get("enable_pex", True))
        out["enable_lan_discovery"] = bool(data.get("enable_lan_discovery", True))
        out["enable_upnp"] = bool(data.get("enable_upnp", True))
        out["enable_natpmp"] = bool(data.get("enable_natpmp", True))

        try:
            listen_port = int(data.get("listen_port", 6881))
        except (TypeError, ValueError):
            listen_port = 6881
        out["listen_port"] = max(1, min(65535, listen_port))

        for key in (
            "global_download_limit_value",
            "global_upload_limit_value",
            "default_download_limit_value",
            "default_upload_limit_value",
        ):
            try:
                out[key] = max(0.0, float(data.get(key, 0.0)))
            except (TypeError, ValueError):
                out[key] = 0.0

        valid_units = {"KB/s", "MB/s", "kbps", "Mbps"}
        for key in (
            "global_download_limit_unit",
            "global_upload_limit_unit",
            "default_download_limit_unit",
            "default_upload_limit_unit",
        ):
            unit = str(data.get(key) or "KB/s")
            out[key] = unit if unit in valid_units else "KB/s"

        priority = str(data.get("default_queue_priority") or TORRENT_PRIORITY_NORMAL).strip().title()
        out["default_queue_priority"] = (
            priority if priority in TORRENT_PRIORITIES else TORRENT_PRIORITY_NORMAL
        )
        return out

    def _load_app_settings(self) -> dict:
        defaults = self._default_app_settings()
        try:
            if not self._settings_file.exists():
                return defaults
            raw = json.loads(self._settings_file.read_text(encoding="utf-8"))
            return self._normalise_app_settings(raw)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return defaults

    def save_app_settings(self):
        try:
            self._ensure_state_directories()
            temp_path = self._settings_file.with_suffix(".json.tmp")
            temp_path.write_text(
                json.dumps(self._settings, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temp_path, self._settings_file)
        except OSError as exc:
            print(f"[Salix_T Notice] Could not save settings: {exc}")

    def get_app_settings(self) -> dict:
        return dict(self._settings)

    @staticmethod
    def _rate_to_bps(value: object, unit: object) -> int:
        try:
            numeric = max(0.0, float(value or 0.0))
        except (TypeError, ValueError):
            numeric = 0.0
        multiplier = RATE_UNIT_MULTIPLIERS.get(str(unit or "KB/s"), 1024.0)
        return int(numeric * multiplier)

    def _apply_global_bandwidth_settings(self):
        self._global_download_limiter.set_rate(
            self._rate_to_bps(
                self._settings.get("global_download_limit_value", 0.0),
                self._settings.get("global_download_limit_unit", "KB/s"),
            )
        )
        self._global_upload_limiter.set_rate(
            self._rate_to_bps(
                self._settings.get("global_upload_limit_value", 0.0),
                self._settings.get("global_upload_limit_unit", "KB/s"),
            )
        )

    def get_connectivity_snapshot(self) -> dict:
        return self._connectivity.snapshot()

    def refresh_connectivity(self):
        self._connectivity.request_refresh(self._settings)

    def _on_session_listen_port(self, port: int):
        # A real bound port is better than the configured preference. Re-map
        # the router if the session had to fall back because the preferred port
        # was occupied.
        if port:
            self._connectivity.request_refresh(self._settings, actual_port=int(port))

    def _on_incoming_peer(self, port: int, remote_ip: str):
        self._connectivity.mark_incoming(port, remote_ip)

    def update_app_settings(self, values: dict) -> dict:
        merged = dict(self._settings)
        if isinstance(values, dict):
            merged.update(values)
        self._settings = self._normalise_app_settings(merged)
        self.save_app_settings()
        self._apply_global_bandwidth_settings()

        queue_limit = int(self._settings.get("max_active_downloads", self.DEFAULT_MAX_ACTIVE_DOWNLOADS))
        if queue_limit != self._max_active_downloads:
            self.set_max_active_downloads(queue_limit)

        self._connectivity.request_refresh(self._settings)
        if self._running:
            self._send_cmd(TorrentCommand.APPLY_APP_SETTINGS, "", dict(self._settings))
        return self.get_app_settings()

    def reset_app_settings(self) -> dict:
        self._settings = self._default_app_settings()
        self.save_app_settings()
        self._apply_global_bandwidth_settings()
        self.set_max_active_downloads(self._settings["max_active_downloads"])
        self._connectivity.request_refresh(self._settings)
        if self._running:
            self._send_cmd(TorrentCommand.APPLY_APP_SETTINGS, "", dict(self._settings))
        return self.get_app_settings()

    def completion_notifications_enabled(self) -> bool:
        return bool(self._settings.get("completion_notifications", True))

    @property
    def session_state_path(self) -> str:
        return str(self._state_file)

    @property
    def settings_path(self) -> str:
        return str(self._settings_file)

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
                    "download_dir": os.path.abspath(session.piece_mgr.download_dir),
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
        if data.get("version") not in (1, 2, 3, 4, self.SESSION_STATE_VERSION):
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
        self._settings["max_active_downloads"] = int(self._max_active_downloads)
        self.save_app_settings()

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
                    max_peers = max(1, int(entry.get("max_peers", self._settings.get("default_max_peers", 25))))
                except (TypeError, ValueError):
                    max_peers = int(self._settings.get("default_max_peers", 25))

                try:
                    seed_source_path = str(entry.get("seed_source_path") or "")
                    download_dir = str(
                        entry.get("download_dir")
                        or self._settings.get("download_dir")
                        or os.path.abspath("downloads")
                    )
                    session = TorrentSession(
                        restore_path,
                        ui_queue=self.ui_queue,
                        max_peers=max_peers,
                        download_dir=download_dir,
                        seed_source_path=seed_source_path or None,
                        listen_port=self._settings.get("listen_port", 6881),
                        enable_dht=self._settings.get("enable_dht", True),
                        enable_pex=self._settings.get("enable_pex", True),
                        enable_lan_discovery=self._settings.get("enable_lan_discovery", True),
                        global_download_limiter=self._global_download_limiter,
                        global_upload_limiter=self._global_upload_limiter,
                        listen_port_callback=self._on_session_listen_port,
                        incoming_peer_callback=self._on_incoming_peer,
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
                if intent == SessionIntent.ACTIVE and not self._settings.get("auto_resume_active", True):
                    intent = SessionIntent.STOPPED
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
        self._settings["max_active_downloads"] = value
        self.save_app_settings()
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

        # Selection is a hot UI path (left/right click in the transfer table).
        # Do not synchronously rewrite session.json on every selection change.
        # The selected torrent is persisted by the next normal state save and
        # always by shutdown(force=True), which preserves the same UX without
        # injecting filesystem latency into Dear PyGui callbacks.

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
        self._connectivity.request_refresh(self._settings)

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

    async def _run_force_recheck(
        self,
        info_hash: str,
        session: TorrentSession,
    ):
        """Run a potentially long disk recheck without blocking engine commands."""
        try:
            if session.is_running:
                session.stop()
                await asyncio.sleep(0)
                main_task = getattr(session, "_main_task", None)
                if (
                    main_task
                    and main_task is not asyncio.current_task()
                    and not main_task.done()
                ):
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(main_task),
                            timeout=2.0,
                        )
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        pass

            await asyncio.to_thread(session.piece_mgr.invalidate_verification)
            success = await session.force_recheck()
            if not success:
                return

            with self._sessions_lock:
                current_intent = self._desired_states.get(
                    info_hash, SessionIntent.STOPPED
                )

            if current_intent == SessionIntent.ACTIVE:
                self._explicit_start_requests.add(info_hash)
                self._rebalance_queue()
            elif current_intent == SessionIntent.PAUSED:
                session.state = SessionState.PAUSED
                session._paused_from_state = SessionState.DOWNLOADING
                session.emit_snapshot()
            elif current_intent == SessionIntent.IDLE:
                session.state = SessionState.IDLE
                session.emit_snapshot()
            else:
                session.state = SessionState.STOPPED
                session.emit_snapshot()

            self.save_session_state()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            try:
                session.error_message = f"Force recheck failed: {exc}"
                session.state = SessionState.ERROR
                session.emit_snapshot()
            except Exception:
                pass
        finally:
            self._maintenance_tasks.pop(info_hash, None)

    def _emit_magnet_event(
        self,
        event_type: str,
        magnet: MagnetLink,
        *,
        stage: str = "",
        progress: float = 0.0,
        message: str = "",
        duplicate: bool = False,
    ):
        self.ui_queue.put(
            {
                "type": event_type,
                "info_hash": magnet.hex_info_hash,
                "magnet_uri": magnet.uri,
                "display_name": magnet.display_name or magnet.hex_info_hash,
                "stage": str(stage or ""),
                "progress": max(0.0, min(1.0, float(progress))),
                "message": str(message or ""),
                "duplicate": bool(duplicate),
            }
        )

    async def _resolve_magnet(self, magnet_uri: str, start_requested: bool):
        magnet = MagnetLink.parse(magnet_uri)
        info_hash = magnet.hex_info_hash
        fetcher = None

        try:
            with self._sessions_lock:
                existing = self.sessions.get(info_hash)
            if existing is not None:
                if start_requested:
                    self._set_intent(info_hash, SessionIntent.ACTIVE)
                    self._explicit_start_requests.add(info_hash)
                    self._rebalance_queue()
                self._emit_magnet_event(
                    "MAGNET_READY",
                    magnet,
                    stage="Already Added",
                    progress=1.0,
                    message="This magnet is already present in the transfer queue.",
                    duplicate=True,
                )
                return

            peer_id = b"-ST0001-" + secrets.token_hex(6).encode("ascii")

            def on_progress(stage: str, progress: float, message: str):
                self._emit_magnet_event(
                    "MAGNET_PROGRESS",
                    magnet,
                    stage=stage,
                    progress=progress,
                    message=message,
                )

            fetcher = MagnetMetadataFetcher(
                magnet,
                peer_id,
                max_peers=int(self._settings.get("default_max_peers", 25)),
                progress_callback=on_progress,
            )
            self._magnet_fetchers[info_hash] = fetcher
            self._emit_magnet_event(
                "MAGNET_PROGRESS",
                magnet,
                stage="Starting",
                progress=0.01,
                message="Starting magnet metadata discovery...",
            )

            raw_info = await fetcher.resolve()
            torrent_bytes = build_torrent_bytes(magnet, raw_info)

            self._ensure_state_directories()
            destination = self._torrent_cache_dir / f"{info_hash}.torrent"
            temp_path = destination.with_suffix(".torrent.tmp")
            await asyncio.to_thread(temp_path.write_bytes, torrent_bytes)
            os.replace(temp_path, destination)

            # Parse through the ordinary TorrentSession/TorrentFile path. This
            # verifies the exact raw info hash again and means resolved magnets
            # use the same storage, checking, queueing and persistence code as
            # normal .torrent files.
            session = self.add_torrent(str(destination), persist=True)
            if session.torrent.hex_info_hash != info_hash:
                raise MagnetError("Resolved metadata did not reproduce the magnet info hash.")

            with self._sessions_lock:
                self._selected_info_hash = info_hash

            if start_requested:
                self._set_intent(info_hash, SessionIntent.ACTIVE)
                self._explicit_start_requests.add(info_hash)
                self._rebalance_queue()
            self.save_session_state()

            self._emit_magnet_event(
                "MAGNET_READY",
                magnet,
                stage="Ready",
                progress=1.0,
                message=f"Metadata received: {session.torrent.name}",
            )

        except MagnetCancelled:
            self._emit_magnet_event(
                "MAGNET_CANCELLED",
                magnet,
                stage="Cancelled",
                progress=0.0,
                message="Magnet metadata retrieval was cancelled.",
            )
        except asyncio.CancelledError:
            if fetcher is not None:
                fetcher.cancel()
            self._emit_magnet_event(
                "MAGNET_CANCELLED",
                magnet,
                stage="Cancelled",
                progress=0.0,
                message="Magnet metadata retrieval was cancelled.",
            )
        except Exception as exc:
            self._emit_magnet_event(
                "MAGNET_ERROR",
                magnet,
                stage="Error",
                progress=0.0,
                message=str(exc) or exc.__class__.__name__,
            )
        finally:
            self._magnet_fetchers.pop(info_hash, None)
            self._magnet_tasks.pop(info_hash, None)

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
                    for fetcher in list(self._magnet_fetchers.values()):
                        try:
                            fetcher.cancel()
                        except Exception:
                            pass
                    magnet_tasks = [
                        task for task in self._magnet_tasks.values() if not task.done()
                    ]
                    for task in magnet_tasks:
                        task.cancel()
                    if magnet_tasks:
                        await asyncio.gather(*magnet_tasks, return_exceptions=True)
                    self._magnet_tasks.clear()
                    self._magnet_fetchers.clear()

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

                if action == TorrentCommand.ADD_MAGNET:
                    payload = payload or {}
                    magnet_uri = str(payload.get("magnet_uri") or "")
                    start_requested = bool(payload.get("start", True))
                    try:
                        magnet = MagnetLink.parse(magnet_uri)
                    except Exception as exc:
                        self.ui_queue.put(
                            {
                                "type": "MAGNET_ERROR",
                                "info_hash": str(info_hash or ""),
                                "display_name": "Magnet",
                                "stage": "Error",
                                "progress": 0.0,
                                "message": str(exc),
                            }
                        )
                        continue

                    actual_hash = magnet.hex_info_hash
                    existing_task = self._magnet_tasks.get(actual_hash)
                    if existing_task and not existing_task.done():
                        self._emit_magnet_event(
                            "MAGNET_PROGRESS",
                            magnet,
                            stage="Resolving",
                            progress=0.05,
                            message="This magnet is already being resolved.",
                        )
                        continue

                    task = asyncio.create_task(
                        self._resolve_magnet(magnet.uri, start_requested)
                    )
                    self._magnet_tasks[actual_hash] = task
                    continue

                if action == TorrentCommand.CANCEL_MAGNET:
                    fetcher = self._magnet_fetchers.get(str(info_hash or ""))
                    if fetcher is not None:
                        fetcher.cancel()
                    task = self._magnet_tasks.get(str(info_hash or ""))
                    if task and not task.done():
                        task.cancel()
                    continue

                if action == TorrentCommand.APPLY_APP_SETTINGS:
                    settings = dict(payload or self._settings)
                    with self._sessions_lock:
                        sessions = list(self.sessions.values())
                    for live_session in sessions:
                        try:
                            await live_session.apply_runtime_preferences(
                                listen_port=settings.get("listen_port", 6881),
                                enable_dht=settings.get("enable_dht", True),
                                enable_pex=settings.get("enable_pex", True),
                                enable_lan_discovery=settings.get("enable_lan_discovery", True),
                            )
                        except Exception as exc:
                            print(f"[Salix_T Notice] Could not apply live network preferences: {exc}")
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

                elif action == TorrentCommand.FORCE_RECHECK:
                    existing_task = self._maintenance_tasks.get(info_hash)
                    if not existing_task or existing_task.done():
                        task = asyncio.create_task(
                            self._run_force_recheck(info_hash, session)
                        )
                        self._maintenance_tasks[info_hash] = task

                elif action == TorrentCommand.ANNOUNCE:
                    if session.state in (SessionState.DOWNLOADING, SessionState.SEEDING):
                        asyncio.create_task(session.manual_announce())

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

    def add_magnet(self, magnet_uri: str, start: bool = True) -> str:
        """Begin non-blocking BEP-9 metadata retrieval for a magnet URI.

        Returns the normalized hexadecimal info hash immediately so the UI can
        associate progress/cancel events with the request.
        """
        magnet = MagnetLink.parse(magnet_uri)
        if not self._running:
            self.start_engine()
        if not self._engine_ready.wait(timeout=5.0):
            raise RuntimeError("SalixTorrent network engine is not ready.")
        if not self._loop or not self._cmd_queue or self._loop.is_closed():
            raise RuntimeError("SalixTorrent network engine is unavailable.")
        self._loop.call_soon_threadsafe(
            self._cmd_queue.put_nowait,
            (
                TorrentCommand.ADD_MAGNET,
                magnet.hex_info_hash,
                {"magnet_uri": magnet.uri, "start": bool(start)},
            ),
        )
        return magnet.hex_info_hash

    def cancel_magnet(self, info_hash: str):
        info_hash = str(info_hash or "").strip().lower()
        if not info_hash:
            return
        self._send_cmd(TorrentCommand.CANCEL_MAGNET, info_hash)

    def add_torrent(
        self,
        torrent_path: str,
        max_peers: Optional[int] = None,
        persist: bool = True,
        seed_source_path: Optional[str] = None,
        download_dir: Optional[str] = None,
    ) -> TorrentSession:
        torrent_path = os.path.abspath(os.path.expanduser(torrent_path))
        seed_source_path = (
            os.path.abspath(os.path.expanduser(seed_source_path))
            if seed_source_path
            else ""
        )

        if max_peers is None:
            max_peers = int(self._settings.get("default_max_peers", 25))
        else:
            max_peers = max(1, int(max_peers))
        if download_dir is None:
            download_dir = str(self._settings.get("download_dir") or os.path.abspath("downloads"))
        download_dir = os.path.abspath(os.path.expanduser(download_dir))

        # TorrentSession construction is lightweight: it parses .torrent
        # metadata and creates Piece descriptors, but does not hash the payload
        # file or allocate every block. External seed sources are read-only and
        # are verified only after Start is requested.
        new_session = TorrentSession(
            torrent_path,
            ui_queue=self.ui_queue,
            max_peers=max_peers,
            download_dir=download_dir,
            seed_source_path=seed_source_path or None,
            listen_port=self._settings.get("listen_port", 6881),
            enable_dht=self._settings.get("enable_dht", True),
            enable_pex=self._settings.get("enable_pex", True),
            enable_lan_discovery=self._settings.get("enable_lan_discovery", True),
            global_download_limiter=self._global_download_limiter,
            global_upload_limiter=self._global_upload_limiter,
            listen_port_callback=self._on_session_listen_port,
            incoming_peer_callback=self._on_incoming_peer,
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
        if replaced_existing:
            new_session.set_queue_priority(replacement_queue_priority, emit=False)
        else:
            new_session.set_queue_priority(
                self._settings.get("default_queue_priority", TORRENT_PRIORITY_NORMAL),
                emit=False,
            )
            new_session.set_transfer_limits(
                self._settings.get("default_download_limit_value", 0.0),
                self._settings.get("default_download_limit_unit", "KB/s"),
                self._settings.get("default_upload_limit_value", 0.0),
                self._settings.get("default_upload_limit_unit", "KB/s"),
            )

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
        max_peers: Optional[int] = None,
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

    def force_recheck(self, info_hash: str):
        """Discard fast-resume trust and hash the existing payload again."""
        with self._sessions_lock:
            if info_hash not in self.sessions:
                return False
        self._send_cmd(TorrentCommand.FORCE_RECHECK, info_hash)
        return True

    def update_trackers(self, info_hash: str):
        """Request an immediate tracker announce for an active torrent."""
        with self._sessions_lock:
            session = self.sessions.get(info_hash)
            if not session or session.state not in (SessionState.DOWNLOADING, SessionState.SEEDING):
                return False
        self._send_cmd(TorrentCommand.ANNOUNCE, info_hash)
        return True

    def pause_all(self):
        with self._sessions_lock:
            hashes = [
                h for h, session in self.sessions.items()
                if session.state in (
                    SessionState.QUEUED, SessionState.CHECKING, SessionState.FAST_RESUME,
                    SessionState.DOWNLOADING, SessionState.SEEDING,
                )
            ]
        for info_hash in hashes:
            self.pause_torrent(info_hash)

    def resume_all(self):
        with self._sessions_lock:
            hashes = [
                h for h, session in self.sessions.items()
                if session.state in (SessionState.PAUSED, SessionState.STOPPED, SessionState.ERROR)
            ]
        for info_hash in hashes:
            self.start_torrent(info_hash)

    def shutdown(self, timeout: float = 5.0):
        """Persist intent, then cleanly stop the async engine before process exit."""
        # This snapshot is the important one: it captures ACTIVE before the
        # shutdown command invokes session.stop() for network cleanup.
        self.save_session_state(force=True)

        if not self._running:
            self._connectivity.close()
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

        self._connectivity.close()
