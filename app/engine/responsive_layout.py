"""Event-driven Dear PyGui layout adapter plus framework geometry compatibility.

Pure geometry primitives live in :mod:`app.framework.geometry`. This module
retains the Dear PyGui resize dispatcher and re-exports those primitives for
legacy application imports while the framework boundary is being extracted.
"""

from __future__ import annotations

from typing import Callable, Hashable, Iterable

from app.framework.geometry import (
    ContentBounds,
    ContentMetrics,
    DialogMetrics,
    HorizontalAlign,
    Number,
    VerticalAlign,
    aligned_offset,
    clamp,
    content_bounds,
    fill_height,
    split_widths,
)

try:  # Keep the adapter importable in headless/unit-test environments.
    import dearpygui.dearpygui as dpg
except ModuleNotFoundError:  # pragma: no cover - exercised only without GUI deps
    dpg = None  # type: ignore[assignment]


class ResponsiveLayout:
    """Central resize dispatcher and low-churn Dear PyGui geometry bridge.

    Viewport and item resize handlers all execute on Dear PyGui's callback path.
    SalixTorrent already serializes callbacks onto its UI thread, so no locks or
    worker threads are needed here.  Geometry writes are memoized to avoid
    configure-item churn and resize feedback loops.
    """

    _instance: "ResponsiveLayout | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._viewport_callbacks: dict[Hashable, Callable[[], None]] = {}
        self._item_callbacks: dict[Hashable, Callable[[], None]] = {}
        self._item_registries: dict[Hashable, object] = {}
        self._applied: dict[tuple[object, str], object] = {}
        self._viewport_installed = False
        self._registry_counter = 0

    @classmethod
    def get_instance(cls) -> "ResponsiveLayout":
        return cls()

    def install_viewport_callback(self):
        if dpg is None or self._viewport_installed:
            return
        dpg.set_viewport_resize_callback(self._on_viewport_resize)
        self._viewport_installed = True

    def register_viewport(self, key: Hashable, callback: Callable[[], None]):
        self._viewport_callbacks[key] = callback

    def unregister_viewport(self, key: Hashable):
        self._viewport_callbacks.pop(key, None)

    def watch_item(self, item, key: Hashable, callback: Callable[[], None]):
        """Run *callback* when one Dear PyGui item changes rendered size."""
        if dpg is None:
            return
        self._item_callbacks[key] = callback
        old = self._item_registries.pop(key, None)
        if old is not None:
            try:
                if dpg.does_item_exist(old):
                    dpg.delete_item(old)
            except Exception:
                pass

        self._registry_counter += 1
        registry = f"salix_responsive_resize::{self._registry_counter}"

        _resized = self._make_item_resize_callback(key)

        with dpg.item_handler_registry(tag=registry):
            dpg.add_item_resize_handler(callback=_resized)
        dpg.bind_item_handler_registry(item, registry)
        self._item_registries[key] = registry


    def _make_item_resize_callback(self, key: Hashable):
        """Return a Dear PyGui-compatible three-argument resize callback.

        Dear PyGui's manual callback queue contains ``callback, sender,
        app_data, user_data``.  The callback therefore must not expose extra
        parameters merely to capture framework state: ``run_callbacks`` uses
        the callable signature to pull positional values from that queue.
        Capture *key* in the closure instead so the public callback contract
        remains exactly the standard three arguments.
        """
        captured_key = key

        def _resized(sender=None, app_data=None, user_data=None):
            del sender, app_data, user_data
            self.trigger(captured_key)

        return _resized

    def trigger(self, key: Hashable):
        callback = self._item_callbacks.get(key) or self._viewport_callbacks.get(key)
        if callback is None:
            return
        try:
            callback()
        except Exception:
            # Layout must never take the application down.  GuiEngine's normal
            # render/update error reporting still handles view-level failures.
            return

    def refresh_all(self):
        """Refresh registered geometry after show/switch/initial viewport setup."""
        for callback in tuple(self._viewport_callbacks.values()):
            try:
                callback()
            except Exception:
                continue
        for callback in tuple(self._item_callbacks.values()):
            try:
                callback()
            except Exception:
                continue

    def _on_viewport_resize(self, sender=None, app_data=None, user_data=None):
        del sender, app_data, user_data
        for callback in tuple(self._viewport_callbacks.values()):
            try:
                callback()
            except Exception:
                continue

    @staticmethod
    def item_size(item) -> tuple[int, int]:
        if dpg is None:
            return (0, 0)
        try:
            width, height = dpg.get_item_rect_size(item)
            return max(0, int(width)), max(0, int(height))
        except Exception:
            return (0, 0)

    def _apply(self, item, name: str, value, callback: Callable[[], None]):
        key = (item, name)
        if self._applied.get(key) == value:
            return False
        if dpg is None:
            self._applied[key] = value
            return False
        try:
            if not dpg.does_item_exist(item):
                return False
            callback()
            self._applied[key] = value
            return True
        except Exception:
            return False

    def width(self, item, value: Number):
        target = int(value)
        return self._apply(item, "width", target, lambda: dpg.configure_item(item, width=target))

    def height(self, item, value: Number):
        target = int(value)
        return self._apply(item, "height", target, lambda: dpg.configure_item(item, height=target))

    def size(self, item, width: Number, height: Number):
        target = (int(width), int(height))
        return self._apply(
            item,
            "size",
            target,
            lambda: dpg.configure_item(item, width=target[0], height=target[1]),
        )

    def wrap(self, item, value: Number):
        target = max(1, int(value))
        return self._apply(item, "wrap", target, lambda: dpg.configure_item(item, wrap=target))

    def wraps(self, items: Iterable[object], value: Number):
        for item in tuple(items):
            self.wrap(item, value)

    def indent(self, item, value: Number):
        """Apply parent-relative indentation with geometry-write memoization."""
        target = max(0, int(value))
        return self._apply(item, "indent", target, lambda: dpg.configure_item(item, indent=target))

    def dialog(
        self,
        window,
        content,
        *,
        metrics: DialogMetrics,
        wrap_items: Iterable[object] = (),
    ):
        """Resize a dialog's fill region and text measure from its rendered size."""
        width, height = self.item_size(window)
        if width <= 1 or height <= 1:
            return
        self.height(
            content,
            fill_height(
                height,
                metrics.reserved_height,
                minimum=metrics.minimum_content_height,
            ),
        )
        wrap_width = clamp(
            width - metrics.horizontal_margin,
            metrics.minimum_wrap,
            metrics.maximum_wrap,
        )
        self.wraps(wrap_items, wrap_width)




