"""Backend-neutral rolling telemetry primitives.

These contracts deliberately contain no rendering, application, or backend
knowledge.  They are suitable for desktop, CLI, headless, and future designer
consumers that need bounded realtime measurements and simple recent statistics.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping


Number = int | float


def _series_name(value: object) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("telemetry series names must be non-empty")
    return name


def _finite_number(value: object, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


@dataclass(frozen=True)
class TelemetrySample:
    """One timestamped measurement across a fixed ordered series set."""

    timestamp: float
    values: tuple[float, ...]


@dataclass(frozen=True)
class SeriesStatistics:
    """Simple statistics for one visible telemetry series."""

    current: float = 0.0
    average: float = 0.0
    peak: float = 0.0
    minimum: float = 0.0
    sample_count: int = 0


@dataclass(frozen=True)
class TelemetryWindow:
    """Immutable view of recent samples captured at one point in time."""

    captured_at: float
    series_names: tuple[str, ...]
    samples: tuple[TelemetrySample, ...]

    def _series_index(self, name: str) -> int:
        try:
            return self.series_names.index(_series_name(name))
        except ValueError as exc:
            raise KeyError(name) from exc

    def values(self, name: str) -> tuple[float, ...]:
        index = self._series_index(name)
        return tuple(sample.values[index] for sample in self.samples)

    def statistics(self, name: str) -> SeriesStatistics:
        values = self.values(name)
        if not values:
            return SeriesStatistics()
        return SeriesStatistics(
            current=values[-1],
            average=sum(values) / len(values),
            peak=max(values),
            minimum=min(values),
            sample_count=len(values),
        )

    def aged_rows(self) -> tuple[tuple[float, tuple[float, ...]], ...]:
        """Return ``(age_seconds, values)`` rows in stored sample order."""

        return tuple(
            (max(0.0, self.captured_at - sample.timestamp), sample.values)
            for sample in self.samples
        )


class RollingTelemetry:
    """Bounded multi-series rolling history with explicit snapshot semantics."""

    def __init__(
        self,
        series_names: Iterable[str],
        *,
        history_seconds: Number,
        sample_interval_seconds: Number | None = None,
        max_samples: int | None = None,
        clock: Callable[[], float] | None = None,
    ):
        names = tuple(_series_name(name) for name in series_names)
        if not names:
            raise ValueError("rolling telemetry requires at least one series")
        if len(set(names)) != len(names):
            raise ValueError("rolling telemetry series names must be unique")

        history = _finite_number(history_seconds, field="history_seconds")
        if history <= 0.0:
            raise ValueError("history_seconds must be greater than zero")

        interval = None
        if sample_interval_seconds is not None:
            interval = _finite_number(
                sample_interval_seconds,
                field="sample_interval_seconds",
            )
            if interval <= 0.0:
                raise ValueError("sample_interval_seconds must be greater than zero")

        if max_samples is None:
            if interval is None:
                raise ValueError(
                    "max_samples is required when sample_interval_seconds is omitted"
                )
            max_samples = int(math.ceil(history / interval)) + 8
        try:
            bounded_samples = int(max_samples)
        except (TypeError, ValueError) as exc:
            raise TypeError("max_samples must be an integer") from exc
        if bounded_samples <= 0:
            raise ValueError("max_samples must be greater than zero")

        self.series_names = names
        self.history_seconds = history
        self.sample_interval_seconds = interval
        self.max_samples = bounded_samples
        self._clock = clock or time.monotonic
        self._samples: deque[TelemetrySample] = deque(maxlen=bounded_samples)

    def __len__(self) -> int:
        return len(self._samples)

    def clear(self) -> None:
        self._samples.clear()

    def record(
        self,
        values: Mapping[str, object],
        *,
        timestamp: Number | None = None,
    ) -> TelemetrySample:
        if not isinstance(values, Mapping):
            raise TypeError("telemetry values must be a mapping")

        supplied = set(values)
        expected = set(self.series_names)
        missing = expected - supplied
        extra = supplied - expected
        if missing or extra:
            details = []
            if missing:
                details.append("missing: " + ", ".join(sorted(missing)))
            if extra:
                details.append("unexpected: " + ", ".join(sorted(extra)))
            raise ValueError("telemetry sample series mismatch (" + "; ".join(details) + ")")

        measured_at = self._clock() if timestamp is None else _finite_number(
            timestamp,
            field="timestamp",
        )
        measured_at = _finite_number(measured_at, field="timestamp")
        ordered_values = tuple(
            _finite_number(values[name], field=f"telemetry value {name!r}")
            for name in self.series_names
        )
        sample = TelemetrySample(measured_at, ordered_values)
        self._samples.append(sample)
        return sample

    def snapshot(
        self,
        *,
        now: Number | None = None,
        window_seconds: Number | None = None,
    ) -> TelemetryWindow:
        captured_at = self._clock() if now is None else _finite_number(now, field="now")
        captured_at = _finite_number(captured_at, field="now")

        visible_window = self.history_seconds
        if window_seconds is not None:
            visible_window = _finite_number(window_seconds, field="window_seconds")
            if visible_window <= 0.0:
                raise ValueError("window_seconds must be greater than zero")
            visible_window = min(self.history_seconds, visible_window)

        cutoff = captured_at - visible_window
        samples = tuple(sample for sample in self._samples if sample.timestamp >= cutoff)
        return TelemetryWindow(
            captured_at=captured_at,
            series_names=self.series_names,
            samples=samples,
        )
