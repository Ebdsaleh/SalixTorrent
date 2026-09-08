from __future__ import annotations

from contextlib import contextmanager
import json
import unittest

from app.framework.components import (
    AnchoredPlacement,
    AxisAnchor,
    Button,
    ControlGrid,
    ControlLayout,
    Insets,
    Label,
    PlacedComponent,
    Placement,
    PositionedPanel,
    SizeConstraints,
    anchored,
    anchored_overlay,
    overlay,
    placement_from_descriptor,
    positioned,
)
from app.framework.components.profile import FRAMEWORK_COMPONENT_PROFILE
from app.framework.responsive import LayoutCoordinator


class GeometryRenderer:
    def __init__(self):
        self.component_profile = FRAMEWORK_COMPONENT_PROFILE
        self.created = []
        self.containers = []
        self.configured = {}
        self.placements = []
        self.measurements = {}
        self.zero_first_measure = False
        self._zeroed_items = set()
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
        if self.zero_first_measure and item not in self._zeroed_items:
            self._zeroed_items.add(item)
            return (0, 0)
        if item in self.measurements:
            return self.measurements[item]
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


class GeometryLayoutHost:
    def __init__(self, default_size=(400, 180)):
        self.default_size = tuple(default_size)
        self.sizes = {}
        self.watches = {}
        self._counter = 0

    def install_viewport_resize(self, callback):
        return True

    def watch_item_resize(self, item, callback):
        self._counter += 1
        watch = (self._counter, item)
        self.watches[watch] = callback
        return watch

    def unwatch_item_resize(self, watch):
        self.watches.pop(watch, None)

    def item_size(self, item):
        return self.sizes.get(item, self.default_size)

    def configure(self, item, **kwargs):
        return True


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


    def test_non_measuring_overlay_uses_local_coordinates_without_growing_parent(self):
        renderer = GeometryRenderer()
        measured = Label("Base", layout=ControlLayout(width=120, height=40))
        badge = Button("Badge", layout=ControlLayout(width=80, height=24))
        panel = PositionedPanel(
            (
                positioned(measured, x=10, y=10),
                overlay(badge, x=500, y=300),
            ),
            padding=5,
        )

        panel.build(renderer=renderer)

        self.assertEqual((140, 60), panel.occupied_size)
        self.assertEqual((badge.require_item(), 505, 305), renderer.placements[-1])
        self.assertFalse(panel.children[1].placement.affects_layout)

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

    def test_anchored_placement_supports_edges_centre_stretch_and_constraints(self):
        end = AnchoredPlacement(
            horizontal=AxisAnchor.END,
            vertical=AxisAnchor.CENTER,
            margin=(10, 8, 20, 12),
        )
        self.assertEqual((280, 93, 100, 30), tuple(end.resolve(400, 220, 100, 30).__dict__.values()))

        stretch = AnchoredPlacement(
            horizontal=AxisAnchor.STRETCH,
            vertical=AxisAnchor.START,
            margin=(20, 10, 20, 10),
            constraints=SizeConstraints(minimum_width=120, maximum_width=300),
        )
        rect = stretch.resolve(500, 120, 80, 24)
        self.assertEqual((20, 10, 300, 24), (rect.x, rect.y, rect.width, rect.height))

    def test_anchored_reflow_refreshes_late_backend_child_measurement(self):
        renderer = GeometryRenderer()
        host = GeometryLayoutHost((400, 120))
        coordinator = LayoutCoordinator(host)
        pinned = Label("Late size")
        panel = PositionedPanel(
            (
                anchored_overlay(
                    pinned,
                    horizontal=AxisAnchor.END,
                    vertical=AxisAnchor.START,
                    margin=10,
                ),
            ),
            fit_content=False,
            coordinator=coordinator,
            layout=ControlLayout(width=400, height=120),
        )

        # Dear PyGui can report a zero rect before the first rendered frame.
        # Reflow must refresh the natural child size once the backend knows it.
        renderer.zero_first_measure = True
        panel.build(renderer=renderer)
        pinned_item = pinned.require_item()
        renderer.measurements[pinned_item] = (70, 20)
        panel.reflow()

        self.assertEqual((pinned_item, 320, 10), renderer.placements[-1])

    def test_placement_descriptors_round_trip_through_json_safe_data(self):
        fixed = Placement(12, 34, margin=(1, 2, 3, 4), affects_layout=False)
        anchored_placement = AnchoredPlacement(
            horizontal=AxisAnchor.END,
            vertical=AxisAnchor.STRETCH,
            margin=(5, 6, 7, 8),
            constraints=SizeConstraints(80, 20, 240, 140),
        )
        for placement in (fixed, anchored_placement):
            payload = json.loads(json.dumps(placement.to_descriptor()))
            restored = placement_from_descriptor(payload)
            self.assertEqual(placement, restored)

    def test_positioned_panel_reflows_anchored_children_on_parent_resize(self):
        renderer = GeometryRenderer()
        host = GeometryLayoutHost((400, 180))
        coordinator = LayoutCoordinator(host)
        pinned = Button("Pinned", layout=ControlLayout(width=80, height=24))
        stretched = Button("Stretch", layout=ControlLayout(height=26))
        panel = PositionedPanel(
            (
                anchored_overlay(
                    pinned,
                    horizontal=AxisAnchor.END,
                    vertical=AxisAnchor.END,
                    margin=10,
                ),
                anchored(
                    stretched,
                    horizontal=AxisAnchor.STRETCH,
                    vertical=AxisAnchor.START,
                    margin=(20, 8, 20, 8),
                    constraints=SizeConstraints(minimum_width=120, maximum_width=300),
                ),
            ),
            padding=5,
            fit_content=False,
            coordinator=coordinator,
            layout=ControlLayout(width=400, height=180),
        )

        panel.build(renderer=renderer)
        root = panel.require_item()
        self.assertEqual((pinned.require_item(), 305, 141), renderer.placements[-2])
        self.assertEqual((stretched.require_item(), 25, 13), renderer.placements[-1])
        self.assertEqual(300, renderer.configured[stretched.require_item()]["width"])
        self.assertEqual(1, len(host.watches))

        host.sizes[root] = (600, 240)
        panel.reflow()
        self.assertEqual((pinned.require_item(), 505, 201), renderer.placements[-2])
        self.assertEqual((stretched.require_item(), 25, 13), renderer.placements[-1])
        self.assertEqual(300, renderer.configured[stretched.require_item()]["width"])

        self.assertTrue(panel.dispose())
        self.assertEqual({}, host.watches)



if __name__ == "__main__":
    unittest.main(verbosity=2)
