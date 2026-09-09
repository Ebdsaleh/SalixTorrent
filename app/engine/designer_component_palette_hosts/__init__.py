"""Concrete desktop hosts for the renderer-neutral designer component palette."""

from .dearpygui import DearPyGuiDesignerComponentPaletteHost
from .tkinter import TkinterDesignerComponentPaletteHost

__all__ = [
    "DearPyGuiDesignerComponentPaletteHost",
    "TkinterDesignerComponentPaletteHost",
]
