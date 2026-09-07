"""Tkinter Canvas implementation of the renderer-neutral realtime plot host."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.engine.component_renderers.tkinter import TkinterRenderer
from app.framework.visualization import PlotBinding, PlotSeriesBinding, PlotSeriesSpec


@dataclass(eq=False)
class _TkAxis:
    plot: "_TkPlot"
    name: str


@dataclass(eq=False)
class _TkSeries:
    plot: "_TkPlot"
    key: str
    label: str
    x_values: tuple[float, ...] = ()
    y_values: tuple[float, ...] = ()


@dataclass(eq=False)
class _TkPlot:
    canvas: object
    x_label: str
    y_label: str
    legend: bool
    x_limits: tuple[float, float] = (0.0, 1.0)
    y_limits: tuple[float, float] = (0.0, 1.0)
    series: list[_TkSeries] = field(default_factory=list)
    binding_id: str | None = None


class TkinterPlotHost:
    """Draw simple line plots on Tkinter Canvas using framework plot contracts."""

    _palette = (
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
    )

    def __init__(self, renderer: TkinterRenderer):
        if not isinstance(renderer, TkinterRenderer):
            raise TypeError("TkinterPlotHost requires a TkinterRenderer")
        self.renderer = renderer

    @staticmethod
    def _finite_range(limits: tuple[float, float]) -> tuple[float, float]:
        low, high = (float(value) for value in limits)
        if high == low:
            high = low + 1.0
        return low, high

    def create_line_plot(
        self,
        *,
        parent: object,
        x_label: str,
        y_label: str,
        series: tuple[PlotSeriesSpec, ...],
        legend: bool = True,
        width: int | float | None = None,
        height: int | float | None = None,
    ) -> PlotBinding:
        import tkinter as tk

        parent_widget = self.renderer.content_widget(parent)
        if parent_widget is None:
            raise RuntimeError("Tkinter plot parent has no widget")

        canvas = tk.Canvas(
            parent_widget,
            highlightthickness=0,
            width=max(1, int(width)) if isinstance(width, (int, float)) and width > 0 else 480,
            height=max(1, int(height)) if isinstance(height, (int, float)) and height > 0 else 220,
        )
        canvas.pack(fill="both", expand=True)
        plot = _TkPlot(canvas=canvas, x_label=str(x_label), y_label=str(y_label), legend=bool(legend))
        x_axis = _TkAxis(plot, "x")
        y_axis = _TkAxis(plot, "y")
        plot.series = [_TkSeries(plot, spec.key, spec.label) for spec in series]
        plot.binding_id = canvas.bind("<Configure>", lambda _event: self._redraw(plot), add="+")
        self._redraw(plot)
        return PlotBinding(
            plot=plot,
            x_axis=x_axis,
            y_axis=y_axis,
            series=tuple(PlotSeriesBinding(item.key, item) for item in plot.series),
        )

    @staticmethod
    def _exists_widget(widget) -> bool:
        try:
            return bool(int(widget.winfo_exists()))
        except Exception:
            return False

    def exists(self, item: object) -> bool:
        if isinstance(item, _TkPlot):
            return self._exists_widget(item.canvas)
        if isinstance(item, (_TkAxis, _TkSeries)):
            return self._exists_widget(item.plot.canvas)
        return False

    def destroy(self, item: object) -> None:
        plot = item if isinstance(item, _TkPlot) else getattr(item, "plot", None)
        if not isinstance(plot, _TkPlot) or not self.exists(plot):
            return
        try:
            if plot.binding_id:
                plot.canvas.unbind("<Configure>", plot.binding_id)
        except Exception:
            pass
        try:
            plot.canvas.destroy()
        except Exception:
            pass

    def set_axis_label(self, axis: object, label: str) -> None:
        if not isinstance(axis, _TkAxis):
            raise TypeError("Tkinter plot axis handle is invalid")
        if axis.name == "x":
            axis.plot.x_label = str(label)
        elif axis.name == "y":
            axis.plot.y_label = str(label)
        else:
            raise KeyError(axis.name)
        self._redraw(axis.plot)

    def set_axis_limits(self, axis: object, minimum, maximum) -> None:
        if not isinstance(axis, _TkAxis):
            raise TypeError("Tkinter plot axis handle is invalid")
        limits = (float(minimum), float(maximum))
        if limits[1] < limits[0]:
            raise ValueError("plot axis maximum must be >= minimum")
        if axis.name == "x":
            axis.plot.x_limits = limits
        elif axis.name == "y":
            axis.plot.y_limits = limits
        else:
            raise KeyError(axis.name)
        self._redraw(axis.plot)

    def set_series(
        self,
        series: object,
        x_values: tuple[float, ...],
        y_values: tuple[float, ...],
    ) -> None:
        if not isinstance(series, _TkSeries):
            raise TypeError("Tkinter plot series handle is invalid")
        if len(x_values) != len(y_values):
            raise ValueError("Tkinter plot series x/y lengths must match")
        series.x_values = tuple(float(value) for value in x_values)
        series.y_values = tuple(float(value) for value in y_values)
        self._redraw(series.plot)

    def _redraw(self, plot: _TkPlot) -> None:
        if not self.exists(plot):
            return
        canvas = plot.canvas
        try:
            width = max(120, int(canvas.winfo_width()))
            height = max(100, int(canvas.winfo_height()))
            canvas.delete("all")

            left = 58
            right = max(left + 10, width - 20)
            top = 20
            bottom = max(top + 10, height - 42)
            canvas.create_line(left, top, left, bottom)
            canvas.create_line(left, bottom, right, bottom)
            canvas.create_text((left + right) / 2, height - 14, text=plot.x_label)
            canvas.create_text(8, top, text=plot.y_label, anchor="nw")

            x_min, x_max = self._finite_range(plot.x_limits)
            y_min, y_max = self._finite_range(plot.y_limits)
            x_span = x_max - x_min
            y_span = y_max - y_min

            for index, series in enumerate(plot.series):
                colour = self._palette[index % len(self._palette)]
                points: list[float] = []
                for x_value, y_value in zip(series.x_values, series.y_values):
                    x = left + ((x_value - x_min) / x_span) * (right - left)
                    y = bottom - ((y_value - y_min) / y_span) * (bottom - top)
                    points.extend((x, y))
                if len(points) >= 4:
                    canvas.create_line(*points, fill=colour, width=2)
                elif len(points) == 2:
                    x, y = points
                    canvas.create_oval(x - 1, y - 1, x + 1, y + 1, fill=colour, outline=colour)

            if plot.legend and plot.series:
                y = top + 4
                for index, series in enumerate(plot.series):
                    colour = self._palette[index % len(self._palette)]
                    canvas.create_line(right - 135, y + 5, right - 115, y + 5, fill=colour, width=2)
                    canvas.create_text(right - 108, y + 5, text=series.label, anchor="w")
                    y += 16
        except Exception:
            return
