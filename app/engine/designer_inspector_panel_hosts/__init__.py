"""Concrete presentation hosts for the optional designer property inspector."""

from .dearpygui import DearPyGuiDesignerInspectorPanelHost
from .tkinter import TkinterDesignerInspectorPanelHost

__all__ = [
    "DearPyGuiDesignerInspectorPanelHost",
    "TkinterDesignerInspectorPanelHost",
]
