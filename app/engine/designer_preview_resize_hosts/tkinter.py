"""Tkinter pointer host for selected designer-preview resizing."""

from __future__ import annotations

from collections.abc import Callable

from app.engine.component_renderers.tkinter import TkinterRenderer
from app.framework.designer_preview_resize import (
    DesignerPreviewResizeBinding,
    DesignerPreviewResizeTarget,
)


class TkinterDesignerPreviewResizeHost:
    """Place one native ``ttk.Sizegrip`` over the selected component."""

    def __init__(self, renderer: TkinterRenderer, *, handle_size: int = 12, minimum_width: int = 24, minimum_height: int = 20):
        if not isinstance(renderer, TkinterRenderer):
            raise TypeError("TkinterDesignerPreviewResizeHost requires a TkinterRenderer")
        self.renderer = renderer
        self.handle_size = max(8, int(handle_size))
        self.minimum_width = max(1, int(minimum_width))
        self.minimum_height = max(1, int(minimum_height))

    @staticmethod
    def _exists_widget(widget) -> bool:
        try:
            return bool(int(widget.winfo_exists()))
        except Exception:
            return False

    def _target_item(self, target: DesignerPreviewResizeTarget | None):
        if target is None:
            return None
        try:
            return target.component.require_item()
        except RuntimeError:
            return None

    def _position_handle(self, binding: DesignerPreviewResizeBinding) -> None:
        metadata = binding.metadata
        if not isinstance(metadata, dict):
            return
        handle = metadata.get("handle")
        parent = metadata.get("parent_widget")
        item = metadata.get("item")
        if handle is None or parent is None or item is None:
            if handle is not None and self._exists_widget(handle):
                handle.place_forget()
            return
        target = self.renderer.native_widget(item.mount if getattr(item, "mount", None) is not None else item)
        if target is None or not self._exists_widget(target) or not self._exists_widget(parent):
            if self._exists_widget(handle):
                handle.place_forget()
            return
        try:
            target.update_idletasks()
            x = int(target.winfo_rootx() - parent.winfo_rootx() + target.winfo_width() - self.handle_size // 2)
            y = int(target.winfo_rooty() - parent.winfo_rooty() + target.winfo_height() - self.handle_size // 2)
            handle.place(x=max(0, x), y=max(0, y), width=self.handle_size, height=self.handle_size)
            handle.lift()
        except Exception:
            try:
                handle.place_forget()
            except Exception:
                pass

    def build(
        self,
        target: DesignerPreviewResizeTarget | None,
        *,
        parent: object,
        on_resize: Callable[[str, int, int], bool],
    ) -> DesignerPreviewResizeBinding:
        if not callable(on_resize):
            raise TypeError("designer preview resize on_resize callback must be callable")
        from tkinter import ttk

        parent_widget = self.renderer.content_widget(parent)
        if parent_widget is None:
            raise RuntimeError("Tkinter designer preview resize parent has no widget")
        handle = ttk.Sizegrip(parent_widget)
        metadata = {
            "target": target,
            "item": self._target_item(target),
            "parent_widget": parent_widget,
            "handle": handle,
            "on_resize": on_resize,
            "dragging": False,
            "start_mouse": None,
            "start_size": None,
            "draft_size": None,
        }
        binding = DesignerPreviewResizeBinding(parent_widget, metadata["item"], metadata)

        def pressed(event):
            item = metadata.get("item")
            current = metadata.get("target")
            if item is None or current is None:
                return
            width, height = self.renderer.measure(item)
            if width <= 0 or height <= 0:
                return
            metadata["dragging"] = True
            metadata["start_mouse"] = (int(event.x_root), int(event.y_root))
            metadata["start_size"] = (int(width), int(height))
            metadata["draft_size"] = (int(width), int(height))

        def moved(event):
            if not metadata.get("dragging"):
                return
            item = metadata.get("item")
            start_mouse = metadata.get("start_mouse")
            start_size = metadata.get("start_size")
            if item is None or start_mouse is None or start_size is None:
                return
            width = max(self.minimum_width, int(start_size[0] + int(event.x_root) - start_mouse[0]))
            height = max(self.minimum_height, int(start_size[1] + int(event.y_root) - start_mouse[1]))
            self.renderer.configure(item, width=width, height=height)
            metadata["draft_size"] = (width, height)
            self._position_handle(binding)

        def released(_event):
            if not metadata.get("dragging"):
                return
            current = metadata.get("target")
            item = metadata.get("item")
            start_size = metadata.get("start_size")
            draft_size = metadata.get("draft_size") or start_size
            metadata["dragging"] = False
            metadata["start_mouse"] = None
            metadata["start_size"] = None
            metadata["draft_size"] = None
            if current is None or draft_size is None:
                self._position_handle(binding)
                return
            committed = bool(on_resize(current.node_id, int(draft_size[0]), int(draft_size[1])))
            if not committed and item is not None and start_size is not None:
                self.renderer.configure(item, width=int(start_size[0]), height=int(start_size[1]))
            try:
                self.renderer.root.after_idle(lambda: self._position_handle(binding))
            except Exception:
                pass

        handle.bind("<ButtonPress-1>", pressed, add="+")
        handle.bind("<B1-Motion>", moved, add="+")
        handle.bind("<ButtonRelease-1>", released, add="+")
        try:
            self.renderer.root.after_idle(lambda: self._position_handle(binding))
        except Exception:
            self._position_handle(binding)
        return binding

    def update(
        self,
        binding: DesignerPreviewResizeBinding,
        target: DesignerPreviewResizeTarget | None,
    ) -> None:
        if not self.exists(binding):
            raise RuntimeError("Tkinter designer preview resize binding is stale")
        assert isinstance(binding.metadata, dict)
        binding.metadata["target"] = target
        binding.metadata["item"] = self._target_item(target)
        binding.metadata["dragging"] = False
        binding.metadata["start_mouse"] = None
        binding.metadata["start_size"] = None
        binding.metadata["draft_size"] = None
        binding.target = binding.metadata["item"]
        try:
            self.renderer.root.after_idle(lambda: self._position_handle(binding))
        except Exception:
            self._position_handle(binding)

    def exists(self, binding: DesignerPreviewResizeBinding) -> bool:
        if not isinstance(binding, DesignerPreviewResizeBinding):
            return False
        metadata = binding.metadata
        return bool(
            isinstance(metadata, dict)
            and self._exists_widget(metadata.get("handle"))
            and self._exists_widget(metadata.get("parent_widget"))
        )

    def dispose(self, binding: DesignerPreviewResizeBinding) -> None:
        if not isinstance(binding, DesignerPreviewResizeBinding):
            return
        metadata = binding.metadata
        if not isinstance(metadata, dict):
            return
        handle = metadata.get("handle")
        if self._exists_widget(handle):
            try:
                handle.destroy()
            except Exception:
                pass
        metadata.clear()
        binding.target = None


__all__ = ["TkinterDesignerPreviewResizeHost"]
