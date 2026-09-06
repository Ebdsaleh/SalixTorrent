from __future__ import annotations

from contextlib import contextmanager
import unittest

from tests.helpers import PROJECT_ROOT

from app.framework.components import (
    AUTO,
    BindingSet,
    FILL,
    FRAMEWORK_COMPONENT_PROFILE,
    Button,
    CheckBox,
    ComponentEvent,
    ComponentEventType,
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
    action_callback,
    resolve_control_layout,
)
from app.framework.components.layout import backend_dimension
from app.framework.property_cascade import PropertySource


class RecordingRenderer:
    def __init__(self, component_profile=None):
        self.component_profile = component_profile or FRAMEWORK_COMPONENT_PROFILE
        self.created = []
        self.containers = []
        self.values = {}
        self.configured = {}
        self.tooltips = []
        self.centered = []
        self.destroyed = []
        self.event_bindings = []

    def _new_item(self, prefix: str) -> str:
        return f"{prefix}:{len(self.created) + len(self.containers) + 1}"

    def set_component_profile(self, profile):
        self.component_profile = profile

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
        if item in self.destroyed:
            return False
        return (
            any(entry[1] == item for entry in self.created)
            or any(entry[1] == item for entry in self.containers)
        )

    def destroy(self, item):
        if self.exists(item):
            self.destroyed.append(item)

    def event_callback(self, source, event_type, callback, *, data=None):
        if callback is None:
            return None
        if not callable(callback):
            raise TypeError("component event callback must be callable")
        event_type = ComponentEventType(event_type)

        def dispatch(value=None):
            return callback(
                ComponentEvent(
                    source=source,
                    event_type=event_type,
                    value=value,
                    data=data,
                )
            )

        self.event_bindings.append((source, event_type, callback, data, dispatch))
        return dispatch

    def center(self, item, *, fallback_size=None):
        self.centered.append((item, fallback_size))

    def attach_tooltip(self, item, text, *, wrap=450):
        record = (item, str(text), int(wrap))
        self.tooltips.append(record)
        return record


class GuiComponentFoundationTests(unittest.TestCase):
    def test_component_framework_boundary_is_product_and_backend_neutral(self):
        import ast

        framework_dir = PROJECT_ROOT / "app" / "framework"
        component_dir = framework_dir / "components"
        candidate_files = (framework_dir / "property_cascade.py", *component_dir.glob("*.py"))
        forbidden_prefixes = (
            "app.engine",
            "app.views",
            "app.logic",
            "app.localization",
            "dearpygui",
        )

        for path in candidate_files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            self.assertFalse(
                any(module.startswith(forbidden_prefixes) for module in imports),
                str(path.relative_to(PROJECT_ROOT)),
            )

    def test_dearpygui_renderer_is_isolated_from_framework_core(self):
        framework_renderer = (
            PROJECT_ROOT / "app" / "framework" / "components" / "renderer.py"
        ).read_text(encoding="utf-8")
        backend_renderer = (
            PROJECT_ROOT / "app" / "engine" / "component_renderers" / "dearpygui.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("dearpygui", framework_renderer.lower())
        self.assertNotIn("DearPyGuiRenderer", framework_renderer)
        self.assertIn("import dearpygui.dearpygui as dpg", backend_renderer)
        self.assertIn("class DearPyGuiRenderer", backend_renderer)

    def test_default_renderer_requires_explicit_composition_root_installation(self):
        from app.framework.components.renderer import (
            clear_default_renderer,
            get_default_renderer,
            set_default_renderer,
        )

        previous = clear_default_renderer()
        renderer = RecordingRenderer()
        try:
            with self.assertRaisesRegex(RuntimeError, "no default component renderer"):
                get_default_renderer()

            self.assertIs(set_default_renderer(renderer), renderer)
            self.assertIs(get_default_renderer(), renderer)
            self.assertIs(clear_default_renderer(renderer), renderer)
            with self.assertRaisesRegex(RuntimeError, "no default component renderer"):
                get_default_renderer()
        finally:
            clear_default_renderer()
            if previous is not None:
                set_default_renderer(previous)

    def test_default_renderer_rejects_incomplete_backend_contract(self):
        from app.framework.components.renderer import set_default_renderer

        with self.assertRaisesRegex(TypeError, "missing"):
            set_default_renderer(object())

    def test_gui_engine_owns_renderer_installation_and_teardown(self):
        source = (PROJECT_ROOT / "app" / "engine" / "gui_engine.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("DearPyGuiRenderer(", source)
        self.assertIn("set_default_renderer(self.component_renderer)", source)
        self.assertIn("clear_default_renderer(self.component_renderer)", source)
        self.assertNotIn("get_default_renderer().set_component_profile", source)

    def test_legacy_component_import_path_is_compatibility_only(self):
        legacy_source = (
            PROJECT_ROOT / "app" / "engine" / "components" / "__init__.py"
        ).read_text(encoding="utf-8")
        view_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (PROJECT_ROOT / "app" / "views").glob("*.py")
        )

        self.assertIn("from app.framework.components import *", legacy_source)
        self.assertNotIn("from app.engine.components import", view_sources)

        from app.engine.components import Button as LegacyButton
        from app.engine.property_cascade import PropertySource as LegacyPropertySource

        self.assertIs(LegacyButton, Button)
        self.assertIs(LegacyPropertySource, PropertySource)

    def test_component_events_normalize_activation_value_and_explicit_data(self):
        renderer = RecordingRenderer()
        received = []
        metadata = {"operation": "save"}
        button = Button(
            "Save",
            callback=received.append,
            event_data=metadata,
        )

        button.build(renderer=renderer)
        _, _, kwargs = renderer.created[-1]
        self.assertNotIn("user_data", kwargs)
        kwargs["callback"]("backend-value")

        self.assertEqual(len(received), 1)
        event = received[0]
        self.assertIs(event.source, button)
        self.assertIs(event.event_type, ComponentEventType.ACTIVATE)
        self.assertEqual(event.value, "backend-value")
        self.assertIs(event.data, metadata)

    def test_value_control_events_use_change_semantics(self):
        renderer = RecordingRenderer()
        received = []
        control = ComboBox(
            ("A", "B"),
            default_value="A",
            callback=received.append,
        )

        control.build(renderer=renderer)
        renderer.created[-1][2]["callback"]("B")

        self.assertEqual(len(received), 1)
        self.assertIs(received[0].source, control)
        self.assertIs(received[0].event_type, ComponentEventType.CHANGE)
        self.assertEqual(received[0].value, "B")

    def test_action_callback_adapts_no_argument_commands_explicitly(self):
        calls = []

        def command():
            calls.append("called")
            return "result"

        callback = action_callback(command)
        result = callback(
            ComponentEvent(
                source=object(),
                event_type=ComponentEventType.ACTIVATE,
                value="ignored",
            )
        )

        self.assertEqual(calls, ["called"])
        self.assertEqual(result, "result")
        self.assertEqual(callback.__name__, command.__name__)

    def test_component_dispose_is_renderer_owned_and_idempotent(self):
        renderer = RecordingRenderer()
        label = Label("Disposable")
        item = label.build(renderer=renderer)

        self.assertTrue(label.exists())
        self.assertTrue(label.dispose())
        self.assertEqual(renderer.destroyed, [item])
        self.assertFalse(label.exists())
        self.assertIsNone(label.item)
        self.assertFalse(label.dispose())
        self.assertEqual(renderer.destroyed, [item])

    def test_stale_rendered_items_are_rejected_and_can_be_rebuilt(self):
        renderer = RecordingRenderer()
        label = Label("Rebuildable")
        first_item = label.build(renderer=renderer)
        renderer.destroy(first_item)

        self.assertFalse(label.exists())
        with self.assertRaisesRegex(RuntimeError, "rendered item no longer exists"):
            label.require_item()

        second_item = label.build(renderer=renderer)
        self.assertNotEqual(first_item, second_item)
        self.assertTrue(label.exists())
        self.assertEqual(label.require_item(), second_item)

    def test_composite_fields_forward_renderer_neutral_event_metadata(self):
        renderer = RecordingRenderer()
        received = []
        field = LabeledComboField(
            "Mode",
            ("A", "B"),
            default_value="A",
            callback=received.append,
            event_data="mode-choice",
        )

        field.build(renderer=renderer)
        combo_record = next(entry for entry in renderer.created if entry[0] == "combo_box")
        combo_record[2]["callback"]("B")

        self.assertEqual(len(received), 1)
        self.assertIs(received[0].source, field.control)
        self.assertIs(received[0].event_type, ComponentEventType.CHANGE)
        self.assertEqual(received[0].value, "B")
        self.assertEqual(received[0].data, "mode-choice")

    def test_componentized_no_argument_view_actions_use_explicit_event_adapter(self):
        import ast

        expected = {
            "app/views/create_torrent_view.py": {
                "self._select_file_source",
                "self._select_folder_source",
                "self._choose_output",
                "self._start_creation",
                "self._cancel_creation",
                "self._start_seeding_created_torrent",
            },
            "app/views/settings_view.py": {
                "self._choose_download_dir",
                "self._refresh_connectivity",
                "self._refresh_network_interfaces",
                "self._save",
                "self._restore_defaults",
            },
            "app/views/download_view.py": {
                "self._submit_magnet",
                "self._paste_magnet",
                "self._cancel_magnet",
                "self._close_magnet_dialog",
                "self._confirm_force_recheck",
                "self._completion_open_folder",
            },
        }

        for relative_path, expected_actions in expected.items():
            tree = ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
            adapted_actions = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Name) or node.func.id != "action_callback":
                    continue
                if node.args:
                    adapted_actions.add(ast.unparse(node.args[0]))
            self.assertTrue(expected_actions.issubset(adapted_actions), relative_path)

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
        renderer_source = (
            PROJECT_ROOT / "app" / "engine" / "component_renderers" / "dearpygui.py"
        ).read_text(encoding="utf-8")

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
