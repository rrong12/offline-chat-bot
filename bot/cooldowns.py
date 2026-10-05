"""Per-user and global command cooldowns, measured on the monotonic clock."""

from __future__ import annotations

from collections.abc import Hashable

from bot.clock import Clock

_PRUNE_AT = 10_000


class Cooldowns:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._until: dict[Hashable, float] = {}

    def remaining(self, key: Hashable) -> float:
        return max(0.0, self._until.get(key, 0.0) - self._clock.mono())

    def ready(self, key: Hashable) -> bool:
        return self.remaining(key) == 0.0

    def trigger(self, key: Hashable, seconds: float) -> None:
        if len(self._until) >= _PRUNE_AT:
            now = self._clock.mono()
            self._until = {k: v for k, v in self._until.items() if v > now}
        self._until[key] = self._clock.mono() + seconds

    def check_command(self, command: str, user_id: str, user_seconds: float, global_seconds: float) -> bool:
        """True (and start both cooldowns) if neither the user's nor the global cooldown is running."""
        user_key, global_key = ("user", command, user_id), ("global", command)
        if not (self.ready(user_key) and self.ready(global_key)):
            return False
        self.trigger(user_key, user_seconds)
        self.trigger(global_key, global_seconds)
        return True
