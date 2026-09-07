"""Reusable failure reporting with duplicate-rate suppression."""

from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Callable


class ExceptionReporter:
    """Report exceptions to stderr/stdout and an optional append-only log file.

    Repeated identical failures may be throttled so one broken update path does
    not emit the same traceback every frame.  Time and output functions are
    injectable for deterministic tests and non-console hosts.
    """

    def __init__(
        self,
        *,
        log_path: Path | None = None,
        prefix: str = "[Application Error]",
        throttle_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        output: Callable[[str], object] = print,
    ):
        self.log_path = Path(log_path) if log_path is not None else None
        self.prefix = str(prefix)
        self.throttle_seconds = max(0.0, float(throttle_seconds))
        self._clock = clock
        self._wall_clock = wall_clock
        self._output = output
        self._last_signature: tuple[str, str, str] | None = None
        self._last_at = float("-inf")

    def report(self, context: str, exc: BaseException) -> bool:
        now = float(self._clock())
        label = str(context or "runtime")
        signature = (label, type(exc).__name__, str(exc))
        if (
            signature == self._last_signature
            and now - self._last_at < self.throttle_seconds
        ):
            return False

        self._last_signature = signature
        self._last_at = now
        rendered = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        self._output(f"{self.prefix} {label}: {exc}\n{rendered}")

        if self.log_path is not None:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(self._wall_clock()),
                )
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        f"\n[{stamp}] {label}: {type(exc).__name__}: {exc}\n"
                    )
                    handle.write(rendered)
            except OSError:
                pass
        return True
