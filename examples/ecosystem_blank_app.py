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
    ControlGrid,
    ControlLayout,
    FILL,
    Label,
    ProgressBar,
    TextInput,
    PlacedComponent,
    PositionedPanel,
    positioned,
)
from app.framework.command_menu import CommandMenu
from app.framework.interactions import CommandSet, CommandSpec
from app.framework.live_data import (
    LiveTable,
    StateGrid,
    StateGridCell,
    StateGridFrame,
    TableCell,
    TableColumnSpec,
    TableFrame,
    TableRow,
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
        self.positioned_panel = PositionedPanel(
            (
                positioned(
                    Label("Local x/y"),
                    x=10,
                    y=8,
                ),
                positioned(
                    Button(
                        "Actions",
                        callback=lambda _event: self._show_demo_menu(),
                        layout=ControlLayout(width=100, height=28),
                    ),
                    x=135,
                    y=42,
                ),
            ),
            padding=6,
            border=True,
            layout=ControlLayout(width=250, height=90),
        )
        self.mixed_layout = ControlGrid(
            ((
                Label("Mixed layout"),
                PlacedComponent(self.positioned_panel, x=24, y=12),
            ),),
            column_widths=(110, 180),
            layout=ControlLayout(width=FILL),
        )
        self.table_container = ControlColumn(layout=ControlLayout(width=FILL, height=150))
        self.grid_container = ControlColumn(layout=ControlLayout(width=FILL, height=72))
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
                self.mixed_layout,
                self.table_container,
                self.grid_container,
                self.plot_container,
            ),
            layout=ControlLayout(width=FILL),
        )
        self.telemetry = RollingTelemetry(
            ("activity",),
            history_seconds=12.0,
            sample_interval_seconds=0.1,
        )
        self.live_table = None
        self.state_grid = None
        self.graph = None
        self.command_menu = None
        self.elapsed = 0.0
        self._last_sample = -1.0

    def build(self):
        self.host.build(self.root)
        if self.host.presentation.supports(PresentationCapability.COMMAND_MENUS):
            self.command_menu = CommandMenu(
                self.host.presentation.command_menu_host,
                title="Demo Actions",
                on_command=self._on_demo_command,
            )
            self.command_menu.build(
                CommandSet((
                    CommandSpec("reset", "Reset progress"),
                    CommandSpec(
                        "mode",
                        "Choose mode",
                        children=(
                            CommandSpec("mode:Desktop", "Desktop", checked=True),
                            CommandSpec("mode:Tool", "Tool", checked=False),
                            CommandSpec("mode:Dashboard", "Dashboard", checked=False),
                        ),
                    ),
                ))
            )
        if self.host.presentation.supports(PresentationCapability.LIVE_TABLES):
            self.live_table = LiveTable(
                self.host.presentation.table_host,
                (
                    TableColumnSpec("item", "Live item", "stretch", 0.7),
                    TableColumnSpec("value", "Value", "fixed", 110),
                ),
            )
            self.live_table.build(parent=self.table_container.require_item(), height=130)
        if self.host.presentation.supports(PresentationCapability.STATE_GRIDS):
            self.state_grid = StateGrid(self.host.presentation.state_grid_host)
            self.state_grid.build(
                parent=self.grid_container.require_item(),
                height=58,
                minimum_columns=12,
                maximum_columns=24,
                minimum_cell_width=12,
            )
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

    def _show_demo_menu(self):
        if self.command_menu is None:
            self.status.set_text("Command menus unavailable")
            return
        current_mode = str(self.mode.get_value() or "Desktop")
        self.command_menu.update(
            CommandSet((
                CommandSpec("reset", "Reset progress"),
                CommandSpec(
                    "mode",
                    "Choose mode",
                    children=tuple(
                        CommandSpec(
                            f"mode:{name}",
                            name,
                            checked=(name == current_mode),
                        )
                        for name in ("Desktop", "Tool", "Dashboard")
                    ),
                ),
            ))
        )
        self.command_menu.show()

    def _on_demo_command(self, key: str):
        if key == "reset":
            self.elapsed = 0.0
            self.status.set_text("Progress reset")
            return
        if key.startswith("mode:"):
            mode = key.split(":", 1)[1]
            self.mode.set_value(mode)
            self.status.set_text(f"Mode changed to {mode}")
            if self.command_menu is not None:
                self.command_menu.hide()
            return
        raise ValueError(key)

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

        if self.live_table is not None and self.live_table.exists():
            self.live_table.render(
                TableFrame((
                    TableRow("backend", (TableCell("Presentation backend"), TableCell(self.host.presentation.name))),
                    TableRow("mode", (TableCell("Selected mode"), TableCell(str(self.mode.get_value() or "Desktop")))),
                    TableRow("progress", (TableCell("Runtime progress"), TableCell(f"{round(progress * 100)}%"))),
                ))
            )
        if self.state_grid is not None and self.state_grid.exists():
            active = max(0, min(23, int(progress * 24)))
            self.state_grid.render(
                StateGridFrame(
                    StateGridCell(
                        str(index),
                        (0, 180, 110, 255) if index <= active else (65, 65, 72, 255),
                    )
                    for index in range(24)
                )
            )

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
        height=780,
        minimum_width=560,
        minimum_height=560,
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
