"""Dear PyGui host for the backend-neutral designer component placement surface."""

from __future__ import annotations

from app.framework.designer_component_placement import (
    DesignerComponentPlacementBinding,
    DesignerComponentPlacementState,
)


class DearPyGuiDesignerComponentPlacementHost:
    """Render one explicit placement form without owning insertion semantics."""

    def __init__(self, *, height: int = 215):
        self.height = max(170, int(height))

    @staticmethod
    def _dpg():
        import dearpygui.dearpygui as dpg

        return dpg

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
        dpg = self._dpg()
        panel = dpg.add_child_window(parent=parent, border=True, height=self.height)
        title_item = dpg.add_text(str(title or "Placement"), parent=panel)
        dpg.add_separator(parent=panel)
        request_item = dpg.add_text("No pending component request", parent=panel, wrap=0)
        parent_combo = dpg.add_combo(parent=panel, label="Parent", width=-1)
        slot_combo = dpg.add_combo(parent=panel, label="Slot", width=-1)
        index_input = dpg.add_input_text(parent=panel, label="Index", width=-1, hint="blank = append")
        metadata_input = dpg.add_input_text(parent=panel, label="Metadata JSON", width=-1)
        error_item = dpg.add_text("", parent=panel, wrap=0)
        with dpg.group(parent=panel, horizontal=True):
            commit_button = dpg.add_button(label="Insert", width=90)
            cancel_button = dpg.add_button(label="Cancel", width=90)

        binding = DesignerComponentPlacementBinding(
            panel=panel,
            title_item=title_item,
            fields={
                "request": request_item,
                "parent": parent_combo,
                "slot": slot_combo,
                "index": index_input,
                "metadata": metadata_input,
                "error": error_item,
                "commit": commit_button,
                "cancel": cancel_button,
            },
            metadata={
                "on_parent": on_parent,
                "on_slot": on_slot,
                "on_index": on_index,
                "on_metadata": on_metadata,
                "on_commit": on_commit,
                "on_cancel": on_cancel,
                "parent_by_label": {},
                "slot_by_label": {},
                "updating": False,
            },
        )

        dpg.configure_item(parent_combo, callback=lambda _s, value, _u: self._dispatch_parent(binding, value))
        dpg.configure_item(slot_combo, callback=lambda _s, value, _u: self._dispatch_slot(binding, value))
        dpg.configure_item(index_input, callback=lambda _s, value, _u: self._dispatch_value(binding, "on_index", value))
        dpg.configure_item(metadata_input, callback=lambda _s, value, _u: self._dispatch_value(binding, "on_metadata", value))
        dpg.configure_item(commit_button, callback=lambda _s, _a, _u: on_commit())
        dpg.configure_item(cancel_button, callback=lambda _s, _a, _u: on_cancel())
        self.update(binding, state)
        return binding

    def _metadata(self, binding):
        return binding.metadata if isinstance(binding.metadata, dict) else {}

    def _dispatch_parent(self, binding, label):
        metadata = self._metadata(binding)
        if metadata.get("updating"):
            return None
        node_id = str(metadata.get("parent_by_label", {}).get(str(label), ""))
        if node_id:
            return metadata["on_parent"](node_id)
        return None

    def _dispatch_slot(self, binding, label):
        metadata = self._metadata(binding)
        if metadata.get("updating"):
            return None
        slot = str(metadata.get("slot_by_label", {}).get(str(label), ""))
        if slot:
            return metadata["on_slot"](slot)
        return None

    def _dispatch_value(self, binding, key, value):
        metadata = self._metadata(binding)
        if metadata.get("updating"):
            return None
        return metadata[key](value)

    def update(
        self,
        binding: DesignerComponentPlacementBinding,
        state: DesignerComponentPlacementState,
    ) -> None:
        dpg = self._dpg()
        fields = binding.fields
        metadata = self._metadata(binding)
        metadata["updating"] = True
        try:
            request_text = "No pending component request"
            if state.request is not None:
                request_text = f"{state.request.label}  ->  {state.node_id}"
            dpg.set_value(fields["request"], request_text)

            parent_labels, parent_by_label, parent_by_id = self._parent_labels(state)
            slot_labels, slot_by_label, slot_by_key = self._slot_labels(state)
            metadata["parent_by_label"] = parent_by_label
            metadata["slot_by_label"] = slot_by_label
            dpg.configure_item(fields["parent"], items=parent_labels, enabled=state.active and not state.closed)
            dpg.configure_item(fields["slot"], items=slot_labels, enabled=state.active and not state.closed)
            dpg.set_value(fields["parent"], parent_by_id.get(state.parent_id, ""))
            dpg.set_value(fields["slot"], slot_by_key.get(state.slot_key, ""))
            dpg.set_value(fields["index"], state.index_text)
            dpg.set_value(fields["metadata"], state.metadata_text)
            dpg.configure_item(fields["index"], enabled=state.active and not state.closed)
            dpg.configure_item(fields["metadata"], enabled=state.active and not state.closed)
            dpg.configure_item(fields["commit"], enabled=state.can_commit)
            dpg.configure_item(fields["cancel"], enabled=state.active)
            dpg.set_value(fields["error"], state.creation_error)
        finally:
            metadata["updating"] = False

    def exists(self, binding: DesignerComponentPlacementBinding) -> bool:
        try:
            return bool(self._dpg().does_item_exist(binding.panel))
        except Exception:
            return False

    def dispose(self, binding: DesignerComponentPlacementBinding) -> None:
        dpg = self._dpg()
        if dpg.does_item_exist(binding.panel):
            dpg.delete_item(binding.panel)
        binding.fields.clear()
        if isinstance(binding.metadata, dict):
            binding.metadata.clear()
        binding.title_item = None
