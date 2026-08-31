"""Documentation layout policy and cascade resolution.

The semantic document model describes content; this module describes how a
page is allowed to occupy its current parent.  Layout configuration is resolved
before any physical constraints are applied, preserving the distinction
between an invalid property (fallback) and a valid property that merely needs
to contract inside a smaller runtime container.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.property_cascade import (
    UNSET,
    PropertySource,
    RejectedPropertyCandidate,
    ResolvedProperty,
    resolve_property,
)
from app.engine.responsive_layout import ContentBounds, HorizontalAlign, aligned_offset


@dataclass(frozen=True)
class DocumentationLayoutDefaults:
    """Hard-coded safe defaults owned by the framework primitive."""

    maximum_width: int | None = 980
    minimum_width: int = 420
    margin_left: int = 12
    margin_right: int = 12
    margin_top: int = 0
    margin_bottom: int = 0
    padding_left: int = 22
    padding_right: int = 22
    padding_top: int = 0
    padding_bottom: int = 0
    document_alignment: HorizontalAlign = HorizontalAlign.CENTER
    title_alignment: HorizontalAlign = HorizontalAlign.CENTER
    media_alignment: HorizontalAlign = HorizontalAlign.CENTER


DEFAULT_DOCUMENTATION_LAYOUT = DocumentationLayoutDefaults()


@dataclass(frozen=True)
class DocumentationLayoutTheme:
    """Sparse active-theme overrides for documentation geometry."""

    maximum_width: object = UNSET
    minimum_width: object = UNSET
    margin_left: object = UNSET
    margin_right: object = UNSET
    margin_top: object = UNSET
    margin_bottom: object = UNSET
    padding_left: object = UNSET
    padding_right: object = UNSET
    padding_top: object = UNSET
    padding_bottom: object = UNSET
    document_alignment: object = UNSET
    title_alignment: object = UNSET
    media_alignment: object = UNSET


@dataclass(frozen=True)
class DocLayout:
    """Sparse explicit per-page overrides.

    ``UNSET`` means inherit.  ``None`` is intentionally available as an
    explicit semantic value where supported; for ``maximum_width`` it means
    that this page has no configured maximum and may fill the available width.
    """

    maximum_width: object = UNSET
    minimum_width: object = UNSET
    margin_left: object = UNSET
    margin_right: object = UNSET
    margin_top: object = UNSET
    margin_bottom: object = UNSET
    padding_left: object = UNSET
    padding_right: object = UNSET
    padding_top: object = UNSET
    padding_bottom: object = UNSET
    document_alignment: object = UNSET
    title_alignment: object = UNSET
    media_alignment: object = UNSET


@dataclass(frozen=True)
class ResolvedDocumentationLayout:
    maximum_width: int | None
    minimum_width: int
    margin_left: int
    margin_right: int
    margin_top: int
    margin_bottom: int
    padding_left: int
    padding_right: int
    padding_top: int
    padding_bottom: int
    document_alignment: HorizontalAlign
    title_alignment: HorizontalAlign
    media_alignment: HorizontalAlign
    sources: tuple[tuple[str, PropertySource], ...] = ()
    rejected: tuple[tuple[str, RejectedPropertyCandidate], ...] = ()

    def source_for(self, name: str) -> PropertySource | None:
        return dict(self.sources).get(str(name))


@dataclass(frozen=True)
class DocumentationBounds:
    """Effective runtime rectangles after current-parent constraints."""

    document: ContentBounds
    content: ContentBounds


_LAYOUT_FIELDS = (
    "maximum_width",
    "minimum_width",
    "margin_left",
    "margin_right",
    "margin_top",
    "margin_bottom",
    "padding_left",
    "padding_right",
    "padding_top",
    "padding_bottom",
    "document_alignment",
    "title_alignment",
    "media_alignment",
)


def _non_negative(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _maximum_width_valid(value: object) -> bool:
    return value is None or _positive(value)


def _alignment_valid(value: object) -> bool:
    try:
        HorizontalAlign(str(getattr(value, "value", value)).lower())
        return True
    except (TypeError, ValueError):
        return False


def _alignment_normalise(value: object) -> HorizontalAlign:
    return HorizontalAlign(str(getattr(value, "value", value)).lower())


def _resolve_field(
    name: str,
    defaults: DocumentationLayoutDefaults,
    theme: DocumentationLayoutTheme,
    override: DocLayout,
) -> ResolvedProperty:
    default = getattr(defaults, name)
    theme_value = getattr(theme, name)
    override_value = getattr(override, name)
    if name == "maximum_width":
        return resolve_property(
            default=default,
            theme=theme_value,
            override=override_value,
            validator=_maximum_width_valid,
        )
    if name == "minimum_width":
        return resolve_property(
            default=default,
            theme=theme_value,
            override=override_value,
            validator=_positive,
            normalizer=int,
        )
    if name.endswith("alignment"):
        return resolve_property(
            default=default,
            theme=theme_value,
            override=override_value,
            validator=_alignment_valid,
            normalizer=_alignment_normalise,
        )
    return resolve_property(
        default=default,
        theme=theme_value,
        override=override_value,
        validator=_non_negative,
        normalizer=int,
    )


def resolve_documentation_layout(
    *,
    theme: DocumentationLayoutTheme | None = None,
    override: DocLayout | None = None,
    defaults: DocumentationLayoutDefaults = DEFAULT_DOCUMENTATION_LAYOUT,
) -> ResolvedDocumentationLayout:
    """Resolve concrete configuration while preserving property provenance."""
    active_theme = theme or DocumentationLayoutTheme()
    instance = override or DocLayout()
    results = {
        name: _resolve_field(name, defaults, active_theme, instance)
        for name in _LAYOUT_FIELDS
    }
    sources = tuple((name, result.source) for name, result in results.items())
    rejected = tuple(
        (name, rejection)
        for name, result in results.items()
        for rejection in result.rejected
    )
    values = {name: result.value for name, result in results.items()}
    return ResolvedDocumentationLayout(
        **values,
        sources=sources,
        rejected=rejected,
    )


def _fit_insets(first: int, second: int, capacity: int) -> tuple[int, int]:
    """Fit two valid insets into current geometry without changing config."""
    first = max(0, int(first))
    second = max(0, int(second))
    capacity = max(0, int(capacity))
    total = first + second
    if total <= capacity:
        return first, second
    if total <= 0 or capacity <= 0:
        return 0, 0
    scale = capacity / total
    fitted_first = int(first * scale)
    fitted_second = capacity - fitted_first
    return fitted_first, fitted_second


def documentation_bounds(
    container_width: int,
    container_height: int = 0,
    *,
    layout: ResolvedDocumentationLayout,
) -> DocumentationBounds:
    """Constrain a valid layout policy against the current parent bounds.

    No fallback happens here.  A configured 1400 px maximum remains 1400 px in
    the resolved policy even if the current pane is only 700 px wide; only the
    *effective* rectangle contracts.  When the pane grows, the same policy can
    expand again without being re-resolved.
    """
    width = max(1, int(container_width))
    height = max(0, int(container_height))

    margin_left, margin_right = _fit_insets(
        layout.margin_left,
        layout.margin_right,
        max(0, width - 1),
    )
    horizontal_available = max(1, width - margin_left - margin_right)
    configured_max = horizontal_available if layout.maximum_width is None else int(layout.maximum_width)
    target_width = min(configured_max, horizontal_available)
    effective_minimum = min(int(layout.minimum_width), configured_max)
    if horizontal_available >= effective_minimum:
        target_width = max(effective_minimum, target_width)
    else:
        target_width = horizontal_available

    document_x = margin_left + aligned_offset(
        horizontal_available,
        target_width,
        layout.document_alignment,
    )

    margin_top, margin_bottom = _fit_insets(
        layout.margin_top,
        layout.margin_bottom,
        max(0, height - 1),
    ) if height > 0 else (0, 0)
    document_height = max(0, height - margin_top - margin_bottom)
    document = ContentBounds(
        x=document_x,
        y=margin_top,
        width=max(1, target_width),
        height=document_height,
    )

    padding_left, padding_right = _fit_insets(
        layout.padding_left,
        layout.padding_right,
        max(0, document.width - 1),
    )
    padding_top, padding_bottom = _fit_insets(
        layout.padding_top,
        layout.padding_bottom,
        max(0, document.height - 1),
    ) if document.height > 0 else (0, 0)

    content = ContentBounds(
        x=document.x + padding_left,
        y=document.y + padding_top,
        width=max(1, document.width - padding_left - padding_right),
        height=max(0, document.height - padding_top - padding_bottom),
    )
    return DocumentationBounds(document=document, content=content)
