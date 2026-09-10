"""Tkinter host for the renderer-neutral designer property inspector."""

from __future__ import annotations

from app.engine.component_renderers.tkinter import TkinterRenderer
from app.framework.designer_inspector import DesignerInspectorEditorKind, DesignerInspectorRow, DesignerInspectorState
from app.framework.designer_inspector_panel import (
    DesignerInspectorPanelBinding,
    format_inspector_editor_value,
    parse_inspector_editor_text,
)


class TkinterDesignerInspectorPanelHost:
    """Render inspector rows through ttk widgets without owning semantics."""

    def __init__(self, renderer: TkinterRenderer, *, height: int = 360):
        if not isinstance(renderer, TkinterRenderer):
            raise TypeError("TkinterDesignerInspectorPanelHost requires a TkinterRenderer")
        self.renderer = renderer
        self.height = max(120, int(height))

    @staticmethod
    def _exists_widget(widget) -> bool:
        try:
            return bool(int(widget.winfo_exists()))
        except Exception:
            return False

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
            label = base if base not in values else f"{base} [{index}]"
            labels.append(label)
            values[label] = choice
        return labels, values

    def _populate(
        self,
        binding: DesignerInspectorPanelBinding,
        state: DesignerInspectorState,
    ) -> None:
        import tkinter as tk
        from tkinter import ttk

        metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
        inner = metadata.get("inner")
        canvas = metadata.get("canvas")
        window = metadata.get("window")
        target_var = metadata.get("target_var")
        if inner is None or not self._exists_widget(inner):
            raise RuntimeError("Tkinter inspector panel body is unavailable")

        def stabilize_geometry():
            # Inspector refresh destroys/recreates the grid while the canvas itself
            # often keeps the same size, so <Configure> is not guaranteed to fire.
            # Reassert the canvas-window width after the callback returns; otherwise
            # a row of empty/default editors can temporarily collapse the stretch
            # column to a few pixels until some unrelated geometry event occurs.
            if canvas is None or window is None:
                return
            try:
                if not self._exists_widget(canvas):
                    return
                width = max(1, int(canvas.winfo_width()))
                canvas.itemconfigure(window, width=width)
                region = canvas.bbox("all")
                if region is not None:
                    canvas.configure(scrollregion=region)
            except Exception:
                pass

        def schedule_geometry_stabilization():
            try:
                self.renderer.root.after_idle(stabilize_geometry)
            except Exception:
                pass

        if target_var is not None:
            if state.has_target:
                target_var.set(f"{state.type_label}  [{state.node_id}]  •  {state.category}")
            else:
                target_var.set("No selection")

        for child in tuple(inner.winfo_children()):
            child.destroy()
        binding.rows.clear()
        metadata["variables"] = {}
        metadata["apply_buttons"] = {}
        metadata["clear_buttons"] = {}
        metadata["none_buttons"] = {}
        metadata["choice_values"] = {}

        if not state.has_target:
            ttk.Label(inner, text="Select a hierarchy row to inspect its properties.").grid(
                row=0, column=0, columnspan=3, sticky="w", padx=4, pady=6
            )
            schedule_geometry_stabilization()
            return

        on_set = metadata["on_set"]
        on_clear = metadata["on_clear"]
        on_error = metadata["on_error"]

        def defer(callback):
            self.renderer.root.after_idle(callback)

        def commit_text(row: DesignerInspectorRow, node_id: str, variable):
            def perform():
                try:
                    value = parse_inspector_editor_text(row, variable.get())
                except Exception as exc:
                    on_error(node_id, row.key, exc)
                    return
                on_set(node_id, row.key, value)

            defer(perform)

        def commit_toggle(row: DesignerInspectorRow, node_id: str, variable):
            defer(lambda: on_set(node_id, row.key, bool(variable.get())))

        def commit_choice(row: DesignerInspectorRow, node_id: str, variable, values):
            def perform():
                try:
                    value = values[str(variable.get())]
                except Exception as exc:
                    on_error(node_id, row.key, exc)
                    return
                on_set(node_id, row.key, value)

            defer(perform)

        # Keep the editor column useful even in a narrow inspector, but put
        # actions on a second row instead of a third horizontal column.  The
        # earlier three-column form could place Apply/None/Default beyond the
        # visible canvas width even though the editor itself was correctly
        # stabilized after refresh.
        inner.columnconfigure(0, minsize=92)
        inner.columnconfigure(1, weight=1, minsize=140)
        for index, row in enumerate(state.rows):
            field_row = index * 2
            action_row = field_row + 1
            label = row.label
            if not row.is_set:
                label += "  · default"
            elif row.value is None:
                label += "  · None"
            ttk.Label(inner, text=label).grid(
                row=field_row, column=0, sticky="nw", padx=(4, 8), pady=(3, 1)
            )

            actions = ttk.Frame(inner)
            has_actions = False

            if not row.can_edit:
                item = ttk.Label(inner, text=self._display_value(row))
                item.grid(row=field_row, column=1, sticky="ew", pady=(3, 1))
            elif row.editor is DesignerInspectorEditorKind.TOGGLE:
                variable = tk.BooleanVar(
                    value=bool(row.value) if row.is_set and row.value is not None else False
                )
                item = ttk.Checkbutton(
                    inner,
                    variable=variable,
                    command=lambda r=row, n=state.node_id, v=variable: commit_toggle(r, n, v),
                )
                item.grid(row=field_row, column=1, sticky="w", pady=(3, 1))
                metadata["variables"][row.key] = variable
            elif row.editor is DesignerInspectorEditorKind.CHOICE:
                choices, values = self._choice_items(row)
                metadata["choice_values"][row.key] = values
                current = ""
                if row.is_set and row.value is not None:
                    current = next((label for label, value in values.items() if value == row.value), "")
                variable = tk.StringVar(value=current)
                item = ttk.Combobox(inner, textvariable=variable, values=choices, state="readonly")
                item.grid(row=field_row, column=1, sticky="ew", pady=(3, 1))
                item.bind(
                    "<<ComboboxSelected>>",
                    lambda _event, r=row, n=state.node_id, v=variable, vals=values: commit_choice(r, n, v, vals),
                    add="+",
                )
                metadata["variables"][row.key] = variable
            else:
                variable = tk.StringVar(value=str(format_inspector_editor_value(row)))
                item = ttk.Entry(inner, textvariable=variable)
                item.grid(row=field_row, column=1, sticky="ew", pady=(3, 1))
                item.bind(
                    "<Return>",
                    lambda _event, r=row, n=state.node_id, v=variable: commit_text(r, n, v),
                    add="+",
                )
                apply_button = ttk.Button(
                    actions,
                    text="Apply",
                    command=lambda r=row, n=state.node_id, v=variable: commit_text(r, n, v),
                )
                apply_button.pack(side="left", padx=(0, 3))
                metadata["apply_buttons"][row.key] = apply_button
                metadata["variables"][row.key] = variable
                has_actions = True

            binding.rows[row.key] = item

            if row.nullable and row.can_edit:
                none_button = ttk.Button(
                    actions,
                    text="None",
                    command=lambda n=state.node_id, key=row.key: defer(lambda: on_set(n, key, None)),
                )
                none_button.pack(side="left", padx=(0, 3))
                metadata["none_buttons"][row.key] = none_button
                has_actions = True
            if row.can_clear:
                clear_button = ttk.Button(
                    actions,
                    text="Default",
                    command=lambda n=state.node_id, key=row.key: defer(lambda: on_clear(n, key)),
                )
                clear_button.pack(side="left")
                metadata["clear_buttons"][row.key] = clear_button
                has_actions = True

            if has_actions:
                actions.grid(
                    row=action_row,
                    column=1,
                    sticky="w",
                    padx=(0, 4),
                    pady=(0, 3),
                )
            else:
                actions.destroy()

        # Reassert width asynchronously after every rebuild. Do not force a
        # nested update_idletasks() here: refresh can run from a deferred native
        # event callback, and recursively draining Tk's idle queue from inside
        # that callback can starve the outer loop.
        schedule_geometry_stabilization()

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
        import tkinter as tk
        from tkinter import ttk

        parent_widget = self.renderer.content_widget(parent)
        if parent_widget is None:
            raise RuntimeError("Tkinter inspector panel parent has no widget")

        frame = ttk.LabelFrame(parent_widget, text=str(title or "Inspector"))
        frame.pack(fill="both", expand=True)
        target_var = tk.StringVar(value="")
        target = ttk.Label(frame, textvariable=target_var)
        target.pack(fill="x", padx=4, pady=(4, 2))

        body = ttk.Frame(frame, height=self.height)
        body.pack(fill="both", expand=True)
        body.pack_propagate(False)
        canvas = tk.Canvas(body, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def resize_inner(event):
            try:
                canvas.itemconfigure(window, width=max(1, int(event.width)))
            except Exception:
                pass

        def update_scroll(_event=None):
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
            except Exception:
                pass

        canvas.bind("<Configure>", resize_inner, add="+")
        inner.bind("<Configure>", update_scroll, add="+")

        binding = DesignerInspectorPanelBinding(
            panel=frame,
            rows={},
            target_item=target,
            metadata={
                "body": body,
                "canvas": canvas,
                "scrollbar": scrollbar,
                "inner": inner,
                "window": window,
                "target_var": target_var,
                "on_set": on_set,
                "on_clear": on_clear,
                "on_error": on_error,
                "variables": {},
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
        return self._exists_widget(binding.panel)

    def dispose(self, binding: DesignerInspectorPanelBinding) -> None:
        if self._exists_widget(binding.panel):
            try:
                binding.panel.destroy()
            except Exception:
                pass
        binding.rows.clear()
        if isinstance(binding.metadata, dict):
            binding.metadata.clear()
        binding.title_item = None
        binding.target_item = None
