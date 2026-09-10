"""Dear PyGui host for clickable designer preview selection and highlighting."""

from __future__ import annotations

from collections.abc import Callable

from app.engine.designer_preview_pointer_arbiter import DearPyGuiDesignerPreviewPointerArbiter
from app.framework.designer_preview_selection import (
    DesignerPreviewSelectionBinding,
    DesignerPreviewSelectionTarget,
)


class DearPyGuiDesignerPreviewSelectionHost:
    """Bind one global pointer-down handler to current rendered preview items.

    Hit-testing is deliberately adapter-owned.  When several nested preview
    items report hover state, the deepest semantic target wins.  The visual
    selection indication is a transient viewport draw rectangle and never
    becomes part of the designer document or preview component tree.
    """

    def __init__(self, *, pointer_arbiter: DearPyGuiDesignerPreviewPointerArbiter | None = None):
        self.pointer_arbiter = pointer_arbiter

    @staticmethod
    def _dpg():
        import dearpygui.dearpygui as dpg

        return dpg

    @staticmethod
    def _mouse_position(dpg):
        try:
            position = dpg.get_mouse_pos(local=False)
        except TypeError:
            position = dpg.get_mouse_pos()
        return float(position[0]), float(position[1])

    @staticmethod
    def _target_item(target: DesignerPreviewSelectionTarget):
        try:
            return target.component.require_item()
        except RuntimeError:
            return None

    def _ordered_targets(self, targets):
        resolved = []
        for target in targets:
            item = self._target_item(target)
            resolved.append((target.depth, target.node_id, item, target.selected))
        resolved.sort(key=lambda value: value[0], reverse=True)
        return resolved

    def _draw_selection(self, binding: DesignerPreviewSelectionBinding) -> None:
        dpg = self._dpg()
        metadata = binding.metadata
        if not isinstance(metadata, dict):
            return
        old = metadata.get("selection_draw")
        if old is not None:
            try:
                if dpg.does_item_exist(old):
                    dpg.delete_item(old)
            except Exception:
                pass
        metadata["selection_draw"] = None

        selected_item = None
        for _depth, _node_id, item, selected in metadata.get("ordered", ()):
            if selected:
                selected_item = item
                break
        if selected_item is None:
            return
        try:
            if not dpg.does_item_exist(selected_item):
                return
            minimum = dpg.get_item_rect_min(selected_item)
            maximum = dpg.get_item_rect_max(selected_item)
            if not minimum or not maximum:
                return
            if maximum[0] <= minimum[0] or maximum[1] <= minimum[1]:
                return
            metadata["selection_draw"] = dpg.draw_rectangle(
                minimum,
                maximum,
                color=(72, 178, 255, 255),
                thickness=2.0,
                parent=metadata["drawlist"],
            )
        except Exception:
            metadata["selection_draw"] = None

    def build(
        self,
        targets: tuple[DesignerPreviewSelectionTarget, ...],
        *,
        parent: object,
        on_select: Callable[[str], object],
    ) -> DesignerPreviewSelectionBinding:
        if not callable(on_select):
            raise TypeError("designer preview-selection on_select callback must be callable")
        dpg = self._dpg()
        ordered = self._ordered_targets(targets)
        by_id = {node_id: item for _depth, node_id, item, _selected in ordered}
        # Preserve semantic preorder in the externally visible binding map.
        mapping = {target.node_id: by_id.get(target.node_id) for target in targets}

        handler_registry = dpg.add_handler_registry()
        drawlist = dpg.add_viewport_drawlist(front=True)
        metadata = {
            "handler_registry": handler_registry,
            "drawlist": drawlist,
            "selection_draw": None,
            "ordered": ordered,
            "on_select": on_select,
        }
        binding = DesignerPreviewSelectionBinding(parent, mapping, metadata)

        def pressed(_sender=None, _app_data=None, _user_data=None):
            # Selection happens on pointer-down, never on release.  When the
            # pointer is inside the active resize handle, that gesture owns the
            # press and selection must remain unchanged.
            if self.pointer_arbiter is not None:
                x, y = self._mouse_position(dpg)
                if self.pointer_arbiter.blocks_selection(x, y):
                    return
            for _depth, node_id, item, _selected in tuple(metadata.get("ordered", ())):
                if item is None:
                    continue
                try:
                    if dpg.does_item_exist(item) and dpg.is_item_hovered(item):
                        on_select(node_id)
                        return
                except Exception:
                    continue

        dpg.add_mouse_down_handler(
            button=dpg.mvMouseButton_Left,
            callback=pressed,
            parent=handler_registry,
        )
        self._draw_selection(binding)
        return binding

    def update(
        self,
        binding: DesignerPreviewSelectionBinding,
        targets: tuple[DesignerPreviewSelectionTarget, ...],
    ) -> None:
        if not self.exists(binding):
            raise RuntimeError("Dear PyGui designer preview-selection binding is stale")
        ordered = self._ordered_targets(targets)
        binding.targets.clear()
        by_id = {node_id: item for _depth, node_id, item, _selected in ordered}
        for target in targets:
            binding.targets[target.node_id] = by_id.get(target.node_id)
        assert isinstance(binding.metadata, dict)
        binding.metadata["ordered"] = ordered
        self._draw_selection(binding)

    def exists(self, binding: DesignerPreviewSelectionBinding) -> bool:
        if not isinstance(binding, DesignerPreviewSelectionBinding):
            return False
        dpg = self._dpg()
        metadata = binding.metadata
        if not isinstance(metadata, dict):
            return False
        try:
            return bool(
                dpg.does_item_exist(metadata.get("handler_registry"))
                and dpg.does_item_exist(metadata.get("drawlist"))
            )
        except Exception:
            return False

    def dispose(self, binding: DesignerPreviewSelectionBinding) -> None:
        if not isinstance(binding, DesignerPreviewSelectionBinding):
            return
        dpg = self._dpg()
        metadata = binding.metadata
        if not isinstance(metadata, dict):
            return
        for key in ("selection_draw", "handler_registry", "drawlist"):
            item = metadata.get(key)
            if item is None:
                continue
            try:
                if dpg.does_item_exist(item):
                    dpg.delete_item(item)
            except Exception:
                pass
        metadata.clear()
        binding.targets.clear()
