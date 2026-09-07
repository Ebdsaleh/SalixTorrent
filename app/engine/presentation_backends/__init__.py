"""Composition factories for concrete presentation backends."""

from .dearpygui import create_dearpygui_backend
from .headless import create_headless_backend
from .tkinter import create_tkinter_backend

__all__ = [
    "create_dearpygui_backend",
    "create_headless_backend",
    "create_tkinter_backend",
]
