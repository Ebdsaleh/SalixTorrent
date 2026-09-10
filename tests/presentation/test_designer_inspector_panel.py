"""Concrete property-inspector panel regressions for designer tooling."""

from __future__ import annotations

import ast
import unittest

from tests.helpers import PROJECT_ROOT

from app.framework.components import Button, ControlColumn, ControlLayout, Label
from app.framework.designer import DesignerIdentityMap, DesignerValueKind, capture_component_tree
from app.framework.designer_editing import DesignerPropertyState
from app.framework.designer_inspector import DesignerInspectorRow
from app.framework.designer_inspector_panel import (
    DesignerInspectorPanel,
    DesignerInspectorPanelBinding,
    format_inspector_editor_value,
    parse_inspector_editor_text,
)
from app.framework.designer_workspace import DesignerWorkspace


class FakeInspectorPanelHost:
    def __init__(self):
        self.binding = None
        self.on_set = None
        self.on_clear = None
        self.on_error = None
        self.on_reset = None
        self.on_scrub_base = None
        self.built = []
        self.updated = []
        self.disposed = 0

    @staticmethod
    def _row_items(state):
        return {row.key: {"row": row, "alive": True} for row in state.rows}

    def build(
        self, state, *, parent, title="", on_set=None, on_clear=None, on_error=None,
        on_reset=None, on_scrub_base=None,
    ):
        self.on_set = on_set
        self.on_clear = on_clear
        self.on_error = on_error
        self.on_reset = on_reset
        self.on_scrub_base = on_scrub_base
        self.built.append(state)
        self.binding = DesignerInspectorPanelBinding(
            panel={"alive": True, "parent": parent, "title": str(title)},
            rows=self._row_items(state),
            target_item={"node_id": state.node_id},
        )
        return self.binding

    def update(self, binding, state):
        self.updated.append(state)
        binding.rows.clear()
        binding.rows.update(self._row_items(state))
        binding.target_item = {"node_id": state.node_id}

    def exists(self, binding):
        return bool(binding.panel["alive"])

    def dispose(self, binding):
        binding.panel["alive"] = False
        self.disposed += 1


class DesignerInspectorPanelTests(unittest.TestCase):
    def _fixture(self):
        status = Label("Status")
        action = Button("Run", layout=ControlLayout(width=120, height=30, spacing=4))
        root = ControlColumn((status, action))
        ids = DesignerIdentityMap(prefix="inspector-panel")
        ids.bind(root, "root")
        ids.bind(status, "status")
        ids.bind(action, "action")
        return root, capture_component_tree(root, identities=ids)

    @staticmethod
    def _row(kind, value, *, is_set=True, nullable=False, unsettable=False):
        state = DesignerPropertyState(
            "node",
            "type",
            "value",
            "Value",
            kind,
            True,
            True,
            nullable,
            unsettable,
            is_set,
            value,
        )
        return DesignerInspectorRow.from_property_state(state)

    def test_requires_workspace_valid_host_and_callbacks(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        with self.assertRaisesRegex(TypeError, "requires DesignerWorkspace"):
            DesignerInspectorPanel(object(), FakeInspectorPanelHost())
        with self.assertRaisesRegex(TypeError, "DesignerInspectorPanelHost"):
            DesignerInspectorPanel(workspace, object())
        with self.assertRaisesRegex(TypeError, "change handler"):
            DesignerInspectorPanel(workspace, FakeInspectorPanelHost(), on_change=object())
        with self.assertRaisesRegex(TypeError, "error handler"):
            DesignerInspectorPanel(workspace, FakeInspectorPanelHost(), on_error=object())
        workspace.close()

    def test_build_without_selection_projects_empty_panel(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        host = FakeInspectorPanelHost()
        panel = DesignerInspectorPanel(workspace, host, title="Properties")
        binding = panel.build(parent="right-pane")
        self.assertTrue(panel.exists())
        self.assertEqual("right-pane", binding.panel["parent"])
        self.assertEqual("Properties", binding.panel["title"])
        self.assertEqual({}, binding.rows)
        self.assertFalse(panel.state.has_target)
        panel.dispose()
        workspace.close()

    def test_build_projects_current_target_rows_and_title(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("action")
        host = FakeInspectorPanelHost()
        panel = DesignerInspectorPanel(workspace, host, title="Inspector")
        binding = panel.build(parent="right")
        self.assertEqual("action", panel.state.node_id)
        self.assertEqual("Button", panel.state.type_label)
        self.assertEqual(
            ("profile_key", "layout.width", "layout.height", "layout.spacing", "label", "enabled", "show"),
            tuple(binding.rows),
        )
        self.assertEqual("action", binding.target_item["node_id"])
        panel.dispose()
        workspace.close()

    def test_host_set_delegates_to_checked_workspace_edit_and_refreshes(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("action")
        generation = workspace.state.preview_generation
        old_component = workspace.preview_host.selected_component
        changes = []
        host = FakeInspectorPanelHost()
        panel = DesignerInspectorPanel(workspace, host, on_change=changes.append)
        panel.build(parent="right")
        self.assertTrue(host.on_set("action", "label", "Edited"))
        self.assertEqual("Edited", workspace.state.inspector.row("label").value)
        self.assertEqual(generation + 1, workspace.state.preview_generation)
        self.assertIsNot(old_component, workspace.preview_host.selected_component)
        self.assertTrue(workspace.state.can_undo)
        self.assertEqual("Edited", host.updated[-1].row("label").value)
        self.assertEqual("Edited", changes[-1].row("label").value)
        panel.dispose()
        workspace.close()

    def test_host_clear_uses_existing_unsettable_semantics(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("action")
        host = FakeInspectorPanelHost()
        panel = DesignerInspectorPanel(workspace, host)
        panel.build(parent="right")
        self.assertTrue(panel.state.row("layout.width").can_clear)
        self.assertTrue(host.on_clear("action", "layout.width"))
        width = panel.state.row("layout.width")
        self.assertFalse(width.is_set)
        self.assertFalse(width.can_clear)
        self.assertFalse(host.updated[-1].row("layout.width").is_set)
        panel.dispose()
        workspace.close()

    def test_host_validation_error_is_reported_without_mutating_document(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("action")
        before = workspace.session.snapshot
        generation = workspace.state.preview_generation
        errors = []
        host = FakeInspectorPanelHost()
        panel = DesignerInspectorPanel(
            workspace,
            host,
            on_error=lambda key, exc: errors.append((key, type(exc), str(exc))),
        )
        panel.build(parent="right")
        self.assertFalse(host.on_set("action", "layout.width", "not-a-dimension"))
        self.assertEqual(before, workspace.session.snapshot)
        self.assertEqual(generation, workspace.state.preview_generation)
        self.assertEqual("layout.width", errors[-1][0])
        self.assertIs(errors[-1][1], ValueError)
        panel.dispose()
        workspace.close()

    def test_stale_binding_callback_cannot_edit_a_new_selection(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("action")
        errors = []
        host = FakeInspectorPanelHost()
        panel = DesignerInspectorPanel(
            workspace,
            host,
            on_error=lambda key, exc: errors.append((key, exc)),
        )
        panel.build(parent="right")
        stale_set = host.on_set
        workspace.select_and_focus_node("status")
        panel.refresh()
        self.assertFalse(stale_set("action", "label", "Wrong target"))
        self.assertEqual("Status", workspace.state.inspector.row("text").value)
        self.assertIsInstance(errors[-1][1], KeyError)
        panel.dispose()
        workspace.close()

    def test_refresh_observes_external_selection_retargeting(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("action")
        host = FakeInspectorPanelHost()
        panel = DesignerInspectorPanel(workspace, host)
        panel.build(parent="right")
        workspace.select_and_focus_node("status")
        panel.refresh()
        self.assertEqual("status", host.updated[-1].node_id)
        self.assertIn("text", host.binding.rows)
        self.assertNotIn("label", host.binding.rows)
        panel.dispose()
        workspace.close()

    def test_read_only_and_nonclearable_rows_reject_direct_edits(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("action")
        panel = DesignerInspectorPanel(workspace, FakeInspectorPanelHost())
        panel.build(parent="right")
        with self.assertRaisesRegex(ValueError, "not editable"):
            panel.set_value("profile_key", "other")
        with self.assertRaisesRegex(ValueError, "cannot be cleared"):
            panel.clear_value("label")
        panel.dispose()
        workspace.close()

    def test_nullable_property_can_store_explicit_none_distinct_from_default(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("action")
        host = FakeInspectorPanelHost()
        panel = DesignerInspectorPanel(workspace, host)
        panel.build(parent="right")
        self.assertTrue(host.on_set("action", "layout.spacing", None))
        spacing = panel.state.row("layout.spacing")
        self.assertTrue(spacing.is_set)
        self.assertIsNone(spacing.value)
        self.assertTrue(spacing.can_clear)
        self.assertTrue(host.on_clear("action", "layout.spacing"))
        self.assertFalse(panel.state.row("layout.spacing").is_set)
        panel.dispose()
        workspace.close()

    def test_scalar_editor_codec_formats_and_parses_semantic_values(self):
        text = self._row(DesignerValueKind.TEXT, "hello")
        integer = self._row(DesignerValueKind.INTEGER, 4)
        number = self._row(DesignerValueKind.NUMBER, 2.5)
        dimension = self._row(DesignerValueKind.DIMENSION, "fill")
        toggle = self._row(DesignerValueKind.BOOLEAN, True)
        self.assertEqual("hello", format_inspector_editor_value(text))
        self.assertEqual("4", format_inspector_editor_value(integer))
        self.assertEqual("2.5", format_inspector_editor_value(number))
        self.assertEqual("fill", format_inspector_editor_value(dimension))
        self.assertIs(format_inspector_editor_value(toggle), True)
        self.assertEqual("changed", parse_inspector_editor_text(text, "changed"))
        self.assertEqual(7, parse_inspector_editor_text(integer, "7"))
        self.assertEqual(1.25, parse_inspector_editor_text(number, "1.25"))
        self.assertEqual("auto", parse_inspector_editor_text(dimension, "AUTO"))
        self.assertEqual(240, parse_inspector_editor_text(dimension, "240"))

    def test_collection_editor_codec_uses_unambiguous_json(self):
        strings = self._row(DesignerValueKind.STRING_LIST, ["one", "two"])
        numbers = self._row(DesignerValueKind.NUMBER_LIST, [1, 2.5])
        insets = self._row(
            DesignerValueKind.INSETS,
            {"left": 1, "top": 2, "right": 3, "bottom": 4},
        )
        self.assertEqual('["one","two"]', format_inspector_editor_value(strings))
        self.assertEqual('[1,2.5]', format_inspector_editor_value(numbers))
        self.assertEqual(
            '{"bottom":4,"left":1,"right":3,"top":2}',
            format_inspector_editor_value(insets),
        )
        self.assertEqual(["x", "y"], parse_inspector_editor_text(strings, '["x", "y"]'))
        self.assertEqual([3, 4.5], parse_inspector_editor_text(numbers, "[3, 4.5]"))
        self.assertEqual(
            {"left": 5, "top": 6, "right": 7, "bottom": 8},
            parse_inspector_editor_text(
                insets,
                '{"left":5,"top":6,"right":7,"bottom":8}',
            ),
        )

    def test_unset_and_none_values_format_without_inventing_semantics(self):
        unset = self._row(DesignerValueKind.DIMENSION, None, is_set=False, unsettable=True)
        nullable = self._row(DesignerValueKind.TEXT, None, nullable=True)
        self.assertEqual("", format_inspector_editor_value(unset))
        self.assertEqual("", format_inspector_editor_value(nullable))
        with self.assertRaises(TypeError):
            parse_inspector_editor_text(self._row(DesignerValueKind.BOOLEAN, True), "true")

    def test_document_edit_and_undo_refresh_reconciles_current_value(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("action")
        host = FakeInspectorPanelHost()
        panel = DesignerInspectorPanel(workspace, host)
        panel.build(parent="right")
        self.assertTrue(panel.set_value("label", "Changed"))
        self.assertEqual("Changed", host.updated[-1].row("label").value)
        self.assertTrue(workspace.undo())
        panel.refresh()
        self.assertEqual("Run", host.updated[-1].row("label").value)
        panel.dispose()
        workspace.close()

    def test_dispose_and_stale_binding_rebuild_are_explicit(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("action")
        host = FakeInspectorPanelHost()
        panel = DesignerInspectorPanel(workspace, host)
        first = panel.build(parent="right")
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
        workspace.select_and_focus_node("action")
        host = FakeInspectorPanelHost()
        panel = DesignerInspectorPanel(workspace, host)
        panel.build(parent="right")
        workspace.close()
        with self.assertRaisesRegex(RuntimeError, "workspace is closed"):
            panel.set_value("label", "Nope")
        self.assertTrue(panel.dispose())

    def test_surface_boundaries_keep_semantics_out_of_toolkits(self):
        framework = PROJECT_ROOT / "app" / "framework" / "designer_inspector_panel.py"
        dpg = PROJECT_ROOT / "app" / "engine" / "designer_inspector_panel_hosts" / "dearpygui.py"
        tkinter = PROJECT_ROOT / "app" / "engine" / "designer_inspector_panel_hosts" / "tkinter.py"

        def imports(path):
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

    def test_code_first_component_tree_remains_unchanged(self):
        source, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("action")
        panel = DesignerInspectorPanel(workspace, FakeInspectorPanelHost())
        panel.build(parent="right")
        before = source.children[1].label
        self.assertTrue(panel.set_value("label", "Designer-only"))
        self.assertEqual(before, source.children[1].label)
        self.assertEqual("Designer-only", workspace.state.inspector.row("label").value)
        panel.dispose()
        workspace.close()


    def test_reset_to_defaults_clears_all_explicit_resettable_properties_once(self):
        _, snapshot = self._fixture()
        workspace = DesignerWorkspace.create(snapshot)
        workspace.select_and_focus_node("action")
        host = FakeInspectorPanelHost()
        panel = DesignerInspectorPanel(workspace, host)
        panel.build(parent="right")
        before_depth = workspace.session.undo_depth
        self.assertTrue(host.on_reset("action"))
        state = workspace.inspector_state()
        for key in ("layout.width", "layout.height", "layout.spacing"):
            self.assertFalse(state.row(key).is_set)
        self.assertEqual(before_depth + 1, workspace.session.undo_depth)
        self.assertEqual("Reset component to defaults", workspace.state.undo_label)
        self.assertTrue(workspace.undo())
        self.assertEqual(120, workspace.inspector_state().row("layout.width").value)
        panel.dispose()
        workspace.close()

    def test_reset_noop_when_selected_component_already_uses_defaults(self):
        root = ControlColumn((Button("Run"),))
        ids = DesignerIdentityMap(prefix="reset-default")
        ids.bind(root, "root")
        ids.bind(root.children[0], "action")
        workspace = DesignerWorkspace.create(capture_component_tree(root, identities=ids))
        workspace.select_and_focus_node("action")
        host = FakeInspectorPanelHost()
        panel = DesignerInspectorPanel(workspace, host)
        panel.build(parent="right")
        # Label is explicit constructor data, so clear it first; subsequent reset is a no-op.
        if workspace.inspector_state().row("label").can_clear:
            panel.clear_value("label")
        depth = workspace.session.undo_depth
        self.assertFalse(panel.reset_to_defaults())
        self.assertEqual(depth, workspace.session.undo_depth)
        panel.dispose()
        workspace.close()

    def test_scrub_base_uses_rendered_default_dimensions_and_explicit_values(self):
        root = ControlColumn((Button("Run"),))
        ids = DesignerIdentityMap(prefix="scrub-base")
        ids.bind(root, "root")
        ids.bind(root.children[0], "action")
        workspace = DesignerWorkspace.create(capture_component_tree(root, identities=ids))
        workspace.select_and_focus_node("action")
        host = FakeInspectorPanelHost()
        panel = DesignerInspectorPanel(workspace, host)
        panel.build(parent="right")
        self.assertEqual(120.0, host.on_scrub_base("action", "layout.width"))
        panel.set_value("layout.width", 196)
        self.assertEqual(196.0, host.on_scrub_base("action", "layout.width"))
        panel.dispose()
        workspace.close()

if __name__ == "__main__":
    unittest.main(verbosity=2)
