"""Shared numeric drag/scrub translation for designer direct manipulation.

This module is toolkit-neutral.  Concrete hosts provide pointer deltas and
modifier state; the helper applies one deterministic sensitivity contract and
property bounds.  Semantic document mutation still belongs to the existing
DesignerWorkspace/property-edit path.
"""
from __future__ import annotations

from dataclasses import dataclass

from .designer_inspector import DesignerInspectorEditorKind, DesignerInspectorRow


@dataclass(frozen=True)
class DesignerDragModifiers:
    shift: bool = False
    ctrl: bool = False

    @property
    def scale(self) -> float:
        # Shift wins if both are held: a deliberate coarse gesture should not
        # collapse back to normal because Ctrl is also down.
        if self.shift:
            return 10.0
        if self.ctrl:
            return 0.1
        return 1.0


def is_scrubbable_row(row: DesignerInspectorRow) -> bool:
    return bool(
        isinstance(row, DesignerInspectorRow)
        and row.can_edit
        and row.editor in {
            DesignerInspectorEditorKind.INTEGER,
            DesignerInspectorEditorKind.NUMBER,
            DesignerInspectorEditorKind.DIMENSION,
        }
    )


def _clamp(value: float, row: DesignerInspectorRow) -> float:
    result = float(value)
    if row.minimum is not None:
        result = max(result, float(row.minimum))
    if row.maximum is not None:
        result = min(result, float(row.maximum))
    return result


def translate_numeric_drag(
    row: DesignerInspectorRow,
    base_value: int | float,
    pointer_delta: int | float,
    modifiers: DesignerDragModifiers | None = None,
) -> int | float:
    """Translate horizontal pointer movement into one candidate property value."""

    if not is_scrubbable_row(row):
        raise TypeError(f"designer property {row.key!r} is not numerically scrubbable")
    if isinstance(base_value, bool) or not isinstance(base_value, (int, float)):
        raise TypeError("designer numeric drag base value must be numeric")
    if isinstance(pointer_delta, bool) or not isinstance(pointer_delta, (int, float)):
        raise TypeError("designer numeric drag pointer delta must be numeric")

    scale = (modifiers or DesignerDragModifiers()).scale
    candidate = _clamp(float(base_value) + float(pointer_delta) * scale, row)
    if row.editor in {DesignerInspectorEditorKind.INTEGER, DesignerInspectorEditorKind.DIMENSION}:
        # Integer fields accumulate fractional Ctrl motion because rounding is
        # applied to the total displacement from drag start, not every event.
        return int(round(candidate))
    return float(candidate)


__all__ = [
    "DesignerDragModifiers",
    "is_scrubbable_row",
    "translate_numeric_drag",
]
