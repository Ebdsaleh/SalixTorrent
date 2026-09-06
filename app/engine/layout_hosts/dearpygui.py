"""Dear PyGui host adapter for the reusable responsive-layout coordinator."""

from __future__ import annotations

from typing import Callable


class DearPyGuiLayoutHost:
    """Own Dear PyGui resize hooks, handler registries and geometry writes."""

    def __init__(self):
        self._registry_counter = 0

    @staticmethod
    def _dpg():
        try:
            import dearpygui.dearpygui as dpg
        except ModuleNotFoundError:  # pragma: no cover - GUI dependency absent
            return None
        return dpg

    @staticmethod
    def _backend_callback(callback: Callable[[], object]):
        """Adapt a zero-argument framework callback to Dear PyGui's contract."""

        def dispatch(sender=None, app_data=None, user_data=None):
            del sender, app_data, user_data
            return callback()

        return dispatch

    def install_viewport_resize(self, callback: Callable[[], object]) -> bool:
        dpg = self._dpg()
        if dpg is None:
            return False
        try:
            dpg.set_viewport_resize_callback(self._backend_callback(callback))
            return True
        except Exception:
            return False

    def watch_item_resize(
        self,
        item: object,
        callback: Callable[[], object],
    ) -> object | None:
        dpg = self._dpg()
        if dpg is None:
            return None

        self._registry_counter += 1
        registry = f"salix_responsive_resize::{self._registry_counter}"
        try:
            with dpg.item_handler_registry(tag=registry):
                dpg.add_item_resize_handler(callback=self._backend_callback(callback))
            dpg.bind_item_handler_registry(item, registry)
            return registry
        except Exception:
            try:
                if dpg.does_item_exist(registry):
                    dpg.delete_item(registry)
            except Exception:
                pass
            return None

    def unwatch_item_resize(self, watch: object) -> None:
        dpg = self._dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(watch):
                dpg.delete_item(watch)
        except Exception:
            return

    def item_size(self, item: object) -> tuple[int, int]:
        dpg = self._dpg()
        if dpg is None:
            return (0, 0)
        try:
            width, height = dpg.get_item_rect_size(item)
            return max(0, int(width)), max(0, int(height))
        except Exception:
            return (0, 0)

    def configure(self, item: object, **kwargs) -> bool:
        dpg = self._dpg()
        if dpg is None:
            return False
        try:
            if not dpg.does_item_exist(item):
                return False
            dpg.configure_item(item, **kwargs)
            return True
        except Exception:
            return False
