# app/engine/desktop_integration.py

from __future__ import annotations

import ctypes
import ctypes.util
import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from typing import Optional

from app.localization import tr


TRAY_ACTION_RESTORE = "restore"
TRAY_ACTION_PAUSE_ALL = "pause_all"
TRAY_ACTION_RESUME_ALL = "resume_all"
TRAY_ACTION_EXIT = "exit"
TRAY_ACTION_CLOSE_REQUESTED = "close_requested"
TRAY_ACTION_MINIMIZE_REQUESTED = "minimize_requested"


@dataclass(frozen=True)
class DesktopCapabilities:
    """Snapshot of the desktop features SalixTorrent can safely use.

    Tray availability and window-management availability are intentionally
    separate. A desktop can support notifications but no tray service, or can
    expose a tray while preventing the application from reliably hiding and
    restoring its main window. The UI uses these capabilities to avoid letting
    a user hide SalixTorrent when there is no dependable way to bring it back.
    """

    platform: str
    tray_backend: str
    tray_supported: bool
    tray_running: bool
    tray_menu_supported: bool
    notifications_supported: bool
    window_hide_supported: bool
    window_activation_supported: bool
    minimize_to_tray_supported: bool
    close_to_tray_supported: bool
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


class DesktopIntegration:
    """Platform-neutral desktop integration controller.

    Torrent/UI code talks only to this facade. Native tray callbacks enqueue
    small semantic actions which are consumed by Dear PyGui's main thread.

    Backends:
      * Windows: dependency-free Win32 notification-area implementation.
      * Linux/BSD: pystray (AppIndicator/GTK/Xorg as available) plus X11
        viewport control.
      * macOS: pystray status item plus AppKit viewport control.

    Every feature fails open. If a tray backend disappears or cannot start,
    SalixTorrent will continue running as a normal window and will never hide
    itself into an unreachable tray.
    """

    _instance: Optional["DesktopIntegration"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._settings: dict = {}
        self._actions: "queue.Queue[str]" = queue.Queue()
        self._tray = _make_tray_backend(self._actions)
        self._window = _make_window_backend()
        self._viewport_handle: int = 0
        self._last_maintain_at = 0.0

    @classmethod
    def get_instance(cls) -> "DesktopIntegration":
        return cls()

    @classmethod
    def _reset_for_tests(cls):
        """Reset the singleton. Intended only for isolated regression tests."""
        instance = cls._instance
        if instance is not None:
            try:
                instance.stop()
            except Exception:
                pass
        cls._instance = None

    @property
    def supported(self) -> bool:
        """Backward-compatible alias for tray capability."""
        return bool(self._tray.supported)

    def configure(self, settings: dict):
        self._settings = dict(settings or {})
        if self._settings.get("system_tray_enabled", True):
            self._tray.start()
        else:
            self._tray.stop()

    def set_viewport_handle(self, handle: object):
        """Bind the native viewport window to the desktop backends.

        Dear PyGui does not guarantee a public cross-platform native-handle
        accessor.  A caller-supplied handle is therefore treated as an optional
        fast path; platform backends can discover the real top-level window
        after the viewport has been shown.
        """
        try:
            resolved = int(handle or 0)
        except (TypeError, ValueError, OverflowError):
            resolved = 0

        self._window.set_handle(resolved)
        if not resolved:
            try:
                resolved = int(self._window.discover_handle() or 0)
            except Exception:
                resolved = 0
            if resolved:
                self._window.set_handle(resolved)

        self._viewport_handle = int(resolved or 0)
        self._tray.set_target_window(self._viewport_handle)
        if self._viewport_handle:
            self._window.install_event_bridge(self._actions)
        return self._viewport_handle

    def refresh_viewport_binding(self) -> int:
        """Recover a missing/stale native viewport binding when possible."""
        try:
            resolved = int(self._window.discover_handle() or 0)
        except Exception:
            resolved = 0
        if resolved and resolved != self._viewport_handle:
            self._window.set_handle(resolved)
            self._viewport_handle = resolved
            self._tray.set_target_window(resolved)
        if self._viewport_handle:
            self._window.install_event_bridge(self._actions)
        return self._viewport_handle

    def queue_action(self, action: str):
        self._actions.put(str(action))

    def poll_actions(self):
        actions = []
        while True:
            try:
                actions.append(self._actions.get_nowait())
            except queue.Empty:
                break
        return actions

    def maintain(self):
        """Keep a requested tray alive without turning the render loop into polling.

        This is deliberately low-frequency and only restarts a tray that should
        be running but is not. It makes source and frozen builds share the same
        lifetime semantics and recovers from desktop-shell restarts/failures.
        """
        now = time.monotonic()
        if now - self._last_maintain_at < 2.0:
            return
        self._last_maintain_at = now
        self.refresh_viewport_binding()
        if self._settings.get("system_tray_enabled", True) and not self._tray.running:
            self._tray.start()

    def notify(self, title: str, message: str) -> bool:
        if not self._settings.get("native_notifications", True):
            return False

        # Windows notifications are provided by the tray backend. On Unix and
        # macOS there can also be an independent desktop notification service.
        if self._tray.running and self._tray.notification_supported:
            if self._tray.notify(str(title), str(message)):
                return True
        return _fallback_notify(str(title), str(message))

    def should_minimize_to_tray(self) -> bool:
        caps = self.capability_snapshot()
        return bool(
            self._settings.get("system_tray_enabled", True)
            and self._settings.get("minimize_to_tray", True)
            and caps.tray_running
            and caps.minimize_to_tray_supported
        )

    def should_close_to_tray(self) -> bool:
        caps = self.capability_snapshot()
        return bool(
            self._settings.get("system_tray_enabled", True)
            and self._settings.get("close_to_tray", True)
            and caps.tray_running
            and caps.close_to_tray_supported
        )

    def is_native_viewport_minimized(self) -> bool:
        self.refresh_viewport_binding()
        return bool(self._window.is_minimized())

    def hide_viewport(self) -> bool:
        # Never hide when there is no live tray to recover the window.
        if not self._tray.running:
            return False
        self.refresh_viewport_binding()
        return bool(self._window.hide())

    def minimize_viewport(self) -> bool:
        self.refresh_viewport_binding()
        return bool(self._window.minimize())

    def show_viewport(self) -> bool:
        # Showing is always allowed: it is also useful after a failed tray
        # operation or during diagnostics.
        self.refresh_viewport_binding()
        return bool(self._window.show_and_activate())

    def capability_snapshot(self) -> DesktopCapabilities:
        self._tray.probe()
        self._window.probe()

        tray_supported = bool(self._tray.supported)
        window_hide = bool(self._window.hide_supported)
        window_activate = bool(self._window.activation_supported)
        notification_supported = bool(
            self._tray.notification_supported or _fallback_notifications_supported()
        )
        minimize_supported = bool(
            tray_supported
            and window_hide
            and self._window.minimize_detection_supported
        )
        close_supported = bool(tray_supported and window_hide and window_activate)

        detail_parts = []
        if self._tray.detail:
            detail_parts.append(self._tray.detail)
        if self._window.detail:
            detail_parts.append(self._window.detail)

        return DesktopCapabilities(
            platform=platform.system() or sys.platform,
            tray_backend=self._tray.name,
            tray_supported=tray_supported,
            tray_running=bool(self._tray.running),
            tray_menu_supported=bool(self._tray.menu_supported),
            notifications_supported=notification_supported,
            window_hide_supported=window_hide,
            window_activation_supported=window_activate,
            minimize_to_tray_supported=minimize_supported,
            close_to_tray_supported=close_supported,
            detail="; ".join(part for part in detail_parts if part),
        )

    def stop(self):
        self._window.remove_event_bridge()
        self._tray.stop()


class _TrayBackend:
    name = "Unavailable"
    supported = False
    running = False
    menu_supported = False
    notification_supported = False
    detail = "No supported tray backend detected."

    def __init__(self, actions: "queue.Queue[str]"):
        self.actions = actions

    def probe(self):
        return self.supported

    def start(self) -> bool:
        return False

    def stop(self):
        return None

    def notify(self, title: str, message: str) -> bool:
        del title, message
        return False

    def set_target_window(self, handle: int):
        del handle


class _WindowBackend:
    name = "Unavailable"
    hide_supported = False
    activation_supported = False
    minimize_detection_supported = False
    detail = "Native viewport control is unavailable."

    def __init__(self):
        self.handle = 0

    def set_handle(self, handle: int):
        self.handle = int(handle or 0)

    def discover_handle(self) -> int:
        return int(self.handle or 0)

    def install_event_bridge(self, actions: "queue.Queue[str]") -> bool:
        del actions
        return False

    def remove_event_bridge(self):
        return None

    def probe(self):
        return bool(self.hide_supported or self.activation_supported)

    def hide(self) -> bool:
        return False

    def minimize(self) -> bool:
        return False

    def show_and_activate(self) -> bool:
        return False

    def is_minimized(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Windows native backend
# ---------------------------------------------------------------------------


class _WindowsWindowBackend(_WindowBackend):
    name = "Win32"
    hide_supported = True
    activation_supported = True
    minimize_detection_supported = True
    detail = "Win32 viewport API available; waiting for SalixTorrent window."

    SW_HIDE = 0
    SW_SHOW = 5
    SW_MINIMIZE = 6
    SW_RESTORE = 9

    HWND_TOP = 0
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2

    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_SHOWWINDOW = 0x0040

    GWLP_WNDPROC = -4
    WM_CLOSE = 0x0010
    WM_SYSCOMMAND = 0x0112
    SC_MINIMIZE = 0xF020

    def __init__(self):
        super().__init__()
        self._event_actions = None
        self._wndproc_ref = None
        self._old_wndproc = 0
        self._event_bridge_handle = 0

    @staticmethod
    def _user32():
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        LRESULT = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
        LONG_PTR = ctypes.c_ssize_t
        WNDENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM,
        )

        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindowAsync.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetActiveWindow.argtypes = [wintypes.HWND]
        user32.SetActiveWindow.restype = wintypes.HWND
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.AttachThreadInput.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.BOOL,
        ]
        user32.AttachThreadInput.restype = wintypes.BOOL

        # Get/SetWindowLongPtrW are exported as Get/SetWindowLongW on 32-bit.
        get_wndproc = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_wndproc = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        get_wndproc.argtypes = [wintypes.HWND, ctypes.c_int]
        get_wndproc.restype = LONG_PTR
        set_wndproc.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
        set_wndproc.restype = LONG_PTR
        user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.CallWindowProcW.restype = LRESULT

        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        return (
            user32,
            kernel32,
            wintypes,
            LRESULT,
            LONG_PTR,
            WNDENUMPROC,
            get_wndproc,
            set_wndproc,
        )

    def probe(self):
        try:
            self._user32()
            self.hide_supported = True
            self.activation_supported = True
            self.minimize_detection_supported = True
            if self.handle:
                self.detail = f"Win32 viewport bound (HWND 0x{self.handle:X})."
            elif not self.detail.startswith("Win32 viewport discovery failed"):
                self.detail = "Win32 viewport API available; waiting for SalixTorrent window."
            return True
        except Exception as exc:
            self.hide_supported = False
            self.activation_supported = False
            self.minimize_detection_supported = False
            self.detail = f"Win32 viewport API unavailable: {exc}"
            return False

    @staticmethod
    def _window_title(user32, wintypes, hwnd) -> str:
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return str(buffer.value or "")

    def discover_handle(self) -> int:
        """Find Dear PyGui's top-level HWND without relying on a DPG handle API."""
        try:
            (
                user32,
                _kernel32,
                wintypes,
                _LRESULT,
                _LONG_PTR,
                WNDENUMPROC,
                _get_wndproc,
                _set_wndproc,
            ) = self._user32()

            if self.handle:
                native = wintypes.HWND(int(self.handle))
                if user32.IsWindow(native):
                    return int(self.handle)

            current_pid = os.getpid()
            exact = []
            fallback = []

            @WNDENUMPROC
            def enum_proc(hwnd, _lparam):
                process_id = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
                if int(process_id.value) != int(current_pid):
                    return True

                title = self._window_title(user32, wintypes, hwnd)
                compact_title = "".join(title.lower().split())
                if compact_title == "salixtorrent(salix_t)":
                    exact.append(int(hwnd))
                    return False

                # Be tolerant of presentation-only title changes (for example
                # ``Salix Torrent`` vs ``SalixTorrent``).  The PID filter above
                # already restricts candidates to this SalixTorrent process.
                if (
                    title
                    and "salix" in title.lower()
                    and "torrent" in title.lower()
                    and compact_title != "salixtorrenttray"
                    and user32.IsWindowVisible(hwnd)
                ):
                    fallback.append(int(hwnd))
                return True

            user32.EnumWindows(enum_proc, 0)
            resolved = exact[0] if exact else (fallback[0] if fallback else 0)
            if resolved:
                self.handle = int(resolved)
                self.detail = f"Win32 viewport bound (HWND 0x{self.handle:X})."
                return self.handle

            self.detail = (
                "Win32 viewport discovery failed: no SalixTorrent top-level window "
                "was found for the current process."
            )
            return 0
        except Exception as exc:
            self.detail = f"Win32 viewport discovery failed: {type(exc).__name__}: {exc}"
            return 0

    def _native(self):
        if not self.handle:
            self.discover_handle()
        if not self.handle:
            return None, None, None
        (
            user32,
            _kernel32,
            wintypes,
            _LRESULT,
            _LONG_PTR,
            _WNDENUMPROC,
            _get_wndproc,
            _set_wndproc,
        ) = self._user32()
        hwnd = wintypes.HWND(int(self.handle))
        if not user32.IsWindow(hwnd):
            self.handle = 0
            if not self.discover_handle():
                return user32, wintypes, None
            hwnd = wintypes.HWND(int(self.handle))
        return user32, wintypes, hwnd

    @classmethod
    def activate_handle(cls, handle: int) -> bool:
        """Restore and foreground a HWND, including from a tray user action."""
        if not handle:
            return False
        try:
            (
                user32,
                kernel32,
                wintypes,
                _LRESULT,
                _LONG_PTR,
                _WNDENUMPROC,
                _get_wndproc,
                _set_wndproc,
            ) = cls._user32()
            hwnd = wintypes.HWND(int(handle))
            if not user32.IsWindow(hwnd):
                return False

            # Restore visibility first. ShowWindowAsync is useful when this is
            # called by the tray's message thread rather than the viewport owner.
            user32.ShowWindowAsync(hwnd, cls.SW_RESTORE)
            user32.ShowWindow(hwnd, cls.SW_RESTORE)
            user32.ShowWindow(hwnd, cls.SW_SHOW)
            user32.SetWindowPos(
                hwnd,
                wintypes.HWND(cls.HWND_TOP),
                0,
                0,
                0,
                0,
                cls.SWP_NOMOVE | cls.SWP_NOSIZE | cls.SWP_SHOWWINDOW,
            )
            user32.BringWindowToTop(hwnd)

            foreground = user32.GetForegroundWindow()
            caller_thread = int(kernel32.GetCurrentThreadId() or 0)
            target_thread = int(user32.GetWindowThreadProcessId(hwnd, None) or 0)
            foreground_thread = int(
                user32.GetWindowThreadProcessId(foreground, None)
                if foreground
                else 0
            )

            attached_pairs = []
            for first, second in (
                (caller_thread, target_thread),
                (caller_thread, foreground_thread),
                (target_thread, foreground_thread),
            ):
                if (
                    first
                    and second
                    and first != second
                    and (first, second) not in attached_pairs
                    and user32.AttachThreadInput(first, second, True)
                ):
                    attached_pairs.append((first, second))

            try:
                user32.BringWindowToTop(hwnd)
                user32.SetActiveWindow(hwnd)
                foregrounded = bool(user32.SetForegroundWindow(hwnd))
                user32.SetFocus(hwnd)

                if user32.GetForegroundWindow() == hwnd:
                    return True

                # Foreground-lock fallback: briefly raise without permanently
                # changing the application's always-on-top state.
                user32.SetWindowPos(
                    hwnd,
                    wintypes.HWND(cls.HWND_TOPMOST),
                    0,
                    0,
                    0,
                    0,
                    cls.SWP_NOMOVE | cls.SWP_NOSIZE | cls.SWP_SHOWWINDOW,
                )
                user32.SetWindowPos(
                    hwnd,
                    wintypes.HWND(cls.HWND_NOTOPMOST),
                    0,
                    0,
                    0,
                    0,
                    cls.SWP_NOMOVE | cls.SWP_NOSIZE | cls.SWP_SHOWWINDOW,
                )
                user32.SetForegroundWindow(hwnd)
                user32.SetActiveWindow(hwnd)
                user32.SetFocus(hwnd)
                return bool(foregrounded or user32.GetForegroundWindow() == hwnd)
            finally:
                for first, second in reversed(attached_pairs):
                    try:
                        user32.AttachThreadInput(first, second, False)
                    except Exception:
                        pass
        except Exception:
            return False

    def hide(self) -> bool:
        try:
            user32, _wintypes, hwnd = self._native()
            if hwnd is None:
                return False
            user32.ShowWindow(hwnd, self.SW_HIDE)
            return True
        except Exception as exc:
            self.detail = f"Win32 hide failed: {exc}"
            return False

    def minimize(self) -> bool:
        try:
            user32, _wintypes, hwnd = self._native()
            if hwnd is None:
                return False
            user32.ShowWindow(hwnd, self.SW_MINIMIZE)
            return True
        except Exception as exc:
            self.detail = f"Win32 minimize failed: {exc}"
            return False

    def is_minimized(self) -> bool:
        try:
            user32, _wintypes, hwnd = self._native()
            return bool(hwnd is not None and user32.IsIconic(hwnd))
        except Exception:
            return False

    def show_and_activate(self) -> bool:
        self.discover_handle()
        result = self.activate_handle(self.handle)
        if not result and self.handle:
            self.detail = "Win32 restore succeeded incompletely: Windows denied foreground focus."
        elif result:
            self.detail = (
                f"Win32 viewport bound (HWND 0x{self.handle:X}); activation succeeded."
            )
        return result

    def install_event_bridge(self, actions: "queue.Queue[str]") -> bool:
        """Convert native close/minimize requests into semantic UI actions."""
        if self._event_bridge_handle and self._wndproc_ref is not None:
            return True
        self.discover_handle()
        if not self.handle:
            return False

        try:
            (
                user32,
                _kernel32,
                wintypes,
                LRESULT,
                LONG_PTR,
                _WNDENUMPROC,
                get_wndproc,
                set_wndproc,
            ) = self._user32()
            hwnd = wintypes.HWND(int(self.handle))
            if not user32.IsWindow(hwnd):
                return False

            WNDPROC = ctypes.WINFUNCTYPE(
                LRESULT,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )
            old_proc = int(get_wndproc(hwnd, self.GWLP_WNDPROC) or 0)
            if not old_proc:
                return False

            @WNDPROC
            def wndproc(window, msg, wparam, lparam):
                try:
                    if msg == self.WM_CLOSE:
                        actions.put(TRAY_ACTION_CLOSE_REQUESTED)
                        return 0
                    if (
                        msg == self.WM_SYSCOMMAND
                        and (int(wparam) & 0xFFF0) == self.SC_MINIMIZE
                    ):
                        actions.put(TRAY_ACTION_MINIMIZE_REQUESTED)
                        return 0
                    return user32.CallWindowProcW(
                        ctypes.c_void_p(old_proc),
                        window,
                        msg,
                        wparam,
                        lparam,
                    )
                except Exception:
                    try:
                        return user32.CallWindowProcW(
                            ctypes.c_void_p(old_proc),
                            window,
                            msg,
                            wparam,
                            lparam,
                        )
                    except Exception:
                        return 0

            proc_pointer = ctypes.cast(wndproc, ctypes.c_void_p).value
            if not proc_pointer:
                return False
            ctypes.set_last_error(0)
            previous = int(
                set_wndproc(
                    hwnd,
                    self.GWLP_WNDPROC,
                    LONG_PTR(proc_pointer),
                )
                or 0
            )
            error = ctypes.get_last_error()
            if not previous and error:
                raise ctypes.WinError(error)

            self._event_actions = actions
            self._wndproc_ref = wndproc
            self._old_wndproc = previous or old_proc
            self._event_bridge_handle = int(self.handle)
            self.detail = (
                f"Win32 viewport bound (HWND 0x{self.handle:X}); "
                "native close/minimize bridge active."
            )
            return True
        except Exception as exc:
            self.detail = f"Win32 event bridge unavailable: {type(exc).__name__}: {exc}"
            self._event_actions = None
            self._wndproc_ref = None
            self._old_wndproc = 0
            self._event_bridge_handle = 0
            return False

    def remove_event_bridge(self):
        if not self._event_bridge_handle or not self._old_wndproc:
            return
        try:
            (
                user32,
                _kernel32,
                wintypes,
                _LRESULT,
                LONG_PTR,
                _WNDENUMPROC,
                _get_wndproc,
                set_wndproc,
            ) = self._user32()
            hwnd = wintypes.HWND(int(self._event_bridge_handle))
            if user32.IsWindow(hwnd):
                set_wndproc(
                    hwnd,
                    self.GWLP_WNDPROC,
                    LONG_PTR(int(self._old_wndproc)),
                )
        except Exception:
            pass
        finally:
            self._event_actions = None
            self._wndproc_ref = None
            self._old_wndproc = 0
            self._event_bridge_handle = 0


class _WindowsTrayBackend(_TrayBackend):
    """Dependency-free Win32 notification-area backend."""

    name = "Windows notification area"
    supported = True
    menu_supported = True
    notification_supported = True
    detail = ""

    WM_TRAYICON = 0x8000 + 51
    WM_CLOSE = 0x0010
    WM_DESTROY = 0x0002
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONUP = 0x0205

    NIM_ADD = 0x00000000
    NIM_MODIFY = 0x00000001
    NIM_DELETE = 0x00000002
    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    NIF_INFO = 0x00000010
    NIIF_INFO = 0x00000001

    TPM_RIGHTBUTTON = 0x0002
    TPM_RETURNCMD = 0x0100
    MF_STRING = 0x0000
    MF_SEPARATOR = 0x0800

    CMD_OPEN = 1001
    CMD_PAUSE_ALL = 1002
    CMD_RESUME_ALL = 1003
    CMD_EXIT = 1004

    def __init__(self, actions: "queue.Queue[str]"):
        super().__init__(actions)
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stop_requested = threading.Event()
        self._hwnd = 0
        self._nid = None
        self._wndproc_ref = None
        self._lock = threading.Lock()
        self._last_start_attempt = 0.0
        self._target_window = 0

    def set_target_window(self, handle: int):
        try:
            self._target_window = int(handle or 0)
        except (TypeError, ValueError, OverflowError):
            self._target_window = 0

    def _request_restore(self):
        # Run the native activation while this tray thread is handling the
        # user's click. Windows foreground-lock rules are most permissive here.
        if self._target_window:
            _WindowsWindowBackend.activate_handle(self._target_window)
        self.actions.put(TRAY_ACTION_RESTORE)

    def probe(self):
        try:
            _WindowsWindowBackend._user32()
            self.supported = True
            if self.detail.startswith("Win32 tray failed"):
                self.detail = ""
        except Exception as exc:
            self.supported = False
            self.detail = f"Win32 tray API unavailable: {exc}"
        return self.supported

    @staticmethod
    def _basic_user32():
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.PostMessageW.restype = wintypes.BOOL
        return user32, wintypes

    def start(self) -> bool:
        if not self.probe():
            return False
        now = time.monotonic()
        with self._lock:
            if self._thread and self._thread.is_alive() and self.running:
                return True
            # Do not spin continuously if the shell refuses tray creation.
            if now - self._last_start_attempt < 1.5:
                return self.running
            self._last_start_attempt = now
            self._stop_requested.clear()
            self._ready.clear()
            self.running = False
            self._thread = threading.Thread(
                target=self._run,
                name="SalixTrayWin32",
                daemon=True,
            )
            self._thread.start()
        self._ready.wait(timeout=2.0)
        return bool(self.running)

    def stop(self):
        thread = self._thread
        if not thread or not thread.is_alive():
            self.running = False
            return
        self._stop_requested.set()
        try:
            user32, wintypes = self._basic_user32()
            if self._hwnd:
                user32.PostMessageW(
                    wintypes.HWND(self._hwnd),
                    self.WM_CLOSE,
                    wintypes.WPARAM(0),
                    wintypes.LPARAM(0),
                )
        except Exception:
            pass
        thread.join(timeout=2.0)
        self.running = False

    def notify(self, title: str, message: str) -> bool:
        if not self.running:
            return False
        try:
            if not self._hwnd or self._nid is None:
                return False
            nid = self._nid
            nid.uFlags = self.NIF_INFO
            nid.szInfoTitle = str(title)[:63]
            nid.szInfo = str(message)[:255]
            nid.dwInfoFlags = self.NIIF_INFO
            shell32 = ctypes.windll.shell32
            shell32.Shell_NotifyIconW.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
            shell32.Shell_NotifyIconW.restype = ctypes.c_int
            result = bool(
                shell32.Shell_NotifyIconW(self.NIM_MODIFY, ctypes.byref(nid))
            )
            nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
            return result
        except Exception as exc:
            self.detail = f"Win32 notification failed: {exc}"
            return False

    def _run(self):
        class_name = None
        hinstance = None
        hwnd = None
        nid = None
        shell32 = None
        user32 = None
        try:
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32
            kernel32 = ctypes.windll.kernel32

            LRESULT = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
            HMODULE = getattr(wintypes, "HMODULE", wintypes.HANDLE)
            HMENU = getattr(wintypes, "HMENU", wintypes.HANDLE)
            LPVOID = ctypes.c_void_p
            UINT_PTR = ctypes.c_size_t

            WNDPROC = ctypes.WINFUNCTYPE(
                LRESULT,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [
                    ("style", wintypes.UINT),
                    ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR),
                ]

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            class NOTIFYICONDATAW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("hWnd", wintypes.HWND),
                    ("uID", wintypes.UINT),
                    ("uFlags", wintypes.UINT),
                    ("uCallbackMessage", wintypes.UINT),
                    ("hIcon", wintypes.HICON),
                    ("szTip", wintypes.WCHAR * 128),
                    ("dwState", wintypes.DWORD),
                    ("dwStateMask", wintypes.DWORD),
                    ("szInfo", wintypes.WCHAR * 256),
                    ("uTimeoutOrVersion", wintypes.UINT),
                    ("szInfoTitle", wintypes.WCHAR * 64),
                    ("dwInfoFlags", wintypes.DWORD),
                    ("guidItem", GUID),
                    ("hBalloonIcon", wintypes.HICON),
                ]

            user32.DefWindowProcW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.DefWindowProcW.restype = LRESULT
            user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
            user32.RegisterClassW.restype = wintypes.ATOM
            user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
            user32.UnregisterClassW.restype = wintypes.BOOL
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD,
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
                wintypes.DWORD,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.HWND,
                HMENU,
                wintypes.HINSTANCE,
                LPVOID,
            ]
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
            user32.LoadIconW.restype = wintypes.HICON
            user32.CreatePopupMenu.argtypes = []
            user32.CreatePopupMenu.restype = HMENU
            user32.AppendMenuW.argtypes = [
                HMENU,
                wintypes.UINT,
                UINT_PTR,
                wintypes.LPCWSTR,
            ]
            user32.AppendMenuW.restype = wintypes.BOOL
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            user32.TrackPopupMenu.argtypes = [
                HMENU,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.HWND,
                ctypes.c_void_p,
            ]
            user32.TrackPopupMenu.restype = wintypes.UINT
            user32.DestroyMenu.argtypes = [HMENU]
            user32.DestroyMenu.restype = wintypes.BOOL
            user32.DestroyWindow.argtypes = [wintypes.HWND]
            user32.DestroyWindow.restype = wintypes.BOOL
            user32.PostQuitMessage.argtypes = [ctypes.c_int]
            user32.PostQuitMessage.restype = None
            user32.GetMessageW.argtypes = [
                ctypes.POINTER(wintypes.MSG),
                wintypes.HWND,
                wintypes.UINT,
                wintypes.UINT,
            ]
            user32.GetMessageW.restype = wintypes.BOOL
            user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.TranslateMessage.restype = wintypes.BOOL
            user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.DispatchMessageW.restype = LRESULT
            user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
            user32.RegisterWindowMessageW.restype = wintypes.UINT

            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = HMODULE
            shell32.Shell_NotifyIconW.argtypes = [
                wintypes.DWORD,
                ctypes.POINTER(NOTIFYICONDATAW),
            ]
            shell32.Shell_NotifyIconW.restype = wintypes.BOOL

            def make_int_resource(value: int):
                return ctypes.cast(ctypes.c_void_p(int(value)), wintypes.LPCWSTR)

            taskbar_created = int(
                user32.RegisterWindowMessageW("TaskbarCreated") or 0
            )

            @WNDPROC
            def wndproc(window, msg, wparam, lparam):
                try:
                    if taskbar_created and msg == taskbar_created and self._nid is not None:
                        shell32.Shell_NotifyIconW(
                            self.NIM_ADD, ctypes.byref(self._nid)
                        )
                        return 0
                    if msg == self.WM_TRAYICON:
                        event = int(lparam) & 0xFFFF
                        if event == self.WM_LBUTTONDBLCLK:
                            self._request_restore()
                            return 0
                        if event == self.WM_RBUTTONUP:
                            menu = user32.CreatePopupMenu()
                            if menu:
                                user32.AppendMenuW(
                                    menu, self.MF_STRING, self.CMD_OPEN, tr("tray.open", "Open SalixTorrent")
                                )
                                user32.AppendMenuW(
                                    menu, self.MF_SEPARATOR, 0, None
                                )
                                user32.AppendMenuW(
                                    menu, self.MF_STRING, self.CMD_PAUSE_ALL, tr("tray.pause_all", "Pause All")
                                )
                                user32.AppendMenuW(
                                    menu, self.MF_STRING, self.CMD_RESUME_ALL, tr("tray.resume_all", "Resume All")
                                )
                                user32.AppendMenuW(
                                    menu, self.MF_SEPARATOR, 0, None
                                )
                                user32.AppendMenuW(
                                    menu, self.MF_STRING, self.CMD_EXIT, tr("tray.exit", "Exit")
                                )
                                point = wintypes.POINT()
                                user32.GetCursorPos(ctypes.byref(point))
                                user32.SetForegroundWindow(window)
                                command = user32.TrackPopupMenu(
                                    menu,
                                    self.TPM_RIGHTBUTTON | self.TPM_RETURNCMD,
                                    point.x,
                                    point.y,
                                    0,
                                    window,
                                    None,
                                )
                                user32.DestroyMenu(menu)
                                if command == self.CMD_OPEN:
                                    self._request_restore()
                                elif command == self.CMD_PAUSE_ALL:
                                    self.actions.put(TRAY_ACTION_PAUSE_ALL)
                                elif command == self.CMD_RESUME_ALL:
                                    self.actions.put(TRAY_ACTION_RESUME_ALL)
                                elif command == self.CMD_EXIT:
                                    self.actions.put(TRAY_ACTION_EXIT)
                            return 0
                    if msg == self.WM_CLOSE:
                        user32.DestroyWindow(window)
                        return 0
                    if msg == self.WM_DESTROY:
                        user32.PostQuitMessage(0)
                        return 0
                    return user32.DefWindowProcW(window, msg, wparam, lparam)
                except Exception:
                    try:
                        return user32.DefWindowProcW(window, msg, wparam, lparam)
                    except Exception:
                        return 0

            self._wndproc_ref = wndproc
            class_name = f"SalixTorrentTrayWindow_{os.getpid()}_{id(self)}"
            hinstance = kernel32.GetModuleHandleW(None)
            wc = WNDCLASSW()
            wc.lpfnWndProc = wndproc
            wc.hInstance = hinstance
            wc.lpszClassName = class_name
            atom = user32.RegisterClassW(ctypes.byref(wc))
            if not atom:
                raise ctypes.WinError()

            hwnd = user32.CreateWindowExW(
                0,
                class_name,
                "SalixTorrent Tray",
                0,
                0,
                0,
                0,
                0,
                None,
                None,
                hinstance,
                None,
            )
            if not hwnd:
                raise ctypes.WinError()
            self._hwnd = int(hwnd)

            icon = user32.LoadIconW(None, make_int_resource(32512))
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = hwnd
            nid.uID = 1
            nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
            nid.uCallbackMessage = self.WM_TRAYICON
            nid.hIcon = icon
            nid.szTip = tr("tray.tooltip", "SalixTorrent (Salix_T)")
            self._nid = nid
            if not shell32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(nid)):
                raise ctypes.WinError()

            self.running = True
            self.detail = ""
            self._ready.set()

            msg = wintypes.MSG()
            while not self._stop_requested.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self.detail = f"Win32 tray failed: {type(exc).__name__}: {exc}"
        finally:
            self.running = False
            self._ready.set()
            if shell32 is not None and nid is not None:
                try:
                    shell32.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(nid))
                except Exception:
                    pass
            if user32 is not None and hwnd:
                try:
                    user32.DestroyWindow(hwnd)
                except Exception:
                    pass
            if user32 is not None and class_name and hinstance:
                try:
                    user32.UnregisterClassW(class_name, hinstance)
                except Exception:
                    pass
            self._hwnd = 0
            self._nid = None


# ---------------------------------------------------------------------------
# Linux / BSD / macOS tray backend
# ---------------------------------------------------------------------------


class _PystrayTrayBackend(_TrayBackend):
    name = "pystray"
    supported = True
    detail = "Not started yet."

    def __init__(self, actions: "queue.Queue[str]"):
        super().__init__(actions)
        self.running = False
        self.menu_supported = False
        self.notification_supported = False
        self._icon = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._loaded = False
        self._pystray = None
        self._Menu = None
        self._MenuItem = None
        self._last_start_attempt = 0.0

    @staticmethod
    def _is_bsd() -> bool:
        value = sys.platform.lower()
        return value.startswith(("freebsd", "openbsd", "netbsd", "dragonfly"))

    def _load(self) -> bool:
        if self._loaded:
            return bool(self.supported)

        # pystray's automatic platform selection is Linux/macOS/Windows
        # oriented. On BSD, explicitly select its Xorg backend unless the user
        # has already requested another backend.
        if self._is_bsd():
            os.environ.setdefault("PYSTRAY_BACKEND", "xorg")

        try:
            import pystray
            from pystray import Menu, MenuItem

            self._pystray = pystray
            self._Menu = Menu
            self._MenuItem = MenuItem
            icon_type = pystray.Icon
            self.menu_supported = bool(getattr(icon_type, "HAS_MENU", True))
            self.notification_supported = bool(
                getattr(icon_type, "HAS_NOTIFICATION", False)
            )
            backend_module = getattr(icon_type, "__module__", "")
            if backend_module:
                self.name = f"pystray ({backend_module.rsplit('.', 1)[-1]})"
            self.supported = True
            self.detail = ""
        except Exception as exc:
            self.supported = False
            self.detail = (
                f"pystray unavailable: {type(exc).__name__}: {exc}. "
                "Linux/BSD needs a working tray backend/display."
            )
        self._loaded = True
        return self.supported

    def probe(self):
        return self._load()

    @staticmethod
    def _icon_image():
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (64, 64), (27, 29, 32, 255))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((5, 5, 58, 58), radius=10, fill=(18, 48, 38, 255))
        draw.line((17, 18, 47, 18), fill=(0, 255, 128, 255), width=5)
        draw.line((17, 31, 43, 31), fill=(0, 255, 128, 255), width=5)
        draw.line((17, 44, 47, 44), fill=(0, 255, 128, 255), width=5)
        return image

    def _build_icon(self):
        Menu = self._Menu
        MenuItem = self._MenuItem

        def enqueue(action: str):
            def callback(*_args):
                self.actions.put(action)
            return callback

        menu = Menu(
            MenuItem(
                tr("tray.open", "Open SalixTorrent"),
                enqueue(TRAY_ACTION_RESTORE),
                default=True,
            ),
            Menu.SEPARATOR,
            MenuItem(tr("tray.pause_all", "Pause All"), enqueue(TRAY_ACTION_PAUSE_ALL)),
            MenuItem(tr("tray.resume_all", "Resume All"), enqueue(TRAY_ACTION_RESUME_ALL)),
            Menu.SEPARATOR,
            MenuItem(tr("tray.exit", "Exit"), enqueue(TRAY_ACTION_EXIT)),
        )
        return self._pystray.Icon(
            "SalixTorrent",
            self._icon_image(),
            tr("tray.tooltip", "SalixTorrent (Salix_T)"),
            menu,
        )

    def start(self) -> bool:
        if not self._load():
            return False
        now = time.monotonic()
        with self._lock:
            if self.running:
                return True
            if now - self._last_start_attempt < 1.5:
                return False
            self._last_start_attempt = now
            self._ready.clear()
            try:
                self._icon = self._build_icon()
            except Exception as exc:
                self.supported = False
                self.detail = f"Could not create tray icon: {type(exc).__name__}: {exc}"
                return False

            if sys.platform == "darwin":
                try:
                    self._icon.run_detached(setup=self._setup_icon)
                except Exception as exc:
                    self.detail = (
                        f"macOS status-item startup failed: {type(exc).__name__}: {exc}"
                    )
                    return False
            else:
                self._thread = threading.Thread(
                    target=self._run,
                    name="SalixTrayPystray",
                    daemon=True,
                )
                self._thread.start()

        self._ready.wait(timeout=2.5)
        return bool(self.running)

    def _setup_icon(self, icon):
        try:
            icon.visible = True
        finally:
            self.running = True
            self.detail = ""
            self._ready.set()

    def _run(self):
        try:
            self._icon.run(setup=self._setup_icon)
        except Exception as exc:
            self.detail = f"Tray runtime failed: {type(exc).__name__}: {exc}"
        finally:
            self.running = False
            self._ready.set()

    def stop(self):
        icon = self._icon
        if icon is None:
            self.running = False
            return
        try:
            icon.stop()
        except Exception as exc:
            self.detail = f"Tray shutdown warning: {type(exc).__name__}: {exc}"
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self.running = False
        self._icon = None
        self._thread = None

    def notify(self, title: str, message: str) -> bool:
        icon = self._icon
        if not self.running or icon is None or not self.notification_supported:
            return False
        try:
            icon.notify(message, title)
            return True
        except Exception as exc:
            self.detail = f"Tray notification failed: {type(exc).__name__}: {exc}"
            return False


# ---------------------------------------------------------------------------
# Linux / BSD X11 viewport control
# ---------------------------------------------------------------------------


class _X11WindowBackend(_WindowBackend):
    name = "X11"
    detail = "X11 viewport API has not been probed."

    IsUnmapped = 0
    IsUnviewable = 1
    IsViewable = 2
    RevertToParent = 2
    CurrentTime = 0

    class XWindowAttributes(ctypes.Structure):
        _fields_ = [
            ("x", ctypes.c_int),
            ("y", ctypes.c_int),
            ("width", ctypes.c_int),
            ("height", ctypes.c_int),
            ("border_width", ctypes.c_int),
            ("depth", ctypes.c_int),
            ("visual", ctypes.c_void_p),
            ("root", ctypes.c_ulong),
            ("class_", ctypes.c_int),
            ("bit_gravity", ctypes.c_int),
            ("win_gravity", ctypes.c_int),
            ("backing_store", ctypes.c_int),
            ("backing_planes", ctypes.c_ulong),
            ("backing_pixel", ctypes.c_ulong),
            ("save_under", ctypes.c_int),
            ("colormap", ctypes.c_ulong),
            ("map_installed", ctypes.c_int),
            ("map_state", ctypes.c_int),
            ("all_event_masks", ctypes.c_long),
            ("your_event_mask", ctypes.c_long),
            ("do_not_propagate_mask", ctypes.c_long),
            ("override_redirect", ctypes.c_int),
            ("screen", ctypes.c_void_p),
        ]

    def __init__(self):
        super().__init__()
        self._x11 = None
        self._display = None
        self._probed = False

    def probe(self):
        if self._probed:
            return bool(self.hide_supported)
        self._probed = True
        if not os.environ.get("DISPLAY"):
            self.detail = (
                "No X11 DISPLAY detected. Wayland-only sessions cannot currently "
                "hide/restore the Dear PyGui viewport through the X11 adapter."
            )
            return False
        try:
            library = ctypes.util.find_library("X11")
            if not library:
                raise RuntimeError("libX11 was not found")
            x11 = ctypes.CDLL(library)
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            x11.XCloseDisplay.restype = ctypes.c_int
            x11.XUnmapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            x11.XUnmapWindow.restype = ctypes.c_int
            x11.XMapRaised.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            x11.XMapRaised.restype = ctypes.c_int
            x11.XSetInputFocus.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_int,
                ctypes.c_ulong,
            ]
            x11.XSetInputFocus.restype = ctypes.c_int
            x11.XGetWindowAttributes.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.POINTER(self.XWindowAttributes),
            ]
            x11.XGetWindowAttributes.restype = ctypes.c_int
            x11.XFlush.argtypes = [ctypes.c_void_p]
            x11.XFlush.restype = ctypes.c_int
            display = x11.XOpenDisplay(None)
            if not display:
                raise RuntimeError("XOpenDisplay returned NULL")
            self._x11 = x11
            self._display = display
            self.hide_supported = True
            self.activation_supported = True
            self.minimize_detection_supported = True
            self.detail = "X11 viewport control available."
            return True
        except Exception as exc:
            self.detail = f"X11 viewport control unavailable: {type(exc).__name__}: {exc}"
            return False

    def _ready(self):
        return bool(self.handle and self.probe() and self._x11 and self._display)

    def hide(self) -> bool:
        if not self._ready():
            return False
        try:
            self._x11.XUnmapWindow(self._display, ctypes.c_ulong(self.handle))
            self._x11.XFlush(self._display)
            return True
        except Exception as exc:
            self.detail = f"X11 hide failed: {type(exc).__name__}: {exc}"
            return False

    def show_and_activate(self) -> bool:
        if not self._ready():
            return False
        try:
            window = ctypes.c_ulong(self.handle)
            self._x11.XMapRaised(self._display, window)
            self._x11.XSetInputFocus(
                self._display,
                window,
                self.RevertToParent,
                self.CurrentTime,
            )
            self._x11.XFlush(self._display)
            return True
        except Exception as exc:
            self.detail = f"X11 restore/focus failed: {type(exc).__name__}: {exc}"
            return False

    def is_minimized(self) -> bool:
        if not self._ready():
            return False
        try:
            attrs = self.XWindowAttributes()
            result = self._x11.XGetWindowAttributes(
                self._display,
                ctypes.c_ulong(self.handle),
                ctypes.byref(attrs),
            )
            return bool(result and attrs.map_state != self.IsViewable)
        except Exception:
            return False

    def __del__(self):
        try:
            if self._x11 is not None and self._display:
                self._x11.XCloseDisplay(self._display)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# macOS AppKit viewport control
# ---------------------------------------------------------------------------


class _MacOSWindowBackend(_WindowBackend):
    name = "AppKit"
    detail = "AppKit has not been probed."

    def __init__(self):
        super().__init__()
        self._AppKit = None
        self._app = None
        self._probed = False

    def probe(self):
        if self._probed:
            return bool(self.hide_supported)
        self._probed = True
        try:
            import AppKit

            self._AppKit = AppKit
            self._app = AppKit.NSApplication.sharedApplication()
            self.hide_supported = True
            self.activation_supported = True
            self.minimize_detection_supported = True
            self.detail = "AppKit window/status-item integration available."
            return True
        except Exception as exc:
            self.detail = (
                f"AppKit unavailable: {type(exc).__name__}: {exc}. "
                "Install the macOS desktop requirements to enable tray window control."
            )
            return False

    def _windows(self):
        if not self.probe() or self._app is None:
            return []
        try:
            return list(self._app.windows())
        except Exception:
            return []

    @staticmethod
    def _salix_window(window) -> bool:
        try:
            title = str(window.title() or "")
        except Exception:
            title = ""
        return "SalixTorrent" in title or "Salix_T" in title

    def _target_windows(self):
        windows = self._windows()
        selected = [window for window in windows if self._salix_window(window)]
        return selected or windows[:1]

    def hide(self) -> bool:
        targets = self._target_windows()
        if not targets:
            return False
        try:
            for window in targets:
                window.orderOut_(None)
            return True
        except Exception as exc:
            self.detail = f"AppKit hide failed: {type(exc).__name__}: {exc}"
            return False

    def show_and_activate(self) -> bool:
        targets = self._target_windows()
        if not targets:
            return False
        try:
            for window in targets:
                try:
                    if window.isMiniaturized():
                        window.deminiaturize_(None)
                except Exception:
                    pass
                window.makeKeyAndOrderFront_(None)
            option = getattr(
                self._AppKit,
                "NSApplicationActivateIgnoringOtherApps",
                1 << 1,
            )
            self._app.activateWithOptions_(option)
            return True
        except Exception as exc:
            self.detail = f"AppKit restore/focus failed: {type(exc).__name__}: {exc}"
            return False

    def is_minimized(self) -> bool:
        targets = self._target_windows()
        if not targets:
            return False
        try:
            return all(bool(window.isMiniaturized()) for window in targets)
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Selection and notification helpers
# ---------------------------------------------------------------------------


def _is_bsd_platform() -> bool:
    value = sys.platform.lower()
    return value.startswith(("freebsd", "openbsd", "netbsd", "dragonfly"))


def _make_tray_backend(actions: "queue.Queue[str]") -> _TrayBackend:
    if os.name == "nt":
        return _WindowsTrayBackend(actions)
    if sys.platform == "darwin" or sys.platform.startswith("linux") or _is_bsd_platform():
        return _PystrayTrayBackend(actions)
    return _TrayBackend(actions)


def _make_window_backend() -> _WindowBackend:
    if os.name == "nt":
        return _WindowsWindowBackend()
    if sys.platform == "darwin":
        return _MacOSWindowBackend()
    if sys.platform.startswith("linux") or _is_bsd_platform():
        return _X11WindowBackend()
    return _WindowBackend()


def _fallback_notifications_supported() -> bool:
    if sys.platform == "darwin":
        return bool(shutil.which("osascript"))
    if sys.platform.startswith("linux") or _is_bsd_platform():
        return bool(shutil.which("notify-send"))
    return False


def _fallback_notify(title: str, message: str) -> bool:
    try:
        if sys.platform == "darwin" and shutil.which("osascript"):
            safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
            safe_message = message.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    f'display notification "{safe_message}" with title "{safe_title}"',
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        if (sys.platform.startswith("linux") or _is_bsd_platform()) and shutil.which(
            "notify-send"
        ):
            subprocess.Popen(
                ["notify-send", title, message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
    except Exception:
        pass
    return False
