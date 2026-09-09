from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.framework.components import Button, ControlColumn, Label
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_editing import DESIGNER_REDO_COMMAND, DESIGNER_UNDO_COMMAND
from app.framework.designer_navigation import DesignerNavigationDirection
from app.framework.designer_shell import (
    DESIGNER_COPY_COMMAND,
    DESIGNER_DUPLICATE_COMMAND,
    DESIGNER_FILE_MENU_COMMAND,
    DESIGNER_NEW_PROJECT_COMMAND,
    DESIGNER_OPEN_PROJECT_COMMAND,
    DESIGNER_PASTE_COMMAND,
    DESIGNER_REVEAL_SELECTION_COMMAND,
    DESIGNER_SAVE_AS_COMMAND,
    DESIGNER_SAVE_COMMAND,
    DesignerShellCommandRequest,
    DesignerShellCommandState,
    DesignerShellCommands,
    DesignerShellRequestKind,
    navigation_command_key,
)
from app.framework.designer_workspace import DesignerWorkspace


class DesignerShellCommandTests(unittest.TestCase):
    def _snapshot(self):
        root = ControlColumn((
            Label("Title"),
            ControlColumn((Button("Run"), Button("Stop"))),
        ))
        identities = DesignerIdentityMap(prefix="shell")
        identities.bind(root, "shell-root")
        return capture_component_tree(root, identities=identities)

    def _node(self, workspace: DesignerWorkspace, *, type_key: str, value: str):
        for node in workspace.session.snapshot.root.walk():
            if node.type_key == type_key and value in node.properties.values():
                return node
        raise AssertionError((type_key, value))

    def test_state_projects_stable_file_edit_and_navigation_command_tree(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        shell = DesignerShellCommands(workspace)
        state = shell.state
        self.assertIsInstance(state, DesignerShellCommandState)
        self.assertEqual(("File", "Edit", "Navigate"), tuple(c.label for c in state.commands))
        self.assertEqual("File", state.command(DESIGNER_FILE_MENU_COMMAND).label)
        self.assertEqual("New Project", state.command(DESIGNER_NEW_PROJECT_COMMAND).label)
        self.assertEqual("Save As", state.command(DESIGNER_SAVE_AS_COMMAND).label)
        self.assertEqual("Parent", state.command(navigation_command_key("parent")).label)
        self.assertGreaterEqual(state.command_count, 18)
        workspace.close()

    def test_unsaved_save_returns_save_as_request_without_guessing_a_path(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        shell = DesignerShellCommands(workspace)
        self.assertTrue(shell.command(DESIGNER_SAVE_COMMAND).enabled)
        generation = workspace.state.preview_generation
        request = shell.dispatch(DESIGNER_SAVE_COMMAND)
        self.assertEqual(
            DesignerShellCommandRequest(
                DESIGNER_SAVE_AS_COMMAND,
                DesignerShellRequestKind.SAVE_AS,
                requires_path=True,
            ),
            request,
        )
        self.assertFalse(workspace.project.is_persisted)
        self.assertEqual(generation, workspace.state.preview_generation)
        workspace.close()

    def test_direct_save_delegates_to_existing_project_owner_without_rebuild(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "shell.project"
            workspace = DesignerWorkspace.create(self._snapshot(), path=path)
            shell = DesignerShellCommands(workspace)
            generation = workspace.state.preview_generation
            result = shell.dispatch(DESIGNER_SAVE_COMMAND)
            self.assertEqual(path.absolute(), result)
            self.assertTrue(path.is_file())
            self.assertFalse(workspace.state.is_dirty)
            self.assertFalse(shell.command(DESIGNER_SAVE_COMMAND).enabled)
            self.assertEqual(generation, workspace.state.preview_generation)
            workspace.close()

    def test_new_open_and_save_as_remain_explicit_shell_requests(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        shell = DesignerShellCommands(workspace)
        new_request = shell.dispatch(DESIGNER_NEW_PROJECT_COMMAND)
        open_request = shell.dispatch(DESIGNER_OPEN_PROJECT_COMMAND)
        save_as_request = shell.dispatch(DESIGNER_SAVE_AS_COMMAND)
        self.assertEqual(DesignerShellRequestKind.NEW_PROJECT, new_request.kind)
        self.assertEqual(DesignerShellRequestKind.OPEN_PROJECT, open_request.kind)
        self.assertTrue(open_request.requires_path)
        self.assertEqual(DesignerShellRequestKind.SAVE_AS, save_as_request.kind)
        self.assertTrue(save_as_request.requires_path)
        self.assertIs(workspace.session, workspace.project.session)
        workspace.close()

    def test_undo_redo_labels_and_dispatch_reuse_transactional_history(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        run = self._node(workspace, type_key="control.button", value="Run")
        workspace.select_and_focus_node(run.node_id)
        shell = DesignerShellCommands(workspace)
        self.assertFalse(shell.command(DESIGNER_UNDO_COMMAND).enabled)
        self.assertTrue(workspace.set_selected_property("label", "Launch"))
        generation = workspace.state.preview_generation
        self.assertEqual("Undo Set label", shell.command(DESIGNER_UNDO_COMMAND).label)
        self.assertTrue(shell.dispatch(DESIGNER_UNDO_COMMAND))
        self.assertEqual(generation + 1, workspace.state.preview_generation)
        self.assertEqual("Redo Set label", shell.command(DESIGNER_REDO_COMMAND).label)
        self.assertTrue(shell.dispatch(DESIGNER_REDO_COMMAND))
        self.assertEqual("Launch", workspace.state.inspector.row("label").value)
        workspace.close()

    def test_copy_is_ephemeral_and_duplicate_uses_existing_checked_transaction(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        run = self._node(workspace, type_key="control.button", value="Run")
        workspace.select_and_focus_node(run.node_id)
        shell = DesignerShellCommands(workspace)
        generation = workspace.state.preview_generation
        payload = shell.dispatch(DESIGNER_COPY_COMMAND)
        self.assertEqual(run.node_id, payload.root.node_id)
        self.assertEqual(generation, workspace.state.preview_generation)
        self.assertTrue(shell.command(DESIGNER_PASTE_COMMAND).enabled)
        self.assertTrue(shell.dispatch(DESIGNER_DUPLICATE_COMMAND))
        self.assertEqual(generation + 1, workspace.state.preview_generation)
        self.assertIsNotNone(workspace.preview_host.component(run.node_id + "-copy"))
        workspace.close()

    def test_paste_is_a_placement_request_not_an_implicit_hierarchy_policy(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        run = self._node(workspace, type_key="control.button", value="Run")
        workspace.select_and_focus_node(run.node_id)
        workspace.copy_selected()
        shell = DesignerShellCommands(workspace)
        before = workspace.session.snapshot
        request = shell.dispatch(DESIGNER_PASTE_COMMAND)
        self.assertEqual(DesignerShellRequestKind.PASTE_PLACEMENT, request.kind)
        self.assertEqual(run.node_id, request.target_hint)
        self.assertEqual(before, workspace.session.snapshot)
        self.assertFalse(workspace.state.can_undo)
        workspace.close()

    def test_navigation_commands_follow_current_snapshot_and_reveal_selection(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        run = self._node(workspace, type_key="control.button", value="Run")
        workspace.select_and_focus_node(run.node_id)
        shell = DesignerShellCommands(workspace)
        generation = workspace.state.preview_generation
        parent_key = navigation_command_key(DesignerNavigationDirection.PARENT)
        self.assertTrue(shell.command(parent_key).enabled)
        self.assertTrue(shell.dispatch(parent_key))
        parent_id = workspace.state.selected_id
        self.assertEqual(parent_id, workspace.state.focused_id)
        self.assertIn(parent_id, tuple(row.node_id for row in workspace.state.hierarchy_rows))
        first_key = navigation_command_key(DesignerNavigationDirection.FIRST_CHILD)
        self.assertTrue(shell.dispatch(first_key))
        self.assertEqual(run.node_id, workspace.state.selected_id)
        self.assertEqual(generation, workspace.state.preview_generation)
        workspace.close()

    def test_reveal_is_ephemeral_and_disabled_navigation_rejects_dispatch(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        root_id = workspace.session.snapshot.root.node_id
        workspace.select_and_focus_node(root_id)
        shell = DesignerShellCommands(workspace)
        generation = workspace.state.preview_generation
        reveal = shell.dispatch(DESIGNER_REVEAL_SELECTION_COMMAND)
        self.assertEqual(root_id, reveal.node_id)
        self.assertEqual(generation, workspace.state.preview_generation)
        parent_key = navigation_command_key(DesignerNavigationDirection.PARENT)
        self.assertFalse(shell.command(parent_key).enabled)
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            shell.dispatch(parent_key)
        workspace.close()

    def test_duplicate_root_and_selection_dependent_commands_are_disabled(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        shell = DesignerShellCommands(workspace)
        self.assertFalse(shell.command(DESIGNER_COPY_COMMAND).enabled)
        self.assertFalse(shell.command(DESIGNER_DUPLICATE_COMMAND).enabled)
        root_id = workspace.session.snapshot.root.node_id
        workspace.select_and_focus_node(root_id)
        self.assertTrue(shell.command(DESIGNER_COPY_COMMAND).enabled)
        self.assertFalse(shell.command(DESIGNER_DUPLICATE_COMMAND).enabled)
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            shell.dispatch(DESIGNER_DUPLICATE_COMMAND)
        workspace.close()

    def test_closed_workspace_disables_owned_actions_but_keeps_lifecycle_requests(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        shell = DesignerShellCommands(workspace)
        workspace.close()
        state = shell.state
        self.assertTrue(state.closed)
        self.assertTrue(state.command(DESIGNER_NEW_PROJECT_COMMAND).enabled)
        self.assertTrue(state.command(DESIGNER_OPEN_PROJECT_COMMAND).enabled)
        self.assertFalse(state.command(DESIGNER_SAVE_AS_COMMAND).enabled)
        self.assertEqual(DesignerShellRequestKind.NEW_PROJECT, shell.dispatch(DESIGNER_NEW_PROJECT_COMMAND).kind)
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            shell.dispatch(DESIGNER_SAVE_AS_COMMAND)

    def test_descriptor_is_json_safe_and_code_first_tree_remains_unchanged(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        view = DemoView(SnapshotHost())
        before = view.capture_designer_snapshot()
        workspace = DesignerWorkspace.create(before)
        shell = DesignerShellCommands(workspace)
        descriptor = shell.state.to_descriptor()
        json.dumps(descriptor, allow_nan=False, sort_keys=True)
        actions = next(
            node for node in workspace.session.snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        workspace.select_and_focus_node(actions.node_id)
        shell.dispatch(DESIGNER_COPY_COMMAND)
        workspace.close()
        self.assertEqual(before.to_descriptor(), view.capture_designer_snapshot().to_descriptor())


if __name__ == "__main__":
    unittest.main(verbosity=2)
