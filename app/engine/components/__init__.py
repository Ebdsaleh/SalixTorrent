"""Compatibility facade for the provisional physical framework extraction.

New SalixTorrent code imports reusable controls from ``app.framework.components``.
The old ``app.engine.components`` path remains temporarily to avoid forcing a
public naming/API decision while the wider RAD boundary is still being proven.
"""

from app.framework.components import *  # noqa: F401,F403
from app.framework.components import __all__ as _framework_all
from app.engine.component_renderers.dearpygui import DearPyGuiRenderer

__all__ = [*_framework_all, "DearPyGuiRenderer"]
