"""Backend-neutral blank-application proof for the extracted Salix ecosystem.

This example is intentionally small and product-neutral.  The same component
and realtime-graph definition runs through Dear PyGui or Tkinter; headless mode
uses the same application runtime without importing a GUI toolkit.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys
import time

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from app.engine.application_hosts.headless import HeadlessApplicationHost
from app.framework.components import (
    Button,
    CheckBox,
    ComboBox,
    ControlColumn,
    ControlLayout,
    FILL,
    Label,
    ProgressBar,
    TextInput,
)
from app.framework.telemetry import RollingTelemetry
from app.framework.visualization import PlotFrame, PlotSeriesData, PlotSeriesSpec, RealtimeGraph
from app.runtime.application import ApplicationSpec
from app.runtime.lifecycle import ApplicationRuntime, CallbackService
from app.runtime.presentation import PresentationCapability


class DemoView:
    def __init__(self, host):
        self.host = host
        self.renderer = host.presentation.component_renderer
        self.status = Label("Ready")
        self.name = TextInput(default_value="World", layout=ControlLayout(width=220))
        self.mode = ComboBox(("Desktop", "Tool", "Dashboard"), default_value="Desktop")
        self.enabled = CheckBox("Enable greeting", default_value=True)
        self.progress = ProgressBar(default_value=0.0, overlay="0%", layout=ControlLayout(width=FILL))
        self.plot_container = ControlColumn(layout=ControlLayout(width=FILL, height=220))
        self.root = ControlColumn(
            (
                Label("Blank Ecosystem Application"),
                Label(f"Presentation backend: {host.presentation.name}"),
                self.name,
                self.mode,
                self.enabled,
                Button("Say hello", callback=self._on_greet),
                self.progress,
                self.status,
                self.plot_container,
            ),
            layout=ControlLayout(width=FILL),
        )
        self.telemetry = RollingTelemetry(
            ("activity",),
            history_seconds=12.0,
            sample_interval_seconds=0.1,
        )
        self.graph = None
        self.elapsed = 0.0
        self._last_sample = -1.0

    def build(self):
        self.host.build(self.root)
        if self.host.presentation.supports(PresentationCapability.REALTIME_PLOTS):
            self.graph = RealtimeGraph(
                self.host.presentation.plot_host,
                (PlotSeriesSpec("activity", "Activity"),),
            )
            self.graph.build(
                parent=self.plot_container.require_item(),
                x_label="Seconds",
                y_label="Value",
                width=-1,
                height=200,
            )

    def _on_greet(self, _event):
        if not bool(self.enabled.get_value()):
            self.status.set_text("Greeting disabled")
            return
        name = str(self.name.get_value() or "World").strip() or "World"
        mode = str(self.mode.get_value() or "Desktop")
        self.status.set_text(f"Hello, {name}!  Mode: {mode}")

    def update(self, delta_seconds: float):
        self.elapsed += max(0.0, float(delta_seconds))
        phase = self.elapsed % 5.0
        progress = phase / 5.0
        self.progress.set_value(progress)
        self.progress.set_overlay(f"{round(progress * 100)}%")

        if self.elapsed - self._last_sample < 0.1:
            return
        self._last_sample = self.elapsed
        now = time.monotonic()
        value = 50.0 + 40.0 * math.sin(self.elapsed * 1.6)
        self.telemetry.record({"activity": value}, timestamp=now)
        if self.graph is None or not self.graph.exists():
            return
        window = self.telemetry.snapshot(now=now, window_seconds=12.0)
        rows = window.aged_rows()
        self.graph.render(
            PlotFrame(
                x_limits=(-12.0, 0.0),
                y_limits=(0.0, 100.0),
                y_label="Value",
                series=(
                    PlotSeriesData(
                        "activity",
                        (-age for age, _values in rows),
                        (values[0] for _age, values in rows),
                    ),
                ),
            )
        )


def _make_runtime() -> ApplicationRuntime:
    return ApplicationRuntime()


def _run_graphical(backend_name: str, *, smoke_seconds: float = 0.0) -> int:
    spec = ApplicationSpec(
        "EcosystemBlankApp",
        title="Blank Ecosystem Application",
        width=820,
        height=620,
        minimum_width=560,
        minimum_height=420,
    )
    runtime = _make_runtime()
    if backend_name == "dearpygui":
        from app.engine.application_hosts.dearpygui import DearPyGuiApplicationHost

        host = DearPyGuiApplicationHost(spec, runtime=runtime)
    else:
        from app.engine.application_hosts.tkinter import TkinterApplicationHost

        host = TkinterApplicationHost(spec, runtime=runtime)
    view = DemoView(host)
    view.build()
    runtime.services.register("demo view", CallbackService(on_update=view.update))
    if smoke_seconds > 0.0:
        elapsed = {"value": 0.0}

        def _smoke_stop(delta_seconds: float):
            elapsed["value"] += max(0.0, float(delta_seconds))
            if elapsed["value"] >= smoke_seconds:
                host.request_stop()

        runtime.services.register("smoke stop", CallbackService(on_update=_smoke_stop))
    return host.run()


def _run_headless() -> int:
    spec = ApplicationSpec("EcosystemBlankApp", title="Blank Ecosystem Application")
    runtime = _make_runtime()
    samples = []
    runtime.services.register(
        "headless proof",
        CallbackService(on_update=lambda delta: samples.append(float(delta))),
    )
    result = HeadlessApplicationHost(spec, runtime=runtime, frames=3).run()
    print(f"Headless runtime OK ({len(samples)} updates)")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ui-backend",
        choices=("dearpygui", "tkinter", "headless"),
        default="dearpygui",
        help="presentation backend used by the blank application proof",
    )
    parser.add_argument(
        "--smoke-seconds",
        type=float,
        default=0.0,
        help="automatically close a graphical smoke run after this many seconds",
    )
    args = parser.parse_args(argv)
    if args.ui_backend == "headless":
        return _run_headless()
    return _run_graphical(args.ui_backend, smoke_seconds=max(0.0, args.smoke_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
