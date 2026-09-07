"""Renderer-neutral semantic command-menu coordination.

``CommandSet`` describes what actions exist.  This module describes how that
semantic tree is presented as one reusable popup/menu surface without teaching
application code about a concrete toolkit.  Applications still own command
consequences; the menu only dispatches stable command keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from .interactions import CommandSet


@dataclass
class CommandMenuBinding:
    """Opaque host-owned menu binding plus optional item lookup metadata."""

    menu: object
    items: dict[str, object]
    title_item: object | None = None


@runtime_checkable
class CommandMenuHost(Protocol):
    def build(
        self,
        commands: CommandSet,
        *,
        title: str = "",
        on_command: Callable[[str], object],
    ) -> CommandMenuBinding:
        ...

    def update(self, binding: CommandMenuBinding, commands: CommandSet) -> None:
        ...

    def show(self, binding: CommandMenuBinding) -> None:
        ...

    def hide(self, binding: CommandMenuBinding) -> None:
        ...

    def exists(self, binding: CommandMenuBinding) -> bool:
        ...

    def dispose(self, binding: CommandMenuBinding) -> None:
        ...


def _host_errors(host: object) -> tuple[str, ...]:
    required = ("build", "update", "show", "hide", "exists", "dispose")
    return tuple(name for name in required if not callable(getattr(host, name, None)))


class CommandMenu:
    """Explicit command-tree presenter with no automatic/reactive state."""

    def __init__(
        self,
        host: CommandMenuHost,
        *,
        on_command: Callable[[str], object],
        title: str = "",
    ):
        missing = _host_errors(host)
        if missing:
            raise TypeError(
                "command-menu host does not satisfy CommandMenuHost; missing: "
                + ", ".join(missing)
            )
        if not callable(on_command):
            raise TypeError("command-menu callback must be callable")
        self.host = host
        self.on_command = on_command
        self.title = str(title)
        self.commands: CommandSet | None = None
        self.binding: CommandMenuBinding | None = None

    def build(self, commands: CommandSet) -> CommandMenuBinding:
        if not isinstance(commands, CommandSet):
            raise TypeError("command menu requires a CommandSet")
        if self.binding is not None and self.exists():
            self.dispose()
        self.commands = commands
        self.binding = self.host.build(
            commands,
            title=self.title,
            on_command=self._dispatch,
        )
        return self.binding

    def _dispatch(self, key: str):
        if self.commands is None:
            raise RuntimeError("command menu has no command set")
        return self.commands.dispatch(key, self.on_command)

    def update(self, commands: CommandSet) -> None:
        if not isinstance(commands, CommandSet):
            raise TypeError("command menu requires a CommandSet")
        if self.binding is None or not self.exists():
            self.build(commands)
            return
        self.commands = commands
        self.host.update(self.binding, commands)

    def show(self) -> None:
        if self.binding is None or not self.exists():
            raise RuntimeError("command menu has not been built")
        self.host.show(self.binding)

    def hide(self) -> None:
        if self.binding is not None and self.exists():
            self.host.hide(self.binding)

    def exists(self) -> bool:
        return self.binding is not None and bool(self.host.exists(self.binding))

    def dispose(self) -> bool:
        if self.binding is None:
            return False
        binding = self.binding
        existed = bool(self.host.exists(binding))
        if existed:
            self.host.dispose(binding)
        self.binding = None
        self.commands = None
        return existed
