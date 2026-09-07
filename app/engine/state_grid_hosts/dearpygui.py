"""Dear PyGui drawlist implementation of the renderer-neutral state grid."""

from __future__ import annotations

from itertools import count
import math

from app.framework.live_data import StateGridBinding, StateGridCell


class DearPyGuiStateGridHost:
    """Render categorical state cells into a Dear PyGui drawlist.

    The host owns resize observation because reflow is a concrete presentation
    concern. ``StateGrid`` can therefore continue suppressing identical data
    frames while this adapter redraws the current cells when the physical
    drawlist width changes.
    """

    _registry_ids = count(1)

    def __init__(self):
        # Resize registries are backend resources independent of the drawlist's
        # child slot. Keep explicit ownership so destroying a grid never leaks
        # the handler registry that was created for it.
        self._resize_registries: dict[object, object] = {}

    @staticmethod
    def _dpg():
        import dearpygui.dearpygui as dpg

        return dpg

    def create_state_grid(
        self,
        *,
        parent: object,
        height: int | float,
        minimum_columns: int = 24,
        maximum_columns: int = 128,
        minimum_cell_width: int | float = 7,
    ) -> StateGridBinding:
        if minimum_columns < 1 or maximum_columns < minimum_columns:
            raise ValueError("state-grid column bounds are invalid")
        if float(minimum_cell_width) <= 0:
            raise ValueError("state-grid minimum_cell_width must be positive")
        dpg = self._dpg()
        grid = dpg.add_drawlist(parent=parent, width=-1, height=height)
        metadata = {
            "height": float(height),
            "minimum_columns": int(minimum_columns),
            "maximum_columns": int(maximum_columns),
            "minimum_cell_width": float(minimum_cell_width),
            "cells": (),
        }
        binding = StateGridBinding(grid=grid, metadata=metadata)
        registry = f"ecosystem_state_grid_resize::{next(self._registry_ids)}"
        try:
            with dpg.item_handler_registry(tag=registry):
                dpg.add_item_resize_handler(
                    callback=lambda sender=None, app_data=None, user_data=None: self._redraw(binding)
                )
            dpg.bind_item_handler_registry(grid, registry)
            self._resize_registries[grid] = registry
        except Exception:
            try:
                if dpg.does_item_exist(registry):
                    dpg.delete_item(registry)
            except Exception:
                pass
        return binding

    def exists(self, item: object) -> bool:
        if isinstance(item, StateGridBinding):
            item = item.grid
        return bool(item and self._dpg().does_item_exist(item))

    def destroy(self, item: object) -> None:
        dpg = self._dpg()
        if isinstance(item, StateGridBinding):
            item = item.grid
        registry = self._resize_registries.pop(item, None)
        try:
            if registry and dpg.does_item_exist(registry):
                dpg.delete_item(registry)
        except Exception:
            pass
        if item and dpg.does_item_exist(item):
            dpg.delete_item(item)

    def set_cells(self, grid: StateGridBinding, cells: tuple[StateGridCell, ...]) -> None:
        metadata = grid.metadata if isinstance(grid.metadata, dict) else {}
        metadata["cells"] = tuple(cells)
        self._redraw(grid)

    def _redraw(self, grid: StateGridBinding) -> None:
        dpg = self._dpg()
        if not self.exists(grid.grid):
            return
        dpg.delete_item(grid.grid, children_only=True)
        metadata = grid.metadata if isinstance(grid.metadata, dict) else {}
        cells = tuple(metadata.get("cells", ()))
        if not cells:
            return
        height = float(metadata.get("height", 92.0))
        minimum_columns = max(1, int(metadata.get("minimum_columns", 24)))
        maximum_columns = max(minimum_columns, int(metadata.get("maximum_columns", 128)))
        minimum_cell_width = max(1.0, float(metadata.get("minimum_cell_width", 7.0)))
        try:
            rect_size = dpg.get_item_rect_size(grid.grid)
            width = float(rect_size[0]) if rect_size else 0.0
        except Exception:
            width = 0.0
        if width < 100:
            width = 1000.0
        columns = max(minimum_columns, min(maximum_columns, int(width // minimum_cell_width)))
        rows = max(1, math.ceil(len(cells) / columns))
        cell_width = width / columns
        cell_height = height / rows
        for index, cell in enumerate(cells):
            row = index // columns
            column = index % columns
            x1 = column * cell_width
            y1 = row * cell_height
            x2 = x1 + max(1.0, cell_width - 1.0)
            y2 = y1 + max(1.0, cell_height - 1.0)
            dpg.draw_rectangle(
                (x1, y1),
                (x2, y2),
                color=cell.border,
                fill=cell.fill,
                thickness=1.0,
                parent=grid.grid,
            )
