"""Explicit synchronous value bindings for reusable GUI components.

Bindings deliberately avoid observer/reactive semantics.  They provide a small,
backend-neutral bridge between named application values and ``ValueComponent``
instances.  Applications decide when to collect from controls and when to apply
model values back to controls; no background mutation or implicit subscription is
performed by this module.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

from .base import ValueComponent
from ..property_cascade import UNSET


def _identity(value):
    return value


class ValueBinding:
    """One explicit mapping key bound to one rendered value component.

    ``read_transform`` converts the component value to the application/model
    representation.  ``write_transform`` performs the inverse presentation
    conversion when a mapping is applied back to the control.  ``default`` is
    used only when collecting an empty/``None`` component value or when applying
    a mapping that omits the key.
    """

    def __init__(
        self,
        key: str,
        component: ValueComponent,
        *,
        read_transform: Callable[[Any], Any] | None = None,
        write_transform: Callable[[Any], Any] | None = None,
        default=UNSET,
    ):
        normalized_key = str(key).strip()
        if not normalized_key:
            raise ValueError("binding key must not be empty")
        if not isinstance(component, ValueComponent):
            raise TypeError("value bindings require a ValueComponent")
        if read_transform is not None and not callable(read_transform):
            raise TypeError("read_transform must be callable")
        if write_transform is not None and not callable(write_transform):
            raise TypeError("write_transform must be callable")

        self.key = normalized_key
        self.component = component
        self.read_transform = read_transform or _identity
        self.write_transform = write_transform or _identity
        self.default = default

    def read(self):
        value = self.component.get_value()
        if (value is None or value == "") and self.default is not UNSET:
            value = self.default
        return self.read_transform(value)

    def write(self, values: Mapping[str, Any]) -> bool:
        if self.key in values:
            value = values[self.key]
        elif self.default is not UNSET:
            value = self.default
        else:
            return False
        self.component.set_value(self.write_transform(value))
        return True


class BindingSet:
    """Validated set of explicit bindings collected/applied on demand."""

    def __init__(self, *bindings: ValueBinding):
        if len(bindings) == 1 and not isinstance(bindings[0], ValueBinding):
            candidate = bindings[0]
            if isinstance(candidate, Iterable):
                bindings = tuple(candidate)
        normalized = tuple(bindings)
        if any(not isinstance(binding, ValueBinding) for binding in normalized):
            raise TypeError("binding sets may contain only ValueBinding instances")
        keys = tuple(binding.key for binding in normalized)
        if len(set(keys)) != len(keys):
            raise ValueError("binding keys must be unique within one BindingSet")
        self.bindings = normalized

    def __iter__(self) -> Iterator[ValueBinding]:
        return iter(self.bindings)

    def __len__(self) -> int:
        return len(self.bindings)

    def collect(self) -> dict[str, Any]:
        return {binding.key: binding.read() for binding in self.bindings}

    def apply(self, values: Mapping[str, Any]) -> tuple[str, ...]:
        applied = []
        for binding in self.bindings:
            if binding.write(values):
                applied.append(binding.key)
        return tuple(applied)
