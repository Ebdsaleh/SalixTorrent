"""Dear PyGui implementation of the renderer-neutral realtime plot host."""

from __future__ import annotations

from app.framework.visualization import (
    PlotBinding,
    PlotSeriesBinding,
    PlotSeriesSpec,
)


class DearPyGuiPlotHost:
    """Concrete Dear PyGui operations required by ``RealtimeGraph``."""

    @staticmethod
    def _dpg():
        import dearpygui.dearpygui as dpg

        return dpg

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
        dpg = self._dpg()
        kwargs = {"parent": parent}
        if width is not None:
            kwargs["width"] = width
        if height is not None:
            kwargs["height"] = height

        with dpg.plot(**kwargs) as plot:
            if legend:
                dpg.add_plot_legend()
            x_axis = dpg.add_plot_axis(dpg.mvXAxis, label=str(x_label))
            y_axis = dpg.add_plot_axis(dpg.mvYAxis, label=str(y_label))
            bindings = tuple(
                PlotSeriesBinding(
                    spec.key,
                    dpg.add_line_series([], [], label=spec.label, parent=y_axis),
                )
                for spec in series
            )

        return PlotBinding(
            plot=plot,
            x_axis=x_axis,
            y_axis=y_axis,
            series=bindings,
        )

    def exists(self, item: object) -> bool:
        return bool(item and self._dpg().does_item_exist(item))

    def destroy(self, item: object) -> None:
        dpg = self._dpg()
        if item and dpg.does_item_exist(item):
            dpg.delete_item(item)

    def set_axis_label(self, axis: object, label: str) -> None:
        self._dpg().configure_item(axis, label=str(label))

    def set_axis_limits(self, axis: object, minimum, maximum) -> None:
        self._dpg().set_axis_limits(axis, float(minimum), float(maximum))

    def set_series(
        self,
        series: object,
        x_values: tuple[float, ...],
        y_values: tuple[float, ...],
    ) -> None:
        self._dpg().set_value(series, [list(x_values), list(y_values)])
