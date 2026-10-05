"""Time sources. Real code uses Clock; tests use FakeClock to control time."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone


class Clock:
    def now(self) -> datetime:
        """Current wall-clock time in UTC (for dates, logs, and the database)."""
        return datetime.now(timezone.utc)

    def mono(self) -> float:
        """Monotonic seconds (for timers and rate limits; never jumps backwards)."""
        return time.monotonic()


class FakeClock(Clock):
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
        self._mono = 1000.0

    def now(self) -> datetime:
        return self._now

    def mono(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._mono += seconds
