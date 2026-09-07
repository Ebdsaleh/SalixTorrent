"""Small headless application host for runtime-only projects and tests."""

from __future__ import annotations

from app.runtime.application import ApplicationSpec
from app.runtime.lifecycle import ApplicationRuntime
from app.runtime.presentation import HEADLESS_PRESENTATION


class HeadlessApplicationHost:
    def __init__(
        self,
        spec: ApplicationSpec,
        *,
        runtime: ApplicationRuntime | None = None,
        frames: int = 1,
    ):
        if not isinstance(spec, ApplicationSpec):
            raise TypeError("HeadlessApplicationHost requires an ApplicationSpec")
        self.spec = spec
        self.runtime = runtime or ApplicationRuntime()
        self.presentation = HEADLESS_PRESENTATION
        self.frames = max(1, int(frames))
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def build(self, _component):
        raise RuntimeError("headless application host does not provide GUI components")

    def run(self) -> int:
        self._stop_requested = False
        self.runtime.start()
        try:
            for _ in range(self.frames):
                if self._stop_requested:
                    break
                self.runtime.update(self.spec.frame_interval_seconds)
            return 0
        finally:
            self.runtime.stop()
