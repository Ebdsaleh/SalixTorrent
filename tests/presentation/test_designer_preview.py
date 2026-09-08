"""Designer snapshot-to-component preview reconstruction regressions."""

from __future__ import annotations

import unittest

from app.framework.components import (
    AxisAnchor,
    Button,
    CheckBox,
    ComboBox,
    ControlColumn,
    ControlGrid,
    ControlLayout,
    FILL,
    Label,
    PlacedComponent,
    PositionedPanel,
    SizeConstraints,
    SplitPane,
    SplitPanel,
    TabContainer,
    TabPage,
    anchored,
    positioned,
)
from app.framework.designer import (
    DesignerIdentityMap,
    DesignerNode,
    capture_component_tree,
)
from app.framework.designer_editing import DesignerEditSession
from app.framework.designer_preview import (
    DesignerPreviewCatalog,
    DesignerPreviewContext,
    DesignerPreviewError,
    DesignerPreviewSpec,
    DesignerPreviewUnsupportedTypeError,
    FRAMEWORK_DESIGNER_PREVIEW_CATALOG,
    reconstruct_designer_snapshot,
    unsupported_preview_type_keys,
)
from app.framework.responsive import LayoutCoordinator


class DesignerPreviewTests(unittest.TestCase):
    def test_preview_catalog_rejects_duplicates_and_bad_builders(self):
        with self.assertRaisesRegex(TypeError, "builder must be callable"):
            DesignerPreviewSpec("probe", None)  # type: ignore[arg-type]
        catalog = DesignerPreviewCatalog((DesignerPreviewSpec("probe", lambda n, c, x: Label("x")),))
        with self.assertRaisesRegex(ValueError, "duplicate designer preview type key"):
            catalog.register(DesignerPreviewSpec("probe", lambda n, c, x: Label("y")))

    def test_common_control_snapshot_reconstructs_with_properties_and_layout(self):
        source = ControlColumn((
            Label("Heading", wrap=220, bullet=True, layout=ControlLayout(width=FILL)),
            Button("Run", enabled=False),
            ComboBox(("A", "B"), default_value="B"),
            CheckBox("Enabled", default_value=True),
        ), layout=ControlLayout(width=420, spacing=5))
        ids = DesignerIdentityMap(prefix="preview")
        ids.bind(source, "root")
        snapshot = capture_component_tree(source, identities=ids)
        preview = reconstruct_designer_snapshot(snapshot)
        self.assertIsInstance(preview.root, ControlColumn)
        self.assertEqual(420, preview.root.layout.width)
        self.assertEqual(5, preview.root.layout.spacing)
        heading = preview.root.children[0]
        self.assertIsInstance(heading, Label)
        self.assertEqual("Heading", heading.text)
        self.assertEqual("fill", heading.layout.width)
        button = preview.root.children[1]
        self.assertIsInstance(button, Button)
        self.assertFalse(button.enabled)
        self.assertIsNone(button.callback)

    def test_preview_build_preserves_stable_node_bindings_and_recaptures_source(self):
        source = ControlColumn((Label("One"), Button("Two")))
        ids = DesignerIdentityMap(prefix="stable")
        ids.bind(source, "root")
        ids.bind(source.children[0], "one")
        ids.bind(source.children[1], "two")
        snapshot = capture_component_tree(source, identities=ids)
        preview = reconstruct_designer_snapshot(snapshot)
        self.assertIs(preview.root, preview.component("root"))
        self.assertEqual("One", preview.component("one").text)
        self.assertEqual(snapshot.to_descriptor(), preview.recapture().to_descriptor())
        with self.assertRaises(KeyError):
            preview.component("missing")

    def test_positioned_and_anchored_relationships_reconstruct_semantically(self):
        source = PositionedPanel((
            positioned(Button("Fixed", layout=ControlLayout(width=80, height=24)), x=12, y=18),
            anchored(
                Button("Stretch", layout=ControlLayout(height=24)),
                horizontal=AxisAnchor.STRETCH,
                vertical=AxisAnchor.END,
                margin=(4, 5, 6, 7),
                constraints=SizeConstraints(minimum_width=100, maximum_width=240),
            ),
        ), padding=6, border=True, fit_content=False, layout=ControlLayout(width=320, height=160))
        snapshot = capture_component_tree(source)
        preview = reconstruct_designer_snapshot(snapshot)
        panel = preview.root
        self.assertIsInstance(panel, PositionedPanel)
        self.assertEqual(2, len(panel.children))
        fixed, stretch = panel.children
        self.assertEqual(12, fixed.placement.x)
        self.assertEqual(18, fixed.placement.y)
        self.assertEqual(AxisAnchor.STRETCH, stretch.placement.horizontal)
        self.assertEqual(AxisAnchor.END, stretch.placement.vertical)
        self.assertEqual(240, stretch.placement.constraints.maximum_width)
        self.assertEqual(snapshot.to_descriptor(), preview.recapture().to_descriptor())

    def test_grid_tabs_and_split_relationships_reconstruct_without_flattening(self):
        grid = ControlGrid(((Label("A"), Label("B")),), column_widths=(90, 110))
        tabs = TabContainer((TabPage("grid", "Grid", (grid,)),))
        source = SplitPanel((
            SplitPane("left", tabs, weight=1, minimum=200, maximum=420, border=True),
            SplitPane("right", Label("Inspector"), weight=2, minimum=260),
        ), gap=8)
        snapshot = capture_component_tree(source)
        preview = reconstruct_designer_snapshot(snapshot)
        split = preview.root
        self.assertIsInstance(split, SplitPanel)
        self.assertEqual(("left", "right"), tuple(pane.key for pane in split.panes))
        self.assertEqual(420, split.panes[0].maximum)
        rebuilt_tabs = split.panes[0].child
        self.assertIsInstance(rebuilt_tabs, TabContainer)
        self.assertEqual("grid", rebuilt_tabs.pages[0].key)
        rebuilt_grid = rebuilt_tabs.pages[0].children[0]
        self.assertIsInstance(rebuilt_grid, ControlGrid)
        self.assertEqual((90, 110), rebuilt_grid.column_widths)
        self.assertEqual(snapshot.to_descriptor(), preview.recapture().to_descriptor())

    def test_placed_component_reconstructs_fixed_local_placement(self):
        source = PlacedComponent(Button("Inside", layout=ControlLayout(width=80)), x=30, y=15)
        snapshot = capture_component_tree(source)
        preview = reconstruct_designer_snapshot(snapshot)
        self.assertIsInstance(preview.root, PlacedComponent)
        self.assertEqual(30, preview.root.placement.x)
        self.assertEqual(15, preview.root.placement.y)
        self.assertEqual(snapshot.to_descriptor(), preview.recapture().to_descriptor())

    def test_sparse_grid_snapshot_is_rejected_before_backend_rendering(self):
        grid = ControlGrid(((Label("A"), Label("B")),))
        snapshot = capture_component_tree(grid)
        second = snapshot.root.children[1]
        sparse_root = DesignerNode(snapshot.root.node_id, snapshot.root.type_key, snapshot.root.properties, (second,))
        sparse = type(snapshot)(sparse_root, snapshot.types)
        with self.assertRaisesRegex(DesignerPreviewError, "dense rectangular"):
            reconstruct_designer_snapshot(sparse)

    def test_specialized_field_types_are_explicitly_reported_as_unsupported(self):
        from app.framework.components import LabeledComboField

        snapshot = capture_component_tree(LabeledComboField("Mode", ("A", "B"), default_value="A"))
        self.assertEqual(("field.labeled_combo",), unsupported_preview_type_keys(snapshot))
        with self.assertRaises(DesignerPreviewUnsupportedTypeError) as caught:
            reconstruct_designer_snapshot(snapshot)
        self.assertEqual(("field.labeled_combo",), caught.exception.type_keys)

    def test_preview_context_accepts_injected_layout_coordinator(self):
        class Host:
            def install_viewport_resize(self, callback):
                return True
            def watch_item_resize(self, item, callback):
                return None
            def unwatch_item_resize(self, watch):
                return None
            def item_size(self, item):
                return (400, 300)
            def configure(self, item, **kwargs):
                return True

        coordinator = LayoutCoordinator(Host())
        source = PositionedPanel((anchored(Label("Pinned"), horizontal=AxisAnchor.END),))
        preview = reconstruct_designer_snapshot(
            capture_component_tree(source),
            context=DesignerPreviewContext(layout_coordinator=coordinator),
        )
        self.assertIs(preview.root.coordinator, coordinator)
        with self.assertRaisesRegex(TypeError, "layout_coordinator"):
            DesignerPreviewContext(layout_coordinator=object())  # type: ignore[arg-type]

    def test_blank_application_snapshot_is_fully_previewable_and_round_trips(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class Host:
            presentation = create_dearpygui_backend()

        view = DemoView(Host())
        snapshot = view.capture_designer_snapshot()
        self.assertEqual((), unsupported_preview_type_keys(snapshot))
        preview = view.reconstruct_designer_preview()
        self.assertEqual(snapshot.node_count, len(preview.components))
        self.assertEqual(snapshot.to_descriptor(), preview.recapture().to_descriptor())

    def test_property_and_structural_edits_feed_preview_without_touching_live_tree(self):
        source_left = ControlColumn((Button("Move me"), Label("Stay")))
        source_right = ControlColumn((Label("Target"),))
        live_root = ControlColumn((source_left, source_right))
        ids = DesignerIdentityMap(prefix="edited")
        ids.bind(live_root, "root")
        ids.bind(source_left, "left")
        ids.bind(source_left.children[0], "move")
        ids.bind(source_left.children[1], "stay")
        ids.bind(source_right, "right")
        ids.bind(source_right.children[0], "target")
        snapshot = capture_component_tree(live_root, identities=ids)
        session = DesignerEditSession(snapshot)
        self.assertTrue(session.set_property("move", "label", "Preview only"))
        self.assertTrue(session.reparent_node("move", "right", index=1))
        preview = reconstruct_designer_snapshot(session.snapshot)
        rebuilt_button = preview.component("move")
        self.assertIsInstance(rebuilt_button, Button)
        self.assertEqual("Preview only", rebuilt_button.label)
        self.assertEqual(["target", "move"], [
            child.node.node_id for child in session.node("right").children
        ])
        self.assertEqual("Move me", source_left.children[0].label)
        self.assertIs(source_left.children[0], live_root.children[0].children[0])

    def test_custom_preview_catalog_can_extend_without_mutating_framework_registry(self):
        snapshot = capture_component_tree(Label("Probe"))
        catalog = DesignerPreviewCatalog((
            DesignerPreviewSpec("control.label", lambda node, children, context: Label("Custom")),
        ))
        preview = reconstruct_designer_snapshot(snapshot, catalog=catalog)
        self.assertEqual("Custom", preview.root.text)
        self.assertEqual("Probe", snapshot.root.properties["text"])
        self.assertTrue(FRAMEWORK_DESIGNER_PREVIEW_CATALOG.supports("control.label"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
