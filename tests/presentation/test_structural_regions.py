from __future__ import annotations

from contextlib import contextmanager
import unittest

from app.framework.components import (
    Button,
    ControlLayout,
    Label,
    SplitOrientation,
    SplitPane,
    SplitPanel,
    TabContainer,
    TabPage,
)
from app.framework.components.events import ComponentEvent, ComponentEventType
from app.framework.components.profile import FRAMEWORK_COMPONENT_PROFILE
from app.framework.geometry import split_sizes
from app.framework.responsive import LayoutCoordinator
from app.engine.component_renderers.dearpygui import DearPyGuiRenderer


class RegionRenderer:
    def __init__(self):
        self.component_profile = FRAMEWORK_COMPONENT_PROFILE
        self.created = []
        self.containers = []
        self.values = {}
        self.callbacks = {}
        self.placements = {}
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
        if kind == "tabs" and kwargs.get("callback") is not None:
            self.callbacks[item] = kwargs["callback"]
        yield item

    def get_value(self, item):
        return self.values.get(item)

    def set_value(self, item, value):
        self.values[item] = value

    def configure(self, item, **kwargs):
        return None

    def place(self, item, x, y):
        self.placements[item] = (int(x), int(y))
        return None

    def measure(self, item):
        for _kind, candidate, kwargs in (*self.created, *self.containers):
            if candidate == item:
                width = kwargs.get("width", 80)
                height = kwargs.get("height", 24)
                return (
                    80 if width in (None, -1) else int(width),
                    24 if height in (None, -1) else int(height),
                )
        return (0, 0)

    def exists(self, item):
        return item not in self.destroyed and any(
            candidate == item
            for _kind, candidate, _kwargs in (*self.created, *self.containers)
        )

    def destroy(self, item):
        self.destroyed.add(item)

    def event_callback(self, source, event_type, callback, *, data=None):
        if callback is None:
            return None

        def dispatch(value=None):
            return callback(
                ComponentEvent(
                    source=source,
                    event_type=event_type,
                    value=value,
                    data=data,
                )
            )

        return dispatch

    def center(self, item, *, fallback_size=None):
        return None

    def attach_tooltip(self, item, text, *, wrap=450):
        return None


class RegionLayoutHost:
    def __init__(self, sizes=None):
        self.sizes = dict(sizes or {})
        self.configured = {}
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
        return self.sizes.get(item, (1000, 400))

    def configure(self, item, **kwargs):
        self.configured.setdefault(item, {}).update(kwargs)
        return True


class _StrictDearPyGuiTabApi:
    """Tiny fake matching the DPG tab contracts relevant to this regression."""

    def __init__(self):
        self.calls = []

    @contextmanager
    def tab_bar(self, **kwargs):
        if "width" in kwargs or "height" in kwargs:
            raise AssertionError("Dear PyGui tab_bar received unsupported dimensions")
        self.calls.append(("tabs", dict(kwargs)))
        yield "dpg:tabs"

    @contextmanager
    def tab(self, **kwargs):
        if "width" in kwargs or "height" in kwargs:
            raise AssertionError("Dear PyGui tab received unsupported dimensions")
        self.calls.append(("tab_page", dict(kwargs)))
        yield "dpg:tab"


class StructuralRegionContractTests(unittest.TestCase):
    def test_dearpygui_tabs_filter_unsupported_semantic_dimensions(self):
        renderer = DearPyGuiRenderer()
        fake = _StrictDearPyGuiTabApi()
        renderer._dpg = lambda: fake

        callback = object()
        with renderer.container(
            "tabs",
            width=-1,
            height=300,
            parent="root",
            callback=callback,
        ) as tabs_item:
            self.assertEqual("dpg:tabs", tabs_item)
            with renderer.container(
                "tab_page",
                width=640,
                height=240,
                label="Page",
            ) as page_item:
                self.assertEqual("dpg:tab", page_item)

        self.assertEqual(
            ("tabs", {"parent": "root", "callback": callback}),
            fake.calls[0],
        )
        self.assertEqual(
            ("tab_page", {"label": "Page"}),
            fake.calls[1],
        )

    def test_split_sizes_are_axis_neutral_and_deterministic(self):
        self.assertEqual(
            (330, 660),
            split_sizes(1000, (1, 2), minimums=(100, 200), gap=10),
        )
        self.assertEqual(
            600 - 5,
            sum(split_sizes(600, (1, 1), minimums=(100, 100), gap=5)),
        )

    def test_tab_container_uses_stable_keys_for_selection_and_change_events(self):
        renderer = RegionRenderer()
        events = []
        tabs = TabContainer(
            (
                TabPage("first", "First", (Label("One"),)),
                TabPage("second", "Second", (Label("Two"),)),
            ),
            callback=events.append,
        )
        tabs.build(renderer=renderer)

        self.assertTrue(tabs.select("second", notify=True))
        self.assertEqual("second", tabs.selected_key())
        self.assertEqual(ComponentEventType.CHANGE, events[-1].event_type)
        self.assertEqual("second", events[-1].value)

        renderer.callbacks[tabs.require_item()](tabs.page_item("first"))
        self.assertEqual("first", events[-1].value)

    def test_tab_change_falls_back_to_backend_current_value_when_callback_data_is_empty(self):
        renderer = RegionRenderer()
        events = []
        tabs = TabContainer(
            (
                TabPage("first", "First"),
                TabPage("second", "Second"),
            ),
            callback=events.append,
        )
        tabs.build(renderer=renderer)
        renderer.values[tabs.require_item()] = tabs.page_item("second")

        renderer.callbacks[tabs.require_item()](None)

        self.assertEqual("second", events[-1].value)

    def test_tab_container_incremental_page_context_supports_existing_views(self):
        renderer = RegionRenderer()
        tabs = TabContainer()
        with tabs.context(renderer=renderer):
            with tabs.page_context("one", "One", renderer=renderer):
                Label("A").build(renderer=renderer)
            with tabs.page_context("two", "Two", renderer=renderer):
                Button("B").build(renderer=renderer)

        self.assertEqual(("one", "two"), tuple(page.key for page in tabs.pages))
        self.assertTrue(tabs.page("one").exists())
        self.assertTrue(tabs.page("two").exists())

    def test_tab_container_rejects_duplicate_keys(self):
        with self.assertRaises(ValueError):
            TabContainer((TabPage("same", "A"), TabPage("same", "B")))

    def test_split_panel_reflows_named_panes_through_layout_coordinator(self):
        renderer = RegionRenderer()
        host = RegionLayoutHost()
        coordinator = LayoutCoordinator(host)
        split = SplitPanel(
            (
                SplitPane("left", Label("Left"), weight=1, minimum=100, border=True),
                SplitPane("right", Label("Right"), weight=2, minimum=200, border=True),
            ),
            gap=10,
            coordinator=coordinator,
        )
        split.build(renderer=renderer)

        self.assertEqual((330, 660), split.current_sizes)
        self.assertEqual(330, host.configured[split.pane_item("left")]["width"])
        self.assertEqual(660, host.configured[split.pane_item("right")]["width"])
        self.assertEqual(400, host.configured[split.pane_item("left")]["height"])
        self.assertEqual(400, host.configured[split.pane_item("right")]["height"])
        self.assertEqual((0, 0), renderer.placements[split.pane_item("left")])
        self.assertEqual((340, 0), renderer.placements[split.pane_item("right")])
        self.assertEqual(
            ["split_pane", "split_pane"],
            [kind for kind, _item, _kwargs in renderer.containers if kind == "split_pane"],
        )
        self.assertIn(
            "positioned_panel",
            [kind for kind, _item, _kwargs in renderer.containers],
        )

    def test_vertical_split_uses_height_and_can_be_reflowed_explicitly(self):
        renderer = RegionRenderer()
        host = RegionLayoutHost()
        coordinator = LayoutCoordinator(host)
        split = SplitPanel(
            (
                SplitPane("top", minimum=80),
                SplitPane("bottom", minimum=120),
            ),
            orientation=SplitOrientation.VERTICAL,
            gap=6,
            coordinator=coordinator,
        )
        with split.context(renderer=renderer):
            with split.pane_context("top", renderer=renderer):
                Label("Top").build(renderer=renderer)
            with split.pane_context("bottom", renderer=renderer):
                Label("Bottom").build(renderer=renderer)

        root = split.require_item()
        host.sizes[root] = (500, 706)
        sizes = split.reflow()
        self.assertEqual(700, sum(sizes))
        self.assertEqual(sizes[0], host.configured[split.pane_item("top")]["height"])
        self.assertEqual(sizes[1], host.configured[split.pane_item("bottom")]["height"])
        self.assertEqual(500, host.configured[split.pane_item("top")]["width"])
        self.assertEqual(500, host.configured[split.pane_item("bottom")]["width"])
        self.assertEqual((0, 0), renderer.placements[split.pane_item("top")])
        self.assertEqual((0, sizes[0] + 6), renderer.placements[split.pane_item("bottom")])

    def test_split_panel_disposal_releases_resize_watch(self):
        renderer = RegionRenderer()
        host = RegionLayoutHost()
        coordinator = LayoutCoordinator(host)
        split = SplitPanel(
            (SplitPane("one"), SplitPane("two")),
            coordinator=coordinator,
        )
        split.build(renderer=renderer)
        self.assertEqual(1, len(host.watches))
        self.assertTrue(split.dispose())
        self.assertEqual({}, host.watches)


if __name__ == "__main__":
    unittest.main(verbosity=2)
