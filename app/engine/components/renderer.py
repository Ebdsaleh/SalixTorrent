"""Rendering bridge for reusable GUI component specifications.

The public component objects are intentionally backend-neutral.  SalixTorrent's
current renderer is Dear PyGui, but the component model does not import it at
module import time so pure framework tests and future extraction work remain
headless-friendly.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import ContextManager, Iterator, Protocol, runtime_checkable


@runtime_checkable
class ComponentRenderer(Protocol):
    """Minimal renderer contract consumed by the component layer."""

    def create(self, kind: str, **kwargs) -> object:
        ...

    def container(self, kind: str, **kwargs) -> ContextManager[object]:
        ...

    def get_value(self, item: object):
        ...

    def set_value(self, item: object, value) -> None:
        ...

    def configure(self, item: object, **kwargs) -> None:
        ...

    def exists(self, item: object) -> bool:
        ...


class DearPyGuiRenderer:
    """Dear PyGui implementation of :class:`ComponentRenderer`."""

    _instance: "DearPyGuiRenderer | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

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
        if kind == "numeric_int":
            return dpg.add_input_int(**kwargs)
        if kind == "numeric_float":
            return dpg.add_input_float(**kwargs)
        if kind == "checkbox":
            return dpg.add_checkbox(**kwargs)
        if kind == "spacer":
            return dpg.add_spacer(**kwargs)
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
        raise ValueError(f"unsupported GUI component container: {kind!r}")

    def get_value(self, item: object):
        return self._dpg().get_value(item)

    def set_value(self, item: object, value) -> None:
        self._dpg().set_value(item, value)

    def configure(self, item: object, **kwargs) -> None:
        self._dpg().configure_item(item, **kwargs)

    def exists(self, item: object) -> bool:
        return bool(self._dpg().does_item_exist(item))


def get_default_renderer() -> ComponentRenderer:
    return DearPyGuiRenderer()
