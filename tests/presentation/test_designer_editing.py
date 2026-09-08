"""Command-based designer editing and undo/redo regressions."""

from __future__ import annotations

import json
import unittest

from app.framework.components import (
    Button,
    ControlColumn,
    ControlLayout,
    Label,
    NumericStepper,
    PositionedPanel,
    TextInput,
    positioned,
)
from app.framework.designer import (
    DesignerIdentityMap,
    DesignerSnapshot,
    FRAMEWORK_DESIGNER_CATALOG,
    capture_component_tree,
)
from app.framework.designer_editing import (
    DESIGNER_REDO_COMMAND,
    DESIGNER_UNDO_COMMAND,
    ClearDesignerProperty,
    CompositeDesignerEdit,
    DesignerEditSession,
    SetDesignerProperty,
    normalize_designer_property_value,
)


class DesignerEditingTests(unittest.TestCase):
    def _button_snapshot(self):
        root = ControlColumn((Button("Run"),), layout=ControlLayout(width=320))
        identities = DesignerIdentityMap(prefix="edit")
        identities.bind(root, "root")
        identities.bind(root.children[0], "button")
        return root, capture_component_tree(root, identities=identities)

    def test_nullable_metadata_distinguishes_none_from_unset(self):
        label_spec = FRAMEWORK_DESIGNER_CATALOG.for_type(Label)
        wrap = next(prop for prop in label_spec.properties if prop.key == "wrap")
        self.assertTrue(wrap.nullable)
        self.assertTrue(wrap.to_descriptor()["nullable"])

        text_input_spec = FRAMEWORK_DESIGNER_CATALOG.for_type(TextInput)
        label = next(prop for prop in text_input_spec.properties if prop.key == "label")
        self.assertTrue(label.nullable)

    def test_property_state_reports_metadata_and_explicit_value_state(self):
        _, snapshot = self._button_snapshot()
        session = DesignerEditSession(snapshot)
        width = session.property_state("button", "layout.width")
        label = session.property_state("button", "label")
        profile = session.property_state("button", "profile_key")

        self.assertFalse(width.is_set)
        self.assertIsNone(width.value)
        self.assertTrue(width.editable)
        self.assertTrue(width.unsettable)
        self.assertEqual("dimension", width.kind.value)
        self.assertTrue(label.is_set)
        self.assertEqual("Run", label.value)
        self.assertFalse(profile.editable)
        json.dumps(label.to_descriptor())

    def test_set_property_validates_types_bounds_choices_dimensions_and_insets(self):
        label = Label("Probe")
        stepper = NumericStepper(kind="integer", default_value=3)
        panel = PositionedPanel(
            (positioned(label, x=5, y=6),),
            padding=(1, 2, 3, 4),
            layout=ControlLayout(width=240, height=120),
        )
        root = ControlColumn((stepper, panel))
        ids = DesignerIdentityMap(prefix="validation")
        ids.bind(stepper, "stepper")
        ids.bind(panel, "panel")
        ids.bind(label, "label")
        snapshot = capture_component_tree(root, identities=ids)
        session = DesignerEditSession(snapshot)

        self.assertTrue(session.set_property("stepper", "kind", "float"))
        self.assertTrue(session.set_property("label", "layout.width", "fill"))
        self.assertTrue(session.set_property("label", "wrap", 180))
        self.assertTrue(session.set_property("label", "wrap", None))
        self.assertTrue(session.set_property("panel", "padding", (8, 12)))
        self.assertEqual(
            {"left": 8, "top": 12, "right": 8, "bottom": 12},
            session.node("panel").properties["padding"],
        )

        with self.assertRaisesRegex(ValueError, "declared choices"):
            session.set_property("stepper", "kind", "decimal")
        with self.assertRaisesRegex(ValueError, "must be positive"):
            session.set_property("label", "layout.width", 0)
        with self.assertRaisesRegex(TypeError, "does not allow None"):
            session.set_property("label", "text", None)
        with self.assertRaisesRegex(ValueError, "must be >= 1"):
            session.set_property("label", "wrap", 0)

    def test_normalizer_handles_list_and_numeric_metadata_without_backend_objects(self):
        combo = FRAMEWORK_DESIGNER_CATALOG.get("control.combo_box")
        items = next(prop.to_descriptor() for prop in combo.properties if prop.key == "items")
        self.assertEqual(["One", "Two"], normalize_designer_property_value(items, ("One", "Two")))

        grid = FRAMEWORK_DESIGNER_CATALOG.get("container.grid")
        widths = next(
            prop.to_descriptor() for prop in grid.properties if prop.key == "column_widths"
        )
        self.assertEqual([80, 120.5], normalize_designer_property_value(widths, (80, 120.5)))
        with self.assertRaisesRegex(TypeError, "numeric"):
            normalize_designer_property_value(widths, (80, "wide"))

    def test_read_only_and_unknown_properties_are_rejected(self):
        _, snapshot = self._button_snapshot()
        session = DesignerEditSession(snapshot)
        with self.assertRaisesRegex(ValueError, "read-only"):
            session.set_property("button", "profile_key", "other")
        with self.assertRaisesRegex(KeyError, "is not defined"):
            session.set_property("button", "missing", "value")
        with self.assertRaisesRegex(KeyError, "node not found"):
            session.set_property("missing-node", "label", "value")
        with self.assertRaisesRegex(ValueError, "cannot be unset"):
            session.clear_property("button", "label")

    def test_set_clear_undo_and_redo_preserve_immutable_snapshot_history(self):
        _, snapshot = self._button_snapshot()
        session = DesignerEditSession(snapshot)

        self.assertFalse(session.is_dirty)
        self.assertTrue(session.set_property("button", "label", "Launch"))
        self.assertEqual("Launch", session.node("button").properties["label"])
        self.assertEqual("Run", snapshot.root.children[0].node.properties["label"])
        self.assertTrue(session.is_dirty)
        self.assertEqual(1, session.undo_depth)
        self.assertEqual("Set label", session.undo_label)

        self.assertTrue(session.set_property("button", "layout.width", 180))
        self.assertTrue(session.clear_property("button", "layout.width"))
        self.assertNotIn("layout.width", session.node("button").properties)
        self.assertEqual(3, session.undo_depth)
        self.assertTrue(session.undo())
        self.assertEqual(180, session.node("button").properties["layout.width"])
        self.assertTrue(session.undo())
        self.assertNotIn("layout.width", session.node("button").properties)
        self.assertEqual("Launch", session.node("button").properties["label"])
        self.assertTrue(session.undo())
        self.assertEqual("Run", session.node("button").properties["label"])
        self.assertFalse(session.can_undo)
        self.assertTrue(session.can_redo)
        self.assertTrue(session.redo())
        self.assertEqual("Launch", session.node("button").properties["label"])

    def test_noop_edits_do_not_create_history_and_new_edit_clears_redo(self):
        _, snapshot = self._button_snapshot()
        session = DesignerEditSession(snapshot)
        self.assertFalse(session.set_property("button", "label", "Run"))
        self.assertEqual(0, session.undo_depth)

        session.set_property("button", "label", "One")
        session.set_property("button", "label", "Two")
        session.undo()
        self.assertTrue(session.can_redo)
        session.set_property("button", "label", "Three")
        self.assertFalse(session.can_redo)
        self.assertEqual("Three", session.node("button").properties["label"])

    def test_mark_clean_tracks_document_state_across_undo_and_redo(self):
        _, snapshot = self._button_snapshot()
        session = DesignerEditSession(snapshot)
        session.set_property("button", "label", "Saved")
        self.assertTrue(session.is_dirty)
        session.mark_clean()
        self.assertFalse(session.is_dirty)
        session.set_property("button", "label", "Later")
        self.assertTrue(session.is_dirty)
        session.undo()
        self.assertFalse(session.is_dirty)
        session.redo()
        self.assertTrue(session.is_dirty)

    def test_composite_edit_is_one_history_step(self):
        _, snapshot = self._button_snapshot()
        session = DesignerEditSession(snapshot)
        command = CompositeDesignerEdit(
            (
                SetDesignerProperty("button", "label", "Launch"),
                SetDesignerProperty("button", "layout.width", 180),
            ),
            label="Resize launch button",
        )
        self.assertTrue(session.execute(command))
        self.assertEqual(1, session.undo_depth)
        self.assertEqual("Resize launch button", session.undo_label)
        self.assertEqual("Launch", session.node("button").properties["label"])
        self.assertEqual(180, session.node("button").properties["layout.width"])
        session.undo()
        self.assertEqual("Run", session.node("button").properties["label"])
        self.assertNotIn("layout.width", session.node("button").properties)

    def test_history_commands_reuse_generic_command_model(self):
        _, snapshot = self._button_snapshot()
        session = DesignerEditSession(snapshot)
        initial = session.history_commands()
        self.assertFalse(initial.enabled(DESIGNER_UNDO_COMMAND))
        self.assertFalse(initial.enabled(DESIGNER_REDO_COMMAND))

        session.set_property("button", "label", "Launch")
        commands = session.history_commands()
        self.assertTrue(commands.enabled(DESIGNER_UNDO_COMMAND))
        self.assertIn("Set label", commands.get(DESIGNER_UNDO_COMMAND).label)
        self.assertTrue(session.dispatch_history_command(DESIGNER_UNDO_COMMAND))
        self.assertEqual("Run", session.node("button").properties["label"])
        self.assertTrue(session.history_commands().enabled(DESIGNER_REDO_COMMAND))
        self.assertTrue(session.dispatch_history_command(DESIGNER_REDO_COMMAND))
        self.assertEqual("Launch", session.node("button").properties["label"])

    def test_edited_snapshot_round_trips_without_mutating_live_components(self):
        root, snapshot = self._button_snapshot()
        live_button = root.children[0]
        session = DesignerEditSession(snapshot)
        session.set_property("button", "label", "Document-only")
        session.set_property("button", "layout.width", 200)

        restored = DesignerSnapshot.from_json(session.snapshot.to_json())
        restored_button = next(node for node in restored.root.walk() if node.node_id == "button")
        self.assertEqual("Document-only", restored_button.properties["label"])
        self.assertEqual(200, restored_button.properties["layout.width"])
        self.assertEqual("Run", live_button.label)
        self.assertIsNone(live_button.item)

    def test_blank_application_snapshot_supports_document_only_edit_history(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class Host:
            presentation = create_dearpygui_backend()

        view = DemoView(Host())
        snapshot = view.capture_designer_snapshot()
        actions = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        session = DesignerEditSession(snapshot)
        self.assertTrue(session.set_property(actions.node_id, "label", "Designer Actions"))
        self.assertEqual(
            "Designer Actions",
            session.node(actions.node_id).properties["label"],
        )
        self.assertEqual("Actions", actions.properties["label"])
        self.assertTrue(session.undo())
        self.assertEqual("Actions", session.node(actions.node_id).properties["label"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
