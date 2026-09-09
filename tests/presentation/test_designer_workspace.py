from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.framework.components import Button, ControlColumn, Label
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_preview_host import DesignerPreviewHost
from app.framework.designer_project import DesignerProjectFile
from app.framework.designer_workspace import DesignerWorkspace, DesignerWorkspaceState


class DesignerWorkspaceTests(unittest.TestCase):
    def _snapshot(self):
        root = ControlColumn((
            Label("Title"),
            ControlColumn((Button("Run"), Button("Stop"))),
        ))
        identities = DesignerIdentityMap(prefix="workspace")
        identities.bind(root, "workspace-root")
        return capture_component_tree(root, identities=identities)

    def _node(self, workspace: DesignerWorkspace, *, type_key: str, value: str):
        for node in workspace.session.snapshot.root.walk():
            if node.type_key != type_key:
                continue
            if value in node.properties.values():
                return node
        raise AssertionError((type_key, value))

    def test_workspace_state_composes_existing_authoritative_models(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        state = workspace.state
        self.assertIsInstance(state, DesignerWorkspaceState)
        self.assertTrue(state.is_dirty)
        self.assertTrue(state.requires_save_as)
        self.assertFalse(state.can_save)
        self.assertFalse(state.can_undo)
        self.assertFalse(state.has_selection)
        self.assertFalse(state.has_clipboard)
        self.assertEqual(workspace.session.hierarchy_expanded_ids, state.expanded_ids)
        self.assertEqual(workspace.preview_host.generation, state.preview_generation)
        self.assertTrue(state.preview_available)
        self.assertFalse(state.preview_rendered)
        descriptor = state.to_descriptor()
        self.assertIsNone(descriptor["project"]["path"])
        self.assertEqual([], descriptor["inspector"]["rows"])
        workspace.close()

    def test_workspace_rejects_mismatched_preview_session_and_ambiguous_options(self):
        first = DesignerProjectFile.create(self._snapshot())
        second = DesignerProjectFile.create(self._snapshot())
        foreign = DesignerPreviewHost(second.session)
        with self.assertRaisesRegex(ValueError, "share one edit session"):
            DesignerWorkspace(first, preview_host=foreign)
        own = DesignerPreviewHost(first.session)
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            DesignerWorkspace(first, preview_host=own, parent=object())
        own.close()
        foreign.close()

    def test_selection_updates_hierarchy_and_inspector_without_preview_rebuild(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        run = self._node(workspace, type_key="control.button", value="Run")
        generation = workspace.state.preview_generation
        self.assertTrue(workspace.select_and_focus_node(run.node_id))
        workspace.reveal_selected_in_hierarchy()
        state = workspace.state
        self.assertEqual(run.node_id, state.selected_id)
        self.assertEqual(run.node_id, state.focused_id)
        self.assertEqual(run.node_id, state.inspector.node_id)
        self.assertEqual("Run", state.inspector.row("label").value)
        row = next(row for row in state.hierarchy_rows if row.node_id == run.node_id)
        self.assertTrue(row.selected)
        self.assertTrue(row.focused)
        self.assertEqual(generation, state.preview_generation)
        self.assertFalse(state.can_undo)
        workspace.close()

    def test_hierarchy_interaction_is_dirty_history_and_preview_neutral(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        run = self._node(workspace, type_key="control.button", value="Run")
        workspace.select_and_focus_node(run.node_id)
        reveal = workspace.reveal_selected_in_hierarchy()
        parent_id = reveal.ancestor_ids[-1]
        before = workspace.state
        self.assertTrue(workspace.collapse_hierarchy_node(parent_id))
        collapsed = workspace.state
        self.assertNotIn(run.node_id, tuple(row.node_id for row in collapsed.hierarchy_rows))
        self.assertEqual(before.preview_generation, collapsed.preview_generation)
        self.assertEqual(before.can_undo, collapsed.can_undo)
        self.assertEqual(before.is_dirty, collapsed.is_dirty)
        self.assertTrue(workspace.expand_hierarchy_node(parent_id))
        workspace.close()

    def test_selected_property_edit_updates_history_dirty_inspector_and_preview(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "workspace.project"
            workspace = DesignerWorkspace.create(self._snapshot())
            workspace.save(path)
            run = self._node(workspace, type_key="control.button", value="Run")
            workspace.select_and_focus_node(run.node_id)
            before = workspace.state
            old_component = workspace.preview_host.selected_component
            self.assertTrue(workspace.set_selected_property("label", "Launch"))
            after = workspace.state
            self.assertTrue(after.is_dirty)
            self.assertTrue(after.can_undo)
            self.assertEqual("Set label", after.undo_label)
            self.assertEqual("Launch", after.inspector.row("label").value)
            self.assertEqual(before.preview_generation + 1, after.preview_generation)
            self.assertIsNot(old_component, workspace.preview_host.selected_component)
            self.assertEqual("Launch", workspace.preview_host.selected_component.label)
            workspace.close()

    def test_undo_redo_state_tracks_existing_preview_transaction_history(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        run = self._node(workspace, type_key="control.button", value="Run")
        workspace.select_and_focus_node(run.node_id)
        self.assertTrue(workspace.set_selected_property("label", "Launch"))
        generation = workspace.state.preview_generation
        self.assertTrue(workspace.undo())
        undone = workspace.state
        self.assertFalse(undone.can_undo)
        self.assertTrue(undone.can_redo)
        self.assertEqual("Set label", undone.redo_label)
        self.assertEqual("Run", undone.inspector.row("label").value)
        self.assertEqual(generation + 1, undone.preview_generation)
        self.assertTrue(workspace.redo())
        redone = workspace.state
        self.assertTrue(redone.can_undo)
        self.assertFalse(redone.can_redo)
        self.assertEqual("Launch", redone.inspector.row("label").value)
        workspace.close()

    def test_save_and_save_as_update_project_state_without_preview_rebuild(self):
        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / "first.project"
            second = Path(td) / "second.project"
            workspace = DesignerWorkspace.create(self._snapshot())
            generation = workspace.state.preview_generation
            self.assertEqual(first.absolute(), workspace.save(first))
            saved = workspace.state
            self.assertTrue(saved.is_persisted)
            self.assertFalse(saved.is_dirty)
            self.assertTrue(saved.has_path)
            self.assertFalse(saved.can_save)
            self.assertEqual(generation, saved.preview_generation)
            run = self._node(workspace, type_key="control.button", value="Run")
            workspace.select_node(run.node_id)
            workspace.set_selected_property("label", "Saved As")
            edited_generation = workspace.state.preview_generation
            self.assertTrue(workspace.state.can_save)
            self.assertEqual(second.absolute(), workspace.save_as(second))
            self.assertEqual(second.absolute(), workspace.state.path)
            self.assertFalse(workspace.state.is_dirty)
            self.assertEqual(edited_generation, workspace.state.preview_generation)
            workspace.close()

    def test_reopened_workspace_does_not_persist_ephemeral_shell_state(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "workspace.project"
            workspace = DesignerWorkspace.create(self._snapshot())
            run = self._node(workspace, type_key="control.button", value="Run")
            workspace.select_and_focus_node(run.node_id)
            workspace.reveal_selected_in_hierarchy()
            workspace.copy_selected()
            workspace.save(path)
            workspace.close()

            reopened = DesignerWorkspace.open(path)
            state = reopened.state
            self.assertFalse(state.is_dirty)
            self.assertFalse(state.has_selection)
            self.assertFalse(state.has_focus)
            self.assertFalse(state.has_clipboard)
            self.assertFalse(state.inspector.has_target)
            self.assertFalse(state.can_undo)
            self.assertEqual((reopened.session.snapshot.root.node_id,), state.expanded_ids)
            reopened.close()

    def test_copy_is_shell_state_only_but_duplicate_uses_existing_transaction(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        run = self._node(workspace, type_key="control.button", value="Run")
        workspace.select_and_focus_node(run.node_id)
        generation = workspace.state.preview_generation
        payload = workspace.copy_selected()
        copied = workspace.state
        self.assertEqual(run.node_id, payload.root.node_id)
        self.assertTrue(copied.has_clipboard)
        self.assertFalse(copied.can_undo)
        self.assertEqual(generation, copied.preview_generation)
        self.assertTrue(workspace.duplicate_selected())
        duplicated = workspace.state
        self.assertTrue(duplicated.can_undo)
        self.assertEqual(generation + 1, duplicated.preview_generation)
        self.assertIsNotNone(workspace.preview_host.component(run.node_id + "-copy"))
        workspace.close()

    def test_external_session_edit_can_be_synchronized_explicitly(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        run = self._node(workspace, type_key="control.button", value="Run")
        generation = workspace.state.preview_generation
        self.assertTrue(workspace.session.set_property(run.node_id, "label", "External"))
        self.assertEqual(generation, workspace.state.preview_generation)
        self.assertEqual("Run", workspace.preview_host.component(run.node_id).label)
        self.assertTrue(workspace.sync_preview())
        self.assertEqual(generation + 1, workspace.state.preview_generation)
        self.assertEqual("External", workspace.preview_host.component(run.node_id).label)
        workspace.close()

    def test_close_is_idempotent_and_blocks_mutating_workspace_operations(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        run = self._node(workspace, type_key="control.button", value="Run")
        generation = workspace.state.preview_generation
        self.assertTrue(workspace.close())
        self.assertFalse(workspace.close())
        state = workspace.state
        self.assertTrue(state.closed)
        self.assertFalse(state.preview_available)
        self.assertEqual(generation, state.preview_generation)
        self.assertFalse(state.can_undo)
        with self.assertRaisesRegex(RuntimeError, "workspace is closed"):
            workspace.select_node(run.node_id)
        with self.assertRaisesRegex(RuntimeError, "workspace is closed"):
            workspace.save()

    def test_blank_code_first_tree_remains_unchanged_by_optional_workspace(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        view = DemoView(SnapshotHost())
        before = view.capture_designer_snapshot()
        workspace = DesignerWorkspace.create(before)
        actions = next(
            node
            for node in workspace.session.snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        workspace.select_and_focus_node(actions.node_id)
        self.assertTrue(workspace.state.inspector.has_target)
        workspace.reveal_selected_in_hierarchy()
        workspace.close()
        self.assertEqual(before.to_descriptor(), view.capture_designer_snapshot().to_descriptor())


if __name__ == "__main__":
    unittest.main(verbosity=2)
