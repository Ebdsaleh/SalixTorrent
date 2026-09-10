"""Backend-neutral keyboard shortcut bridge for optional designer shells.

The semantic command tree already owns command availability and dispatch.  This
module adds a deliberately small shortcut surface that maps normalized keyboard
gestures onto those existing command keys.  It owns no document, selection,
history, hierarchy, preview, project or toolkit state.

Concrete hosts translate native key events into the normalized gesture strings
used here.  Disabled semantic commands are inert when reached through a
shortcut, which keeps ordinary key presses from surfacing command-state
exceptions while still revalidating availability at dispatch time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Protocol, runtime_checkable

from .designer_shell import (
    DESIGNER_DUPLICATE_COMMAND,
    DESIGNER_MOVE_DOWN_COMMAND,
    DESIGNER_MOVE_UP_COMMAND,
    DESIGNER_REMOVE_COMMAND,
    DesignerShellCommandRequest,
    DesignerShellCommands,
)


def _gesture(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("designer shortcut gesture must be non-empty")
    parts = [part.strip() for part in text.replace("-", "+").split("+") if part.strip()]
    aliases = {
        "control": "Ctrl",
        "ctrl": "Ctrl",
        "alt": "Alt",
        "option": "Alt",
        "shift": "Shift",
        "delete": "Delete",
        "del": "Delete",
        "up": "Up",
        "down": "Down",
    }
    normalized = []
    for part in parts:
        key = part.lower()
        normalized.append(aliases.get(key, part.upper() if len(part) == 1 else part.title()))
    modifiers = [name for name in ("Ctrl", "Alt", "Shift") if name in normalized]
    keys = [name for name in normalized if name not in {"Ctrl", "Alt", "Shift"}]
    if len(keys) != 1:
        raise ValueError("designer shortcut gesture must contain exactly one key")
    return "+".join((*modifiers, keys[0]))


@dataclass(frozen=True)
class DesignerShellShortcutSpec:
    """One normalized keyboard gesture mapped to an existing shell command."""

    gesture: str
    command_key: str
    label: str

    def __init__(self, gesture: object, command_key: object, label: object = ""):
        resolved_command = str(command_key or "").strip()
        if not resolved_command:
            raise ValueError("designer shortcut command key must be non-empty")
        object.__setattr__(self, "gesture", _gesture(gesture))
        object.__setattr__(self, "command_key", resolved_command)
        object.__setattr__(self, "label", str(label or resolved_command))

    def to_descriptor(self) -> dict[str, str]:
        return {
            "gesture": self.gesture,
            "command_key": self.command_key,
            "label": self.label,
        }


DEFAULT_DESIGNER_SHELL_SHORTCUTS = (
    DesignerShellShortcutSpec("Ctrl+D", DESIGNER_DUPLICATE_COMMAND, "Duplicate"),
    DesignerShellShortcutSpec("Ctrl+Delete", DESIGNER_REMOVE_COMMAND, "Remove"),
    DesignerShellShortcutSpec("Alt+Up", DESIGNER_MOVE_UP_COMMAND, "Move Up"),
    DesignerShellShortcutSpec("Alt+Down", DESIGNER_MOVE_DOWN_COMMAND, "Move Down"),
)


@dataclass
class DesignerShellShortcutBinding:
    """Opaque host-owned native shortcut registration."""

    handle: object
    gestures: tuple[str, ...]
    metadata: object | None = None


@runtime_checkable
class DesignerShellShortcutHost(Protocol):
    """Concrete adapter contract consumed by :class:`DesignerShellShortcuts`."""

    def build(
        self,
        shortcuts: tuple[DesignerShellShortcutSpec, ...],
        *,
        on_gesture: Callable[[str], object],
    ) -> DesignerShellShortcutBinding:
        ...

    def exists(self, binding: DesignerShellShortcutBinding) -> bool:
        ...

    def dispose(self, binding: DesignerShellShortcutBinding) -> None:
        ...


DesignerShellShortcutRequestHandler = Callable[[DesignerShellCommandRequest], object]
DesignerShellShortcutResultHandler = Callable[[str, object], object]


def _host_errors(host: object) -> tuple[str, ...]:
    required = ("build", "exists", "dispose")
    return tuple(name for name in required if not callable(getattr(host, name, None)))


class DesignerShellShortcuts:
    """Bind native keyboard gestures to the existing semantic designer shell."""

    def __init__(
        self,
        shell: DesignerShellCommands,
        host: DesignerShellShortcutHost,
        *,
        shortcuts: Iterable[DesignerShellShortcutSpec] = DEFAULT_DESIGNER_SHELL_SHORTCUTS,
        on_request: DesignerShellShortcutRequestHandler | None = None,
        on_result: DesignerShellShortcutResultHandler | None = None,
    ):
        if not isinstance(shell, DesignerShellCommands):
            raise TypeError("designer shell shortcuts require DesignerShellCommands")
        errors = _host_errors(host)
        if errors:
            raise TypeError("designer shell shortcut host is missing: " + ", ".join(errors))
        if on_request is not None and not callable(on_request):
            raise TypeError("designer shortcut request handler must be callable")
        if on_result is not None and not callable(on_result):
            raise TypeError("designer shortcut result handler must be callable")

        specs = tuple(shortcuts)
        if not specs or not all(isinstance(spec, DesignerShellShortcutSpec) for spec in specs):
            raise TypeError("designer shell shortcuts must be DesignerShellShortcutSpec instances")
        gestures = [spec.gesture for spec in specs]
        if len(gestures) != len(set(gestures)):
            raise ValueError("designer shortcut gestures must be unique")
        for spec in specs:
            shell.command(spec.command_key)

        self._shell = shell
        self._host = host
        self._shortcuts = specs
        self._by_gesture = {spec.gesture: spec for spec in specs}
        self._on_request = on_request
        self._on_result = on_result
        self._binding: DesignerShellShortcutBinding | None = None

    @property
    def shell(self) -> DesignerShellCommands:
        return self._shell

    @property
    def shortcuts(self) -> tuple[DesignerShellShortcutSpec, ...]:
        return self._shortcuts

    @property
    def binding(self) -> DesignerShellShortcutBinding | None:
        return self._binding

    def build(self) -> DesignerShellShortcutBinding:
        if self._binding is not None and self.exists():
            return self._binding
        self._binding = self._host.build(self._shortcuts, on_gesture=self.dispatch_gesture)
        if not isinstance(self._binding, DesignerShellShortcutBinding):
            raise TypeError("designer shell shortcut host returned an invalid binding")
        return self._binding

    def exists(self) -> bool:
        return bool(self._binding is not None and self._host.exists(self._binding))

    def dispatch_gesture(self, gesture: object):
        """Dispatch a currently-enabled semantic command for one normalized gesture."""

        resolved = _gesture(gesture)
        try:
            spec = self._by_gesture[resolved]
        except KeyError as exc:
            raise KeyError(f"designer shortcut gesture is not bound: {resolved}") from exc
        command = self._shell.command(spec.command_key)
        if not command.enabled:
            return False
        result = self._shell.dispatch(spec.command_key)
        if isinstance(result, DesignerShellCommandRequest) and self._on_request is not None:
            result = self._on_request(result)
        if self._on_result is not None:
            self._on_result(spec.command_key, result)
        return result

    def dispose(self) -> bool:
        binding = self._binding
        if binding is None:
            return False
        self._binding = None
        self._host.dispose(binding)
        return True

    def to_descriptor(self) -> dict[str, object]:
        return {"shortcuts": [spec.to_descriptor() for spec in self._shortcuts]}


__all__ = [
    "DEFAULT_DESIGNER_SHELL_SHORTCUTS",
    "DesignerShellShortcutBinding",
    "DesignerShellShortcutHost",
    "DesignerShellShortcutRequestHandler",
    "DesignerShellShortcutResultHandler",
    "DesignerShellShortcutSpec",
    "DesignerShellShortcuts",
]
