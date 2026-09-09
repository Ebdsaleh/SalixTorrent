"""Tkinter host for the backend-neutral designer component placement surface."""

from __future__ import annotations

from app.engine.component_renderers.tkinter import TkinterRenderer
from app.framework.designer_component_placement import (
    DesignerComponentPlacementBinding,
    DesignerComponentPlacementState,
)


class TkinterDesignerComponentPlacementHost:
    """Render one placement form through ttk widgets without owning policy."""

    def __init__(self, renderer: TkinterRenderer):
        if not isinstance(renderer, TkinterRenderer):
            raise TypeError("TkinterDesignerComponentPlacementHost requires a TkinterRenderer")
        self.renderer = renderer

    @staticmethod
    def _exists_widget(widget) -> bool:
        try:
            return bool(int(widget.winfo_exists()))
        except Exception:
            return False

    @staticmethod
    def _parent_labels(state: DesignerComponentPlacementState):
        labels = [parent.display_label for parent in state.parents]
        by_label = {parent.display_label: parent.node_id for parent in state.parents}
        by_id = {parent.node_id: parent.display_label for parent in state.parents}
        return labels, by_label, by_id

    @staticmethod
    def _slot_labels(state: DesignerComponentPlacementState):
        slots = state.current_slots
        labels = [f"{slot.label} [{slot.key}]" for slot in slots]
        by_label = {f"{slot.label} [{slot.key}]": slot.key for slot in slots}
        by_key = {slot.key: f"{slot.label} [{slot.key}]" for slot in slots}
        return labels, by_label, by_key

    def build(
        self,
        state: DesignerComponentPlacementState,
        *,
        parent: object,
        title: str,
        on_parent,
        on_slot,
        on_index,
        on_metadata,
        on_commit,
        on_cancel,
    ) -> DesignerComponentPlacementBinding:
        import tkinter as tk
        from tkinter import ttk

        parent_widget = self.renderer.content_widget(parent)
        if parent_widget is None:
            raise RuntimeError("Tkinter component placement parent has no widget")
        frame = ttk.LabelFrame(parent_widget, text=str(title or "Placement"))
        frame.pack(fill="x", expand=False)
        frame.columnconfigure(1, weight=1)

        request_var = tk.StringVar(frame)
        parent_var = tk.StringVar(frame)
        slot_var = tk.StringVar(frame)
        index_var = tk.StringVar(frame)
        metadata_var = tk.StringVar(frame)
        error_var = tk.StringVar(frame)

        ttk.Label(frame, textvariable=request_var).grid(row=0, column=0, columnspan=2, sticky="w", padx=4, pady=(2, 4))
        ttk.Label(frame, text="Parent").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        parent_combo = ttk.Combobox(frame, textvariable=parent_var, state="readonly")
        parent_combo.grid(row=1, column=1, sticky="ew", padx=4, pady=2)
        ttk.Label(frame, text="Slot").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        slot_combo = ttk.Combobox(frame, textvariable=slot_var, state="readonly")
        slot_combo.grid(row=2, column=1, sticky="ew", padx=4, pady=2)
        ttk.Label(frame, text="Index").grid(row=3, column=0, sticky="w", padx=4, pady=2)
        index_entry = ttk.Entry(frame, textvariable=index_var)
        index_entry.grid(row=3, column=1, sticky="ew", padx=4, pady=2)
        ttk.Label(frame, text="Metadata JSON").grid(row=4, column=0, sticky="w", padx=4, pady=2)
        metadata_entry = ttk.Entry(frame, textvariable=metadata_var)
        metadata_entry.grid(row=4, column=1, sticky="ew", padx=4, pady=2)
        error_label = ttk.Label(frame, textvariable=error_var)
        error_label.grid(row=5, column=0, columnspan=2, sticky="w", padx=4, pady=2)
        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=2, sticky="ew", padx=4, pady=(2, 4))
        commit_button = ttk.Button(buttons, text="Insert", command=on_commit)
        commit_button.pack(side="left", padx=(0, 4))
        cancel_button = ttk.Button(buttons, text="Cancel", command=on_cancel)
        cancel_button.pack(side="left")

        binding = DesignerComponentPlacementBinding(
            panel=frame,
            fields={
                "request_var": request_var,
                "parent_var": parent_var,
                "slot_var": slot_var,
                "index_var": index_var,
                "metadata_var": metadata_var,
                "error_var": error_var,
                "parent": parent_combo,
                "slot": slot_combo,
                "index": index_entry,
                "metadata": metadata_entry,
                "commit": commit_button,
                "cancel": cancel_button,
            },
            metadata={
                "on_parent": on_parent,
                "on_slot": on_slot,
                "on_index": on_index,
                "on_metadata": on_metadata,
                "parent_by_label": {},
                "slot_by_label": {},
                "updating": False,
            },
        )

        def parent_selected(_event=None):
            metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
            if metadata.get("updating"):
                return None
            node_id = str(metadata.get("parent_by_label", {}).get(parent_var.get(), ""))
            return on_parent(node_id) if node_id else None

        def slot_selected(_event=None):
            metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
            if metadata.get("updating"):
                return None
            slot = str(metadata.get("slot_by_label", {}).get(slot_var.get(), ""))
            return on_slot(slot) if slot else None

        def index_changed(_event=None):
            metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
            if not metadata.get("updating"):
                return on_index(index_var.get())
            return None

        def metadata_changed(_event=None):
            metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
            if not metadata.get("updating"):
                return on_metadata(metadata_var.get())
            return None

        parent_combo.bind("<<ComboboxSelected>>", parent_selected, add="+")
        slot_combo.bind("<<ComboboxSelected>>", slot_selected, add="+")
        index_entry.bind("<FocusOut>", index_changed, add="+")
        index_entry.bind("<Return>", index_changed, add="+")
        metadata_entry.bind("<FocusOut>", metadata_changed, add="+")
        metadata_entry.bind("<Return>", metadata_changed, add="+")
        self.update(binding, state)
        return binding

    @staticmethod
    def _set_widget_state(widget, enabled: bool, *, readonly: bool = False):
        try:
            widget.configure(state=("readonly" if enabled and readonly else "normal" if enabled else "disabled"))
        except Exception:
            pass

    def update(
        self,
        binding: DesignerComponentPlacementBinding,
        state: DesignerComponentPlacementState,
    ) -> None:
        fields = binding.fields
        metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
        metadata["updating"] = True
        try:
            request_text = "No pending component request"
            if state.request is not None:
                request_text = f"{state.request.label}  ->  {state.node_id}"
            fields["request_var"].set(request_text)
            parent_labels, parent_by_label, parent_by_id = self._parent_labels(state)
            slot_labels, slot_by_label, slot_by_key = self._slot_labels(state)
            metadata["parent_by_label"] = parent_by_label
            metadata["slot_by_label"] = slot_by_label
            fields["parent"].configure(values=parent_labels)
            fields["slot"].configure(values=slot_labels)
            fields["parent_var"].set(parent_by_id.get(state.parent_id, ""))
            fields["slot_var"].set(slot_by_key.get(state.slot_key, ""))
            fields["index_var"].set(state.index_text)
            fields["metadata_var"].set(state.metadata_text)
            fields["error_var"].set(state.creation_error)
            enabled = state.active and not state.closed
            self._set_widget_state(fields["parent"], enabled, readonly=True)
            self._set_widget_state(fields["slot"], enabled, readonly=True)
            self._set_widget_state(fields["index"], enabled)
            self._set_widget_state(fields["metadata"], enabled)
            fields["commit"].configure(state=("normal" if state.can_commit else "disabled"))
            fields["cancel"].configure(state=("normal" if state.active else "disabled"))
        finally:
            metadata["updating"] = False

    def exists(self, binding: DesignerComponentPlacementBinding) -> bool:
        return self._exists_widget(binding.panel)

    def dispose(self, binding: DesignerComponentPlacementBinding) -> None:
        if self._exists_widget(binding.panel):
            try:
                binding.panel.destroy()
            except Exception:
                pass
        binding.fields.clear()
        if isinstance(binding.metadata, dict):
            binding.metadata.clear()
        binding.title_item = None
