from __future__ import annotations

from contextlib import contextmanager
import unittest

from tests.helpers import PROJECT_ROOT

from app.engine.components import (
    AUTO,
    BindingSet,
    FILL,
    FRAMEWORK_COMPONENT_PROFILE,
    Button,
    CheckBox,
    ComponentGroup,
    ComponentLayoutProfile,
    ComboBox,
    ControlColumn,
    ControlGrid,
    ControlLayout,
    ControlLayoutDefaults,
    ControlLayoutTheme,
    ControlRow,
    Dialog,
    DurationEditor,
    Label,
    LabeledComboField,
    LabeledField,
    LabeledNumericField,
    NumericKind,
    NumericStepper,
    NumericUnitField,
    ProgressBar,
    SectionPanel,
    Separator,
    TextInput,
    Tooltip,
    ValueBinding,
    resolve_control_layout,
)
from app.engine.components.layout import backend_dimension
from app.engine.property_cascade import PropertySource


class RecordingRenderer:
    def __init__(self, component_profile=None):
        self.component_profile = component_profile or FRAMEWORK_COMPONENT_PROFILE
        self.created = []
        self.containers = []
        self.values = {}
        self.configured = {}
        self.tooltips = []
        self.centered = []

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
        return (
            any(entry[1] == item for entry in self.created)
            or any(entry[1] == item for entry in self.containers)
        )

    def center(self, item, *, fallback_size=None):
        self.centered.append((item, fallback_size))

    def attach_tooltip(self, item, text, *, wrap=450):
        record = (item, str(text), int(wrap))
        self.tooltips.append(record)
        return record


class GuiComponentFoundationTests(unittest.TestCase):
    def test_component_model_keeps_dearpygui_imports_behind_renderer_bridge(self):
        import ast

        component_dir = PROJECT_ROOT / "app" / "engine" / "components"
        model_files = (
            "__init__.py",
            "attachments.py",
            "base.py",
            "bindings.py",
            "containers.py",
            "controls.py",
            "fields.py",
            "layout.py",
            "profile.py",
            "state.py",
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

    def test_labeled_field_supports_multiple_trailing_accessories(self):
        renderer = RecordingRenderer()
        field = LabeledField(
            "Network interface / VPN",
            ComboBox(("Any interface", "Ethernet"), default_value="Any interface"),
            accessories=(
                Button("Refresh Interfaces"),
                Label("Ready"),
            ),
        )

        field.build(renderer=renderer)

        self.assertEqual(len(field.row.children), 4)
        self.assertIs(field.row.children[0], field.label)
        self.assertIs(field.row.children[1], field.control)
        self.assertEqual(len(field.accessory_items()), 2)
        self.assertEqual(renderer.created[0][0], "label")
        self.assertEqual(renderer.created[1][0], "combo_box")
        self.assertEqual(renderer.created[2][0], "button")
        self.assertEqual(renderer.created[3][0], "label")

    def test_numeric_unit_field_keeps_value_and_unit_controls_independent(self):
        renderer = RecordingRenderer()
        field = NumericUnitField(
            "Download",
            ("KB/s", "MB/s"),
            default_value=2.5,
            default_unit="MB/s",
            min_value=0.0,
            min_clamped=True,
            format="%.2f",
            value_width=110,
            unit_width=90,
        )

        field.build(renderer=renderer)
        value_item, unit_item = field.value_items()

        self.assertEqual(field.value_control.get_value(), 2.5)
        self.assertEqual(field.unit_control.get_value(), "MB/s")
        self.assertEqual(value_item, field.control.require_item())
        self.assertEqual(unit_item, field.accessories[0].require_item())
        field.unit_control.set_value("KB/s")
        self.assertEqual(field.unit_control.get_value(), "KB/s")

    def test_text_input_dispatches_through_renderer_and_keeps_layout_semantic(self):
        renderer = RecordingRenderer()
        control = TextInput(
            default_value="C:/Downloads",
            hint="Folder",
            layout=ControlLayout(width=700),
        )

        control.build(renderer=renderer)

        kind, _, kwargs = renderer.created[0]
        self.assertEqual(kind, "text_input")
        self.assertEqual(kwargs["default_value"], "C:/Downloads")
        self.assertEqual(kwargs["hint"], "Folder")
        self.assertEqual(kwargs["width"], 700)
        self.assertEqual(control.get_value(), "C:/Downloads")

    def test_specialized_labeled_fields_share_generic_composition_contract(self):
        combo = LabeledComboField("Mode", ("A", "B"), default_value="A")
        numeric = LabeledNumericField("Ratio", default_value=1)

        self.assertIsInstance(combo, LabeledField)
        self.assertIsInstance(numeric, LabeledField)
        self.assertEqual(combo.accessories, [])
        self.assertEqual(numeric.accessories, [])

    def test_preferences_value_controls_are_component_owned(self):
        source = (PROJECT_ROOT / "app" / "views" / "settings_view.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("LabeledField(", source)
        self.assertIn("NumericUnitField(", source)
        self.assertIn("TextInput(", source)
        self.assertIn("ControlRow(", source)
        self.assertNotIn("dpg.add_input_", source)
        self.assertNotIn("dpg.add_combo(", source)
        self.assertNotIn("dpg.add_checkbox(", source)


    def test_named_profile_supplies_component_defaults_without_instance_widths(self):
        profile = ComponentLayoutProfile(
            name="test-profile",
            parent=FRAMEWORK_COMPONENT_PROFILE,
            layouts={
                "demo.combo": ControlLayoutDefaults(width=321, height=28),
            },
        )
        renderer = RecordingRenderer(profile)
        control = ComboBox(("A", "B"), default_value="A", profile_key="demo.combo")

        control.build(renderer=renderer)

        self.assertEqual(control.resolved_layout.width, 321)
        self.assertEqual(control.resolved_layout.height, 28)
        self.assertEqual(control.resolved_layout.source_for("width"), PropertySource.DEFAULT)
        self.assertEqual(renderer.created[0][2]["width"], 321)
        self.assertEqual(renderer.created[0][2]["height"], 28)

    def test_theme_and_instance_still_override_profile_defaults_independently(self):
        profile = ComponentLayoutProfile(
            name="test-profile",
            parent=FRAMEWORK_COMPONENT_PROFILE,
            layouts={
                "demo.numeric": ControlLayoutDefaults(width=140, height=24),
            },
        )
        renderer = RecordingRenderer(profile)
        control = NumericStepper(
            kind=NumericKind.INTEGER,
            profile_key="demo.numeric",
            theme=ControlLayoutTheme(width=180, height=30),
            layout=ControlLayout(width=220),
        )

        control.build(renderer=renderer)

        self.assertEqual(control.resolved_layout.width, 220)
        self.assertEqual(control.resolved_layout.height, 30)
        self.assertEqual(control.resolved_layout.source_for("width"), PropertySource.INSTANCE)
        self.assertEqual(control.resolved_layout.source_for("height"), PropertySource.THEME)

    def test_unknown_profile_slot_falls_back_to_safe_framework_auto(self):
        renderer = RecordingRenderer(
            ComponentLayoutProfile(name="empty", parent=FRAMEWORK_COMPONENT_PROFILE)
        )
        control = ComboBox(("A",), default_value="A", profile_key="missing.slot")

        control.build(renderer=renderer)

        self.assertIs(control.resolved_layout.width, AUTO)
        self.assertNotIn("width", renderer.created[0][2])

    def test_numeric_unit_field_consumes_profile_owned_value_and_unit_widths(self):
        profile = ComponentLayoutProfile(
            name="wide-bandwidth",
            parent=FRAMEWORK_COMPONENT_PROFILE,
            layouts={
                "numeric_unit.value": ControlLayoutDefaults(width=140),
                "numeric_unit.unit": ControlLayoutDefaults(width=100),
            },
        )
        renderer = RecordingRenderer(profile)
        field = NumericUnitField(
            "Download",
            ("KB/s", "MB/s"),
            default_value=1.0,
            default_unit="MB/s",
        )

        field.build(renderer=renderer)

        numeric = next(entry for entry in renderer.created if entry[0] == "numeric_float")
        unit = next(entry for entry in renderer.created if entry[0] == "combo_box")
        self.assertEqual(numeric[2]["width"], 140)
        self.assertEqual(unit[2]["width"], 100)

    def test_duration_editor_consumes_profile_grid_input_and_column_metrics(self):
        profile = ComponentLayoutProfile(
            name="wide-duration",
            parent=FRAMEWORK_COMPONENT_PROFILE,
            layouts={
                "duration_editor.input": ControlLayoutDefaults(width=132),
                "duration_editor.grid": ControlLayoutDefaults(width=300),
            },
            columns={
                "duration_editor.columns": (95, 180),
            },
        )
        renderer = RecordingRenderer(profile)
        editor = DurationEditor(
            heading="Time target",
            day_label="Days",
            hour_label="Hours",
            minute_label="Minutes",
            days=1,
            hours=2,
            minutes=3,
        )

        editor.build(renderer=renderer)

        numeric_calls = [entry for entry in renderer.created if entry[0] == "numeric_int"]
        self.assertEqual([entry[2]["width"] for entry in numeric_calls], [132, 132, 132])
        grid_call = next(entry for entry in renderer.containers if entry[0] == "grid")
        self.assertEqual(grid_call[2]["width"], 300)
        columns = [entry for entry in renderer.created if entry[0] == "grid_column"]
        self.assertEqual(
            [entry[2]["init_width_or_weight"] for entry in columns],
            [95, 180],
        )

    def test_salix_view_component_dimensions_are_profile_owned(self):
        settings_source = (PROJECT_ROOT / "app" / "views" / "settings_view.py").read_text(
            encoding="utf-8"
        )
        download_source = (PROJECT_ROOT / "app" / "views" / "download_view.py").read_text(
            encoding="utf-8"
        )
        profile_source = (PROJECT_ROOT / "app" / "engine" / "ui_component_profile.py").read_text(
            encoding="utf-8"
        )

        forbidden = (
            "ControlLayout(width=",
            "control_width=",
            "value_width=",
            "unit_width=",
            "input_width=",
            "grid_width=",
            "label_column_width=",
            "control_column_width=",
        )
        for source in (settings_source, download_source):
            for token in forbidden:
                self.assertNotIn(token, source)

        self.assertIn('profile_key="settings.download_path"', settings_source)
        self.assertIn('control_profile_key="settings.protocol"', settings_source)
        self.assertIn('profile_key="torrent_properties.seeding_ratio"', download_source)
        self.assertIn('"settings.download_path": ControlLayoutDefaults(width=700)', profile_source)
        self.assertIn('"configure_targets.duration.columns": (90, 170)', profile_source)

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


    def test_component_attachment_runs_after_item_binding(self):
        renderer = RecordingRenderer()
        seen = []
        control = Button("Save")
        returned = control.attach(lambda item, active: seen.append((item, active)))

        self.assertIs(returned, control)
        item = control.build(renderer=renderer)

        self.assertEqual(seen, [(item, renderer)])

    def test_component_attachment_added_after_build_runs_immediately(self):
        renderer = RecordingRenderer()
        control = Label("Ready")
        item = control.build(renderer=renderer)
        seen = []

        control.attach(lambda attached_item, active: seen.append((attached_item, active)))

        self.assertEqual(seen, [(item, renderer)])

    def test_control_row_and_column_contexts_support_incremental_content(self):
        renderer = RecordingRenderer()
        row = ControlRow()
        column = ControlColumn()

        with column.context(renderer=renderer):
            with row.context(renderer=renderer):
                renderer.create("label", text="imperative child")

        self.assertEqual([entry[0] for entry in renderer.containers], ["column", "row"])
        self.assertEqual(renderer.created[-1][0], "label")
        self.assertEqual(renderer.created[-1][2]["text"], "imperative child")

    def test_section_panel_owns_heading_separator_and_profile_dimensions(self):
        profile = ComponentLayoutProfile(
            name="panel-profile",
            parent=FRAMEWORK_COMPONENT_PROFILE,
            layouts={
                "demo.panel": ControlLayoutDefaults(width=530, height=290),
            },
        )
        renderer = RecordingRenderer(profile)
        panel = SectionPanel(
            "NETWORKING",
            heading_color=(255, 200, 100),
            profile_key="demo.panel",
        )

        with panel.context(renderer=renderer):
            renderer.create("label", text="inside")

        kind, item, kwargs = renderer.containers[0]
        self.assertEqual(kind, "panel")
        self.assertEqual(kwargs["width"], 530)
        self.assertEqual(kwargs["height"], 290)
        self.assertTrue(kwargs["border"])
        self.assertEqual(panel.require_item(), item)
        self.assertEqual(renderer.created[0][0], "label")
        self.assertEqual(renderer.created[0][2]["text"], "NETWORKING")
        self.assertEqual(renderer.created[1][0], "separator")

    def test_section_panel_declarative_children_share_same_container(self):
        renderer = RecordingRenderer()
        panel = SectionPanel(
            "QUEUE",
            (Label("Active download slots"), Button("Apply Queue")),
        )

        panel.build(renderer=renderer)

        self.assertEqual(renderer.containers[0][0], "panel")
        self.assertEqual([entry[0] for entry in renderer.created], [
            "label", "separator", "label", "button"
        ])

    def test_dialog_uses_profile_size_without_backend_sizing_literals(self):
        profile = ComponentLayoutProfile(
            name="dialog-profile",
            parent=FRAMEWORK_COMPONENT_PROFILE,
            layouts={
                "demo.dialog": ControlLayoutDefaults(width=620, height=365),
            },
        )
        renderer = RecordingRenderer(profile)
        dialog = Dialog(
            "Seeding Goal for Torrent",
            modal=True,
            show=False,
            no_resize=True,
            profile_key="demo.dialog",
        )

        with dialog.context(renderer=renderer):
            Separator().build(renderer=renderer)

        kind, _, kwargs = renderer.containers[0]
        self.assertEqual(kind, "dialog")
        self.assertEqual(kwargs["width"], 620)
        self.assertEqual(kwargs["height"], 365)
        self.assertTrue(kwargs["modal"])
        self.assertFalse(kwargs["show"])
        self.assertTrue(kwargs["no_resize"])

    def test_settings_structural_regions_are_component_owned(self):
        source = (PROJECT_ROOT / "app" / "views" / "settings_view.py").read_text(
            encoding="utf-8"
        )
        profile_source = (PROJECT_ROOT / "app" / "engine" / "ui_component_profile.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("SectionPanel(", source)
        self.assertIn("ControlColumn()", source)
        self.assertIn(".context(parent=parent_tag)", source)
        self.assertNotIn("dpg.child_window", source)
        self.assertNotIn("with dpg.group", source)
        self.assertIn('"settings.networking_panel": ControlLayoutDefaults(width=530, height=290)', profile_source)
        self.assertIn('"settings.desktop_panel": ControlLayoutDefaults(width=FILL, height=350)', profile_source)

    def test_configure_targets_dialog_structure_is_component_owned(self):
        source = (PROJECT_ROOT / "app" / "views" / "download_view.py").read_text(
            encoding="utf-8"
        )
        profile_source = (PROJECT_ROOT / "app" / "engine" / "ui_component_profile.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("self.seeding_goal_dialog = Dialog(", source)
        self.assertIn('profile_key="configure_targets.dialog"', source)
        self.assertIn("self.seeding_goal_dialog_separator = Separator()", source)
        self.assertNotIn("width=620,\n            height=365", source)
        self.assertIn('"configure_targets.dialog": ControlLayoutDefaults(width=620, height=365)', profile_source)

    def test_progress_bar_dispatches_through_renderer_and_value_api(self):
        renderer = RecordingRenderer()
        progress = ProgressBar(default_value=0.25)

        progress.build(renderer=renderer)

        self.assertEqual(renderer.created[-1][0], "progress_bar")
        self.assertEqual(progress.get_value(), 0.25)
        progress.set_value(0.75)
        self.assertEqual(progress.get_value(), 0.75)

    def test_tooltip_attachment_uses_renderer_boundary(self):
        renderer = RecordingRenderer()
        button = Button("Create").attach(Tooltip("Create a torrent", wrap=420))

        item = button.build(renderer=renderer)

        self.assertEqual(renderer.tooltips, [(item, "Create a torrent", 420)])

    def test_empty_tooltip_attachment_is_a_safe_noop(self):
        renderer = RecordingRenderer()
        label = Label("Status").attach(Tooltip("   "))

        label.build(renderer=renderer)

        self.assertEqual(renderer.tooltips, [])

    def test_create_torrent_structure_is_component_owned(self):
        source = (PROJECT_ROOT / "app" / "views" / "create_torrent_view.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("self.create_root = ControlColumn()", source)
        self.assertIn("SectionPanel(", source)
        self.assertIn("ControlRow()", source)
        self.assertNotIn("with dpg.child_window", source)
        self.assertNotIn("with dpg.group", source)

    def test_create_torrent_value_controls_are_component_owned(self):
        source = (PROJECT_ROOT / "app" / "views" / "create_torrent_view.py").read_text(
            encoding="utf-8"
        )

        for token in (
            "dpg.add_button(",
            "dpg.add_combo(",
            "dpg.add_checkbox(",
            "dpg.add_input_text(",
            "dpg.add_progress_bar(",
        ):
            self.assertNotIn(token, source)
        self.assertIn("ProgressBar(", source)
        self.assertIn("TextInput(", source)
        self.assertIn("ComboBox(", source)

    def test_create_torrent_dimensions_are_profile_owned(self):
        source = (PROJECT_ROOT / "app" / "views" / "create_torrent_view.py").read_text(
            encoding="utf-8"
        )
        profile_source = (PROJECT_ROOT / "app" / "engine" / "ui_component_profile.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("width=235", source)
        self.assertNotIn("width=130", source)
        self.assertNotIn("height=155", source)
        self.assertNotIn("height=190", source)
        self.assertNotIn("height=145", source)
        self.assertIn('profile_key="create_torrent.generation"', source)
        self.assertIn('profile_key="create_torrent.progress_bar"', source)
        self.assertIn('"create_torrent.source_panel": ControlLayoutDefaults(width=FILL, height=155)', profile_source)
        self.assertIn('"create_torrent.progress_bar": ControlLayoutDefaults(width=FILL, height=22)', profile_source)

    def test_create_torrent_uses_attachment_adapters_for_component_help(self):
        source = (PROJECT_ROOT / "app" / "views" / "create_torrent_view.py").read_text(
            encoding="utf-8"
        )
        adapter_source = (PROJECT_ROOT / "app" / "engine" / "ui_component_attachments.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("from app.engine.ui_component_attachments import help_tooltip, text_tooltip", source)
        self.assertIn('.attach(help_tooltip("CREATE_TORRENT"))', source)
        self.assertIn(".attach(text_tooltip(", source)
        self.assertNotIn("add_help_tooltip(", source)
        self.assertNotIn("add_text_tooltip(", source)
        self.assertNotIn("app.views", adapter_source)
        self.assertIn("app.localization.documents", adapter_source)

    def test_help_tooltip_backend_creation_is_centralized_in_renderer(self):
        help_source = (PROJECT_ROOT / "app" / "views" / "help_terms.py").read_text(
            encoding="utf-8"
        )
        renderer_source = (PROJECT_ROOT / "app" / "engine" / "components" / "renderer.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("import dearpygui", help_source)
        self.assertIn("get_default_renderer().attach_tooltip", help_source)
        self.assertIn("dpg.add_tooltip(parent=item)", renderer_source)

    def test_component_runtime_state_helpers_use_renderer_configuration(self):
        renderer = RecordingRenderer()
        button = Button("Run", enabled=True, show=True)
        item = button.build(renderer=renderer)

        self.assertTrue(button.exists())
        button.set_enabled(False)
        button.set_visible(False)
        button.configure(label="Retry")

        self.assertEqual(
            renderer.configured[item],
            {"enabled": False, "show": False, "label": "Retry"},
        )

    def test_component_group_applies_shared_runtime_state(self):
        renderer = RecordingRenderer()
        first = Button("First")
        second = ComboBox(("A", "B"), default_value="A")
        first.build(renderer=renderer)
        second.build(renderer=renderer)
        group = ComponentGroup(first, second)

        group.set_enabled(False)
        group.set_visible(True)

        self.assertEqual(len(group), 2)
        for component in group:
            configured = renderer.configured[component.require_item()]
            self.assertFalse(configured["enabled"])
            self.assertTrue(configured["show"])

    def test_component_group_accepts_iterables_and_rejects_non_components(self):
        first = Button("First")
        second = Button("Second")
        group = ComponentGroup((first, second))

        self.assertEqual(tuple(group), (first, second))
        with self.assertRaises(TypeError):
            ComponentGroup(first, object())

    def test_create_torrent_runtime_state_uses_components_not_dearpygui(self):
        source = (PROJECT_ROOT / "app" / "views" / "create_torrent_view.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("import dearpygui", source)
        self.assertNotIn("dpg.", source)
        self.assertIn("ComponentGroup(", source)
        self.assertIn("self.creation_editable_components.set_enabled", source)
        self.assertIn("self.progress_component.set_value", source)
        self.assertIn("self.status_component.set_text", source)
        self.assertIn("self.start_seeding_component.set_visible", source)


    def test_progress_bar_overlay_configures_through_renderer(self):
        renderer = RecordingRenderer()
        progress = ProgressBar(default_value=0.0, overlay="Idle")
        item = progress.build(renderer=renderer)

        progress.set_overlay("Metadata 50%")

        self.assertEqual(progress.overlay, "Metadata 50%")
        self.assertEqual(renderer.configured[item]["overlay"], "Metadata 50%")

    def test_dialog_supports_minimum_size_and_backend_neutral_centering(self):
        profile = ComponentLayoutProfile(
            name="dialog-center",
            parent=FRAMEWORK_COMPONENT_PROFILE,
            layouts={
                "demo.centered": ControlLayoutDefaults(width=680, height=285),
            },
        )
        renderer = RecordingRenderer(profile)
        dialog = Dialog(
            "Open Magnet Link",
            modal=True,
            minimum_size=(560, 250),
            profile_key="demo.centered",
        )

        with dialog.context(renderer=renderer):
            Label("Magnet").build(renderer=renderer)
        dialog.center()

        self.assertEqual(renderer.containers[0][2]["min_size"], [560, 250])
        self.assertEqual(renderer.centered, [(dialog.require_item(), (680, 285))])

    def test_magnet_dialog_structure_is_component_owned(self):
        source = (PROJECT_ROOT / "app" / "views" / "download_view.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("self.magnet_dialog = Dialog(", source)
        self.assertIn('profile_key="download.magnet.dialog"', source)
        self.assertIn("self.magnet_input_component = TextInput(", source)
        self.assertIn("self.magnet_progress_component = ProgressBar(", source)
        self.assertIn("self.magnet_action_row = ControlRow()", source)
        self.assertNotIn("dpg.add_input_text(\n                multiline=True,\n                height=70", source)

    def test_magnet_runtime_state_uses_component_contract(self):
        source = (PROJECT_ROOT / "app" / "views" / "download_view.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("self.magnet_progress_component.set_overlay", source)
        self.assertIn("self.magnet_input_component.get_value", source)
        self.assertIn("self.magnet_add_component.set_enabled", source)
        self.assertIn("self.magnet_dialog.center()", source)
        for token in (
            "dpg.set_value(self.magnet_progress",
            "dpg.configure_item(self.magnet_progress",
            "dpg.configure_item(self.magnet_add_button",
            "dpg.configure_item(self.magnet_cancel_button",
            "dpg.show_item(self.magnet_modal)",
            "dpg.hide_item(self.magnet_modal)",
        ):
            self.assertNotIn(token, source)

    def test_transfer_confirmation_dialogs_are_component_owned(self):
        source = (PROJECT_ROOT / "app" / "views" / "download_view.py").read_text(
            encoding="utf-8"
        )

        for name in (
            "remove_torrent_dialog",
            "remove_notice_dialog",
            "recheck_dialog",
            "completion_notice_dialog",
        ):
            self.assertIn(f"self.{name} = Dialog(", source)
        self.assertIn("self.remove_torrent_dialog.show_centered()", source)
        self.assertIn("self.completion_notice_title_component.set_text", source)
        self.assertIn("self.recheck_title_component.set_text", source)

    def test_transfer_dialog_dimensions_are_profile_owned(self):
        source = (PROJECT_ROOT / "app" / "views" / "download_view.py").read_text(
            encoding="utf-8"
        )
        profile_source = (PROJECT_ROOT / "app" / "engine" / "ui_component_profile.py").read_text(
            encoding="utf-8"
        )

        for token in (
            'profile_key="download.magnet.dialog"',
            'profile_key="download.remove.dialog"',
            'profile_key="download.removal_notice.dialog"',
            'profile_key="download.recheck.dialog"',
            'profile_key="download.completion_notice.dialog"',
        ):
            self.assertIn(token, source)
        self.assertIn('"download.magnet.dialog": ControlLayoutDefaults(width=680, height=285)', profile_source)
        self.assertIn('"download.remove.dialog": ControlLayoutDefaults(width=520, height=230)', profile_source)
        self.assertIn('"download.recheck.dialog": ControlLayoutDefaults(width=560, height=190)', profile_source)
        self.assertIn('"download.completion_notice.dialog": ControlLayoutDefaults(width=480, height=150)', profile_source)
    def test_value_binding_round_trips_with_explicit_transforms(self):
        renderer = RecordingRenderer()
        control = TextInput(default_value="42")
        control.build(renderer=renderer)
        binding = ValueBinding(
            "answer",
            control,
            read_transform=lambda value: int(value),
            write_transform=lambda value: str(int(value)),
        )

        self.assertEqual(binding.read(), 42)
        self.assertTrue(binding.write({"answer": 7}))
        self.assertEqual(control.get_value(), "7")

    def test_binding_set_collects_and_applies_only_when_explicitly_called(self):
        renderer = RecordingRenderer()
        name = TextInput(default_value="alpha")
        enabled = CheckBox("Enabled", default_value=True)
        name.build(renderer=renderer)
        enabled.build(renderer=renderer)
        bindings = BindingSet(
            ValueBinding("name", name, read_transform=str),
            ValueBinding("enabled", enabled, read_transform=bool),
        )

        self.assertEqual(bindings.collect(), {"name": "alpha", "enabled": True})
        name.set_value("local-only")
        self.assertEqual(enabled.get_value(), True)
        self.assertEqual(bindings.apply({"name": "model-value", "enabled": False}), ("name", "enabled"))
        self.assertEqual(name.get_value(), "model-value")
        self.assertFalse(enabled.get_value())

    def test_binding_set_rejects_invalid_or_duplicate_bindings(self):
        control = TextInput(default_value="")
        with self.assertRaises(TypeError):
            ValueBinding("bad", Button("Not a value"))
        first = ValueBinding("same", control)
        second = ValueBinding("same", control)
        with self.assertRaises(ValueError):
            BindingSet(first, second)
        with self.assertRaises(TypeError):
            BindingSet(first, object())

    def test_binding_defaults_are_explicit_and_missing_values_do_not_require_observers(self):
        renderer = RecordingRenderer()
        control = TextInput(default_value="")
        control.build(renderer=renderer)
        binding = ValueBinding("path", control, default="downloads")

        self.assertEqual(binding.read(), "downloads")
        self.assertTrue(binding.write({}))
        self.assertEqual(control.get_value(), "downloads")

    def test_preferences_runtime_values_use_explicit_component_bindings_not_dearpygui(self):
        source = (PROJECT_ROOT / "app" / "views" / "settings_view.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("import dearpygui", source)
        self.assertNotIn("dpg.", source)
        self.assertIn("BindingSet(", source)
        self.assertIn("ValueBinding(", source)
        self.assertIn("self.preference_bindings.collect()", source)
        self.assertIn("self.preference_bindings.apply(settings)", source)
        self.assertIn("self.connectivity_status_component.set_text", source)
        self.assertIn("self.status_component.set_text", source)



if __name__ == "__main__":
    unittest.main()
