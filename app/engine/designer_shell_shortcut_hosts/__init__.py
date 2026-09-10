"""Concrete keyboard-shortcut hosts for the optional designer shell."""

from .dearpygui import DearPyGuiDesignerShellShortcutHost
from .tkinter import TkinterDesignerShellShortcutHost

__all__ = [
    "DearPyGuiDesignerShellShortcutHost",
    "TkinterDesignerShellShortcutHost",
]
