"""Dear PyGui host for the renderer-neutral designer component palette."""

from __future__ import annotations

from app.framework.designer_component_palette import (
    DesignerComponentPaletteBinding,
    DesignerComponentPaletteState,
)


class DearPyGuiDesignerComponentPaletteHost:
    """Render catalog entries as grouped disposable Dear PyGui tool buttons."""

    def __init__(self, *, height: int = 190):
        self.height = max(100, int(height))

    @staticmethod
    def _dpg():
        import dearpygui.dearpygui as dpg

        return dpg

    @staticmethod
    def _category_label(category: str) -> str:
        return str(category).replace("_", " ").strip().title()

    def _populate(
        self,
        binding: DesignerComponentPaletteBinding,
        state: DesignerComponentPaletteState,
    ) -> None:
        dpg = self._dpg()
        metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
        body = metadata.get("body")
        if body is None or not dpg.does_item_exist(body):
            raise RuntimeError("Dear PyGui component palette body is unavailable")

        dpg.delete_item(body, children_only=True)
        binding.items.clear()
        on_activate = metadata["on_activate"]
        enabled = not state.closed

        by_category = {category: [] for category in state.categories}
        for entry in state.entries:
            by_category.setdefault(entry.category, []).append(entry)

        for category in state.categories:
            header = dpg.add_collapsing_header(
                label=self._category_label(category),
                default_open=True,
                parent=body,
            )
            for entry in by_category.get(category, ()):
                suffix = "  ▸" if entry.accepts_children else ""
                item = dpg.add_button(
                    label=f"{entry.label}{suffix}",
                    parent=header,
                    width=-1,
                    enabled=enabled,
                    user_data=entry.component_type_key,
                    callback=lambda _s, _a, component_key: on_activate(component_key),
                )
                binding.items[entry.component_type_key] = item

    def build(
        self,
        state: DesignerComponentPaletteState,
        *,
        parent: object,
        title: str = "",
        on_activate,
    ) -> DesignerComponentPaletteBinding:
        dpg = self._dpg()
        panel = dpg.add_child_window(parent=parent, border=True, height=self.height)
        title_item = None
        if title:
            title_item = dpg.add_text(str(title), parent=panel)
            dpg.add_separator(parent=panel)
        body = dpg.add_group(parent=panel)
        binding = DesignerComponentPaletteBinding(
            panel=panel,
            items={},
            title_item=title_item,
            metadata={"body": body, "on_activate": on_activate},
        )
        self._populate(binding, state)
        return binding

    def update(
        self,
        binding: DesignerComponentPaletteBinding,
        state: DesignerComponentPaletteState,
    ) -> None:
        self._populate(binding, state)

    def exists(self, binding: DesignerComponentPaletteBinding) -> bool:
        try:
            return bool(self._dpg().does_item_exist(binding.panel))
        except Exception:
            return False

    def dispose(self, binding: DesignerComponentPaletteBinding) -> None:
        dpg = self._dpg()
        if dpg.does_item_exist(binding.panel):
            dpg.delete_item(binding.panel)
        binding.items.clear()
        if isinstance(binding.metadata, dict):
            binding.metadata.clear()
        binding.title_item = None
