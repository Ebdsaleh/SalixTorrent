"""Tkinter host for the renderer-neutral designer component palette."""

from __future__ import annotations

from itertools import count

from app.engine.component_renderers.tkinter import TkinterRenderer
from app.framework.designer_component_palette import (
    DesignerComponentPaletteBinding,
    DesignerComponentPaletteState,
)


class TkinterDesignerComponentPaletteHost:
    """Render grouped palette entries through ttk.Treeview without owning policy."""

    def __init__(self, renderer: TkinterRenderer, *, height_rows: int = 8):
        if not isinstance(renderer, TkinterRenderer):
            raise TypeError("TkinterDesignerComponentPaletteHost requires a TkinterRenderer")
        self.renderer = renderer
        self.height_rows = max(5, int(height_rows))
        self._ids = count(1)

    @staticmethod
    def _exists_widget(widget) -> bool:
        try:
            return bool(int(widget.winfo_exists()))
        except Exception:
            return False

    @staticmethod
    def _category_label(category: str) -> str:
        return str(category).replace("_", " ").strip().title()

    def _populate(
        self,
        binding: DesignerComponentPaletteBinding,
        state: DesignerComponentPaletteState,
    ) -> None:
        metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
        tree = metadata.get("tree")
        if tree is None or not self._exists_widget(tree):
            raise RuntimeError("Tkinter component palette tree is unavailable")

        existing = tree.get_children("")
        if existing:
            tree.delete(*existing)
        binding.items.clear()
        reverse: dict[str, str] = {}

        by_category = {category: [] for category in state.categories}
        for entry in state.entries:
            by_category.setdefault(entry.category, []).append(entry)

        for category in state.categories:
            category_iid = f"ecosystem_designer_palette_category_{next(self._ids)}"
            tree.insert(
                "",
                "end",
                iid=category_iid,
                text=self._category_label(category),
                open=True,
            )
            for entry in by_category.get(category, ()):
                iid = f"ecosystem_designer_palette_item_{next(self._ids)}"
                suffix = "  ▸" if entry.accepts_children else ""
                tree.insert(category_iid, "end", iid=iid, text=f"{entry.label}{suffix}")
                binding.items[entry.component_type_key] = iid
                reverse[iid] = entry.component_type_key

        metadata["reverse"] = reverse
        metadata["closed"] = state.closed

    def build(
        self,
        state: DesignerComponentPaletteState,
        *,
        parent: object,
        title: str = "",
        on_activate,
    ) -> DesignerComponentPaletteBinding:
        from tkinter import ttk

        parent_widget = self.renderer.content_widget(parent)
        if parent_widget is None:
            raise RuntimeError("Tkinter component palette parent has no widget")

        frame = ttk.LabelFrame(parent_widget, text=str(title or "Components"))
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, show="tree", selectmode="browse", height=self.height_rows)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)

        binding = DesignerComponentPaletteBinding(
            panel=frame,
            items={},
            metadata={
                "tree": tree,
                "scrollbar": scrollbar,
                "reverse": {},
                "closed": state.closed,
                "on_activate": on_activate,
            },
        )

        def activate_current(_event=None):
            metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
            if metadata.get("closed"):
                return None
            selection = tuple(tree.selection())
            iid = str(selection[0]) if selection else str(tree.focus())
            component_key = str(metadata.get("reverse", {}).get(iid, ""))
            if component_key:
                return on_activate(component_key)
            return None

        binding.metadata["activate_current"] = activate_current
        tree.bind("<Double-1>", activate_current, add="+")
        tree.bind("<Return>", activate_current, add="+")
        self._populate(binding, state)
        return binding

    def update(
        self,
        binding: DesignerComponentPaletteBinding,
        state: DesignerComponentPaletteState,
    ) -> None:
        self._populate(binding, state)

    def exists(self, binding: DesignerComponentPaletteBinding) -> bool:
        return self._exists_widget(binding.panel)

    def dispose(self, binding: DesignerComponentPaletteBinding) -> None:
        if self._exists_widget(binding.panel):
            try:
                binding.panel.destroy()
            except Exception:
                pass
        binding.items.clear()
        if isinstance(binding.metadata, dict):
            binding.metadata.clear()
        binding.title_item = None
