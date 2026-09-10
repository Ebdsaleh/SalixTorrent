"""Dear PyGui host for the renderer-neutral designer property inspector."""

from __future__ import annotations

from app.framework.designer_inspector import DesignerInspectorEditorKind, DesignerInspectorRow, DesignerInspectorState
from app.framework.designer_inspector_panel import (
    DesignerInspectorPanelBinding,
    format_inspector_editor_value,
    parse_inspector_editor_text,
)
from app.framework.designer_numeric_drag import (
    DesignerDragModifiers,
    is_scrubbable_row,
    translate_numeric_drag,
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
        metadata["scrub_handles"] = {}
        metadata["scrub_rows"] = {}

        if not state.has_target:
            dpg.add_text("Select a hierarchy row to inspect its properties.", parent=body)
            return

        on_set = metadata["on_set"]
        on_clear = metadata["on_clear"]
        on_error = metadata["on_error"]
        on_reset = metadata["on_reset"]
        on_scrub_base = metadata["on_scrub_base"]

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

        reset_enabled = any(row.can_clear for row in state.rows)
        reset_button = dpg.add_button(
            label="Reset all to defaults",
            parent=body,
            enabled=reset_enabled,
            user_data=state.node_id,
            callback=lambda _s, _a, node_id: on_reset(node_id),
        )
        metadata["reset_button"] = reset_button
        dpg.add_separator(parent=body)

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
                            if is_scrubbable_row(row):
                                with dpg.group(horizontal=True):
                                    item = dpg.add_input_text(
                                        default_value=str(format_inspector_editor_value(row)),
                                        width=max(96, self.editor_width - 34),
                                        on_enter=True,
                                        user_data=(row, state.node_id),
                                        callback=commit_text,
                                    )
                                    scrub = dpg.add_button(label="<>", width=28)
                                    metadata["scrub_handles"][row.key] = scrub
                                    metadata["scrub_rows"][scrub] = (row, state.node_id, item)
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
        on_reset,
        on_scrub_base,
    ) -> DesignerInspectorPanelBinding:
        dpg = self._dpg()
        panel = dpg.add_child_window(parent=parent, border=True, height=self.height)
        handler_registry = dpg.add_handler_registry()
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
                "on_reset": on_reset,
                "on_scrub_base": on_scrub_base,
                "handler_registry": handler_registry,
                "scrub_drag": None,
                "apply_buttons": {},
                "clear_buttons": {},
                "none_buttons": {},
                "choice_values": {},
            },
        )
        def _mouse_x():
            try:
                return float(dpg.get_mouse_pos(local=False)[0])
            except TypeError:
                return float(dpg.get_mouse_pos()[0])

        def _mods():
            def down(name):
                key = getattr(dpg, name, None)
                return bool(key is not None and dpg.is_key_down(key))
            return DesignerDragModifiers(
                shift=down("mvKey_LShift") or down("mvKey_RShift"),
                ctrl=down("mvKey_LControl") or down("mvKey_RControl") or down("mvKey_Control"),
            )

        def scrub_down(_sender=None, _app_data=None, _user_data=None):
            rows = binding.metadata.get("scrub_rows", {})
            for handle, data in list(rows.items()):
                try:
                    hovered = dpg.does_item_exist(handle) and dpg.is_item_hovered(handle)
                except Exception:
                    hovered = False
                if not hovered:
                    continue
                row, node_id, editor = data
                try:
                    base = float(on_scrub_base(node_id, row.key))
                except Exception as exc:
                    on_error(node_id, row.key, exc)
                    return
                binding.metadata["scrub_drag"] = {
                    "row": row, "node_id": node_id, "editor": editor,
                    "start_x": _mouse_x(), "base": base, "value": base,
                }
                return

        def scrub_move(_sender=None, _app_data=None, _user_data=None):
            drag = binding.metadata.get("scrub_drag")
            if not isinstance(drag, dict):
                return
            row = drag["row"]
            value = translate_numeric_drag(row, drag["base"], _mouse_x() - drag["start_x"], _mods())
            drag["value"] = value
            text = str(int(value)) if isinstance(value, int) else f"{float(value):g}"
            try:
                if dpg.does_item_exist(drag["editor"]):
                    dpg.set_value(drag["editor"], text)
            except Exception:
                pass

        def scrub_release(_sender=None, _app_data=None, _user_data=None):
            drag = binding.metadata.get("scrub_drag")
            binding.metadata["scrub_drag"] = None
            if not isinstance(drag, dict):
                return
            try:
                on_set(drag["node_id"], drag["row"].key, drag["value"])
            except Exception as exc:
                on_error(drag["node_id"], drag["row"].key, exc)

        dpg.add_mouse_down_handler(button=dpg.mvMouseButton_Left, callback=scrub_down, parent=handler_registry)
        dpg.add_mouse_move_handler(callback=scrub_move, parent=handler_registry)
        dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Left, callback=scrub_release, parent=handler_registry)

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
        if isinstance(binding.metadata, dict):
            registry = binding.metadata.get("handler_registry")
            if registry is not None and dpg.does_item_exist(registry):
                dpg.delete_item(registry)
        binding.rows.clear()
        if isinstance(binding.metadata, dict):
            binding.metadata.clear()
        binding.title_item = None
        binding.target_item = None
