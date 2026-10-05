"""Riddle, a personal game: 3 guesses with ?g, a written clue and then a letter hint."""

from __future__ import annotations

import hashlib
import random
import re
import unicodedata
from datetime import datetime
from functools import cache
from typing import Any

from bot.assets import Assets
from bot.connectors.base import ChatMessage
from bot.games.base import Game, Outcome
from bot.text import fold_accents, normalize, strip_article

EXTRA_WORDS = 2  # besides filler words, a guess may hold this many words beyond the answer
# Apostrophes are removed, not spaced, so "I'm" can't leave a lone "m" (checked after NFKC folds fullwidth ones).
_APOSTROPHES = re.compile("['\u2018\u2019\u201b`\u00b4\u02bc]")
# Words that don't count toward a guess's length: "I think it's a clock" is one answer, "map towel clock" a list.
FILLER = frozenset(
    "i im ive id think thinking guess guessing maybe probably perhaps definitely surely its it is was be been "
    "could would might will a an the my your our answer because cause cuz so um uh hmm lol lmao going gonna "
    "to say said that thats this he she they you we of in on at for and or not no do does dont doesnt cant cannot "
    "isnt wont didnt letter".split()
)
NEGATIONS = frozenset("not no never isnt neither nor".split())  # "not a clock" doesn't name the clock
NUMBER_WORDS = frozenset(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand".split()
)
_PLURAL_ES = ("s", "x", "z", "ch", "sh")  # not "o": "sho" must not match "shoes"


def riddle_id(entry: dict[str, Any]) -> str:
    return _text_id(entry["riddle"])


@cache  # one shared string per riddle, so remembered ids don't pile up copies
def _text_id(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:10]


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}{'es' if word.endswith('s') else 's'}"


def _same_word(guess: str, answer: str) -> bool:
    """Equal, or a plural of the other: clock/clocks, match/matches (but not pin/pines)."""
    if guess == answer:
        return True
    for longer, shorter in ((guess, answer), (answer, guess)):
        if longer == shorter + "s" or (longer == shorter + "es" and shorter.endswith(_PLURAL_ES)):
            return True
    return False


def _words(text: str) -> list[str]:
    """A guess or answer as comparable words: apostrophes and a leading article dropped, accents folded."""
    text = _APOSTROPHES.sub("", unicodedata.normalize("NFKC", text))
    return fold_accents(normalize(strip_article(text))).split()


def _numbers(words: list[str]) -> set[str]:
    return {w for w in words if w.isdigit() or w in NUMBER_WORDS}


def _content(words: list[str], context: list[str] = ()) -> int:
    """How many words could be an answer: not filler, and not a word from the riddle itself."""
    return sum(w not in FILLER and not any(_same_word(w, c) for c in context) for w in words)


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
        recent: tuple[str, ...] = (),
    ) -> None:
        super().__init__(category, rng, assets, level=level, recent=recent)
        riddles: list[dict[str, Any]] = assets.json("riddles")
        entry = self.pick_unseen(riddles, riddle_id)
        self.item_id = riddle_id(entry)
        self.riddle: str = entry["riddle"]
        self.answers: list[str] = entry["answers"]
        self.clue: str = entry["clue"]
        self._accepted = [_words(a) for a in self.answers]
        self._context = _words(self.riddle)  # "roosters don't lay eggs" reuses the riddle's words: not a list
        # a guess naming a different number ("3-2=1" when the answer is 2) is wrong even if it contains the answer
        self._answer_numbers = set().union(*(_numbers(a) for a in self._accepted))
        self.guesses_left = self.GUESSES
        self.hints_used = 0

    def start(self) -> str:
        return f"🧩 {self.riddle} · {self.time_limit}s · {{p}}g <answer> · {{p}}hint"

    def _match(self, words: list[str]) -> tuple[list[str], int] | None:
        """The longest accepted answer the guess contains as whole words, and where it starts; None if none.
        Spacing may differ by one word ("rain bow", "tea pot"), and the answer may be plural."""
        found: tuple[list[str], int] | None = None
        for answer in self._accepted:
            joined = "".join(answer)
            for size in sorted({len(answer) - 1, len(answer), len(answer) + 1} - {0}):
                for i in range(len(words) - size + 1):
                    if _same_word("".join(words[i : i + size]), joined) and (
                        found is None or _content(answer) > _content(found[0])
                    ):
                        found = (answer, i)
        return found

    def _is_answer(self, words: list[str]) -> tuple[bool, bool]:
        """(right, a list): does the guess name the answer, and is it really several guesses at once?"""
        found = self._match(words)
        if found is None:
            return False, False
        answer, start = found
        letter = len(answer) == 1 and len(answer[0]) == 1 and answer[0].isalpha()  # the M, E and W riddles
        extra = 0 if letter or "or" in words else EXTRA_WORDS
        if _content(words, self._context) > max(1, _content(answer)) + extra:
            return False, True
        before = [w for w in words[:start] if w not in ("a", "an", "the")]
        if before and before[-1] in NEGATIONS:
            return False, False
        if _numbers(words) - self._answer_numbers:  # "3-2=1" names another number
            return False, False
        if letter and any(self._other_letter(words, i, answer[0]) for i in range(len(words))):
            return False, True  # "a, e, i" or "y e a r" hedges between letters
        return True, False

    @staticmethod
    def _other_letter(words: list[str], i: int, answer: str) -> bool:
        """Is words[i] a single letter other than the answer? "I" opening a sentence and "a" right before
        the answer ("is it a m") don't count."""
        w = words[i]
        if len(w) != 1 or not w.isalpha() or w == answer:
            return False
        if (w == "i" and i == 0) or (w == "a" and i + 1 < len(words) and len(words[i + 1]) == 1):
            return False
        return True

    def on_command(self, name: str, args: str, msg: ChatMessage, now: datetime) -> Outcome | None:
        if name == "hint":
            return self._hint()
        words = _words(args)
        if name != "g" or not words:
            return None
        right, too_long = self._is_answer(words)
        if right:
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
        # for a one- or two-letter answer, "starts with M" would give it away
        start = f", starts with {letters[0].upper()}" if len(letters) > 2 else ""
        return Outcome(messages=[f"💡 {prefix}{_plural(len(letters), 'letter')}{start}"])

    def on_timeout(self) -> Outcome:
        return Outcome(messages=[f"⏰ Time's up! It was: {self.answers[0]}."], finished=True, result="timeout")

    def reveal(self) -> str:
        return self.answers[0]
