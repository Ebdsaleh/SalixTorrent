"""Concrete GUI backend adapters for the reusable component framework."""

from app.engine.component_renderers.dearpygui import DearPyGuiRenderer
from app.engine.component_renderers.tkinter import TkinterRenderer

__all__ = ["DearPyGuiRenderer", "TkinterRenderer"]
