"""Renderer-neutral interaction, selection and command-state contracts.

These provisional models deliberately contain no GUI callbacks.  They describe
selection and command availability so application policy can be tested and
reused by desktop, CLI/headless and future designer surfaces.  Concrete
presentation adapters remain responsible for translating clicks, menus and
keyboard gestures into explicit command keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


def _key(value: object, *, field: str = "key") -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


class SelectionModel:
    """Explicit single-selection state with no observer/reactive machinery."""

    def __init__(self, selected: object | None = None):
        self._selected = ""
        if selected is not None and str(selected).strip():
            self._selected = _key(selected, field="selection key")

    @property
    def selected(self) -> str:
        return self._selected

    @property
    def has_selection(self) -> bool:
        return bool(self._selected)

    def select(self, key: object) -> bool:
        resolved = _key(key, field="selection key")
        changed = resolved != self._selected
        self._selected = resolved
        return changed

    def clear(self) -> bool:
        changed = bool(self._selected)
        self._selected = ""
        return changed

    def retain(self, keys: Iterable[object]) -> bool:
        available = {str(value) for value in keys}
        if self._selected and self._selected not in available:
            return self.clear()
        return False


@dataclass(frozen=True)
class CommandSpec:
    """One semantic command or submenu node.

    ``key`` is the stable identity dispatched by application code.  ``label``
    is presentation text.  ``checked`` is optional so ordinary menu items are
    distinguishable from check/radio-style choices without backend constants.
    """

    key: str
    label: str
    enabled: bool = True
    checked: bool | None = None
    children: tuple["CommandSpec", ...] = ()

    def __init__(
        self,
        key: object,
        label: object,
        *,
        enabled: bool = True,
        checked: bool | None = None,
        children: Iterable["CommandSpec"] = (),
    ):
        resolved_children = tuple(children)
        if not all(isinstance(child, CommandSpec) for child in resolved_children):
            raise TypeError("command children must be CommandSpec instances")
        if checked is not None and not isinstance(checked, bool):
            raise TypeError("command checked state must be bool or None")
        object.__setattr__(self, "key", _key(key, field="command key"))
        object.__setattr__(self, "label", str(label))
        object.__setattr__(self, "enabled", bool(enabled))
        object.__setattr__(self, "checked", checked)
        object.__setattr__(self, "children", resolved_children)


class CommandSet:
    """Validated command tree with explicit key-based dispatch."""

    def __init__(self, commands: Iterable[CommandSpec]):
        self.commands = tuple(commands)
        if not all(isinstance(command, CommandSpec) for command in self.commands):
            raise TypeError("commands must be CommandSpec instances")
        flattened: dict[str, CommandSpec] = {}

        def visit(command: CommandSpec) -> None:
            if command.key in flattened:
                raise ValueError(f"duplicate command key: {command.key}")
            flattened[command.key] = command
            for child in command.children:
                visit(child)

        for command in self.commands:
            visit(command)
        self._by_key = flattened

    def get(self, key: object) -> CommandSpec:
        return self._by_key[_key(key, field="command key")]

    def enabled(self, key: object) -> bool:
        return self.get(key).enabled

    def dispatch(
        self,
        key: object,
        handler: Callable[[str], object],
    ) -> object:
        if not callable(handler):
            raise TypeError("command handler must be callable")
        command = self.get(key)
        if not command.enabled:
            raise RuntimeError(f"command {command.key!r} is disabled")
        if command.children:
            raise RuntimeError(f"command {command.key!r} is a submenu and cannot be dispatched")
        return handler(command.key)
