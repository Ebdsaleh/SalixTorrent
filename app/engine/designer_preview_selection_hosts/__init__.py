"""Concrete desktop hosts for the optional designer preview-selection surface."""

from .dearpygui import DearPyGuiDesignerPreviewSelectionHost
from .tkinter import TkinterDesignerPreviewSelectionHost

__all__ = [
    "DearPyGuiDesignerPreviewSelectionHost",
    "TkinterDesignerPreviewSelectionHost",
]
