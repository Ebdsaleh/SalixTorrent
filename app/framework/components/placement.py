"""Backend-neutral local-placement and mixed-layout primitives.

Placement is deliberately modeled as metadata on the parent/child relationship
rather than as a global application layout mode.  An automatic parent may place
one child normally while a small wrapper applies an explicit local offset to
that child.  The wrapper reserves the child's occupied bounds so rows, columns
and other automatic layouts can still measure around positioned content.

This geometry contract is intended to remain useful to a future visual designer.
It supports fixed local x/y placement, edge/centre/stretch anchoring, margins,
minimum/maximum size constraints, non-measuring overlays and JSON-safe placement
descriptors. Percentage geometry and a complete designer document model remain
future extensions rather than hidden policy in this foundation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Iterable, Mapping

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




class AxisAnchor(str, Enum):
    """How a child is positioned on one parent-local axis."""

    START = "start"
    CENTER = "center"
    END = "end"
    STRETCH = "stretch"


@dataclass(frozen=True)
class SizeConstraints:
    """Optional minimum/maximum extents for responsive local placement."""

    minimum_width: int = 0
    minimum_height: int = 0
    maximum_width: int | None = None
    maximum_height: int | None = None

    def __post_init__(self) -> None:
        min_width = _non_negative_int(self.minimum_width, field="minimum width")
        min_height = _non_negative_int(self.minimum_height, field="minimum height")
        object.__setattr__(self, "minimum_width", min_width)
        object.__setattr__(self, "minimum_height", min_height)
        for name, minimum in (("maximum_width", min_width), ("maximum_height", min_height)):
            value = getattr(self, name)
            if value is None:
                continue
            maximum = _non_negative_int(value, field=name.replace("_", " "))
            if maximum < minimum:
                raise ValueError(f"{name.replace('_', ' ')} must be >= its minimum")
            object.__setattr__(self, name, maximum)

    def constrain_width(self, width: object) -> int:
        value = max(self.minimum_width, _non_negative_int(width, field="width"))
        if self.maximum_width is not None:
            value = min(value, self.maximum_width)
        return value

    def constrain_height(self, height: object) -> int:
        value = max(self.minimum_height, _non_negative_int(height, field="height"))
        if self.maximum_height is not None:
            value = min(value, self.maximum_height)
        return value

    def constrain(self, width: object, height: object) -> tuple[int, int]:
        return self.constrain_width(width), self.constrain_height(height)

    def to_descriptor(self) -> dict[str, int | None]:
        return {
            "minimum_width": self.minimum_width,
            "minimum_height": self.minimum_height,
            "maximum_width": self.maximum_width,
            "maximum_height": self.maximum_height,
        }

    @classmethod
    def from_descriptor(cls, value: Mapping[str, object] | None) -> "SizeConstraints":
        data = dict(value or {})
        return cls(
            minimum_width=data.get("minimum_width", 0),
            minimum_height=data.get("minimum_height", 0),
            maximum_width=data.get("maximum_width"),
            maximum_height=data.get("maximum_height"),
        )


@dataclass(frozen=True)
class ResolvedPlacement:
    """Concrete parent-local rectangle produced by responsive placement."""

    x: int
    y: int
    width: int
    height: int


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

    def to_descriptor(self) -> dict[str, object]:
        return {
            "kind": "fixed",
            "x": self.x,
            "y": self.y,
            "margin": [self.margin.left, self.margin.top, self.margin.right, self.margin.bottom],
            "affects_layout": self.affects_layout,
        }


@dataclass(frozen=True)
class AnchoredPlacement:
    """Responsive parent-local placement using edge/centre anchor semantics.

    Margins are edge offsets inside the parent's content rectangle. ``STRETCH``
    consumes the available axis between both edge offsets; minimum/maximum
    constraints are applied after that responsive target is calculated.
    """

    horizontal: AxisAnchor = AxisAnchor.START
    vertical: AxisAnchor = AxisAnchor.START
    margin: Insets = Insets()
    constraints: SizeConstraints = SizeConstraints()
    affects_layout: bool = True

    def __init__(
        self,
        *,
        horizontal: AxisAnchor | str = AxisAnchor.START,
        vertical: AxisAnchor | str = AxisAnchor.START,
        margin: Insets | int | tuple[int, int] | tuple[int, int, int, int] = 0,
        constraints: SizeConstraints | None = None,
        affects_layout: bool = True,
    ):
        object.__setattr__(self, "horizontal", AxisAnchor(str(getattr(horizontal, "value", horizontal)).lower()))
        object.__setattr__(self, "vertical", AxisAnchor(str(getattr(vertical, "value", vertical)).lower()))
        object.__setattr__(self, "margin", insets(margin))
        if constraints is not None and not isinstance(constraints, SizeConstraints):
            raise TypeError("constraints must be SizeConstraints or None")
        object.__setattr__(self, "constraints", constraints or SizeConstraints())
        object.__setattr__(self, "affects_layout", bool(affects_layout))

    @staticmethod
    def _axis(
        parent_size: int,
        child_size: int,
        anchor: AxisAnchor,
        start_offset: int,
        end_offset: int,
        constrain,
    ) -> tuple[int, int]:
        available = max(0, int(parent_size) - int(start_offset) - int(end_offset))
        requested = available if anchor is AxisAnchor.STRETCH else child_size
        size = constrain(requested)
        if anchor is AxisAnchor.END:
            origin = max(int(start_offset), int(parent_size) - int(end_offset) - size)
        elif anchor is AxisAnchor.CENTER:
            origin = int(start_offset) + max(0, (available - size) // 2)
        else:
            origin = int(start_offset)
        return origin, size

    def resolve(
        self,
        parent_width: object,
        parent_height: object,
        child_width: object,
        child_height: object,
    ) -> ResolvedPlacement:
        width = _non_negative_int(parent_width, field="parent width")
        height = _non_negative_int(parent_height, field="parent height")
        natural_width = _non_negative_int(child_width, field="child width")
        natural_height = _non_negative_int(child_height, field="child height")
        x, resolved_width = self._axis(
            width, natural_width, self.horizontal, self.margin.left, self.margin.right,
            self.constraints.constrain_width,
        )
        y, resolved_height = self._axis(
            height, natural_height, self.vertical, self.margin.top, self.margin.bottom,
            self.constraints.constrain_height,
        )
        return ResolvedPlacement(x, y, resolved_width, resolved_height)

    @property
    def controls_width(self) -> bool:
        return (
            self.horizontal is AxisAnchor.STRETCH
            or self.constraints.minimum_width > 0
            or self.constraints.maximum_width is not None
        )

    @property
    def controls_height(self) -> bool:
        return (
            self.vertical is AxisAnchor.STRETCH
            or self.constraints.minimum_height > 0
            or self.constraints.maximum_height is not None
        )

    def minimum_size(self, child_width: object, child_height: object) -> tuple[int, int]:
        width, height = self.constraints.constrain(child_width, child_height)
        return self.margin.horizontal + width, self.margin.vertical + height

    def to_descriptor(self) -> dict[str, object]:
        return {
            "kind": "anchored",
            "horizontal": self.horizontal.value,
            "vertical": self.vertical.value,
            "margin": [self.margin.left, self.margin.top, self.margin.right, self.margin.bottom],
            "constraints": self.constraints.to_descriptor(),
            "affects_layout": self.affects_layout,
        }


@dataclass(frozen=True)
class AnchoredChild:
    component: "Component"
    placement: AnchoredPlacement

    def __init__(
        self,
        component: "Component",
        *,
        horizontal: AxisAnchor | str = AxisAnchor.START,
        vertical: AxisAnchor | str = AxisAnchor.START,
        margin: Insets | int | tuple[int, int] | tuple[int, int, int, int] = 0,
        constraints: SizeConstraints | None = None,
        placement: AnchoredPlacement | None = None,
        affects_layout: bool = True,
    ):
        from .base import Component

        if not isinstance(component, Component):
            raise TypeError("anchored child must wrap a Component")
        if placement is not None and not isinstance(placement, AnchoredPlacement):
            raise TypeError("placement must be AnchoredPlacement")
        object.__setattr__(self, "component", component)
        object.__setattr__(
            self,
            "placement",
            placement if placement is not None else AnchoredPlacement(
                horizontal=horizontal,
                vertical=vertical,
                margin=margin,
                constraints=constraints,
                affects_layout=affects_layout,
            ),
        )


def anchored(
    component: "Component",
    *,
    horizontal: AxisAnchor | str = AxisAnchor.START,
    vertical: AxisAnchor | str = AxisAnchor.START,
    margin: Insets | int | tuple[int, int] | tuple[int, int, int, int] = 0,
    constraints: SizeConstraints | None = None,
    affects_layout: bool = True,
) -> AnchoredChild:
    return AnchoredChild(
        component,
        horizontal=horizontal,
        vertical=vertical,
        margin=margin,
        constraints=constraints,
        affects_layout=affects_layout,
    )


def anchored_overlay(
    component: "Component",
    *,
    horizontal: AxisAnchor | str = AxisAnchor.END,
    vertical: AxisAnchor | str = AxisAnchor.START,
    margin: Insets | int | tuple[int, int] | tuple[int, int, int, int] = 0,
    constraints: SizeConstraints | None = None,
) -> AnchoredChild:
    return anchored(
        component,
        horizontal=horizontal,
        vertical=vertical,
        margin=margin,
        constraints=constraints,
        affects_layout=False,
    )


def placement_from_descriptor(value: Mapping[str, object]) -> Placement | AnchoredPlacement:
    """Restore JSON-safe placement metadata without importing a GUI backend."""

    data = dict(value)
    kind = str(data.get("kind", "")).strip().lower()
    margin_value = data.get("margin", 0)
    if kind == "fixed":
        return Placement(
            data.get("x", 0),
            data.get("y", 0),
            margin=margin_value,
            affects_layout=bool(data.get("affects_layout", True)),
        )
    if kind == "anchored":
        constraints_value = data.get("constraints")
        if constraints_value is not None and not isinstance(constraints_value, Mapping):
            raise TypeError("anchored placement constraints descriptor must be a mapping")
        return AnchoredPlacement(
            horizontal=data.get("horizontal", AxisAnchor.START.value),
            vertical=data.get("vertical", AxisAnchor.START.value),
            margin=margin_value,
            constraints=SizeConstraints.from_descriptor(constraints_value),
            affects_layout=bool(data.get("affects_layout", True)),
        )
    raise ValueError(f"unknown placement descriptor kind: {kind!r}")


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
