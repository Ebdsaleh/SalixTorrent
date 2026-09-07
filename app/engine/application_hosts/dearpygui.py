"""Minimal Dear PyGui application host for backend-neutral component trees."""

from __future__ import annotations

import time

from app.engine.presentation_backends import create_dearpygui_backend
from app.framework.components import clear_default_renderer, set_default_renderer
from app.framework.components.profile import ComponentLayoutProfile
from app.framework.responsive import LayoutCoordinator
from app.runtime.application import ApplicationSpec
from app.runtime.lifecycle import ApplicationRuntime
from app.runtime.scenes import SceneRegistry


class DearPyGuiApplicationHost:
    """Own a plain Dear PyGui viewport without SalixTorrent-specific services."""

    def __init__(
        self,
        spec: ApplicationSpec,
        *,
        runtime: ApplicationRuntime | None = None,
        component_profile: ComponentLayoutProfile | None = None,
    ):
        if not isinstance(spec, ApplicationSpec):
            raise TypeError("DearPyGuiApplicationHost requires an ApplicationSpec")
        try:
            import dearpygui.dearpygui as dpg
        except ModuleNotFoundError as exc:
            raise RuntimeError("Dear PyGui is not installed") from exc

        self.spec = spec
        self._dpg = dpg
        self.runtime = runtime or ApplicationRuntime()
        self.presentation = create_dearpygui_backend(component_profile=component_profile)
        self.component_renderer = self.presentation.component_renderer
        self.layout = LayoutCoordinator(self.presentation.layout_host)
        self.scenes = SceneRegistry(self.presentation.scene_host)
        self.root = "ecosystem_application_root"
        self._closed = False

        dpg.create_context()
        dpg.create_viewport(
            title=self.spec.title,
            width=self.spec.width,
            height=self.spec.height,
        )
        try:
            dpg.set_viewport_min_width(self.spec.minimum_width)
            dpg.set_viewport_min_height(self.spec.minimum_height)
        except Exception:
            pass
        dpg.setup_dearpygui()
        dpg.add_window(tag=self.root, no_title_bar=True, no_resize=True)
        dpg.set_primary_window(self.root, True)
        set_default_renderer(self.component_renderer)
        self.layout.install_viewport_callback()

    def build(self, component):
        build = getattr(component, "build", None)
        if not callable(build):
            raise TypeError("application content must provide build(renderer=..., parent=...)")
        return build(renderer=self.component_renderer, parent=self.root)

    def request_stop(self) -> None:
        try:
            self._dpg.stop_dearpygui()
        except Exception:
            pass

    def run(self) -> int:
        dpg = self._dpg
        dpg.show_viewport()
        self.layout.refresh_all()
        last_frame_at = time.monotonic()
        try:
            self.runtime.start()
            while dpg.is_dearpygui_running():
                now = time.monotonic()
                delta_seconds = max(0.0, min(1.0, now - last_frame_at))
                last_frame_at = now
                self.runtime.update(delta_seconds)
                dpg.render_dearpygui_frame()
            return 0
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.runtime.stop()
        clear_default_renderer(self.component_renderer)
        try:
            self._dpg.destroy_context()
        except Exception:
            pass
