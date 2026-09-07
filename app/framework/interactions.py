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


class OrderedItems:
    """Explicit stable-key ordering model for list/tree/table-like collections.

    This is intentionally independent of any rendered list widget.  Callers
    mutate this semantic order first, persist it when appropriate, then ask a
    concrete surface to reflect the resulting key sequence.
    """

    def __init__(self, keys: Iterable[object] = ()):
        self._keys: list[str] = []
        self.replace(keys)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self._keys)

    def __len__(self) -> int:
        return len(self._keys)

    def __iter__(self):
        return iter(tuple(self._keys))

    def __contains__(self, key: object) -> bool:
        return str(key) in self._keys

    def index(self, key: object) -> int:
        return self._keys.index(_key(key, field="ordered-item key"))

    def replace(self, keys: Iterable[object]) -> bool:
        normalized = [_key(value, field="ordered-item key") for value in keys]
        if len(normalized) != len(set(normalized)):
            raise ValueError("ordered-item keys must be unique")
        changed = normalized != self._keys
        self._keys = normalized
        return changed

    def append(self, key: object) -> bool:
        resolved = _key(key, field="ordered-item key")
        if resolved in self._keys:
            return False
        self._keys.append(resolved)
        return True

    def remove(self, key: object) -> bool:
        resolved = _key(key, field="ordered-item key")
        if resolved not in self._keys:
            return False
        self._keys.remove(resolved)
        return True

    def can_move_item_up(self, key: object) -> bool:
        try:
            return self.index(key) > 0
        except ValueError:
            return False

    def can_move_item_down(self, key: object) -> bool:
        try:
            index = self.index(key)
        except ValueError:
            return False
        return index < len(self._keys) - 1

    def move_item_up(self, key: object) -> bool:
        resolved = _key(key, field="ordered-item key")
        if not self.can_move_item_up(resolved):
            return False
        index = self._keys.index(resolved)
        self._keys[index - 1], self._keys[index] = self._keys[index], self._keys[index - 1]
        return True

    def move_item_down(self, key: object) -> bool:
        resolved = _key(key, field="ordered-item key")
        if not self.can_move_item_down(resolved):
            return False
        index = self._keys.index(resolved)
        self._keys[index], self._keys[index + 1] = self._keys[index + 1], self._keys[index]
        return True

    def move_item_to(self, key: object, index: object) -> bool:
        resolved = _key(key, field="ordered-item key")
        if resolved not in self._keys:
            return False
        if isinstance(index, bool):
            raise TypeError("ordered-item target index must be an integer")
        try:
            target = int(index)
        except (TypeError, ValueError) as exc:
            raise TypeError("ordered-item target index must be an integer") from exc
        if target < 0 or target >= len(self._keys):
            raise IndexError("ordered-item target index is out of range")
        current = self._keys.index(resolved)
        if current == target:
            return False
        self._keys.pop(current)
        self._keys.insert(target, resolved)
        return True
