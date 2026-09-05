"""Seeding-goal policy and automatic-stop regressions."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.logic.bencode import Bencode
from app.logic.seeding_policy import (
    DEFAULT_SEEDING_RATIO,
    DEFAULT_SEEDING_TIME_MINUTES,
    MAX_SEEDING_RATIO,
    MAX_SEEDING_TIME_MINUTES,
    MIN_SEEDING_RATIO,
    MIN_SEEDING_TIME_MINUTES,
    SEEDING_GOAL_EITHER,
    SEEDING_GOAL_FOREVER,
    SEEDING_GOAL_RATIO,
    SEEDING_GOAL_TIME,
    evaluate_seeding_goal,
    seeding_time_components_from_minutes,
    seeding_time_components_to_minutes,
    seeding_time_preset_minutes,
    seeding_time_preset_selection,
    seeding_time_parts_from_minutes,
    seeding_time_parts_to_minutes,
    normalise_seeding_goal_mode,
    normalise_seeding_ratio,
    normalise_seeding_time_minutes,
)
from app.logic.session import SessionState, TorrentSession


def _write_torrent(path: Path, payload: bytes = b"seeding-goal-test") -> None:
    info = {
        b"name": b"seed.bin",
        b"piece length": 16 * 1024,
        b"pieces": hashlib.sha1(payload).digest(),
        b"length": len(payload),
    }
    path.write_bytes(Bencode.encode({b"info": info}))


class TestSeedingGoalPolicy(unittest.TestCase):
    def test_normalization_is_bounded_and_fail_safe(self):
        self.assertEqual(normalise_seeding_goal_mode("unknown"), SEEDING_GOAL_FOREVER)
        self.assertEqual(normalise_seeding_ratio("bad"), DEFAULT_SEEDING_RATIO)
        self.assertEqual(normalise_seeding_time_minutes("bad"), DEFAULT_SEEDING_TIME_MINUTES)
        self.assertEqual(normalise_seeding_ratio(-1), MIN_SEEDING_RATIO)
        self.assertEqual(normalise_seeding_ratio(1_000_000), MAX_SEEDING_RATIO)
        self.assertEqual(normalise_seeding_time_minutes(0), MIN_SEEDING_TIME_MINUTES)
        self.assertEqual(
            normalise_seeding_time_minutes(9_999_999),
            MAX_SEEDING_TIME_MINUTES,
        )

    def test_quick_time_presets_cover_requested_day_hour_and_minute_ranges(self):
        self.assertEqual(seeding_time_preset_minutes("minutes", 1), 1)
        self.assertEqual(seeding_time_preset_minutes("minutes", 60), 60)
        self.assertEqual(seeding_time_preset_minutes("hours", 1), 60)
        self.assertEqual(seeding_time_preset_minutes("hours", 12), 720)
        self.assertEqual(seeding_time_preset_minutes("days", 1), 1_440)
        self.assertEqual(seeding_time_preset_minutes("days", 31), 44_640)
        with self.assertRaises(ValueError):
            seeding_time_preset_minutes("hours", 13)
        with self.assertRaises(ValueError):
            seeding_time_preset_minutes("minutes", 0)

    def test_quick_time_preset_selection_is_deterministic_across_restart(self):
        self.assertEqual(seeding_time_preset_selection(45), ("minutes", 45))
        self.assertEqual(seeding_time_preset_selection(60), ("hours", 1))
        self.assertEqual(seeding_time_preset_selection(720), ("hours", 12))
        self.assertEqual(seeding_time_preset_selection(1_440), ("days", 1))
        self.assertEqual(seeding_time_preset_selection(44_640), ("days", 31))
        self.assertIsNone(seeding_time_preset_selection(90))

    def test_quick_time_components_are_additive(self):
        self.assertEqual(seeding_time_components_to_minutes(1, 5, 10), 1750)
        self.assertEqual(seeding_time_components_from_minutes(1750), (1, 5, 10))
        self.assertEqual(seeding_time_components_to_minutes(0, 12, 60), 780)

    def test_editor_time_parts_round_trip_days_hours_and_minutes(self):
        self.assertEqual(seeding_time_parts_from_minutes(3_000), (2, 2, 0))
        self.assertEqual(seeding_time_parts_from_minutes(1_750), (1, 5, 10))
        self.assertEqual(seeding_time_parts_to_minutes(1, 5, 10), 1_750)
        self.assertEqual(seeding_time_parts_to_minutes(0, 1, 0), 60)
        self.assertEqual(seeding_time_parts_to_minutes(0, 0, 0), 1)

    def test_timed_goal_uses_an_instance_baseline_instead_of_lifetime_seed_time(self):
        status = evaluate_seeding_goal(
            SEEDING_GOAL_TIME,
            1.0,
            60,
            uploaded_bytes=0,
            payload_bytes=100,
            elapsed_seconds=70 * 60,
            time_baseline_seconds=70 * 60,
        )
        self.assertFalse(status.reached)
        self.assertEqual(status.elapsed_seconds, 0.0)
        self.assertEqual(status.total_elapsed_seconds, 70 * 60)

        reached = evaluate_seeding_goal(
            SEEDING_GOAL_TIME,
            1.0,
            60,
            uploaded_bytes=0,
            payload_bytes=100,
            elapsed_seconds=130 * 60,
            time_baseline_seconds=70 * 60,
        )
        self.assertTrue(reached.reached)
        self.assertEqual(reached.elapsed_seconds, 60 * 60)

    def test_indefinite_mode_never_auto_stops(self):
        status = evaluate_seeding_goal(
            SEEDING_GOAL_FOREVER,
            1.0,
            60,
            uploaded_bytes=10_000,
            payload_bytes=100,
            elapsed_seconds=86_400,
        )
        self.assertFalse(status.reached)
        self.assertEqual(status.reason, "")
        self.assertIsNone(status.remaining_ratio)
        self.assertIsNone(status.remaining_seconds)

    def test_ratio_goal_reaches_at_payload_equivalent_threshold(self):
        below = evaluate_seeding_goal(
            SEEDING_GOAL_RATIO,
            1.5,
            60,
            uploaded_bytes=149,
            payload_bytes=100,
            elapsed_seconds=0,
        )
        reached = evaluate_seeding_goal(
            SEEDING_GOAL_RATIO,
            1.5,
            60,
            uploaded_bytes=150,
            payload_bytes=100,
            elapsed_seconds=0,
        )
        self.assertFalse(below.reached)
        self.assertAlmostEqual(below.current_ratio, 1.49)
        self.assertTrue(reached.reached)
        self.assertEqual(reached.reason, "ratio")

    def test_ratio_goal_does_not_spuriously_reach_for_zero_payload(self):
        status = evaluate_seeding_goal(
            SEEDING_GOAL_RATIO,
            1.0,
            60,
            uploaded_bytes=10_000,
            payload_bytes=0,
            elapsed_seconds=0,
        )
        self.assertFalse(status.reached)
        self.assertEqual(status.current_ratio, 0.0)

    def test_time_goal_counts_cumulative_seeding_seconds(self):
        before = evaluate_seeding_goal(
            SEEDING_GOAL_TIME,
            1.0,
            10,
            uploaded_bytes=0,
            payload_bytes=100,
            elapsed_seconds=599.9,
        )
        reached = evaluate_seeding_goal(
            SEEDING_GOAL_TIME,
            1.0,
            10,
            uploaded_bytes=0,
            payload_bytes=100,
            elapsed_seconds=600.0,
        )
        self.assertFalse(before.reached)
        self.assertTrue(reached.reached)
        self.assertEqual(reached.reason, "time")

    def test_either_goal_reaches_on_the_first_satisfied_condition(self):
        by_ratio = evaluate_seeding_goal(
            SEEDING_GOAL_EITHER,
            2.0,
            120,
            uploaded_bytes=200,
            payload_bytes=100,
            elapsed_seconds=1,
        )
        by_time = evaluate_seeding_goal(
            SEEDING_GOAL_EITHER,
            2.0,
            120,
            uploaded_bytes=1,
            payload_bytes=100,
            elapsed_seconds=7_200,
        )
        both = evaluate_seeding_goal(
            SEEDING_GOAL_EITHER,
            2.0,
            120,
            uploaded_bytes=200,
            payload_bytes=100,
            elapsed_seconds=7_200,
        )
        self.assertEqual(by_ratio.reason, "ratio")
        self.assertEqual(by_time.reason, "time")
        self.assertEqual(both.reason, "ratio_and_time")


    def test_seeding_clock_accumulates_only_while_explicitly_running(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            torrent_path = root / "seed-clock.torrent"
            _write_torrent(torrent_path)
            session = TorrentSession(
                str(torrent_path),
                download_dir=str(root / "downloads"),
            )

            with mock.patch(
                "app.logic.session.time.monotonic",
                side_effect=[100.0, 115.0, 125.0],
            ):
                session._begin_seeding_clock()
                self.assertEqual(session.seeding_elapsed_seconds, 15.0)
                session._pause_seeding_clock()

            # Once paused, wall-clock time no longer changes the persisted value.
            self.assertEqual(session.seeding_elapsed_seconds, 25.0)

    def test_applying_timed_goal_restarts_from_current_seed_time_without_erasing_total(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            torrent_path = root / "timed-instance.torrent"
            _write_torrent(torrent_path)
            session = TorrentSession(
                str(torrent_path),
                download_dir=str(root / "downloads"),
                seeding_goal_mode=SEEDING_GOAL_TIME,
                seeding_time_limit_minutes=60,
                seeding_elapsed_seconds=70 * 60,
            )
            session.state = SessionState.SEEDING

            session.set_seeding_goal(
                SEEDING_GOAL_TIME,
                1.0,
                60,
                time_components=(0, 1, 0),
                restart_time_window=True,
                emit=False,
            )
            self.assertEqual(session.seeding_elapsed_seconds, 70 * 60)
            self.assertEqual(session.seeding_goal_elapsed_seconds, 0.0)
            self.assertFalse(session._check_seeding_goal())

            session._seeding_elapsed_seconds = 130 * 60
            self.assertTrue(session._check_seeding_goal())

    def test_torrent_session_emits_goal_callback_once_until_policy_is_rearmed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            torrent_path = root / "seed.torrent"
            _write_torrent(torrent_path)
            callbacks: list[tuple[str, str]] = []
            session = TorrentSession(
                str(torrent_path),
                download_dir=str(root / "downloads"),
                seeding_goal_mode=SEEDING_GOAL_RATIO,
                seeding_ratio_limit=1.0,
                seeding_goal_callback=lambda info_hash, reason: callbacks.append(
                    (info_hash, reason)
                ),
            )
            session.state = SessionState.SEEDING
            session.uploaded_bytes = session.torrent.total_length

            self.assertTrue(session._check_seeding_goal())
            self.assertFalse(session._check_seeding_goal())
            self.assertEqual(callbacks, [(session.torrent.hex_info_hash, "ratio")])

            session.set_seeding_goal(SEEDING_GOAL_RATIO, 2.0, 60, emit=False)
            self.assertFalse(session._check_seeding_goal())
            session.uploaded_bytes = session.torrent.total_length * 2
            self.assertTrue(session._check_seeding_goal())
            self.assertEqual(len(callbacks), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
