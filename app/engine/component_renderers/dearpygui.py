"""Dear PyGui renderer adapter for the reusable component framework."""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from typing import Callable, Iterator

from app.framework.components.events import ComponentEvent, ComponentEventType
from app.framework.components.profile import ComponentLayoutProfile, FRAMEWORK_COMPONENT_PROFILE


class DearPyGuiRenderer:
    """Dear PyGui implementation of the reusable ``ComponentRenderer`` contract."""

    def __init__(self, *, component_profile: ComponentLayoutProfile | None = None):
        self.component_profile = component_profile or FRAMEWORK_COMPONENT_PROFILE

    def set_component_profile(self, profile: ComponentLayoutProfile) -> None:
        if not isinstance(profile, ComponentLayoutProfile):
            raise TypeError("component profile must be a ComponentLayoutProfile")
        self.component_profile = profile

    @staticmethod
    def _dpg():
        import dearpygui.dearpygui as dpg

        return dpg

    @staticmethod
    def _clean_kwargs(kwargs: dict) -> dict:
        return {key: value for key, value in kwargs.items() if value is not None}

    def create(self, kind: str, **kwargs) -> object:
        dpg = self._dpg()
        kwargs = self._clean_kwargs(dict(kwargs))

        if kind == "label":
            text = kwargs.pop("text")
            return dpg.add_text(text, **kwargs)
        if kind == "button":
            return dpg.add_button(**kwargs)
        if kind == "combo_box":
            return dpg.add_combo(**kwargs)
        if kind == "text_input":
            return dpg.add_input_text(**kwargs)
        if kind == "numeric_int":
            return dpg.add_input_int(**kwargs)
        if kind == "numeric_float":
            return dpg.add_input_float(**kwargs)
        if kind == "checkbox":
            return dpg.add_checkbox(**kwargs)
        if kind == "spacer":
            return dpg.add_spacer(**kwargs)
        if kind == "separator":
            return dpg.add_separator(**kwargs)
        if kind == "progress_bar":
            return dpg.add_progress_bar(**kwargs)
        if kind == "grid_column":
            return dpg.add_table_column(**kwargs)
        raise ValueError(f"unsupported GUI component kind: {kind!r}")

    @contextmanager
    def container(self, kind: str, **kwargs) -> Iterator[object]:
        dpg = self._dpg()
        kwargs = self._clean_kwargs(dict(kwargs))

        if kind == "row":
            with dpg.group(horizontal=True, **kwargs) as item:
                yield item
            return
        if kind == "column":
            with dpg.group(horizontal=False, **kwargs) as item:
                yield item
            return
        if kind == "grid":
            policy = kwargs.pop("policy", None)
            if policy == "fixed_fit":
                kwargs["policy"] = dpg.mvTable_SizingFixedFit
            with dpg.table(**kwargs) as item:
                yield item
            return
        if kind == "grid_row":
            with dpg.table_row(**kwargs) as item:
                yield item
            return
        if kind == "panel":
            with dpg.child_window(**kwargs) as item:
                yield item
            return
        if kind in {"positioned_panel", "positioned_slot"}:
            kwargs.setdefault("border", False)
            kwargs.setdefault("no_scrollbar", True)
            kwargs.setdefault("no_scroll_with_mouse", True)
            with dpg.child_window(**kwargs) as item:
                yield item
            return
        if kind == "dialog":
            with dpg.window(**kwargs) as item:
                yield item
            return
        raise ValueError(f"unsupported GUI component container: {kind!r}")

    def get_value(self, item: object):
        return self._dpg().get_value(item)

    def set_value(self, item: object, value) -> None:
        self._dpg().set_value(item, value)

    def configure(self, item: object, **kwargs) -> None:
        self._dpg().configure_item(item, **kwargs)

    def place(self, item: object, x: int, y: int) -> None:
        dpg = self._dpg()
        if not dpg.does_item_exist(item):
            return
        dpg.set_item_pos(item, [max(0, int(x)), max(0, int(y))])

    def measure(self, item: object) -> tuple[int, int]:
        dpg = self._dpg()
        if not dpg.does_item_exist(item):
            return (0, 0)
        width = height = 0
        try:
            width, height = dpg.get_item_rect_size(item)
        except Exception:
            pass
        if int(width or 0) <= 0 or int(height or 0) <= 0:
            try:
                config = dpg.get_item_configuration(item) or {}
                if int(width or 0) <= 0:
                    width = config.get("width", 0)
                if int(height or 0) <= 0:
                    height = config.get("height", 0)
            except Exception:
                pass
        return max(0, int(width or 0)), max(0, int(height or 0))

    def exists(self, item: object) -> bool:
        return bool(self._dpg().does_item_exist(item))

    def destroy(self, item: object) -> None:
        dpg = self._dpg()
        if dpg.does_item_exist(item):
            dpg.delete_item(item)

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
        def dispatch(_sender=None, app_data=None, _user_data=None):
            return callback(
                ComponentEvent(
                    source=source,
                    event_type=event_type,
                    value=app_data,
                    data=data,
                )
            )

        return dispatch

    def center(self, item: object, *, fallback_size: tuple[int, int] | None = None) -> None:
        dpg = self._dpg()
        fallback_width = fallback_height = 0
        if fallback_size is not None:
            fallback_width = max(0, int(fallback_size[0]))
            fallback_height = max(0, int(fallback_size[1]))

        try:
            width, height = dpg.get_item_rect_size(item)
            width = int(width or fallback_width)
            height = int(height or fallback_height)
        except Exception:
            width, height = fallback_width, fallback_height

        if width <= 0 or height <= 0:
            return

        try:
            x = max(0, (int(dpg.get_viewport_client_width()) - width) // 2)
            y = max(0, (int(dpg.get_viewport_client_height()) - height) // 2)
            dpg.set_item_pos(item, [x, y])
        except Exception:
            return

    def attach_tooltip(self, item: object, text: str, *, wrap: int = 450) -> object | None:
        if not item or not str(text or "").strip():
            return None

        dpg = self._dpg()
        tooltip_id = None
        try:
            tooltip_id = dpg.add_tooltip(parent=item)
            return dpg.add_text(str(text), parent=tooltip_id, wrap=max(1, int(wrap)))
        except Exception:
            try:
                if tooltip_id and dpg.does_item_exist(tooltip_id):
                    dpg.delete_item(tooltip_id)
            except Exception:
                pass
            return None
