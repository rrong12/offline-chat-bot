"""Append-only JSONL activity log: one file per UTC day, old files pruned."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from bot.clock import Clock

logger = logging.getLogger("bot.activity")
_PREFIX = "activity-"


class ActivityLog:
    def __init__(self, directory: Path, clock: Clock, retention_days: int = 30) -> None:
        self.directory = directory
        self.clock = clock
        self.retention_days = retention_days
        self._last_prune_day: date | None = None
        directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, day: date) -> Path:
        return self.directory / f"{_PREFIX}{day.isoformat()}.jsonl"

    def write(self, event: str, **fields: Any) -> None:
        now = self.clock.now()
        record = {"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "event": event, **fields}
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self.path_for(now.date()).open("a", encoding="utf-8") as fp:
            fp.write(line + "\n")
        logger.info("%s %s", event, json.dumps(fields, ensure_ascii=False, default=str))

    def prune(self) -> int:
        """Delete files older than the retention window. Returns how many were deleted."""
        today = self.clock.now().date()
        cutoff = today - timedelta(days=self.retention_days)
        deleted = 0
        for path in self.directory.glob(f"{_PREFIX}*.jsonl"):
            try:
                day = date.fromisoformat(path.stem.removeprefix(_PREFIX))
            except ValueError:
                continue
            if day < cutoff:
                path.unlink()
                deleted += 1
        self._last_prune_day = today
        return deleted

    def maybe_rollover(self) -> None:
        """Prune once per UTC day; called from the bot's 1-second tick."""
        if self._last_prune_day != self.clock.now().date():
            self.prune()
