"""Dear PyGui scene-visibility host."""

from __future__ import annotations


class DearPyGuiSceneHost:
    """Implement the generic scene-host contract with Dear PyGui items."""

    @staticmethod
    def _dpg():
        import dearpygui.dearpygui as dpg

        return dpg

    def exists(self, container: object) -> bool:
        return bool(self._dpg().does_item_exist(container))

    def show(self, container: object) -> None:
        self._dpg().show_item(container)

    def hide(self, container: object) -> None:
        self._dpg().hide_item(container)
