"""Dear PyGui host for the renderer-neutral designer property inspector."""

from __future__ import annotations

from app.framework.designer_inspector import DesignerInspectorEditorKind, DesignerInspectorRow, DesignerInspectorState
from app.framework.designer_inspector_panel import (
    DesignerInspectorPanelBinding,
    format_inspector_editor_value,
    parse_inspector_editor_text,
)


class DearPyGuiDesignerInspectorPanelHost:
    """Render inspector rows as disposable Dear PyGui editor bindings."""

    def __init__(
        self,
        *,
        height: int = 420,
        label_width: int = 118,
        editor_width: int = 170,
    ):
        self.height = max(100, int(height))
        self.label_width = max(72, int(label_width))
        self.editor_width = max(120, int(editor_width))

    @staticmethod
    def _dpg():
        import dearpygui.dearpygui as dpg

        return dpg

    @staticmethod
    def _display_value(row: DesignerInspectorRow) -> str:
        if not row.is_set:
            return "(default)"
        if row.value is None:
            return "None"
        rendered = format_inspector_editor_value(row)
        if isinstance(rendered, bool):
            return "True" if rendered else "False"
        return str(rendered)

    @staticmethod
    def _choice_items(row: DesignerInspectorRow) -> tuple[list[str], dict[str, object]]:
        labels: list[str] = []
        values: dict[str, object] = {}
        for index, choice in enumerate(row.choices):
            base = str(choice)
            label = base
            if label in values:
                label = f"{base} [{index}]"
            labels.append(label)
            values[label] = choice
        return labels, values

    def _populate(
        self,
        binding: DesignerInspectorPanelBinding,
        state: DesignerInspectorState,
    ) -> None:
        dpg = self._dpg()
        metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
        body = metadata.get("body")
        if body is None or not dpg.does_item_exist(body):
            raise RuntimeError("Dear PyGui inspector panel body is unavailable")

        if binding.target_item is not None and dpg.does_item_exist(binding.target_item):
            if state.has_target:
                target = f"{state.type_label}  [{state.node_id}]  •  {state.category}"
            else:
                target = "No selection"
            dpg.set_value(binding.target_item, target)

        dpg.delete_item(body, children_only=True)
        binding.rows.clear()
        metadata["apply_buttons"] = {}
        metadata["clear_buttons"] = {}
        metadata["none_buttons"] = {}
        metadata["choice_values"] = {}

        if not state.has_target:
            dpg.add_text("Select a hierarchy row to inspect its properties.", parent=body)
            return

        on_set = metadata["on_set"]
        on_clear = metadata["on_clear"]
        on_error = metadata["on_error"]

        def commit_text(_sender, app_data, user_data):
            row, node_id = user_data
            try:
                value = parse_inspector_editor_text(row, app_data)
            except Exception as exc:
                return on_error(node_id, row.key, exc)
            return on_set(node_id, row.key, value)

        def apply_text(_sender, _app_data, user_data):
            row, node_id, editor = user_data
            try:
                raw = dpg.get_value(editor)
                value = parse_inspector_editor_text(row, raw)
            except Exception as exc:
                return on_error(node_id, row.key, exc)
            return on_set(node_id, row.key, value)

        def commit_toggle(_sender, app_data, user_data):
            row, node_id = user_data
            return on_set(node_id, row.key, bool(app_data))

        def commit_choice(_sender, app_data, user_data):
            row, node_id, values = user_data
            try:
                value = values[str(app_data)]
            except Exception as exc:
                return on_error(node_id, row.key, exc)
            return on_set(node_id, row.key, value)

        with dpg.table(
            parent=body,
            header_row=False,
            resizable=True,
            policy=dpg.mvTable_SizingStretchProp,
            borders_innerH=True,
            borders_outerH=False,
            borders_innerV=False,
            borders_outerV=False,
        ):
            dpg.add_table_column(init_width_or_weight=float(self.label_width), width_fixed=True)
            dpg.add_table_column(init_width_or_weight=1.0)

            for row in state.rows:
                with dpg.table_row():
                    label = row.label
                    if not row.is_set:
                        label += "  · default"
                    elif row.value is None:
                        label += "  · None"
                    dpg.add_text(label)

                    with dpg.group(horizontal=False):
                        if not row.can_edit:
                            item = dpg.add_text(self._display_value(row))
                        elif row.editor is DesignerInspectorEditorKind.TOGGLE:
                            item = dpg.add_checkbox(
                                default_value=bool(row.value) if row.is_set and row.value is not None else False,
                                user_data=(row, state.node_id),
                                callback=commit_toggle,
                            )
                        elif row.editor is DesignerInspectorEditorKind.CHOICE:
                            choices, values = self._choice_items(row)
                            metadata["choice_values"][row.key] = values
                            current = ""
                            if row.is_set and row.value is not None:
                                current = next((label for label, value in values.items() if value == row.value), "")
                            item = dpg.add_combo(
                                choices,
                                default_value=current,
                                width=self.editor_width,
                                user_data=(row, state.node_id, values),
                                callback=commit_choice,
                            )
                        else:
                            item = dpg.add_input_text(
                                default_value=str(format_inspector_editor_value(row)),
                                width=self.editor_width,
                                on_enter=True,
                                user_data=(row, state.node_id),
                                callback=commit_text,
                            )

                        binding.rows[row.key] = item

                        if row.can_edit and (
                            row.editor not in {
                                DesignerInspectorEditorKind.TOGGLE,
                                DesignerInspectorEditorKind.CHOICE,
                            }
                            or row.nullable
                            or row.can_clear
                        ):
                            with dpg.group(horizontal=True):
                                if row.editor not in {
                                    DesignerInspectorEditorKind.TOGGLE,
                                    DesignerInspectorEditorKind.CHOICE,
                                }:
                                    apply_button = dpg.add_button(
                                        label="Apply",
                                        user_data=(row, state.node_id, item),
                                        callback=apply_text,
                                    )
                                    metadata["apply_buttons"][row.key] = apply_button

                                if row.nullable:
                                    none_button = dpg.add_button(
                                        label="None",
                                        user_data=(state.node_id, row.key),
                                        callback=lambda _s, _a, data: on_set(data[0], data[1], None),
                                    )
                                    metadata["none_buttons"][row.key] = none_button
                                if row.can_clear:
                                    clear_button = dpg.add_button(
                                        label="Default",
                                        user_data=(state.node_id, row.key),
                                        callback=lambda _s, _a, data: on_clear(data[0], data[1]),
                                    )
                                    metadata["clear_buttons"][row.key] = clear_button

    def build(
        self,
        state: DesignerInspectorState,
        *,
        parent: object,
        title: str = "",
        on_set,
        on_clear,
        on_error,
    ) -> DesignerInspectorPanelBinding:
        dpg = self._dpg()
        panel = dpg.add_child_window(parent=parent, border=True, height=self.height)
        title_item = None
        if title:
            title_item = dpg.add_text(str(title), parent=panel)
        target_item = dpg.add_text("", parent=panel)
        dpg.add_separator(parent=panel)
        body = dpg.add_group(parent=panel)
        binding = DesignerInspectorPanelBinding(
            panel=panel,
            rows={},
            title_item=title_item,
            target_item=target_item,
            metadata={
                "body": body,
                "on_set": on_set,
                "on_clear": on_clear,
                "on_error": on_error,
                "apply_buttons": {},
                "clear_buttons": {},
                "none_buttons": {},
                "choice_values": {},
            },
        )
        self._populate(binding, state)
        return binding

    def update(
        self,
        binding: DesignerInspectorPanelBinding,
        state: DesignerInspectorState,
    ) -> None:
        self._populate(binding, state)

    def exists(self, binding: DesignerInspectorPanelBinding) -> bool:
        try:
            return bool(self._dpg().does_item_exist(binding.panel))
        except Exception:
            return False

    def dispose(self, binding: DesignerInspectorPanelBinding) -> None:
        dpg = self._dpg()
        if dpg.does_item_exist(binding.panel):
            dpg.delete_item(binding.panel)
        binding.rows.clear()
        if isinstance(binding.metadata, dict):
            binding.metadata.clear()
        binding.title_item = None
        binding.target_item = None
