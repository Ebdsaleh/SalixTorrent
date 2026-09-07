"""Dear PyGui implementation of the renderer-neutral live-table host."""

from __future__ import annotations

from app.framework.live_data import (
    TableBinding,
    TableColumnBinding,
    TableColumnSpec,
    TableRow,
    TableRowBinding,
)


class DearPyGuiTableHost:
    @staticmethod
    def _dpg():
        import dearpygui.dearpygui as dpg

        return dpg

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
        dpg = self._dpg()
        kwargs = {
            "parent": parent,
            "header_row": bool(header_row),
            "resizable": bool(resizable),
            "policy": dpg.mvTable_SizingStretchProp,
            "borders_outerH": True,
            "borders_innerH": True,
            "borders_innerV": True,
            "scrollY": bool(scroll_y),
        }
        if height is not None:
            kwargs["height"] = height
        with dpg.table(**kwargs) as table:
            bindings = []
            for spec in columns:
                column_kwargs = {
                    "label": spec.label,
                    "width_stretch": spec.width_mode == "stretch",
                    "width_fixed": spec.width_mode == "fixed",
                    "init_width_or_weight": spec.width,
                }
                item = dpg.add_table_column(**column_kwargs)
                bindings.append(TableColumnBinding(spec.key, item))
        return TableBinding(table=table, columns=tuple(bindings))

    def exists(self, item: object) -> bool:
        return bool(item and self._dpg().does_item_exist(item))

    def destroy(self, item: object) -> None:
        dpg = self._dpg()
        if item and dpg.does_item_exist(item):
            dpg.delete_item(item)

    @staticmethod
    def _attach_tooltip(dpg, item: object, text: str):
        if not text:
            return None
        try:
            with dpg.tooltip(parent=item):
                text_item = dpg.add_text(str(text), wrap=520)
            return text_item
        except Exception:
            return None

    def create_row(self, table: TableBinding, row: TableRow) -> TableRowBinding:
        dpg = self._dpg()
        cell_items = []
        tooltip_items = []
        with dpg.table_row(parent=table.table) as row_item:
            for cell in row.cells:
                kwargs = {}
                if cell.foreground is not None:
                    kwargs["color"] = cell.foreground
                item = dpg.add_text(cell.text, **kwargs)
                cell_items.append(item)
                tooltip_items.append(self._attach_tooltip(dpg, item, cell.tooltip))
        return TableRowBinding(
            key=row.key,
            row=row_item,
            cells=tuple(cell_items),
            metadata={"tooltips": tooltip_items},
        )

    def update_row(self, table: TableBinding, binding: TableRowBinding, row: TableRow) -> None:
        del table
        dpg = self._dpg()
        if len(binding.cells) != len(row.cells):
            raise ValueError("Dear PyGui table row cell count changed unexpectedly")
        metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
        tooltip_items = list(metadata.get("tooltips", [None] * len(binding.cells)))
        if len(tooltip_items) != len(binding.cells):
            tooltip_items = [None] * len(binding.cells)

        for index, (item, cell) in enumerate(zip(binding.cells, row.cells)):
            if not dpg.does_item_exist(item):
                continue
            dpg.set_value(item, cell.text)
            if cell.foreground is not None:
                dpg.configure_item(item, color=cell.foreground)

            tooltip_text_item = tooltip_items[index]
            if cell.tooltip:
                if tooltip_text_item and dpg.does_item_exist(tooltip_text_item):
                    dpg.set_value(tooltip_text_item, cell.tooltip)
                else:
                    tooltip_items[index] = self._attach_tooltip(dpg, item, cell.tooltip)
            elif tooltip_text_item and dpg.does_item_exist(tooltip_text_item):
                try:
                    tooltip = dpg.get_item_parent(tooltip_text_item)
                    if tooltip and dpg.does_item_exist(tooltip):
                        dpg.delete_item(tooltip)
                except Exception:
                    pass
                tooltip_items[index] = None

        if isinstance(binding.metadata, dict):
            binding.metadata["tooltips"] = tooltip_items

    def destroy_row(self, table: TableBinding, binding: TableRowBinding) -> None:
        del table
        self.destroy(binding.row)

    def reorder_rows(self, table: TableBinding, rows: tuple[TableRowBinding, ...]) -> None:
        if not rows:
            return
        try:
            self._dpg().reorder_items(table.table, 1, [row.row for row in rows])
        except Exception:
            pass
