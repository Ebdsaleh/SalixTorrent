from __future__ import annotations

import ast
import unittest

from tests.helpers import PROJECT_ROOT

from app.engine.plot_hosts import DearPyGuiPlotHost
from app.framework.visualization import (
    PlotBinding,
    PlotFrame,
    PlotHost,
    PlotSeriesBinding,
    PlotSeriesData,
    PlotSeriesSpec,
    RealtimeGraph,
)


class RecordingPlotHost:
    def __init__(self):
        self.created = []
        self.existing = set()
        self.destroyed = []
        self.axis_labels = []
        self.axis_limits = []
        self.series_values = []

    def create_line_plot(
        self,
        *,
        parent,
        x_label,
        y_label,
        series,
        legend=True,
        width=None,
        height=None,
    ):
        plot = "plot"
        binding = PlotBinding(
            plot=plot,
            x_axis="x-axis",
            y_axis="y-axis",
            series=tuple(
                PlotSeriesBinding(spec.key, f"series:{spec.key}") for spec in series
            ),
        )
        self.created.append(
            (parent, x_label, y_label, series, legend, width, height, binding)
        )
        self.existing.add(plot)
        return binding

    def exists(self, item):
        return item in self.existing

    def destroy(self, item):
        self.existing.discard(item)
        self.destroyed.append(item)

    def set_axis_label(self, axis, label):
        self.axis_labels.append((axis, label))

    def set_axis_limits(self, axis, minimum, maximum):
        self.axis_limits.append((axis, float(minimum), float(maximum)))

    def set_series(self, series, x_values, y_values):
        self.series_values.append((series, tuple(x_values), tuple(y_values)))


class RealtimeVisualizationTests(unittest.TestCase):
    def _graph(self, host=None):
        host = host or RecordingPlotHost()
        graph = RealtimeGraph(
            host,
            (
                PlotSeriesSpec("primary", "Primary"),
                PlotSeriesSpec("reference", "Reference"),
            ),
        )
        return host, graph

    def test_plot_host_contract_is_backend_neutral(self):
        host = RecordingPlotHost()
        self.assertIsInstance(host, PlotHost)
        self.assertNotIn("dearpygui", (PROJECT_ROOT / "app" / "framework" / "visualization.py").read_text(encoding="utf-8").lower())

    def test_realtime_graph_rejects_incomplete_host(self):
        with self.assertRaisesRegex(TypeError, "PlotHost"):
            RealtimeGraph(object(), (PlotSeriesSpec("a", "A"),))

    def test_duplicate_series_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            RealtimeGraph(
                RecordingPlotHost(),
                (PlotSeriesSpec("a", "A"), PlotSeriesSpec("a", "Again")),
            )

    def test_build_returns_backend_handles_without_exposing_backend_in_frame(self):
        host, graph = self._graph()

        binding = graph.build(
            parent="parent",
            x_label="Seconds",
            y_label="Units",
            width=-1,
            height=-1,
        )

        self.assertEqual(binding.plot, "plot")
        self.assertEqual(graph.plot_handle(), "plot")
        self.assertEqual(graph.axis_handle("x"), "x-axis")
        self.assertEqual(graph.series_handle("primary"), "series:primary")
        self.assertEqual(host.created[0][0:3], ("parent", "Seconds", "Units"))

    def test_render_applies_complete_frame_and_clears_missing_series(self):
        host, graph = self._graph()
        graph.build(parent="parent", x_label="X", y_label="Y")

        graph.render(
            PlotFrame(
                x_limits=(-30, 0),
                y_limits=(0, 100),
                y_label="KB/s",
                series=(PlotSeriesData("primary", (-1, 0), (10, 20)),),
            )
        )

        self.assertEqual(host.axis_labels, [("y-axis", "KB/s")])
        self.assertEqual(
            host.axis_limits,
            [("x-axis", -30.0, 0.0), ("y-axis", 0.0, 100.0)],
        )
        self.assertEqual(
            host.series_values,
            [
                ("series:primary", (-1.0, 0.0), (10.0, 20.0)),
                ("series:reference", (), ()),
            ],
        )

    def test_plot_frame_rejects_mismatched_series_values(self):
        with self.assertRaisesRegex(ValueError, "lengths"):
            PlotSeriesData("bad", (0, 1), (2,))

    def test_clear_and_dispose_are_explicit(self):
        host, graph = self._graph()
        graph.build(parent="parent", x_label="X", y_label="Y")

        graph.clear()
        graph.dispose()

        self.assertEqual(
            host.series_values,
            [("series:primary", (), ()), ("series:reference", (), ())],
        )
        self.assertEqual(host.destroyed, ["plot"])
        self.assertFalse(graph.exists())

    def test_dearpygui_plot_host_is_isolated_from_framework(self):
        backend_source = (
            PROJECT_ROOT / "app" / "engine" / "plot_hosts" / "dearpygui.py"
        ).read_text(encoding="utf-8")
        framework_source = (
            PROJECT_ROOT / "app" / "framework" / "visualization.py"
        ).read_text(encoding="utf-8")

        self.assertIn("class DearPyGuiPlotHost", backend_source)
        self.assertIn("import dearpygui.dearpygui as dpg", backend_source)
        self.assertNotIn("dearpygui", framework_source.lower())
        self.assertIsInstance(DearPyGuiPlotHost(), PlotHost)

    def test_speed_view_routes_plot_creation_and_updates_through_graph_boundary(self):
        source = (PROJECT_ROOT / "app" / "views" / "speed_view.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        dpg_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "dpg"
        }

        self.assertIn("RealtimeGraph", source)
        self.assertIn("DearPyGuiPlotHost", source)
        self.assertNotIn("plot", {name.removeprefix("add_") for name in dpg_calls})
        self.assertNotIn("add_line_series", dpg_calls)
        self.assertNotIn("set_axis_limits", dpg_calls)
        self.assertNotIn("configure_item", dpg_calls)


if __name__ == "__main__":
    unittest.main()
