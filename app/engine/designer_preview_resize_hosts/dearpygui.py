"""Dear PyGui pointer host for selected designer-preview resizing."""

from __future__ import annotations

from collections.abc import Callable

from app.engine.designer_preview_pointer_arbiter import DearPyGuiDesignerPreviewPointerArbiter
from app.framework.designer_preview_resize import (
    DesignerPreviewResizeBinding,
    DesignerPreviewResizeTarget,
)


class DearPyGuiDesignerPreviewResizeHost:
    """Draw one bottom-right resize handle and own native pointer drag state."""

    def __init__(
        self,
        *,
        handle_size: int = 10,
        minimum_width: int = 24,
        minimum_height: int = 20,
        pointer_arbiter: DearPyGuiDesignerPreviewPointerArbiter | None = None,
    ):
        self.handle_size = max(6, int(handle_size))
        self.minimum_width = max(1, int(minimum_width))
        self.minimum_height = max(1, int(minimum_height))
        self.pointer_arbiter = pointer_arbiter

    @staticmethod
    def _dpg():
        import dearpygui.dearpygui as dpg

        return dpg

    @staticmethod
    def _target_item(target: DesignerPreviewResizeTarget | None):
        if target is None:
            return None
        try:
            return target.component.require_item()
        except RuntimeError:
            return None

    @staticmethod
    def _mouse_position(dpg):
        try:
            position = dpg.get_mouse_pos(local=False)
        except TypeError:
            position = dpg.get_mouse_pos()
        return float(position[0]), float(position[1])

    @staticmethod
    def _rect(dpg, item):
        if item is None or not dpg.does_item_exist(item):
            return None
        try:
            minimum = dpg.get_item_rect_min(item)
            maximum = dpg.get_item_rect_max(item)
        except Exception:
            return None
        if not minimum or not maximum:
            return None
        if maximum[0] <= minimum[0] or maximum[1] <= minimum[1]:
            return None
        return (float(minimum[0]), float(minimum[1])), (float(maximum[0]), float(maximum[1]))

    def _remove_handle(self, metadata: dict) -> None:
        dpg = self._dpg()
        handle = metadata.get("handle_draw")
        metadata["handle_draw"] = None
        metadata["handle_bounds"] = None
        if self.pointer_arbiter is not None:
            self.pointer_arbiter.set_resize_handle_bounds(None)
        if handle is None:
            return
        try:
            if dpg.does_item_exist(handle):
                dpg.delete_item(handle)
        except Exception:
            pass

    def _draw_handle(self, binding: DesignerPreviewResizeBinding) -> None:
        dpg = self._dpg()
        metadata = binding.metadata
        if not isinstance(metadata, dict):
            return
        self._remove_handle(metadata)
        target = metadata.get("target")
        item = metadata.get("item")
        if target is None or item is None:
            return
        rect = self._rect(dpg, item)
        if rect is None:
            return
        minimum, maximum = rect
        # Keep the whole interactive square *inside* the selected component.
        # The earlier centered-on-corner handle straddled the component edge, so
        # clicking its outer half could be interpreted as clicking the parent.
        inset = 1.0
        right = max(float(minimum[0]), float(maximum[0]) - inset)
        bottom = max(float(minimum[1]), float(maximum[1]) - inset)
        left = max(float(minimum[0]), right - float(self.handle_size))
        top = max(float(minimum[1]), bottom - float(self.handle_size))
        bounds = (left, top, right, bottom)
        metadata["handle_bounds"] = bounds
        if self.pointer_arbiter is not None:
            self.pointer_arbiter.set_resize_handle_bounds(bounds)
        try:
            metadata["handle_draw"] = dpg.draw_rectangle(
                (left, top),
                (right, bottom),
                color=(72, 178, 255, 255),
                fill=(72, 178, 255, 255),
                thickness=1.0,
                parent=metadata["drawlist"],
            )
        except Exception:
            metadata["handle_draw"] = None
            metadata["handle_bounds"] = None
            if self.pointer_arbiter is not None:
                self.pointer_arbiter.set_resize_handle_bounds(None)

    def _is_handle_hit(self, dpg, metadata: dict) -> bool:
        bounds = metadata.get("handle_bounds")
        if not isinstance(bounds, tuple) or len(bounds) != 4:
            return False
        x, y = self._mouse_position(dpg)
        left, top, right, bottom = bounds
        return left <= x <= right and top <= y <= bottom

    def build(
        self,
        target: DesignerPreviewResizeTarget | None,
        *,
        parent: object,
        on_resize: Callable[[str, int, int], bool],
    ) -> DesignerPreviewResizeBinding:
        if not callable(on_resize):
            raise TypeError("designer preview resize on_resize callback must be callable")
        dpg = self._dpg()
        registry = dpg.add_handler_registry()
        drawlist = dpg.add_viewport_drawlist(front=True)
        metadata = {
            "target": target,
            "item": self._target_item(target),
            "on_resize": on_resize,
            "handler_registry": registry,
            "drawlist": drawlist,
            "handle_draw": None,
            "handle_bounds": None,
            "dragging": False,
            "drag_target": None,
            "drag_item": None,
            "start_mouse": None,
            "start_size": None,
            "draft_size": None,
        }
        binding = DesignerPreviewResizeBinding(parent, metadata["item"], metadata)

        def mouse_down(_sender=None, _app_data=None, _user_data=None):
            item = metadata.get("item")
            current = metadata.get("target")
            if current is None or item is None or not self._is_handle_hit(dpg, metadata):
                return
            rect = self._rect(dpg, item)
            if rect is None:
                return
            minimum, maximum = rect
            # Freeze semantic/native ownership at pointer-down.  Refreshes or
            # selection changes must never retarget a gesture mid-drag.
            metadata["dragging"] = True
            metadata["drag_target"] = current
            metadata["drag_item"] = item
            metadata["start_mouse"] = self._mouse_position(dpg)
            metadata["start_size"] = (
                max(1, int(round(maximum[0] - minimum[0]))),
                max(1, int(round(maximum[1] - minimum[1]))),
            )
            metadata["draft_size"] = metadata["start_size"]
            if self.pointer_arbiter is not None:
                self.pointer_arbiter.begin_resize(current.node_id)

        def mouse_move(_sender=None, _app_data=None, _user_data=None):
            if not metadata.get("dragging"):
                return
            item = metadata.get("drag_item")
            start_mouse = metadata.get("start_mouse")
            start_size = metadata.get("start_size")
            if item is None or start_mouse is None or start_size is None:
                return
            x, y = self._mouse_position(dpg)
            width = max(self.minimum_width, int(round(start_size[0] + x - start_mouse[0])))
            height = max(self.minimum_height, int(round(start_size[1] + y - start_mouse[1])))
            try:
                if dpg.does_item_exist(item):
                    dpg.configure_item(item, width=width, height=height)
            except Exception:
                return
            metadata["draft_size"] = (width, height)
            self._draw_handle(binding)

        def mouse_release(_sender=None, _app_data=None, _user_data=None):
            if not metadata.get("dragging"):
                return
            current = metadata.get("drag_target")
            item = metadata.get("drag_item")
            start_size = metadata.get("start_size")
            draft_size = metadata.get("draft_size") or start_size
            metadata["dragging"] = False
            metadata["drag_target"] = None
            metadata["drag_item"] = None
            metadata["start_mouse"] = None
            metadata["start_size"] = None
            metadata["draft_size"] = None
            if self.pointer_arbiter is not None:
                self.pointer_arbiter.end_resize()
            if current is None or draft_size is None:
                self._draw_handle(binding)
                return
            committed = bool(on_resize(current.node_id, int(draft_size[0]), int(draft_size[1])))
            if not committed and item is not None and start_size is not None:
                try:
                    if dpg.does_item_exist(item):
                        dpg.configure_item(item, width=int(start_size[0]), height=int(start_size[1]))
                except Exception:
                    pass
            self._draw_handle(binding)

        dpg.add_mouse_down_handler(
            button=dpg.mvMouseButton_Left,
            callback=mouse_down,
            parent=registry,
        )
        dpg.add_mouse_move_handler(callback=mouse_move, parent=registry)
        dpg.add_mouse_release_handler(
            button=dpg.mvMouseButton_Left,
            callback=mouse_release,
            parent=registry,
        )
        self._draw_handle(binding)
        return binding

    def update(
        self,
        binding: DesignerPreviewResizeBinding,
        target: DesignerPreviewResizeTarget | None,
    ) -> None:
        if not self.exists(binding):
            raise RuntimeError("Dear PyGui designer preview resize binding is stale")
        assert isinstance(binding.metadata, dict)
        # A native drag owns its original target until release.  Do not cancel or
        # retarget it merely because another presenter asked for a refresh.
        if binding.metadata.get("dragging"):
            return
        binding.metadata["target"] = target
        binding.metadata["item"] = self._target_item(target)
        binding.metadata["drag_target"] = None
        binding.metadata["drag_item"] = None
        binding.metadata["start_mouse"] = None
        binding.metadata["start_size"] = None
        binding.metadata["draft_size"] = None
        binding.target = binding.metadata["item"]
        self._draw_handle(binding)

    def exists(self, binding: DesignerPreviewResizeBinding) -> bool:
        if not isinstance(binding, DesignerPreviewResizeBinding):
            return False
        metadata = binding.metadata
        if not isinstance(metadata, dict):
            return False
        dpg = self._dpg()
        try:
            return bool(
                dpg.does_item_exist(metadata.get("handler_registry"))
                and dpg.does_item_exist(metadata.get("drawlist"))
            )
        except Exception:
            return False

    def dispose(self, binding: DesignerPreviewResizeBinding) -> None:
        if not isinstance(binding, DesignerPreviewResizeBinding):
            return
        metadata = binding.metadata
        if not isinstance(metadata, dict):
            return
        dpg = self._dpg()
        self._remove_handle(metadata)
        if self.pointer_arbiter is not None:
            self.pointer_arbiter.end_resize()
        for key in ("handler_registry", "drawlist"):
            item = metadata.get(key)
            if item is None:
                continue
            try:
                if dpg.does_item_exist(item):
                    dpg.delete_item(item)
            except Exception:
                pass
        metadata.clear()
        binding.target = None


__all__ = ["DearPyGuiDesignerPreviewResizeHost"]
