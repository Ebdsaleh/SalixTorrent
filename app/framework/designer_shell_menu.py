"""Concrete command-menu presentation bridge for optional designer tooling.

The v0.5.1 checkpoint completed the backend-neutral designer semantic core.
This module starts the next extraction sequence by binding
``DesignerShellCommands`` to the already-existing ``CommandMenu`` presenter.
It deliberately owns no editor state and imports no concrete GUI toolkit.

A Dear PyGui or Tkinter application supplies its normal ``CommandMenuHost``.
The bridge rebuilds command availability immediately before presentation and
revalidates dispatch through ``DesignerShellCommands`` when an item is chosen.
Shell-owned follow-up policy (New/Open/Save-As/Paste placement) is surfaced as
``DesignerShellCommandRequest`` values rather than guessed here.
"""

from __future__ import annotations

from collections.abc import Callable

from .command_menu import CommandMenu, CommandMenuBinding, CommandMenuHost
from .designer_shell import (
    DesignerShellCommandRequest,
    DesignerShellCommands,
)


DesignerShellRequestHandler = Callable[[DesignerShellCommandRequest], object]
DesignerShellResultHandler = Callable[[str, object], object]


class DesignerShellMenu:
    """Present one ``DesignerShellCommands`` tree through a command-menu host.

    The presenter has an intentionally small lifetime contract: callers build
    it after the backend host exists, call ``show()`` whenever the editor wants
    the command surface, and dispose it before the backend context is destroyed.
    ``show()`` always refreshes from current workspace state so stale enablement
    and Undo/Redo labels never become presenter-owned state.
    """

    def __init__(
        self,
        shell: DesignerShellCommands,
        host: CommandMenuHost,
        *,
        title: str = "Designer Commands",
        on_request: DesignerShellRequestHandler | None = None,
        on_result: DesignerShellResultHandler | None = None,
    ):
        if not isinstance(shell, DesignerShellCommands):
            raise TypeError("designer shell menu requires DesignerShellCommands")
        if on_request is not None and not callable(on_request):
            raise TypeError("designer shell request handler must be callable")
        if on_result is not None and not callable(on_result):
            raise TypeError("designer shell result handler must be callable")

        self._shell = shell
        self._on_request = on_request
        self._on_result = on_result
        self._menu = CommandMenu(
            host,
            title=str(title),
            on_command=self._dispatch,
        )

    @property
    def shell(self) -> DesignerShellCommands:
        return self._shell

    @property
    def menu(self) -> CommandMenu:
        return self._menu

    @property
    def binding(self) -> CommandMenuBinding | None:
        return self._menu.binding

    def build(self) -> CommandMenuBinding:
        """Build the host surface from the shell's current semantic command set."""

        return self._menu.build(self._shell.command_set())

    def refresh(self) -> None:
        """Refresh labels/availability without acquiring any editor state."""

        commands = self._shell.command_set()
        if self._menu.binding is None or not self._menu.exists():
            self._menu.build(commands)
            return
        self._menu.update(commands)

    def show(self) -> None:
        """Refresh from current workspace state and show the host surface."""

        self.refresh()
        self._menu.show()

    def hide(self) -> None:
        self._menu.hide()

    def exists(self) -> bool:
        return self._menu.exists()

    def dispose(self) -> bool:
        return self._menu.dispose()

    def _dispatch(self, key: str):
        """Revalidate one menu selection through the semantic shell owner."""

        result = self._shell.dispatch(key)
        if isinstance(result, DesignerShellCommandRequest) and self._on_request is not None:
            result = self._on_request(result)
        if self._on_result is not None:
            self._on_result(str(key), result)
        # A completed command can alter history/selection/clipboard state. Keep
        # the existing surface synchronized for callers that leave it alive.
        self.refresh()
        return result


__all__ = [
    "DesignerShellMenu",
    "DesignerShellRequestHandler",
    "DesignerShellResultHandler",
]
