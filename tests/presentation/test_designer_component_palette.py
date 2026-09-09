"""Regressions for the request-only designer component-palette surface."""

from __future__ import annotations

import ast
import json
import unittest

from app.framework.components import Button, ControlColumn, Label
from app.framework.designer import (
    DesignerCatalog,
    DesignerIdentityMap,
    FRAMEWORK_DESIGNER_CATALOG,
    capture_component_tree,
)
from app.framework.designer_component_palette import (
    DesignerComponentInsertRequest,
    DesignerComponentPalette,
    DesignerComponentPaletteBinding,
)
from app.framework.designer_workspace import DesignerWorkspace
from tests.helpers import PROJECT_ROOT


class FakeComponentPaletteHost:
    def __init__(self, *, bad_shape: bool = False):
        self.bad_shape = bad_shape
        self.binding = None
        self.on_activate = None
        self.built = []
        self.updated = []
        self.disposed = 0

    @staticmethod
    def _items(state):
        return {entry.component_type_key: {"entry": entry} for entry in state.entries}

    def build(self, state, *, parent, title="", on_activate=None):
        self.on_activate = on_activate
        items = self._items(state)
        if self.bad_shape:
            items = {"wrong": object()}
        self.binding = DesignerComponentPaletteBinding(
            panel={"alive": True, "parent": parent, "title": str(title)},
            items=items,
            metadata={"state": state},
        )
        self.built.append(state)
        return self.binding

    def update(self, binding, state):
        binding.items.clear()
        binding.items.update(self._items(state))
        binding.metadata = {"state": state}
        self.updated.append(state)

    def exists(self, binding):
        return bool(binding.panel["alive"])

    def dispose(self, binding):
        binding.panel["alive"] = False
        self.disposed += 1


class DesignerComponentPaletteTests(unittest.TestCase):
    def _fixture(self):
        label = Label("Status")
        button = Button("Run")
        root = ControlColumn((label, button))
        identities = DesignerIdentityMap(prefix="palette")
        identities.bind(root, "root")
        identities.bind(label, "status")
        identities.bind(button, "run")
        return root, capture_component_tree(root, identities=identities)

    def test_requires_workspace_catalog_valid_host_and_callback(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        with self.assertRaisesRegex(TypeError, "requires DesignerWorkspace"):
            DesignerComponentPalette(object(), FakeComponentPaletteHost())
        with self.assertRaisesRegex(TypeError, "catalog must be DesignerCatalog"):
            DesignerComponentPalette(workspace, FakeComponentPaletteHost(), catalog=object())
        with self.assertRaisesRegex(TypeError, "DesignerComponentPaletteHost"):
            DesignerComponentPalette(workspace, object())
        with self.assertRaisesRegex(TypeError, "request handler"):
            DesignerComponentPalette(workspace, FakeComponentPaletteHost(), on_request=object())
        workspace.close()

    def test_component_key_filter_is_explicit_validated_and_ordered(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeComponentPaletteHost()
        palette = DesignerComponentPalette(
            workspace,
            host,
            component_keys=("control.button", "control.label"),
        )
        self.assertEqual(
            ("control.button", "control.label"),
            tuple(entry.component_type_key for entry in palette.state.entries),
        )
        with self.assertRaisesRegex(ValueError, "keys must be unique"):
            DesignerComponentPalette(
                workspace,
                host,
                component_keys=("control.button", "control.button"),
            )
        with self.assertRaises(KeyError):
            DesignerComponentPalette(workspace, host, component_keys=("missing.type",))
        workspace.close()

    def test_state_projects_catalog_entries_categories_and_target_hint(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("run")
        palette = DesignerComponentPalette(workspace, FakeComponentPaletteHost())
        state = palette.state
        self.assertEqual(len(FRAMEWORK_DESIGNER_CATALOG.specs), state.entry_count)
        self.assertEqual("run", state.target_hint)
        self.assertEqual(
            tuple(spec.key for spec in FRAMEWORK_DESIGNER_CATALOG.specs),
            tuple(entry.component_type_key for entry in state.entries),
        )
        self.assertIn("control", state.categories)
        self.assertIn("container", state.categories)
        self.assertIn("structure", state.categories)
        self.assertIn("field", state.categories)
        json.dumps(state.to_descriptor())
        workspace.close()

    def test_build_projects_expected_item_shape_and_title(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeComponentPaletteHost()
        palette = DesignerComponentPalette(
            workspace,
            host,
            component_keys=("control.label", "control.button"),
            title="Toolbox",
        )
        binding = palette.build(parent="left")
        self.assertTrue(palette.exists())
        self.assertEqual("left", binding.panel["parent"])
        self.assertEqual("Toolbox", binding.panel["title"])
        self.assertEqual(("control.label", "control.button"), tuple(binding.items))
        palette.dispose()
        workspace.close()

    def test_activation_returns_explicit_request_and_forwards_handler(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("run")
        seen = []
        host = FakeComponentPaletteHost()
        palette = DesignerComponentPalette(workspace, host, on_request=seen.append)
        palette.build(parent="palette")
        request = host.on_activate("control.button")
        self.assertIsInstance(request, DesignerComponentInsertRequest)
        self.assertEqual("control.button", request.component_type_key)
        self.assertEqual("Button", request.label)
        self.assertEqual("control", request.category)
        self.assertEqual("run", request.target_hint)
        self.assertTrue(request.requires_placement)
        self.assertEqual([request], seen)
        self.assertEqual(request.to_descriptor(), json.loads(json.dumps(request.to_descriptor())))
        palette.dispose()
        workspace.close()

    def test_activation_revalidates_against_current_selection(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("status")
        palette = DesignerComponentPalette(workspace, FakeComponentPaletteHost())
        palette.build(parent="palette")
        self.assertEqual("status", palette.activate("control.label").target_hint)
        workspace.select_and_focus_node("run")
        self.assertEqual("run", palette.activate("control.label").target_hint)
        palette.dispose()
        workspace.close()

    def test_activation_with_no_selection_keeps_empty_hint_instead_of_guessing(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        palette = DesignerComponentPalette(workspace, FakeComponentPaletteHost())
        request = palette.activate("control.button")
        self.assertEqual("", request.target_hint)
        self.assertTrue(request.requires_placement)
        workspace.close()

    def test_activation_is_document_history_and_preview_neutral(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("root")
        palette = DesignerComponentPalette(workspace, FakeComponentPaletteHost())
        before_state = workspace.state
        before_snapshot = workspace.session.snapshot
        before_undo = workspace.session.undo_depth
        request = palette.activate("control.label")
        after_state = workspace.state
        self.assertEqual("root", request.target_hint)
        self.assertIs(before_snapshot, workspace.session.snapshot)
        self.assertEqual(before_undo, workspace.session.undo_depth)
        self.assertEqual(before_state.is_dirty, after_state.is_dirty)
        self.assertEqual(before_state.preview_generation, after_state.preview_generation)
        workspace.close()

    def test_unknown_activation_is_rejected_without_request_callback(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        seen = []
        palette = DesignerComponentPalette(
            workspace,
            FakeComponentPaletteHost(),
            component_keys=("control.label",),
            on_request=seen.append,
        )
        with self.assertRaisesRegex(KeyError, "not exposed"):
            palette.activate("control.button")
        with self.assertRaises(ValueError):
            palette.activate("")
        self.assertEqual([], seen)
        workspace.close()

    def test_refresh_observes_workspace_closed_state_and_rebuilds_stale_binding(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeComponentPaletteHost()
        palette = DesignerComponentPalette(workspace, host, component_keys=("control.label",))
        first = palette.build(parent="palette")
        first.panel["alive"] = False
        second = palette.refresh()
        self.assertIsNot(first, second)
        self.assertEqual(2, len(host.built))
        workspace.close()
        palette.refresh()
        self.assertTrue(host.updated[-1].closed)
        palette.dispose()

    def test_host_binding_shape_is_validated(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeComponentPaletteHost(bad_shape=True)
        palette = DesignerComponentPalette(
            workspace,
            host,
            component_keys=("control.label",),
        )
        with self.assertRaisesRegex(ValueError, "unexpected shape"):
            palette.build(parent="palette")
        self.assertEqual(1, host.disposed)
        workspace.close()

    def test_closed_workspace_rejects_activation_but_palette_disposes(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeComponentPaletteHost()
        palette = DesignerComponentPalette(workspace, host)
        palette.build(parent="palette")
        workspace.close()
        with self.assertRaisesRegex(RuntimeError, "workspace is closed"):
            host.on_activate("control.label")
        self.assertTrue(palette.dispose())
        self.assertFalse(palette.dispose())

    def test_code_first_tree_remains_unchanged_by_palette_requests(self):
        source, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        palette = DesignerComponentPalette(workspace, FakeComponentPaletteHost())
        palette.activate("container.column")
        palette.activate("control.button")
        self.assertEqual("Status", source.children[0].text)
        self.assertEqual("Run", source.children[1].label)
        self.assertIsNone(source.children[0].item)
        self.assertIsNone(source.children[1].item)
        workspace.close()

    def test_surface_boundaries_keep_semantics_out_of_toolkits_and_product_layers(self):
        framework = PROJECT_ROOT / "app" / "framework" / "designer_component_palette.py"
        tree = ast.parse(framework.read_text(encoding="utf-8"), filename=str(framework))
        absolute_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                absolute_imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                absolute_imports.append(node.module)
        forbidden = ("dearpygui", "tkinter", "app.engine", "app.views", "app.logic")
        self.assertFalse(any(name.startswith(forbidden) for name in absolute_imports), absolute_imports)

        for relative in (
            "app/engine/designer_component_palette_hosts/dearpygui.py",
            "app/engine/designer_component_palette_hosts/tkinter.py",
        ):
            text = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("app.views", text)
            self.assertNotIn("app.logic", text)
            self.assertNotIn("TorrentManager", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
