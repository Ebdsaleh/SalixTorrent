"""Post-v0.5.1 Tranche 11 layout-autonomy regressions."""

from __future__ import annotations

import ast
import unittest

from tests.helpers import PROJECT_ROOT
from tests.presentation.test_gui_components import RecordingRenderer

from app.framework.components import (
    Button,
    ControlColumn,
    ControlLayout,
    ControlRow,
    CrossAxisMode,
    NATURAL,
    STRETCH,
    cross_axis_mode,
)
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_editing import DesignerEditSession
from app.framework.designer_preview import reconstruct_designer_snapshot


class DesignerLayoutAutonomyTests(unittest.TestCase):
    def test_cross_axis_modes_are_explicit_and_validated(self):
        self.assertIs(CrossAxisMode.NATURAL, NATURAL)
        self.assertIs(CrossAxisMode.STRETCH, STRETCH)
        self.assertIs(NATURAL, cross_axis_mode("natural"))
        self.assertIs(STRETCH, cross_axis_mode(" STRETCH "))
        with self.assertRaisesRegex(ValueError, "natural.*stretch"):
            cross_axis_mode("mystery")

    def test_linear_containers_default_to_natural_child_geometry(self):
        row = ControlRow((Button("A"),))
        column = ControlColumn((Button("B"),))
        self.assertIs(NATURAL, row.cross_axis)
        self.assertIs(NATURAL, column.cross_axis)

        renderer = RecordingRenderer()
        row.build(renderer=renderer)
        column.build(renderer=renderer)
        self.assertEqual("natural", renderer.containers[0][2]["cross_axis"])
        self.assertEqual("natural", renderer.containers[1][2]["cross_axis"])

    def test_stretch_is_opt_in_and_renderer_neutral(self):
        renderer = RecordingRenderer()
        ControlColumn((Button("A"),), cross_axis=STRETCH).build(renderer=renderer)
        self.assertEqual("stretch", renderer.containers[0][2]["cross_axis"])

    def test_code_first_snapshot_captures_cross_axis_policy(self):
        root = ControlColumn((Button("Run"),), cross_axis=STRETCH)
        ids = DesignerIdentityMap(prefix="layout")
        ids.bind(root, "root")
        snapshot = capture_component_tree(root, identities=ids)
        self.assertEqual("stretch", snapshot.root.properties["cross_axis"])
        type_descriptor = next(item for item in snapshot.types if item["key"] == "container.column")
        prop = next(item for item in type_descriptor["properties"] if item["key"] == "cross_axis")
        self.assertEqual(["natural", "stretch"], prop["choices"])

    def test_preview_reconstructs_cross_axis_without_backend_state(self):
        root = ControlColumn((Button("Run"),), cross_axis=STRETCH)
        snapshot = capture_component_tree(root)
        preview = reconstruct_designer_snapshot(snapshot)
        self.assertIs(STRETCH, preview.root.cross_axis)
        self.assertEqual(snapshot.to_descriptor(), preview.recapture().to_descriptor())

    def test_missing_snapshot_cross_axis_defaults_to_natural_for_compatibility(self):
        snapshot = capture_component_tree(ControlColumn((Button("Run"),), cross_axis=NATURAL))
        descriptor = snapshot.to_descriptor()
        descriptor["root"]["properties"].pop("cross_axis", None)
        from app.framework.designer import DesignerSnapshot

        restored = DesignerSnapshot.from_descriptor(descriptor)
        preview = reconstruct_designer_snapshot(restored)
        self.assertIs(NATURAL, preview.root.cross_axis)

    def test_designer_edit_can_switch_column_between_natural_and_stretch(self):
        root = ControlColumn((Button("Run"),), cross_axis=NATURAL)
        ids = DesignerIdentityMap(prefix="layout")
        ids.bind(root, "root")
        session = DesignerEditSession(capture_component_tree(root, identities=ids))
        self.assertTrue(session.set_property("root", "cross_axis", "stretch"))
        self.assertEqual("stretch", session.node("root").properties["cross_axis"])
        self.assertTrue(session.undo())
        self.assertEqual("natural", session.node("root").properties["cross_axis"])

    def test_row_and_column_share_same_policy_vocabulary(self):
        snapshot = capture_component_tree(
            ControlColumn((ControlRow((Button("Run"),), cross_axis=STRETCH),))
        )
        row = next(node for node in snapshot.root.walk() if node.type_key == "container.row")
        column = snapshot.root
        self.assertEqual("stretch", row.properties["cross_axis"])
        self.assertEqual("natural", column.properties["cross_axis"])

    def test_framework_layout_policy_has_no_toolkit_or_product_imports(self):
        paths = (
            PROJECT_ROOT / "app" / "framework" / "components" / "layout.py",
            PROJECT_ROOT / "app" / "framework" / "components" / "containers.py",
        )
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            self.assertFalse(
                any(name.startswith(("dearpygui", "tkinter", "app.engine", "app.views")) for name in imports),
                str(path),
            )

    def test_backend_adapters_translate_explicit_cross_axis_without_owning_policy(self):
        dpg_source = (PROJECT_ROOT / "app" / "engine" / "component_renderers" / "dearpygui.py").read_text(encoding="utf-8")
        tk_source = (PROJECT_ROOT / "app" / "engine" / "component_renderers" / "tkinter.py").read_text(encoding="utf-8")
        self.assertIn("_apply_parent_cross_axis", dpg_source)
        self.assertIn('mode != "stretch"', dpg_source)
        self.assertIn('state.cross_axis == "stretch"', tk_source)
        self.assertNotIn("Designer", dpg_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
