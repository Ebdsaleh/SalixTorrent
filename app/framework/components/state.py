"""Backend-neutral runtime-state helpers for reusable GUI components.

This module intentionally stops short of an observer/data-binding framework.
It provides the small runtime lifecycle contract already proven useful by the
migrated forms: configure one component, change enabled/visible state, and
apply the same state transition to a group of components.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from .base import Component


class ComponentGroup:
    """A validated group of components that share runtime state transitions.

    Groups do not own layout or rendering.  They simply coordinate state
    changes across already-built components through the same renderer-neutral
    methods available on each component.
    """

    def __init__(self, *components: Component):
        if len(components) == 1 and not isinstance(components[0], Component):
            candidate = components[0]
            if isinstance(candidate, Iterable):
                components = tuple(candidate)
        normalized = tuple(components)
        if any(not isinstance(component, Component) for component in normalized):
            raise TypeError("component groups may contain only Component instances")
        self.components = normalized

    def __iter__(self) -> Iterator[Component]:
        return iter(self.components)

    def __len__(self) -> int:
        return len(self.components)

    def configure(self, **kwargs) -> None:
        for component in self.components:
            component.configure(**kwargs)

    def set_enabled(self, enabled: bool) -> None:
        for component in self.components:
            component.set_enabled(enabled)

    def set_visible(self, visible: bool) -> None:
        for component in self.components:
            component.set_visible(visible)
