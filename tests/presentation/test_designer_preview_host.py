from __future__ import annotations

import unittest

from app.framework.components import Button, ControlColumn, Label
from app.framework.designer import (
    DesignerNode,
    DesignerSnapshot,
    FRAMEWORK_DESIGNER_CATALOG,
    capture_component_tree,
)
from app.framework.designer_editing import DesignerEditSession, SetDesignerProperty
from app.framework.designer_preview import (
    DesignerPreviewCatalog,
    DesignerPreviewSpec,
    DesignerPreviewUnsupportedTypeError,
    FRAMEWORK_DESIGNER_PREVIEW_CATALOG,
)
from app.framework.designer_preview_host import DesignerPreviewHost


class DesignerPreviewHostTests(unittest.TestCase):
    def _session(self):
        captured = capture_component_tree(ControlColumn((Label("One"),)))
        snapshot = DesignerSnapshot(
            captured.root,
            FRAMEWORK_DESIGNER_CATALOG.metadata_descriptor(),
        )
        return DesignerEditSession(snapshot)

    def test_host_builds_initial_backend_neutral_preview(self):
        session = self._session()
        host = DesignerPreviewHost(session)
        self.assertEqual(1, host.generation)
        self.assertEqual(session.snapshot, host.preview.source_snapshot)
        self.assertEqual("One", host.preview.root.children[0].text)
        self.assertFalse(host.state.rendered)

    def test_property_edit_rebuilds_preview_without_mutating_source_component(self):
        source = Label("Original")
        session = DesignerEditSession(capture_component_tree(ControlColumn((source,))))
        node_id = session.snapshot.root.children[0].node.node_id
        host = DesignerPreviewHost(session)
        self.assertTrue(host.set_property(node_id, "text", "Edited"))
        self.assertEqual(2, host.generation)
        self.assertEqual("Edited", host.component(node_id).text)
        self.assertEqual("Original", source.text)
        self.assertEqual("Edited", session.node(node_id).properties["text"])

    def test_noop_edit_does_not_rebuild(self):
        session = self._session()
        node = session.snapshot.root.children[0].node
        host = DesignerPreviewHost(session)
        self.assertFalse(host.set_property(node.node_id, "text", "One"))
        self.assertEqual(1, host.generation)
        self.assertEqual(0, session.undo_depth)

    def test_structural_edit_then_undo_redo_replaces_preview(self):
        session = self._session()
        host = DesignerPreviewHost(session)
        button = DesignerNode("new-button", "control.button", {"label": "Run"})
        self.assertTrue(host.insert_child(session.snapshot.root.node_id, button))
        self.assertEqual(2, len(host.preview.root.children))
        self.assertEqual(2, host.generation)
        self.assertTrue(host.undo())
        self.assertEqual(1, len(host.preview.root.children))
        self.assertEqual(3, host.generation)
        self.assertTrue(host.redo())
        self.assertEqual(2, len(host.preview.root.children))
        self.assertEqual(4, host.generation)

    def test_failed_candidate_does_not_advance_document_or_history(self):
        session = self._session()
        custom = DesignerPreviewCatalog(
            DesignerPreviewSpec(key, FRAMEWORK_DESIGNER_PREVIEW_CATALOG.get(key).builder)
            for key in ("container.column", "control.label")
        )
        host = DesignerPreviewHost(session, catalog=custom)
        before = session.snapshot
        generation = host.generation
        with self.assertRaises(DesignerPreviewUnsupportedTypeError):
            host.insert_child(
                before.root.node_id,
                DesignerNode("unsupported-button", "control.button", {"label": "Run"}),
            )
        self.assertEqual(before, session.snapshot)
        self.assertEqual(0, session.undo_depth)
        self.assertEqual(generation, host.generation)
        self.assertEqual(before, host.preview.source_snapshot)

    def test_external_session_edit_can_be_synchronized_explicitly(self):
        session = self._session()
        node_id = session.snapshot.root.children[0].node.node_id
        host = DesignerPreviewHost(session)
        session.set_property(node_id, "text", "External")
        self.assertEqual("One", host.component(node_id).text)
        self.assertTrue(host.sync())
        self.assertEqual("External", host.component(node_id).text)
        self.assertFalse(host.sync())

    def test_blank_application_code_first_tree_can_feed_optional_preview_host(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        view = DemoView(SnapshotHost())
        snapshot = view.capture_designer_snapshot()
        actions = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        session = DesignerEditSession(snapshot)
        host = DesignerPreviewHost(session)
        self.assertTrue(host.set_property(actions.node_id, "label", "Preview Actions"))
        self.assertEqual("Preview Actions", host.component(actions.node_id).label)
        self.assertEqual("Actions", view.positioned_panel.children[1].component.label)

    def test_force_rebuild_replaces_equal_snapshot(self):
        host = DesignerPreviewHost(self._session())
        first_root = host.preview.root
        self.assertTrue(host.rebuild(force=True))
        self.assertIsNot(first_root, host.preview.root)
        self.assertEqual(2, host.generation)

    def test_close_is_idempotent_and_blocks_further_work(self):
        host = DesignerPreviewHost(self._session())
        self.assertFalse(host.close())  # backend-neutral tree was never rendered
        self.assertTrue(host.closed)
        self.assertFalse(host.close())
        with self.assertRaises(RuntimeError):
            host.rebuild()

    def test_checked_edit_rejects_without_mutating_history(self):
        session = self._session()
        node_id = session.snapshot.root.children[0].node.node_id
        before = session.snapshot

        def reject(_snapshot):
            raise RuntimeError("reject")

        with self.assertRaisesRegex(RuntimeError, "reject"):
            session.execute_checked(SetDesignerProperty(node_id, "text", "No"), reject)
        self.assertEqual(before, session.snapshot)
        self.assertEqual(0, session.undo_depth)
        self.assertEqual(0, session.redo_depth)

    def test_checked_undo_redo_are_transactional(self):
        session = self._session()
        node_id = session.snapshot.root.children[0].node.node_id
        session.set_property(node_id, "text", "Two")
        changed = session.snapshot
        with self.assertRaises(RuntimeError):
            session.undo_checked(lambda _snapshot: (_ for _ in ()).throw(RuntimeError("no")))
        self.assertEqual(changed, session.snapshot)
        self.assertEqual(1, session.undo_depth)
        self.assertEqual(0, session.redo_depth)
        self.assertTrue(session.undo())
        undone = session.snapshot
        with self.assertRaises(RuntimeError):
            session.redo_checked(lambda _snapshot: (_ for _ in ()).throw(RuntimeError("no")))
        self.assertEqual(undone, session.snapshot)
        self.assertEqual(0, session.undo_depth)
        self.assertEqual(1, session.redo_depth)


if __name__ == "__main__":
    unittest.main(verbosity=2)
