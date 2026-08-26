# app/engine/desktop_integration.py

from __future__ import annotations

import os
import queue
import threading
from typing import Optional


class DesktopIntegration:
    """Native-desktop bridge with a dependency-free Windows tray backend.

    Other platforms deliberately degrade to no-op behaviour for now. The
    public API stays platform-neutral so Linux/BSD/macOS tray backends can be
    added later without leaking platform code into the torrent/UI layers.
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
        self._settings = {}
        self._actions: "queue.Queue[str]" = queue.Queue()
        self._backend = _WindowsTrayBackend(self._actions) if os.name == "nt" else None
        self._viewport_handle: int = 0

    @classmethod
    def get_instance(cls) -> "DesktopIntegration":
        return cls()

    @property
    def supported(self) -> bool:
        return self._backend is not None

    def configure(self, settings: dict):
        self._settings = dict(settings or {})
        if not self._backend:
            return
        wanted = bool(
            self._settings.get("system_tray_enabled", True)
            or self._settings.get("native_notifications", True)
            or self._settings.get("minimize_to_tray", True)
        )
        if wanted:
            self._backend.start()
        else:
            self._backend.stop()

    def set_viewport_handle(self, handle: object):
        try:
            self._viewport_handle = int(handle or 0)
        except (TypeError, ValueError, OverflowError):
            self._viewport_handle = 0

    def poll_actions(self):
        actions = []
        while True:
            try:
                actions.append(self._actions.get_nowait())
            except queue.Empty:
                break
        return actions

    def notify(self, title: str, message: str):
        if not self._backend or not self._settings.get("native_notifications", True):
            return False
        self._backend.start()
        return self._backend.notify(str(title), str(message))

    def should_minimize_to_tray(self) -> bool:
        return bool(
            self._backend
            and self._settings.get("system_tray_enabled", True)
            and self._settings.get("minimize_to_tray", True)
        )

    def is_native_viewport_minimized(self) -> bool:
        if not self._backend or not self._viewport_handle:
            return False
        return self._backend.is_minimized(self._viewport_handle)

    def hide_viewport(self):
        if self._backend and self._viewport_handle:
            self._backend.hide_window(self._viewport_handle)

    def show_viewport(self):
        if self._backend and self._viewport_handle:
            self._backend.show_window(self._viewport_handle)

    def stop(self):
        if self._backend:
            self._backend.stop()


class _WindowsTrayBackend:
    """Small Win32 notification-area backend.

    Win32 handles, WPARAM, LPARAM and LRESULT are pointer-sized on 64-bit
    Windows. ctypes assumes ``c_int`` for undeclared function arguments and
    return values, which truncates those values and can raise errors such as:

        ctypes.ArgumentError: OverflowError: int too long to convert

    Every Win32 function used by this backend therefore receives an explicit
    ctypes signature before it is called.
    """

    WM_TRAYICON = 0x8000 + 51
    WM_COMMAND = 0x0111
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

    SW_HIDE = 0
    SW_RESTORE = 9
    SW_SHOW = 5

    CMD_OPEN = 1001
    CMD_PAUSE_ALL = 1002
    CMD_RESUME_ALL = 1003
    CMD_EXIT = 1004

    def __init__(self, actions: "queue.Queue[str]"):
        self.actions = actions
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stop_requested = threading.Event()
        self._hwnd = 0
        self._nid = None
        self._wndproc_ref = None
        self._lock = threading.Lock()

    @staticmethod
    def _configure_basic_user32():
        """Return user32 with 64-bit-safe signatures for viewport operations."""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.PostMessageW.restype = wintypes.BOOL
        return user32, wintypes

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_requested.clear()
            self._ready.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="SalixTray",
                daemon=True,
            )
            self._thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self):
        thread = self._thread
        if not thread or not thread.is_alive():
            return
        self._stop_requested.set()
        try:
            user32, wintypes = self._configure_basic_user32()
            if self._hwnd:
                user32.PostMessageW(
                    wintypes.HWND(self._hwnd),
                    self.WM_CLOSE,
                    wintypes.WPARAM(0),
                    wintypes.LPARAM(0),
                )
        except Exception:
            pass
        thread.join(timeout=1.5)

    @classmethod
    def is_minimized(cls, hwnd: int) -> bool:
        try:
            user32, wintypes = cls._configure_basic_user32()
            return bool(user32.IsIconic(wintypes.HWND(int(hwnd))))
        except Exception:
            return False

    @classmethod
    def hide_window(cls, hwnd: int):
        try:
            user32, wintypes = cls._configure_basic_user32()
            user32.ShowWindow(wintypes.HWND(int(hwnd)), cls.SW_HIDE)
        except Exception:
            pass

    @classmethod
    def show_window(cls, hwnd: int):
        try:
            user32, wintypes = cls._configure_basic_user32()
            native = wintypes.HWND(int(hwnd))
            user32.ShowWindow(native, cls.SW_RESTORE)
            user32.ShowWindow(native, cls.SW_SHOW)
            user32.SetForegroundWindow(native)
        except Exception:
            pass

    def notify(self, title: str, message: str) -> bool:
        self._ready.wait(timeout=2.0)
        try:
            import ctypes

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
            return bool(
                shell32.Shell_NotifyIconW(
                    self.NIM_MODIFY,
                    ctypes.byref(nid),
                )
            )
        except Exception:
            return False

    def _run(self):
        try:
            import ctypes
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

            # ctypes defaults to 32-bit ``c_int`` conversions when function
            # prototypes are omitted. Explicit prototypes are essential on
            # 64-bit Windows because HWND/WPARAM/LPARAM/LRESULT are pointer-sized.
            user32.DefWindowProcW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.DefWindowProcW.restype = LRESULT
            user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
            user32.RegisterClassW.restype = wintypes.ATOM
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
            user32.AppendMenuW.argtypes = [HMENU, wintypes.UINT, UINT_PTR, wintypes.LPCWSTR]
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
            user32.PostMessageW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.PostMessageW.restype = wintypes.BOOL

            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = HMODULE
            shell32.Shell_NotifyIconW.argtypes = [
                wintypes.DWORD,
                ctypes.POINTER(NOTIFYICONDATAW),
            ]
            shell32.Shell_NotifyIconW.restype = wintypes.BOOL

            def make_int_resource(value: int):
                # MAKEINTRESOURCEW stores an integer resource id in the low
                # pointer bits; this is intentional Win32 API behaviour.
                return ctypes.cast(ctypes.c_void_p(int(value)), wintypes.LPCWSTR)

            @WNDPROC
            def wndproc(hwnd, msg, wparam, lparam):
                try:
                    if msg == self.WM_TRAYICON:
                        event = int(lparam) & 0xFFFF
                        if event == self.WM_LBUTTONDBLCLK:
                            self.actions.put("restore")
                            return 0
                        if event == self.WM_RBUTTONUP:
                            menu = user32.CreatePopupMenu()
                            if menu:
                                user32.AppendMenuW(menu, self.MF_STRING, self.CMD_OPEN, "Open SalixTorrent")
                                user32.AppendMenuW(menu, self.MF_SEPARATOR, 0, None)
                                user32.AppendMenuW(menu, self.MF_STRING, self.CMD_PAUSE_ALL, "Pause All")
                                user32.AppendMenuW(menu, self.MF_STRING, self.CMD_RESUME_ALL, "Resume All")
                                user32.AppendMenuW(menu, self.MF_SEPARATOR, 0, None)
                                user32.AppendMenuW(menu, self.MF_STRING, self.CMD_EXIT, "Exit")
                                point = wintypes.POINT()
                                user32.GetCursorPos(ctypes.byref(point))
                                user32.SetForegroundWindow(hwnd)
                                command = user32.TrackPopupMenu(
                                    menu,
                                    self.TPM_RIGHTBUTTON | self.TPM_RETURNCMD,
                                    point.x,
                                    point.y,
                                    0,
                                    hwnd,
                                    None,
                                )
                                user32.DestroyMenu(menu)
                                if command == self.CMD_OPEN:
                                    self.actions.put("restore")
                                elif command == self.CMD_PAUSE_ALL:
                                    self.actions.put("pause_all")
                                elif command == self.CMD_RESUME_ALL:
                                    self.actions.put("resume_all")
                                elif command == self.CMD_EXIT:
                                    self.actions.put("exit")
                            return 0
                    if msg == self.WM_CLOSE:
                        user32.DestroyWindow(hwnd)
                        return 0
                    if msg == self.WM_DESTROY:
                        user32.PostQuitMessage(0)
                        return 0
                    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
                except Exception:
                    # A ctypes callback must never let a Python exception escape
                    # back into user32. Falling back to DefWindowProc keeps the
                    # hidden tray window's message pump alive.
                    try:
                        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
                    except Exception:
                        return 0

            self._wndproc_ref = wndproc
            class_name = "SalixTorrentTrayWindow"
            hinstance = kernel32.GetModuleHandleW(None)
            wc = WNDCLASSW()
            wc.lpfnWndProc = wndproc
            wc.hInstance = hinstance
            wc.lpszClassName = class_name
            user32.RegisterClassW(ctypes.byref(wc))

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
            self._hwnd = int(hwnd or 0)

            icon = user32.LoadIconW(None, make_int_resource(32512))
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = hwnd
            nid.uID = 1
            nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
            nid.uCallbackMessage = self.WM_TRAYICON
            nid.hIcon = icon
            nid.szTip = "SalixTorrent (Salix_T)"
            self._nid = nid
            shell32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(nid))
            self._ready.set()

            msg = wintypes.MSG()
            while not self._stop_requested.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            try:
                shell32.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(nid))
            except Exception:
                pass
            if hwnd:
                try:
                    user32.DestroyWindow(hwnd)
                except Exception:
                    pass
        except Exception:
            self._ready.set()
        finally:
            self._hwnd = 0
            self._nid = None
            self._ready.set()
