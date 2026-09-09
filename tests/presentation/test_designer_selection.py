"""Stable-ID selection/focus regressions for optional designer tooling."""

from __future__ import annotations

import unittest

from app.framework.components import Button, ControlColumn, Label
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_editing import DesignerEditSession
from app.framework.designer_preview_host import DesignerPreviewHost
from app.framework.designer_selection import DesignerSelectionModel, DesignerSelectionState


class DesignerSelectionTests(unittest.TestCase):
    def _snapshot(self):
        first = Label("One")
        nested_label = Label("Nested")
        inner = ControlColumn((nested_label,))
        action = Button("Run")
        root = ControlColumn((first, inner, action))
        ids = DesignerIdentityMap(prefix="selection")
        ids.bind(root, "root")
        ids.bind(first, "first")
        ids.bind(inner, "inner")
        ids.bind(nested_label, "nested")
        ids.bind(action, "action")
        return root, capture_component_tree(root, identities=ids)

    def test_selection_model_starts_empty_and_state_is_immutable_record(self):
        _, snapshot = self._snapshot()
        model = DesignerSelectionModel()
        self.assertEqual(DesignerSelectionState(), model.state)
        self.assertFalse(model.has_selection)
        self.assertFalse(model.has_focus)
        self.assertIsNone(model.selected_node(snapshot))
        self.assertIsNone(model.focused_node(snapshot))
        self.assertIsNone(model.selected_location(snapshot))
        self.assertIsNone(model.focused_location(snapshot))

    def test_select_and_focus_validate_stable_snapshot_ids(self):
        _, snapshot = self._snapshot()
        model = DesignerSelectionModel(snapshot, selected="first", focused="action")
        self.assertEqual("first", model.selected_id)
        self.assertEqual("action", model.focused_id)
        self.assertTrue(model.select(snapshot, "inner"))
        self.assertFalse(model.select(snapshot, "inner"))
        self.assertTrue(model.focus(snapshot, "nested"))
        with self.assertRaisesRegex(KeyError, "designer node not found"):
            model.select(snapshot, "missing")
        with self.assertRaisesRegex(KeyError, "designer node not found"):
            model.focus(snapshot, "missing")

    def test_selection_and_focus_are_distinct_and_can_be_cleared_independently(self):
        _, snapshot = self._snapshot()
        model = DesignerSelectionModel()
        self.assertTrue(model.select(snapshot, "first"))
        self.assertTrue(model.focus(snapshot, "action"))
        self.assertEqual(DesignerSelectionState("first", "action"), model.state)
        self.assertTrue(model.clear_focus())
        self.assertEqual("first", model.selected_id)
        self.assertFalse(model.has_focus)
        self.assertTrue(model.clear_selection())
        self.assertFalse(model.has_selection)
        self.assertFalse(model.clear_selection())

    def test_select_and_focus_helpers_can_couple_explicitly(self):
        _, snapshot = self._snapshot()
        model = DesignerSelectionModel()
        self.assertTrue(model.select(snapshot, "first", focus=True))
        self.assertEqual(DesignerSelectionState("first", "first"), model.state)
        self.assertTrue(model.focus(snapshot, "action", select=True))
        self.assertEqual(DesignerSelectionState("action", "action"), model.state)
        self.assertTrue(model.select_and_focus(snapshot, "nested"))
        self.assertEqual(DesignerSelectionState("nested", "nested"), model.state)
        self.assertFalse(model.select_and_focus(snapshot, "nested"))

    def test_selected_nodes_and_locations_resolve_current_document_context(self):
        _, snapshot = self._snapshot()
        model = DesignerSelectionModel(snapshot, selected="nested", focused="inner")
        self.assertEqual("Nested", model.selected_node(snapshot).properties["text"])
        self.assertEqual("container.column", model.focused_node(snapshot).type_key)
        selected_location = model.selected_location(snapshot)
        focused_location = model.focused_location(snapshot)
        self.assertEqual("inner", selected_location.parent_id)
        self.assertEqual(2, selected_location.depth)
        self.assertEqual("root", focused_location.parent_id)
        self.assertEqual(1, focused_location.depth)

    def test_session_selection_is_ephemeral_not_dirty_or_undoable(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        self.assertTrue(session.select_node("first"))
        self.assertTrue(session.focus_node("action"))
        self.assertFalse(session.is_dirty)
        self.assertEqual(0, session.undo_depth)
        self.assertEqual(snapshot, session.snapshot)
        self.assertEqual("first", session.selected_node_id)
        self.assertEqual("action", session.focused_node_id)
        self.assertEqual("first", session.selected_node().node_id)
        self.assertEqual("action", session.focused_node().node_id)

    def test_property_edit_move_and_reparent_preserve_stable_selection_ids(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        session.select_and_focus_node("action")
        self.assertTrue(session.set_property("action", "label", "Changed"))
        self.assertEqual(DesignerSelectionState("action", "action"), session.selection_state)
        self.assertTrue(session.move_node("action", 0))
        self.assertEqual(DesignerSelectionState("action", "action"), session.selection_state)
        self.assertTrue(session.reparent_node("action", "inner"))
        self.assertEqual(DesignerSelectionState("action", "action"), session.selection_state)
        self.assertEqual("inner", session.selected_location().parent_id)

    def test_deleting_selected_node_falls_back_to_nearest_surviving_ancestor(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        session.select_and_focus_node("nested")
        self.assertTrue(session.remove_node("nested"))
        self.assertEqual(DesignerSelectionState("inner", "inner"), session.selection_state)
        self.assertEqual("container.column", session.selected_node().type_key)

    def test_deleting_selected_subtree_climbs_past_removed_ancestors(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        session.select_node("nested")
        session.focus_node("inner")
        self.assertTrue(session.remove_node("inner"))
        self.assertEqual(DesignerSelectionState("root", "root"), session.selection_state)
        self.assertTrue(session.undo())
        # Selection is ephemeral interaction state, so undo restores the document
        # without resurrecting an older selection that no longer owns history.
        self.assertEqual(DesignerSelectionState("root", "root"), session.selection_state)
        self.assertIn("inner", {node.node_id for node in session.snapshot.root.walk()})

    def test_duplicate_and_clipboard_operations_do_not_implicitly_move_selection(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        session.select_and_focus_node("action")
        session.copy_node("first")
        self.assertEqual(DesignerSelectionState("action", "action"), session.selection_state)
        self.assertTrue(session.duplicate_node("first"))
        self.assertIn("first-copy", {node.node_id for node in session.snapshot.root.walk()})
        self.assertEqual(DesignerSelectionState("action", "action"), session.selection_state)

    def test_preview_host_selection_does_not_rebuild_and_tracks_replacements_by_id(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        host = DesignerPreviewHost(session)
        generation = host.generation
        self.assertTrue(host.select_and_focus_node("action"))
        selected_before = host.selected_component
        self.assertIs(selected_before, host.focused_component)
        self.assertEqual(generation, host.generation)
        self.assertTrue(host.set_property("action", "label", "Preview"))
        selected_after = host.selected_component
        self.assertIsNot(selected_before, selected_after)
        self.assertEqual("Preview", selected_after.label)
        self.assertEqual(DesignerSelectionState("action", "action"), session.selection_state)
        self.assertEqual(generation + 1, host.generation)
        host.close()

    def test_blank_code_first_tree_remains_unchanged_by_optional_selection_tooling(self):
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
        host = DesignerPreviewHost(session)
        self.assertTrue(host.select_and_focus_node(actions.node_id))
        self.assertEqual("Actions", host.selected_component.label)
        self.assertEqual(before.to_descriptor(), view.capture_designer_snapshot().to_descriptor())
        self.assertEqual("Actions", view.positioned_panel.children[1].component.label)
        host.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
