"""Backend-neutral layout policy for reusable GUI components.

The component layer follows the same configuration precedence already used by
the documentation framework::

    framework default -> active theme -> explicit instance override

Dimensions use semantic values instead of leaking Dear PyGui's integer sizing
conventions into framework-facing code. ``AUTO`` asks the backend to use its
natural size and ``FILL`` asks it to occupy the remaining space on that axis.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.engine.property_cascade import (
    UNSET,
    PropertySource,
    RejectedPropertyCandidate,
    resolve_property,
)


class DimensionMode(str, Enum):
    AUTO = "auto"
    FILL = "fill"


AUTO = DimensionMode.AUTO
FILL = DimensionMode.FILL


@dataclass(frozen=True)
class ControlLayoutDefaults:
    """Safe framework-owned layout defaults."""

    width: int | DimensionMode = AUTO
    height: int | DimensionMode = AUTO
    spacing: int | None = None


DEFAULT_CONTROL_LAYOUT = ControlLayoutDefaults()


@dataclass(frozen=True)
class ControlLayoutTheme:
    """Sparse active-theme overrides for a reusable component."""

    width: object = UNSET
    height: object = UNSET
    spacing: object = UNSET


@dataclass(frozen=True)
class ControlLayout:
    """Sparse explicit per-instance component overrides."""

    width: object = UNSET
    height: object = UNSET
    spacing: object = UNSET


@dataclass(frozen=True)
class ResolvedControlLayout:
    width: int | DimensionMode
    height: int | DimensionMode
    spacing: int | None
    sources: tuple[tuple[str, PropertySource], ...] = ()
    rejected: tuple[tuple[str, RejectedPropertyCandidate], ...] = ()

    def source_for(self, name: str) -> PropertySource | None:
        return dict(self.sources).get(str(name))


def _dimension_valid(value: object) -> bool:
    if isinstance(value, DimensionMode):
        return True
    if isinstance(value, str):
        return value.strip().lower() in {member.value for member in DimensionMode}
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _dimension_normalise(value: object) -> int | DimensionMode:
    if isinstance(value, DimensionMode):
        return value
    if isinstance(value, str):
        return DimensionMode(value.strip().lower())
    return int(value)


def _spacing_valid(value: object) -> bool:
    return value is None or (
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
    )


def _spacing_normalise(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def resolve_control_layout(
    *,
    theme: ControlLayoutTheme | None = None,
    override: ControlLayout | None = None,
    defaults: ControlLayoutDefaults = DEFAULT_CONTROL_LAYOUT,
) -> ResolvedControlLayout:
    """Resolve width/height/spacing independently with provenance."""

    active_theme = theme or ControlLayoutTheme()
    instance = override or ControlLayout()

    width = resolve_property(
        default=defaults.width,
        theme=active_theme.width,
        override=instance.width,
        validator=_dimension_valid,
        normalizer=_dimension_normalise,
    )
    height = resolve_property(
        default=defaults.height,
        theme=active_theme.height,
        override=instance.height,
        validator=_dimension_valid,
        normalizer=_dimension_normalise,
    )
    spacing = resolve_property(
        default=defaults.spacing,
        theme=active_theme.spacing,
        override=instance.spacing,
        validator=_spacing_valid,
        normalizer=_spacing_normalise,
    )

    results = {"width": width, "height": height, "spacing": spacing}
    return ResolvedControlLayout(
        width=width.value,
        height=height.value,
        spacing=spacing.value,
        sources=tuple((name, result.source) for name, result in results.items()),
        rejected=tuple(
            (name, rejection)
            for name, result in results.items()
            for rejection in result.rejected
        ),
    )


def backend_dimension(value: int | DimensionMode) -> int | None:
    """Translate a semantic dimension into common backend sizing semantics.

    ``None`` means "omit the dimension and let the backend choose its natural
    size".  ``-1`` is deliberately confined to the backend bridge as the
    conventional Dear PyGui fill value.
    """

    if value is AUTO:
        return None
    if value is FILL:
        return -1
    return int(value)
