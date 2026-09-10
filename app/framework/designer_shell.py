"""Backend-neutral editor-shell command projection for optional designer tooling.

Tranche 20 composes the authoritative designer owners into one
``DesignerWorkspace``.  This module adds the next deliberately narrow seam: a
stable command tree that a future menu bar, toolbar, command palette or keyboard
adapter can render without inventing toolkit-specific command policy.

The shell model owns no document, history, selection, clipboard, preview or
project-file state.  It re-projects availability from ``DesignerWorkspace`` on
every read.  Commands that already have complete semantic inputs delegate to the
workspace.  Lifecycle/placement actions that require shell-supplied data (New,
Open, Save As and Paste placement) return immutable requests instead of guessing
file dialogs, templates or hierarchy-placement policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .designer_clipboard import DesignerClipboardPayload
from .designer_editing import DESIGNER_REDO_COMMAND, DESIGNER_UNDO_COMMAND
from .designer_navigation import DesignerHierarchyReveal, DesignerNavigationDirection
from .designer_workspace import DesignerWorkspace
from .interactions import CommandSet, CommandSpec


DESIGNER_FILE_MENU_COMMAND = "designer.shell.file"
DESIGNER_EDIT_MENU_COMMAND = "designer.shell.edit"
DESIGNER_NAVIGATE_MENU_COMMAND = "designer.shell.navigate"

DESIGNER_NEW_PROJECT_COMMAND = "designer.project.new"
DESIGNER_OPEN_PROJECT_COMMAND = "designer.project.open"
DESIGNER_SAVE_COMMAND = "designer.project.save"
DESIGNER_SAVE_AS_COMMAND = "designer.project.save_as"
DESIGNER_COPY_COMMAND = "designer.copy"
DESIGNER_PASTE_COMMAND = "designer.paste"
DESIGNER_DUPLICATE_COMMAND = "designer.duplicate"
DESIGNER_REMOVE_COMMAND = "designer.structure.remove"
DESIGNER_MOVE_UP_COMMAND = "designer.structure.move_up"
DESIGNER_MOVE_DOWN_COMMAND = "designer.structure.move_down"
DESIGNER_REVEAL_SELECTION_COMMAND = "designer.hierarchy.reveal_selection"


def navigation_command_key(direction: DesignerNavigationDirection | str) -> str:
    """Return the stable shell command key for one hierarchy direction."""

    text = str(getattr(direction, "value", direction) or "").strip().lower()
    try:
        resolved = DesignerNavigationDirection(text)
    except ValueError as exc:
        raise ValueError(f"unsupported designer navigation direction: {direction!r}") from exc
    return f"designer.navigate.{resolved.value}"


_NAVIGATION_LABELS = {
    DesignerNavigationDirection.PARENT: "Parent",
    DesignerNavigationDirection.FIRST_CHILD: "First Child",
    DesignerNavigationDirection.LAST_CHILD: "Last Child",
    DesignerNavigationDirection.PREVIOUS_SIBLING: "Previous Sibling",
    DesignerNavigationDirection.NEXT_SIBLING: "Next Sibling",
    DesignerNavigationDirection.PREVIOUS_PREORDER: "Previous Item",
    DesignerNavigationDirection.NEXT_PREORDER: "Next Item",
}
_NAVIGATION_BY_COMMAND = {
    navigation_command_key(direction): direction for direction in DesignerNavigationDirection
}


class DesignerShellRequestKind(str, Enum):
    """Shell-owned follow-up required before a semantic action can execute."""

    NEW_PROJECT = "new_project"
    OPEN_PROJECT = "open_project"
    SAVE_AS = "save_as"
    PASTE_PLACEMENT = "paste_placement"


@dataclass(frozen=True)
class DesignerShellCommandRequest:
    """Immutable request for information deliberately owned by the editor shell."""

    command_key: str
    kind: DesignerShellRequestKind
    requires_path: bool = False
    target_hint: str = ""

    def to_descriptor(self) -> dict[str, object]:
        return {
            "command_key": self.command_key,
            "kind": self.kind.value,
            "requires_path": self.requires_path,
            "target_hint": self.target_hint,
        }


@dataclass(frozen=True)
class DesignerShellCommandState:
    """Immutable presentation snapshot of the current shell command tree."""

    closed: bool
    commands: tuple[CommandSpec, ...]

    @property
    def command_set(self) -> CommandSet:
        return CommandSet(self.commands)

    def command(self, key: object) -> CommandSpec:
        return self.command_set.get(key)

    @property
    def command_count(self) -> int:
        count = 0

        def visit(command: CommandSpec) -> None:
            nonlocal count
            count += 1
            for child in command.children:
                visit(child)

        for command in self.commands:
            visit(command)
        return count

    @property
    def enabled_leaf_count(self) -> int:
        count = 0

        def visit(command: CommandSpec) -> None:
            nonlocal count
            if command.children:
                for child in command.children:
                    visit(child)
            elif command.enabled:
                count += 1

        for command in self.commands:
            visit(command)
        return count

    def to_descriptor(self) -> dict[str, object]:
        def describe(command: CommandSpec) -> dict[str, object]:
            return {
                "key": command.key,
                "label": command.label,
                "enabled": command.enabled,
                "checked": command.checked,
                "children": [describe(child) for child in command.children],
            }

        return {
            "closed": self.closed,
            "command_count": self.command_count,
            "enabled_leaf_count": self.enabled_leaf_count,
            "commands": [describe(command) for command in self.commands],
        }


class DesignerShellCommands:
    """Project and dispatch a future editor shell's semantic command tree."""

    def __init__(self, workspace: DesignerWorkspace):
        if not isinstance(workspace, DesignerWorkspace):
            raise TypeError("designer shell commands require DesignerWorkspace")
        self._workspace = workspace

    @property
    def workspace(self) -> DesignerWorkspace:
        return self._workspace

    @property
    def state(self) -> DesignerShellCommandState:
        workspace = self._workspace
        state = workspace.state
        session = workspace.session
        active = not state.closed
        selected_location = session.selected_location() if active else None
        structural_parent = None
        if active and selected_location is not None and selected_location.parent_id is not None:
            structural_parent = session.node(selected_location.parent_id)
        duplicate_enabled = bool(structural_parent is not None)
        remove_enabled = bool(structural_parent is not None)
        move_up_enabled = bool(
            structural_parent is not None
            and selected_location is not None
            and selected_location.index is not None
            and selected_location.index > 0
        )
        move_down_enabled = bool(
            structural_parent is not None
            and selected_location is not None
            and selected_location.index is not None
            and selected_location.index < len(structural_parent.children) - 1
        )

        undo_label = "Undo" if not state.undo_label else f"Undo {state.undo_label}"
        redo_label = "Redo" if not state.redo_label else f"Redo {state.redo_label}"

        navigation_commands = []
        for direction in DesignerNavigationDirection:
            enabled = bool(active and session.selection_navigation_target(direction) is not None)
            navigation_commands.append(
                CommandSpec(
                    navigation_command_key(direction),
                    _NAVIGATION_LABELS[direction],
                    enabled=enabled,
                )
            )

        commands = (
            CommandSpec(
                DESIGNER_FILE_MENU_COMMAND,
                "File",
                children=(
                    CommandSpec(DESIGNER_NEW_PROJECT_COMMAND, "New Project"),
                    CommandSpec(DESIGNER_OPEN_PROJECT_COMMAND, "Open Project"),
                    CommandSpec(
                        DESIGNER_SAVE_COMMAND,
                        "Save",
                        enabled=bool(active and state.is_dirty),
                    ),
                    CommandSpec(DESIGNER_SAVE_AS_COMMAND, "Save As", enabled=active),
                ),
            ),
            CommandSpec(
                DESIGNER_EDIT_MENU_COMMAND,
                "Edit",
                children=(
                    CommandSpec(DESIGNER_UNDO_COMMAND, undo_label, enabled=state.can_undo),
                    CommandSpec(DESIGNER_REDO_COMMAND, redo_label, enabled=state.can_redo),
                    CommandSpec(
                        DESIGNER_COPY_COMMAND,
                        "Copy",
                        enabled=bool(active and state.has_selection),
                    ),
                    CommandSpec(
                        DESIGNER_PASTE_COMMAND,
                        "Paste",
                        enabled=bool(active and state.has_selection and state.has_clipboard),
                    ),
                    CommandSpec(
                        DESIGNER_DUPLICATE_COMMAND,
                        "Duplicate",
                        enabled=duplicate_enabled,
                    ),
                    CommandSpec(
                        DESIGNER_MOVE_UP_COMMAND,
                        "Move Up",
                        enabled=move_up_enabled,
                    ),
                    CommandSpec(
                        DESIGNER_MOVE_DOWN_COMMAND,
                        "Move Down",
                        enabled=move_down_enabled,
                    ),
                    CommandSpec(
                        DESIGNER_REMOVE_COMMAND,
                        "Remove",
                        enabled=remove_enabled,
                    ),
                ),
            ),
            CommandSpec(
                DESIGNER_NAVIGATE_MENU_COMMAND,
                "Navigate",
                children=(
                    CommandSpec(
                        DESIGNER_REVEAL_SELECTION_COMMAND,
                        "Reveal Selection",
                        enabled=bool(active and state.has_selection),
                    ),
                    *navigation_commands,
                ),
            ),
        )
        return DesignerShellCommandState(closed=state.closed, commands=commands)

    def command_set(self) -> CommandSet:
        return self.state.command_set

    def command(self, key: object) -> CommandSpec:
        return self.state.command(key)

    def dispatch(
        self,
        key: object,
    ) -> (
        bool
        | Path
        | DesignerClipboardPayload
        | DesignerHierarchyReveal
        | DesignerShellCommandRequest
        | None
    ):
        """Dispatch one currently-enabled leaf command.

        New/Open/Save-As/Paste return explicit requests because templates, file
        dialogs and paste placement are editor-shell policy.  Every other action
        delegates to the existing workspace/session/preview owners.
        """

        commands = self.command_set()

        def execute(command_key: str):
            workspace = self._workspace
            state = workspace.state

            if command_key == DESIGNER_NEW_PROJECT_COMMAND:
                return DesignerShellCommandRequest(
                    command_key,
                    DesignerShellRequestKind.NEW_PROJECT,
                )
            if command_key == DESIGNER_OPEN_PROJECT_COMMAND:
                return DesignerShellCommandRequest(
                    command_key,
                    DesignerShellRequestKind.OPEN_PROJECT,
                    requires_path=True,
                )
            if command_key == DESIGNER_SAVE_COMMAND:
                if state.requires_save_as:
                    return DesignerShellCommandRequest(
                        DESIGNER_SAVE_AS_COMMAND,
                        DesignerShellRequestKind.SAVE_AS,
                        requires_path=True,
                    )
                return workspace.save()
            if command_key == DESIGNER_SAVE_AS_COMMAND:
                return DesignerShellCommandRequest(
                    command_key,
                    DesignerShellRequestKind.SAVE_AS,
                    requires_path=True,
                )
            if command_key == DESIGNER_UNDO_COMMAND:
                return workspace.undo()
            if command_key == DESIGNER_REDO_COMMAND:
                return workspace.redo()
            if command_key == DESIGNER_COPY_COMMAND:
                return workspace.copy_selected()
            if command_key == DESIGNER_PASTE_COMMAND:
                return DesignerShellCommandRequest(
                    command_key,
                    DesignerShellRequestKind.PASTE_PLACEMENT,
                    target_hint=state.selected_id,
                )
            if command_key == DESIGNER_DUPLICATE_COMMAND:
                return workspace.duplicate_selected()
            if command_key == DESIGNER_MOVE_UP_COMMAND:
                changed = workspace.move_selected_up()
                if changed:
                    workspace.reveal_selected_in_hierarchy()
                return changed
            if command_key == DESIGNER_MOVE_DOWN_COMMAND:
                changed = workspace.move_selected_down()
                if changed:
                    workspace.reveal_selected_in_hierarchy()
                return changed
            if command_key == DESIGNER_REMOVE_COMMAND:
                changed = workspace.remove_selected()
                if changed and workspace.state.has_selection:
                    workspace.reveal_selected_in_hierarchy()
                return changed
            if command_key == DESIGNER_REVEAL_SELECTION_COMMAND:
                return workspace.reveal_selected_in_hierarchy()
            if command_key in _NAVIGATION_BY_COMMAND:
                changed = workspace.navigate_selection(
                    _NAVIGATION_BY_COMMAND[command_key],
                    focus=True,
                )
                if changed:
                    workspace.reveal_selected_in_hierarchy()
                return changed
            raise KeyError(command_key)

        return commands.dispatch(key, execute)


__all__ = [
    "DESIGNER_COPY_COMMAND",
    "DESIGNER_DUPLICATE_COMMAND",
    "DESIGNER_MOVE_DOWN_COMMAND",
    "DESIGNER_MOVE_UP_COMMAND",
    "DESIGNER_REMOVE_COMMAND",
    "DESIGNER_EDIT_MENU_COMMAND",
    "DESIGNER_FILE_MENU_COMMAND",
    "DESIGNER_NAVIGATE_MENU_COMMAND",
    "DESIGNER_NEW_PROJECT_COMMAND",
    "DESIGNER_OPEN_PROJECT_COMMAND",
    "DESIGNER_PASTE_COMMAND",
    "DESIGNER_REDO_COMMAND",
    "DESIGNER_REVEAL_SELECTION_COMMAND",
    "DESIGNER_SAVE_AS_COMMAND",
    "DESIGNER_SAVE_COMMAND",
    "DESIGNER_UNDO_COMMAND",
    "DesignerShellCommandRequest",
    "DesignerShellCommandState",
    "DesignerShellCommands",
    "DesignerShellRequestKind",
    "navigation_command_key",
]
