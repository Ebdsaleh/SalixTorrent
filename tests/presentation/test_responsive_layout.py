import inspect
import unittest

from app.engine.layout_hosts import DearPyGuiLayoutHost
from app.engine.responsive_layout import ResponsiveLayout
from app.framework.geometry import (
    ContentMetrics,
    DialogMetrics,
    HorizontalAlign,
    aligned_offset,
    clamp,
    content_bounds,
    fill_height,
    split_widths,
)
from app.framework.responsive import LayoutCoordinator, LayoutHost


class RecordingLayoutHost:
    def __init__(self):
        self.viewport_callback = None
        self.watch_callbacks = {}
        self.unwatched = []
        self.sizes = {}
        self.configurations = []
        self._counter = 0

    def install_viewport_resize(self, callback):
        self.viewport_callback = callback
        return True

    def watch_item_resize(self, item, callback):
        self._counter += 1
        token = f"watch-{self._counter}"
        self.watch_callbacks[token] = (item, callback)
        return token

    def unwatch_item_resize(self, watch):
        self.unwatched.append(watch)
        self.watch_callbacks.pop(watch, None)

    def item_size(self, item):
        return self.sizes.get(item, (0, 0))

    def configure(self, item, **kwargs):
        self.configurations.append((item, kwargs))
        return True


class ResponsiveGeometryTests(unittest.TestCase):
    def test_clamp_enforces_bounds(self):
        self.assertEqual(clamp(50, 100, 200), 100)
        self.assertEqual(clamp(150, 100, 200), 150)
        self.assertEqual(clamp(250, 100, 200), 200)

    def test_split_widths_consumes_available_width(self):
        widths = split_widths(1200, (0.25, 0.25, 0.50), minimums=(200, 200, 300), gap=8)
        self.assertEqual(sum(widths) + 16, 1200)
        self.assertTrue(all(width > 0 for width in widths))
        self.assertGreater(widths[2], widths[0])

    def test_split_widths_scales_minimums_on_narrow_layout(self):
        widths = split_widths(600, (1, 1, 1), minimums=(300, 300, 400), gap=8)
        self.assertEqual(sum(widths) + 16, 600)
        self.assertTrue(all(width > 0 for width in widths))
        self.assertGreater(widths[2], widths[0])

    def test_fill_height_preserves_minimum_content(self):
        self.assertEqual(fill_height(700, 120, minimum=180), 580)
        self.assertEqual(fill_height(200, 120, minimum=180), 180)

    def test_content_bounds_center_a_max_width_region(self):
        bounds = content_bounds(1400, metrics=ContentMetrics(horizontal_padding=20, maximum_width=900))
        self.assertEqual(bounds.width, 900)
        self.assertEqual(bounds.x, 250)
        self.assertEqual(aligned_offset(bounds.width, 300, HorizontalAlign.CENTER), 300)

    def test_dearpygui_host_callback_exposes_only_standard_arguments(self):
        callback = DearPyGuiLayoutHost._backend_callback(lambda: None)
        parameters = tuple(inspect.signature(callback).parameters)
        self.assertEqual(parameters, ("sender", "app_data", "user_data"))

    def test_dearpygui_host_callback_dispatches_framework_callback(self):
        seen = []
        callback = DearPyGuiLayoutHost._backend_callback(lambda: seen.append("fired"))
        callback(123, (800, 600), None)
        self.assertEqual(seen, ["fired"])

    def test_layout_host_contract_is_backend_neutral(self):
        host = RecordingLayoutHost()
        self.assertIsInstance(host, LayoutHost)
        coordinator = LayoutCoordinator(host)
        self.assertIs(coordinator.host, host)

    def test_layout_coordinator_rejects_incomplete_host(self):
        with self.assertRaisesRegex(TypeError, "LayoutHost"):
            LayoutCoordinator(object())

    def test_viewport_callbacks_install_once_and_refresh_explicitly(self):
        host = RecordingLayoutHost()
        layout = LayoutCoordinator(host)
        seen = []
        layout.register_viewport("root", lambda: seen.append("viewport"))

        self.assertTrue(layout.install_viewport_callback())
        self.assertFalse(layout.install_viewport_callback())
        host.viewport_callback()
        layout.refresh_all()

        self.assertEqual(seen, ["viewport", "viewport"])

    def test_item_watch_replacement_is_host_owned_and_keyed(self):
        host = RecordingLayoutHost()
        layout = LayoutCoordinator(host)
        seen = []

        first = layout.watch_item("panel", "root", lambda: seen.append("first"))
        _item, first_callback = host.watch_callbacks[first]
        first_callback()

        second = layout.watch_item("panel", "root", lambda: seen.append("second"))
        self.assertEqual(host.unwatched, [first])
        _item, second_callback = host.watch_callbacks[second]
        second_callback()
        layout.unwatch_item("root")

        self.assertEqual(seen, ["first", "second"])
        self.assertEqual(host.unwatched, [first, second])

    def test_geometry_writes_are_memoized_above_backend_host(self):
        host = RecordingLayoutHost()
        layout = LayoutCoordinator(host)

        self.assertTrue(layout.width("panel", 420))
        self.assertFalse(layout.width("panel", 420))
        self.assertTrue(layout.width("panel", 421))

        self.assertEqual(
            host.configurations,
            [
                ("panel", {"width": 420}),
                ("panel", {"width": 421}),
            ],
        )

    def test_dialog_geometry_uses_backend_neutral_host_operations(self):
        host = RecordingLayoutHost()
        host.sizes["dialog"] = (700, 500)
        layout = LayoutCoordinator(host)
        metrics = DialogMetrics(
            reserved_height=120,
            minimum_content_height=180,
            horizontal_margin=40,
            minimum_wrap=200,
            maximum_wrap=600,
        )

        layout.dialog(
            "dialog",
            "content",
            metrics=metrics,
            wrap_items=("intro", "status"),
        )

        self.assertIn(("content", {"height": 380}), host.configurations)
        self.assertIn(("intro", {"wrap": 600}), host.configurations)
        self.assertIn(("status", {"wrap": 600}), host.configurations)

    def test_salix_responsive_layout_is_composition_over_dearpygui_host(self):
        layout = ResponsiveLayout.get_instance()
        self.assertIsInstance(layout, LayoutCoordinator)
        self.assertIsInstance(layout.host, DearPyGuiLayoutHost)


if __name__ == "__main__":
    unittest.main()
