"""Regressions for shared designer numeric scrubbing/direct-drag translation."""
from __future__ import annotations

import ast
import unittest

from tests.helpers import PROJECT_ROOT
from app.framework.designer import DesignerValueKind
from app.framework.designer_editing import DesignerPropertyState
from app.framework.designer_inspector import DesignerInspectorRow
from app.framework.designer_numeric_drag import (
    DesignerDragModifiers,
    is_scrubbable_row,
    translate_numeric_drag,
)


def _row(kind, *, value=10, minimum=None, maximum=None, editable=True):
    state = DesignerPropertyState(
        "node", "type", "value", "Value", kind,
        editable, True, False, True, True, value,
        minimum=minimum, maximum=maximum,
    )
    return DesignerInspectorRow.from_property_state(state)


class DesignerNumericDragTests(unittest.TestCase):
    def test_modifier_scales_are_normal_coarse_and_fine(self):
        self.assertEqual(1.0, DesignerDragModifiers().scale)
        self.assertEqual(10.0, DesignerDragModifiers(shift=True).scale)
        self.assertEqual(0.1, DesignerDragModifiers(ctrl=True).scale)

    def test_shift_wins_when_both_modifiers_are_pressed(self):
        self.assertEqual(10.0, DesignerDragModifiers(shift=True, ctrl=True).scale)

    def test_integer_drag_uses_total_delta_and_rounds_once(self):
        row = _row(DesignerValueKind.INTEGER)
        self.assertEqual(14, translate_numeric_drag(row, 10, 4))
        self.assertEqual(11, translate_numeric_drag(row, 10, 6, DesignerDragModifiers(ctrl=True)))

    def test_shift_integer_drag_is_coarse(self):
        row = _row(DesignerValueKind.INTEGER)
        self.assertEqual(50, translate_numeric_drag(row, 10, 4, DesignerDragModifiers(shift=True)))

    def test_number_drag_preserves_fractional_fine_values(self):
        row = _row(DesignerValueKind.NUMBER)
        self.assertAlmostEqual(10.3, translate_numeric_drag(row, 10.0, 3, DesignerDragModifiers(ctrl=True)))

    def test_dimension_drag_is_integer_scrubbable(self):
        row = _row(DesignerValueKind.DIMENSION)
        self.assertTrue(is_scrubbable_row(row))
        self.assertEqual(22, translate_numeric_drag(row, 20, 2))

    def test_minimum_clamps_translated_value(self):
        row = _row(DesignerValueKind.INTEGER, minimum=4)
        self.assertEqual(4, translate_numeric_drag(row, 10, -100))

    def test_maximum_clamps_translated_value(self):
        row = _row(DesignerValueKind.NUMBER, maximum=12.5)
        self.assertEqual(12.5, translate_numeric_drag(row, 10.0, 100))

    def test_text_rows_are_not_scrubbable(self):
        row = _row(DesignerValueKind.TEXT, value="x")
        self.assertFalse(is_scrubbable_row(row))
        with self.assertRaises(TypeError):
            translate_numeric_drag(row, 0, 1)

    def test_bad_numeric_inputs_are_rejected(self):
        row = _row(DesignerValueKind.INTEGER)
        with self.assertRaises(TypeError):
            translate_numeric_drag(row, True, 1)
        with self.assertRaises(TypeError):
            translate_numeric_drag(row, 1, False)

    def test_framework_helper_has_no_toolkit_or_product_imports(self):
        path = PROJECT_ROOT / "app" / "framework" / "designer_numeric_drag.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
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

    def test_concrete_hosts_share_modifier_translation_contract(self):
        dpg = (PROJECT_ROOT / "app" / "engine" / "designer_preview_resize_hosts" / "dearpygui.py").read_text(encoding="utf-8")
        tk = (PROJECT_ROOT / "app" / "engine" / "designer_preview_resize_hosts" / "tkinter.py").read_text(encoding="utf-8")
        inspector = (PROJECT_ROOT / "app" / "engine" / "designer_inspector_panel_hosts" / "dearpygui.py").read_text(encoding="utf-8")
        self.assertIn("DesignerDragModifiers", dpg)
        self.assertIn("DesignerDragModifiers", tk)
        self.assertIn("translate_numeric_drag", inspector)
        self.assertNotIn("ttk.Sizegrip(", tk)


if __name__ == "__main__":
    unittest.main(verbosity=2)
