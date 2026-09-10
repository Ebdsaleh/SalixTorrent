"""Concrete desktop hosts for the optional designer preview-resize surface."""

from .dearpygui import DearPyGuiDesignerPreviewResizeHost
from .tkinter import TkinterDesignerPreviewResizeHost

__all__ = [
    "DearPyGuiDesignerPreviewResizeHost",
    "TkinterDesignerPreviewResizeHost",
]
