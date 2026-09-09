"""Concrete hierarchy-panel presentation regressions for designer tooling."""

from __future__ import annotations

import ast
import unittest

from tests.helpers import PROJECT_ROOT

from app.framework.components import Button, ControlColumn, Label
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_hierarchy_panel import (
    DesignerHierarchyPanel,
    DesignerHierarchyPanelBinding,
)
from app.framework.designer_workspace import DesignerWorkspace


class FakeHierarchyPanelHost:
    def __init__(self):
        self.binding = None
        self.on_select = None
        self.on_toggle = None
        self.built = []
        self.updated = []
        self.disposed = 0

    @staticmethod
    def _row_items(rows):
        return {row.node_id: {"row": row, "alive": True} for row in rows}

    def build(self, rows, *, parent, title="", on_select=None, on_toggle=None):
        self.on_select = on_select
        self.on_toggle = on_toggle
        self.built.append(tuple(rows))
        self.binding = DesignerHierarchyPanelBinding(
            panel={"alive": True, "parent": parent, "title": str(title)},
            rows=self._row_items(rows),
        )
        return self.binding

    def update(self, binding, rows):
        self.updated.append(tuple(rows))
        binding.rows.clear()
        binding.rows.update(self._row_items(rows))

    def exists(self, binding):
        return bool(binding.panel["alive"])

    def dispose(self, binding):
        binding.panel["alive"] = False
        self.disposed += 1


class DesignerHierarchyPanelTests(unittest.TestCase):
    def _fixture(self):
        first = Label("First")
        run = Button("Run")
        stop = Button("Stop")
        inner = ControlColumn((run, stop))
        last = Label("Last")
        root = ControlColumn((first, inner, last))
        ids = DesignerIdentityMap(prefix="panel")
        ids.bind(root, "root")
        ids.bind(first, "first")
        ids.bind(inner, "inner")
        ids.bind(run, "run")
        ids.bind(stop, "stop")
        ids.bind(last, "last")
        return root, capture_component_tree(root, identities=ids)

    def test_requires_workspace_and_valid_host(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        with self.assertRaisesRegex(TypeError, "requires DesignerWorkspace"):
            DesignerHierarchyPanel(object(), FakeHierarchyPanelHost())
        with self.assertRaisesRegex(TypeError, "DesignerHierarchyPanelHost"):
            DesignerHierarchyPanel(workspace, object())
        with self.assertRaisesRegex(TypeError, "change handler"):
            DesignerHierarchyPanel(workspace, FakeHierarchyPanelHost(), on_change=object())
        workspace.close()

    def test_build_projects_current_visible_rows_and_title(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeHierarchyPanelHost()
        panel = DesignerHierarchyPanel(workspace, host, title="Project Tree")
        binding = panel.build(parent="left-pane")
        self.assertTrue(panel.exists())
        self.assertEqual("left-pane", binding.panel["parent"])
        self.assertEqual("Project Tree", binding.panel["title"])
        self.assertEqual(("root", "first", "inner", "last"), tuple(binding.rows))
        self.assertEqual(panel.visible_ids, tuple(binding.rows))
        panel.dispose()
        workspace.close()

    def test_select_delegates_to_workspace_without_preview_rebuild(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeHierarchyPanelHost()
        panel = DesignerHierarchyPanel(workspace, host)
        panel.build(parent="panel")
        generation = workspace.state.preview_generation
        self.assertTrue(host.on_select("inner"))
        state = workspace.state
        self.assertEqual("inner", state.selected_id)
        self.assertEqual("inner", state.focused_id)
        self.assertEqual(generation, state.preview_generation)
        row = next(row for row in host.updated[-1] if row.node_id == "inner")
        self.assertTrue(row.selected)
        self.assertTrue(row.focused)
        panel.dispose()
        workspace.close()

    def test_toggle_expands_and_collapses_through_workspace(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeHierarchyPanelHost()
        panel = DesignerHierarchyPanel(workspace, host)
        panel.build(parent="panel")
        generation = workspace.state.preview_generation
        self.assertTrue(host.on_toggle("inner"))
        self.assertEqual(("root", "inner"), workspace.state.expanded_ids)
        self.assertEqual(("root", "first", "inner", "run", "stop", "last"), panel.visible_ids)
        self.assertEqual(generation, workspace.state.preview_generation)
        self.assertTrue(host.on_toggle("inner"))
        self.assertEqual(("root",), workspace.state.expanded_ids)
        self.assertFalse(panel.toggle("first"))
        panel.dispose()
        workspace.close()

    def test_change_handler_observes_direct_panel_interactions(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeHierarchyPanelHost()
        seen = []
        panel = DesignerHierarchyPanel(workspace, host, on_change=lambda: seen.append(workspace.state))
        panel.build(parent="panel")
        self.assertTrue(panel.select("inner"))
        self.assertEqual("inner", seen[-1].selected_id)
        self.assertTrue(panel.toggle("inner"))
        self.assertIn("inner", seen[-1].expanded_ids)
        workspace.select_and_focus_node("run")
        panel.reveal_selected()
        self.assertEqual("run", seen[-1].selected_id)
        panel.dispose()
        workspace.close()

    def test_reveal_selected_expands_ancestors_and_refreshes(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeHierarchyPanelHost()
        panel = DesignerHierarchyPanel(workspace, host)
        panel.build(parent="panel")
        workspace.select_and_focus_node("run")
        self.assertNotIn("run", panel.visible_ids)
        reveal = panel.reveal_selected()
        self.assertEqual(("root", "inner", "run"), reveal.path_ids)
        self.assertIn("run", panel.visible_ids)
        row = next(row for row in host.updated[-1] if row.node_id == "run")
        self.assertTrue(row.selected)
        self.assertTrue(row.focused)
        panel.dispose()
        workspace.close()

    def test_refresh_observes_external_selection_and_expansion(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeHierarchyPanelHost()
        panel = DesignerHierarchyPanel(workspace, host)
        panel.build(parent="panel")
        workspace.select_and_focus_node("stop")
        workspace.reveal_selected_in_hierarchy()
        panel.refresh()
        self.assertIn("stop", panel.visible_ids)
        stop = next(row for row in host.updated[-1] if row.node_id == "stop")
        self.assertTrue(stop.selected)
        self.assertTrue(stop.focused)
        panel.dispose()
        workspace.close()

    def test_stale_hidden_row_callback_is_revalidated(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeHierarchyPanelHost()
        panel = DesignerHierarchyPanel(workspace, host)
        panel.build(parent="panel")
        self.assertTrue(panel.toggle("inner"))
        stale_select = host.on_select
        self.assertIn("run", panel.visible_ids)
        self.assertTrue(panel.toggle("inner"))
        self.assertNotIn("run", panel.visible_ids)
        with self.assertRaisesRegex(KeyError, "row is not visible"):
            stale_select("run")
        panel.dispose()
        workspace.close()

    def test_document_edit_and_undo_refresh_reconciles_rows(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("run")
        workspace.reveal_selected_in_hierarchy()
        host = FakeHierarchyPanelHost()
        panel = DesignerHierarchyPanel(workspace, host)
        panel.build(parent="panel")
        self.assertTrue(workspace.duplicate_selected())
        panel.refresh()
        self.assertIn("run-copy", panel.visible_ids)
        self.assertTrue(workspace.undo())
        panel.refresh()
        self.assertNotIn("run-copy", panel.visible_ids)
        panel.dispose()
        workspace.close()

    def test_dispose_and_stale_binding_rebuild_are_explicit(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeHierarchyPanelHost()
        panel = DesignerHierarchyPanel(workspace, host)
        first = panel.build(parent="panel")
        first.panel["alive"] = False
        second = panel.refresh()
        self.assertIsNot(first, second)
        self.assertEqual(2, len(host.built))
        self.assertTrue(panel.dispose())
        self.assertFalse(panel.dispose())
        self.assertEqual(1, host.disposed)
        workspace.close()

    def test_closed_workspace_rejects_interaction_but_panel_disposes(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeHierarchyPanelHost()
        panel = DesignerHierarchyPanel(workspace, host)
        panel.build(parent="panel")
        workspace.close()
        with self.assertRaisesRegex(RuntimeError, "workspace is closed"):
            host.on_select("inner")
        self.assertTrue(panel.dispose())

    def test_surface_boundaries_keep_semantics_out_of_toolkits(self):
        framework = PROJECT_ROOT / "app" / "framework" / "designer_hierarchy_panel.py"
        dpg = PROJECT_ROOT / "app" / "engine" / "designer_hierarchy_panel_hosts" / "dearpygui.py"
        tkinter = PROJECT_ROOT / "app" / "engine" / "designer_hierarchy_panel_hosts" / "tkinter.py"

        def imports(path):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            result = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    result.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    result.append(node.module)
            return tuple(result)

        framework_imports = imports(framework)
        self.assertFalse(any(name.startswith(("app.engine", "dearpygui", "tkinter")) for name in framework_imports))
        forbidden_product = ("app.logic", "app.views", "app.localization", "app.persistence")
        self.assertFalse(any(name.startswith(forbidden_product) for name in imports(dpg)))
        self.assertFalse(any(name.startswith("tkinter") for name in imports(dpg)))
        self.assertFalse(any(name.startswith(forbidden_product) for name in imports(tkinter)))
        self.assertFalse(any(name.startswith("dearpygui") for name in imports(tkinter)))

    def test_code_first_component_tree_remains_unchanged(self):
        source, snapshot = self._fixture()
        before_children = tuple(source.children)
        before_inner_children = tuple(source.children[1].children)
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeHierarchyPanelHost()
        panel = DesignerHierarchyPanel(workspace, host)
        panel.build(parent="panel")
        panel.select("inner")
        panel.toggle("inner")
        panel.select("run")
        panel.toggle("inner")
        self.assertEqual(before_children, tuple(source.children))
        self.assertEqual(before_inner_children, tuple(source.children[1].children))
        self.assertEqual("Run", source.children[1].children[0].label)
        self.assertEqual("Stop", source.children[1].children[1].label)
        panel.dispose()
        workspace.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
