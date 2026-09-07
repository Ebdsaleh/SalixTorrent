from __future__ import annotations

from contextlib import contextmanager
import unittest

from app.framework.components import (
    Button,
    ControlGrid,
    ControlLayout,
    Insets,
    Label,
    PlacedComponent,
    Placement,
    PositionedPanel,
    positioned,
)
from app.framework.components.profile import FRAMEWORK_COMPONENT_PROFILE


class GeometryRenderer:
    def __init__(self):
        self.component_profile = FRAMEWORK_COMPONENT_PROFILE
        self.created = []
        self.containers = []
        self.configured = {}
        self.placements = []
        self.destroyed = set()

    def _item(self, prefix):
        return f"{prefix}:{len(self.created) + len(self.containers) + 1}"

    def set_component_profile(self, profile):
        self.component_profile = profile

    def create(self, kind, **kwargs):
        item = self._item(kind)
        self.created.append((kind, item, dict(kwargs)))
        return item

    @contextmanager
    def container(self, kind, **kwargs):
        item = self._item(kind)
        self.containers.append((kind, item, dict(kwargs)))
        yield item

    def get_value(self, item):
        return None

    def set_value(self, item, value):
        return None

    def configure(self, item, **kwargs):
        self.configured.setdefault(item, {}).update(kwargs)

    def place(self, item, x, y):
        self.placements.append((item, int(x), int(y)))

    def measure(self, item):
        for _kind, candidate, kwargs in (*self.created, *self.containers):
            if candidate == item:
                width = kwargs.get("width", 80)
                height = kwargs.get("height", 24)
                if width in (None, -1):
                    width = 80
                if height in (None, -1):
                    height = 24
                return int(width), int(height)
        return (0, 0)

    def exists(self, item):
        if item in self.destroyed:
            return False
        return any(candidate == item for _kind, candidate, _kwargs in (*self.created, *self.containers))

    def destroy(self, item):
        self.destroyed.add(item)

    def event_callback(self, source, event_type, callback, *, data=None):
        return callback

    def center(self, item, *, fallback_size=None):
        return None

    def attach_tooltip(self, item, text, *, wrap=450):
        return None


class MixedLayoutContractTests(unittest.TestCase):
    def test_insets_support_compact_forms(self):
        self.assertEqual(Insets(4, 4, 4, 4), Insets(4, 4, 4, 4))
        from app.framework.components.placement import insets

        self.assertEqual(Insets(5, 5, 5, 5), insets(5))
        self.assertEqual(Insets(8, 3, 8, 3), insets((8, 3)))
        self.assertEqual(Insets(1, 2, 3, 4), insets((1, 2, 3, 4)))

    def test_placement_translates_margin_and_reports_occupied_bounds(self):
        placement = Placement(200, 100, margin=(10, 5, 20, 15))
        self.assertEqual((210, 105), (placement.local_x, placement.local_y))
        self.assertEqual((630, 370), placement.occupied_size(400, 250))

    def test_negative_explicit_coordinates_are_rejected(self):
        with self.assertRaises(ValueError):
            Placement(-1, 0)
        with self.assertRaises(ValueError):
            Placement(0, -1)

    def test_placed_component_reserves_offset_and_child_extent_for_parent(self):
        renderer = GeometryRenderer()
        child = Button("Reset", layout=ControlLayout(width=120, height=30))
        wrapper = PlacedComponent(child, x=200, y=100, margin=(10, 5, 20, 15))

        wrapper.build(renderer=renderer)

        slot = wrapper.require_item()
        self.assertEqual((350, 150), wrapper.occupied_size)
        self.assertEqual({"width": 350, "height": 150}, renderer.configured[slot])
        self.assertEqual((child.require_item(), 210, 105), renderer.placements[-1])

    def test_positioned_panel_grows_to_direct_children_and_padding(self):
        renderer = GeometryRenderer()
        first = Label("A", layout=ControlLayout(width=80, height=20))
        second = Button("B", layout=ControlLayout(width=100, height=30))
        panel = PositionedPanel(
            (
                positioned(first, x=10, y=10),
                positioned(second, x=180, y=70, margin=(5, 4, 5, 6)),
            ),
            padding=(12, 8),
        )

        panel.build(renderer=renderer)

        self.assertEqual((314, 126), panel.occupied_size)
        self.assertEqual((first.require_item(), 22, 18), renderer.placements[0])
        self.assertEqual((second.require_item(), 197, 82), renderer.placements[1])
        configured = renderer.configured[panel.require_item()]
        self.assertEqual(314, configured["width"])
        self.assertEqual(126, configured["height"])

    def test_grid_column_minimum_includes_placed_child_offset(self):
        renderer = GeometryRenderer()
        panel = PositionedPanel(
            (positioned(Label("Inside", layout=ControlLayout(width=160, height=30)), x=20, y=10),),
            layout=ControlLayout(width=200, height=80),
        )
        wrapped = PlacedComponent(panel, x=200, y=100)
        grid = ControlGrid(((Label("Left"), wrapped),), column_widths=(90, 120))

        grid.build(renderer=renderer)

        grid_columns = [entry for entry in renderer.created if entry[0] == "grid_column"]
        self.assertEqual(90, grid_columns[0][2]["init_width_or_weight"])
        self.assertEqual(400, grid_columns[1][2]["init_width_or_weight"])
        self.assertEqual((400, 180), wrapped.occupied_size)

    def test_positioned_panel_can_contain_an_automatic_layout_component(self):
        renderer = GeometryRenderer()
        inner_grid = ControlGrid(
            ((Label("Name"), Button("Save", layout=ControlLayout(width=90, height=28))),),
            column_widths=(80, 90),
            layout=ControlLayout(width=180, height=40),
        )
        panel = PositionedPanel(
            (positioned(inner_grid, x=30, y=25),),
            padding=5,
        )

        panel.build(renderer=renderer)

        self.assertTrue(panel.exists())
        self.assertTrue(inner_grid.exists())
        self.assertIn((inner_grid.require_item(), 35, 30), renderer.placements)


if __name__ == "__main__":
    unittest.main(verbosity=2)
