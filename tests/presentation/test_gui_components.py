from __future__ import annotations

from contextlib import contextmanager
import unittest

from tests.helpers import PROJECT_ROOT

from app.engine.components import (
    AUTO,
    FILL,
    ComboBox,
    ControlGrid,
    ControlLayout,
    ControlLayoutTheme,
    ControlRow,
    DurationEditor,
    Label,
    LabeledNumericField,
    NumericKind,
    NumericStepper,
    resolve_control_layout,
)
from app.engine.components.layout import backend_dimension
from app.engine.property_cascade import PropertySource


class RecordingRenderer:
    def __init__(self):
        self.created = []
        self.containers = []
        self.values = {}
        self.configured = {}

    def _new_item(self, prefix: str) -> str:
        return f"{prefix}:{len(self.created) + len(self.containers) + 1}"

    def create(self, kind: str, **kwargs):
        item = self._new_item(kind)
        self.created.append((kind, item, dict(kwargs)))
        if "default_value" in kwargs:
            self.values[item] = kwargs["default_value"]
        elif kind == "label":
            self.values[item] = kwargs.get("text", "")
        return item

    @contextmanager
    def container(self, kind: str, **kwargs):
        item = self._new_item(kind)
        self.containers.append((kind, item, dict(kwargs)))
        yield item

    def get_value(self, item):
        return self.values.get(item)

    def set_value(self, item, value):
        self.values[item] = value

    def configure(self, item, **kwargs):
        self.configured.setdefault(item, {}).update(kwargs)

    def exists(self, item):
        return item in self.values or any(entry[1] == item for entry in self.containers)


class GuiComponentFoundationTests(unittest.TestCase):
    def test_component_model_keeps_dearpygui_imports_behind_renderer_bridge(self):
        import ast

        component_dir = PROJECT_ROOT / "app" / "engine" / "components"
        model_files = (
            "__init__.py",
            "base.py",
            "containers.py",
            "controls.py",
            "fields.py",
            "layout.py",
        )
        for name in model_files:
            tree = ast.parse(
                (component_dir / name).read_text(encoding="utf-8"),
                filename=name,
            )
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            self.assertFalse(
                any(module.startswith("dearpygui") for module in imports),
                name,
            )

        renderer_source = (component_dir / "renderer.py").read_text(encoding="utf-8")
        self.assertIn("import dearpygui.dearpygui as dpg", renderer_source)

    def test_component_layout_uses_default_theme_instance_precedence(self):
        resolved = resolve_control_layout(
            theme=ControlLayoutTheme(width=320, height=28, spacing=6),
            override=ControlLayout(width=480),
        )
        self.assertEqual(resolved.width, 480)
        self.assertEqual(resolved.height, 28)
        self.assertEqual(resolved.spacing, 6)
        self.assertEqual(resolved.source_for("width"), PropertySource.INSTANCE)
        self.assertEqual(resolved.source_for("height"), PropertySource.THEME)
        self.assertEqual(resolved.source_for("spacing"), PropertySource.THEME)

    def test_invalid_instance_dimension_falls_back_without_affecting_other_fields(self):
        resolved = resolve_control_layout(
            theme=ControlLayoutTheme(width=360, height=32),
            override=ControlLayout(width=-1, height=44),
        )
        self.assertEqual(resolved.width, 360)
        self.assertEqual(resolved.height, 44)
        self.assertEqual(resolved.source_for("width"), PropertySource.THEME)
        self.assertEqual(resolved.source_for("height"), PropertySource.INSTANCE)
        self.assertEqual(resolved.rejected[0][0], "width")
        self.assertEqual(resolved.rejected[0][1].source, PropertySource.INSTANCE)

    def test_semantic_auto_and_fill_do_not_leak_backend_magic_numbers(self):
        self.assertIsNone(backend_dimension(AUTO))
        self.assertEqual(backend_dimension(FILL), -1)
        self.assertEqual(backend_dimension(240), 240)

    def test_control_row_accepts_arbitrary_children_and_resolves_size(self):
        renderer = RecordingRenderer()
        row = ControlRow(
            (
                Label("Goal mode"),
                ComboBox(("A", "B"), default_value="A", layout=ControlLayout(width=220)),
                Label("Ratio"),
                NumericStepper(
                    kind=NumericKind.FLOAT,
                    default_value=1.0,
                    min_value=0.1,
                    max_value=10.0,
                    min_clamped=True,
                    max_clamped=True,
                    layout=ControlLayout(width=120),
                ),
            ),
            theme=ControlLayoutTheme(width=500, height=30, spacing=7),
            layout=ControlLayout(width=620),
        )

        row.build(renderer=renderer)

        self.assertEqual(len(row.children), 4)
        self.assertEqual(row.resolved_layout.width, 620)
        self.assertEqual(row.resolved_layout.height, 30)
        self.assertEqual(row.resolved_layout.spacing, 7)
        kind, _, kwargs = renderer.containers[0]
        self.assertEqual(kind, "row")
        self.assertEqual(kwargs["width"], 620)
        self.assertEqual(kwargs["height"], 30)
        self.assertEqual(kwargs["horizontal_spacing"], 7)

    def test_numeric_stepper_dispatches_integer_and_float_backends(self):
        renderer = RecordingRenderer()
        integer = NumericStepper(
            kind=NumericKind.INTEGER,
            default_value=4,
            min_value=0,
            max_value=12,
            min_clamped=True,
            max_clamped=True,
        )
        floating = NumericStepper(
            kind=NumericKind.FLOAT,
            default_value=1.5,
            min_value=0.1,
            max_value=5.0,
            min_clamped=True,
            max_clamped=True,
            format="%.2f",
        )

        integer.build(renderer=renderer)
        floating.build(renderer=renderer)

        self.assertEqual(renderer.created[0][0], "numeric_int")
        self.assertEqual(renderer.created[1][0], "numeric_float")
        self.assertTrue(renderer.created[0][2]["min_clamped"])
        self.assertEqual(renderer.created[1][2]["format"], "%.2f")

    def test_value_components_expose_backend_neutral_get_set_and_configure(self):
        renderer = RecordingRenderer()
        field = LabeledNumericField(
            "Ratio target",
            kind=NumericKind.FLOAT,
            default_value=1.0,
            min_value=0.1,
            max_value=1000.0,
            min_clamped=True,
            max_clamped=True,
            control_width=120,
        )
        field.build(renderer=renderer)

        self.assertEqual(field.control.get_value(), 1.0)
        field.control.set_value(2.5)
        self.assertEqual(field.control.get_value(), 2.5)
        field.control.configure(enabled=False)
        self.assertFalse(renderer.configured[field.control.require_item()]["enabled"])

    def test_control_grid_rejects_ragged_rows_and_bad_column_contracts(self):
        with self.assertRaises(ValueError):
            ControlGrid(((Label("A"), Label("B")), (Label("C"),)))
        with self.assertRaises(ValueError):
            ControlGrid(((Label("A"), Label("B")),), column_widths=(100,))

    def test_duration_editor_is_three_validated_numeric_controls_in_one_grid(self):
        renderer = RecordingRenderer()
        editor = DurationEditor(
            heading="Time target",
            day_label="Days",
            hour_label="Hours",
            minute_label="Minutes",
            days=2,
            hours=5,
            minutes=10,
            input_width=130,
            grid_width=280,
            label_column_width=90,
            control_column_width=170,
        )

        editor.build(renderer=renderer)

        self.assertEqual(editor.days.get_value(), 2)
        self.assertEqual(editor.hours.get_value(), 5)
        self.assertEqual(editor.minutes.get_value(), 10)
        self.assertEqual(len(editor.value_items()), 3)
        grid_calls = [entry for entry in renderer.containers if entry[0] == "grid"]
        row_calls = [entry for entry in renderer.containers if entry[0] == "grid_row"]
        self.assertEqual(len(grid_calls), 1)
        self.assertEqual(len(row_calls), 3)
        self.assertEqual(grid_calls[0][2]["width"], 280)


if __name__ == "__main__":
    unittest.main()
