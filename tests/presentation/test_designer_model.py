"""Designer metadata/snapshot regressions for the provisional RAD boundary."""

from __future__ import annotations

import ast
import json
import unittest

from tests.helpers import PROJECT_ROOT

from app.framework import components as component_package
from app.framework.components import (
    AxisAnchor,
    Button,
    CheckBox,
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
from app.framework.components.base import Component
from app.framework.designer import (
    DESIGNER_SNAPSHOT_KIND,
    DESIGNER_SNAPSHOT_VERSION,
    DesignerCatalog,
    DesignerComponentSpec,
    DesignerIdentityMap,
    DesignerPropertySpec,
    DesignerSnapshot,
    DesignerValueKind,
    FRAMEWORK_DESIGNER_CATALOG,
    capture_component_tree,
)


class DesignerModelTests(unittest.TestCase):
    def test_framework_catalog_exposes_provisional_type_and_property_metadata(self):
        label_spec = FRAMEWORK_DESIGNER_CATALOG.for_type(Label)
        self.assertEqual("control.label", label_spec.key)
        self.assertEqual("control", label_spec.category)
        self.assertFalse(label_spec.accepts_children)
        property_keys = {prop.key for prop in label_spec.properties}
        self.assertTrue({"profile_key", "layout.width", "text", "wrap", "bullet"}.issubset(property_keys))

        metadata = FRAMEWORK_DESIGNER_CATALOG.metadata_descriptor(
            keys=("control.label", "container.positioned")
        )
        self.assertEqual(["control.label", "container.positioned"], [item["key"] for item in metadata])
        json.dumps(metadata)

    def test_property_metadata_rejects_invalid_choice_and_numeric_bounds(self):
        with self.assertRaisesRegex(ValueError, "choices require choice kind"):
            DesignerPropertySpec(
                "mode",
                "Mode",
                DesignerValueKind.TEXT,
                choices=("a", "b"),
            )
        with self.assertRaisesRegex(ValueError, "maximum must be >= minimum"):
            DesignerPropertySpec(
                "size",
                "Size",
                DesignerValueKind.INTEGER,
                minimum=10,
                maximum=5,
            )

    def test_catalog_rejects_duplicate_keys_and_component_types(self):
        one = DesignerComponentSpec("probe.one", "One", Label)
        catalog = DesignerCatalog((one,))
        with self.assertRaisesRegex(ValueError, "duplicate designer component type key"):
            catalog.register(DesignerComponentSpec("probe.one", "Other", Button))
        with self.assertRaisesRegex(ValueError, "already registered"):
            catalog.register(DesignerComponentSpec("probe.label", "Label", Label))

    def test_identity_map_is_stable_and_supports_explicit_persisted_keys(self):
        identities = DesignerIdentityMap(prefix="probe")
        first = Label("First")
        second = Label("Second")
        self.assertEqual("probe-0001", identities.identify(first))
        self.assertEqual("probe-0001", identities.identify(first))
        self.assertEqual("persisted-second", identities.bind(second, "persisted-second"))
        self.assertEqual("persisted-second", identities.identify(second))
        with self.assertRaisesRegex(ValueError, "already belongs"):
            identities.bind(Label("Third"), "persisted-second")

    def test_component_tree_snapshot_captures_properties_hierarchy_and_layout(self):
        root = ControlColumn(
            (
                Label("Heading", layout=ControlLayout(width=FILL)),
                CheckBox("Enabled", default_value=True),
            ),
            layout=ControlLayout(width=640),
        )
        identities = DesignerIdentityMap(prefix="tree")
        identities.bind(root, "root")
        snapshot = capture_component_tree(root, identities=identities)

        self.assertEqual(DESIGNER_SNAPSHOT_KIND, snapshot.kind)
        self.assertEqual(DESIGNER_SNAPSHOT_VERSION, snapshot.version)
        self.assertEqual("root", snapshot.root.node_id)
        self.assertEqual("container.column", snapshot.root.type_key)
        self.assertEqual(640, snapshot.root.properties["layout.width"])
        self.assertEqual(3, snapshot.node_count)
        heading = snapshot.root.children[0].node
        self.assertEqual("control.label", heading.type_key)
        self.assertEqual("Heading", heading.properties["text"])
        self.assertEqual("fill", heading.properties["layout.width"])

    def test_positioned_and_anchored_relationships_preserve_geometry_metadata(self):
        panel = PositionedPanel(
            (
                positioned(Button("Fixed", layout=ControlLayout(width=80, height=24)), x=12, y=18),
                anchored(
                    Button("Stretch", layout=ControlLayout(height=24)),
                    horizontal=AxisAnchor.STRETCH,
                    vertical=AxisAnchor.END,
                    margin=(4, 5, 6, 7),
                    constraints=SizeConstraints(minimum_width=100, maximum_width=240),
                ),
            ),
            layout=ControlLayout(width=320, height=160),
        )
        snapshot = capture_component_tree(panel)
        fixed = snapshot.root.children[0].metadata["placement"]
        stretch = snapshot.root.children[1].metadata["placement"]
        self.assertEqual("fixed", fixed["kind"])
        self.assertEqual(12, fixed["x"])
        self.assertEqual(18, fixed["y"])
        self.assertEqual("anchored", stretch["kind"])
        self.assertEqual("stretch", stretch["horizontal"])
        self.assertEqual("end", stretch["vertical"])
        self.assertEqual(100, stretch["constraints"]["minimum_width"])
        self.assertEqual(240, stretch["constraints"]["maximum_width"])

    def test_structural_relationships_capture_grid_tab_and_split_semantics(self):
        grid = ControlGrid(((Label("A"), Label("B")),), column_widths=(90, 110))
        tabs = TabContainer((TabPage("grid", "Grid", (grid,)),))
        root = SplitPanel(
            (
                SplitPane("left", tabs, weight=1, minimum=200, maximum=420, border=True),
                SplitPane("right", Label("Inspector"), weight=2, minimum=260),
            ),
            gap=8,
        )
        snapshot = capture_component_tree(root)
        left = snapshot.root.children[0]
        self.assertEqual("pane", left.slot)
        self.assertEqual("left", left.metadata["key"])
        self.assertEqual(420, left.metadata["maximum"])
        tab_page = left.node.children[0]
        self.assertEqual("page", tab_page.slot)
        self.assertEqual("grid", tab_page.metadata["key"])
        cells = tab_page.node.children[0].node.children
        self.assertEqual((0, 0), (cells[0].metadata["row"], cells[0].metadata["column"]))
        self.assertEqual((0, 1), (cells[1].metadata["row"], cells[1].metadata["column"]))

    def test_snapshot_round_trips_through_json_and_keeps_node_ids(self):
        root = ControlColumn((Label("One"), Button("Two")))
        identities = DesignerIdentityMap(prefix="persist")
        identities.bind(root, "designer-root")
        snapshot = capture_component_tree(root, identities=identities)
        restored = DesignerSnapshot.from_json(snapshot.to_json())
        self.assertEqual(snapshot.to_descriptor(), restored.to_descriptor())
        self.assertEqual("designer-root", restored.root.node_id)
        self.assertEqual(snapshot.node_count, restored.node_count)

    def test_snapshot_rejects_reused_component_instances_and_duplicate_serialized_ids(self):
        shared = Label("Shared")
        with self.assertRaisesRegex(ValueError, "cycles or reused"):
            capture_component_tree(ControlColumn((shared, shared)))

        snapshot = capture_component_tree(ControlColumn((Label("A"), Label("B"))))
        descriptor = snapshot.to_descriptor()
        duplicate_id = descriptor["root"]["children"][0]["node"]["id"]
        descriptor["root"]["children"][1]["node"]["id"] = duplicate_id
        with self.assertRaisesRegex(ValueError, "node ids must be unique"):
            DesignerSnapshot.from_descriptor(descriptor)

    def test_salix_views_only_import_component_classes_covered_by_designer_catalog(self):
        imported_component_types: set[type[Component]] = set()
        for path in sorted((PROJECT_ROOT / "app" / "views").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module != "app.framework.components":
                    continue
                for alias in node.names:
                    value = getattr(component_package, alias.name, None)
                    if isinstance(value, type) and issubclass(value, Component):
                        imported_component_types.add(value)

        self.assertTrue(imported_component_types)
        missing = []
        for component_type in sorted(imported_component_types, key=lambda value: value.__name__):
            try:
                FRAMEWORK_DESIGNER_CATALOG.for_type(component_type)
            except KeyError:
                missing.append(component_type.__name__)
        self.assertEqual([], missing)

    def test_blank_application_exposes_stable_backend_neutral_designer_snapshot(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class Host:
            presentation = create_dearpygui_backend()

        view = DemoView(Host())
        first = view.capture_designer_snapshot()
        second = view.capture_designer_snapshot()
        self.assertEqual("demo-root", first.root.node_id)
        self.assertEqual(first.to_descriptor(), second.to_descriptor())
        self.assertGreater(first.node_count, 20)
        self.assertIn("container.positioned", {node.type_key for node in first.root.walk()})
        self.assertIn("structure.split", {node.type_key for node in first.root.walk()})
        self.assertIn("structure.tabs", {node.type_key for node in first.root.walk()})


if __name__ == "__main__":
    unittest.main(verbosity=2)
