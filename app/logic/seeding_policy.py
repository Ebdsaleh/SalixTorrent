"""Seeding-goal policy normalization and evaluation.

The policy is deliberately independent from persistence and presentation so the
same semantics are shared by live torrent sessions, settings defaults, restored
session state, and regression tests.
"""

from __future__ import annotations

from dataclasses import dataclass


SEEDING_GOAL_FOREVER = "Seed Indefinitely"
SEEDING_GOAL_RATIO = "Stop at Ratio"
SEEDING_GOAL_TIME = "Stop after Time"
SEEDING_GOAL_EITHER = "Stop at Ratio or Time"
SEEDING_GOAL_MODES = (
    SEEDING_GOAL_FOREVER,
    SEEDING_GOAL_RATIO,
    SEEDING_GOAL_TIME,
    SEEDING_GOAL_EITHER,
)

DEFAULT_SEEDING_RATIO = 1.0
DEFAULT_SEEDING_TIME_MINUTES = 60
MIN_SEEDING_RATIO = 0.1
MAX_SEEDING_RATIO = 1000.0
MIN_SEEDING_TIME_MINUTES = 1
MAX_SEEDING_TIME_MINUTES = 525_600  # one year

# Context-menu component ranges. They are intentionally independent so a user
# can compose, for example, 1 day + 5 hours + 10 minutes.
SEEDING_TIME_COMPONENT_SPECS = (
    ("days", 24 * 60, 31),
    ("hours", 60, 12),
    ("minutes", 1, 60),
)
# Backward-compatible alias retained for code/tests written during the first
# quick-menu iteration.
SEEDING_TIME_PRESET_SPECS = SEEDING_TIME_COMPONENT_SPECS


def seeding_goal_uses_time(mode: object) -> bool:
    value = normalise_seeding_goal_mode(mode)
    return value in {SEEDING_GOAL_TIME, SEEDING_GOAL_EITHER}


def seeding_time_preset_minutes(unit: object, value: object) -> int:
    """Return the minute contribution represented by one quick-menu component."""

    unit_text = str(unit or "").strip().lower()
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Seeding-time component value must be an integer") from exc

    for name, multiplier, maximum in SEEDING_TIME_COMPONENT_SPECS:
        if unit_text != name:
            continue
        if not 1 <= count <= maximum:
            raise ValueError(
                f"Seeding-time {name} component must be between 1 and {maximum}"
            )
        return count * multiplier
    raise ValueError(f"Unsupported seeding-time component unit: {unit_text!r}")


def normalise_seeding_time_component(unit: object, value: object) -> int:
    """Normalize one Days/Hours/Minutes component, allowing zero as 'not set'."""

    unit_text = str(unit or "").strip().lower()
    maximum = None
    for name, _multiplier, candidate_maximum in SEEDING_TIME_COMPONENT_SPECS:
        if name == unit_text:
            maximum = candidate_maximum
            break
    if maximum is None:
        raise ValueError(f"Unsupported seeding-time component unit: {unit_text!r}")
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = 0
    return max(0, min(maximum, numeric))


def seeding_time_components_to_minutes(
    days: object,
    hours: object,
    minutes: object,
) -> int:
    """Return the additive duration represented by the three quick components."""

    values = {
        "days": normalise_seeding_time_component("days", days),
        "hours": normalise_seeding_time_component("hours", hours),
        "minutes": normalise_seeding_time_component("minutes", minutes),
    }
    return sum(
        values[name] * multiplier
        for name, multiplier, _maximum in SEEDING_TIME_COMPONENT_SPECS
    )


def seeding_time_components_from_minutes(total_minutes: object) -> tuple[int, int, int] | None:
    """Represent an exact minute target as Days/Hours/Minutes when possible.

    The quick tree intentionally caps its three branches at 31 days, 12 hours,
    and 60 minutes. Targets outside that representable set remain fully valid
    through Configure Targets and simply have no numeric quick-menu checkmarks.
    """

    total = normalise_seeding_time_minutes(total_minutes)
    day_max = SEEDING_TIME_COMPONENT_SPECS[0][2]
    hour_max = SEEDING_TIME_COMPONENT_SPECS[1][2]
    minute_max = SEEDING_TIME_COMPONENT_SPECS[2][2]

    for days in range(min(day_max, total // 1440), -1, -1):
        after_days = total - days * 1440
        for hours in range(min(hour_max, after_days // 60), -1, -1):
            minutes = after_days - hours * 60
            if 0 <= minutes <= minute_max:
                return days, hours, minutes
    return None




def seeding_time_parts_to_minutes(days: object, hours: object, minutes: object) -> int:
    """Convert an editor/display Days/Hours/Minutes tuple into bounded minutes.

    Unlike the quick-menu components, editor fields are canonical time parts:
    hours are 0-23 and minutes are 0-59. The resulting duration is still
    clamped by the application's one-year seeding-time ceiling.
    """

    def _non_negative_int(value: object) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    total = (
        _non_negative_int(days) * 24 * 60
        + min(23, _non_negative_int(hours)) * 60
        + min(59, _non_negative_int(minutes))
    )
    return normalise_seeding_time_minutes(total)


def seeding_time_parts_from_minutes(total_minutes: object) -> tuple[int, int, int]:
    """Return canonical Days/Hours/Minutes parts for editors and display."""

    total = normalise_seeding_time_minutes(total_minutes)
    days, remainder = divmod(total, 24 * 60)
    hours, minutes = divmod(remainder, 60)
    return int(days), int(hours), int(minutes)

def seeding_time_preset_selection(total_minutes: object) -> tuple[str, int] | None:
    """Return a canonical single-branch representation when one exists.

    Kept for compatibility with the first quick-menu implementation. New UI
    code uses the additive three-component representation instead.
    """

    minutes = normalise_seeding_time_minutes(total_minutes)
    for name, multiplier, maximum in SEEDING_TIME_COMPONENT_SPECS:
        if minutes % multiplier:
            continue
        count = minutes // multiplier
        if 1 <= count <= maximum:
            return name, count
    return None


@dataclass(frozen=True)
class SeedingGoalStatus:
    """One evaluation of a torrent's configured seeding goal."""

    reached: bool
    reason: str
    ratio_reached: bool
    time_reached: bool
    current_ratio: float
    # Elapsed time for the *current timed goal instance*, not lifetime seed time.
    elapsed_seconds: float
    total_elapsed_seconds: float
    remaining_ratio: float | None
    remaining_seconds: float | None


def normalise_seeding_goal_mode(value: object) -> str:
    text = str(value or SEEDING_GOAL_FOREVER).strip()
    return text if text in SEEDING_GOAL_MODES else SEEDING_GOAL_FOREVER


def normalise_seeding_ratio(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = DEFAULT_SEEDING_RATIO
    return max(MIN_SEEDING_RATIO, min(MAX_SEEDING_RATIO, numeric))


def normalise_seeding_time_minutes(value: object) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = DEFAULT_SEEDING_TIME_MINUTES
    return max(MIN_SEEDING_TIME_MINUTES, min(MAX_SEEDING_TIME_MINUTES, numeric))


def evaluate_seeding_goal(
    mode: object,
    ratio_limit: object,
    time_limit_minutes: object,
    *,
    uploaded_bytes: object,
    payload_bytes: object,
    elapsed_seconds: object,
    time_baseline_seconds: object = 0.0,
) -> SeedingGoalStatus:
    """Evaluate a normalized seeding policy without causing side effects.

    ``elapsed_seconds`` is lifetime/cumulative seeding time for the torrent.
    ``time_baseline_seconds`` snapshots that counter when the current timed goal
    is applied. Automatic stop therefore behaves as users expect: "seed for
    this long starting now" rather than comparing against historical seed time.
    """

    mode_value = normalise_seeding_goal_mode(mode)
    ratio_target = normalise_seeding_ratio(ratio_limit)
    time_target_minutes = normalise_seeding_time_minutes(time_limit_minutes)

    try:
        uploaded = max(0, int(uploaded_bytes or 0))
    except (TypeError, ValueError):
        uploaded = 0
    try:
        payload = max(0, int(payload_bytes or 0))
    except (TypeError, ValueError):
        payload = 0
    try:
        total_elapsed = max(0.0, float(elapsed_seconds or 0.0))
    except (TypeError, ValueError):
        total_elapsed = 0.0
    try:
        baseline = max(0.0, float(time_baseline_seconds or 0.0))
    except (TypeError, ValueError):
        baseline = 0.0
    baseline = min(baseline, total_elapsed)
    goal_elapsed = max(0.0, total_elapsed - baseline)

    current_ratio = (uploaded / payload) if payload > 0 else 0.0
    ratio_reached = current_ratio >= ratio_target
    time_target_seconds = float(time_target_minutes * 60)
    time_reached = goal_elapsed >= time_target_seconds

    if mode_value == SEEDING_GOAL_FOREVER:
        reached = False
        reason = ""
    elif mode_value == SEEDING_GOAL_RATIO:
        reached = ratio_reached
        reason = "ratio" if reached else ""
    elif mode_value == SEEDING_GOAL_TIME:
        reached = time_reached
        reason = "time" if reached else ""
    else:
        reached = ratio_reached or time_reached
        if ratio_reached and time_reached:
            reason = "ratio_and_time"
        elif ratio_reached:
            reason = "ratio"
        elif time_reached:
            reason = "time"
        else:
            reason = ""

    return SeedingGoalStatus(
        reached=reached,
        reason=reason,
        ratio_reached=ratio_reached,
        time_reached=time_reached,
        current_ratio=current_ratio,
        elapsed_seconds=goal_elapsed,
        total_elapsed_seconds=total_elapsed,
        remaining_ratio=(
            max(0.0, ratio_target - current_ratio)
            if mode_value in {SEEDING_GOAL_RATIO, SEEDING_GOAL_EITHER}
            else None
        ),
        remaining_seconds=(
            max(0.0, time_target_seconds - goal_elapsed)
            if mode_value in {SEEDING_GOAL_TIME, SEEDING_GOAL_EITHER}
            else None
        ),
    )
