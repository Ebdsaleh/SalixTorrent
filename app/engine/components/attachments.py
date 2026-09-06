"""Reusable renderer-adjacent component attachments.

Attachments are callable objects consumed by :meth:`Component.attach`.  They
remain independent of Dear PyGui and delegate backend work through the active
component renderer.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.components.renderer import ComponentRenderer


@dataclass(frozen=True)
class Tooltip:
    """Attach explanatory text to a rendered component item."""

    text: str
    wrap: int = 450

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", str(self.text))
        object.__setattr__(self, "wrap", max(1, int(self.wrap)))

    def __call__(self, item: object, renderer: ComponentRenderer) -> None:
        text = self.text.strip()
        if not text:
            return
        renderer.attach_tooltip(item, text, wrap=self.wrap)
