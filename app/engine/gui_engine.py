# app/engine/gui_engine.py

from typing import Optional
import os
import time

import dearpygui.dearpygui as dpg
from app.engine.scene_manager import SceneManager
from app.engine.scene_hosts import DearPyGuiSceneHost
from app.engine.desktop_integration import (
    DesktopIntegration,
    TRAY_ACTION_CLOSE_REQUESTED,
    TRAY_ACTION_MINIMIZE_REQUESTED,
    TRAY_ACTION_EXIT,
    TRAY_ACTION_PAUSE_ALL,
    TRAY_ACTION_RESTORE,
    TRAY_ACTION_RESUME_ALL,
)
from app.engine.ui_typography import UiTypography
from app.engine.responsive_layout import ResponsiveLayout
from app.engine.runtime_paths import state_directory
from app.runtime.diagnostics import ExceptionReporter
from app.runtime.lifecycle import ApplicationRuntime, CallbackService
from app.framework.components import clear_default_renderer, set_default_renderer
from app.engine.component_renderers import DearPyGuiRenderer
from app.engine.ui_component_profile import SALIXTORRENT_COMPONENT_PROFILE


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

        # Register scalable system-font sizes before Dear PyGui builds its font
        # atlas. The selected size is applied after setup and before any
        # SalixTorrent view widgets are constructed.
        self.typography = UiTypography.get_instance()
        self.typography.register_fonts()

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

        # Windows close/minimize requests are intercepted at the native HWND
        # after the viewport is shown. Other platforms retain Dear PyGui's
        # exit-callback fallback.
        self._native_window_events = os.name == "nt"
        self._intercept_viewport_close = bool(
            not self._native_window_events and hasattr(dpg, "set_exit_callback")
        )
        dpg.create_viewport(
            title="SalixTorrent (Salix_T)",
            width=1100,
            height=700,
            disable_close=self._intercept_viewport_close,
        )
        # Native desktop applications enforce a sensible minimum rather than
        # allowing their controls to collapse into unusable geometry.
        try:
            dpg.set_viewport_min_width(1000)
            dpg.set_viewport_min_height(620)
        except Exception:
            pass
        dpg.setup_dearpygui()

        # Select SalixTorrent's application-level component metrics once at the
        # composition root. Reusable components remain backend/application neutral;
        # views refer only to semantic profile keys, while explicit per-instance
        # layout overrides remain available for exceptional cases.
        self.component_renderer = DearPyGuiRenderer(
            component_profile=SALIXTORRENT_COMPONENT_PROFILE
        )
        set_default_renderer(self.component_renderer)

        if self._intercept_viewport_close:
            try:
                dpg.set_exit_callback(self._on_viewport_close_requested)
            except Exception:
                self._intercept_viewport_close = False
                try:
                    dpg.configure_viewport(0, disable_close=False)
                except Exception:
                    pass

        self.layout = ResponsiveLayout.get_instance()
        self.layout.install_viewport_callback()

        # TorrentManager is already created by main.py before the viewport. A
        # local import avoids turning the engine/settings relationship into a
        # module-level circular dependency.
        try:
            from app.logic.torrent_manager import TorrentManager

            ui_font_size = TorrentManager.get_instance().get_app_settings().get(
                "ui_font_size", 15
            )
        except Exception:
            ui_font_size = 15
        self.typography.apply_font_size(ui_font_size)

        self.scene_mgr = SceneManager.get_instance()
        self.scene_mgr.engine = self
        self.scene_mgr.set_host(DearPyGuiSceneHost())

        self._ui_error_reporter = ExceptionReporter(
            log_path=state_directory() / "ui_errors.log",
            prefix="[Salix_T UI Error]",
            throttle_seconds=5.0,
        )
        self.runtime = ApplicationRuntime(error_handler=self._report_runtime_exception)
        self.runtime.services.register(
            "application menu update",
            CallbackService(on_update=self._update_application_menu),
        )
        self.runtime.services.register(
            "active scene update",
            CallbackService(on_update=self._update_active_scene),
        )

        self.desktop = DesktopIntegration.get_instance()
        self._last_minimize_check = 0.0
        self.application_menu = None
        self._initialized = True

    @classmethod
    def get_instance(cls) -> "GuiEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def switch_scene(self, scene_name: str, **kwargs):
        self.scene_mgr.switch_to(scene_name, **kwargs)
        # Hidden scene containers do not receive useful resize events. Refresh
        # layout once when a scene becomes visible rather than polling it.
        try:
            self.layout.refresh_all()
        except Exception:
            pass
        if self.application_menu is not None:
            try:
                self.application_menu.update(force=True)
            except Exception as exc:
                self._report_ui_exception("application menu scene update", exc)

    def set_application_menu(self, application_menu):
        """Register the viewport-level menu for lightweight state refreshes."""
        self.application_menu = application_menu

    def ui_error_log_path(self):
        """Return the append-only UI exception log used by diagnostics."""
        return self._ui_error_reporter.log_path

    def _report_ui_exception(self, context: str, exc: BaseException):
        self._ui_error_reporter.report(context, exc)

    def _report_runtime_exception(self, service_name: str, exc: BaseException):
        self._report_ui_exception(service_name, exc)

    def _update_application_menu(self, _delta_seconds: float):
        if self.application_menu is not None:
            self.application_menu.update()

    def _update_active_scene(self, delta_seconds: float):
        active_scene = self.scene_mgr.active_scene()
        update = getattr(active_scene, "update", None)
        if callable(update):
            update(delta_seconds)

    def _on_viewport_close_requested(self, sender=None, app_data=None, user_data=None):
        """Route the native close button through the main UI thread.

        ``disable_close`` keeps Dear PyGui alive long enough for this callback
        to decide whether closing should hide to a *live* tray or perform a
        real application shutdown. Tray -> Exit always bypasses this policy.
        """
        del sender, app_data, user_data
        self.desktop.queue_action(TRAY_ACTION_CLOSE_REQUESTED)

    def run(self):
        """Starts the native Dear PyGui render loop."""
        from app.logic.torrent_manager import TorrentManager

        manager = TorrentManager.get_instance()
        dpg.show_viewport()
        try:
            self.layout.refresh_all()
        except Exception:
            pass

        # A native-handle accessor is not part of Dear PyGui's documented
        # cross-platform API. Use it only when a build happens to expose one,
        # then let DesktopIntegration discover/bind the real native window when
        # it does not.
        try:
            getter = getattr(dpg, "get_viewport_platform_handle", None)
            platform_handle = getter() if callable(getter) else 0
        except Exception:
            platform_handle = 0
        self.desktop.set_viewport_handle(platform_handle)

        # Start the tray only after the viewport has been bound, so Windows tray
        # clicks already know which HWND they must restore and focus.
        self.desktop.configure(manager.get_app_settings())

        last_frame_at = time.monotonic()
        try:
            self.runtime.start()
            while dpg.is_dearpygui_running():
                # Tray callbacks are produced on a tiny native message thread,
                # then consumed here so all Dear PyGui/window operations remain
                # serialized onto the application's main UI thread.
                self.desktop.maintain()
                for action in self.desktop.poll_actions():
                    try:
                        if action == TRAY_ACTION_RESTORE:
                            self.desktop.show_viewport()
                        elif action == TRAY_ACTION_PAUSE_ALL:
                            manager.pause_all()
                        elif action == TRAY_ACTION_RESUME_ALL:
                            manager.resume_all()
                        elif action == TRAY_ACTION_MINIMIZE_REQUESTED:
                            if self.desktop.should_minimize_to_tray():
                                if not self.desktop.hide_viewport():
                                    self.desktop.minimize_viewport()
                            else:
                                self.desktop.minimize_viewport()
                        elif action == TRAY_ACTION_CLOSE_REQUESTED:
                            if self.desktop.should_close_to_tray():
                                if not self.desktop.hide_viewport():
                                    dpg.stop_dearpygui()
                            else:
                                dpg.stop_dearpygui()
                        elif action == TRAY_ACTION_EXIT:
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

                frame_at = time.monotonic()
                delta_seconds = max(0.0, min(1.0, frame_at - last_frame_at))
                last_frame_at = frame_at
                self.runtime.update(delta_seconds)

                try:
                    dpg.render_dearpygui_frame()
                except Exception as exc:
                    self._report_ui_exception("DearPyGui render", exc)
        finally:
            self.runtime.stop()
            self.desktop.stop()
            clear_default_renderer(self.component_renderer)
            dpg.destroy_context()


