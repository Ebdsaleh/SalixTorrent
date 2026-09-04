import inspect
import unittest

from app.engine.responsive_layout import (
    ContentMetrics,
    HorizontalAlign,
    ResponsiveLayout,
    aligned_offset,
    clamp,
    content_bounds,
    fill_height,
    split_widths,
)


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

    def test_resize_callback_exposes_only_dpg_standard_arguments(self):
        layout = ResponsiveLayout.get_instance()
        callback = layout._make_item_resize_callback("test-key")
        parameters = tuple(inspect.signature(callback).parameters)
        self.assertEqual(parameters, ("sender", "app_data", "user_data"))

    def test_resize_callback_dispatches_captured_key(self):
        layout = ResponsiveLayout.get_instance()
        seen = []
        layout._item_callbacks["test-key"] = lambda: seen.append("fired")
        try:
            callback = layout._make_item_resize_callback("test-key")
            callback(123, (800, 600), None)
            self.assertEqual(seen, ["fired"])
        finally:
            layout._item_callbacks.pop("test-key", None)


if __name__ == "__main__":
    unittest.main()
