"""Copy/paste/duplicate regressions for provisional designer documents."""

from __future__ import annotations

import json
import unittest

from app.framework.components import (
    Button,
    ControlColumn,
    ControlGrid,
    Label,
    PositionedPanel,
    ControlLayout,
    positioned,
)
from app.framework.designer import (
    DesignerIdentityMap,
    DesignerNode,
    capture_component_tree,
)
from app.framework.designer_clipboard import (
    DesignerClipboardPayload,
    DuplicateDesignerNode,
    PasteDesignerSubtree,
    copy_designer_subtree,
    remap_designer_subtree_ids,
)
from app.framework.designer_editing import DesignerEditSession
from app.framework.designer_preview_host import DesignerPreviewHost
from app.framework.designer_structure import locate_designer_node


class DesignerClipboardTests(unittest.TestCase):
    def _column_snapshot(self):
        first = Label("One")
        second = Button("Two")
        inner = ControlColumn((Label("Nested"),))
        root = ControlColumn((first, second, inner))
        ids = DesignerIdentityMap(prefix="clip")
        ids.bind(root, "root")
        ids.bind(first, "first")
        ids.bind(second, "second")
        ids.bind(inner, "inner")
        ids.bind(inner.children[0], "nested")
        return root, capture_component_tree(root, identities=ids)

    def _grid_snapshot(self):
        cell = Label("A")
        grid = ControlGrid(((cell,),))
        ids = DesignerIdentityMap(prefix="grid")
        ids.bind(grid, "grid")
        ids.bind(cell, "cell-a")
        return grid, capture_component_tree(grid, identities=ids)

    def test_copy_payload_preserves_subtree_and_relationship_and_round_trips_json(self):
        _, snapshot = self._column_snapshot()
        payload = copy_designer_subtree(snapshot, "inner")
        self.assertEqual("inner", payload.root.node_id)
        self.assertEqual("children", payload.slot)
        self.assertIsNone(payload.metadata)
        self.assertEqual(2, payload.node_count)
        self.assertEqual(("container.column", "control.label"), payload.type_keys)
        restored = DesignerClipboardPayload.from_json(payload.to_json())
        self.assertEqual(payload.to_descriptor(), restored.to_descriptor())
        json.dumps(restored.to_descriptor())

    def test_id_remapping_is_preorder_deterministic_and_conflict_safe(self):
        _, snapshot = self._column_snapshot()
        source = next(node for node in snapshot.root.walk() if node.node_id == "inner")
        existing = {node.node_id for node in snapshot.root.walk()} | {"inner-copy", "nested-copy"}
        first = remap_designer_subtree_ids(source, existing)
        second = remap_designer_subtree_ids(source, existing)
        self.assertEqual(
            {"inner": "inner-copy-2", "nested": "nested-copy-2"},
            dict(first.id_map),
        )
        self.assertEqual(dict(first.id_map), dict(second.id_map))
        self.assertEqual("inner-copy-2", first.root.node_id)
        self.assertEqual("nested-copy-2", first.root.children[0].node.node_id)
        self.assertEqual("inner", source.node_id)

    def test_paste_clones_complete_subtree_without_reusing_source_ids(self):
        _, snapshot = self._column_snapshot()
        payload = copy_designer_subtree(snapshot, "inner")
        command = PasteDesignerSubtree("root", payload, index=1)
        clone = command.clone_for(snapshot)
        result = command.apply(snapshot)
        self.assertEqual("inner-copy", clone.root.node_id)
        self.assertEqual("nested-copy", clone.node_id("nested"))
        self.assertEqual(
            ["first", "inner-copy", "second", "inner"],
            [child.node.node_id for child in result.root.children],
        )
        self.assertEqual("Nested", result.root.children[1].node.children[0].node.properties["text"])
        self.assertIn("inner", {node.node_id for node in result.root.walk()})
        self.assertIn("inner-copy", {node.node_id for node in result.root.walk()})

    def test_repeated_paste_allocates_predictable_numeric_suffixes(self):
        _, snapshot = self._column_snapshot()
        payload = copy_designer_subtree(snapshot, "first")
        command = PasteDesignerSubtree("root", payload)
        once = command.apply(snapshot)
        twice = command.apply(once)
        self.assertEqual(
            ["first", "second", "inner", "first-copy", "first-copy-2"],
            [child.node.node_id for child in twice.root.children],
        )

    def test_paste_preserves_relationship_by_default_and_allows_explicit_override(self):
        _, snapshot = self._grid_snapshot()
        payload = copy_designer_subtree(snapshot, "cell-a")
        self.assertEqual({"row": 0, "column": 0}, dict(payload.metadata))
        with self.assertRaisesRegex(ValueError, "requires unique metadata"):
            PasteDesignerSubtree("grid", payload).apply(snapshot)
        result = PasteDesignerSubtree(
            "grid",
            payload,
            metadata={"row": 0, "column": 1},
        ).apply(snapshot)
        location = locate_designer_node(result, "cell-a-copy")
        self.assertEqual("cell", location.slot)
        self.assertEqual({"row": 0, "column": 1}, dict(location.metadata))

    def test_duplicate_inserts_adjacent_sibling_and_rejects_root(self):
        _, snapshot = self._column_snapshot()
        result = DuplicateDesignerNode("inner").apply(snapshot)
        self.assertEqual(
            ["first", "second", "inner", "inner-copy"],
            [child.node.node_id for child in result.root.children],
        )
        duplicate = next(node for node in result.root.walk() if node.node_id == "inner-copy")
        self.assertEqual("nested-copy", duplicate.children[0].node.node_id)
        with self.assertRaisesRegex(ValueError, "root cannot be duplicated"):
            DuplicateDesignerNode("root").apply(snapshot)

    def test_duplicate_relationship_validation_requires_grid_coordinate_override(self):
        _, snapshot = self._grid_snapshot()
        with self.assertRaisesRegex(ValueError, "requires unique metadata"):
            DuplicateDesignerNode("cell-a").apply(snapshot)
        result = DuplicateDesignerNode(
            "cell-a",
            metadata={"row": 0, "column": 1},
        ).apply(snapshot)
        self.assertEqual(
            {"row": 0, "column": 1},
            dict(locate_designer_node(result, "cell-a-copy").metadata),
        )

    def test_session_clipboard_is_ephemeral_and_paste_shares_undo_redo_history(self):
        _, snapshot = self._column_snapshot()
        session = DesignerEditSession(snapshot)
        payload = session.copy_node("first")
        self.assertTrue(session.has_clipboard)
        self.assertIs(payload, session.clipboard)
        self.assertFalse(session.is_dirty)
        self.assertEqual(0, session.undo_depth)
        self.assertEqual(snapshot, session.snapshot)
        self.assertTrue(session.paste("root", index=1))
        self.assertTrue(session.is_dirty)
        self.assertEqual(1, session.undo_depth)
        self.assertEqual("Paste first", session.undo_label)
        self.assertEqual("first-copy", session.snapshot.root.children[1].node.node_id)
        self.assertTrue(session.undo())
        self.assertEqual(snapshot, session.snapshot)
        self.assertTrue(session.redo())
        self.assertIn("first-copy", {node.node_id for node in session.snapshot.root.walk()})
        self.assertTrue(session.clear_clipboard())
        self.assertFalse(session.has_clipboard)
        self.assertFalse(session.clear_clipboard())

    def test_session_can_paste_explicit_payload_across_compatible_documents(self):
        _, source = self._column_snapshot()
        payload = copy_designer_subtree(source, "inner")
        target_root = ControlColumn((Label("Target"),))
        ids = DesignerIdentityMap(prefix="target")
        ids.bind(target_root, "target-root")
        ids.bind(target_root.children[0], "target-label")
        target = capture_component_tree(target_root, identities=ids)
        session = DesignerEditSession(target)
        self.assertTrue(session.paste("target-root", payload=payload))
        self.assertEqual("inner-copy", session.snapshot.root.children[-1].node.node_id)
        self.assertEqual("nested-copy", session.snapshot.root.children[-1].node.children[0].node.node_id)
        self.assertFalse(session.has_clipboard)
        with self.assertRaisesRegex(RuntimeError, "clipboard is empty"):
            session.paste("target-root")

    def test_preview_host_copy_does_not_rebuild_but_paste_duplicate_and_undo_do(self):
        _, snapshot = self._column_snapshot()
        session = DesignerEditSession(snapshot)
        host = DesignerPreviewHost(session)
        self.assertEqual(1, host.generation)
        payload = host.copy_node("first")
        self.assertEqual("first", payload.root.node_id)
        self.assertEqual(1, host.generation)
        self.assertTrue(host.paste("root", index=1))
        self.assertEqual(2, host.generation)
        self.assertEqual("One", host.component("first-copy").text)
        self.assertTrue(host.duplicate_node("second"))
        self.assertEqual(3, host.generation)
        self.assertEqual("Two", host.component("second-copy").label)
        self.assertTrue(host.undo())
        self.assertEqual(4, host.generation)
        with self.assertRaises(KeyError):
            host.component("second-copy")
        host.close()

    def test_blank_application_copy_duplicate_is_document_only(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        view = DemoView(SnapshotHost())
        original = view.capture_designer_snapshot()
        actions = next(
            node
            for node in original.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        session = DesignerEditSession(original)
        self.assertTrue(session.duplicate_node(actions.node_id))
        self.assertEqual(original.node_count + 1, session.snapshot.node_count)
        self.assertEqual(original.to_descriptor(), view.capture_designer_snapshot().to_descriptor())
        self.assertIn(f"{actions.node_id}-copy", {node.node_id for node in session.snapshot.root.walk()})

    def test_clipboard_rejects_invalid_payloads_and_explicit_metadata_misuse(self):
        _, snapshot = self._column_snapshot()
        with self.assertRaisesRegex(ValueError, "kind is invalid"):
            DesignerClipboardPayload(snapshot.root, kind="other")
        with self.assertRaisesRegex(ValueError, "unsupported designer clipboard version"):
            DesignerClipboardPayload(snapshot.root, version=2)
        session = DesignerEditSession(snapshot)
        session.copy_node("first")
        with self.assertRaisesRegex(ValueError, "preserve_relationship=False"):
            session.paste("root", metadata={"x": 1})
        with self.assertRaisesRegex(ValueError, "preserve_relationship=False"):
            session.duplicate_node("first", metadata={"x": 1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
