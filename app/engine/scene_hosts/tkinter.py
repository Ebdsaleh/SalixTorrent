"""Tkinter scene-visibility adapter for the reusable scene registry."""

from __future__ import annotations

from app.engine.component_renderers.tkinter import TkinterRenderer


class TkinterSceneHost:
    def __init__(self, renderer: TkinterRenderer):
        if not isinstance(renderer, TkinterRenderer):
            raise TypeError("TkinterSceneHost requires a TkinterRenderer")
        self.renderer = renderer

    def exists(self, container: object) -> bool:
        return bool(self.renderer.exists(container))

    def show(self, container: object) -> None:
        self.renderer.configure(container, show=True)

    def hide(self, container: object) -> None:
        self.renderer.configure(container, show=False)
