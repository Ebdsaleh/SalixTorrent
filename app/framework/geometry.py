"""Backend-neutral geometry primitives for reusable framework surfaces.

These helpers contain no renderer or application dependencies. Concrete GUI
adapters may re-export them while owning resize/event integration separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

Number = int | float


class HorizontalAlign(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class VerticalAlign(str, Enum):
    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"


@dataclass(frozen=True)
class ContentBounds:
    """Parent-relative rectangle used by reusable responsive components.

    Dear PyGui does not provide a CSS-like layout model.  Components therefore
    receive an explicit content rectangle and calculate their own alignment
    inside that rectangle.  ``x``/``y`` are local to the current parent, not the
    operating-system viewport.
    """

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass(frozen=True)
class ContentMetrics:
    """Policy for a centered, readable content region inside a parent."""

    horizontal_padding: int = 18
    vertical_padding: int = 0
    minimum_width: int = 320
    maximum_width: int = 980


def aligned_offset(container_size: Number, item_size: Number, alignment: HorizontalAlign | VerticalAlign | str) -> int:
    """Return the parent-relative offset for one axis alignment."""
    container = max(0, int(container_size))
    item = max(0, min(container, int(item_size)))
    value = str(getattr(alignment, "value", alignment)).lower()
    if value in {"center", "middle"}:
        return max(0, (container - item) // 2)
    if value in {"right", "bottom", "end"}:
        return max(0, container - item)
    return 0


def content_bounds(
    container_width: Number,
    container_height: Number = 0,
    *,
    metrics: ContentMetrics = ContentMetrics(),
) -> ContentBounds:
    """Return a centered readable rectangle within the supplied parent size.

    The maximum width prevents documentation/body text from becoming an
    unreadably long line on large monitors.  Narrow windows gracefully use all
    available width instead of overflowing the parent.
    """
    width = max(1, int(container_width))
    height = max(0, int(container_height))
    hpad = max(0, int(metrics.horizontal_padding))
    vpad = max(0, int(metrics.vertical_padding))
    available = max(1, width - (hpad * 2))
    preferred = min(max(1, int(metrics.maximum_width)), available)
    if available >= int(metrics.minimum_width):
        preferred = max(int(metrics.minimum_width), preferred)
    else:
        preferred = available
    x = aligned_offset(width, preferred, HorizontalAlign.CENTER)
    inner_height = max(0, height - (vpad * 2))
    return ContentBounds(x=x, y=vpad, width=preferred, height=inner_height)


def clamp(value: Number, minimum: Number, maximum: Number) -> int:
    """Clamp *value* to an inclusive integer range."""
    lo = int(minimum)
    hi = max(lo, int(maximum))
    return max(lo, min(hi, int(value)))


def split_sizes(
    total_size: Number,
    weights: Sequence[Number],
    *,
    minimums: Sequence[Number] | None = None,
    gap: Number = 8,
) -> tuple[int, ...]:
    """Return stable pixel extents for one axis of a responsive split.

    ``weights`` describe the preferred proportions. ``minimums`` are treated
    as preferred lower bounds while enough space exists. If the available axis
    is narrower than the sum of those bounds, the bounds are scaled together so
    every pane remains visible rather than overflowing unpredictably.
    """
    count = len(weights)
    if count == 0:
        return ()
    if any(float(weight) < 0 for weight in weights):
        raise ValueError("split weights must be non-negative")

    min_values = [0] * count if minimums is None else [max(0, int(v)) for v in minimums]
    if len(min_values) != count:
        raise ValueError("minimums must match weights")

    available = max(count, int(total_size) - max(0, count - 1) * int(gap))
    min_total = sum(min_values)

    if min_total >= available and min_total > 0:
        raw = [available * value / min_total for value in min_values]
    else:
        remaining = available - min_total
        weight_total = sum(float(weight) for weight in weights)
        if weight_total <= 0:
            raw = [value + remaining / count for value in min_values]
        else:
            raw = [
                min_values[index] + remaining * float(weights[index]) / weight_total
                for index in range(count)
            ]

    sizes = [max(1, int(value)) for value in raw]
    sizes[-1] += available - sum(sizes)
    return tuple(sizes)


def split_widths(
    total_width: Number,
    weights: Sequence[Number],
    *,
    minimums: Sequence[Number] | None = None,
    gap: Number = 8,
) -> tuple[int, ...]:
    """Compatibility helper for horizontal splits."""
    return split_sizes(total_width, weights, minimums=minimums, gap=gap)


def fill_height(container_height: Number, reserved_height: Number, *, minimum: Number = 1) -> int:
    """Height available to a growable content region after fixed chrome."""
    return max(int(minimum), int(container_height) - int(reserved_height))


@dataclass(frozen=True)
class DialogMetrics:
    """Geometry policy for a resizable data/content dialog."""

    reserved_height: int
    minimum_content_height: int = 80
    horizontal_margin: int = 48
    minimum_wrap: int = 260
    maximum_wrap: int = 1400
