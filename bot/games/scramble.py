"""Scramble: unscramble a word. First exact answer wins; hints lower the points."""

from __future__ import annotations

import codecs
import logging
import math
import random
from datetime import datetime

from bot.assets import Assets
from bot.connectors.base import ChatMessage
from bot.games.base import Game, Outcome
from bot.text import normalize

logger = logging.getLogger(__name__)

MAX_SHUFFLES = 200


def _blocked_fragments(assets: Assets) -> tuple[str, ...]:
    """Words a scramble must never spell by accident (stored ROT13 in content/blocked_rot13.txt)."""
    try:
        return tuple(codecs.decode(line, "rot13").upper() for line in assets.lines("blocked_rot13"))
    except FileNotFoundError:
        logger.warning("content/blocked_rot13.txt is missing: scrambles are not being filtered")
        return ()


def _valid(entry: str) -> bool:
    # Needs two distinct letters, or no scramble can differ from the word ("aaaa").
    return entry.isascii() and entry.isalpha() and 4 <= len(entry) <= 10 and len(set(entry.lower())) > 1


class Scramble(Game):
    name = "scramble"
    title = "Scramble"
    usage = "{p}scramble [category]"
    description = (
        "Your own word to unscramble: 10 points, or 7 or 4 if you take hints with {p}hint. "
        "{p}scramble categories lists topics. {p}skip ends your game."
    )
    time_limit = 45
    POINTS = (10, 7, 4)
    commands = {"hint": ("{p}hint", "Get a hint in your Scramble game (fewer points).")}

    @classmethod
    def category_names(cls, assets: Assets) -> list[str]:
        return [c for c in assets.categories() if any(_valid(w) for w in assets.words(c))]

    def __init__(self, category: str | None, rng: random.Random, assets: Assets) -> None:
        super().__init__(category, rng, assets)
        assert category is not None
        blocked = _blocked_fragments(assets)
        candidates = [w.upper() for w in assets.words(category) if _valid(w)]
        rng.shuffle(candidates)
        for word in candidates:  # almost always the first word works
            scrambled = self._scramble(word, blocked)
            if scrambled is not None:
                self.word, self.scrambled = word, scrambled
                break
        else:
            raise ValueError(f"no word in {category!r} can be scrambled cleanly")
        # Any word from this category that uses exactly the same letters is also a right answer
        # (e.g. UNDERTALE and DELTARUNE), since the scramble fits both.
        letters = sorted(self.word)
        self._answers = {w.lower() for w in candidates if sorted(w) == letters}
        self.hints_shown = 0
        middle = list(range(1, len(self.word) - 1))
        rng.shuffle(middle)
        self._reveal_order = middle

    def _scramble(self, word: str, blocked: tuple[str, ...]) -> str | None:
        """A shuffle that differs from the word and spells none of the blocked fragments, or None."""
        letters = list(word)
        for _ in range(MAX_SHUFFLES):
            self.rng.shuffle(letters)
            candidate = "".join(letters)
            if candidate != word and not any(fragment in candidate for fragment in blocked):
                return candidate
        return None

    def start(self) -> str:
        return f"🔤 Unscramble ({self.category}): {self.scrambled} · {self.time_limit}s · {{p}}hint for a hint"

    def _hint(self) -> str:
        shown = {0, len(self.word) - 1}
        if self.hints_shown >= 2:
            middle = max(1, math.ceil(len(self.word) / 2) - 2)  # about half the word in total
            shown |= set(self._reveal_order[:middle])
        return " ".join(ch if i in shown else "_" for i, ch in enumerate(self.word))

    def on_message(self, msg: ChatMessage, now: datetime) -> Outcome | None:
        guess = normalize(msg.text)
        if " " in guess or len(guess) != len(self.word):
            return None
        if guess not in self._answers:
            return Outcome()
        points = self.POINTS[self.hints_shown]
        return Outcome(
            messages=[f"✅ {msg.display_name} got it: {guess.upper()} (+{points})"],
            awards={msg.user_id: points},
            winners={msg.user_id},
            finished=True,
            result="won",
        )

    def on_command(self, name: str, args: str, msg: ChatMessage, now: datetime) -> Outcome | None:
        if name != "hint" or self.hints_shown >= len(self.POINTS) - 1:
            return None
        self.hints_shown += 1
        return Outcome(messages=[f"💡 Hint: {self._hint()}"])

    def on_timeout(self) -> Outcome:
        return Outcome(messages=[f"⏰ Time's up! It was {self.word}."], finished=True, result="timeout")

    def reveal(self) -> str:
        return self.word
