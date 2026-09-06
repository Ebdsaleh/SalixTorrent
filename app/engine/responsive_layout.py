"""SalixTorrent responsive-layout composition and compatibility surface.

Reusable callback coordination and low-churn geometry application live in
:mod:`app.framework.responsive`. Dear PyGui resize hooks and item operations
live in :mod:`app.engine.layout_hosts.dearpygui`. This module retains the
application singleton used by existing views and re-exports framework geometry
for compatibility while extraction remains in progress.
"""

from __future__ import annotations

from app.engine.layout_hosts import DearPyGuiLayoutHost
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
from app.framework.responsive import LayoutCoordinator


class ResponsiveLayout(LayoutCoordinator):
    """Application singleton backed by the concrete Dear PyGui layout host."""

    _instance: "ResponsiveLayout | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        super().__init__(DearPyGuiLayoutHost())
        self._initialized = True

    @classmethod
    def get_instance(cls) -> "ResponsiveLayout":
        return cls()
