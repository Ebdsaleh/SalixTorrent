"""Regressions for live Inspector numeric-scrub preview feedback."""
from __future__ import annotations

import ast
import unittest

from tests.helpers import PROJECT_ROOT
from app.framework.components import Button, ControlColumn, ControlLayout
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_inspector_panel import DesignerInspectorPanel, DesignerInspectorPanelBinding
from app.framework.designer_workspace import DesignerWorkspace


class _Host:
    def __init__(self):
        self.binding = None
        self.on_set = None
        self.on_scrub_base = None
        self.on_scrub_preview = None

    @staticmethod
    def _rows(state):
        return {row.key: object() for row in state.rows}

    def build(
        self, state, *, parent, title="", on_set=None, on_clear=None, on_error=None,
        on_reset=None, on_scrub_base=None, on_scrub_preview=None,
    ):
        self.on_set = on_set
        self.on_scrub_base = on_scrub_base
        self.on_scrub_preview = on_scrub_preview
        self.binding = DesignerInspectorPanelBinding(
            panel={"alive": True, "parent": parent}, rows=self._rows(state)
        )
        return self.binding

    def update(self, binding, state):
        binding.rows.clear()
        binding.rows.update(self._rows(state))

    def exists(self, binding):
        return bool(binding.panel["alive"])

    def dispose(self, binding):
        binding.panel["alive"] = False


class DesignerInspectorLivePreviewTests(unittest.TestCase):
    def _workspace(self):
        action = Button("Actions", layout=ControlLayout(width=120, height=28, spacing=4))
        secondary = Button("Secondary", layout=ControlLayout(width=90, height=28))
        root = ControlColumn((action, secondary))
        ids = DesignerIdentityMap(prefix="live-scrub")
        ids.bind(root, "root")
        ids.bind(action, "action")
        ids.bind(secondary, "secondary")
        workspace = DesignerWorkspace.create(capture_component_tree(root, identities=ids))
        workspace.select_and_focus_node("action")
        return workspace

    def test_preview_property_draft_is_document_history_and_dirty_neutral(self):
        workspace = self._workspace()
        before = workspace.session.snapshot
        undo_depth = workspace.session.undo_depth
        generation = workspace.preview_host.generation
        dirty = workspace.state.is_dirty
        self.assertTrue(workspace.preview_selected_property("layout.width", 180))
        self.assertTrue(workspace.preview_host.has_preview_draft)
        self.assertEqual(before, workspace.session.snapshot)
        self.assertEqual(undo_depth, workspace.session.undo_depth)
        self.assertEqual(dirty, workspace.state.is_dirty)
        self.assertGreater(workspace.preview_host.generation, generation)
        self.assertEqual(180, workspace.preview_host.selected_component.layout.width)
        workspace.close()

    def test_repeated_drafts_are_absolute_against_authoritative_snapshot(self):
        workspace = self._workspace()
        self.assertTrue(workspace.preview_selected_property("layout.width", 180))
        self.assertTrue(workspace.preview_selected_property("layout.width", 135))
        self.assertEqual(135, workspace.preview_host.selected_component.layout.width)
        self.assertEqual(120, workspace.inspector_state().row("layout.width").value)
        self.assertEqual(0, workspace.session.undo_depth)
        workspace.close()

    def test_returning_to_authoritative_value_cancels_draft(self):
        workspace = self._workspace()
        self.assertTrue(workspace.preview_selected_property("layout.width", 180))
        self.assertTrue(workspace.preview_host.has_preview_draft)
        self.assertTrue(workspace.preview_selected_property("layout.width", 120))
        self.assertFalse(workspace.preview_host.has_preview_draft)
        self.assertEqual(120, workspace.preview_host.selected_component.layout.width)
        self.assertEqual(0, workspace.session.undo_depth)
        workspace.close()

    def test_commit_after_live_draft_is_one_history_step(self):
        workspace = self._workspace()
        workspace.preview_selected_property("layout.width", 180)
        self.assertTrue(workspace.set_selected_property("layout.width", 180))
        self.assertFalse(workspace.preview_host.has_preview_draft)
        self.assertEqual(1, workspace.session.undo_depth)
        self.assertEqual(180, workspace.inspector_state().row("layout.width").value)
        self.assertTrue(workspace.undo())
        self.assertEqual(120, workspace.inspector_state().row("layout.width").value)
        workspace.close()

    def test_semantic_noop_release_cannot_leave_a_preview_draft(self):
        workspace = self._workspace()
        workspace.preview_selected_property("layout.width", 180)
        # The final semantic value is unchanged from the document. execute() is
        # a no-op, but it must still retire the transient candidate.
        self.assertFalse(workspace.set_selected_property("layout.width", 120))
        self.assertFalse(workspace.preview_host.has_preview_draft)
        self.assertEqual(120, workspace.preview_host.selected_component.layout.width)
        self.assertEqual(0, workspace.session.undo_depth)
        workspace.close()

    def test_panel_scrub_preview_rebuilds_without_refreshing_document_state(self):
        workspace = self._workspace()
        host = _Host()
        previews = []
        panel = DesignerInspectorPanel(
            workspace, host,
            on_preview=lambda node, key, value: previews.append((node, key, value)),
        )
        panel.build(parent="right")
        before = workspace.session.snapshot
        self.assertTrue(host.on_scrub_preview("action", "layout.width", 200))
        self.assertEqual(before, workspace.session.snapshot)
        self.assertEqual(("action", "layout.width", 200), previews[-1])
        self.assertEqual(200, workspace.preview_host.selected_component.layout.width)
        # Inspector state remains authoritative until release.
        self.assertEqual(120, panel.state.row("layout.width").value)
        panel.dispose()
        workspace.close()

    def test_stale_scrub_preview_is_rejected_without_mutation(self):
        workspace = self._workspace()
        host = _Host()
        errors = []
        panel = DesignerInspectorPanel(
            workspace, host,
            on_error=lambda key, exc: errors.append((key, exc)),
        )
        panel.build(parent="right")
        stale = host.on_scrub_preview
        before = workspace.session.snapshot
        workspace.select_and_focus_node("secondary")
        panel.refresh()
        self.assertFalse(stale("action", "layout.width", 240))
        self.assertEqual(before, workspace.session.snapshot)
        self.assertFalse(workspace.preview_host.has_preview_draft)
        self.assertIsInstance(errors[-1][1], KeyError)
        panel.dispose()
        workspace.close()

    def test_stale_release_after_live_draft_restores_authoritative_preview(self):
        workspace = self._workspace()
        host = _Host()
        errors = []
        panel = DesignerInspectorPanel(
            workspace, host,
            on_error=lambda key, exc: errors.append((key, exc)),
        )
        panel.build(parent="right")
        stale_set = host.on_set
        self.assertTrue(host.on_scrub_preview("action", "layout.width", 240))
        self.assertTrue(workspace.preview_host.has_preview_draft)
        workspace.select_and_focus_node("secondary")
        panel.refresh()
        self.assertFalse(stale_set("action", "layout.width", 240))
        self.assertFalse(workspace.preview_host.has_preview_draft)
        self.assertEqual(120, workspace.preview_host.component("action").layout.width)
        self.assertEqual(0, workspace.session.undo_depth)
        self.assertIsInstance(errors[-1][1], KeyError)
        panel.dispose()
        workspace.close()

    def test_concrete_scrub_hosts_request_live_preview_during_motion(self):
        dpg = (PROJECT_ROOT / "app" / "engine" / "designer_inspector_panel_hosts" / "dearpygui.py").read_text(encoding="utf-8")
        tk = (PROJECT_ROOT / "app" / "engine" / "designer_inspector_panel_hosts" / "tkinter.py").read_text(encoding="utf-8")
        self.assertIn("on_scrub_preview(drag[\"node_id\"], row.key, value)", dpg)
        self.assertIn("on_scrub_preview(n, r.key, value)", tk)
        self.assertIn("on_set(drag[\"node_id\"], drag[\"row\"].key, drag[\"value\"])", dpg)
        self.assertIn("defer(lambda: on_set(n, r.key, value))", tk)

    def test_live_preview_framework_paths_have_no_toolkit_or_product_imports(self):
        for relative in (
            "app/framework/designer_preview_host.py",
            "app/framework/designer_inspector_panel.py",
            "app/framework/designer_workspace.py",
        ):
            tree = ast.parse((PROJECT_ROOT / relative).read_text(encoding="utf-8"))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            joined = "\n".join(imports).lower()
            self.assertNotIn("dearpygui", joined)
            self.assertNotIn("tkinter", joined)
            self.assertNotIn("app.views", joined)
            self.assertNotIn("torrent", joined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
