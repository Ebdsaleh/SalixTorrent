"""Post-v0.5.1 Tranche 11 hierarchy drag/reparent regressions."""

from __future__ import annotations

import ast
import unittest

from tests.helpers import PROJECT_ROOT

from app.framework.components import Button, ControlColumn, ControlGrid, Label
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_hierarchy_drag import (
    DesignerHierarchyReparentPlan,
    plan_hierarchy_reparent,
)
from app.framework.designer_hierarchy_panel import (
    DesignerHierarchyPanel,
    DesignerHierarchyPanelBinding,
)
from app.framework.designer_workspace import DesignerWorkspace
from app.framework.designer_structure import locate_designer_node


class _DragHost:
    def __init__(self):
        self.binding = None
        self.on_reparent = None
        self.on_select = None
        self.on_toggle = None

    def build(self, rows, *, parent, title="", on_select, on_toggle, on_reparent):
        self.on_select = on_select
        self.on_toggle = on_toggle
        self.on_reparent = on_reparent
        self.binding = DesignerHierarchyPanelBinding(
            panel={"alive": True, "parent": parent},
            rows={row.node_id: object() for row in rows},
        )
        return self.binding

    def update(self, binding, rows):
        binding.rows.clear()
        binding.rows.update({row.node_id: object() for row in rows})

    def exists(self, binding):
        return bool(binding.panel["alive"])

    def dispose(self, binding):
        binding.panel["alive"] = False


class DesignerHierarchyDragTests(unittest.TestCase):
    def _fixture(self):
        move = Button("Move")
        stay = Button("Stay")
        left = ControlColumn((move,))
        right = ControlColumn((stay,))
        root = ControlColumn((Label("Title"), left, right))
        ids = DesignerIdentityMap(prefix="drag")
        for component, node_id in (
            (root, "root"),
            (left, "left"),
            (right, "right"),
            (move, "move"),
            (stay, "stay"),
        ):
            ids.bind(component, node_id)
        return root, capture_component_tree(root, identities=ids)

    def test_plan_reparents_into_one_simple_metadata_free_slot(self):
        _, snapshot = self._fixture()
        plan = plan_hierarchy_reparent(snapshot, "move", "right")
        self.assertEqual(
            DesignerHierarchyReparentPlan("move", "right", "children", 1),
            plan,
        )

    def test_plan_rejects_root_self_and_subtree_cycles(self):
        _, snapshot = self._fixture()
        with self.assertRaisesRegex(ValueError, "root cannot"):
            plan_hierarchy_reparent(snapshot, "root", "right")
        with self.assertRaisesRegex(ValueError, "onto itself"):
            plan_hierarchy_reparent(snapshot, "left", "left")
        with self.assertRaisesRegex(ValueError, "own subtree"):
            plan_hierarchy_reparent(snapshot, "left", "move")

    def test_plan_rejects_leaf_drop_target(self):
        _, snapshot = self._fixture()
        with self.assertRaisesRegex(ValueError, "does not accept children"):
            plan_hierarchy_reparent(snapshot, "move", "stay")

    def test_plan_rejects_relationships_that_need_explicit_metadata(self):
        grid = ControlGrid(((Button("Cell"),),))
        root = ControlColumn((Button("Move"), grid))
        ids = DesignerIdentityMap(prefix="drag")
        ids.bind(root, "root")
        ids.bind(root.children[0], "move")
        ids.bind(grid, "grid")
        snapshot = capture_component_tree(root, identities=ids)
        with self.assertRaisesRegex(ValueError, "explicit relationship metadata"):
            plan_hierarchy_reparent(snapshot, "move", "grid")

    def test_same_parent_drop_plans_append_reorder(self):
        a, b, c = Button("A"), Button("B"), Button("C")
        root = ControlColumn((a, b, c))
        ids = DesignerIdentityMap(prefix="drag")
        ids.bind(root, "root")
        ids.bind(a, "a")
        ids.bind(b, "b")
        ids.bind(c, "c")
        snapshot = capture_component_tree(root, identities=ids)
        plan = plan_hierarchy_reparent(snapshot, "b", "root")
        self.assertEqual(2, plan.index)

    def test_plan_descriptor_is_json_safe_and_stable(self):
        _, snapshot = self._fixture()
        descriptor = plan_hierarchy_reparent(snapshot, "move", "right").to_descriptor()
        self.assertEqual(
            {"node_id": "move", "parent_id": "right", "slot": "children", "index": 1},
            descriptor,
        )

    def test_panel_drop_executes_one_checked_reparent_and_preserves_selection(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = _DragHost()
        changes = []
        panel = DesignerHierarchyPanel(workspace, host, on_change=lambda: changes.append(True))
        panel.build(parent="hierarchy")
        generation = workspace.state.preview_generation

        self.assertTrue(host.on_reparent("move", "right"))
        self.assertGreater(workspace.state.preview_generation, generation)
        self.assertEqual("move", workspace.state.selected_id)
        self.assertEqual("move", workspace.state.focused_id)
        location = locate_designer_node(workspace.session.snapshot, "move")
        self.assertEqual("right", location.parent_id)
        self.assertEqual(1, location.index)
        self.assertTrue(changes)

        self.assertTrue(workspace.undo())
        self.assertEqual("left", locate_designer_node(workspace.session.snapshot, "move").parent_id)
        panel.dispose()
        workspace.close()

    def test_panel_drop_error_is_reported_without_document_or_history_mutation(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = _DragHost()
        errors = []
        panel = DesignerHierarchyPanel(workspace, host, on_error=errors.append)
        panel.build(parent="hierarchy")
        before = workspace.session.snapshot.to_descriptor()
        self.assertFalse(host.on_reparent("move", "stay"))
        self.assertEqual(before, workspace.session.snapshot.to_descriptor())
        self.assertFalse(workspace.state.can_undo)
        self.assertIsInstance(errors[-1], ValueError)
        panel.dispose()
        workspace.close()

    def test_workspace_reparent_helper_uses_existing_structural_transaction(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        self.assertTrue(
            workspace.reparent_node(
                "move",
                "right",
                index=1,
                slot="children",
                metadata=None,
                preserve_metadata=False,
            )
        )
        self.assertEqual("right", locate_designer_node(workspace.session.snapshot, "move").parent_id)
        self.assertTrue(workspace.undo())
        workspace.close()

    def test_drag_edit_never_mutates_original_code_first_tree(self):
        source, snapshot = self._fixture()
        left = source.children[1]
        right = source.children[2]
        workspace = DesignerWorkspace.create(snapshot)
        host = _DragHost()
        panel = DesignerHierarchyPanel(workspace, host)
        panel.build(parent="hierarchy")
        self.assertTrue(panel.reparent("move", "right"))
        self.assertEqual(["Move"], [child.label for child in left.children])
        self.assertEqual(["Stay"], [child.label for child in right.children])
        panel.dispose()
        workspace.close()

    def test_framework_drag_planning_and_panel_have_no_toolkit_or_product_imports(self):
        for relative in (
            "app/framework/designer_hierarchy_drag.py",
            "app/framework/designer_hierarchy_panel.py",
        ):
            path = PROJECT_ROOT / relative
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            self.assertFalse(
                any(name.startswith(("dearpygui", "tkinter", "app.engine", "app.views")) for name in imports),
                relative,
            )

    def test_concrete_hosts_only_forward_stable_drag_ids(self):
        dpg = (PROJECT_ROOT / "app" / "engine" / "designer_hierarchy_panel_hosts" / "dearpygui.py").read_text(encoding="utf-8")
        tk = (PROJECT_ROOT / "app" / "engine" / "designer_hierarchy_panel_hosts" / "tkinter.py").read_text(encoding="utf-8")
        self.assertIn("drag_payload", dpg)
        self.assertIn("on_reparent(", dpg)
        self.assertIn("source_id, target_id", dpg)
        self.assertIn('tree.bind("<B1-Motion>"', tk)
        self.assertIn("on_reparent(source, target)", tk)
        self.assertNotIn("ReparentDesignerNode", dpg)
        self.assertNotIn("ReparentDesignerNode", tk)

    def test_root_has_no_dpg_drag_payload_but_remains_valid_drop_target_by_contract(self):
        source = (PROJECT_ROOT / "app" / "engine" / "designer_hierarchy_panel_hosts" / "dearpygui.py").read_text(encoding="utf-8")
        self.assertIn("if row.parent_id is not None", source)
        _, snapshot = self._fixture()
        plan = plan_hierarchy_reparent(snapshot, "move", "root")
        self.assertEqual("root", plan.parent_id)
        self.assertEqual("children", plan.slot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
