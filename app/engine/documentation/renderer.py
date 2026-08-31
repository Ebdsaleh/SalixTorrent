"""Dear PyGui renderer for the semantic documentation model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    import dearpygui.dearpygui as dpg
except ModuleNotFoundError:  # pragma: no cover - renderer is GUI-only
    dpg = None  # type: ignore[assignment]

from app.engine.responsive_layout import (
    ContentMetrics,
    HorizontalAlign,
    ResponsiveLayout,
    aligned_offset,
    content_bounds,
)
from app.engine.ui_typography import UiTypography

from .model import (
    DocBlock,
    DocCallout,
    DocCodeBlock,
    DocIconLine,
    DocLink,
    DocLinks,
    DocMedia,
    DocMediaKind,
    DocPage,
    DocParagraph,
    DocRole,
)
from .typography import (
    DocumentationTheme,
    icon_marker,
    normalise_documentation_scale,
    role_font_size,
)


@dataclass
class _RenderedText:
    item: object
    role: DocRole
    wrap: bool = True
    centered: bool = False
    extra_indent: int = 0


@dataclass
class _RenderedWidth:
    item: object
    extra_indent: int = 0


@dataclass
class _RenderedAnchor:
    item: object
    extra_indent: int = 0


@dataclass
class _RenderedMedia:
    item: object
    native_width: int
    native_height: int
    maximum_width: int
    maximum_height: int


class DocumentationMediaCache:
    """Lazy image texture cache owned by the documentation renderer layer.

    Static images are supported now.  Animation/video are represented by the
    semantic model but intentionally degrade to explanatory fallbacks until a
    real timed decoder/player backend exists.
    """

    def __init__(self):
        self._registry = None
        self._textures: dict[str, tuple[object, int, int]] = {}

    def load_image(self, source: str):
        if dpg is None:
            return None
        path = str(Path(source).expanduser())
        cached = self._textures.get(path)
        if cached is not None:
            return cached
        try:
            width, height, channels, data = dpg.load_image(path)
            del channels
            if self._registry is None or not dpg.does_item_exist(self._registry):
                self._registry = dpg.add_texture_registry(show=False)
            texture = dpg.add_static_texture(width, height, data, parent=self._registry)
            result = (texture, int(width), int(height))
            self._textures[path] = result
            return result
        except Exception:
            return None


class DocumentationRenderer:
    """Render and reflow semantic documentation inside one parent container."""

    def __init__(
        self,
        parent,
        *,
        layout: Optional[ResponsiveLayout] = None,
        theme: Optional[DocumentationTheme] = None,
        scale_percent: int = 100,
        unicode_symbols: bool = False,
        on_link: Optional[Callable[[str], None]] = None,
        tooltip: Optional[Callable[[object, str], None]] = None,
    ):
        self.parent = parent
        self.layout = layout or ResponsiveLayout.get_instance()
        self.theme = theme or DocumentationTheme()
        self.typography = UiTypography.get_instance()
        self.scale_percent = normalise_documentation_scale(scale_percent)
        self.unicode_symbols = bool(unicode_symbols)
        self.on_link = on_link
        self.tooltip = tooltip
        self.media = DocumentationMediaCache()
        self._text_items: list[_RenderedText] = []
        self._width_items: list[_RenderedWidth] = []
        self._anchor_items: list[_RenderedAnchor] = []
        self._media_items: list[_RenderedMedia] = []
        self._last_parent_width = 0
        self._last_bounds = None

    def set_scale(self, value: object):
        new_value = normalise_documentation_scale(value)
        if new_value == self.scale_percent:
            return
        self.scale_percent = new_value
        self.refresh_typography()
        self.reflow(force=True)

    def clear(self):
        if dpg is not None:
            try:
                dpg.delete_item(self.parent, children_only=True)
            except Exception:
                pass
        self._text_items.clear()
        self._width_items.clear()
        self._anchor_items.clear()
        self._media_items.clear()

    def _font_size(self, role: DocRole) -> int:
        return role_font_size(role, self.typography.current_size, self.scale_percent)

    def _bind(self, item, role: DocRole):
        try:
            self.typography.bind_item_font(item, self._font_size(role))
        except Exception:
            pass

    def _add_text(
        self,
        text: str,
        role: DocRole,
        *,
        wrap: bool = True,
        centered: bool = False,
        extra_indent: int = 0,
        parent=None,
    ):
        if dpg is None:
            return None
        item = dpg.add_text(
            str(text),
            color=self.theme.color_for_role(role),
            wrap=1 if wrap else 0,
            parent=self.parent if parent is None else parent,
        )
        self._text_items.append(
            _RenderedText(
                item=item,
                role=DocRole(role),
                wrap=wrap,
                centered=centered,
                extra_indent=max(0, int(extra_indent)),
            )
        )
        self._bind(item, role)
        return item

    def render_page(self, page: DocPage):
        self.clear()
        self._add_text(page.title, DocRole.PAGE_TITLE, wrap=False, centered=True)
        if dpg is not None:
            dpg.add_spacer(height=self.theme.title_bottom_gap, parent=self.parent)
        if page.lead:
            self._add_text(page.lead, DocRole.LEAD, wrap=True)
            if dpg is not None:
                dpg.add_spacer(height=self.theme.lead_bottom_gap, parent=self.parent)

        for block in page.blocks:
            self._render_block(block)

        for section in page.sections:
            if dpg is not None:
                dpg.add_spacer(height=4, parent=self.parent)
            self._add_text(section.title, DocRole.SECTION_TITLE, wrap=True)
            if dpg is not None:
                dpg.add_spacer(height=5, parent=self.parent)
            for block in section.blocks:
                self._render_block(block)
            if dpg is not None:
                dpg.add_spacer(height=self.theme.section_gap, parent=self.parent)

        self.refresh_typography()
        self.reflow(force=True)

    def _render_block(self, block: DocBlock):
        if isinstance(block, DocParagraph):
            self._add_text(block.text, block.role, wrap=True)
            if dpg is not None:
                dpg.add_spacer(height=self.theme.paragraph_gap, parent=self.parent)
            return
        if isinstance(block, DocCodeBlock):
            self._render_code(block)
            return
        if isinstance(block, DocIconLine):
            self._render_icon_line(block)
            return
        if isinstance(block, DocCallout):
            self._render_callout(block)
            return
        if isinstance(block, DocMedia):
            self._render_media(block)
            return
        if isinstance(block, DocLinks):
            self._render_links(block)
            return

    def _render_icon_line(self, block: DocIconLine):
        marker = icon_marker(
            block.icon,
            emoji=block.emoji,
            unicode_symbols=self.unicode_symbols,
        )
        self._add_text(f"{marker}  {block.text}", DocRole.BODY, wrap=True)
        if dpg is not None:
            dpg.add_spacer(height=self.theme.paragraph_gap, parent=self.parent)

    def _render_callout(self, block: DocCallout):
        marker = icon_marker(
            block.icon,
            emoji=block.emoji,
            unicode_symbols=self.unicode_symbols,
        )
        title = block.title.strip() or block.kind.value.title()
        if dpg is None:
            return
        heading = dpg.add_text(
            f"{marker}  {title}",
            color=self.theme.color_for_callout(block.kind),
            parent=self.parent,
        )
        self._text_items.append(_RenderedText(heading, DocRole.SUBSECTION_TITLE, False, False, 8))
        self._bind(heading, DocRole.SUBSECTION_TITLE)
        body = dpg.add_text(
            block.body,
            color=self.theme.body_color,
            wrap=1,
            parent=self.parent,
        )
        self._text_items.append(_RenderedText(body, DocRole.BODY, True, False, 22))
        self._bind(body, DocRole.BODY)
        dpg.add_spacer(height=self.theme.paragraph_gap, parent=self.parent)

    def _render_code(self, block: DocCodeBlock):
        if dpg is None:
            return
        if block.caption:
            self._add_text(block.caption, DocRole.CAPTION, wrap=True)
        line_count = max(1, str(block.text).count("\n") + 1)
        height = max(52, min(360, line_count * (self._font_size(DocRole.CODE) + 5) + 18))
        item = dpg.add_input_text(
            default_value=block.text,
            multiline=True,
            readonly=True,
            height=height,
            width=300,
            parent=self.parent,
        )
        self._width_items.append(_RenderedWidth(item))
        self._text_items.append(_RenderedText(item, DocRole.CODE, False, False, 0))
        self._bind(item, DocRole.CODE)
        dpg.add_spacer(height=self.theme.paragraph_gap, parent=self.parent)

    def _render_media(self, block: DocMedia):
        if dpg is None:
            return
        if block.kind is not DocMediaKind.IMAGE:
            self._render_callout(
                DocCallout(
                    title=f"{block.kind.value.title()} media",
                    body=(
                        block.alt_text
                        or block.caption
                        or "This document declares rich media here, but this build does not yet provide a timed animation/video playback backend."
                    ),
                )
            )
            return
        loaded = self.media.load_image(block.source)
        if loaded is None:
            self._render_callout(
                DocCallout(
                    title="Image unavailable",
                    body=block.alt_text or block.caption or str(block.source),
                )
            )
            return
        texture, width, height = loaded
        item = dpg.add_image(texture, width=width, height=height, parent=self.parent)
        self._media_items.append(
            _RenderedMedia(
                item=item,
                native_width=width,
                native_height=height,
                maximum_width=max(1, int(block.maximum_width)),
                maximum_height=max(1, int(block.maximum_height)),
            )
        )
        if block.caption:
            self._add_text(block.caption, DocRole.CAPTION, wrap=True, centered=True)
        dpg.add_spacer(height=self.theme.paragraph_gap, parent=self.parent)

    def _render_links(self, block: DocLinks):
        if dpg is None or not block.links:
            return
        if block.title.strip():
            self._add_text(block.title, DocRole.SUBSECTION_TITLE, wrap=True)
        rows = [block.links[index:index + 3] for index in range(0, len(block.links), 3)]
        for links in rows:
            row = dpg.add_group(horizontal=True, parent=self.parent)
            self._anchor_items.append(_RenderedAnchor(row))
            for link in links:
                item = dpg.add_button(
                    label=f" {link.label} ",
                    parent=row,
                    callback=self._on_link_clicked,
                    user_data=link.target,
                )
                if self.tooltip and link.tooltip:
                    try:
                        self.tooltip(item, link.tooltip)
                    except Exception:
                        pass
        dpg.add_spacer(height=self.theme.paragraph_gap, parent=self.parent)

    def _on_link_clicked(self, sender=None, app_data=None, user_data=None):
        del sender, app_data
        if self.on_link is not None and user_data is not None:
            self.on_link(str(user_data))

    def refresh_typography(self):
        alive: list[_RenderedText] = []
        for record in self._text_items:
            if dpg is not None:
                try:
                    if not dpg.does_item_exist(record.item):
                        continue
                except Exception:
                    continue
            self._bind(record.item, record.role)
            alive.append(record)
        self._text_items = alive

    def _measure_text(self, text: str, role: DocRole) -> int:
        return self.typography.measure_text_width(text, self._font_size(role))

    @staticmethod
    def _fit_media(native_width: int, native_height: int, max_width: int, max_height: int) -> tuple[int, int]:
        width = max(1, int(native_width))
        height = max(1, int(native_height))
        scale = min(1.0, max(1, int(max_width)) / width, max(1, int(max_height)) / height)
        return max(1, int(width * scale)), max(1, int(height * scale))

    def reflow(self, width: Optional[int] = None, *, force: bool = False):
        if dpg is None:
            return
        if width is None:
            width, _height = self.layout.item_size(self.parent)
        width = max(0, int(width or 0))
        if width <= 1:
            return
        if not force and abs(width - self._last_parent_width) < 4:
            return
        self._last_parent_width = width
        bounds = content_bounds(
            width,
            metrics=ContentMetrics(
                horizontal_padding=self.theme.horizontal_padding,
                minimum_width=self.theme.content_min_width,
                maximum_width=self.theme.content_max_width,
            ),
        )
        self._last_bounds = bounds

        alive_text: list[_RenderedText] = []
        for record in self._text_items:
            try:
                if not dpg.does_item_exist(record.item):
                    continue
            except Exception:
                continue
            if record.centered:
                try:
                    value = str(dpg.get_value(record.item) or "")
                except Exception:
                    value = ""
                measured = min(bounds.width, self._measure_text(value, record.role))
                indent = bounds.x + aligned_offset(bounds.width, measured, HorizontalAlign.CENTER)
            else:
                indent = bounds.x + record.extra_indent
            self.layout.indent(record.item, indent)
            if record.wrap:
                self.layout.wrap(record.item, max(120, bounds.width - record.extra_indent))
            alive_text.append(record)
        self._text_items = alive_text

        alive_width: list[_RenderedWidth] = []
        for record in self._width_items:
            try:
                if not dpg.does_item_exist(record.item):
                    continue
            except Exception:
                continue
            self.layout.indent(record.item, bounds.x + record.extra_indent)
            self.layout.width(record.item, max(120, bounds.width - record.extra_indent))
            alive_width.append(record)
        self._width_items = alive_width

        alive_anchor: list[_RenderedAnchor] = []
        for record in self._anchor_items:
            try:
                if not dpg.does_item_exist(record.item):
                    continue
            except Exception:
                continue
            self.layout.indent(record.item, bounds.x + record.extra_indent)
            alive_anchor.append(record)
        self._anchor_items = alive_anchor

        alive_media: list[_RenderedMedia] = []
        for record in self._media_items:
            try:
                if not dpg.does_item_exist(record.item):
                    continue
            except Exception:
                continue
            target_width, target_height = self._fit_media(
                record.native_width,
                record.native_height,
                min(bounds.width, record.maximum_width),
                record.maximum_height,
            )
            indent = bounds.x + aligned_offset(bounds.width, target_width, HorizontalAlign.CENTER)
            self.layout.indent(record.item, indent)
            self.layout.size(record.item, target_width, target_height)
            alive_media.append(record)
        self._media_items = alive_media
