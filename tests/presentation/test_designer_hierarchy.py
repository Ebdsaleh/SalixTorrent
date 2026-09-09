"""Hierarchy projection/expansion regressions for optional designer tooling."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import tempfile
import unittest

from app.framework.components import Button, ControlColumn, Label
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_editing import DesignerEditSession
from app.framework.designer_hierarchy import (
    DesignerHierarchyProjection,
    DesignerHierarchyProjectionState,
    DesignerHierarchyRow,
)
from app.framework.designer_preview_host import DesignerPreviewHost
from app.framework.designer_project import DesignerProjectFile


class DesignerHierarchyProjectionTests(unittest.TestCase):
    def _snapshot(self):
        first = Label("One")
        nested_a = Label("Nested A")
        nested_b = Label("Nested B")
        inner = ControlColumn((nested_a, nested_b))
        other_child = Label("Other Child")
        other = ControlColumn((other_child,))
        action = Button("Run")
        root = ControlColumn((first, inner, other, action))
        ids = DesignerIdentityMap(prefix="hierarchy")
        ids.bind(root, "root")
        ids.bind(first, "first")
        ids.bind(inner, "inner")
        ids.bind(nested_a, "nested-a")
        ids.bind(nested_b, "nested-b")
        ids.bind(other, "other")
        ids.bind(other_child, "other-child")
        ids.bind(action, "action")
        return root, capture_component_tree(root, identities=ids)

    def test_default_projection_expands_root_and_projects_visible_depth_rows(self):
        _, snapshot = self._snapshot()
        projection = DesignerHierarchyProjection(snapshot)
        rows = projection.rows()
        self.assertEqual(("root",), projection.expanded_ids)
        self.assertEqual(
            ("root", "first", "inner", "other", "action"),
            tuple(row.node_id for row in rows),
        )
        self.assertEqual((0, 1, 1, 1, 1), tuple(row.depth for row in rows))
        root = rows[0]
        self.assertEqual(
            DesignerHierarchyRow(
                "root",
                snapshot.root.type_key,
                0,
                "",
                4,
                True,
                False,
                False,
            ),
            root,
        )
        self.assertTrue(root.expandable)
        self.assertFalse(rows[1].expandable)

    def test_expand_collapse_and_toggle_change_visibility_only(self):
        _, snapshot = self._snapshot()
        projection = DesignerHierarchyProjection(snapshot)
        self.assertTrue(projection.expand("inner"))
        self.assertFalse(projection.expand("inner"))
        self.assertEqual(
            ("root", "first", "inner", "nested-a", "nested-b", "other", "action"),
            projection.visible_ids(),
        )
        self.assertTrue(projection.collapse("root"))
        self.assertEqual(("root",), projection.visible_ids())
        self.assertTrue(projection.toggle("root"))
        self.assertIn("inner", projection.visible_ids())
        self.assertTrue(projection.toggle("inner"))
        self.assertNotIn("nested-a", projection.visible_ids())
        self.assertEqual(snapshot, projection.snapshot)

    def test_rows_synchronize_selected_and_focused_flags_without_owning_selection(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        session.select_node("inner")
        session.focus_node("action")
        rows = {row.node_id: row for row in session.hierarchy_rows()}
        self.assertTrue(rows["inner"].selected)
        self.assertFalse(rows["inner"].focused)
        self.assertFalse(rows["action"].selected)
        self.assertTrue(rows["action"].focused)
        self.assertFalse(session.is_dirty)
        self.assertEqual(0, session.undo_depth)

    def test_reveal_expands_ancestor_path_without_changing_selection(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        before = session.selection_state
        self.assertNotIn("nested-b", session.visible_hierarchy_ids())
        reveal = session.reveal_hierarchy_node("nested-b")
        self.assertEqual(("root", "inner", "nested-b"), reveal.path_ids)
        self.assertIn("inner", session.hierarchy_expanded_ids)
        self.assertIn("nested-b", session.visible_hierarchy_ids())
        self.assertEqual(before, session.selection_state)
        self.assertFalse(session.is_dirty)

    def test_projection_validates_inputs_and_leaf_expansion_is_a_noop(self):
        _, snapshot = self._snapshot()
        with self.assertRaisesRegex(TypeError, "requires DesignerSnapshot"):
            DesignerHierarchyProjection(object())
        with self.assertRaisesRegex(KeyError, "designer node not found"):
            DesignerHierarchyProjection(snapshot, expanded_ids=("missing",))
        projection = DesignerHierarchyProjection(snapshot)
        self.assertFalse(projection.expand("first"))
        self.assertFalse(projection.toggle("action"))
        with self.assertRaisesRegex(ValueError, "designer node id must be non-empty"):
            projection.expand("")
        with self.assertRaisesRegex(KeyError, "designer node not found"):
            projection.collapse("missing")
        self.assertIsNone(projection.row("nested-a"))

    def test_projection_state_is_immutable_and_preorder_normalized(self):
        _, snapshot = self._snapshot()
        projection = DesignerHierarchyProjection(
            snapshot,
            expanded_ids=("other", "inner"),
        )
        state = projection.state
        self.assertEqual(
            DesignerHierarchyProjectionState(("root", "inner", "other")),
            state,
        )
        self.assertEqual(3, state.expanded_count)
        with self.assertRaises(FrozenInstanceError):
            state.expanded_ids = ()

    def test_session_expansion_is_ephemeral_dirty_and_history_neutral(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        self.assertTrue(session.expand_hierarchy_node("inner"))
        self.assertTrue(session.collapse_hierarchy_node("root"))
        self.assertTrue(session.toggle_hierarchy_node("root"))
        self.assertEqual(("root", "inner"), session.hierarchy_expanded_ids)
        self.assertEqual(snapshot, session.snapshot)
        self.assertFalse(session.is_dirty)
        self.assertEqual(0, session.undo_depth)
        self.assertEqual(0, session.redo_depth)

    def test_reveal_selected_and_focused_expand_paths_and_sync_rows(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        session.select_node("nested-a")
        session.focus_node("other-child")
        self.assertNotIn("nested-a", session.visible_hierarchy_ids())
        self.assertEqual(
            ("root", "inner", "nested-a"),
            session.reveal_selected_in_hierarchy().path_ids,
        )
        self.assertEqual(
            ("root", "other", "other-child"),
            session.reveal_focused_in_hierarchy().path_ids,
        )
        rows = {row.node_id: row for row in session.hierarchy_rows()}
        self.assertTrue(rows["nested-a"].selected)
        self.assertTrue(rows["other-child"].focused)
        self.assertEqual(("root", "inner", "other"), session.hierarchy_expanded_ids)

    def test_expansion_reconciles_across_reparent_remove_and_undo_without_history_replay(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        session.expand_hierarchy_node("inner")
        self.assertTrue(session.reparent_node("inner", "other"))
        self.assertIn("inner", session.hierarchy_expanded_ids)
        self.assertNotIn("inner", session.visible_hierarchy_ids())
        session.reveal_hierarchy_node("inner")
        self.assertIn("other", session.hierarchy_expanded_ids)
        self.assertIn("inner", session.visible_hierarchy_ids())
        self.assertTrue(session.undo())
        self.assertIn("inner", session.hierarchy_expanded_ids)
        self.assertIn("other", session.hierarchy_expanded_ids)
        self.assertTrue(session.remove_node("inner"))
        self.assertNotIn("inner", session.hierarchy_expanded_ids)
        self.assertTrue(session.undo())
        self.assertNotIn("inner", session.hierarchy_expanded_ids)
        self.assertIn("inner", session.visible_hierarchy_ids())

    def test_project_round_trip_does_not_persist_hierarchy_expansion(self):
        _, snapshot = self._snapshot()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "hierarchy.project"
            project = DesignerProjectFile.create(snapshot)
            project.session.expand_hierarchy_node("inner")
            project.session.expand_hierarchy_node("other")
            self.assertEqual(("root", "inner", "other"), project.session.hierarchy_expanded_ids)
            project.save(path)
            reopened = DesignerProjectFile.open(path)
            self.assertEqual(("root",), reopened.session.hierarchy_expanded_ids)
            self.assertFalse(reopened.is_dirty)

    def test_preview_host_projection_operations_never_rebuild(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        host = DesignerPreviewHost(session)
        generation = host.generation
        host.select_and_focus_node("nested-b")
        self.assertNotIn("nested-b", host.visible_hierarchy_ids())
        reveal = host.reveal_selected_in_hierarchy()
        self.assertEqual(("root", "inner", "nested-b"), reveal.path_ids)
        self.assertIn("nested-b", host.visible_hierarchy_ids())
        row = next(row for row in host.hierarchy_rows() if row.node_id == "nested-b")
        self.assertTrue(row.selected)
        self.assertTrue(row.focused)
        self.assertEqual(generation, host.generation)
        self.assertTrue(host.collapse_hierarchy_node("inner"))
        self.assertEqual(generation, host.generation)
        host.close()

    def test_blank_code_first_tree_remains_unchanged_by_hierarchy_projection(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        view = DemoView(SnapshotHost())
        before = view.capture_designer_snapshot()
        actions = next(
            node
            for node in before.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        session = DesignerEditSession(before)
        session.select_and_focus_node(actions.node_id)
        session.reveal_selected_in_hierarchy()
        row = next(row for row in session.hierarchy_rows() if row.node_id == actions.node_id)
        self.assertTrue(row.selected)
        self.assertTrue(row.focused)
        self.assertEqual(before.to_descriptor(), view.capture_designer_snapshot().to_descriptor())
        self.assertEqual("Actions", view.positioned_panel.children[1].component.label)


if __name__ == "__main__":
    unittest.main(verbosity=2)
