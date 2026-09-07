"""Concrete live-table presentation hosts."""

from .dearpygui import DearPyGuiTableHost
from .tkinter import TkinterTableHost

__all__ = ["DearPyGuiTableHost", "TkinterTableHost"]
