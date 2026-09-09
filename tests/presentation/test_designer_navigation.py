"""Stable-ID hierarchy navigation regressions for optional designer tooling."""

from __future__ import annotations

import unittest

from app.framework.components import Button, ControlColumn, Label
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_editing import DesignerEditSession
from app.framework.designer_navigation import (
    DesignerHierarchyNavigator,
    DesignerHierarchyReveal,
    DesignerNavigationDirection,
)
from app.framework.designer_preview_host import DesignerPreviewHost
from app.framework.designer_selection import DesignerSelectionState


class DesignerNavigationTests(unittest.TestCase):
    def _snapshot(self):
        first = Label("One")
        nested_a = Label("Nested A")
        nested_b = Label("Nested B")
        inner = ControlColumn((nested_a, nested_b))
        action = Button("Run")
        root = ControlColumn((first, inner, action))
        ids = DesignerIdentityMap(prefix="navigation")
        ids.bind(root, "root")
        ids.bind(first, "first")
        ids.bind(inner, "inner")
        ids.bind(nested_a, "nested-a")
        ids.bind(nested_b, "nested-b")
        ids.bind(action, "action")
        return root, capture_component_tree(root, identities=ids)

    def test_parent_child_and_sibling_navigation_follows_snapshot_order(self):
        _, snapshot = self._snapshot()
        nav = DesignerHierarchyNavigator(snapshot)
        self.assertEqual("root", nav.root_id)
        self.assertEqual(("first", "inner", "action"), nav.child_ids("root"))
        self.assertEqual("first", nav.first_child_id("root"))
        self.assertEqual("action", nav.last_child_id("root"))
        self.assertEqual("root", nav.parent_id("inner"))
        self.assertEqual("first", nav.previous_sibling_id("inner"))
        self.assertEqual("action", nav.next_sibling_id("inner"))
        self.assertEqual("nested-a", nav.first_child_id("inner"))
        self.assertEqual("nested-b", nav.last_child_id("inner"))

    def test_preorder_navigation_is_deterministic_across_nested_hierarchy(self):
        _, snapshot = self._snapshot()
        nav = DesignerHierarchyNavigator(snapshot)
        self.assertEqual(
            ("root", "first", "inner", "nested-a", "nested-b", "action"),
            nav.preorder_ids,
        )
        self.assertEqual("inner", nav.previous_preorder_id("nested-a"))
        self.assertEqual("nested-b", nav.next_preorder_id("nested-a"))
        self.assertEqual("nested-b", nav.previous_preorder_id("action"))
        self.assertEqual("action", nav.next_preorder_id("nested-b"))

    def test_reveal_path_contains_root_to_parent_without_persisting_expansion_state(self):
        _, snapshot = self._snapshot()
        nav = DesignerHierarchyNavigator(snapshot)
        reveal = nav.reveal("nested-b")
        self.assertEqual(DesignerHierarchyReveal("nested-b", ("root", "inner")), reveal)
        self.assertEqual(("root", "inner", "nested-b"), reveal.path_ids)
        self.assertEqual(2, reveal.depth)
        self.assertEqual(("root", "inner"), nav.ancestor_ids("nested-b"))
        self.assertEqual(reveal.path_ids, nav.path_ids("nested-b"))

    def test_direction_dispatch_accepts_enum_or_string_and_rejects_unknown_values(self):
        _, snapshot = self._snapshot()
        nav = DesignerHierarchyNavigator(snapshot)
        self.assertEqual(
            "inner",
            nav.target("nested-a", DesignerNavigationDirection.PARENT),
        )
        self.assertEqual("nested-b", nav.target("nested-a", "next_sibling"))
        self.assertEqual("action", nav.target("nested-b", "next_preorder"))
        with self.assertRaisesRegex(ValueError, "unsupported designer navigation direction"):
            nav.target("first", "sideways")

    def test_navigation_boundaries_return_none_instead_of_wrapping(self):
        _, snapshot = self._snapshot()
        nav = DesignerHierarchyNavigator(snapshot)
        self.assertIsNone(nav.parent_id("root"))
        self.assertIsNone(nav.previous_sibling_id("root"))
        self.assertIsNone(nav.next_sibling_id("root"))
        self.assertIsNone(nav.previous_preorder_id("root"))
        self.assertIsNone(nav.next_preorder_id("action"))
        self.assertIsNone(nav.first_child_id("first"))
        self.assertIsNone(nav.last_child_id("action"))

    def test_navigation_validates_snapshot_and_node_identity(self):
        _, snapshot = self._snapshot()
        with self.assertRaisesRegex(TypeError, "requires DesignerSnapshot"):
            DesignerHierarchyNavigator(object())
        nav = DesignerHierarchyNavigator(snapshot)
        with self.assertRaisesRegex(ValueError, "designer node id must be non-empty"):
            nav.node("")
        with self.assertRaisesRegex(KeyError, "designer node not found"):
            nav.node("missing")
        with self.assertRaisesRegex(KeyError, "designer node not found"):
            nav.target("missing", "parent")

    def test_session_selection_navigation_is_ephemeral_and_history_neutral(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        session.select_node("inner")
        self.assertEqual("first", session.selection_navigation_target("previous_sibling"))
        self.assertTrue(session.navigate_selection("previous_sibling"))
        self.assertEqual("first", session.selected_node_id)
        self.assertFalse(session.is_dirty)
        self.assertEqual(0, session.undo_depth)
        self.assertEqual(0, session.redo_depth)
        self.assertEqual(snapshot, session.snapshot)
        self.assertFalse(session.navigate_selection("previous_sibling"))
        self.assertEqual("first", session.selected_node_id)

    def test_focus_navigation_remains_distinct_and_can_couple_selection_explicitly(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        session.select_node("first")
        session.focus_node("inner")
        self.assertTrue(session.navigate_focus("first_child"))
        self.assertEqual(DesignerSelectionState("first", "nested-a"), session.selection_state)
        self.assertTrue(session.navigate_focus("next_sibling", select=True))
        self.assertEqual(DesignerSelectionState("nested-b", "nested-b"), session.selection_state)
        self.assertFalse(session.is_dirty)
        self.assertEqual(0, session.undo_depth)

    def test_session_reveal_helpers_return_paths_without_mutating_selection(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        self.assertIsNone(session.reveal_selected())
        self.assertIsNone(session.reveal_focused())
        session.select_node("nested-a")
        session.focus_node("action")
        before = session.selection_state
        self.assertEqual(("root", "inner", "nested-a"), session.reveal_selected().path_ids)
        self.assertEqual(("root", "action"), session.reveal_focused().path_ids)
        self.assertEqual(("root", "inner", "nested-b"), session.reveal_node("nested-b").path_ids)
        self.assertEqual(before, session.selection_state)
        self.assertFalse(session.is_dirty)

    def test_navigation_reads_current_snapshot_after_move_and_reparent(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        self.assertEqual("action", session.hierarchy_navigation().next_sibling_id("inner"))
        self.assertTrue(session.move_node("action", 0))
        self.assertEqual("first", session.hierarchy_navigation().next_sibling_id("action"))
        self.assertTrue(session.reparent_node("action", "inner"))
        nav = session.hierarchy_navigation()
        self.assertEqual("inner", nav.parent_id("action"))
        self.assertEqual("action", nav.last_child_id("inner"))
        self.assertEqual(("root", "inner", "action"), nav.path_ids("action"))

    def test_preview_host_navigation_never_rebuilds_and_resolves_selected_component(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        host = DesignerPreviewHost(session)
        generation = host.generation
        host.select_and_focus_node("inner")
        self.assertEqual("first", host.selection_navigation_target("previous_sibling"))
        self.assertTrue(host.navigate_selection("previous_sibling"))
        self.assertEqual("first", session.selected_node_id)
        self.assertEqual("One", host.selected_component.text)
        self.assertEqual(generation, host.generation)
        self.assertEqual(("root", "first"), host.reveal_selected().path_ids)
        self.assertEqual(generation, host.generation)
        host.close()

    def test_blank_code_first_tree_remains_unchanged_by_navigation_tooling(self):
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
        reveal = session.reveal_selected()
        self.assertEqual(actions.node_id, reveal.node_id)
        self.assertGreater(reveal.depth, 0)
        self.assertTrue(session.navigate_selection("parent", focus=True))
        self.assertEqual(session.selected_node_id, session.focused_node_id)
        self.assertEqual(before.to_descriptor(), view.capture_designer_snapshot().to_descriptor())
        self.assertEqual("Actions", view.positioned_panel.children[1].component.label)


if __name__ == "__main__":
    unittest.main(verbosity=2)
