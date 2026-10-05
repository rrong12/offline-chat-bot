"""Trivia, a personal game. Easy questions are multiple choice (one guess); medium and hard ones
are typed answers with 3 guesses, small typos forgiven, and up to 2 hints."""

from __future__ import annotations

import math
import random
import re
from datetime import datetime
from typing import Any

from bot.assets import Assets
from bot.connectors.base import ChatMessage
from bot.games.base import Game, Outcome
from bot.text import fold_accents, normalize, strip_article, typo_match

LETTERS = "ABCD"
TYPO_MIN_LETTERS = 5  # words this long forgive one typo; shorter words and numbers must be exact
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")


def _questions(assets: Assets) -> list[dict[str, Any]]:
    return assets.json("trivia")["questions"]


def _forms(text: str) -> set[str]:
    """Comparable forms of raw text: normalized and accent-folded, with and without a leading article."""
    return {fold_accents(normalize(t)) for t in (text, strip_article(text))}


def opening(category: str, level: str, question: str, options: list[str], seconds: int) -> str:
    """The message that asks a question (also used by the content test to check every question fits)."""
    head = f"❓ ({category}, {level}) {question}"
    if options:
        labelled = " ".join(f"{LETTERS[i]}) {option}" for i, option in enumerate(options))
        return f"{head} {labelled} · {seconds}s · answer with {{p}}g A-{LETTERS[len(options) - 1]}"
    return f"{head} · {seconds}s · {{p}}g <answer> · {{p}}hint"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}{'es' if word.endswith('s') else 's'}"


class Trivia(Game):
    name = "trivia"
    title = "Trivia"
    usage = "{p}trivia [category] [easy|medium|hard]"
    description = (
        "Your own trivia question. Easy: multiple choice, answer with {p}g A-D (5 points). "
        "Medium and hard: type the answer with {p}g, 3 guesses, {p}hint for help "
        "(10 or 15 points, fewer with hints). {p}trivia categories lists topics."
    )
    time_limit = 30
    EASY_TIME = 20
    GUESSES = 3
    POINTS = {"easy": (5,), "medium": (10, 7, 4), "hard": (15, 10, 6)}
    levels = ("easy", "medium", "hard")
    levels_label = "difficulties"
    commands = {
        "g": ("{p}g <answer>", "Answer your trivia question."),
        "hint": ("{p}hint", "Get a hint for a typed trivia answer (fewer points)."),
    }

    @classmethod
    def category_names(cls, assets: Assets) -> list[str]:
        return sorted({q["category"] for q in _questions(assets)})

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
        in_category = [q for q in _questions(assets) if q["category"] == category]
        if not in_category:
            raise ValueError(f"no trivia questions in {category!r}")
        available = sorted({q["difficulty"] for q in in_category}, key=self.levels.index)
        if level not in available:  # not chosen, or this category has none at that difficulty
            level = rng.choice(available)
        self.level = level
        pool = [q for q in in_category if q["difficulty"] == level]
        fresh = [q for q in pool if q["id"] not in avoid] or pool
        q = rng.choice(fresh)
        self.item_id = q["id"]
        self.question: str = q["question"]
        self.answer: str = q["answer"]
        self.options: list[str] = []
        if level == "easy":
            self.options = [self.answer, *q["wrong"]]
            rng.shuffle(self.options)
            self.time_limit = self.EASY_TIME
        self._accepted = _forms(self.answer) | _forms(_PARENTHETICAL.sub("", self.answer))
        self.guesses_left = self.GUESSES
        self.hints_used = 0
        self._told_how = False  # the "answer with A-D" reminder is sent at most once
        letters = [i for i, ch in enumerate(self.answer) if ch.isalnum()]
        middle = letters[1:-1]
        rng.shuffle(middle)
        self._reveal_order = middle

    @property
    def easy(self) -> bool:
        return self.level == "easy"

    def _labelled(self, index: int) -> str:
        return f"{LETTERS[index]}) {self.options[index]}"

    def start(self) -> str:
        assert self.category is not None and self.level is not None
        return opening(self.category, self.level, self.question, self.options, self.time_limit)

    def _correct_text(self) -> str:
        return self._labelled(self.options.index(self.answer)) if self.easy else self.answer

    def _win(self, msg: ChatMessage) -> Outcome:
        points = self.POINTS[self.level][self.hints_used]
        return Outcome(
            messages=[f"✅ {msg.display_name} got it: {self._correct_text()} (+{points})"],
            awards={msg.user_id: points},
            winners={msg.user_id},
            finished=True,
            result="won",
        )

    def on_command(self, name: str, args: str, msg: ChatMessage, now: datetime) -> Outcome | None:
        if name == "hint":
            return self._hint()
        if name != "g" or not normalize(args):
            return None
        return self._guess_choice(args, msg) if self.easy else self._guess_typed(args, msg)

    def _guess_choice(self, args: str, msg: ChatMessage) -> Outcome | None:
        guess = normalize(args)
        index = LETTERS.lower().find(guess) if len(guess) == 1 else -1
        if index < 0 or index >= len(self.options):
            said = {f.replace(" ", "") for f in _forms(args)}
            index = next((i for i, o in enumerate(self.options) if said & {f.replace(" ", "") for f in _forms(o)}), -1)
        if index < 0:
            if self._told_how:
                return None
            self._told_how = True
            return Outcome(messages=[f"Answer with {{p}}g and a letter, A to {LETTERS[len(self.options) - 1]}."])
        if self.options[index] == self.answer:
            return self._win(msg)
        return Outcome(messages=[f"❌ It was {self._correct_text()}."], finished=True, result="lost")

    def _matches(self, guess: str) -> bool:
        return any(typo_match(g, a, TYPO_MIN_LETTERS) for g in _forms(guess) for a in self._accepted)

    def _guess_typed(self, args: str, msg: ChatMessage) -> Outcome:
        if self._matches(args):
            return self._win(msg)
        self.guesses_left -= 1
        if self.guesses_left == 0:
            return Outcome(messages=[f"💀 Out of guesses! It was {self.answer}."], finished=True, result="lost")
        return Outcome(messages=[f"❌ Not it, {_plural(self.guesses_left, 'guess')} left."])

    def _hint(self) -> Outcome | None:
        if self.easy or self.hints_used >= len(self.POINTS[self.level]) - 1:
            return None
        self.hints_used += 1
        letters = [ch for ch in self.answer if ch.isalnum()]
        if self.hints_used == 1:
            words = len(self.answer.split())
            prefix = f"{_plural(words, 'word')}, " if words > 1 else ""
            return Outcome(messages=[f"💡 {prefix}{_plural(len(letters), 'letter')}, starts with {letters[0].upper()}"])
        alnum = [i for i, ch in enumerate(self.answer) if ch.isalnum()]
        shown = {alnum[0], alnum[-1]} | set(self._reveal_order[: max(0, math.ceil(len(alnum) / 2) - 2)])
        cells = []
        for i, ch in enumerate(self.answer):
            if ch == " ":
                cells.append("/")
            elif not ch.isalnum():
                cells.append(ch)
            else:
                cells.append(ch.upper() if i in shown else "_")
        return Outcome(messages=[f"💡 {' '.join(cells)}"])

    def on_timeout(self) -> Outcome:
        return Outcome(messages=[f"⏰ Time's up! It was {self._correct_text()}."], finished=True, result="timeout")

    def reveal(self) -> str:
        return self._correct_text()
