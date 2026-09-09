from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.framework.components import Button, ControlColumn, Label
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_project import (
    DESIGNER_PROJECT_KIND,
    DESIGNER_PROJECT_VERSION,
    DesignerProjectDocument,
    DesignerProjectFile,
    DesignerProjectFormatError,
    load_designer_project,
)
from app.framework.designer_preview_host import DesignerPreviewHost


class DesignerProjectTests(unittest.TestCase):
    def _snapshot(self):
        root = ControlColumn((Label("One"), Button("Run")))
        ids = DesignerIdentityMap(prefix="project")
        ids.bind(root, "project-root")
        return capture_component_tree(root, identities=ids)

    def _label(self, project: DesignerProjectFile):
        return next(
            node for node in project.session.snapshot.root.walk()
            if node.type_key == "control.label"
        )

    def test_document_envelope_round_trips_deterministically(self):
        snapshot = self._snapshot()
        document = DesignerProjectDocument(snapshot)
        descriptor = document.to_descriptor()
        self.assertEqual(DESIGNER_PROJECT_KIND, descriptor["kind"])
        self.assertEqual(DESIGNER_PROJECT_VERSION, descriptor["version"])
        self.assertEqual(snapshot.to_descriptor(), descriptor["snapshot"])
        first = document.to_json()
        second = DesignerProjectDocument.from_json(first).to_json()
        self.assertEqual(first, second)
        self.assertEqual(snapshot, DesignerProjectDocument.from_json(first).snapshot)

    def test_document_rejects_wrong_shape_kind_version_and_unknown_fields(self):
        descriptor = DesignerProjectDocument(self._snapshot()).to_descriptor()
        cases = []
        missing = dict(descriptor)
        missing.pop("snapshot")
        cases.append(missing)
        wrong_kind = dict(descriptor, kind="other-project")
        cases.append(wrong_kind)
        wrong_version = dict(descriptor, version=99)
        cases.append(wrong_version)
        non_integer_version = dict(descriptor, version=1.0)
        cases.append(non_integer_version)
        unknown = dict(descriptor, future=True)
        cases.append(unknown)
        for candidate in cases:
            with self.subTest(candidate=candidate.keys()):
                with self.assertRaises((DesignerProjectFormatError, TypeError)):
                    DesignerProjectDocument.from_descriptor(candidate)

    def test_json_loader_rejects_duplicate_keys_nonfinite_values_and_non_object_root(self):
        with self.assertRaisesRegex(DesignerProjectFormatError, "duplicate key"):
            DesignerProjectDocument.from_json(
                '{"kind":"salix-designer-project","kind":"again","version":1,"snapshot":{}}'
            )
        with self.assertRaisesRegex(DesignerProjectFormatError, "non-finite"):
            DesignerProjectDocument.from_json(
                '{"kind":"salix-designer-project","version":1,"snapshot":NaN}'
            )
        with self.assertRaisesRegex(DesignerProjectFormatError, "must contain an object"):
            DesignerProjectDocument.from_json("[]")

    def test_new_project_is_unsaved_and_dirty_even_before_document_edits(self):
        project = DesignerProjectFile.create(self._snapshot())
        self.assertIsNone(project.path)
        self.assertFalse(project.has_path)
        self.assertFalse(project.is_persisted)
        self.assertTrue(project.is_dirty)
        self.assertFalse(project.session.is_dirty)
        self.assertEqual(project.state.is_dirty, project.is_dirty)
        with self.assertRaisesRegex(ValueError, "no save path"):
            project.save()

    def test_prospective_path_does_not_claim_persistence_until_first_successful_save(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "draft.project"
            project = DesignerProjectFile.create(self._snapshot(), path=target)
            self.assertEqual(target.absolute(), project.path)
            self.assertTrue(project.has_path)
            self.assertFalse(project.is_persisted)
            self.assertTrue(project.is_dirty)
            saved = project.save()
            self.assertEqual(target.absolute(), saved)
            self.assertTrue(target.is_file())
            self.assertTrue(project.is_persisted)
            self.assertFalse(project.is_dirty)

    def test_save_load_and_edit_dirty_semantics_follow_edit_session_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "sample.project"
            project = DesignerProjectFile.create(self._snapshot())
            project.save(target)
            label = self._label(project)
            self.assertTrue(project.session.set_property(label.node_id, "text", "Edited"))
            self.assertTrue(project.is_dirty)
            project.save()
            self.assertFalse(project.is_dirty)
            reopened = load_designer_project(target)
            self.assertFalse(reopened.is_dirty)
            self.assertEqual("Edited", self._label(reopened).properties["text"])
            self.assertEqual(project.session.snapshot, reopened.session.snapshot)

    def test_save_as_commits_new_ownership_only_after_success(self):
        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / "first.project"
            project = DesignerProjectFile.create(self._snapshot())
            project.save(first)
            label = self._label(project)
            project.session.set_property(label.node_id, "text", "Unsaved")
            occupied_target = Path(td) / "occupied"
            occupied_target.mkdir()
            with self.assertRaises(OSError):
                project.save_as(occupied_target)
            self.assertEqual(first.absolute(), project.path)
            self.assertTrue(project.is_dirty)
            self.assertEqual("Unsaved", self._label(project).properties["text"])
            self.assertEqual([], list(Path(td).glob(".occupied.*.tmp")))

    def test_save_as_changes_owner_and_leaves_previous_file_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / "first.project"
            second = Path(td) / "second.any-extension"
            project = DesignerProjectFile.create(self._snapshot())
            project.save(first)
            original_text = first.read_text(encoding="utf-8")
            label = self._label(project)
            project.session.set_property(label.node_id, "text", "Second")
            project.save_as(second)
            self.assertEqual(second.absolute(), project.path)
            self.assertEqual(original_text, first.read_text(encoding="utf-8"))
            self.assertEqual("Second", self._label(load_designer_project(second)).properties["text"])

    def test_ephemeral_selection_clipboard_and_history_are_not_persisted(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "ephemeral.project"
            project = DesignerProjectFile.create(self._snapshot())
            label = self._label(project)
            project.session.select_and_focus_node(label.node_id)
            project.session.copy_node(label.node_id)
            project.session.set_property(label.node_id, "text", "Persisted")
            self.assertTrue(project.session.can_undo)
            project.save(target)
            reopened = DesignerProjectFile.open(target)
            self.assertFalse(reopened.session.has_selection)
            self.assertFalse(reopened.session.has_focus)
            self.assertFalse(reopened.session.has_clipboard)
            self.assertFalse(reopened.session.can_undo)
            self.assertFalse(reopened.session.can_redo)
            self.assertEqual("Persisted", self._label(reopened).properties["text"])

    def test_loaded_project_feeds_existing_preview_host_without_special_runtime_path(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "preview.project"
            project = DesignerProjectFile.create(self._snapshot())
            project.save(target)
            reopened = DesignerProjectFile.open(target)
            label = self._label(reopened)
            host = DesignerPreviewHost(reopened.session)
            self.assertEqual("One", host.component(label.node_id).text)
            self.assertTrue(host.set_property(label.node_id, "text", "Previewed"))
            self.assertTrue(reopened.is_dirty)
            reopened.save()
            self.assertFalse(reopened.is_dirty)
            host.close()
            third = DesignerProjectFile.open(target)
            self.assertEqual("Previewed", self._label(third).properties["text"])

    def test_blank_application_code_first_snapshot_round_trips_without_mutating_live_tree(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        view = DemoView(SnapshotHost())
        before = view.capture_designer_snapshot()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "blank.project"
            project = DesignerProjectFile.create(before)
            project.save(path)
            reopened = DesignerProjectFile.open(path)
            self.assertEqual(before.to_descriptor(), reopened.session.snapshot.to_descriptor())
        self.assertEqual(before.to_descriptor(), view.capture_designer_snapshot().to_descriptor())

    def test_saved_text_is_canonical_utf8_json_with_single_terminal_newline(self):
        snapshot = capture_component_tree(ControlColumn((Label("München 東京"),)))
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "unicode"
            project = DesignerProjectFile.create(snapshot)
            project.save(target)
            raw = target.read_bytes()
            self.assertTrue(raw.endswith(b"\n"))
            self.assertFalse(raw.endswith(b"\n\n"))
            text = raw.decode("utf-8")
            self.assertIn("München 東京", text)
            parsed = json.loads(text)
            self.assertEqual(DESIGNER_PROJECT_KIND, parsed["kind"])
            self.assertEqual(snapshot, DesignerProjectFile.open(target).session.snapshot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
