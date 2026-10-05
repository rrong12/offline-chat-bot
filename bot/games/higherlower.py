"""Higher or Lower, a personal streak game on monthly English Wikipedia page views."""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from bot.assets import Assets
from bot.connectors.base import ChatMessage
from bot.games.base import Game, Outcome
from bot.text import normalize, short_number

MIN_RATIO = 1.15  # the two numbers in a pair differ by at least 15%, so a guess is never a coin flip
WIN_STREAK = 5  # a streak this long counts as a win in ?gamestats
HIGHER = {"higher", "h", "more"}
LOWER = {"lower", "l", "less"}


class HigherLower(Game):
    name = "higherlower"
    title = "Higher or Lower"
    usage = "{p}higherlower"
    aliases = ("hl",)
    description = (
        "Does the next thing get more or fewer monthly Wikipedia views? Answer {p}g higher or {p}g lower. "
        "Each right answer is 1 point and resets the timer; one wrong answer ends your streak."
    )
    time_limit = 20
    commands = {"g": ("{p}g higher|lower", "Answer in your Higher or Lower game.")}

    def __init__(
        self,
        category: str | None,
        rng: random.Random,
        assets: Assets,
        *,
        level: str | None = None,
        avoid: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(category, rng, assets, level=level, avoid=avoid)
        self.terms: list[dict[str, Any]] = assets.json("higherlower")["terms"]
        self.used: set[str] = set()
        self.streak = 0
        self.player_id = ""  # set by the first answer; a streak above 0 always has one
        self._told_how = False
        for _ in range(20):  # nearly every term has a partner; retry the rare one that doesn't
            self.current = self._pick(rng.choice(self.terms))
            self.next = self._partner()
            if self.next is not None:
                break
        else:
            raise ValueError("no Higher or Lower pair found")

    def _pick(self, term: dict[str, Any]) -> dict[str, Any]:
        self.used.add(term["name"])
        return term

    def _partner(self) -> dict[str, Any] | None:
        base = self.current["views"]
        options = [
            t for t in self.terms
            if t["name"] not in self.used and max(t["views"], base) >= MIN_RATIO * min(t["views"], base)
        ]
        return self._pick(self.rng.choice(options)) if options else None

    def _question(self) -> str:
        assert self.next is not None
        return f"Does {self.next['name']} get higher or lower?"

    def start(self) -> str:
        views = short_number(self.current["views"])
        return (
            f"↕️ {self.current['name']} gets {views} monthly Wikipedia views. {self._question()} "
            f"· {self.time_limit}s · {{p}}g higher / {{p}}g lower"
        )

    def _result(self) -> str:
        assert self.next is not None
        return f"{self.next['name']}: {short_number(self.next['views'])}"

    def _end(self, text: str, result: str) -> Outcome:
        awards = {self.player_id: self.streak} if self.streak else {}
        winners = {self.player_id} if self.streak >= WIN_STREAK else set()
        return Outcome(messages=[text], awards=awards, winners=winners, finished=True, result=result)

    def on_command(self, name: str, args: str, msg: ChatMessage, now: datetime) -> Outcome | None:
        guess = normalize(args)
        if name != "g" or not guess:
            return None
        self.player_id = msg.user_id
        if guess not in HIGHER | LOWER:
            if self._told_how:
                return None
            self._told_how = True
            return Outcome(messages=["Answer with {p}g higher or {p}g lower."])
        assert self.next is not None
        before, after = self.current["views"], self.next["views"]
        right = after >= before if guess in HIGHER else after <= before
        if not right:
            return self._end(f"❌ {self._result()}. Game over, streak {self.streak} (+{self.streak})", "lost")
        self.streak += 1
        revealed = self._result()
        self.current = self.next
        self.next = self._partner()
        if self.next is None:
            return self._end(f"🏆 {revealed}. You used up every term! Streak {self.streak} (+{self.streak})", "won")
        return Outcome(
            messages=[f"✅ {revealed}. Streak {self.streak}. {self._question()} · {self.time_limit}s"],
            restart_timer=True,
        )

    def on_timeout(self) -> Outcome:
        return self._end(f"⏰ Time's up! {self._result()}. Streak {self.streak} (+{self.streak})", "timeout")

    def reveal(self) -> str:
        return self._result()
