"""Renderer-neutral realtime line-plot contracts.

The current concrete implementation lives outside the framework.  These
working contracts are intentionally small so a second backend can challenge
the abstraction before any public API is frozen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable


Number = int | float


def _finite_number(value: object, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _series_key(value: object) -> str:
    key = str(value or "").strip()
    if not key:
        raise ValueError("plot series keys must be non-empty")
    return key


@dataclass(frozen=True)
class PlotSeriesSpec:
    key: str
    label: str

    def __post_init__(self):
        object.__setattr__(self, "key", _series_key(self.key))
        object.__setattr__(self, "label", str(self.label))


@dataclass(frozen=True)
class PlotSeriesData:
    key: str
    x_values: tuple[float, ...]
    y_values: tuple[float, ...]

    def __init__(self, key: str, x_values: Iterable[Number], y_values: Iterable[Number]):
        key = _series_key(key)
        xs = tuple(_finite_number(value, field=f"{key} x-value") for value in x_values)
        ys = tuple(_finite_number(value, field=f"{key} y-value") for value in y_values)
        if len(xs) != len(ys):
            raise ValueError(f"plot series {key!r} x/y lengths must match")
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "x_values", xs)
        object.__setattr__(self, "y_values", ys)


@dataclass(frozen=True)
class PlotFrame:
    """One complete graph update expressed without backend objects."""

    x_limits: tuple[float, float]
    y_limits: tuple[float, float]
    y_label: str
    series: tuple[PlotSeriesData, ...]

    def __init__(
        self,
        *,
        x_limits: tuple[Number, Number],
        y_limits: tuple[Number, Number],
        y_label: str,
        series: Iterable[PlotSeriesData],
    ):
        x_min = _finite_number(x_limits[0], field="x minimum")
        x_max = _finite_number(x_limits[1], field="x maximum")
        y_min = _finite_number(y_limits[0], field="y minimum")
        y_max = _finite_number(y_limits[1], field="y maximum")
        if x_max < x_min:
            raise ValueError("plot x maximum must be >= minimum")
        if y_max < y_min:
            raise ValueError("plot y maximum must be >= minimum")

        rows = tuple(series)
        keys = tuple(row.key for row in rows)
        if len(set(keys)) != len(keys):
            raise ValueError("plot frame series keys must be unique")

        object.__setattr__(self, "x_limits", (x_min, x_max))
        object.__setattr__(self, "y_limits", (y_min, y_max))
        object.__setattr__(self, "y_label", str(y_label))
        object.__setattr__(self, "series", rows)


@dataclass(frozen=True)
class PlotSeriesBinding:
    key: str
    item: object


@dataclass(frozen=True)
class PlotBinding:
    plot: object
    x_axis: object
    y_axis: object
    series: tuple[PlotSeriesBinding, ...]

    def series_item(self, key: str) -> object:
        key = _series_key(key)
        for binding in self.series:
            if binding.key == key:
                return binding.item
        raise KeyError(key)


@runtime_checkable
class PlotHost(Protocol):
    """Backend operations required by the provisional realtime graph."""

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
        ...

    def exists(self, item: object) -> bool:
        ...

    def destroy(self, item: object) -> None:
        ...

    def set_axis_label(self, axis: object, label: str) -> None:
        ...

    def set_axis_limits(self, axis: object, minimum: Number, maximum: Number) -> None:
        ...

    def set_series(
        self,
        series: object,
        x_values: tuple[float, ...],
        y_values: tuple[float, ...],
    ) -> None:
        ...


def _plot_host_contract_errors(host: object) -> tuple[str, ...]:
    required = (
        "create_line_plot",
        "exists",
        "destroy",
        "set_axis_label",
        "set_axis_limits",
        "set_series",
    )
    return tuple(name for name in required if not callable(getattr(host, name, None)))


class RealtimeGraph:
    """Small coordinator joining semantic plot frames to a concrete plot host."""

    def __init__(self, host: PlotHost, series: Iterable[PlotSeriesSpec]):
        missing = _plot_host_contract_errors(host)
        if missing:
            raise TypeError(
                "plot host does not satisfy PlotHost; missing: " + ", ".join(missing)
            )

        specs = tuple(series)
        if not specs:
            raise ValueError("realtime graph requires at least one series")
        keys = tuple(spec.key for spec in specs)
        if len(set(keys)) != len(keys):
            raise ValueError("realtime graph series keys must be unique")

        self.host = host
        self.series_specs = specs
        self._series_keys = frozenset(keys)
        self._binding: PlotBinding | None = None

    @property
    def binding(self) -> PlotBinding | None:
        return self._binding

    def build(
        self,
        *,
        parent: object,
        x_label: str,
        y_label: str,
        legend: bool = True,
        width: int | float | None = None,
        height: int | float | None = None,
    ) -> PlotBinding:
        if self._binding is not None and self.host.exists(self._binding.plot):
            raise RuntimeError("realtime graph is already built")

        binding = self.host.create_line_plot(
            parent=parent,
            x_label=str(x_label),
            y_label=str(y_label),
            series=self.series_specs,
            legend=bool(legend),
            width=width,
            height=height,
        )
        if not isinstance(binding, PlotBinding):
            raise TypeError("plot host must return a PlotBinding")

        actual_keys = tuple(item.key for item in binding.series)
        expected_keys = tuple(spec.key for spec in self.series_specs)
        if actual_keys != expected_keys:
            raise ValueError("plot host returned series bindings in an unexpected shape")

        self._binding = binding
        return binding

    def exists(self) -> bool:
        return bool(self._binding is not None and self.host.exists(self._binding.plot))

    def require_binding(self) -> PlotBinding:
        if not self.exists():
            raise RuntimeError("realtime graph is not built or its backend item is stale")
        assert self._binding is not None
        return self._binding

    def plot_handle(self) -> object:
        return self.require_binding().plot

    def axis_handle(self, axis: str) -> object:
        binding = self.require_binding()
        name = str(axis).strip().lower()
        if name == "x":
            return binding.x_axis
        if name == "y":
            return binding.y_axis
        raise KeyError(axis)

    def series_handle(self, key: str) -> object:
        return self.require_binding().series_item(key)

    def clear(self) -> None:
        if not self.exists():
            return
        binding = self.require_binding()
        for series in binding.series:
            self.host.set_series(series.item, (), ())

    def render(self, frame: PlotFrame) -> None:
        if not isinstance(frame, PlotFrame):
            raise TypeError("realtime graph render requires a PlotFrame")
        binding = self.require_binding()

        frame_by_key = {series.key: series for series in frame.series}
        unknown = set(frame_by_key) - self._series_keys
        if unknown:
            raise ValueError(
                "plot frame contains unknown series: " + ", ".join(sorted(unknown))
            )

        self.host.set_axis_label(binding.y_axis, frame.y_label)
        self.host.set_axis_limits(binding.x_axis, *frame.x_limits)
        self.host.set_axis_limits(binding.y_axis, *frame.y_limits)

        for series_binding in binding.series:
            data = frame_by_key.get(series_binding.key)
            if data is None:
                self.host.set_series(series_binding.item, (), ())
            else:
                self.host.set_series(
                    series_binding.item,
                    data.x_values,
                    data.y_values,
                )

    def dispose(self) -> None:
        binding = self._binding
        self._binding = None
        if binding is not None and self.host.exists(binding.plot):
            self.host.destroy(binding.plot)
