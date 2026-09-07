"""Named layout profiles for reusable GUI components.

The component model keeps concrete widget dimensions out of view code.  A
renderer carries one :class:`ComponentLayoutProfile`; components select a
named profile slot and still retain the normal configuration precedence::

    profile/default -> component theme -> explicit instance override

Profiles are backend-neutral.  They contain semantic layout defaults and
optional non-layout metrics such as fixed grid-column widths.  Application
code may supply its own profile while the framework profile always provides a
safe AUTO-sized fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Sequence

from .layout import DEFAULT_CONTROL_LAYOUT, ControlLayoutDefaults


def _freeze_layouts(values: Mapping[str, ControlLayoutDefaults]) -> Mapping[str, ControlLayoutDefaults]:
    normalized: dict[str, ControlLayoutDefaults] = {}
    for key, value in values.items():
        name = str(key).strip()
        if not name:
            raise ValueError("component-profile layout keys must not be empty")
        if not isinstance(value, ControlLayoutDefaults):
            raise TypeError("component-profile layouts must use ControlLayoutDefaults")
        normalized[name] = value
    return MappingProxyType(normalized)


def _freeze_columns(values: Mapping[str, Sequence[int]]) -> Mapping[str, tuple[int, ...]]:
    normalized: dict[str, tuple[int, ...]] = {}
    for key, widths in values.items():
        name = str(key).strip()
        if not name:
            raise ValueError("component-profile column keys must not be empty")
        resolved = tuple(int(value) for value in widths)
        if not resolved or any(value <= 0 for value in resolved):
            raise ValueError("component-profile column widths must be positive")
        normalized[name] = resolved
    return MappingProxyType(normalized)


@dataclass(frozen=True)
class ComponentLayoutProfile:
    """Immutable named layout defaults carried by a component renderer.

    ``layouts`` maps arbitrary semantic keys to safe component defaults.
    ``columns`` stores fixed column-width tuples used by aligned composites.
    Missing keys fall back through ``parent`` and finally to the framework's
    AUTO-sized default rather than raising during view construction.
    """

    name: str = "framework-default"
    layouts: Mapping[str, ControlLayoutDefaults] = field(default_factory=dict)
    columns: Mapping[str, Sequence[int]] = field(default_factory=dict)
    parent: "ComponentLayoutProfile | None" = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name).strip() or "unnamed")
        object.__setattr__(self, "layouts", _freeze_layouts(self.layouts))
        object.__setattr__(self, "columns", _freeze_columns(self.columns))
        if self.parent is not None and not isinstance(self.parent, ComponentLayoutProfile):
            raise TypeError("component-profile parent must be another ComponentLayoutProfile")

    def layout_for(
        self,
        key: str | None,
        *,
        fallback_key: str | None = None,
        fallback: ControlLayoutDefaults = DEFAULT_CONTROL_LAYOUT,
    ) -> ControlLayoutDefaults:
        for candidate in (key, fallback_key):
            if candidate:
                name = str(candidate)
                if name in self.layouts:
                    return self.layouts[name]
                if self.parent is not None:
                    inherited = self.parent._find_layout(name)
                    if inherited is not None:
                        return inherited
        return fallback

    def _find_layout(self, key: str) -> ControlLayoutDefaults | None:
        if key in self.layouts:
            return self.layouts[key]
        if self.parent is not None:
            return self.parent._find_layout(key)
        return None

    def columns_for(
        self,
        key: str | None,
        *,
        fallback: Sequence[int] = (),
    ) -> tuple[int, ...]:
        if key:
            name = str(key)
            if name in self.columns:
                return tuple(self.columns[name])
            if self.parent is not None:
                inherited = self.parent._find_columns(name)
                if inherited is not None:
                    return inherited
        return tuple(int(value) for value in fallback)

    def _find_columns(self, key: str) -> tuple[int, ...] | None:
        if key in self.columns:
            return tuple(self.columns[key])
        if self.parent is not None:
            return self.parent._find_columns(key)
        return None


FRAMEWORK_COMPONENT_PROFILE = ComponentLayoutProfile(
    layouts={
        "component": DEFAULT_CONTROL_LAYOUT,
        "label": DEFAULT_CONTROL_LAYOUT,
        "button": DEFAULT_CONTROL_LAYOUT,
        "combo_box": DEFAULT_CONTROL_LAYOUT,
        "text_input": DEFAULT_CONTROL_LAYOUT,
        "numeric_stepper": DEFAULT_CONTROL_LAYOUT,
        "checkbox": DEFAULT_CONTROL_LAYOUT,
        "spacer": DEFAULT_CONTROL_LAYOUT,
        "separator": DEFAULT_CONTROL_LAYOUT,
        "progress_bar": DEFAULT_CONTROL_LAYOUT,
        "section_panel": DEFAULT_CONTROL_LAYOUT,
        "dialog": DEFAULT_CONTROL_LAYOUT,
        "control_row": DEFAULT_CONTROL_LAYOUT,
        "control_column": DEFAULT_CONTROL_LAYOUT,
        "control_grid": DEFAULT_CONTROL_LAYOUT,
        "placed_component": DEFAULT_CONTROL_LAYOUT,
        "positioned_panel": DEFAULT_CONTROL_LAYOUT,
        # Composite-internal defaults preserve the dimensions established by
        # the first two GUI-component tranches without forcing view code to
        # repeat them.
        "numeric_unit.value": ControlLayoutDefaults(width=110),
        "numeric_unit.unit": ControlLayoutDefaults(width=90),
        "duration_editor.input": ControlLayoutDefaults(width=120),
        "duration_editor.grid": ControlLayoutDefaults(width=250),
    },
    columns={
        "duration_editor.columns": (80, 150),
    },
)
