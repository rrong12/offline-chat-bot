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
_PARENTHETICAL = re.compile(r"\s*\(([^)]*)\)")
_NUMBER_WITH_UNIT = re.compile(r"^\s*(\d[\d,]*)\s*'?s?\s+[A-Za-z][A-Za-z./]*(?:\s+[A-Za-z./]+)?\s*$")  # 88 mph
_DECADE = re.compile(r"^\s*(\d+)'?s\s*$")  # "50's", "1980s"
_ORDINAL = re.compile(r"^(\d+)(?:st|nd|rd|th)$")
_APOSTROPHES = re.compile("['\u2018\u2019`]")  # removed inside words: "Xi'an" is "xian", not the numeral XI
_UNITS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen " \
         "sixteen seventeen eighteen nineteen twenty".split()
_TENS = {w: 10 * n for n, w in enumerate("thirty forty fifty sixty seventy eighty ninety".split(), start=3)}
_ORDINAL_WORDS = "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth " \
                 "fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth".split()
# Same meaning, different spelling: number words, ordinals, Roman numerals II-XX (single letters are too ambiguous).
_CANONICAL = {
    **{w: str(n) for n, w in enumerate(_UNITS)},
    **{w: str(n) for w, n in _TENS.items()},
    **{w: str(n) for n, w in enumerate(_ORDINAL_WORDS, start=1)},
    **{r: str(n) for n, r in enumerate(
        "- - ii iii iv - vi vii viii ix - xi xii xiii xiv xv xvi xvii xviii xix xx".split()) if r != "-"},
    "mt": "mount",
    "st": "saint",
    "ww1": "world war 1", "wwi": "world war 1", "ww2": "world war 2", "wwii": "world war 2",
}
_PHRASES = {"first world war": "world war 1", "second world war": "world war 2"}
_TITLES = frozenset("sir dame count countess professor prof pope officer doctor dr captain lord lady".split())
_PARTICLES = frozenset("van von de del della da di du la le".split())


def _questions(assets: Assets) -> list[dict[str, Any]]:
    return assets.json("trivia")["questions"]


def _canonical(text: str) -> str:
    words = fold_accents(normalize(_APOSTROPHES.sub("", text.replace("&", " and ")))).split()
    joined = " ".join(words)
    for phrase, same in _PHRASES.items():
        joined = joined.replace(phrase, same)
    out: list[str] = []
    for w in " ".join(_CANONICAL.get(w, w) for w in joined.split()).split():
        w = m.group(1) if (m := _ORDINAL.match(w)) else w
        if out and out[-1] in {str(n) for n in _TENS.values()} and w.isdigit() and len(w) == 1 and w != "0":
            out[-1] = str(int(out[-1]) + int(w))  # "fifty seven" -> 57
        else:
            out.append(w)
    return " ".join(out)


def _forms(text: str) -> set[str]:
    """Comparable forms of raw text: with and without a leading article, accents folded, "&" read as
    "and", and numbers, Roman numerals and ordinals written as plain digits ("World War II" = "world war 2")."""
    return {_canonical(t) for t in (text, strip_article(text))} - {""}


def accepted_answers(answer: str, question: str = "") -> set[str]:
    """Every form of a typed answer that counts as right."""
    outside = _PARENTHETICAL.sub("", answer).strip()
    variants = {answer, outside}
    inner = _PARENTHETICAL.search(answer)
    if inner and not re.search(r"[A-Za-z0-9]", outside):  # "Φ (phi)": the bracket is the typeable part
        variants.add(inner.group(1))
    place = re.fullmatch(r"\s*([^,\d]*[A-Za-z]{3}[^,\d]*),\s*((?:the\s+\w|[A-Z])[^,]*)", outside)
    if place:  # "Cupertino, California" -> "Cupertino", "Laika, the dog" -> "Laika"; not "1,776 ft" or lists
        variants.add(place.group(1))
    if (m := _NUMBER_WITH_UNIT.match(outside)) or (m := _DECADE.match(outside)):  # "88 mph" -> "88"
        variants.add(m.group(1).replace(",", ""))
    forms = set().union(*(_forms(v) for v in variants))
    for form in list(forms):
        words = form.split()
        if len(words) >= 3:  # "harry s truman" -> "harry truman" (letters only: "class 3 e" keeps its 3)
            forms.add(" ".join([words[0], *(w for w in words[1:-1] if not (len(w) == 1 and w.isalpha())), words[-1]]))
        if words[:1] == ["mount"] and len(words) > 1:  # "Mt. Everest" -> "everest"
            forms.add(" ".join(words[1:]))
        if words[:1] and words[0] in _TITLES and len(words) > 1:  # "Sir Alex Ferguson" -> "alex ferguson"
            forms.add(" ".join(words[1:]))
    if re.match(r"(?i)\s*who\b", question):  # "Who directed ...?" -> "miyazaki", "van halen"
        name = _canonical(_PARENTHETICAL.sub("", answer)).split()
        if 2 <= len(name) <= 4 and len(name[-1]) >= 4:
            forms.add(name[-1])
            if name[-2] in _PARTICLES:
                forms.add(" ".join(name[-2:]))
    return forms


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
        "(10 or 15 points, fewer with hints). {p}trivia categories lists topics. "
        "Questions: Open Trivia DB, CC BY-SA 4.0."
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
        recent: tuple[str, ...] = (),
    ) -> None:
        super().__init__(category, rng, assets, level=level, recent=recent)
        in_category = [q for q in _questions(assets) if q["category"] == category]
        if not in_category:
            raise ValueError(f"no trivia questions in {category!r}")
        available = sorted({q["difficulty"] for q in in_category}, key=self.levels.index)
        if level not in available:  # not chosen, or this category has none at that difficulty
            level = rng.choice(available)
        self.level = level
        pool = [q for q in in_category if q["difficulty"] == level]
        q = self.pick_unseen(pool, lambda question: question["id"])
        self.item_id = q["id"]
        self.question: str = q["question"]
        self.answer: str = q["answer"]
        self.options: list[str] = []
        if level == "easy":
            self.options = [self.answer, *q["wrong"]]
            rng.shuffle(self.options)
            self.time_limit = self.EASY_TIME
        self._accepted = accepted_answers(self.answer, self.question)
        self.guesses_left = self.GUESSES
        self.hints_used = 0
        self._told_how = False  # the "answer with A-D" reminder is sent at most once
        outside = _PARENTHETICAL.sub("", self.answer).strip()
        inner = _PARENTHETICAL.search(self.answer)
        # hints describe what's typed: skip "(Clown)", but use "phi" for "Φ (phi)"
        self._hint_text = inner.group(1) if inner and not re.search(r"[A-Za-z0-9]", outside) else outside or self.answer
        letters = [i for i, ch in enumerate(self._hint_text) if ch.isalnum()]
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
            matches = [i for i, o in enumerate(self.options) if said & {f.replace(" ", "") for f in _forms(o)}]
            index = matches[0] if len(matches) == 1 else -1  # two options that read alike: ask for the letter
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
        text = self._hint_text
        number = _NUMBER_WITH_UNIT.match(text) or _DECADE.match(text)  # "7 years": the number is the answer
        if number:
            text = number.group(1)
        chars = [ch for ch in text if ch.isalnum()]
        short = len(chars) <= 2 or text.replace(",", "").isdigit()  # "starts with 8" would give these away
        if self.easy or self.hints_used >= (1 if short else len(self.POINTS[self.level]) - 1):
            return None
        self.hints_used += 1
        kind = "letter" if all(ch.isalpha() for ch in chars) else "character"
        if self.hints_used == 1:
            if text.replace(",", "").isdigit():
                return Outcome(messages=[f"💡 A {len(chars)}-digit number"])
            if short:
                return Outcome(messages=[f"💡 {_plural(len(chars), kind)}"])
            words = sum(any(ch.isalnum() for ch in w) for w in text.split())  # "&" isn't a word
            prefix = f"{_plural(words, 'word')}, " if words > 1 else ""
            return Outcome(messages=[f"💡 {prefix}{_plural(len(chars), kind)}, starts with {chars[0].upper()}"])
        alnum = [i for i, ch in enumerate(text) if ch.isalnum()]
        shown = {alnum[0], alnum[-1]} | set(self._reveal_order[: max(0, math.ceil(len(alnum) / 2) - 2)])
        cells = []
        for i, ch in enumerate(text):
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
