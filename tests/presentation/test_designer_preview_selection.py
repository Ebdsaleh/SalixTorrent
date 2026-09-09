"""Regressions for the clickable designer preview-selection presentation surface."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from app.framework.components import Button, ControlColumn, Label
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_preview_selection import (
    DesignerPreviewSelectionBinding,
    DesignerPreviewSelectionSurface,
)
from app.framework.designer_workspace import DesignerWorkspace
from tests.helpers import PROJECT_ROOT


class FakePreviewSelectionHost:
    def __init__(self, *, bad_shape: bool = False):
        self.bad_shape = bad_shape
        self.built = []
        self.updated = []
        self.disposed = 0
        self.binding = None
        self.on_select = None

    def build(self, targets, *, parent, on_select):
        self.on_select = on_select
        mapping = {target.node_id: target.component for target in targets}
        if self.bad_shape:
            mapping = {"wrong": object()}
        binding = DesignerPreviewSelectionBinding(
            {"alive": True, "parent": parent},
            mapping,
            {"selected": tuple(t.node_id for t in targets if t.selected)},
        )
        self.binding = binding
        self.built.append((targets, parent))
        return binding

    def update(self, binding, targets):
        binding.targets.clear()
        binding.targets.update({target.node_id: target.component for target in targets})
        binding.metadata = {"selected": tuple(t.node_id for t in targets if t.selected)}
        self.updated.append(targets)

    def exists(self, binding):
        return bool(binding.panel["alive"] if hasattr(binding, "panel") else binding.surface["alive"])

    def dispose(self, binding):
        binding.surface["alive"] = False
        self.disposed += 1


class DesignerPreviewSelectionSurfaceTests(unittest.TestCase):
    def _fixture(self):
        source = ControlColumn((
            Label("Status"),
            ControlColumn((Button("Run"), Button("Stop"))),
        ))
        identities = DesignerIdentityMap(prefix="surface")
        identities.bind(source, "root")
        identities.bind(source.children[0], "status")
        identities.bind(source.children[1], "actions")
        identities.bind(source.children[1].children[0], "run")
        identities.bind(source.children[1].children[1], "stop")
        snapshot = capture_component_tree(source, identities=identities)
        return source, snapshot

    def test_build_projects_current_preview_targets_depth_and_selection(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("run")
        host = FakePreviewSelectionHost()
        surface = DesignerPreviewSelectionSurface(workspace, host)
        binding = surface.build(parent="preview")
        targets = host.built[-1][0]
        self.assertEqual(("root", "status", "actions", "run", "stop"), tuple(t.node_id for t in targets))
        self.assertEqual((0, 1, 1, 2, 2), tuple(t.depth for t in targets))
        self.assertEqual(("run",), tuple(t.node_id for t in targets if t.selected))
        self.assertEqual(tuple(t.node_id for t in targets), tuple(binding.targets))
        surface.dispose()
        workspace.close()

    def test_requires_workspace_valid_host_and_callback(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        with self.assertRaises(TypeError):
            DesignerPreviewSelectionSurface(object(), FakePreviewSelectionHost())
        with self.assertRaises(TypeError):
            DesignerPreviewSelectionSurface(workspace, object())
        with self.assertRaises(TypeError):
            DesignerPreviewSelectionSurface(workspace, FakePreviewSelectionHost(), on_change="bad")
        workspace.close()

    def test_select_delegates_to_workspace_reveals_and_is_document_neutral(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("status")
        host = FakePreviewSelectionHost()
        changes = []
        surface = DesignerPreviewSelectionSurface(workspace, host, on_change=changes.append)
        surface.build(parent="preview")
        before = workspace.state
        self.assertTrue(host.on_select("run"))
        after = workspace.state
        self.assertEqual("run", after.selected_id)
        self.assertEqual("run", after.focused_id)
        self.assertIn("actions", after.expanded_ids)
        self.assertEqual(before.preview_generation, after.preview_generation)
        self.assertEqual(before.is_dirty, after.is_dirty)
        self.assertEqual(before.can_undo, after.can_undo)
        self.assertEqual(["run"], changes)
        surface.dispose()
        workspace.close()

    def test_refresh_observes_external_selection(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("run")
        host = FakePreviewSelectionHost()
        surface = DesignerPreviewSelectionSurface(workspace, host)
        surface.build(parent="preview")
        workspace.select_and_focus_node("stop")
        surface.refresh()
        self.assertEqual(("stop",), host.binding.metadata["selected"])
        surface.dispose()
        workspace.close()

    def test_preview_replacement_refresh_rebinds_fresh_components_by_stable_id(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("run")
        host = FakePreviewSelectionHost()
        surface = DesignerPreviewSelectionSurface(workspace, host)
        surface.build(parent="preview")
        old = dict(host.binding.targets)
        old_generation = workspace.state.preview_generation
        self.assertTrue(workspace.set_selected_property("label", "Run now"))
        self.assertGreater(workspace.state.preview_generation, old_generation)
        surface.refresh()
        self.assertEqual(workspace.state.preview_generation, surface.generation)
        self.assertEqual(set(old), set(host.binding.targets))
        self.assertTrue(all(old[key] is not host.binding.targets[key] for key in old))
        surface.dispose()
        workspace.close()

    def test_unknown_or_empty_click_target_is_revalidated(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakePreviewSelectionHost()
        surface = DesignerPreviewSelectionSurface(workspace, host)
        surface.build(parent="preview")
        before = workspace.session.snapshot
        with self.assertRaises(ValueError):
            host.on_select("")
        with self.assertRaises(KeyError):
            host.on_select("missing")
        self.assertEqual(before, workspace.session.snapshot)
        surface.dispose()
        workspace.close()

    def test_clicking_current_selection_is_a_noop_but_refreshes_visual_state(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("run")
        host = FakePreviewSelectionHost()
        changes = []
        surface = DesignerPreviewSelectionSurface(workspace, host, on_change=changes.append)
        surface.build(parent="preview")
        self.assertFalse(host.on_select("run"))
        self.assertTrue(host.updated)
        self.assertEqual(["run"], changes)
        surface.dispose()
        workspace.close()

    def test_code_first_component_tree_remains_unchanged(self):
        source, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        surface = DesignerPreviewSelectionSurface(workspace, FakePreviewSelectionHost())
        surface.build(parent="preview")
        self.assertTrue(surface.select("run"))
        self.assertEqual("Run", source.children[1].children[0].label)
        self.assertIsNone(source.children[1].children[0].item)
        surface.dispose()
        workspace.close()

    def test_dispose_and_stale_binding_rebuild_are_explicit(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakePreviewSelectionHost()
        surface = DesignerPreviewSelectionSurface(workspace, host)
        first = surface.build(parent="preview")
        first.surface["alive"] = False
        second = surface.refresh()
        self.assertIsNot(first, second)
        self.assertEqual(2, len(host.built))
        self.assertTrue(surface.dispose())
        self.assertFalse(surface.dispose())
        self.assertEqual(1, host.disposed)
        workspace.close()

    def test_host_binding_shape_is_validated(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakePreviewSelectionHost(bad_shape=True)
        surface = DesignerPreviewSelectionSurface(workspace, host)
        with self.assertRaisesRegex(ValueError, "unexpected shape"):
            surface.build(parent="preview")
        self.assertEqual(1, host.disposed)
        workspace.close()

    def test_closed_workspace_rejects_interaction_but_surface_disposes(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakePreviewSelectionHost()
        surface = DesignerPreviewSelectionSurface(workspace, host)
        surface.build(parent="preview")
        workspace.close()
        with self.assertRaisesRegex(RuntimeError, "workspace is closed"):
            surface.select("run")
        self.assertTrue(surface.dispose())

    def test_surface_boundaries_keep_semantics_out_of_toolkits(self):
        framework = PROJECT_ROOT / "app" / "framework" / "designer_preview_selection.py"
        dpg = PROJECT_ROOT / "app" / "engine" / "designer_preview_selection_hosts" / "dearpygui.py"
        tkinter = PROJECT_ROOT / "app" / "engine" / "designer_preview_selection_hosts" / "tkinter.py"

        def imports(path: Path):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            result = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    result.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    result.append(node.module)
            return tuple(result)

        self.assertFalse(
            any(name.startswith(("app.engine", "dearpygui", "tkinter")) for name in imports(framework))
        )
        forbidden_product = ("app.logic", "app.views", "app.localization", "app.persistence")
        self.assertFalse(any(name.startswith(forbidden_product) for name in imports(dpg)))
        self.assertFalse(any(name.startswith(forbidden_product) for name in imports(tkinter)))
        self.assertFalse(any(name.startswith("tkinter") for name in imports(dpg)))
        self.assertFalse(any(name.startswith("dearpygui") for name in imports(tkinter)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
