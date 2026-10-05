"""Hangman, a personal game: guess with ?g <letter> or ?g <answer>. Plain chat never counts."""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import datetime

from bot.assets import Assets
from bot.connectors.base import ChatMessage
from bot.games.base import Game, Outcome
from bot.text import normalize

_ALLOWED_PUNCT = " -'"


def _valid(entry: str) -> bool:
    letters = sum(ch.isalpha() for ch in entry)
    return (
        entry.isascii()
        and letters >= 3
        and len(entry) <= 30
        and all(ch.isalpha() or ch in _ALLOWED_PUNCT for ch in entry)
    )


def _compact(text: str) -> str:
    return normalize(text).replace(" ", "")


class Hangman(Game):
    name = "hangman"
    title = "Hangman"
    usage = "{p}hangman [category]"
    description = (
        "Your own hidden word: guess with {p}g <letter> or {p}g <answer>. 6 wrong letters and you lose. "
        "Win to score 10 points plus 1 per correct letter. {p}hangman categories lists topics. "
        "{p}skip ends your game."
    )
    time_limit = 120
    LIVES = 6
    GUESS_COOLDOWN = 2.0
    WIN_POINTS = 10
    commands = {"g": ("{p}g <letter|answer>", "Guess a letter or the whole answer in your Hangman game.")}

    @classmethod
    def category_names(cls, assets: Assets) -> list[str]:
        return [c for c in assets.categories() if any(_valid(w) for w in assets.words(c))]

    def __init__(self, category: str | None, rng: random.Random, assets: Assets) -> None:
        super().__init__(category, rng, assets)
        assert category is not None
        self.answer = rng.choice([w for w in assets.words(category) if _valid(w)]).upper()
        self.guessed: set[str] = set()
        self.wrong: list[str] = []
        self.held: defaultdict[str, int] = defaultdict(int)  # user_id -> letter points
        self._last_guess: dict[str, datetime] = {}

    def board(self) -> str:
        cells = []
        for ch in self.answer:
            if ch == " ":
                cells.append("/")
            elif ch.isalpha():
                cells.append(ch if ch in self.guessed else "_")
            else:
                cells.append(ch)
        return " ".join(cells)

    def status(self) -> str:
        wrong = " ".join(sorted(self.wrong)) or "-"  # sorted, so guess order can't spell a word
        return f"{self.board()} | wrong: {wrong} ({len(self.wrong)}/{self.LIVES})"

    def _hidden(self) -> set[str]:
        return {ch for ch in self.answer if ch.isalpha()} - self.guessed

    def start(self) -> str:
        return (
            f"🪢 Hangman ({self.category}): {self.board()} · guess with {{p}}g <letter> or "
            f"{{p}}g <answer> · {self.LIVES} lives, {self.time_limit}s"
        )

    def on_command(self, name: str, args: str, msg: ChatMessage, now: datetime) -> Outcome | None:
        guess = normalize(args)
        if name != "g" or not guess:
            return None
        last = self._last_guess.get(msg.user_id)
        if last is not None and (now - last).total_seconds() < self.GUESS_COOLDOWN:
            return None
        if len(guess) == 1:
            letter = guess.upper()
            if not ("A" <= letter <= "Z") or letter in self.guessed or letter in self.wrong:
                return None
            self._last_guess[msg.user_id] = now
            return self._guess_letter(letter, msg)
        self._last_guess[msg.user_id] = now
        if _compact(guess) == _compact(self.answer):
            return self._win(msg)
        return Outcome(messages=["❌ Not it."])  # a wrong solve attempt costs no lives

    def _guess_letter(self, letter: str, msg: ChatMessage) -> Outcome:
        if letter in self.answer:
            self.guessed.add(letter)
            self.held[msg.user_id] += 1
            if not self._hidden():
                return self._win(msg)
            return Outcome(messages=[self.status()], coalesce_key="hangman-board")
        self.wrong.append(letter)
        if len(self.wrong) >= self.LIVES:
            return Outcome(
                messages=[f"💀 Out of lives! The word was {self.answer}."], finished=True, result="lost"
            )
        return Outcome(messages=[self.status()], coalesce_key="hangman-board")

    def _win(self, msg: ChatMessage) -> Outcome:
        awards = dict(self.held)
        awards[msg.user_id] = awards.get(msg.user_id, 0) + self.WIN_POINTS
        return Outcome(
            messages=[f"🎉 {msg.display_name} solved it: {self.answer} (+{awards[msg.user_id]})"],
            awards=awards,
            winners={msg.user_id},
            finished=True,
            result="won",
        )

    def on_timeout(self) -> Outcome:
        return Outcome(messages=[f"💀 Time's up! The word was {self.answer}."], finished=True, result="timeout")

    def reveal(self) -> str:
        return self.answer
