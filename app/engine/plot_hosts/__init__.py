"""Concrete realtime-plot hosts used by desktop presentation backends."""

from .dearpygui import DearPyGuiPlotHost
from .tkinter import TkinterPlotHost

__all__ = ["DearPyGuiPlotHost", "TkinterPlotHost"]
