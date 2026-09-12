"""Tkinter renderer adapter for the reusable component framework.

Tkinter is the compatibility/reference implementation for the common desktop
surface.  The renderer translates the same semantic component contract used by
Dear PyGui without requiring application views to branch on toolkit identity.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Callable, Iterator

from app.framework.components.events import ComponentEvent, ComponentEventType
from app.framework.components.profile import ComponentLayoutProfile, FRAMEWORK_COMPONENT_PROFILE


@dataclass(eq=False)
class _TkItem:
    widget: object | None
    kind: str
    mount: object | None = None
    value_var: object | None = None
    geometry_manager: str | None = None
    geometry_options: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    alive: bool = True


@dataclass(eq=False)
class _TkVirtualItem:
    kind: str
    alive: bool = True


@dataclass
class _ContainerState:
    kind: str
    item: _TkItem | _TkVirtualItem
    widget: object
    row: int = 0
    column: int = 0
    horizontal_spacing: int = 0
    cross_axis: str = "natural"


class _TkTooltip:
    def __init__(self, root, widget, text: str, wrap: int):
        self.root = root
        self.widget = widget
        self.text = str(text)
        self.wrap = max(1, int(wrap))
        self.window = None
        self._enter_binding = widget.bind("<Enter>", self._show, add="+")
        self._leave_binding = widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event=None):
        if self.window is not None:
            return
        try:
            import tkinter as tk

            window = tk.Toplevel(self.root)
            window.wm_overrideredirect(True)
            window.attributes("-topmost", True)
            x = int(self.widget.winfo_rootx()) + 12
            y = int(self.widget.winfo_rooty()) + int(self.widget.winfo_height()) + 8
            window.geometry(f"+{x}+{y}")
            label = tk.Label(
                window,
                text=self.text,
                justify="left",
                relief="solid",
                borderwidth=1,
                padx=6,
                pady=4,
                wraplength=self.wrap,
            )
            label.pack()
            self.window = window
        except Exception:
            self.window = None

    def _hide(self, _event=None):
        window = self.window
        self.window = None
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass

    def destroy(self):
        self._hide()
        try:
            if self._enter_binding:
                self.widget.unbind("<Enter>", self._enter_binding)
            if self._leave_binding:
                self.widget.unbind("<Leave>", self._leave_binding)
        except Exception:
            pass


class TkinterRenderer:
    """Tkinter implementation of the reusable ``ComponentRenderer`` contract."""

    def __init__(
        self,
        root,
        *,
        component_profile: ComponentLayoutProfile | None = None,
    ):
        if root is None:
            raise ValueError("TkinterRenderer requires a Tk root or container")
        self.root = root
        self.component_profile = component_profile or FRAMEWORK_COMPONENT_PROFILE
        self._stack: list[_ContainerState] = []
        self._tooltips: list[_TkTooltip] = []
        self._value_items: list[_TkItem] = []
        self._closed = False

    @staticmethod
    def _modules():
        import tkinter as tk
        from tkinter import ttk

        return tk, ttk

    @property
    def closed(self) -> bool:
        return bool(self._closed)

    def close(self) -> None:
        """Release Python-side Tcl/Tk references on the Tk owner thread.

        Tk variables can participate in callback/object cycles.  If those
        cycles survive until a background worker happens to trigger garbage
        collection, CPython may finalize ``tkinter.Variable`` objects on that
        worker and Tcl aborts with ``Tcl_AsyncDelete: async handler deleted by
        the wrong thread``.  Application hosts and tests therefore call this
        hook on the Tk owner thread before destroying the root.

        The renderer does not destroy the root itself; root ownership remains
        with the composition host/caller.
        """
        if self._closed:
            return
        self._closed = True

        for tooltip in reversed(self._tooltips):
            try:
                tooltip.destroy()
            except Exception:
                pass
        self._tooltips.clear()
        self._stack.clear()

        # Drop Python Variable references while Tcl is still owned by this
        # thread.  Widget destruction/root teardown can then release any
        # remaining callback references deterministically on the same thread.
        for item in self._value_items:
            item.value_var = None
        self._value_items.clear()

    def set_component_profile(self, profile: ComponentLayoutProfile) -> None:
        if not isinstance(profile, ComponentLayoutProfile):
            raise TypeError("component profile must be a ComponentLayoutProfile")
        self.component_profile = profile

    @staticmethod
    def _clean_kwargs(kwargs: dict) -> dict:
        return {key: value for key, value in kwargs.items() if value is not None}

    @staticmethod
    def _colour(value):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        try:
            parts = tuple(int(part) for part in value)
        except (TypeError, ValueError):
            return None
        if len(parts) < 3:
            return None
        r, g, b = (max(0, min(255, part)) for part in parts[:3])
        return f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def _widget_exists(widget) -> bool:
        if widget is None:
            return False
        try:
            return bool(int(widget.winfo_exists()))
        except Exception:
            return False

    def native_widget(self, item: object):
        """Return the toolkit widget for a concrete Tkinter backend handle."""
        if isinstance(item, _TkItem):
            return item.widget
        return item

    def content_widget(self, item: object):
        """Return the widget that should parent backend-specific child content."""
        if isinstance(item, _TkItem):
            return item.widget
        return item

    def _parent_widget(self, parent: object | None = None):
        if parent is not None:
            widget = self.content_widget(parent)
            if widget is None:
                raise RuntimeError("Tkinter parent handle has no widget")
            return widget
        if self._stack:
            return self._stack[-1].widget
        return self.root

    def _new_mount(self, parent, *, width=None, height=None):
        tk, _ = self._modules()
        mount = tk.Frame(parent, borderwidth=0, highlightthickness=0)
        fixed = False
        if isinstance(width, (int, float)) and width > 0:
            mount.configure(width=max(1, int(width)))
            fixed = True
        if isinstance(height, (int, float)) and height > 0:
            mount.configure(height=max(1, int(height)))
            fixed = True
        if fixed:
            mount.pack_propagate(False)
            mount.grid_propagate(False)
        return mount

    def _remember_and_apply_geometry(
        self,
        item: _TkItem,
        *,
        width=None,
        height=None,
        parent_explicit: bool = False,
        show: bool = True,
    ) -> None:
        mount = item.mount or item.widget
        if mount is None:
            return

        state = self._stack[-1] if self._stack else None
        fill_x = width == -1
        fill_y = height == -1

        if state is not None and state.kind == "grid_row" and not parent_explicit:
            options = {
                "row": state.row,
                "column": state.column,
                "sticky": "nsew" if fill_y else "ew",
                "padx": (state.horizontal_spacing // 2) if state.horizontal_spacing else 1,
                "pady": 1,
            }
            state.column += 1
            item.geometry_manager = "grid"
            item.geometry_options = options
            if show:
                mount.grid(**options)
            return

        if (
            item.kind == "split_pane"
            and state is not None
            and state.kind in {"row", "column"}
            and not parent_explicit
        ):
            options = {
                "side": "left" if state.kind == "row" else "top",
                "fill": "both",
                "expand": False,
            }
            if state.kind == "row" and state.horizontal_spacing:
                gap = max(0, int(state.horizontal_spacing))
                options["padx"] = (0, gap)
            item.geometry_manager = "pack"
            item.geometry_options = options
            if show:
                mount.pack(**options)
            return

        side = "left" if state is not None and state.kind == "row" and not parent_explicit else "top"
        options = {"side": side}

        if state is not None and state.kind == "column" and not parent_explicit:
            # A column owns vertical flow only.  Cross-axis stretching is now an
            # explicit container policy instead of an implicit side effect of
            # the widest sibling.  Explicit FILL still wins on either axis.
            stretch_x = fill_x or state.cross_axis == "stretch"
            if fill_y:
                options.update(
                    fill="both" if stretch_x else "y",
                    expand=True,
                    anchor="w",
                )
            elif stretch_x:
                options.update(fill="x", expand=False, anchor="w")
            else:
                options.update(anchor="w")
        elif state is not None and state.kind == "row" and not parent_explicit:
            # A row owns horizontal flow only.  Natural child heights stay
            # autonomous unless the parent explicitly requests cross-axis
            # stretching or the child explicitly asks for FILL height.
            stretch_y = fill_y or state.cross_axis == "stretch"
            if fill_x:
                options.update(
                    fill="both" if stretch_y else "x",
                    expand=True,
                    anchor="n",
                )
            elif stretch_y:
                options.update(fill="y", expand=False, anchor="n")
            else:
                options.update(anchor="n")
        elif fill_x and fill_y:
            options.update(fill="both", expand=True)
        elif fill_x:
            options.update(fill="x", expand=True)
        elif fill_y:
            options.update(fill="y", expand=True)
        elif state is not None and state.kind == "panel":
            options.update(fill="x")

        if state is not None and state.kind == "row" and state.horizontal_spacing:
            gap = max(0, int(state.horizontal_spacing))
            options["padx"] = (0, gap)

        item.geometry_manager = "pack"
        item.geometry_options = options
        if show:
            mount.pack(**options)

    def _wrap_widget(
        self,
        widget,
        *,
        kind: str,
        parent,
        width=None,
        height=None,
        show: bool = True,
        value_var=None,
        extra=None,
        mount=None,
        parent_explicit: bool = False,
    ) -> _TkItem:
        if mount is None:
            mount = self._new_mount(parent, width=width, height=height)
        if widget is not mount:
            widget.pack(fill="both", expand=True)
        item = _TkItem(
            widget=widget,
            kind=kind,
            mount=mount,
            value_var=value_var,
            extra=dict(extra or {}),
        )
        if value_var is not None:
            self._value_items.append(item)
        self._remember_and_apply_geometry(
            item,
            width=width,
            height=height,
            parent_explicit=parent_explicit,
            show=bool(show),
        )
        return item

    def _dispatch_change(self, callback, getter):
        if callback is None:
            return None

        def dispatch(_event=None):
            try:
                value = getter()
            except Exception:
                value = None
            return callback(value)

        return dispatch

    def create(self, kind: str, **kwargs) -> object:
        tk, ttk = self._modules()
        kwargs = self._clean_kwargs(dict(kwargs))
        parent_arg = kwargs.pop("parent", None)
        parent = self._parent_widget(parent_arg)
        parent_explicit = parent_arg is not None
        width = kwargs.pop("width", None)
        height = kwargs.pop("height", None)
        show = bool(kwargs.pop("show", True))

        if kind == "grid_column":
            state = self._stack[-1] if self._stack else None
            if state is None or state.kind != "grid":
                raise RuntimeError("Tkinter grid_column requires an active grid container")
            index = state.column
            state.column += 1
            fixed_width = kwargs.get("init_width_or_weight")
            try:
                if fixed_width is not None:
                    state.widget.grid_columnconfigure(index, minsize=max(1, int(fixed_width)))
                else:
                    state.widget.grid_columnconfigure(index, weight=1)
            except Exception:
                pass
            return _TkVirtualItem("grid_column")

        if kind == "label":
            text = str(kwargs.pop("text", ""))
            if kwargs.pop("bullet", False):
                text = f"• {text}"
            label_options = {"text": text, "anchor": "w", "justify": "left"}
            colour = self._colour(kwargs.pop("color", None))
            if colour:
                label_options["fg"] = colour
            wrap = kwargs.pop("wrap", None)
            if wrap:
                label_options["wraplength"] = max(1, int(wrap))
            mount = self._new_mount(parent, width=width, height=height)
            widget = tk.Label(mount, **label_options)
            return self._wrap_widget(
                widget,
                kind=kind,
                parent=parent,
                width=width,
                height=height,
                show=show,
                mount=mount,
                parent_explicit=parent_explicit,
            )

        if kind == "button":
            enabled = bool(kwargs.pop("enabled", True))
            mount = self._new_mount(parent, width=width, height=height)
            widget = ttk.Button(
                mount,
                text=str(kwargs.pop("label", "")),
                command=kwargs.pop("callback", None),
            )
            if not enabled:
                widget.state(["disabled"])
            return self._wrap_widget(
                widget,
                kind=kind,
                parent=parent,
                width=width,
                height=height,
                show=show,
                mount=mount,
                parent_explicit=parent_explicit,
            )

        if kind == "combo_box":
            value = kwargs.pop("default_value", None)
            var = tk.StringVar(master=self.root, value="" if value is None else str(value))
            enabled = bool(kwargs.pop("enabled", True))
            mount = self._new_mount(parent, width=width, height=height)
            widget = ttk.Combobox(
                mount,
                textvariable=var,
                values=tuple(kwargs.pop("items", ())),
                state="readonly" if enabled else "disabled",
            )
            callback = self._dispatch_change(kwargs.pop("callback", None), var.get)
            if callback is not None:
                widget.bind("<<ComboboxSelected>>", callback, add="+")
            return self._wrap_widget(
                widget,
                kind=kind,
                parent=parent,
                width=width,
                height=height,
                show=show,
                value_var=var,
                extra={"enabled_state": "readonly"},
                mount=mount,
                parent_explicit=parent_explicit,
            )

        if kind == "text_input":
            label_text = kwargs.pop("label", None)
            default_value = str(kwargs.pop("default_value", ""))
            multiline = bool(kwargs.pop("multiline", False))
            readonly = bool(kwargs.pop("readonly", False))
            enabled = bool(kwargs.pop("enabled", True))
            hint = kwargs.pop("hint", None)
            callback_raw = kwargs.pop("callback", None)

            mount = self._new_mount(parent, width=width, height=height)
            if label_text:
                tk.Label(mount, text=str(label_text), anchor="w").pack(side="left")

            if multiline:
                widget = tk.Text(mount, wrap="word")
                widget.insert("1.0", default_value)
                getter = lambda: widget.get("1.0", "end-1c")
                callback = self._dispatch_change(callback_raw, getter)
                if callback is not None:
                    widget.bind("<KeyRelease>", callback, add="+")
                if readonly or not enabled:
                    widget.configure(state="disabled")
                value_var = None
            else:
                var = tk.StringVar(master=self.root, value=default_value)
                widget = ttk.Entry(mount, textvariable=var)
                getter = var.get
                callback = self._dispatch_change(callback_raw, getter)
                if callback is not None:
                    widget.bind("<KeyRelease>", callback, add="+")
                if readonly or not enabled:
                    widget.state(["disabled"])
                value_var = var
                if hint:
                    try:
                        widget.configure(takefocus=True)
                    except Exception:
                        pass

            widget.pack(side="left", fill="both", expand=True)
            item = _TkItem(
                widget=widget,
                kind=kind,
                mount=mount,
                value_var=value_var,
                extra={"multiline": multiline, "readonly": readonly, "hint": hint},
            )
            if value_var is not None:
                self._value_items.append(item)
            self._remember_and_apply_geometry(
                item,
                width=width,
                height=height,
                parent_explicit=parent_explicit,
                show=show,
            )
            return item

        if kind in {"numeric_int", "numeric_float"}:
            is_int = kind == "numeric_int"
            default = kwargs.pop("default_value", 0)
            variable_type = tk.IntVar if is_int else tk.DoubleVar
            var = variable_type(master=self.root, value=default)
            min_value = kwargs.pop("min_value", None)
            max_value = kwargs.pop("max_value", None)
            min_clamped = bool(kwargs.pop("min_clamped", False))
            max_clamped = bool(kwargs.pop("max_clamped", False))
            step = kwargs.pop("step", 1 if is_int else 0.1)
            if step in (None, 0):
                step = 1 if is_int else 0.1
            lower = min_value if min_clamped and min_value is not None else (-2147483648 if is_int else -1.0e100)
            upper = max_value if max_clamped and max_value is not None else (2147483647 if is_int else 1.0e100)
            enabled = bool(kwargs.pop("enabled", True))
            mount = self._new_mount(parent, width=width, height=height)
            widget = ttk.Spinbox(
                mount,
                from_=lower,
                to=upper,
                increment=step,
                textvariable=var,
            )
            callback = self._dispatch_change(kwargs.pop("callback", None), var.get)
            if callback is not None:
                widget.configure(command=callback)
                widget.bind("<KeyRelease>", callback, add="+")
                widget.bind("<FocusOut>", callback, add="+")
            if not enabled:
                widget.state(["disabled"])
            return self._wrap_widget(
                widget,
                kind=kind,
                parent=parent,
                width=width,
                height=height,
                show=show,
                value_var=var,
                extra={"integer": is_int},
                mount=mount,
                parent_explicit=parent_explicit,
            )

        if kind == "checkbox":
            var = tk.BooleanVar(master=self.root, value=bool(kwargs.pop("default_value", False)))
            callback_raw = kwargs.pop("callback", None)
            callback = None
            if callback_raw is not None:
                callback = lambda: callback_raw(bool(var.get()))
            mount = self._new_mount(parent, width=width, height=height)
            widget = ttk.Checkbutton(
                mount,
                text=str(kwargs.pop("label", "")),
                variable=var,
                command=callback,
            )
            if not bool(kwargs.pop("enabled", True)):
                widget.state(["disabled"])
            return self._wrap_widget(
                widget,
                kind=kind,
                parent=parent,
                width=width,
                height=height,
                show=show,
                value_var=var,
                mount=mount,
                parent_explicit=parent_explicit,
            )

        if kind == "spacer":
            widget = tk.Frame(parent, borderwidth=0, highlightthickness=0)
            item = _TkItem(widget=widget, kind=kind, mount=widget)
            if isinstance(width, (int, float)) and width > 0:
                widget.configure(width=int(width))
            if isinstance(height, (int, float)) and height > 0:
                widget.configure(height=int(height))
            self._remember_and_apply_geometry(
                item,
                width=width,
                height=height,
                parent_explicit=parent_explicit,
                show=show,
            )
            return item

        if kind == "separator":
            mount = self._new_mount(parent, width=width, height=height)
            widget = ttk.Separator(mount, orient="horizontal")
            return self._wrap_widget(
                widget,
                kind=kind,
                parent=parent,
                width=width,
                height=height,
                show=show,
                mount=mount,
                parent_explicit=parent_explicit,
            )

        if kind == "progress_bar":
            var = tk.DoubleVar(master=self.root, value=float(kwargs.pop("default_value", 0.0)))
            mount = self._new_mount(parent, width=width, height=height)
            widget = ttk.Progressbar(mount, variable=var, maximum=1.0)
            widget.pack(fill="both", expand=True)
            overlay_text = kwargs.pop("overlay", None)
            overlay_widget = tk.Label(mount, text="" if overlay_text is None else str(overlay_text))
            if overlay_text:
                overlay_widget.place(relx=0.5, rely=0.5, anchor="center")
            item = _TkItem(
                widget=widget,
                kind=kind,
                mount=mount,
                value_var=var,
                extra={"overlay_widget": overlay_widget},
            )
            self._value_items.append(item)
            self._remember_and_apply_geometry(
                item,
                width=width,
                height=height,
                parent_explicit=parent_explicit,
                show=show,
            )
            return item

        raise ValueError(f"unsupported GUI component kind: {kind!r}")

    @contextmanager
    def container(self, kind: str, **kwargs) -> Iterator[object]:
        tk, ttk = self._modules()
        kwargs = self._clean_kwargs(dict(kwargs))
        parent_arg = kwargs.pop("parent", None)
        parent = self._parent_widget(parent_arg)
        parent_explicit = parent_arg is not None
        width = kwargs.pop("width", None)
        height = kwargs.pop("height", None)

        if kind == "tabs":
            callback = kwargs.pop("callback", None)
            mount = self._new_mount(parent, width=width, height=height)
            widget = ttk.Notebook(mount)
            widget.pack(fill="both", expand=True)
            item = _TkItem(
                widget=widget,
                kind=kind,
                mount=mount,
                extra={"pages": {}, "suppress_change": False},
            )
            self._remember_and_apply_geometry(
                item,
                width=width,
                height=height,
                parent_explicit=parent_explicit,
                show=True,
            )
            if callback is not None:
                def _tab_changed(_event=None):
                    if item.extra.get("suppress_change"):
                        item.extra["suppress_change"] = False
                        return None
                    try:
                        selected = str(widget.select())
                    except Exception:
                        selected = ""
                    return callback(item.extra.get("pages", {}).get(selected))

                item.extra["tab_binding"] = widget.bind(
                    "<<NotebookTabChanged>>", _tab_changed, add="+"
                )
            state = _ContainerState(kind=kind, item=item, widget=widget)
            self._stack.append(state)
            try:
                yield item
            finally:
                self._stack.pop()
            return

        if kind == "tab_page":
            tabs = self._stack[-1] if self._stack else None
            if tabs is None or tabs.kind != "tabs" or not isinstance(tabs.item, _TkItem):
                raise RuntimeError("Tkinter tab_page requires an active tabs container")
            label = str(kwargs.pop("label", ""))
            widget = tk.Frame(tabs.widget, borderwidth=0, highlightthickness=0)
            item = _TkItem(widget=widget, kind=kind, mount=widget)
            tabs.widget.add(widget, text=label)
            item.geometry_manager = "notebook"
            tabs.item.extra.setdefault("pages", {})[str(widget)] = item
            state = _ContainerState(kind=kind, item=item, widget=widget)
            self._stack.append(state)
            try:
                yield item
            finally:
                self._stack.pop()
            return

        if kind == "dialog":
            widget = tk.Toplevel(parent)
            widget.title(str(kwargs.pop("label", "")))
            no_resize = bool(kwargs.pop("no_resize", False))
            widget.resizable(not no_resize, not no_resize)
            min_size = kwargs.pop("min_size", None)
            if min_size:
                widget.minsize(max(1, int(min_size[0])), max(1, int(min_size[1])))
            if isinstance(width, (int, float)) and width > 0 and isinstance(height, (int, float)) and height > 0:
                widget.geometry(f"{int(width)}x{int(height)}")
            if not bool(kwargs.pop("show", False)):
                widget.withdraw()
            modal = bool(kwargs.pop("modal", False))
            item = _TkItem(widget=widget, kind=kind, mount=widget, extra={"modal": modal})
            state = _ContainerState(kind=kind, item=item, widget=widget)
            self._stack.append(state)
            try:
                yield item
            finally:
                self._stack.pop()
                if modal and self._widget_exists(widget):
                    try:
                        widget.transient(self.root)
                        if str(widget.state()) != "withdrawn":
                            widget.grab_set()
                    except Exception:
                        pass
            return

        if kind == "grid_row":
            grid = self._stack[-1] if self._stack else None
            if grid is None or grid.kind != "grid":
                raise RuntimeError("Tkinter grid_row requires an active grid container")
            row_index = grid.row
            grid.row += 1
            virtual = _TkVirtualItem("grid_row")
            state = _ContainerState(
                kind="grid_row",
                item=virtual,
                widget=grid.widget,
                row=row_index,
                column=0,
                horizontal_spacing=grid.horizontal_spacing,
            )
            self._stack.append(state)
            try:
                yield virtual
            finally:
                self._stack.pop()
            return

        if kind not in {
            "row",
            "column",
            "grid",
            "panel",
            "positioned_panel",
            "positioned_slot",
            "split_pane",
        }:
            raise ValueError(f"unsupported GUI component container: {kind!r}")

        border = bool(kwargs.pop("border", False))
        relief = "groove" if border else "flat"
        widget = tk.Frame(parent, borderwidth=1 if border else 0, relief=relief)
        if isinstance(width, (int, float)) and width > 0:
            widget.configure(width=int(width))
        if isinstance(height, (int, float)) and height > 0:
            widget.configure(height=int(height))
        fixed_geometry = (isinstance(width, (int, float)) and width > 0) or (
            isinstance(height, (int, float)) and height > 0
        )
        if fixed_geometry or kind in {"positioned_panel", "positioned_slot"}:
            widget.pack_propagate(False)
            widget.grid_propagate(False)

        item = _TkItem(widget=widget, kind=kind, mount=widget)
        self._remember_and_apply_geometry(
            item,
            width=width,
            height=height,
            parent_explicit=parent_explicit,
            show=True,
        )
        spacing = max(0, int(kwargs.pop("horizontal_spacing", 0) or 0))
        cross_axis = str(kwargs.pop("cross_axis", "natural")).strip().lower()
        if cross_axis not in {"natural", "stretch"}:
            raise ValueError("Tkinter linear container cross_axis must be 'natural' or 'stretch'")
        state = _ContainerState(
            kind=kind,
            item=item,
            widget=widget,
            horizontal_spacing=spacing,
            cross_axis=cross_axis,
        )
        self._stack.append(state)
        try:
            yield item
        finally:
            self._stack.pop()

    def get_value(self, item: object):
        if not isinstance(item, _TkItem):
            return None
        if item.kind == "tabs":
            try:
                selected = str(item.widget.select())
            except Exception:
                return None
            return item.extra.get("pages", {}).get(selected)
        if item.kind == "text_input" and item.extra.get("multiline"):
            return item.widget.get("1.0", "end-1c")
        if item.value_var is not None:
            return item.value_var.get()
        if item.kind == "label":
            return item.widget.cget("text")
        return None

    def set_value(self, item: object, value) -> None:
        if not isinstance(item, _TkItem) or not self.exists(item):
            raise RuntimeError("Tkinter item does not exist")
        if item.kind == "tabs":
            if not isinstance(value, _TkItem) or value.kind != "tab_page":
                raise TypeError("Tkinter tabs value must be a tab-page handle")
            item.extra["suppress_change"] = True
            item.widget.select(value.widget)
            return
        if item.kind == "text_input" and item.extra.get("multiline"):
            widget = item.widget
            previous_state = str(widget.cget("state"))
            if previous_state == "disabled":
                widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", str(value))
            if previous_state == "disabled":
                widget.configure(state="disabled")
            return
        if item.value_var is not None:
            item.value_var.set(value)
            return
        if item.kind == "label":
            item.widget.configure(text=str(value))
            return
        raise TypeError(f"Tkinter item kind {item.kind!r} does not own a value")

    def _set_visible(self, item: _TkItem, visible: bool) -> None:
        mount = item.mount or item.widget
        if mount is None:
            return
        if not visible:
            try:
                if item.geometry_manager == "grid":
                    mount.grid_remove()
                elif item.geometry_manager == "pack":
                    mount.pack_forget()
                elif item.geometry_manager == "place":
                    mount.place_forget()
                elif item.kind == "dialog":
                    item.widget.withdraw()
            except Exception:
                pass
            return

        try:
            if item.kind == "dialog":
                item.widget.deiconify()
                item.widget.lift()
                return
            if item.geometry_manager == "grid":
                mount.grid(**item.geometry_options)
            elif item.geometry_manager == "pack":
                mount.pack(**item.geometry_options)
            elif item.geometry_manager == "place":
                mount.place(**item.geometry_options)
        except Exception:
            pass

    def _set_enabled(self, item: _TkItem, enabled: bool) -> None:
        widget = item.widget
        if widget is None:
            return
        try:
            if item.kind == "combo_box":
                widget.configure(state=item.extra.get("enabled_state", "readonly") if enabled else "disabled")
            elif hasattr(widget, "state") and callable(widget.state):
                widget.state(["!disabled"] if enabled else ["disabled"])
            else:
                widget.configure(state="normal" if enabled else "disabled")
        except Exception:
            pass

    def configure(self, item: object, **kwargs) -> None:
        if not isinstance(item, _TkItem) or not self.exists(item):
            return
        kwargs = dict(kwargs)
        if "show" in kwargs:
            self._set_visible(item, bool(kwargs.pop("show")))
        if "enabled" in kwargs:
            self._set_enabled(item, bool(kwargs.pop("enabled")))
        if "items" in kwargs and item.kind == "combo_box":
            item.widget.configure(values=tuple(kwargs.pop("items")))
        if "overlay" in kwargs and item.kind == "progress_bar":
            overlay = kwargs.pop("overlay")
            label = item.extra.get("overlay_widget")
            if label is not None:
                label.configure(text="" if overlay is None else str(overlay))
                if overlay:
                    label.place(relx=0.5, rely=0.5, anchor="center")
                else:
                    label.place_forget()
        if "wrap" in kwargs and item.kind == "label":
            item.widget.configure(wraplength=max(1, int(kwargs.pop("wrap"))))
        if "label" in kwargs:
            label = str(kwargs.pop("label"))
            try:
                if item.kind == "dialog":
                    item.widget.title(label)
                else:
                    item.widget.configure(text=label)
            except Exception:
                pass
        if "width" in kwargs:
            value = kwargs.pop("width")
            if isinstance(value, (int, float)) and value > 0 and item.mount is not None:
                try:
                    item.mount.configure(width=int(value))
                    item.mount.pack_propagate(False)
                    item.mount.grid_propagate(False)
                except Exception:
                    pass
        if "height" in kwargs:
            value = kwargs.pop("height")
            if isinstance(value, (int, float)) and value > 0 and item.mount is not None:
                try:
                    item.mount.configure(height=int(value))
                    item.mount.pack_propagate(False)
                    item.mount.grid_propagate(False)
                except Exception:
                    pass
        if "indent" in kwargs:
            value = max(0, int(kwargs.pop("indent")))
            if item.geometry_manager == "pack":
                item.geometry_options["padx"] = (value, 0)
                self._set_visible(item, False)
                self._set_visible(item, True)
        if kwargs:
            try:
                item.widget.configure(**kwargs)
            except Exception:
                # The generic framework may expose a property unsupported by a
                # compatibility backend. Unsupported presentation decoration is
                # intentionally best-effort rather than a runtime failure.
                pass

    def place(self, item: object, x: int, y: int) -> None:
        if not isinstance(item, _TkItem) or not self.exists(item):
            return
        mount = item.mount or item.widget
        if mount is None:
            return
        try:
            if item.geometry_manager == "grid":
                mount.grid_forget()
            elif item.geometry_manager == "pack":
                mount.pack_forget()
            elif item.geometry_manager == "place":
                mount.place_forget()
        except Exception:
            pass
        options = {"x": max(0, int(x)), "y": max(0, int(y)), "anchor": "nw"}
        item.geometry_manager = "place"
        item.geometry_options = options
        try:
            mount.place(**options)
        except Exception:
            return

    def measure(self, item: object) -> tuple[int, int]:
        if not isinstance(item, _TkItem) or not self.exists(item):
            return (0, 0)
        target = item.mount or item.widget
        if target is None:
            return (0, 0)
        try:
            target.update_idletasks()
            width = max(int(target.winfo_width()), int(target.winfo_reqwidth()))
            height = max(int(target.winfo_height()), int(target.winfo_reqheight()))
            return max(0, width), max(0, height)
        except Exception:
            return (0, 0)

    def exists(self, item: object) -> bool:
        if isinstance(item, _TkVirtualItem):
            return bool(item.alive)
        if not isinstance(item, _TkItem) or not item.alive:
            return False
        return self._widget_exists(item.widget)

    def destroy(self, item: object) -> None:
        if isinstance(item, _TkVirtualItem):
            item.alive = False
            return
        if not isinstance(item, _TkItem) or not item.alive:
            return
        item.alive = False
        target = item.mount or item.widget
        if target is not None:
            try:
                target.destroy()
            except Exception:
                pass
        if item.value_var is not None:
            item.value_var = None
            try:
                self._value_items.remove(item)
            except ValueError:
                pass

    def event_callback(
        self,
        source: object,
        event_type: ComponentEventType,
        callback: Callable[[ComponentEvent], object] | None,
        *,
        data: object = None,
    ) -> object | None:
        if callback is None:
            return None
        if not callable(callback):
            raise TypeError("component event callback must be callable")
        event_type = ComponentEventType(event_type)

        @wraps(callback)
        def dispatch(value=None, *_args, **_kwargs):
            return callback(
                ComponentEvent(
                    source=source,
                    event_type=event_type,
                    value=value,
                    data=data,
                )
            )

        return dispatch

    def center(self, item: object, *, fallback_size: tuple[int, int] | None = None) -> None:
        if not isinstance(item, _TkItem) or item.kind != "dialog" or not self.exists(item):
            return
        window = item.widget
        try:
            window.update_idletasks()
            width = int(window.winfo_width())
            height = int(window.winfo_height())
            if (width <= 1 or height <= 1) and fallback_size is not None:
                width, height = (max(1, int(value)) for value in fallback_size)
            screen_width = int(window.winfo_screenwidth())
            screen_height = int(window.winfo_screenheight())
            x = max(0, (screen_width - width) // 2)
            y = max(0, (screen_height - height) // 2)
            window.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            return

    def attach_tooltip(self, item: object, text: str, *, wrap: int = 450) -> object | None:
        if not str(text or "").strip() or not isinstance(item, _TkItem) or not self.exists(item):
            return None
        try:
            tooltip = _TkTooltip(self.root, item.widget, str(text), max(1, int(wrap)))
            self._tooltips.append(tooltip)
            return tooltip
        except Exception:
            return None
