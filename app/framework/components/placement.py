"""Backend-neutral local-placement and mixed-layout primitives.

Placement is deliberately modeled as metadata on the parent/child relationship
rather than as a global application layout mode.  An automatic parent may place
one child normally while a small wrapper applies an explicit local offset to
that child.  The wrapper reserves the child's occupied bounds so rows, columns
and other automatic layouts can still measure around positioned content.

This is the first geometry contract intended for the future visual designer.
It stays intentionally small: local x/y placement, margins, container padding
and occupied-bounds participation.  Anchors, percentages and richer constraints
remain future extensions rather than hidden policy in this foundation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .base import Component
    from .renderer import ComponentRenderer


def _non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field} must be an integer")
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field} must be an integer") from exc
    if resolved < 0:
        raise ValueError(f"{field} must be non-negative")
    return resolved


@dataclass(frozen=True)
class Insets:
    """Four non-negative edge distances in left/top/right/bottom order."""

    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "left", _non_negative_int(self.left, field="left inset"))
        object.__setattr__(self, "top", _non_negative_int(self.top, field="top inset"))
        object.__setattr__(self, "right", _non_negative_int(self.right, field="right inset"))
        object.__setattr__(self, "bottom", _non_negative_int(self.bottom, field="bottom inset"))

    @property
    def horizontal(self) -> int:
        return self.left + self.right

    @property
    def vertical(self) -> int:
        return self.top + self.bottom


def insets(value: Insets | int | tuple[int, int] | tuple[int, int, int, int] = 0) -> Insets:
    """Normalize a compact margin/padding value.

    ``int`` applies to every edge, ``(horizontal, vertical)`` applies the first
    value to left/right and the second to top/bottom, and four values are
    interpreted as left/top/right/bottom.
    """

    if isinstance(value, Insets):
        return value
    if isinstance(value, bool):
        raise TypeError("insets must be an integer, Insets, 2-tuple or 4-tuple")
    if isinstance(value, int):
        return Insets(value, value, value, value)
    try:
        parts = tuple(value)
    except TypeError as exc:
        raise TypeError("insets must be an integer, Insets, 2-tuple or 4-tuple") from exc
    if len(parts) == 2:
        horizontal, vertical = parts
        return Insets(horizontal, vertical, horizontal, vertical)
    if len(parts) == 4:
        return Insets(*parts)
    raise ValueError("insets tuple must contain 2 or 4 values")


@dataclass(frozen=True)
class Placement:
    """Local child placement relative to its parent's assigned content origin.

    ``affects_layout`` controls whether the positioned child's occupied bounds
    contribute to parent measurement. Normal positioned content uses ``True``;
    overlays such as badges, HUD labels and drag handles can opt out while still
    sharing the same parent-local coordinate system.
    """

    x: int = 0
    y: int = 0
    margin: Insets = Insets()
    affects_layout: bool = True

    def __init__(
        self,
        x: object = 0,
        y: object = 0,
        *,
        margin: Insets | int | tuple[int, int] | tuple[int, int, int, int] = 0,
        affects_layout: bool = True,
    ):
        object.__setattr__(self, "x", _non_negative_int(x, field="placement x"))
        object.__setattr__(self, "y", _non_negative_int(y, field="placement y"))
        object.__setattr__(self, "margin", insets(margin))
        object.__setattr__(self, "affects_layout", bool(affects_layout))

    @property
    def local_x(self) -> int:
        return self.x + self.margin.left

    @property
    def local_y(self) -> int:
        return self.y + self.margin.top

    def occupied_size(self, child_width: object, child_height: object) -> tuple[int, int]:
        width = _non_negative_int(child_width, field="child width")
        height = _non_negative_int(child_height, field="child height")
        return (
            self.local_x + width + self.margin.right,
            self.local_y + height + self.margin.bottom,
        )


@dataclass(frozen=True)
class PositionedChild:
    """One component plus its placement inside a :class:`PositionedPanel`."""

    component: "Component"
    placement: Placement

    def __init__(
        self,
        component: "Component",
        *,
        x: object = 0,
        y: object = 0,
        margin: Insets | int | tuple[int, int] | tuple[int, int, int, int] = 0,
        placement: Placement | None = None,
        affects_layout: bool = True,
    ):
        from .base import Component

        if not isinstance(component, Component):
            raise TypeError("positioned child must wrap a Component")
        object.__setattr__(self, "component", component)
        if placement is not None and not isinstance(placement, Placement):
            raise TypeError("placement must be a Placement")
        object.__setattr__(
            self,
            "placement",
            placement if placement is not None else Placement(
                x, y, margin=margin, affects_layout=affects_layout
            ),
        )


def positioned(
    component: "Component",
    *,
    x: object = 0,
    y: object = 0,
    margin: Insets | int | tuple[int, int] | tuple[int, int, int, int] = 0,
    affects_layout: bool = True,
) -> PositionedChild:
    """Convenience constructor for children of ``PositionedPanel``."""

    return PositionedChild(
        component,
        x=x,
        y=y,
        margin=margin,
        affects_layout=affects_layout,
    )


def overlay(
    component: "Component",
    *,
    x: object = 0,
    y: object = 0,
    margin: Insets | int | tuple[int, int] | tuple[int, int, int, int] = 0,
) -> PositionedChild:
    """Create a positioned child that does not enlarge its parent."""

    return positioned(
        component,
        x=x,
        y=y,
        margin=margin,
        affects_layout=False,
    )


def component_size_hint(component: "Component", renderer: "ComponentRenderer") -> tuple[int, int]:
    """Return deterministic semantic width/height hints when explicitly known."""

    width, height = component.layout_size_hint(renderer=renderer)
    return max(0, int(width or 0)), max(0, int(height or 0))


def occupied_extent(
    children: Iterable[PositionedChild],
    renderer: "ComponentRenderer",
    *,
    padding: Insets | int | tuple[int, int] | tuple[int, int, int, int] = 0,
) -> tuple[int, int]:
    """Compute the minimum occupied bounds from semantic child size hints."""

    pad = insets(padding)
    width = pad.horizontal
    height = pad.vertical
    for child in tuple(children):
        if not isinstance(child, PositionedChild):
            raise TypeError("occupied_extent children must be PositionedChild instances")
        if not child.placement.affects_layout:
            continue
        child_width, child_height = component_size_hint(child.component, renderer)
        occupied_width, occupied_height = child.placement.occupied_size(
            child_width,
            child_height,
        )
        width = max(width, pad.left + occupied_width + pad.right)
        height = max(height, pad.top + occupied_height + pad.bottom)
    return width, height
