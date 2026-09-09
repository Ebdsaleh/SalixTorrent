"""Regressions for explicit designer component placement resolution."""

from __future__ import annotations

import ast
import json
import unittest

from app.framework.components import Button, ControlColumn, ControlGrid, Label, TabContainer, TabPage
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_component_palette import DesignerComponentInsertRequest
from app.framework.designer_component_placement import (
    DesignerComponentPlacementBinding,
    DesignerComponentPlacementSurface,
)
from app.framework.designer_workspace import DesignerWorkspace
from tests.helpers import PROJECT_ROOT


class FakePlacementHost:
    def __init__(self):
        self.binding = None
        self.callbacks = {}
        self.built = []
        self.updated = []
        self.disposed = 0

    def build(self, state, *, parent, title, on_parent, on_slot, on_index, on_metadata, on_commit, on_cancel):
        self.callbacks = {
            "parent": on_parent,
            "slot": on_slot,
            "index": on_index,
            "metadata": on_metadata,
            "commit": on_commit,
            "cancel": on_cancel,
        }
        self.binding = DesignerComponentPlacementBinding(
            panel={"alive": True, "parent": parent, "title": title},
            fields={"state": state},
        )
        self.built.append(state)
        return self.binding

    def update(self, binding, state):
        binding.fields["state"] = state
        self.updated.append(state)

    def exists(self, binding):
        return bool(binding.panel["alive"])

    def dispose(self, binding):
        binding.panel["alive"] = False
        self.disposed += 1


class DesignerComponentPlacementTests(unittest.TestCase):
    def _fixture(self):
        label = Label("Status")
        button = Button("Run")
        root = ControlColumn((label, button))
        ids = DesignerIdentityMap(prefix="placement")
        ids.bind(root, "root")
        ids.bind(label, "status")
        ids.bind(button, "run")
        return root, capture_component_tree(root, identities=ids)

    @staticmethod
    def _request(type_key="control.label", label="Label", target="run"):
        return DesignerComponentInsertRequest(type_key, label, type_key.split(".", 1)[0], target)

    def test_requires_workspace_valid_host_and_callbacks(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        with self.assertRaisesRegex(TypeError, "requires DesignerWorkspace"):
            DesignerComponentPlacementSurface(object(), FakePlacementHost())
        with self.assertRaisesRegex(TypeError, "DesignerComponentPlacementHost"):
            DesignerComponentPlacementSurface(workspace, object())
        with self.assertRaisesRegex(TypeError, "change handler"):
            DesignerComponentPlacementSurface(workspace, FakePlacementHost(), on_change=object())
        with self.assertRaisesRegex(TypeError, "error handler"):
            DesignerComponentPlacementSurface(workspace, FakePlacementHost(), on_error=object())
        workspace.close()

    def test_build_starts_inert_and_projects_title(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakePlacementHost()
        surface = DesignerComponentPlacementSurface(workspace, host, title="Place component")
        binding = surface.build(parent="sidebar")
        self.assertEqual("sidebar", binding.panel["parent"])
        self.assertEqual("Place component", binding.panel["title"])
        self.assertFalse(surface.state.active)
        self.assertFalse(surface.state.can_commit)
        surface.dispose()
        workspace.close()

    def test_begin_leaf_hint_falls_back_to_current_parent_without_committing(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakePlacementHost()
        surface = DesignerComponentPlacementSurface(workspace, host)
        surface.build(parent="placement")
        before = workspace.session.snapshot
        state = surface.begin(self._request(target="run"))
        self.assertEqual("root", state.parent_id)
        self.assertEqual("children", state.slot_key)
        self.assertTrue(state.node_id.startswith("designer-label-"))
        self.assertTrue(state.can_commit)
        self.assertIs(before, workspace.session.snapshot)
        self.assertEqual(0, workspace.session.undo_depth)
        workspace.close()

    def test_begin_container_hint_prefers_selected_parent(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        surface = DesignerComponentPlacementSurface(workspace, FakePlacementHost())
        state = surface.begin(self._request(target="root"))
        self.assertEqual("root", state.parent_id)
        self.assertEqual("children", state.slot_key)
        workspace.close()

    def test_state_descriptor_is_json_safe_and_exposes_relationship_choices(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        surface = DesignerComponentPlacementSurface(workspace, FakePlacementHost())
        state = surface.begin(self._request())
        descriptor = state.to_descriptor()
        self.assertEqual(descriptor, json.loads(json.dumps(descriptor)))
        self.assertEqual("root", descriptor["parents"][0]["node_id"])
        self.assertEqual("children", descriptor["parents"][0]["slots"][0]["key"])
        workspace.close()

    def test_sparse_creation_rejects_types_that_require_child_templates(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        surface = DesignerComponentPlacementSurface(workspace, FakePlacementHost())
        state = surface.begin(self._request("structure.split", "Split panel", "root"))
        self.assertTrue(state.creation_error)
        self.assertFalse(state.can_commit)
        with self.assertRaisesRegex(ValueError, "cannot be created as a sparse node"):
            surface.commit()
        self.assertEqual(0, workspace.session.undo_depth)
        workspace.close()

    def test_commit_inserts_visible_default_through_checked_history_and_selects_new_node(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        surface = DesignerComponentPlacementSurface(workspace, FakePlacementHost())
        surface.begin(self._request("control.label", "Label", "run"))
        inserted_id = surface.commit()
        self.assertEqual(inserted_id, workspace.state.selected_id)
        self.assertEqual(inserted_id, workspace.state.focused_id)
        self.assertEqual(1, workspace.session.undo_depth)
        self.assertTrue(workspace.state.is_dirty)
        inserted = next(node for node in workspace.session.snapshot.root.walk() if node.node_id == inserted_id)
        self.assertEqual("Label", inserted.properties["text"])
        self.assertEqual("Label", workspace.preview_host.preview.component(inserted_id).text)
        self.assertFalse(surface.state.active)
        workspace.close()

    def test_explicit_index_controls_sibling_insertion_position(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        surface = DesignerComponentPlacementSurface(workspace, FakePlacementHost())
        surface.begin(self._request("control.button", "Button", "root"))
        surface.set_index_text("0")
        inserted_id = surface.commit()
        self.assertEqual(
            [inserted_id, "status", "run"],
            [child.node.node_id for child in workspace.session.snapshot.root.children],
        )
        workspace.close()

    def test_invalid_index_or_metadata_fails_before_document_mutation(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        errors = []
        surface = DesignerComponentPlacementSurface(workspace, FakePlacementHost(), on_error=errors.append)
        surface.begin(self._request(target="root"))
        before = workspace.session.snapshot
        surface.set_index_text("nope")
        with self.assertRaisesRegex(ValueError, "index must be an integer"):
            surface.commit()
        self.assertIs(before, workspace.session.snapshot)
        self.assertEqual([], errors)  # parsing failed before the checked structural call
        surface.set_index_text("")
        surface.set_metadata_text("[1,2]")
        with self.assertRaisesRegex(TypeError, "JSON must be an object"):
            surface.commit()
        self.assertIs(before, workspace.session.snapshot)
        workspace.close()

    def test_transactional_relationship_error_is_reported_without_history(self):
        grid = ControlGrid(())
        ids = DesignerIdentityMap(prefix="grid")
        ids.bind(grid, "grid")
        snapshot = capture_component_tree(grid, identities=ids)
        workspace = DesignerWorkspace.create(snapshot)
        errors = []
        surface = DesignerComponentPlacementSurface(workspace, FakePlacementHost(), on_error=errors.append)
        state = surface.begin(self._request("control.label", "Label", "grid"))
        self.assertEqual('{"column":0,"row":0}', state.metadata_text)
        surface.set_metadata_text("{}")
        before_generation = workspace.state.preview_generation
        with self.assertRaisesRegex(ValueError, "requires metadata"):
            surface.commit()
        self.assertEqual(0, workspace.session.undo_depth)
        self.assertEqual(before_generation, workspace.state.preview_generation)
        self.assertEqual(1, len(errors))
        workspace.close()

    def test_grid_metadata_suggestion_can_insert_first_cell(self):
        grid = ControlGrid(())
        ids = DesignerIdentityMap(prefix="grid")
        ids.bind(grid, "grid")
        workspace = DesignerWorkspace.create(capture_component_tree(grid, identities=ids))
        surface = DesignerComponentPlacementSurface(workspace, FakePlacementHost())
        state = surface.begin(self._request("control.button", "Button", "grid"))
        self.assertEqual("cell", state.slot_key)
        self.assertEqual({"column": 0, "row": 0}, json.loads(state.metadata_text))
        inserted_id = surface.commit()
        child = workspace.session.snapshot.root.children[0]
        self.assertEqual(inserted_id, child.node.node_id)
        self.assertEqual({"column": 0, "row": 0}, child.metadata)
        workspace.close()

    def test_tabs_only_expose_page_slot_for_tab_page_requests(self):
        tabs = TabContainer(())
        root = ControlColumn((tabs,))
        ids = DesignerIdentityMap(prefix="tabs")
        ids.bind(root, "root")
        ids.bind(tabs, "tabs")
        workspace = DesignerWorkspace.create(capture_component_tree(root, identities=ids))
        surface = DesignerComponentPlacementSurface(workspace, FakePlacementHost())
        label_state = surface.begin(self._request("control.label", "Label", "tabs"))
        self.assertNotIn("tabs", {parent.node_id for parent in label_state.parents})
        page_state = surface.begin(self._request("structure.tab_page", "Tab page", "tabs"))
        self.assertEqual("tabs", page_state.parent_id)
        self.assertEqual("page", page_state.slot_key)
        self.assertEqual(page_state.node_id, json.loads(page_state.metadata_text)["key"])
        inserted_id = surface.commit()
        page = workspace.session.snapshot.root.children[0].node.children[0]
        self.assertEqual(inserted_id, page.node.node_id)
        self.assertEqual(inserted_id, page.node.properties["key"])
        workspace.close()

    def test_parent_and_slot_changes_are_explicit_and_revalidated(self):
        nested = ControlColumn(())
        root = ControlColumn((nested,))
        ids = DesignerIdentityMap(prefix="parent")
        ids.bind(root, "root")
        ids.bind(nested, "nested")
        workspace = DesignerWorkspace.create(capture_component_tree(root, identities=ids))
        surface = DesignerComponentPlacementSurface(workspace, FakePlacementHost())
        surface.begin(self._request(target="root"))
        state = surface.choose_parent("nested")
        self.assertEqual("nested", state.parent_id)
        self.assertEqual("children", state.slot_key)
        with self.assertRaisesRegex(KeyError, "parent is not available"):
            surface.choose_parent("missing")
        with self.assertRaisesRegex(KeyError, "slot is not available"):
            surface.choose_slot("missing")
        workspace.close()

    def test_cancel_is_ephemeral_and_keeps_document_history_neutral(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        surface = DesignerComponentPlacementSurface(workspace, FakePlacementHost())
        before = workspace.session.snapshot
        surface.begin(self._request())
        surface.set_index_text("1")
        surface.cancel()
        self.assertFalse(surface.state.active)
        self.assertIs(before, workspace.session.snapshot)
        self.assertEqual(0, workspace.session.undo_depth)
        workspace.close()

    def test_refresh_rebuilds_stale_host_and_closed_workspace_rejects_begin(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakePlacementHost()
        surface = DesignerComponentPlacementSurface(workspace, host)
        first = surface.build(parent="placement")
        first.panel["alive"] = False
        second = surface.refresh()
        self.assertIsNot(first, second)
        workspace.close()
        with self.assertRaisesRegex(RuntimeError, "workspace is closed"):
            surface.begin(self._request())
        surface.dispose()
        self.assertEqual(1, host.disposed)

    def test_surface_boundaries_keep_semantics_out_of_toolkits_and_product_layers(self):
        framework = PROJECT_ROOT / "app" / "framework" / "designer_component_placement.py"
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
            "app/engine/designer_component_placement_hosts/dearpygui.py",
            "app/engine/designer_component_placement_hosts/tkinter.py",
        ):
            text = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("app.views", text)
            self.assertNotIn("app.logic", text)
            self.assertNotIn("TorrentManager", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
