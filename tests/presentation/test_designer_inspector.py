"""Backend-neutral property-inspector presentation regressions."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.framework.components import Button, ControlColumn, ControlLayout, Label
from app.framework.designer import DesignerIdentityMap, DesignerValueKind, capture_component_tree
from app.framework.designer_editing import DesignerEditSession, DesignerPropertyState
from app.framework.designer_inspector import (
    DesignerInspectorEditorKind,
    DesignerInspectorRow,
    DesignerInspectorState,
    DesignerPropertyInspector,
    inspector_editor_kind,
)
from app.framework.designer_preview_host import DesignerPreviewHost
from app.framework.designer_project import DesignerProjectFile


class DesignerInspectorTests(unittest.TestCase):
    def _snapshot(self):
        label = Label("Status")
        action = Button("Run", layout=ControlLayout(width=120, height=30))
        root = ControlColumn((label, action))
        identities = DesignerIdentityMap(prefix="inspector")
        identities.bind(root, "root")
        identities.bind(label, "status")
        identities.bind(action, "action")
        return root, capture_component_tree(root, identities=identities)

    def test_inspector_starts_empty_without_selection(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        inspector = DesignerPropertyInspector(session)
        state = inspector.state()
        self.assertEqual(DesignerInspectorState(), state)
        self.assertFalse(state.has_target)
        self.assertEqual(0, state.row_count)
        self.assertEqual({"target": None, "rows": []}, state.to_descriptor())
        self.assertEqual((), inspector.rows())
        self.assertIsNone(inspector.row("label"))

    def test_selected_node_projects_type_header_and_property_order(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        session.select_node("action")
        state = session.inspector_state()
        self.assertEqual("action", state.node_id)
        self.assertEqual("control.button", state.type_key)
        self.assertEqual("Button", state.type_label)
        self.assertEqual("control", state.category)
        self.assertEqual(
            ("profile_key", "layout.width", "layout.height", "layout.spacing", "label", "enabled", "show"),
            tuple(row.key for row in state.rows),
        )
        self.assertEqual(len(state.rows), state.row_count)

    def test_editor_hints_cover_every_designer_value_kind(self):
        expected = {
            DesignerValueKind.TEXT: DesignerInspectorEditorKind.TEXT,
            DesignerValueKind.BOOLEAN: DesignerInspectorEditorKind.TOGGLE,
            DesignerValueKind.INTEGER: DesignerInspectorEditorKind.INTEGER,
            DesignerValueKind.NUMBER: DesignerInspectorEditorKind.NUMBER,
            DesignerValueKind.CHOICE: DesignerInspectorEditorKind.CHOICE,
            DesignerValueKind.STRING_LIST: DesignerInspectorEditorKind.STRING_LIST,
            DesignerValueKind.NUMBER_LIST: DesignerInspectorEditorKind.NUMBER_LIST,
            DesignerValueKind.DIMENSION: DesignerInspectorEditorKind.DIMENSION,
            DesignerValueKind.INSETS: DesignerInspectorEditorKind.INSETS,
        }
        self.assertEqual(expected, {kind: inspector_editor_kind(kind) for kind in DesignerValueKind})
        self.assertEqual(DesignerInspectorEditorKind.TOGGLE, inspector_editor_kind("boolean"))
        with self.assertRaises(ValueError):
            inspector_editor_kind("unknown")

    def test_rows_preserve_property_state_and_derive_edit_clear_capabilities(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        session.select_node("action")
        width = session.inspected_property("layout.width")
        profile = session.inspected_property("profile_key")
        self.assertIsInstance(width.property, DesignerPropertyState)
        self.assertEqual(DesignerInspectorEditorKind.DIMENSION, width.editor)
        self.assertTrue(width.can_edit)
        self.assertTrue(width.can_clear)
        self.assertEqual(120, width.value)
        self.assertFalse(profile.can_edit)
        self.assertFalse(profile.can_clear)
        descriptor = width.to_descriptor()
        self.assertEqual("dimension", descriptor["editor"])
        self.assertTrue(descriptor["can_edit"])
        self.assertTrue(descriptor["can_clear"])

    def test_include_read_only_filter_is_projection_only(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        session.select_node("action")
        all_rows = session.inspector_rows()
        editable_rows = session.inspector_rows(include_read_only=False)
        self.assertIn("profile_key", {row.key for row in all_rows})
        self.assertNotIn("profile_key", {row.key for row in editable_rows})
        self.assertEqual(snapshot, session.snapshot)
        self.assertFalse(session.is_dirty)
        self.assertEqual(0, session.undo_depth)

    def test_selection_changes_retarget_inspector_without_document_history(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        self.assertTrue(session.select_node("status"))
        self.assertEqual("Label", session.inspector_state().type_label)
        self.assertTrue(session.select_node("action"))
        self.assertEqual("Button", session.inspector_state().type_label)
        self.assertFalse(session.is_dirty)
        self.assertEqual(0, session.undo_depth)
        self.assertEqual(snapshot, session.snapshot)

    def test_selected_property_edit_uses_existing_validation_and_history(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        session.select_node("action")
        self.assertTrue(session.set_selected_property("label", "Edited"))
        self.assertEqual("Edited", session.inspected_property("label").value)
        self.assertTrue(session.is_dirty)
        self.assertEqual(1, session.undo_depth)
        self.assertTrue(session.undo())
        self.assertEqual("Run", session.inspected_property("label").value)
        self.assertEqual("action", session.selected_node_id)

    def test_selected_property_clear_uses_existing_unsettable_contract(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        session.select_node("action")
        width = session.inspected_property("layout.width")
        self.assertTrue(width.can_clear)
        self.assertTrue(session.clear_selected_property("layout.width"))
        width = session.inspected_property("layout.width")
        self.assertFalse(width.is_set)
        self.assertFalse(width.can_clear)
        with self.assertRaisesRegex(ValueError, "cannot be unset"):
            session.clear_selected_property("label")

    def test_selected_property_helpers_require_selection(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        with self.assertRaisesRegex(RuntimeError, "no selected node"):
            session.set_selected_property("label", "Nope")
        with self.assertRaisesRegex(RuntimeError, "no selected node"):
            session.clear_selected_property("layout.width")
        self.assertIsNone(session.inspected_property("label"))

    def test_preview_host_inspector_projection_does_not_rebuild_but_edit_does(self):
        _, snapshot = self._snapshot()
        session = DesignerEditSession(snapshot)
        host = DesignerPreviewHost(session)
        generation = host.generation
        self.assertTrue(host.select_and_focus_node("action"))
        self.assertEqual("Run", host.inspected_property("label").value)
        self.assertEqual(generation, host.generation)
        before = host.selected_component
        self.assertTrue(host.set_selected_property("label", "Preview"))
        self.assertEqual(generation + 1, host.generation)
        self.assertEqual("Preview", host.inspected_property("label").value)
        self.assertIsNot(before, host.selected_component)
        self.assertEqual("Preview", host.selected_component.label)
        host.close()

    def test_project_round_trip_does_not_persist_inspector_selection(self):
        _, snapshot = self._snapshot()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "inspector.project"
            project = DesignerProjectFile.create(snapshot)
            project.session.select_node("action")
            self.assertTrue(project.session.inspector_state().has_target)
            project.save(path)
            reopened = DesignerProjectFile.open(path)
            self.assertFalse(reopened.session.inspector_state().has_target)
            self.assertFalse(reopened.session.has_selection)
            self.assertEqual(snapshot.to_descriptor(), reopened.session.snapshot.to_descriptor())

    def test_blank_code_first_tree_remains_unchanged_by_optional_inspector(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        view = DemoView(SnapshotHost())
        before = view.capture_designer_snapshot()
        actions = next(
            node for node in before.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        session = DesignerEditSession(before)
        session.select_node(actions.node_id)
        state = session.inspector_state()
        self.assertEqual("Button", state.type_label)
        self.assertEqual("Actions", state.row("label").value)
        self.assertEqual(before.to_descriptor(), view.capture_designer_snapshot().to_descriptor())
        self.assertEqual("Actions", view.positioned_panel.children[1].component.label)


if __name__ == "__main__":
    unittest.main(verbosity=2)
