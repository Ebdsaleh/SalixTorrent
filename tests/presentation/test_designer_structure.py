"""Structural hierarchy mutation regressions for provisional designer snapshots."""

from __future__ import annotations

import json
import unittest

from app.framework.components import (
    AxisAnchor,
    Button,
    ControlColumn,
    ControlGrid,
    ControlLayout,
    Label,
    PositionedPanel,
    TabContainer,
    TabPage,
    anchored,
    positioned,
)
from app.framework.designer import (
    DesignerChild,
    DesignerChildSlotSpec,
    DesignerIdentityMap,
    DesignerNode,
    DesignerSnapshot,
    FRAMEWORK_DESIGNER_CATALOG,
    capture_component_tree,
)
from app.framework.designer_editing import DesignerEditSession
from app.framework.designer_structure import (
    InsertDesignerChild,
    MoveDesignerNode,
    RemoveDesignerNode,
    ReparentDesignerNode,
    locate_designer_node,
)


class DesignerStructureTests(unittest.TestCase):
    def _column_snapshot(self):
        first = Label("One")
        second = Button("Two")
        inner = ControlColumn((Label("Nested"),))
        root = ControlColumn((first, second, inner))
        ids = DesignerIdentityMap(prefix="tree")
        ids.bind(root, "root")
        ids.bind(first, "first")
        ids.bind(second, "second")
        ids.bind(inner, "inner")
        ids.bind(inner.children[0], "nested")
        return root, capture_component_tree(root, identities=ids)

    def test_component_metadata_declares_structural_child_slots(self):
        column = FRAMEWORK_DESIGNER_CATALOG.get("container.column").to_descriptor()
        grid = FRAMEWORK_DESIGNER_CATALOG.get("container.grid").to_descriptor()
        tabs = FRAMEWORK_DESIGNER_CATALOG.get("structure.tabs").to_descriptor()
        placed = FRAMEWORK_DESIGNER_CATALOG.get("container.placed").to_descriptor()
        self.assertEqual(["children"], [slot["key"] for slot in column["child_slots"]])
        self.assertEqual(["row", "column"], grid["child_slots"][0]["allowed_metadata"])
        self.assertEqual(["row", "column"], grid["child_slots"][0]["required_metadata"])
        self.assertEqual(["row", "column"], grid["child_slots"][0]["unique_by"])
        self.assertEqual(["key"], tabs["child_slots"][0]["unique_by"])
        self.assertFalse(placed["child_slots"][0]["multiple"])
        json.dumps((column, grid, tabs, placed))

    def test_child_slot_metadata_rejects_ambiguous_constraints(self):
        with self.assertRaisesRegex(ValueError, "also be required"):
            DesignerChildSlotSpec("page", "Page", unique_by=("key",))
        with self.assertRaisesRegex(ValueError, "must be unique"):
            DesignerChildSlotSpec(
                "cell",
                "Cell",
                required_metadata=("row", "row"),
            )

    def test_location_reports_root_parent_index_slot_and_metadata(self):
        _, snapshot = self._column_snapshot()
        root = locate_designer_node(snapshot, "root")
        nested = locate_designer_node(snapshot, "nested")
        self.assertIsNone(root.parent_id)
        self.assertEqual(0, root.depth)
        self.assertEqual("inner", nested.parent_id)
        self.assertEqual("container.column", nested.parent_type_key)
        self.assertEqual(0, nested.index)
        self.assertEqual("children", nested.slot)
        self.assertEqual(2, nested.depth)
        json.dumps(nested.to_descriptor())

    def test_insert_child_supports_index_and_stable_subtree_identity(self):
        _, snapshot = self._column_snapshot()
        inserted = DesignerNode("inserted", "control.label", {"text": "Inserted"})
        result = InsertDesignerChild("root", inserted, index=1).apply(snapshot)
        self.assertEqual(
            ["first", "inserted", "second", "inner"],
            [child.node.node_id for child in result.root.children],
        )
        self.assertEqual("inserted", locate_designer_node(result, "inserted").node_id)
        self.assertEqual("Inserted", next(n for n in result.root.walk() if n.node_id == "inserted").properties["text"])
        self.assertNotIn("inserted", {node.node_id for node in snapshot.root.walk()})

    def test_insert_rejects_leaf_parent_duplicate_ids_and_unknown_types(self):
        _, snapshot = self._column_snapshot()
        with self.assertRaisesRegex(ValueError, "does not accept children"):
            InsertDesignerChild(
                "first", DesignerNode("new", "control.label", {"text": "New"})
            ).apply(snapshot)
        with self.assertRaisesRegex(ValueError, "reuses existing node id"):
            InsertDesignerChild(
                "root", DesignerNode("second", "control.label", {"text": "Duplicate"})
            ).apply(snapshot)
        with self.assertRaisesRegex(ValueError, "unknown type metadata"):
            InsertDesignerChild(
                "root", DesignerNode("unknown", "custom.widget", {})
            ).apply(snapshot)

    def test_relationship_validation_enforces_slots_metadata_cardinality_and_identity(self):
        grid = ControlGrid(((Label("A"),),))
        ids = DesignerIdentityMap(prefix="grid")
        ids.bind(grid, "grid")
        ids.bind(grid.rows[0][0], "cell-a")
        snapshot = capture_component_tree(grid, identities=ids)
        new_cell = DesignerNode("cell-b", "control.label", {"text": "B"})
        with self.assertRaisesRegex(ValueError, "does not declare child slot"):
            InsertDesignerChild("grid", new_cell, slot="children").apply(snapshot)
        with self.assertRaisesRegex(ValueError, "requires metadata"):
            InsertDesignerChild("grid", new_cell, slot="cell").apply(snapshot)
        with self.assertRaisesRegex(ValueError, "requires unique metadata"):
            InsertDesignerChild(
                "grid", new_cell, slot="cell", metadata={"row": 0, "column": 0}
            ).apply(snapshot)
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            InsertDesignerChild(
                "grid", new_cell, slot="cell", metadata={"row": -1, "column": 1}
            ).apply(snapshot)

        page = TabPage("one", "One", (Label("Inside"),))
        tabs = TabContainer((page,))
        tab_ids = DesignerIdentityMap(prefix="tabs")
        tab_ids.bind(tabs, "tabs")
        tab_ids.bind(page, "page-one")
        tab_ids.bind(page.children[0], "inside")
        tab_snapshot = capture_component_tree(tabs, identities=tab_ids)
        with self.assertRaisesRegex(ValueError, "only own structure.tab_page"):
            InsertDesignerChild(
                "tabs",
                DesignerNode("bad-page", "control.label", {"text": "Bad"}),
                slot="page",
                metadata={"key": "bad"},
            ).apply(tab_snapshot)
        with self.assertRaisesRegex(ValueError, "requires unique metadata"):
            InsertDesignerChild(
                "tabs",
                DesignerNode("page-two", "structure.tab_page", {"key": "one", "label": "Two"}),
                slot="page",
                metadata={"key": "one"},
            ).apply(tab_snapshot)

    def test_remove_node_removes_complete_subtree_and_rejects_root(self):
        _, snapshot = self._column_snapshot()
        result = RemoveDesignerNode("inner").apply(snapshot)
        self.assertEqual(["first", "second"], [child.node.node_id for child in result.root.children])
        self.assertNotIn("nested", {node.node_id for node in result.root.walk()})
        with self.assertRaisesRegex(ValueError, "root cannot be removed"):
            RemoveDesignerNode("root").apply(snapshot)

    def test_move_node_reorders_siblings_and_preserves_relationship(self):
        _, snapshot = self._column_snapshot()
        result = MoveDesignerNode("first", 2).apply(snapshot)
        self.assertEqual(["second", "inner", "first"], [child.node.node_id for child in result.root.children])
        location = locate_designer_node(result, "first")
        self.assertEqual("children", location.slot)
        self.assertIsNone(location.metadata)
        self.assertIs(snapshot, MoveDesignerNode("second", 1).apply(snapshot))
        with self.assertRaisesRegex(ValueError, "root cannot be moved"):
            MoveDesignerNode("root", 0).apply(snapshot)

    def test_reparent_preserves_relationship_and_stable_ids_between_linear_containers(self):
        _, snapshot = self._column_snapshot()
        result = ReparentDesignerNode("second", "inner").apply(snapshot)
        self.assertEqual(["first", "inner"], [child.node.node_id for child in result.root.children])
        self.assertEqual(["nested", "second"], [child.node.node_id for child in result.root.children[1].node.children])
        location = locate_designer_node(result, "second")
        self.assertEqual("inner", location.parent_id)
        self.assertEqual("children", location.slot)
        self.assertEqual("second", location.node_id)

    def test_reparent_can_replace_relationship_metadata_for_positioned_parent(self):
        label = Label("Free")
        source = ControlColumn((label,))
        target = PositionedPanel((), layout=ControlLayout(width=220, height=100))
        root = ControlColumn((source, target))
        ids = DesignerIdentityMap(prefix="position")
        ids.bind(root, "root")
        ids.bind(source, "source")
        ids.bind(label, "label")
        ids.bind(target, "target")
        snapshot = capture_component_tree(root, identities=ids)
        result = ReparentDesignerNode(
            "label",
            "target",
            slot="children",
            metadata={"placement": {"kind": "fixed", "x": 12, "y": 18}},
        ).apply(snapshot)
        location = locate_designer_node(result, "label")
        self.assertEqual("target", location.parent_id)
        self.assertEqual("fixed", location.metadata["placement"]["kind"])
        self.assertEqual(12, location.metadata["placement"]["x"])
        with self.assertRaisesRegex(ValueError, "requires metadata"):
            ReparentDesignerNode("label", "target", slot="children", metadata=None).apply(snapshot)

    def test_reparent_rejects_root_cycles_and_incompatible_preserved_slots(self):
        _, snapshot = self._column_snapshot()
        with self.assertRaisesRegex(ValueError, "root cannot be reparented"):
            ReparentDesignerNode("root", "inner").apply(snapshot)
        with self.assertRaisesRegex(ValueError, "own subtree"):
            ReparentDesignerNode("inner", "nested").apply(snapshot)

        panel = PositionedPanel(
            (positioned(Label("Fixed"), x=4, y=5),),
            layout=ControlLayout(width=120, height=80),
        )
        target = ControlColumn(())
        root = ControlColumn((panel, target))
        ids = DesignerIdentityMap(prefix="slot")
        ids.bind(root, "root")
        ids.bind(panel, "panel")
        ids.bind(panel.children[0].component, "fixed")
        ids.bind(target, "target")
        positioned_snapshot = capture_component_tree(root, identities=ids)
        with self.assertRaisesRegex(ValueError, "does not allow metadata"):
            ReparentDesignerNode("fixed", "target").apply(positioned_snapshot)

    def test_edit_session_structural_helpers_share_undo_redo_and_dirty_history(self):
        _, snapshot = self._column_snapshot()
        session = DesignerEditSession(snapshot)
        inserted = DesignerNode("inserted", "control.button", {"label": "Insert"})
        self.assertTrue(session.insert_child("root", inserted, index=1))
        self.assertEqual(1, session.undo_depth)
        self.assertTrue(session.move_node("inserted", 3))
        self.assertTrue(session.reparent_node("second", "inner"))
        self.assertTrue(session.remove_node("first"))
        self.assertTrue(session.is_dirty)
        self.assertEqual("inner", session.location("second").parent_id)
        self.assertEqual(4, session.undo_depth)
        self.assertTrue(session.undo())
        self.assertIsNotNone(session.node("first"))
        self.assertTrue(session.undo())
        self.assertEqual("root", session.location("second").parent_id)
        self.assertTrue(session.redo())
        self.assertEqual("inner", session.location("second").parent_id)

    def test_structural_edits_round_trip_through_snapshot_json(self):
        _, snapshot = self._column_snapshot()
        session = DesignerEditSession(snapshot)
        session.reparent_node("second", "inner", index=0)
        session.insert_child(
            "root",
            DesignerNode("third", "control.label", {"text": "Three"}),
            index=1,
        )
        restored = DesignerSnapshot.from_json(session.snapshot.to_json())
        self.assertEqual(session.snapshot.to_descriptor(), restored.to_descriptor())
        self.assertEqual("inner", locate_designer_node(restored, "second").parent_id)
        self.assertEqual("third", restored.root.children[1].node.node_id)

    def test_blank_application_hierarchy_edit_is_document_only(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class Host:
            presentation = create_dearpygui_backend()

        view = DemoView(Host())
        snapshot = view.capture_designer_snapshot()
        actions = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        source = locate_designer_node(snapshot, actions.node_id)
        self.assertIsNotNone(source.parent_id)
        source_parent = next(node for node in snapshot.root.walk() if node.node_id == source.parent_id)
        target = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "container.positioned"
            and node.node_id != source.parent_id
            and any(
                child.metadata
                and child.metadata.get("placement", {}).get("kind") == "anchored"
                for child in node.children
            )
        )
        session = DesignerEditSession(snapshot)
        self.assertTrue(
            session.reparent_node(
                actions.node_id,
                target.node_id,
                slot="children",
                metadata={
                    "placement": {
                        "kind": "anchored",
                        "horizontal": AxisAnchor.CENTER.value,
                        "vertical": AxisAnchor.CENTER.value,
                    }
                },
                preserve_metadata=False,
            )
        )
        self.assertEqual(target.node_id, session.location(actions.node_id).parent_id)
        self.assertEqual(source.parent_id, locate_designer_node(snapshot, actions.node_id).parent_id)
        self.assertIn(actions.node_id, {child.node.node_id for child in source_parent.children})
        self.assertEqual("Actions", actions.properties["label"])
        self.assertTrue(session.undo())
        self.assertEqual(source.parent_id, session.location(actions.node_id).parent_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
