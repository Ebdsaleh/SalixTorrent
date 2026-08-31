"""Semantic document model used by SalixTorrent's offline documentation.

The model deliberately contains no Dear PyGui calls.  Content describes what an
item *means*; the renderer decides how that meaning should look in the current
container, theme and typography scale.  This separation is what makes the
subsystem suitable for later extraction into a reusable DPG framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple

from .layout import DocLayout


class DocRole(str, Enum):
    PAGE_TITLE = "page_title"
    LEAD = "lead"
    SECTION_TITLE = "section_title"
    SUBSECTION_TITLE = "subsection_title"
    BODY = "body"
    MUTED = "muted"
    CAPTION = "caption"
    CODE = "code"
    INDEX_HEADING = "index_heading"


class DocCalloutKind(str, Enum):
    INFO = "info"
    TIP = "tip"
    WARNING = "warning"
    SUCCESS = "success"
    ERROR = "error"
    NOTE = "note"


class DocIconKind(str, Enum):
    INFO = "info"
    TIP = "tip"
    WARNING = "warning"
    SUCCESS = "success"
    ERROR = "error"
    NOTE = "note"
    NETWORK = "network"
    SECURITY = "security"
    PERFORMANCE = "performance"


class DocMediaKind(str, Enum):
    IMAGE = "image"
    ANIMATION = "animation"
    VIDEO = "video"


@dataclass(frozen=True)
class DocParagraph:
    text: str
    role: DocRole = DocRole.BODY


@dataclass(frozen=True)
class DocCodeBlock:
    text: str
    language: str = ""
    caption: str = ""


@dataclass(frozen=True)
class DocIconLine:
    text: str
    icon: DocIconKind = DocIconKind.INFO
    emoji: str = ""


@dataclass(frozen=True)
class DocCallout:
    body: str
    title: str = ""
    kind: DocCalloutKind = DocCalloutKind.INFO
    icon: DocIconKind = DocIconKind.INFO
    emoji: str = ""


@dataclass(frozen=True)
class DocMedia:
    source: str
    kind: DocMediaKind = DocMediaKind.IMAGE
    caption: str = ""
    alt_text: str = ""
    maximum_width: int = 900
    maximum_height: int = 700


@dataclass(frozen=True)
class DocLink:
    label: str
    target: str
    tooltip: str = ""


@dataclass(frozen=True)
class DocLinks:
    title: str
    links: Tuple[DocLink, ...]


DocBlock = DocParagraph | DocCodeBlock | DocIconLine | DocCallout | DocMedia | DocLinks


@dataclass(frozen=True)
class DocSection:
    title: str
    blocks: Tuple[DocBlock, ...]


@dataclass(frozen=True)
class DocPage:
    title: str
    lead: str = ""
    sections: Tuple[DocSection, ...] = ()
    blocks: Tuple[DocBlock, ...] = ()
    layout: DocLayout = field(default_factory=DocLayout)
