"""Dear PyGui preview-pointer arbitration for designer direct manipulation.

This module is deliberately backend/presentation scoped.  It coordinates only
native Dear PyGui pointer ownership between preview selection and resize hosts;
no designer document, history, selection, layout or persistence semantics live
here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DearPyGuiDesignerPreviewPointerArbiter:
    """Share transient resize-handle hit state between Dear PyGui hosts."""

    _handle_bounds: tuple[float, float, float, float] | None = None
    _resize_node_id: str | None = None

    def set_resize_handle_bounds(
        self,
        bounds: tuple[float, float, float, float] | None,
    ) -> None:
        self._handle_bounds = bounds

    @property
    def resize_node_id(self) -> str | None:
        return self._resize_node_id

    @property
    def resizing(self) -> bool:
        return self._resize_node_id is not None

    def begin_resize(self, node_id: str) -> None:
        resolved = str(node_id or "").strip()
        if not resolved:
            raise ValueError("designer preview pointer resize node id must be non-empty")
        self._resize_node_id = resolved

    def end_resize(self) -> None:
        self._resize_node_id = None

    def contains_resize_handle(self, x: float, y: float) -> bool:
        bounds = self._handle_bounds
        if bounds is None:
            return False
        left, top, right, bottom = bounds
        return left <= float(x) <= right and top <= float(y) <= bottom

    def blocks_selection(self, x: float, y: float) -> bool:
        return self.resizing or self.contains_resize_handle(x, y)


__all__ = ["DearPyGuiDesignerPreviewPointerArbiter"]
