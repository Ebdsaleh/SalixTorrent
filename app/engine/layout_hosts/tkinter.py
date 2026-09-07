"""Tkinter host adapter for the reusable responsive-layout coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.engine.component_renderers.tkinter import TkinterRenderer


@dataclass(eq=False)
class _TkResizeWatch:
    widget: object
    sequence: str
    binding_id: str | None


class TkinterLayoutHost:
    """Own Tkinter configure bindings and geometry writes."""

    def __init__(self, renderer: TkinterRenderer):
        if not isinstance(renderer, TkinterRenderer):
            raise TypeError("TkinterLayoutHost requires a TkinterRenderer")
        self.renderer = renderer
        self.root = renderer.root
        self._viewport_binding: str | None = None

    @staticmethod
    def _dispatch(callback: Callable[[], object]):
        def invoke(_event=None):
            return callback()

        return invoke

    def install_viewport_resize(self, callback: Callable[[], object]) -> bool:
        if self._viewport_binding is not None:
            return False
        try:
            self._viewport_binding = self.root.bind(
                "<Configure>", self._dispatch(callback), add="+"
            )
            return True
        except Exception:
            self._viewport_binding = None
            return False

    def watch_item_resize(
        self,
        item: object,
        callback: Callable[[], object],
    ) -> object | None:
        widget = self.renderer.native_widget(item)
        if widget is None:
            return None
        try:
            binding = widget.bind("<Configure>", self._dispatch(callback), add="+")
            return _TkResizeWatch(widget, "<Configure>", binding)
        except Exception:
            return None

    def unwatch_item_resize(self, watch: object) -> None:
        if not isinstance(watch, _TkResizeWatch):
            return
        try:
            if watch.binding_id:
                watch.widget.unbind(watch.sequence, watch.binding_id)
        except Exception:
            return

    def item_size(self, item: object) -> tuple[int, int]:
        widget = self.renderer.native_widget(item)
        if widget is None:
            return (0, 0)
        try:
            widget.update_idletasks()
            return max(0, int(widget.winfo_width())), max(0, int(widget.winfo_height()))
        except Exception:
            return (0, 0)

    def configure(self, item: object, **kwargs) -> bool:
        if not self.renderer.exists(item):
            return False
        try:
            self.renderer.configure(item, **kwargs)
            return True
        except Exception:
            return False
