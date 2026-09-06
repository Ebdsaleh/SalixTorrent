"""Compatibility renderer imports during framework extraction."""

from app.framework.components.renderer import *  # noqa: F401,F403
from app.engine.component_renderers.dearpygui import DearPyGuiRenderer

__all__ = [
    "ComponentRenderer",
    "DearPyGuiRenderer",
    "clear_default_renderer",
    "get_default_renderer",
    "set_default_renderer",
]
