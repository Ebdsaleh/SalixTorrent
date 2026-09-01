"""Headless SalixTorrent runner.

This module deliberately has no Dear PyGui dependency.  It consumes the same
structured engine events as the desktop UI and owns only terminal presentation,
signal handling, and headless process lifecycle.
"""

from __future__ import annotations

import json
import queue
import signal
import sys
import threading
import time
from dataclasses import dataclass
from typing import IO, Optional

from app.localization import tr, tr_value
from app.logic.session import SessionState
from app.logic.transfer_add import TransferAddRequest


@dataclass(frozen=True)
class HeadlessOptions:
    max_peers: int = 25
    download_dir: Optional[str] = None
    status_interval: float = 1.0
    json_status: bool = False
    exit_on_complete: bool = False


class HeadlessReporter:
    """Rate-limited terminal renderer for structured torrent-engine events."""

    def __init__(
        self,
        *,
        stream: IO[str] = sys.stdout,
        status_interval: float = 1.0,
        json_status: bool = False,
    ):
        self.stream = stream
        self.status_interval = max(0.1, float(status_interval or 1.0))
        self.json_status = bool(json_status)
        self._last_status_at = 0.0
        self._last_state = ""
        self._last_magnet_stage = ""
        self._last_magnet_at = 0.0

    @staticmethod
    def _format_bytes(value: object) -> str:
        try:
            size = max(0.0, float(value or 0.0))
        except (TypeError, ValueError):
            size = 0.0
        units = ("B", "KiB", "MiB", "GiB", "TiB")
        unit = units[0]
        for unit in units:
            if size < 1024.0 or unit == units[-1]:
                break
            size /= 1024.0
        if unit == "B":
            return f"{int(size)} {unit}"
        return f"{size:.2f} {unit}"

    @staticmethod
    def _status_payload(event: dict) -> dict:
        return {
            "type": "status",
            "info_hash": str(event.get("info_hash") or ""),
            "name": str(event.get("torrent_name") or ""),
            "state": str(event.get("state_label") or event.get("state") or ""),
            "progress": float(event.get("wanted_progress", event.get("progress", 0.0)) or 0.0),
            "downloaded_bytes": int(event.get("downloaded_bytes", 0) or 0),
            "total_bytes": int(event.get("total_bytes", 0) or 0),
            "download_kib_s": float(event.get("speed_kbps", 0.0) or 0.0),
            "upload_kib_s": float(event.get("upload_speed_kbps", 0.0) or 0.0),
            "peers": int(event.get("connected_peers", 0) or 0),
            "error": str(event.get("error_message") or ""),
        }

    def _write_json(self, payload: dict):
        self.stream.write(json.dumps(payload, sort_keys=True) + "\n")
        self.stream.flush()

    def message(self, text: str, *, event_type: str = "message"):
        if self.json_status:
            self._write_json({"type": event_type, "message": str(text)})
        else:
            self.stream.write(str(text) + "\n")
            self.stream.flush()

    def magnet_event(self, event: dict):
        event_type = str(event.get("type") or "")
        stage = str(event.get("stage") or "")
        progress = max(0.0, min(1.0, float(event.get("progress", 0.0) or 0.0)))
        message = str(event.get("message") or stage)

        if self.json_status:
            self._write_json(
                {
                    "type": event_type.lower(),
                    "info_hash": str(event.get("info_hash") or ""),
                    "name": str(event.get("display_name") or ""),
                    "stage": stage,
                    "progress": progress,
                    "message": message,
                }
            )
            return

        # Metadata progress can be noisy, so keep it visible but rate-limited.
        # Stage changes and terminal events are always emitted immediately.
        now = time.monotonic()
        if (
            event_type == "MAGNET_PROGRESS"
            and stage == self._last_magnet_stage
            and now - self._last_magnet_at < self.status_interval
        ):
            return
        self._last_magnet_stage = stage
        self._last_magnet_at = now
        pct = f" {progress * 100:.0f}%" if 0.0 < progress < 1.0 else ""
        self.stream.write(tr("cli.magnet.progress", "[Magnet] {stage}{pct}: {message}", stage=stage, pct=pct, message=message) + "\n")
        self.stream.flush()

    def transfer_event(self, event: dict, *, force: bool = False) -> bool:
        now = time.monotonic()
        state = str(event.get("state_label") or event.get("state") or "")
        state_changed = state != self._last_state
        if not force and not state_changed and now - self._last_status_at < self.status_interval:
            return False

        self._last_status_at = now
        self._last_state = state
        payload = self._status_payload(event)
        if self.json_status:
            self._write_json(payload)
            return True

        progress = max(0.0, min(1.0, float(payload["progress"] or 0.0))) * 100.0
        line = tr(
            "cli.transfer.status",
            "{name} | {state} | {progress:6.2f}% | Down {down:.1f} KiB/s | Up {up:.1f} KiB/s | Peers {peers} | {downloaded} / {total}",
            name=payload["name"],
            state=tr_value(payload["state"]),
            progress=progress,
            down=payload["download_kib_s"],
            up=payload["upload_kib_s"],
            peers=payload["peers"],
            downloaded=self._format_bytes(payload["downloaded_bytes"]),
            total=self._format_bytes(payload["total_bytes"]),
        )
        if payload["error"]:
            line += tr("cli.transfer.error_suffix", " | Error: {error}", error=payload["error"])
        self.stream.write(line + "\n")
        self.stream.flush()
        return True


class HeadlessRunner:
    """Run one torrent/magnet using TorrentManager without a graphical UI."""

    TERMINAL_STATES = {SessionState.ERROR, SessionState.STOPPED}

    def __init__(self, manager, event_queue: queue.Queue, *, stream: IO[str] = sys.stdout):
        self.manager = manager
        self.event_queue = event_queue
        self.stream = stream
        self._stop_requested = threading.Event()
        self._previous_handlers = {}
        self._exit_signal: Optional[int] = None

    def request_stop(self, signum=None, *_args):
        try:
            self._exit_signal = int(signum) if signum is not None else self._exit_signal
        except (TypeError, ValueError):
            pass
        self._stop_requested.set()

    def _install_signal_handlers(self):
        if threading.current_thread() is not threading.main_thread():
            return
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                self._previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, self.request_stop)
            except (ValueError, OSError, AttributeError):
                pass
        if hasattr(signal, "SIGBREAK"):
            try:
                signum = signal.SIGBREAK
                self._previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, self.request_stop)
            except (ValueError, OSError, AttributeError):
                pass

    def _restore_signal_handlers(self):
        if threading.current_thread() is not threading.main_thread():
            return
        for signum, handler in self._previous_handlers.items():
            try:
                signal.signal(signum, handler)
            except (ValueError, OSError, AttributeError):
                pass
        self._previous_handlers.clear()

    def run(self, source: str, options: HeadlessOptions) -> int:
        reporter = HeadlessReporter(
            stream=self.stream,
            status_interval=options.status_interval,
            json_status=options.json_status,
        )
        self._install_signal_handlers()
        target_hash = ""
        last_snapshot = None
        result_code = 0

        try:
            self.manager.start_engine()
            handle = self.manager.add_transfer(
                TransferAddRequest(
                    source=source,
                    start=True,
                    persist=False,
                    max_peers=options.max_peers,
                    download_dir=options.download_dir,
                )
            )
            target_hash = handle.info_hash
            reporter.message(
                tr("cli.transfer.submitted", "Headless transfer submitted: {source}", source=source),
                event_type="started",
            )

            while not self._stop_requested.is_set():
                try:
                    event = self.event_queue.get(timeout=0.25)
                except queue.Empty:
                    continue

                if not isinstance(event, dict):
                    continue
                event_type = str(event.get("type") or "")
                info_hash = str(event.get("info_hash") or "")
                if target_hash and info_hash and info_hash != target_hash:
                    continue

                if event_type.startswith("MAGNET_"):
                    reporter.magnet_event(event)
                    if event_type == "MAGNET_ERROR":
                        result_code = 2
                        break
                    if event_type == "MAGNET_CANCELLED":
                        result_code = 130 if self._stop_requested.is_set() else 2
                        break
                    continue

                if event_type != "TRANSFER_STATS":
                    continue

                last_snapshot = event
                rendered = reporter.transfer_event(event)
                state = str(event.get("state") or "")
                if state == SessionState.ERROR:
                    result_code = 2
                    break
                if options.exit_on_complete and state in {SessionState.SEEDING, SessionState.COMPLETED}:
                    if not rendered:
                        reporter.transfer_event(event, force=True)
                    break
                if state == SessionState.STOPPED:
                    break

            if self._stop_requested.is_set():
                result_code = 128 + self._exit_signal if self._exit_signal else 130
                reporter.message(tr("cli.shutdown", "Shutdown requested; stopping torrent networking..."), event_type="shutdown")
            elif last_snapshot is not None and str(last_snapshot.get("state") or "") == SessionState.ERROR:
                result_code = 2

            return result_code
        except KeyboardInterrupt:
            self._stop_requested.set()
            reporter.message(tr("cli.shutdown", "Shutdown requested; stopping torrent networking..."), event_type="shutdown")
            return 130
        except Exception as exc:
            reporter.message(tr("cli.transfer.failed", "Headless transfer failed: {error}", error=exc), event_type="error")
            return 2
        finally:
            # TorrentManager owns all networking tasks/sockets.  The headless
            # presentation layer only requests shutdown and waits for that owner
            # to tear them down in one place.
            try:
                self.manager.shutdown()
            finally:
                self._restore_signal_handlers()
