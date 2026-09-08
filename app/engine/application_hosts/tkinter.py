"""Tkinter application host for backend-neutral component trees."""

from __future__ import annotations

import time

from app.engine.presentation_backends import create_tkinter_backend
from app.framework.components import clear_default_renderer, set_default_renderer
from app.framework.components.profile import ComponentLayoutProfile
from app.framework.responsive import LayoutCoordinator
from app.runtime.application import ApplicationSpec
from app.runtime.lifecycle import ApplicationRuntime
from app.runtime.scenes import SceneRegistry


class TkinterApplicationHost:
    """Own a Tk root, runtime tick loop and the Tkinter presentation bundle."""

    def __init__(
        self,
        spec: ApplicationSpec,
        *,
        runtime: ApplicationRuntime | None = None,
        component_profile: ComponentLayoutProfile | None = None,
        root=None,
    ):
        if not isinstance(spec, ApplicationSpec):
            raise TypeError("TkinterApplicationHost requires an ApplicationSpec")
        if root is None:
            try:
                import tkinter as tk

                root = tk.Tk()
            except Exception as exc:
                raise RuntimeError("Tkinter application host could not create a Tk root") from exc

        self.spec = spec
        self.root = root
        self.runtime = runtime or ApplicationRuntime()
        self.presentation = create_tkinter_backend(
            root,
            component_profile=component_profile,
        )
        self.component_renderer = self.presentation.component_renderer
        self.layout = LayoutCoordinator(self.presentation.layout_host)
        self.scenes = SceneRegistry(self.presentation.scene_host)
        self._stop_requested = False
        self._closed = False
        self._last_frame_at = time.monotonic()

        root.title(self.spec.title)
        root.geometry(f"{self.spec.width}x{self.spec.height}")
        root.minsize(self.spec.minimum_width, self.spec.minimum_height)
        root.protocol("WM_DELETE_WINDOW", self.request_stop)
        set_default_renderer(self.component_renderer)
        self.layout.install_viewport_callback()

    def build(self, component):
        build = getattr(component, "build", None)
        if not callable(build):
            raise TypeError("application content must provide build(renderer=..., parent=...)")
        return build(renderer=self.component_renderer, parent=None)

    def request_stop(self) -> None:
        if self._stop_requested:
            return
        self._stop_requested = True
        try:
            self.root.quit()
        except Exception:
            pass

    def _tick(self) -> None:
        if self._stop_requested:
            return
        now = time.monotonic()
        delta_seconds = max(0.0, min(1.0, now - self._last_frame_at))
        self._last_frame_at = now
        self.runtime.update(delta_seconds)
        try:
            self.root.after(self.spec.frame_interval_milliseconds, self._tick)
        except Exception:
            self.request_stop()

    def run(self) -> int:
        self._stop_requested = False
        self._last_frame_at = time.monotonic()
        try:
            self.runtime.start()
            self.layout.refresh_all()
            self.root.after(self.spec.frame_interval_milliseconds, self._tick)
            self.root.mainloop()
            return 0
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_requested = True
        self.runtime.stop()
        clear_default_renderer(self.component_renderer)
        try:
            self.component_renderer.close()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
