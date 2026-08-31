"""Semantic documentation typography and presentation theme."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from .model import DocCalloutKind, DocIconKind, DocRole


DOCUMENTATION_SCALES = (90, 100, 115, 130)
DEFAULT_DOCUMENTATION_SCALE = 100
DOCUMENTATION_SCALE_LABELS = {
    90: "90% - Compact",
    100: "100% - Comfortable",
    115: "115% - Large",
    130: "130% - Extra Large",
}


def normalise_documentation_scale(value: object) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = DEFAULT_DOCUMENTATION_SCALE
    return min(DOCUMENTATION_SCALES, key=lambda scale: abs(scale - numeric))


def documentation_scale_label(value: object) -> str:
    return DOCUMENTATION_SCALE_LABELS[normalise_documentation_scale(value)]


def documentation_scale_from_label(value: object) -> int:
    text = str(value or "").strip()
    for scale, label in DOCUMENTATION_SCALE_LABELS.items():
        if text == label:
            return scale
    try:
        return normalise_documentation_scale(int(text.split("%", 1)[0]))
    except (TypeError, ValueError, IndexError):
        return DEFAULT_DOCUMENTATION_SCALE


_ROLE_DELTAS: Dict[DocRole, int] = {
    DocRole.PAGE_TITLE: 8,
    DocRole.LEAD: 1,
    DocRole.SECTION_TITLE: 3,
    DocRole.SUBSECTION_TITLE: 1,
    DocRole.BODY: 0,
    DocRole.MUTED: -1,
    DocRole.CAPTION: -1,
    DocRole.CODE: 0,
    DocRole.INDEX_HEADING: 2,
}


def role_font_size(role: DocRole, ui_font_size: int, scale_percent: int = 100) -> int:
    """Resolve a semantic role to a concrete scalable-font pixel size."""
    base = max(10, int(round(int(ui_font_size) * normalise_documentation_scale(scale_percent) / 100.0)))
    return max(11, min(36, base + _ROLE_DELTAS.get(DocRole(role), 0)))


@dataclass(frozen=True)
class DocumentationTheme:
    """Presentation tokens for a technical manual rendered by Dear PyGui."""

    page_title_color: Tuple[int, int, int] = (105, 195, 255)
    lead_color: Tuple[int, int, int] = (185, 190, 200)
    section_color: Tuple[int, int, int] = (255, 200, 100)
    subsection_color: Tuple[int, int, int] = (130, 190, 255)
    body_color: Tuple[int, int, int] = (225, 225, 230)
    muted_color: Tuple[int, int, int] = (155, 160, 170)
    caption_color: Tuple[int, int, int] = (150, 160, 175)
    code_color: Tuple[int, int, int] = (205, 220, 230)
    related_color: Tuple[int, int, int] = (105, 185, 255)
    content_max_width: int = 980
    content_min_width: int = 420
    horizontal_padding: int = 22
    section_gap: int = 14
    paragraph_gap: int = 7
    title_bottom_gap: int = 7
    lead_bottom_gap: int = 15

    def color_for_role(self, role: DocRole):
        mapping = {
            DocRole.PAGE_TITLE: self.page_title_color,
            DocRole.LEAD: self.lead_color,
            DocRole.SECTION_TITLE: self.section_color,
            DocRole.SUBSECTION_TITLE: self.subsection_color,
            DocRole.BODY: self.body_color,
            DocRole.MUTED: self.muted_color,
            DocRole.CAPTION: self.caption_color,
            DocRole.CODE: self.code_color,
            DocRole.INDEX_HEADING: self.subsection_color,
        }
        return mapping.get(DocRole(role), self.body_color)

    def color_for_callout(self, kind: DocCalloutKind):
        mapping = {
            DocCalloutKind.INFO: (105, 185, 255),
            DocCalloutKind.TIP: (110, 220, 150),
            DocCalloutKind.WARNING: (255, 200, 100),
            DocCalloutKind.SUCCESS: (100, 225, 145),
            DocCalloutKind.ERROR: (255, 120, 120),
            DocCalloutKind.NOTE: (185, 165, 255),
        }
        return mapping.get(DocCalloutKind(kind), self.related_color)


ASCII_ICON_MARKERS = {
    DocIconKind.INFO: "[i]",
    DocIconKind.TIP: "[+]",
    DocIconKind.WARNING: "[!]",
    DocIconKind.SUCCESS: "[OK]",
    DocIconKind.ERROR: "[X]",
    DocIconKind.NOTE: "[*]",
    DocIconKind.NETWORK: "[NET]",
    DocIconKind.SECURITY: "[SEC]",
    DocIconKind.PERFORMANCE: "[PERF]",
}

UNICODE_ICON_MARKERS = {
    DocIconKind.INFO: "ℹ",
    DocIconKind.TIP: "◆",
    DocIconKind.WARNING: "⚠",
    DocIconKind.SUCCESS: "✓",
    DocIconKind.ERROR: "✕",
    DocIconKind.NOTE: "●",
    DocIconKind.NETWORK: "↔",
    DocIconKind.SECURITY: "◆",
    DocIconKind.PERFORMANCE: "⚡",
}


def icon_marker(icon: DocIconKind, *, emoji: str = "", unicode_symbols: bool = False) -> str:
    """Resolve a semantic icon with a portable ASCII fallback."""
    if emoji and unicode_symbols:
        return str(emoji)
    table = UNICODE_ICON_MARKERS if unicode_symbols else ASCII_ICON_MARKERS
    return table.get(DocIconKind(icon), "[*]")
