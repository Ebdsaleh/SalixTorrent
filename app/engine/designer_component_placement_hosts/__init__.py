"""Concrete desktop hosts for the backend-neutral designer placement surface."""

from .dearpygui import DearPyGuiDesignerComponentPlacementHost
from .tkinter import TkinterDesignerComponentPlacementHost

__all__ = [
    "DearPyGuiDesignerComponentPlacementHost",
    "TkinterDesignerComponentPlacementHost",
]
