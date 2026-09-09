"""Dear PyGui host for the renderer-neutral designer hierarchy panel."""

from __future__ import annotations

from app.framework.designer_hierarchy import DesignerHierarchyRow
from app.framework.designer_hierarchy_panel import DesignerHierarchyPanelBinding


class DearPyGuiDesignerHierarchyPanelHost:
    """Render visible hierarchy rows as disposable Dear PyGui presentation items."""

    def __init__(self, *, height: int = 260):
        self.height = max(80, int(height))

    @staticmethod
    def _dpg():
        import dearpygui.dearpygui as dpg

        return dpg

    def _populate(
        self,
        binding: DesignerHierarchyPanelBinding,
        rows: tuple[DesignerHierarchyRow, ...],
    ) -> None:
        dpg = self._dpg()
        metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
        body = metadata.get("body")
        if body is None or not dpg.does_item_exist(body):
            raise RuntimeError("Dear PyGui hierarchy panel body is unavailable")
        dpg.delete_item(body, children_only=True)
        binding.rows.clear()
        toggles: dict[str, object] = {}
        on_select = metadata["on_select"]
        on_toggle = metadata["on_toggle"]

        for row in rows:
            with dpg.group(parent=body, horizontal=True):
                if row.depth:
                    dpg.add_spacer(width=row.depth * 16)
                if row.expandable:
                    toggle = dpg.add_button(
                        label="-" if row.expanded else "+",
                        width=24,
                        user_data=row.node_id,
                        callback=lambda _s, _a, node_id: on_toggle(node_id),
                    )
                    toggles[row.node_id] = toggle
                else:
                    dpg.add_spacer(width=28)

                label = f"{row.type_key}  [{row.node_id}]"
                if row.focused:
                    label += "  *"
                item = dpg.add_selectable(
                    label=label,
                    default_value=bool(row.selected),
                    user_data=row.node_id,
                    callback=lambda _s, _a, node_id: on_select(node_id),
                )
                binding.rows[row.node_id] = item

        metadata["toggles"] = toggles

    def build(
        self,
        rows: tuple[DesignerHierarchyRow, ...],
        *,
        parent: object,
        title: str = "",
        on_select,
        on_toggle,
    ) -> DesignerHierarchyPanelBinding:
        dpg = self._dpg()
        panel = dpg.add_child_window(parent=parent, border=True, height=self.height)
        title_item = None
        if title:
            title_item = dpg.add_text(str(title), parent=panel)
            dpg.add_separator(parent=panel)
        body = dpg.add_group(parent=panel)
        binding = DesignerHierarchyPanelBinding(
            panel=panel,
            rows={},
            title_item=title_item,
            metadata={
                "body": body,
                "on_select": on_select,
                "on_toggle": on_toggle,
                "toggles": {},
            },
        )
        self._populate(binding, rows)
        return binding

    def update(
        self,
        binding: DesignerHierarchyPanelBinding,
        rows: tuple[DesignerHierarchyRow, ...],
    ) -> None:
        self._populate(binding, rows)

    def exists(self, binding: DesignerHierarchyPanelBinding) -> bool:
        try:
            return bool(self._dpg().does_item_exist(binding.panel))
        except Exception:
            return False

    def dispose(self, binding: DesignerHierarchyPanelBinding) -> None:
        dpg = self._dpg()
        if dpg.does_item_exist(binding.panel):
            dpg.delete_item(binding.panel)
        binding.rows.clear()
        if isinstance(binding.metadata, dict):
            binding.metadata.clear()
        binding.title_item = None
