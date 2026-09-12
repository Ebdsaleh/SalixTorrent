"""Tkinter host for the renderer-neutral designer hierarchy panel."""

from __future__ import annotations

from itertools import count

from app.engine.component_renderers.tkinter import TkinterRenderer
from app.framework.designer_hierarchy import DesignerHierarchyRow
from app.framework.designer_hierarchy_panel import DesignerHierarchyPanelBinding


class TkinterDesignerHierarchyPanelHost:
    """Render hierarchy rows through ttk.Treeview without owning semantics."""

    def __init__(self, renderer: TkinterRenderer, *, height_rows: int = 12):
        if not isinstance(renderer, TkinterRenderer):
            raise TypeError("TkinterDesignerHierarchyPanelHost requires a TkinterRenderer")
        self.renderer = renderer
        self.height_rows = max(4, int(height_rows))
        self._ids = count(1)

    @staticmethod
    def _exists_widget(widget) -> bool:
        try:
            return bool(int(widget.winfo_exists()))
        except Exception:
            return False

    @staticmethod
    def _tree(binding: DesignerHierarchyPanelBinding):
        metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
        return metadata.get("tree")

    def _populate(
        self,
        binding: DesignerHierarchyPanelBinding,
        rows: tuple[DesignerHierarchyRow, ...],
    ) -> None:
        metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
        tree = metadata.get("tree")
        if tree is None or not self._exists_widget(tree):
            raise RuntimeError("Tkinter hierarchy tree is unavailable")

        metadata["suppress"] = True
        generation = int(metadata.get("population_generation", 0)) + 1
        metadata["population_generation"] = generation
        try:
            existing = tree.get_children("")
            if existing:
                tree.delete(*existing)
            binding.rows.clear()
            reverse: dict[str, str] = {}

            for row in rows:
                parent_iid = binding.rows.get(row.parent_id, "")
                iid = f"ecosystem_designer_hierarchy_{next(self._ids)}"
                text = f"{row.type_key}  [{row.node_id}]"
                if row.focused:
                    text += "  *"
                tree.insert(
                    parent_iid,
                    "end",
                    iid=iid,
                    text=text,
                    open=bool(row.expanded),
                )
                binding.rows[row.node_id] = iid
                reverse[iid] = row.node_id
                if row.expandable and not row.expanded:
                    dummy = f"ecosystem_designer_hierarchy_dummy_{next(self._ids)}"
                    tree.insert(iid, "end", iid=dummy, text="")

            metadata["reverse"] = reverse
            selected = next((row.node_id for row in rows if row.selected), "")
            focused = next((row.node_id for row in rows if row.focused), "")
            selected_iid = binding.rows.get(selected)
            if selected_iid:
                tree.selection_set(selected_iid)
                tree.see(selected_iid)
            else:
                tree.selection_remove(tree.selection())
            focused_iid = binding.rows.get(focused)
            if focused_iid:
                tree.focus(focused_iid)
        finally:
            # Tk queues <<TreeviewSelect>> after selection_set().  Keep native
            # callbacks suppressed until the current event queue has drained so
            # a presentation refresh cannot recursively select/rebuild forever.
            def release_suppression(expected=generation):
                current = binding.metadata if isinstance(binding.metadata, dict) else {}
                if current.get("population_generation") == expected:
                    current["suppress"] = False

            self.renderer.root.after_idle(release_suppression)

    def build(
        self,
        rows: tuple[DesignerHierarchyRow, ...],
        *,
        parent: object,
        title: str = "",
        on_select,
        on_toggle,
        on_reparent,
    ) -> DesignerHierarchyPanelBinding:
        from tkinter import ttk

        parent_widget = self.renderer.content_widget(parent)
        if parent_widget is None:
            raise RuntimeError("Tkinter hierarchy panel parent has no widget")

        frame = ttk.LabelFrame(parent_widget, text=str(title or "Hierarchy"))
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, show="tree", selectmode="browse", height=self.height_rows)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)

        binding = DesignerHierarchyPanelBinding(
            panel=frame,
            rows={},
            metadata={
                "tree": tree,
                "scrollbar": scrollbar,
                "on_select": on_select,
                "on_toggle": on_toggle,
                "on_reparent": on_reparent,
                "reverse": {},
                "suppress": False,
                "population_generation": 0,
                "drag_source": "",
                "drag_start": (0, 0),
                "drag_active": False,
            },
        )

        def current_node_id() -> str:
            metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
            reverse = metadata.get("reverse", {})
            return str(reverse.get(str(tree.focus()), ""))

        def handle_select(_event=None):
            metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
            if metadata.get("suppress"):
                return None
            selection = tuple(tree.selection())
            if not selection:
                return None
            node_id = str(metadata.get("reverse", {}).get(str(selection[0]), ""))
            if node_id:
                # Rebuilding the tree from inside a native selection callback can
                # invalidate the item Tcl is still dispatching.  Defer semantic
                # dispatch until the current Tk event has unwound.
                self.renderer.root.after_idle(lambda value=node_id: on_select(value))
            return None

        def handle_toggle(_event=None):
            metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
            if metadata.get("suppress"):
                return None
            node_id = current_node_id()
            if node_id:
                # The workspace remains the expansion owner; this scheduling is
                # only a safe Tk callback boundary before the presenter rebuilds.
                self.renderer.root.after_idle(lambda value=node_id: on_toggle(value))
            return None

        def handle_drag_press(event):
            metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
            iid = str(tree.identify_row(event.y) or "")
            source_id = str(metadata.get("reverse", {}).get(iid, ""))
            metadata["drag_source"] = source_id
            metadata["drag_start"] = (int(event.x), int(event.y))
            metadata["drag_active"] = False
            return None

        def handle_drag_motion(event):
            metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
            if not metadata.get("drag_source"):
                return None
            start_x, start_y = metadata.get("drag_start", (event.x, event.y))
            if abs(int(event.x) - int(start_x)) + abs(int(event.y) - int(start_y)) >= 6:
                metadata["drag_active"] = True
            return None

        def handle_drag_release(event):
            metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
            source_id = str(metadata.get("drag_source", ""))
            active = bool(metadata.get("drag_active"))
            metadata["drag_source"] = ""
            metadata["drag_active"] = False
            if not source_id or not active:
                return None
            target_iid = str(tree.identify_row(event.y) or "")
            target_id = str(metadata.get("reverse", {}).get(target_iid, ""))
            if target_id and target_id != source_id:
                # Defer until the native button-release dispatch unwinds; the
                # presenter may rebuild the complete tree after the edit.
                self.renderer.root.after_idle(
                    lambda source=source_id, target=target_id: on_reparent(source, target)
                )
            return None

        tree.bind("<<TreeviewSelect>>", handle_select, add="+")
        tree.bind("<<TreeviewOpen>>", handle_toggle, add="+")
        tree.bind("<<TreeviewClose>>", handle_toggle, add="+")
        tree.bind("<ButtonPress-1>", handle_drag_press, add="+")
        tree.bind("<B1-Motion>", handle_drag_motion, add="+")
        tree.bind("<ButtonRelease-1>", handle_drag_release, add="+")
        self._populate(binding, rows)
        return binding

    def update(
        self,
        binding: DesignerHierarchyPanelBinding,
        rows: tuple[DesignerHierarchyRow, ...],
    ) -> None:
        self._populate(binding, rows)

    def exists(self, binding: DesignerHierarchyPanelBinding) -> bool:
        return self._exists_widget(binding.panel)

    def dispose(self, binding: DesignerHierarchyPanelBinding) -> None:
        if self._exists_widget(binding.panel):
            try:
                binding.panel.destroy()
            except Exception:
                pass
        binding.rows.clear()
        if isinstance(binding.metadata, dict):
            binding.metadata.clear()
        binding.title_item = None
