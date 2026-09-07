from __future__ import annotations

import unittest

from app.framework.telemetry import RollingTelemetry, SeriesStatistics


class RealtimeTelemetryTests(unittest.TestCase):
    def test_rolling_telemetry_preserves_declared_series_order(self):
        history = RollingTelemetry(
            ("down", "up"),
            history_seconds=10,
            sample_interval_seconds=1,
            clock=lambda: 10.0,
        )
        sample = history.record({"up": 4, "down": 2}, timestamp=8.0)

        self.assertEqual(history.series_names, ("down", "up"))
        self.assertEqual(sample.values, (2.0, 4.0))

    def test_rolling_telemetry_rejects_missing_or_unknown_series(self):
        history = RollingTelemetry(
            ("a", "b"),
            history_seconds=10,
            sample_interval_seconds=1,
        )

        with self.assertRaisesRegex(ValueError, "missing"):
            history.record({"a": 1})
        with self.assertRaisesRegex(ValueError, "unexpected"):
            history.record({"a": 1, "b": 2, "c": 3})

    def test_snapshot_filters_by_requested_visible_window(self):
        history = RollingTelemetry(
            ("value",),
            history_seconds=20,
            sample_interval_seconds=1,
        )
        history.record({"value": 1}, timestamp=1)
        history.record({"value": 2}, timestamp=8)
        history.record({"value": 3}, timestamp=10)

        window = history.snapshot(now=10, window_seconds=3)

        self.assertEqual(window.values("value"), (2.0, 3.0))
        self.assertEqual(window.aged_rows(), ((2.0, (2.0,)), (0.0, (3.0,))))

    def test_snapshot_statistics_are_current_average_peak_and_minimum(self):
        history = RollingTelemetry(
            ("value",),
            history_seconds=10,
            sample_interval_seconds=1,
        )
        for timestamp, value in ((1, 5), (2, 2), (3, 8)):
            history.record({"value": value}, timestamp=timestamp)

        stats = history.snapshot(now=3).statistics("value")

        self.assertEqual(
            stats,
            SeriesStatistics(
                current=8.0,
                average=5.0,
                peak=8.0,
                minimum=2.0,
                sample_count=3,
            ),
        )

    def test_empty_snapshot_has_zero_statistics(self):
        history = RollingTelemetry(
            ("value",),
            history_seconds=10,
            sample_interval_seconds=1,
        )

        self.assertEqual(
            history.snapshot(now=10).statistics("value"),
            SeriesStatistics(),
        )

    def test_sample_count_is_strictly_bounded(self):
        history = RollingTelemetry(
            ("value",),
            history_seconds=100,
            sample_interval_seconds=1,
            max_samples=3,
        )
        for timestamp in range(5):
            history.record({"value": timestamp}, timestamp=timestamp)

        self.assertEqual(len(history), 3)
        self.assertEqual(history.snapshot(now=4).values("value"), (2.0, 3.0, 4.0))

    def test_clear_discards_history_without_changing_contract(self):
        history = RollingTelemetry(
            ("down", "up"),
            history_seconds=10,
            sample_interval_seconds=1,
        )
        history.record({"down": 1, "up": 2}, timestamp=1)

        history.clear()

        self.assertEqual(len(history), 0)
        self.assertEqual(history.series_names, ("down", "up"))


if __name__ == "__main__":
    unittest.main()
