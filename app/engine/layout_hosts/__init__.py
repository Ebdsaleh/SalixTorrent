"""Concrete layout-host adapters for desktop presentation backends."""

from .dearpygui import DearPyGuiLayoutHost
from .tkinter import TkinterLayoutHost

__all__ = ["DearPyGuiLayoutHost", "TkinterLayoutHost"]
