"""Tkinter ttk.Treeview implementation of the renderer-neutral live-table host."""

from __future__ import annotations

from itertools import count

from app.engine.component_renderers.tkinter import TkinterRenderer
from app.framework.live_data import (
    TableBinding,
    TableColumnBinding,
    TableColumnSpec,
    TableRow,
    TableRowBinding,
)


class TkinterTableHost:
    def __init__(self, renderer: TkinterRenderer):
        if not isinstance(renderer, TkinterRenderer):
            raise TypeError("TkinterTableHost requires a TkinterRenderer")
        self.renderer = renderer
        self._ids = count(1)

    def create_table(
        self,
        *,
        parent: object,
        columns: tuple[TableColumnSpec, ...],
        header_row: bool = True,
        resizable: bool = True,
        scroll_y: bool = True,
        height: int | float | None = None,
    ) -> TableBinding:
        del resizable, height
        import tkinter as tk
        from tkinter import ttk

        parent_widget = self.renderer.content_widget(parent)
        if parent_widget is None:
            raise RuntimeError("Tkinter table parent has no widget")

        frame = ttk.Frame(parent_widget)
        frame.pack(fill="both", expand=True)
        keys = tuple(column.key for column in columns)
        tree = ttk.Treeview(frame, columns=keys, show="headings" if header_row else "", selectmode="browse")
        tree.pack(side="left", fill="both", expand=True)
        if scroll_y:
            scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
            scrollbar.pack(side="right", fill="y")
            tree.configure(yscrollcommand=scrollbar.set)
        tree._ecosystem_frame = frame  # type: ignore[attr-defined]

        bindings = []
        for column in columns:
            tree.heading(column.key, text=column.label)
            if column.width_mode == "fixed":
                tree.column(column.key, width=max(20, int(column.width)), stretch=False)
            else:
                tree.column(column.key, width=max(60, int(column.width * 180)), stretch=True)
            bindings.append(TableColumnBinding(column.key, column.key))
        return TableBinding(table=tree, columns=tuple(bindings))

    @staticmethod
    def _exists_widget(widget) -> bool:
        try:
            return bool(int(widget.winfo_exists()))
        except Exception:
            return False

    def exists(self, item: object) -> bool:
        return self._exists_widget(item)

    def destroy(self, item: object) -> None:
        if not self.exists(item):
            return
        frame = getattr(item, "_ecosystem_frame", None)
        try:
            if frame is not None and self._exists_widget(frame):
                frame.destroy()
            else:
                item.destroy()
        except Exception:
            pass

    def create_row(self, table: TableBinding, row: TableRow) -> TableRowBinding:
        item_id = f"ecosystem_row_{next(self._ids)}"
        table.table.insert("", "end", iid=item_id, values=tuple(cell.text for cell in row.cells))
        return TableRowBinding(key=row.key, row=item_id, cells=tuple(range(len(row.cells))))

    def update_row(self, table: TableBinding, binding: TableRowBinding, row: TableRow) -> None:
        table.table.item(binding.row, values=tuple(cell.text for cell in row.cells))

    def destroy_row(self, table: TableBinding, binding: TableRowBinding) -> None:
        try:
            table.table.delete(binding.row)
        except Exception:
            pass

    def reorder_rows(self, table: TableBinding, rows: tuple[TableRowBinding, ...]) -> None:
        for index, row in enumerate(rows):
            try:
                table.table.move(row.row, "", index)
            except Exception:
                pass
