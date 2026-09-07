"""Tkinter Canvas implementation of the renderer-neutral state grid."""

from __future__ import annotations

from dataclasses import dataclass
import math

from app.engine.component_renderers.tkinter import TkinterRenderer
from app.framework.live_data import StateGridBinding, StateGridCell


def _hex(colour) -> str:
    return "#%02x%02x%02x" % tuple(int(value) for value in colour[:3])


@dataclass(eq=False)
class _TkStateGrid:
    canvas: object
    height: float
    minimum_columns: int
    maximum_columns: int
    minimum_cell_width: float
    cells: tuple[StateGridCell, ...] = ()
    binding_id: str | None = None


class TkinterStateGridHost:
    def __init__(self, renderer: TkinterRenderer):
        if not isinstance(renderer, TkinterRenderer):
            raise TypeError("TkinterStateGridHost requires a TkinterRenderer")
        self.renderer = renderer

    def create_state_grid(
        self,
        *,
        parent: object,
        height: int | float,
        minimum_columns: int = 24,
        maximum_columns: int = 128,
        minimum_cell_width: int | float = 7,
    ) -> StateGridBinding:
        import tkinter as tk

        if minimum_columns < 1 or maximum_columns < minimum_columns:
            raise ValueError("state-grid column bounds are invalid")
        if float(minimum_cell_width) <= 0:
            raise ValueError("state-grid minimum_cell_width must be positive")
        parent_widget = self.renderer.content_widget(parent)
        if parent_widget is None:
            raise RuntimeError("Tkinter state-grid parent has no widget")
        canvas = tk.Canvas(parent_widget, highlightthickness=0, height=max(1, int(height)))
        canvas.pack(fill="x", expand=False)
        state = _TkStateGrid(
            canvas=canvas,
            height=float(height),
            minimum_columns=int(minimum_columns),
            maximum_columns=int(maximum_columns),
            minimum_cell_width=float(minimum_cell_width),
        )
        state.binding_id = canvas.bind("<Configure>", lambda _event: self._redraw(state), add="+")
        return StateGridBinding(grid=state)

    @staticmethod
    def _exists_widget(widget) -> bool:
        try:
            return bool(int(widget.winfo_exists()))
        except Exception:
            return False

    def exists(self, item: object) -> bool:
        if isinstance(item, _TkStateGrid):
            return self._exists_widget(item.canvas)
        return False

    def destroy(self, item: object) -> None:
        if not isinstance(item, _TkStateGrid) or not self.exists(item):
            return
        try:
            if item.binding_id:
                item.canvas.unbind("<Configure>", item.binding_id)
        except Exception:
            pass
        try:
            item.canvas.destroy()
        except Exception:
            pass

    def set_cells(self, grid: StateGridBinding, cells: tuple[StateGridCell, ...]) -> None:
        state = grid.grid
        if not isinstance(state, _TkStateGrid):
            raise TypeError("Tkinter state-grid handle is invalid")
        state.cells = tuple(cells)
        self._redraw(state)

    def _redraw(self, state: _TkStateGrid) -> None:
        if not self.exists(state):
            return
        canvas = state.canvas
        try:
            width = max(100.0, float(canvas.winfo_width()))
            canvas.delete("all")
            if not state.cells:
                return
            columns = max(
                state.minimum_columns,
                min(state.maximum_columns, int(width // state.minimum_cell_width)),
            )
            rows = max(1, math.ceil(len(state.cells) / columns))
            cell_width = width / columns
            cell_height = state.height / rows
            for index, cell in enumerate(state.cells):
                row = index // columns
                column = index % columns
                x1 = column * cell_width
                y1 = row * cell_height
                x2 = x1 + max(1.0, cell_width - 1.0)
                y2 = y1 + max(1.0, cell_height - 1.0)
                canvas.create_rectangle(
                    x1,
                    y1,
                    x2,
                    y2,
                    outline=_hex(cell.border),
                    fill=_hex(cell.fill),
                    width=1,
                )
        except Exception:
            return
