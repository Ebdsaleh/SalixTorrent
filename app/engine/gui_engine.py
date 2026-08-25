# app/engine/gui_engine.py

from typing import Optional
import os
import sys
import time
import traceback
from pathlib import Path

import dearpygui.dearpygui as dpg
from app.engine.scene_manager import SceneManager
from app.engine.desktop_integration import DesktopIntegration


class GuiEngine:
    _instance: Optional["GuiEngine"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GuiEngine, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        dpg.create_context()

        # Dear PyGui normally executes callbacks on an internal worker thread.
        # SalixTorrent callbacks manipulate the same widget tree that our main
        # render/update loop touches, so on modern Dear PyGui we serialize all
        # callbacks onto the main UI thread. DPG 2.2 also fixed handler-registry
        # support in manual callback mode; older versions keep their default
        # callback handling so right-click handlers are not accidentally lost.
        self._manual_callbacks = False
        try:
            raw_version = str(dpg.get_dearpygui_version() or "0")
            numeric = []
            for part in raw_version.split("."):
                digits = "".join(ch for ch in part if ch.isdigit())
                numeric.append(int(digits or 0))
                if len(numeric) == 3:
                    break
            while len(numeric) < 3:
                numeric.append(0)
            version_tuple = tuple(numeric[:3])
        except Exception:
            raw_version = "unknown"
            version_tuple = (0, 0, 0)

        if version_tuple >= (2, 2, 0):
            dpg.configure_app(manual_callback_management=True)
            self._manual_callbacks = True
        else:
            print(
                f"[Salix_T Notice] Dear PyGui {raw_version}: main-thread callback "
                "serialization requires Dear PyGui 2.2.0 or newer. UI telemetry "
                "coalescing remains enabled; upgrading Dear PyGui is recommended."
            )

        dpg.create_viewport(title="SalixTorrent (Salix_T)", width=1100, height=700)
        dpg.setup_dearpygui()

        self.scene_mgr = SceneManager.get_instance()
        self.scene_mgr.engine = self
        self._last_ui_error_signature = None
        self._last_ui_error_at = 0.0
        self.desktop = DesktopIntegration.get_instance()
        self._last_minimize_check = 0.0
        self._initialized = True

    @classmethod
    def get_instance(cls) -> "GuiEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def switch_scene(self, scene_name: str, **kwargs):
        self.scene_mgr.switch_to(scene_name, **kwargs)

    @staticmethod
    def _ui_error_log_path() -> Path:
        if os.name == "nt":
            base = os.environ.get("LOCALAPPDATA")
            root = Path(base) / "SalixTorrent" if base else Path.home() / "AppData" / "Local" / "SalixTorrent"
        elif sys.platform == "darwin":
            root = Path.home() / "Library" / "Application Support" / "SalixTorrent"
        else:
            base = os.environ.get("XDG_STATE_HOME")
            root = Path(base) / "SalixTorrent" if base else Path.home() / ".local" / "state" / "SalixTorrent"
        return root / "ui_errors.log"

    def _report_ui_exception(self, context: str, exc: BaseException):
        now = time.monotonic()
        signature = (context, type(exc).__name__, str(exc))
        # A persistent bad widget should not write the same traceback 60 times
        # per second. Keep one report every five seconds for a repeated error.
        if signature == self._last_ui_error_signature and now - self._last_ui_error_at < 5.0:
            return

        self._last_ui_error_signature = signature
        self._last_ui_error_at = now
        rendered = traceback.format_exc()
        print(f"[Salix_T UI Error] {context}: {exc}\n{rendered}")

        try:
            path = self._ui_error_log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"\n[{stamp}] {context}: {type(exc).__name__}: {exc}\n")
                handle.write(rendered)
        except OSError:
            pass

    def run(self):
        """Starts the native Dear PyGui render loop."""
        from app.logic.torrent_manager import TorrentManager

        manager = TorrentManager.get_instance()
        self.desktop.configure(manager.get_app_settings())
        dpg.show_viewport()

        # Dear PyGui 2.x exposes the native platform handle. On older builds the
        # tray still exists, but automatic minimize-to-tray is simply skipped.
        try:
            platform_handle = dpg.get_viewport_platform_handle()
        except Exception:
            platform_handle = 0
        self.desktop.set_viewport_handle(platform_handle)

        try:
            while dpg.is_dearpygui_running():
                # Tray callbacks are produced on a tiny native message thread,
                # then consumed here so all Dear PyGui/window operations remain
                # serialized onto the application's main UI thread.
                for action in self.desktop.poll_actions():
                    try:
                        if action == "restore":
                            self.desktop.show_viewport()
                        elif action == "pause_all":
                            manager.pause_all()
                        elif action == "resume_all":
                            manager.resume_all()
                        elif action == "exit":
                            dpg.stop_dearpygui()
                    except Exception as exc:
                        self._report_ui_exception(f"desktop action {action}", exc)

                now = time.monotonic()
                if (
                    now - self._last_minimize_check >= 0.20
                    and self.desktop.should_minimize_to_tray()
                ):
                    self._last_minimize_check = now
                    if self.desktop.is_native_viewport_minimized():
                        self.desktop.hide_viewport()

                # Run queued callbacks on this same main thread before touching
                # scene widgets when manual callback management is available.
                if self._manual_callbacks:
                    try:
                        jobs = dpg.get_callback_queue()
                    except Exception as exc:
                        jobs = None
                        self._report_ui_exception("DearPyGui callback queue", exc)

                    if jobs:
                        for job in jobs:
                            try:
                                dpg.run_callbacks([job])
                            except Exception as exc:
                                callback_name = (
                                    getattr(job[0], "__name__", repr(job[0]))
                                    if job else "unknown"
                                )
                                self._report_ui_exception(
                                    f"DearPyGui callback {callback_name}", exc
                                )

                if self.scene_mgr.current_scene:
                    active_scene = self.scene_mgr.scenes.get(self.scene_mgr.current_scene)
                    if active_scene and hasattr(active_scene, "update"):
                        try:
                            active_scene.update(0.016)
                        except Exception as exc:
                            self._report_ui_exception(
                                f"{self.scene_mgr.current_scene}.update", exc
                            )

                try:
                    dpg.render_dearpygui_frame()
                except Exception as exc:
                    self._report_ui_exception("DearPyGui render", exc)
        finally:
            self.desktop.stop()
            dpg.destroy_context()
