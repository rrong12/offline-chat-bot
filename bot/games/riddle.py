"""Riddle, a personal game: 3 guesses with ?g, a written clue and then a letter hint."""

from __future__ import annotations

import hashlib
import random
import re
from datetime import datetime
from typing import Any

from bot.assets import Assets
from bot.connectors.base import ChatMessage
from bot.games.base import Game, Outcome
from bot.text import normalize, strip_article

EXTRA_WORDS = 3  # a guess may wrap the answer in this many extra words ("is it a clock")
_APOSTROPHES = re.compile("['\u2019]")  # removed, not spaced: "I'm" must not leave a lone "m"


def riddle_id(entry: dict[str, Any]) -> str:
    return hashlib.sha1(entry["riddle"].encode()).hexdigest()[:10]


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}{'es' if word.endswith('s') else 's'}"


def _same_word(guess: str, answer: str) -> bool:
    """Equal, or one is the other plus "s"/"es" (clock/clocks, match/matches)."""
    return guess == answer or guess in (answer + "s", answer + "es") or answer in (guess + "s", guess + "es")


class Riddle(Game):
    name = "riddle"
    title = "Riddle"
    usage = "{p}riddle"
    description = (
        "Your own riddle: answer with {p}g <answer>, 3 guesses. {p}hint gives a clue, then the letter count "
        "(10 points, or 7 or 4 with hints). {p}skip ends your game."
    )
    time_limit = 60
    GUESSES = 3
    POINTS = (10, 7, 4)
    commands = {
        "g": ("{p}g <answer>", "Answer your riddle."),
        "hint": ("{p}hint", "Get a hint for your riddle (fewer points)."),
    }

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
        riddles: list[dict[str, Any]] = assets.json("riddles")
        fresh = [r for r in riddles if riddle_id(r) not in avoid] or riddles
        entry = rng.choice(fresh)
        self.item_id = riddle_id(entry)
        self.riddle: str = entry["riddle"]
        self.answers: list[str] = entry["answers"]
        self.clue: str = entry["clue"]
        self._accepted = [normalize(a).split() for a in self.answers]
        self._max_words = max(len(a) for a in self._accepted) + EXTRA_WORDS
        self.guesses_left = self.GUESSES
        self.hints_used = 0

    def start(self) -> str:
        return f"🧩 {self.riddle} · {self.time_limit}s · {{p}}g <answer> · {{p}}hint"

    def _matches(self, words: list[str]) -> bool:
        for answer in self._accepted:
            n = len(answer)
            for i in range(len(words) - n + 1):
                window = words[i : i + n]
                if window[:-1] == answer[:-1] and _same_word(window[-1], answer[-1]):
                    return True
        return False

    def on_command(self, name: str, args: str, msg: ChatMessage, now: datetime) -> Outcome | None:
        if name == "hint":
            return self._hint()
        words = strip_article(normalize(_APOSTROPHES.sub("", args))).split()
        if name != "g" or not words:
            return None
        too_long = len(words) > self._max_words  # one answer per guess, not a list of them
        if not too_long and self._matches(words):
            points = self.POINTS[self.hints_used]
            return Outcome(
                messages=[f"✅ {msg.display_name} got it: {self.answers[0]} (+{points})"],
                awards={msg.user_id: points},
                winners={msg.user_id},
                finished=True,
                result="won",
            )
        self.guesses_left -= 1
        if self.guesses_left == 0:
            return Outcome(messages=[f"💀 Out of guesses! It was: {self.answers[0]}."], finished=True, result="lost")
        why = "One answer per guess" if too_long else "Not it"
        return Outcome(messages=[f"❌ {why}, {_plural(self.guesses_left, 'guess')} left."])

    def _hint(self) -> Outcome | None:
        if self.hints_used >= len(self.POINTS) - 1:
            return None
        self.hints_used += 1
        if self.hints_used == 1:
            return Outcome(messages=[f"💡 Clue: {self.clue}"])
        main = self.answers[0]
        letters = [ch for ch in main if ch.isalnum()]
        words = len(main.split())
        prefix = f"{_plural(words, 'word')}, " if words > 1 else ""
        return Outcome(messages=[f"💡 {prefix}{_plural(len(letters), 'letter')}, starts with {letters[0].upper()}"])

    def on_timeout(self) -> Outcome:
        return Outcome(messages=[f"⏰ Time's up! It was: {self.answers[0]}."], finished=True, result="timeout")

    def reveal(self) -> str:
        return self.answers[0]
