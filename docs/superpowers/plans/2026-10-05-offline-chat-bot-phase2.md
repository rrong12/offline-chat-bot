# Offline Chat Bot Phase 2 (Trivia, Riddle, Higher or Lower) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three personal games, Trivia, Riddle and Higher or Lower, to the Phase 1 bot.

**Architecture:** Each game is a pure `Game` class run by the existing `GameManager`, which gains start options (category plus difficulty), per-player repeat avoidance, timer restarts, aliases and shared `?g`/`?hint` help. Content is bundled JSON: an Open Trivia DB question bank, riddles written for the bot, and Wikipedia page views, built by scripts in `scripts/`.

**Tech Stack:** Python 3.12, pytest + pytest-asyncio, SQLite, the existing bot packages.

**Spec:** `docs/superpowers/specs/2026-10-04-offline-chat-bot-phase2-design.md`

---

## Conventions

- Work in the repo root with the project venv (`.venv/bin/python`, `.venv/bin/pytest`). Lint with
  `ruff check --select F,E,W,B,I --line-length 120 bot tests scripts` if ruff is available.
- Every code step gives the **whole file**. Write it exactly; where a file already exists, replace
  it completely. The code was run and tested before this plan was written.
- Commit after each task with the message given, and never add AI attribution to commits.
- Text the bot posts never repeats what a user typed, and content never contains blocked words
  (`content/blocked_prose_rot13.txt`, checked by `BlockedWords`).

## File map

| File | Task |
|---|---|
| `README.md` | 6 |
| `bot/assets.py` | 1 |
| `bot/content/TRIVIA_CREDITS.md` | 7 |
| `bot/content/higherlower.json` | 9 |
| `bot/content/riddles.json` | 8 |
| `bot/content/trivia.json` | 7 |
| `bot/games/__init__.py` | 6 |
| `bot/games/base.py` | 2 |
| `bot/games/hangman.py` | 2 |
| `bot/games/higherlower.py` | 5 |
| `bot/games/manager.py` | 2 |
| `bot/games/riddle.py` | 4 |
| `bot/games/scramble.py` | 2 |
| `bot/games/trivia.py` | 3 |
| `bot/stats_commands.py` | 6 |
| `bot/text.py` | 1 |
| `config.toml` | 6 |
| `pyproject.toml` | 6 |
| `scripts/fetch_pageviews.py` | 9 |
| `scripts/fetch_trivia.py` | 7 |
| `scripts/higherlower_terms.txt` | 9 |
| `tests/conftest.py` | 1 |
| `tests/test_assets.py` | 1 |
| `tests/test_cli.py` | 6 |
| `tests/test_config.py` | 6 |
| `tests/test_content.py` | 10 |
| `tests/test_flows.py` | 6 |
| `tests/test_higherlower.py` | 5 |
| `tests/test_manager.py` | 2 |
| `tests/test_riddle.py` | 4 |
| `tests/test_scramble.py` | 2 |
| `tests/test_stats_help_commands.py` | 6 |
| `tests/test_text.py` | 1 |
| `tests/test_trivia.py` | 3 |

### Task 1: Text helpers and JSON content

**Files:**
- Replace: `tests/conftest.py`, `tests/test_text.py`, `tests/test_assets.py`, `bot/text.py`, `bot/assets.py`

Small helpers the new games share, all in `bot/text.py`:

- `strip_article` drops a leading "a", "an" or "the" from **raw** text (before `normalize`, which turns punctuation into spaces): only a whole word followed by real whitespace counts, so "A-ha" and "A$AP Rocky" keep their "A".
- `fold_accents` removes accents ("Pokémon" -> "Pokemon"), so a missing accent never costs a player their one typo.
- `within_one_edit` is a Damerau-Levenshtein distance of at most 1 (one insertion, deletion, substitution, or swap of neighbouring letters).
- `typo_match` decides whether two normalized answers match (spec §3): equal ignoring spaces, or the same words except one word of 5+ letters that is one edit off. Numbers ("Apollo 13" vs 11), one-letter words ("C minor" vs E) and Roman numerals ("Louis XIV" vs XVI) must match exactly, because there one character is the whole answer.
- `short_number` formats view counts for Higher or Lower: 950, 1.2K, 55K, 241K, 1.2M (spec §5). It uses integer maths to round half up, moves into the next unit instead of printing "1000K", and rejects negative numbers.

`Assets.json(name)` loads `content/<name>.json` once and caches it. The parsed object is shared, so callers must not modify it.

The test fixtures gain tiny `trivia.json`, `riddles.json` and `higherlower.json` files, used here and by the game tasks.

- [ ] **Step 1: Write `tests/conftest.py`**

```python
import json
from pathlib import Path

import pytest

from bot.assets import Assets
from bot.clock import FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def content_dir(tmp_path: Path) -> Path:
    """A tiny content folder so game tests don't depend on the real word lists."""
    root = tmp_path / "content"
    (root / "words").mkdir(parents=True)
    (root / "words" / "animals.txt").write_text("# comment\nalligator\ncat\nsea lion\n", encoding="utf-8")
    (root / "words" / "food.txt").write_text("ramen\nhot cheetos\n", encoding="utf-8")
    (root / "8ball.txt").write_text("Yes.\nNo.\n", encoding="utf-8")
    (root / "blocked_rot13.txt").write_text("# test fragment: 'gat'\ntng\n", encoding="utf-8")
    (root / "fortunes.txt").write_text("Good things are coming.\n", encoding="utf-8")
    for name in ("catfacts", "dogfacts", "facts", "dadjokes"):
        (root / f"fallback_{name}.txt").write_text(f"fallback {name} line\n", encoding="utf-8")
    trivia = [
        {"id": "e1", "category": "science", "difficulty": "easy", "question": "What gas do plants absorb?",
         "answer": "Carbon dioxide", "wrong": ["Oxygen", "Nitrogen", "Helium"]},
        {"id": "m1", "category": "science", "difficulty": "medium", "question": "Which planet is the largest?",
         "answer": "Jupiter"},
        {"id": "h1", "category": "history", "difficulty": "hard", "question": "In what year did WW2 end?",
         "answer": "1945"},
        {"id": "h2", "category": "history", "difficulty": "hard", "question": "Who painted the Mona Lisa?",
         "answer": "Leonardo da Vinci"},
    ]
    (root / "trivia.json").write_text(json.dumps({"questions": trivia}), encoding="utf-8")
    riddles = [
        {"riddle": "What has hands but can't clap?", "answers": ["clock", "watch"],
         "clue": "You probably check me several times a day."},
        {"riddle": "What gets wetter the more it dries?", "answers": ["towel"], "clue": "Find me in a bathroom."},
    ]
    (root / "riddles.json").write_text(json.dumps(riddles), encoding="utf-8")
    terms = [{"name": "Minecraft", "views": 241_000}, {"name": "Pizza", "views": 55_000},
             {"name": "Axolotl", "views": 30_000}, {"name": "YouTube", "views": 1_200_000}]
    (root / "higherlower.json").write_text(json.dumps({"terms": terms}), encoding="utf-8")
    return root


@pytest.fixture
def assets(content_dir: Path) -> Assets:
    return Assets(content_dir)
```

- [ ] **Step 2: Write `tests/test_text.py`**

```python
import pytest

from bot.text import (
    clean_username,
    fold_accents,
    format_duration,
    normalize,
    short_number,
    strip_article,
    strip_invisible,
    truncate,
    typo_match,
    within_one_edit,
)


def test_normalize_lowercases_and_collapses_spaces():
    assert normalize("  Hello   WORLD ") == "hello world"


def test_normalize_turns_punctuation_into_spaces():
    assert normalize("spider-man!") == "spider man"


def test_normalize_drops_chatterino_duplicate_tag():
    assert normalize("alligator \U000e0000") == "alligator"


def test_normalize_drops_zero_width_characters():
    assert normalize("alli" + chr(0x200B) + "gator") == "alligator"


def test_normalize_removes_combining_marks_instead_of_splitting_words():
    stroke = chr(0x0336)  # combining long stroke overlay: strikethrough "fancy text"
    assert normalize(f"h{stroke}e{stroke}l{stroke}l{stroke}o{stroke}") == "hello"


def test_normalize_removes_format_characters_mid_word():
    for invisible in (chr(0x00AD), chr(0x2066), chr(0xFE0F)):  # soft hyphen, directional isolate, variation selector
        assert normalize(f"alli{invisible}gator") == "alligator"


def test_normalize_keeps_accented_letters():
    assert normalize("Cafe" + chr(0x0301)) == "caf" + chr(0x00E9)  # NFKC composes the accent before marks are dropped


def test_normalize_applies_nfkc():
    assert normalize("ｆｕｌｌｗｉｄｔｈ") == "fullwidth"


def test_strip_invisible_keeps_visible_text():
    assert strip_invisible("?scramble\U000e0000") == "?scramble"


def test_truncate_leaves_short_text_alone():
    assert truncate("hi") == "hi"


def test_truncate_cuts_at_word_boundary_with_ellipsis():
    text = "word " * 200
    out = truncate(text)
    assert len(out) <= 500
    assert out.endswith("word…")


def test_truncate_hard_cuts_one_long_word():
    out = truncate("x" * 600)
    assert len(out) == 500
    assert out.endswith("…")


def test_clean_username_accepts_valid_names():
    assert clean_username("@Some_User") == "some_user"


def test_clean_username_accepts_boundary_lengths():
    assert clean_username("abc") == "abc"
    assert clean_username("x" * 25) == "x" * 25


def test_clean_username_rejects_bad_names():
    assert clean_username("ab") is None
    assert clean_username("has space") is None
    assert clean_username("emoji😀") is None
    assert clean_username("x" * 26) is None


def test_format_duration():
    assert format_duration(45) == "45s"
    assert format_duration(12 * 60 + 5) == "12m"
    assert format_duration(3 * 3600 + 12 * 60) == "3h 12m"
    assert format_duration(-5) == "0s"


def test_strip_article():
    assert strip_article("The Eiffel Tower") == "Eiffel Tower"
    assert strip_article("an apple") == "apple"
    assert strip_article("a towel") == "towel"
    assert strip_article("  the  clock") == "clock"
    assert strip_article("theater") == "theater"  # only a whole leading word
    assert strip_article("A-ha") == "A-ha" and strip_article("A$AP Rocky") == "A$AP Rocky"  # not articles
    assert strip_article("the") == "the" and strip_article("") == ""


def test_fold_accents():
    assert fold_accents("Pokémon Mötley Crüe café") == "Pokemon Motley Crue cafe"


def test_typo_match():
    assert typo_match("jupitor", "jupiter")
    assert typo_match("pacman", "pac man")  # spaces don't matter
    assert typo_match("leonardo da vinsi", "leonardo da vinci")
    assert not typo_match("apollo 13", "apollo 11")  # numbers exact
    assert not typo_match("e minor", "a minor")  # short words exact
    assert not typo_match("louis xvi", "louis xiv")  # Roman numerals exact
    assert not typo_match("henry vii", "henry viii")
    assert not typo_match("1950s", "1940s")
    assert not typo_match("jupitor saturnn", "jupiter saturn")  # one typo in total
    assert not typo_match("cat", "car")  # too short for a typo
    assert not typo_match("wario", "mario")  # a typo never changes the first letter
    assert not typo_match("louis xvii", "louis xviii")  # a 5-letter Roman numeral is still exact
    assert not typo_match("1 38 billion", "13 8 billion")  # digit groups must match, not just digits
    assert typo_match("shaquile oneal", "shaquille o neal")  # split differently, still one typo


def test_within_one_edit():
    assert within_one_edit("jupiter", "jupiter")
    assert within_one_edit("jupiter", "jupitor")  # substitution
    assert within_one_edit("jupiter", "jupiterr")  # insertion
    assert within_one_edit("jupiter", "upiter")  # deletion
    assert within_one_edit("jupiter", "jupietr")  # neighbours swapped
    assert not within_one_edit("jupiter", "jpuietr")
    assert not within_one_edit("jupiter", "juxyter")  # two different letters side by side
    assert within_one_edit("", "a") and not within_one_edit("", "ab")
    assert not within_one_edit("abc", "cba")
    assert not within_one_edit("a", "abc")


def test_short_number():
    cases = {0: "0", 950: "950", 1000: "1K", 1234: "1.2K", 1150: "1.2K", 1350: "1.4K", 9950: "10K",
             10_500: "11K", 55_123: "55K", 241_000: "241K", 999_499: "999K", 999_500: "1M",
             1_234_567: "1.2M", 12_345_678: "12M", 1_500_000_000: "1.5B"}
    for n, text in cases.items():
        assert short_number(n) == text, n
    with pytest.raises(ValueError):
        short_number(-5)
```

- [ ] **Step 3: Write `tests/test_assets.py`**

```python
from bot.assets import Assets


def test_lines_skip_blank_and_comment_lines(assets: Assets):
    assert assets.words("animals") == ["alligator", "cat", "sea lion"]


def test_categories_are_sorted_file_stems(assets: Assets):
    assert assets.categories() == ["animals", "food"]


def test_lines_reads_top_level_files(assets: Assets):
    assert assets.lines("8ball") == ["Yes.", "No."]


def test_json_reads_top_level_json_files(assets: Assets):
    assert assets.json("riddles")[0]["answers"] == ["clock", "watch"]
```

- [ ] **Step 4: Run the tests and see them fail**

Run: `.venv/bin/pytest tests/test_text.py tests/test_assets.py -q`
Expected: `ImportError: cannot import name 'short_number' from 'bot.text'`.

- [ ] **Step 5: Write `bot/text.py`**

```python
"""Text helpers: answer normalization and matching, truncation, usernames, durations, numbers."""

from __future__ import annotations

import re
import unicodedata

MAX_MESSAGE = 500

# Removed outright rather than turned into spaces, so a word stays one word:
# - format characters (category Cf): zero-width spaces and joiners, BOM, soft hyphen,
#   directional marks;
# - combining marks (Mn, Me): strikethrough and "fancy text" overlays, variation selectors;
# - the Unicode tag block U+E0000-E007F. Chatterino and 7TV append U+E0000 to repeated
#   messages, and it is unassigned (category Cn), so the category check alone misses it.
_DROP_CATEGORIES = frozenset({"Cf", "Mn", "Me"})
_TAG_BLOCK = range(0xE0000, 0xE0080)
_USERNAME = re.compile(r"^[A-Za-z0-9_]{3,25}$")


def strip_invisible(text: str) -> str:
    return "".join(
        ch for ch in text if unicodedata.category(ch) not in _DROP_CATEGORIES and ord(ch) not in _TAG_BLOCK
    )


def normalize(text: str) -> str:
    """Lowercase, drop invisible characters, turn punctuation into spaces, collapse spaces."""
    t = unicodedata.normalize("NFKC", text).lower()
    t = strip_invisible(t)
    t = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in t)
    return " ".join(t.split())


def truncate(text: str, limit: int = MAX_MESSAGE) -> str:
    """Cut to at most `limit` characters at a word boundary, ending with an ellipsis."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def clean_username(raw: str) -> str | None:
    """Strip a leading @ and return the lowercase login, or None if it isn't a valid name."""
    name = strip_invisible(raw).strip().lstrip("@")
    if not _USERNAME.fullmatch(name):
        return None
    return name.lower()


def format_duration(seconds: float) -> str:
    """3h 12m, 12m, or 45s."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"


_LEADING_ARTICLE = re.compile(r"(?i)^\s*(?:a|an|the)\s+(?=\S)")
_ROMAN = re.compile(r"[ivxlcdm]+")
_DIGITS = re.compile(r"\d+")


def strip_article(text: str) -> str:
    """'The Eiffel Tower' -> 'Eiffel Tower'. Use on raw text, before normalize: only a whole leading
    word followed by real whitespace counts, so "A-ha" and "A$AP" keep their "A"."""
    return _LEADING_ARTICLE.sub("", text, count=1)


_LIGATURES = str.maketrans({"æ": "ae", "Æ": "AE", "ø": "o", "Ø": "O", "œ": "oe", "Œ": "OE", "ß": "ss", "ł": "l"})


def fold_accents(text: str) -> str:
    """'pokémon' -> 'pokemon', 'solskjær' -> 'solskjaer', so a missing accent never costs a player their typo."""
    text = text.translate(_LIGATURES)
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def within_one_edit(a: str, b: str) -> bool:
    """True if a and b differ by at most one insertion, deletion, substitution, or swap of neighbours."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(short) and short[i] == long[i]:
        i += 1
    return short[i:] == long[i + 1:]


def typo_match(guess: str, answer: str, min_letters: int = 5) -> bool:
    """Do two normalized answers match? Equal ignoring spaces, or off by one typo in a word of
    `min_letters`+ letters that keeps its first letter (so Mario isn't Wario). Numbers must be the same
    groups of digits ("1 38" isn't "13 8", "Apollo 13" isn't 11), and short words ("A minor") and Roman
    numerals ("Louis XIV") must match exactly: there one character is the whole answer."""
    if _DIGITS.findall(guess) != _DIGITS.findall(answer):
        return False
    if guess.replace(" ", "") == answer.replace(" ", ""):
        return True
    guess_words, answer_words = guess.split(), answer.split()
    if len(guess_words) == len(answer_words):
        typos = 0
        for g, a in zip(guess_words, answer_words, strict=True):
            if g == a:
                continue
            if not _typo_ok(g, a, min_letters):
                return False
            typos += 1
        return typos <= 1
    # split differently ("shaquile oneal" for "shaquille o neal"): one typo over the whole answer
    joined_guess, joined_answer = guess.replace(" ", ""), answer.replace(" ", "")
    if any(_ROMAN.fullmatch(a) and len(a) > 1 for a in answer_words) or len(joined_answer) < 2 * min_letters:
        return False
    return _typo_ok(joined_guess, joined_answer, min_letters)


def _typo_ok(guess: str, answer: str, min_letters: int) -> bool:
    return (
        answer.isalpha()
        and len(answer) >= min_letters
        and not _ROMAN.fullmatch(answer)
        and guess[:1] == answer[:1]
        and within_one_edit(guess, answer)
    )


def short_number(n: int) -> str:
    """950, 1.2K, 55K, 241K, 1.2M, 12M: at most three significant digits, rounded half up."""
    if n < 0:
        raise ValueError(f"short_number needs a count, got {n}")
    if n < 1000:
        return str(n)
    for divisor, suffix in ((1_000, "K"), (1_000_000, "M"), (1_000_000_000, "B")):
        tenths = (n * 10 + divisor // 2) // divisor  # integer maths: no float rounding surprises
        if tenths < 100:
            return f"{tenths // 10}.{tenths % 10}".removesuffix(".0") + suffix
        whole = (n + divisor // 2) // divisor
        if whole < 1000 or suffix == "B":
            return f"{whole}{suffix}"
    raise AssertionError("unreachable")
```

- [ ] **Step 6: Write `bot/assets.py`**

```python
"""Loads the bundled content in bot/content/: text files (one item per line) and JSON files."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(__file__).parent / "content"


class Assets:
    def __init__(self, root: Path = DEFAULT_ROOT) -> None:
        self.root = root

    def lines(self, name: str) -> list[str]:
        """Non-blank, non-comment lines of content/<name>.txt."""
        return list(_read(self.root / f"{name}.txt"))

    def words(self, category: str) -> list[str]:
        return list(_read(self.root / "words" / f"{category}.txt"))

    def categories(self) -> list[str]:
        return sorted(p.stem for p in (self.root / "words").glob("*.txt"))

    def json(self, name: str) -> Any:
        """Parsed content/<name>.json. Cached and shared: callers must not modify it."""
        return _read_json(self.root / f"{name}.json")


@cache  # content is bundled and read-only, so each file is read once per process
def _read(path: Path) -> tuple[str, ...]:
    text = path.read_text(encoding="utf-8")
    return tuple(
        line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    )


@cache
def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/pytest tests/test_text.py tests/test_assets.py -q`, then `.venv/bin/pytest -q`.
Expected: `25 passed`, then the whole suite passes (309 passed).

- [ ] **Step 8: Commit**

```bash
git add tests/conftest.py tests/test_text.py tests/test_assets.py bot/text.py bot/assets.py
git commit -m "Phase 2: text helpers (articles, typo tolerance, short numbers) and JSON content"
```

### Task 2: Game framework: options, repeats, timers, aliases, shared help

**Files:**
- Replace: `tests/test_manager.py`, `tests/test_scramble.py`, `bot/games/base.py`, `bot/games/manager.py`, `bot/games/scramble.py`, `bot/games/hangman.py`

Framework changes from spec §6, all backwards compatible with Scramble and Hangman:

- **`Outcome.restart_timer`:** when an unfinished outcome sets it, the manager resets the session's start time, so streak games give each answer a fresh time limit.
- **Start options:** a game may declare `levels` (Trivia's difficulties) and a `levels_label`. The manager reads up to one category and one level from the start command, in either order and in any case (`?trivia HARD science`; a repeated word is fine). Any other word gets "Unknown option." ("Unknown category." for games without levels) plus the option list, never repeating the word. `?<game> categories` lists the levels too. A game with neither categories nor levels ignores extra words, as in Phase 1 (`?hl lets go` just starts), and `?riddle categories` says it has no options. (A content test in Task 10 checks that no category shares a name with a level, since `?trivia easy` would be ambiguous.)
- **No repeats:** a game may set `item_id` (a string) for the question it picked. The manager keeps each player's last 50 ids per game (in memory since the bot started; the least recently active of 10,000 players are forgotten) and passes them, oldest first, as `recent`. `Game.pick_unseen` picks a random unseen item, or, once all have been seen, the one seen longest ago, so a small pool never repeats back to back.
- **A broken time limit** (not a finite number) ends only that game, with "Game ended due to an error.", instead of raising in the 1-second tick and freezing every timer.
- **Aliases:** a game's `aliases` become aliases of its start command (`?hl`).
- **Shared help:** an in-game command declared by more than one game (`?g`, `?hint`) gets generic help text ("Guess in your current game."); a command only one game uses keeps that game's text.
- **Game constructor:** `Game.__init__(category, rng, assets, *, level=None, recent=())`. `time_limit` is now a plain class attribute a game may change for one round (Trivia's easy questions get 20 s).
- **Scramble accepts `?g <word>`** too, so `?g` works in every game. A wrong `?g` stays silent, like a wrong plain-chat guess.

- [ ] **Step 1: Write `tests/test_manager.py`**

```python
import json
import random
import re

import pytest

from bot.activity_log import ActivityLog
from bot.clock import FakeClock
from bot.commands import CommandContext, CommandRegistry
from bot.games.base import Game, Outcome
from bot.games.hangman import Hangman
from bot.games.manager import GameManager
from bot.games.scramble import Scramble
from bot.stats import StatsStore
from tests.helpers import make_msg


class Boom(Game):
    """A game whose code raises, to test error handling."""

    name = "boom"
    title = "Boom"
    usage = "{p}boom"
    description = "Explodes."
    time_limit = 10

    def start(self) -> str:
        return "boom started"

    def on_message(self, msg, now):
        raise RuntimeError("kaboom")

    def on_timeout(self) -> Outcome:
        return Outcome(finished=True, result="timeout")

    def reveal(self) -> str:
        return "nothing"


class Stubborn(Boom):
    """A game whose on_timeout forgets to finish, and whose reveal raises."""

    name = "stubborn"

    def on_message(self, msg, now):
        return None

    def on_timeout(self) -> Outcome:
        return Outcome(messages=["still going"])

    def reveal(self) -> str:
        raise RuntimeError("no answer")


class NoResult(Boom):
    """Times out with finished=True but no result."""

    name = "noresult"

    def on_message(self, msg, now):
        return None

    def on_timeout(self) -> Outcome:
        return Outcome(messages=["over"], finished=True)


class AnyCommand(Boom):
    """Answers any in-game command, to prove the manager only routes declared ones."""

    name = "anycommand"
    commands = {"g": ("{p}g", "Guess.")}

    def on_message(self, msg, now):
        return None

    def on_command(self, name, args, msg, now):
        return Outcome(messages=[f"got {name}"])


class BrokenStart(Boom):
    name = "brokenstart"

    def start(self) -> str:
        raise RuntimeError("cannot start")


class Quiz(Boom):
    """Has categories, levels, an alias, and question ids, to test start options and repeat avoidance."""

    name = "quiz"
    title = "Quiz"
    aliases = ("qz",)
    levels = ("easy", "hard")
    levels_label = "difficulties"
    ITEMS = ("q1", "q2", "q3")

    @classmethod
    def category_names(cls, assets):
        return ["science", "history"]

    def __init__(self, category, rng, assets, *, level=None, recent=()):
        super().__init__(category, rng, assets, level=level, recent=recent)
        self.item_id = self.pick_unseen(list(self.ITEMS), lambda item: item)

    def start(self) -> str:
        return f"quiz {self.category} {self.level} {self.item_id}"

    def on_message(self, msg, now):
        return None


class Streak(Boom):
    """Every guess is right and restarts the timer."""

    name = "streak"
    commands = {"g": ("{p}g", "Guess.")}

    def on_message(self, msg, now):
        return None

    def on_command(self, name, args, msg, now):
        return Outcome(messages=["right"], restart_timer=True)


class Harness:
    def __init__(self, tmp_path, clock: FakeClock, assets, max_games: int = 25, extra_games=None):
        self.clock = clock
        self.said: list[tuple[str, dict]] = []  # everything the manager sent: (text, kwargs)
        self.replies: list[str] = []  # direct command replies (ctx.reply)
        self.busy = False
        self.stats = StatsStore(":memory:")
        self.log = ActivityLog(tmp_path / "logs", clock)
        self.manager = GameManager(
            games={"scramble": Scramble, "hangman": Hangman, "boom": Boom, "stubborn": Stubborn,
                   "noresult": NoResult, "anycommand": AnyCommand, "brokenstart": BrokenStart,
                   "quiz": Quiz, "streak": Streak, **(extra_games or {})},
            stats=self.stats,
            log=self.log,
            clock=clock,
            assets=assets,
            rng=random.Random(1),
            say=lambda text, **kw: self.said.append((text, kw)),
            prefix="?",
            cooldown_seconds=10,
            max_games=max_games,
            is_busy=lambda: self.busy,
        )
        self.registry = CommandRegistry("?")
        self.manager.register(self.registry)

    async def command(self, text: str, login: str = "alice"):
        name, _, args = text.removeprefix("?").partition(" ")
        msg = make_msg(text, login)
        ctx = CommandContext(
            msg, name, args, "?",
            lambda t, **kw: self.replies.append(t), lambda t, **kw: self.said.append((t, kw)),
        )
        await self.registry.get(name).handler(ctx)
        return msg

    def chat(self, text: str, login: str = "alice"):
        msg = make_msg(text, login)
        self.manager.on_message(msg)
        return msg

    def texts(self) -> list[str]:
        return [t for t, _ in self.said]

    def events(self) -> list[dict]:
        path = self.log.path_for(self.clock.now().date())
        return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def h(tmp_path, clock, assets) -> Harness:
    return Harness(tmp_path, clock, assets)


def test_register_adds_start_skip_and_hidden_game_commands(h: Harness):
    names = {c.name for c in h.registry.all()}
    assert names == {
        "scramble", "hangman", "boom", "stubborn", "noresult", "anycommand", "brokenstart", "quiz", "streak",
        "skip", "hint", "g",
    }
    start = h.registry.get("scramble")
    assert not start.cooldown  # the per-player game cooldown is the only limit on starting
    assert not h.registry.get("g").listed and not h.registry.get("g").cooldown
    assert not h.registry.get("skip").cooldown


async def test_start_replies_to_the_player_with_the_category(h: Harness):
    msg = await h.command("?scramble")
    text, kw = h.said[0]
    assert text.startswith("🔤 Unscramble (") and "?hint" in text
    assert kw["reply_to"] == msg.id
    assert h.events()[0]["event"] == "game_start" and h.events()[0]["player"] == "alice"


async def test_categories_lists_and_starts_nothing(h: Harness):
    await h.command("?scramble categories")
    assert h.replies == ["Scramble categories: animals, food"]
    assert h.manager.sessions == {}


async def test_unknown_category_lists_categories(h: Harness):
    await h.command("?scramble planets")
    assert h.replies == ["Unknown category. Scramble categories: animals, food"]
    assert h.manager.sessions == {}


async def test_players_have_separate_games_at_the_same_time(h: Harness):
    await h.command("?scramble animals", "alice")
    await h.command("?hangman animals", "bob")
    assert set(h.manager.sessions) == {"id-alice", "id-bob"}
    h.chat("alligator", "bob")  # bob's chat doesn't answer alice's game
    assert "id-alice" in h.manager.sessions
    answer = h.chat("alligator", "alice")
    text, kw = h.said[-1]
    assert text == "✅ alice got it: ALLIGATOR (+10)"
    assert kw["reply_to"] == answer.id  # threaded under the winning answer
    assert set(h.manager.sessions) == {"id-bob"}


async def test_one_game_per_player_and_per_player_cooldown(h: Harness):
    await h.command("?scramble animals")
    await h.command("?hangman animals")
    assert h.replies[-1] == "You already have a scramble game running."
    h.chat("alligator")  # alice wins; her 10 s cooldown starts now
    h.clock.advance(5)
    await h.command("?scramble animals")
    assert h.replies[-1] == "Your next game in 5s."
    await h.command("?scramble animals", "bob")  # other players aren't blocked
    assert "id-bob" in h.manager.sessions
    h.clock.advance(5)
    await h.command("?scramble animals")
    assert "id-alice" in h.manager.sessions


async def test_refusal_replies_are_rate_limited_per_player(h: Harness):
    await h.command("?scramble animals")
    await h.command("?scramble animals")
    await h.command("?scramble animals")
    assert h.replies == ["You already have a scramble game running."]
    h.clock.advance(5)
    await h.command("?scramble animals")
    assert len(h.replies) == 2


async def test_category_list_is_rate_limited_per_game(h: Harness):
    await h.command("?scramble categories")
    await h.command("?scramble categories")
    await h.command("?hangman categories")
    assert h.replies == ["Scramble categories: animals, food", "Hangman categories: animals, food"]


async def test_categories_then_pick_works_immediately(h: Harness):
    await h.command("?scramble categories")
    await h.command("?scramble food")
    assert h.texts()[0].startswith("🔤 Unscramble (food)")


async def test_max_running_games(tmp_path, clock, assets):
    h = Harness(tmp_path, clock, assets, max_games=2)
    await h.command("?scramble", "p1")
    await h.command("?scramble", "p2")
    await h.command("?scramble", "p3")
    assert h.replies[-1] == "Too many games running right now, try again in a moment."
    assert len(h.manager.sessions) == 2


async def test_busy_brake_refuses_new_games(h: Harness):
    h.busy = True
    await h.command("?scramble")
    assert h.replies[-1] == "Too many games running right now, try again in a moment."
    assert h.manager.sessions == {}


async def test_win_records_one_player_round(h: Harness):
    await h.command("?scramble animals")
    h.chat("crocodile")  # wrong guesses cost nothing
    h.chat("alligator")
    assert [r.login for r in h.stats.leaderboard("scramble", 5)] == ["alice"]
    end = h.events()[-1]
    assert end["event"] == "game_end" and end["outcome"] == "won" and end["points"] == 10


async def test_hint_command_reaches_only_your_game(h: Harness):
    await h.command("?scramble animals", "alice")
    await h.command("?hint", "bob")  # bob has no game: ignored
    assert len(h.said) == 1
    msg = await h.command("?hint", "alice")
    text, kw = h.said[-1]
    assert text == "💡 Hint: A _ _ _ _ _ _ _ R" and kw["reply_to"] == msg.id
    h.chat("alligator")
    assert h.texts()[-1] == "✅ alice got it: ALLIGATOR (+7)"


async def test_hangman_board_updates_coalesce_per_game(h: Harness):
    await h.command("?hangman animals", "alice")
    await h.command("?hangman animals", "bob")
    await h.command("?g z", "alice")
    await h.command("?g z", "bob")
    (text_a, kw_a), (_, kw_b) = h.said[-2], h.said[-1]
    assert "wrong: Z (1/6)" in text_a
    assert kw_a["coalesce_key"] == f"hangman-board:{h.manager.sessions['id-alice'].key}"
    assert kw_a["coalesce_key"] != kw_b["coalesce_key"]


async def test_timeout_ends_the_game(h: Harness):
    await h.command("?scramble animals")
    h.clock.advance(44)
    h.manager.tick()
    assert "id-alice" in h.manager.sessions
    h.clock.advance(1)
    h.manager.tick()
    assert h.texts()[-1] == "⏰ Time's up! It was ALLIGATOR."
    assert h.manager.sessions == {}


async def test_status_counts_running_games(h: Harness):
    assert h.manager.status() == "0 running"
    await h.command("?scramble", "p1")
    await h.command("?hangman", "p2")
    assert h.manager.status() == "2 running"


async def test_skip_ends_your_own_game(h: Harness):
    await h.command("?scramble animals", "alice")
    await h.command("?scramble animals", "bob")
    await h.command("?skip", "alice")
    assert h.texts()[-1] == "⏭️ Skipped. It was ALLIGATOR."
    assert set(h.manager.sessions) == {"id-bob"}
    assert h.events()[-1]["outcome"] == "skipped"


async def test_skip_without_game_does_nothing(h: Harness):
    await h.command("?skip")
    assert h.said == [] and h.replies == []


async def test_stop_all_ends_every_game_without_points(h: Harness):
    await h.command("?scramble animals", "alice")
    await h.command("?hangman animals", "bob")
    assert h.manager.stop_all() == 2
    assert h.manager.sessions == {}
    assert h.stats.leaderboard(None, 5) == []
    assert [e["outcome"] for e in h.events() if e["event"] == "game_end"] == ["stopped", "stopped"]
    assert h.manager.stop_all() == 0


async def test_game_error_ends_only_that_players_game(h: Harness):
    await h.command("?boom", "alice")
    await h.command("?scramble animals", "bob")
    msg = h.chat("anything", "alice")
    text, kw = h.said[-1]
    assert text == "Game ended due to an error." and kw["reply_to"] == msg.id
    assert set(h.manager.sessions) == {"id-bob"}
    assert any(e["event"] == "error" and e["where"] == "game:boom.on_message" for e in h.events())
    ends = [e for e in h.events() if e["event"] == "game_end"]
    assert ends == [{**ends[0], "game": "boom", "outcome": "stopped"}]


async def test_reveal_error_during_skip_ends_the_game_once(h: Harness):
    await h.command("?stubborn", "alice")
    await h.command("?skip", "alice")
    ends = [e for e in h.events() if e["event"] == "game_end"]
    assert len(ends) == 1 and ends[0]["outcome"] == "stopped"
    assert h.manager.sessions == {}
    assert h.stats._conn.execute("SELECT COUNT(*) FROM rounds").fetchone()[0] == 1


async def test_timeout_is_forced_if_the_game_does_not_finish(h: Harness):
    await h.command("?stubborn", "alice")
    h.clock.advance(10)
    h.manager.tick()
    h.manager.tick()
    assert h.manager.sessions == {}
    assert [e["outcome"] for e in h.events() if e["event"] == "game_end"] == ["timeout"]


async def test_start_failure_is_reported_once_and_starts_nothing(h: Harness):
    await h.command("?brokenstart")
    await h.command("?brokenstart")
    assert h.replies == ["Couldn't start that game."]
    assert h.manager.sessions == {}


async def test_finished_timeout_without_result_counts_as_timeout(h: Harness):
    await h.command("?noresult")
    h.clock.advance(10)
    h.manager.tick()
    assert [e["outcome"] for e in h.events() if e["event"] == "game_end"] == ["timeout"]


async def test_stats_failure_still_ends_the_game(h: Harness, monkeypatch):
    def broken(rec):
        raise RuntimeError("disk full")

    monkeypatch.setattr(h.stats, "record_round", broken)
    await h.command("?scramble animals")
    h.chat("alligator")
    assert h.manager.sessions == {}
    assert h.texts()[-1] == "✅ alice got it: ALLIGATOR (+10)"
    assert h.manager.cooldown_remaining("id-alice") == 10
    assert any(e["event"] == "error" and e["where"] == "stats.record_round" for e in h.events())


async def test_in_game_command_for_a_different_game_is_ignored(h: Harness):
    await h.command("?anycommand", "bob")
    await h.command("?hint", "bob")  # registered by Scramble; bob's game doesn't declare it
    assert h.texts() == ["boom started"]
    await h.command("?g", "bob")  # declared: reaches the game
    assert h.texts()[-1] == "got g"


async def test_finish_records_the_players_current_name(h: Harness):
    await h.command("?scramble animals")
    renamed = make_msg("alligator", "alice")
    renamed = renamed.__class__(**{**renamed.__dict__, "login": "alice_new", "display_name": "Alice_New"})
    h.manager.on_message(renamed)
    assert h.stats.find_user("alice_new") is not None


async def test_game_messages_get_prefix_substituted(h: Harness):
    await h.command("?hangman animals")
    assert "guess with ?g <letter>" in h.texts()[0]


def test_shared_in_game_commands_get_generic_help(h: Harness):
    assert h.registry.get("g").description == "Guess in your current game."  # several games use ?g
    assert h.registry.get("hint").description == "Get a hint in your Scramble game (fewer points)."  # only Scramble


async def test_category_and_level_in_either_order(h: Harness):
    await h.command("?quiz hard science")
    assert h.texts()[-1] == "quiz science hard q1"


async def test_level_without_category_picks_a_category(h: Harness):
    await h.command("?quiz easy")
    assert re.fullmatch(r"quiz (science|history) easy q[123]", h.texts()[-1])


async def test_categories_list_includes_levels(h: Harness):
    await h.command("?quiz categories")
    assert h.replies == ["Quiz categories: science, history · difficulties: easy, hard"]


async def test_unknown_option_lists_categories_and_levels_without_echoing(h: Harness):
    await h.command("?quiz science planets")
    assert h.replies == ["Unknown option. Quiz categories: science, history · difficulties: easy, hard"]
    assert h.manager.sessions == {}


async def test_alias_starts_the_game(h: Harness):
    await h.command("?qz science")
    assert h.texts()[-1] == "quiz science None q1"


async def test_recent_questions_are_not_repeated_for_that_player(h: Harness):
    seen = []
    for _ in range(4):
        await h.command("?quiz science")
        seen.append(h.texts()[-1].split()[-1])
        await h.command("?skip")
        h.clock.advance(10)
    assert sorted(seen[:3]) == ["q1", "q2", "q3"] and seen[3] == seen[0]  # all seen: the oldest comes back


async def test_each_player_has_their_own_question_history(h: Harness):
    for _ in range(2):
        await h.command("?quiz science", "alice")
        await h.command("?skip", "alice")
        h.clock.advance(10)
    await h.command("?quiz science", "bob")
    assert h.manager.sessions["id-bob"].game.recent == ()  # alice's history isn't bob's


async def test_refusal_notices_are_limited_per_game_even_through_an_alias(h: Harness):
    await h.command("?quiz science")
    await h.command("?qz science")
    await h.command("?quiz science")
    assert h.replies == ["You already have a quiz game running."]


async def test_restart_timer_gives_a_fresh_time_limit(h: Harness):
    await h.command("?streak")
    h.clock.advance(8)
    await h.command("?g x")
    h.clock.advance(8)  # 16 s since the start, but only 8 s since the right guess
    h.manager.tick()
    assert "id-alice" in h.manager.sessions
    h.clock.advance(2)
    h.manager.tick()
    assert h.manager.sessions == {}


class Plain(Boom):
    """No categories and no levels, like Riddle and Higher or Lower."""

    name = "plain"
    title = "Plain"

    def on_message(self, msg, now):
        return None


async def test_extra_words_are_ignored_by_a_game_without_options(tmp_path, clock, assets):
    h = Harness(tmp_path, clock, assets, extra_games={"plain": Plain})
    await h.command("?plain lets go")
    assert "id-alice" in h.manager.sessions
    await h.command("?plain categories", "bob")
    assert h.replies == ["Plain has no options."]


async def test_duplicate_and_uppercase_words_are_fine(h: Harness):
    await h.command("?quiz HARD hard Science")
    assert h.texts()[-1] == "quiz science hard q1"


async def test_a_broken_time_limit_ends_only_that_game(h: Harness):
    await h.command("?scramble animals", "alice")
    await h.command("?hangman animals", "bob")
    h.manager.sessions["id-alice"].game.time_limit = float("nan")
    h.manager.tick()
    assert set(h.manager.sessions) == {"id-bob"}
    assert h.texts()[-1] == "Game ended due to an error."
    h.clock.advance(200)
    h.manager.tick()  # bob's game still times out normally
    assert h.manager.sessions == {}


async def test_remembered_questions_are_bounded(h: Harness, monkeypatch):
    import bot.games.manager as manager_module

    monkeypatch.setattr(manager_module, "RECENT_ITEMS", 2)
    monkeypatch.setattr(manager_module, "RECENT_PLAYERS", 2)
    for login in ("alice", "bob", "carol"):
        for _ in range(3):
            await h.command("?quiz science", login)
            await h.command("?skip", login)
            h.clock.advance(10)
    assert list(h.manager._recent) == [("quiz", "id-bob"), ("quiz", "id-carol")]  # alice, the oldest, is gone
    assert all(len(ids) == 2 for ids in h.manager._recent.values())


class Sticky(Streak):
    """Asks for more time when it times out."""

    name = "sticky"

    def on_timeout(self):
        return Outcome(messages=["one more?"], restart_timer=True)


async def test_a_restart_timer_from_on_timeout_cannot_extend_a_game(tmp_path, clock, assets):
    h = Harness(tmp_path, clock, assets, extra_games={"sticky": Sticky})
    await h.command("?sticky")
    h.clock.advance(10)
    h.manager.tick()
    assert h.manager.sessions == {}  # force-finished anyway


class BadId(Quiz):
    name = "badid"
    aliases = ()

    def __init__(self, category, rng, assets, *, level=None, recent=()):
        super().__init__(category, rng, assets, level=level, recent=recent)
        self.item_id = ["not", "a", "string"]


async def test_a_non_string_item_id_is_not_remembered(tmp_path, clock, assets):
    h = Harness(tmp_path, clock, assets, extra_games={"badid": BadId})
    await h.command("?badid science")
    assert "id-alice" in h.manager.sessions and h.manager._recent == {}


class BrokenContent(Quiz):
    name = "brokencontent"
    aliases = ()

    @classmethod
    def category_names(cls, assets):
        raise FileNotFoundError("content/missing.json")


async def test_a_broken_content_file_gets_a_reply(tmp_path, clock, assets):
    h = Harness(tmp_path, clock, assets, extra_games={"brokencontent": BrokenContent})
    await h.command("?brokencontent")
    assert h.replies == ["Couldn't start that game."]
```

- [ ] **Step 2: Write `tests/test_scramble.py`**

```python
import random

from bot.games.scramble import Scramble
from tests.helpers import make_msg


def make(assets, seed=1, category="animals") -> Scramble:
    return Scramble(category, random.Random(seed), assets)


def test_only_valid_words_and_categories(assets):
    # "cat" is too short and "sea lion" has a space; "hot cheetos" too
    assert Scramble.category_names(assets) == ["animals", "food"]
    game = make(assets)
    assert game.word == "ALLIGATOR"


def test_words_that_cannot_be_scrambled_are_skipped():
    from bot.games.scramble import _valid

    assert not _valid("aaaa") and not _valid("AaAa")
    assert _valid("abba")


def test_an_anagram_from_the_same_category_also_wins(tmp_path):
    import random as random_module

    from bot.assets import Assets

    root = tmp_path / "content"
    (root / "words").mkdir(parents=True)
    (root / "words" / "general.txt").write_text("canoe\nocean\n", encoding="utf-8")
    game = Scramble("general", random_module.Random(1), Assets(root))
    other = "ocean" if game.word == "CANOE" else "canoe"
    out = game.on_message(make_msg(other), None)
    assert out.finished and out.messages == [f"✅ alice got it: {other.upper()} (+10)"]


def test_scrambles_never_spell_a_blocked_fragment(assets):
    # the test content blocks "GAT"; unfiltered, some shuffles of ALLIGATOR would contain it
    scrambles = {make(assets, seed=seed).scrambled for seed in range(300)}
    assert scrambles and not any("GAT" in s for s in scrambles)


def test_word_that_cannot_be_scrambled_cleanly_is_skipped(tmp_path, monkeypatch):
    import random as random_module

    from bot.assets import Assets
    from bot.games import scramble as scramble_module

    root = tmp_path / "content"
    (root / "words").mkdir(parents=True)
    (root / "words" / "only.txt").write_text("abcd\nwxyz\n", encoding="utf-8")
    (root / "blocked_rot13.txt").write_text("n\n", encoding="utf-8")  # blocks every scramble containing "A"
    monkeypatch.setattr(scramble_module, "MAX_SHUFFLES", 50)
    for seed in range(20):
        assert scramble_module.Scramble("only", random_module.Random(seed), Assets(root)).word == "WXYZ"


def test_start_message_shows_scramble_that_differs(assets):
    game = make(assets)
    assert game.scrambled != game.word
    assert sorted(game.scrambled) == sorted(game.word)
    assert game.start() == f"🔤 Unscramble (animals): {game.scrambled} · 45s · {{p}}hint for a hint"


def test_unrelated_chatter_is_not_an_attempt(assets):
    game = make(assets)
    assert game.on_message(make_msg("lol"), None) is None
    assert game.on_message(make_msg("is it gator lol"), None) is None


def test_wrong_same_length_word_is_an_attempt(assets):
    game = make(assets)
    out = game.on_message(make_msg("crocodile"), None)
    assert out is not None and not out.finished


def test_correct_answer_wins_ten_points_case_insensitive(assets):
    game = make(assets)
    out = game.on_message(make_msg("AlLiGaToR \U000e0000", "bob"), None)
    assert out.finished and out.result == "won"
    assert out.awards == {"id-bob": 10} and out.winners == {"id-bob"}
    assert out.messages == ["✅ bob got it: ALLIGATOR (+10)"]


def hint(game: Scramble):
    return game.on_command("hint", "", make_msg("?hint"), None)


def test_hints_on_request_reduce_points(assets):
    game = make(assets)
    assert game.on_tick(30) is None  # no automatic hints
    assert hint(game).messages == ["💡 Hint: A _ _ _ _ _ _ _ R"]
    hint2 = hint(game).messages[0]
    revealed = [c for c in hint2.removeprefix("💡 Hint: ").split(" ") if c != "_"]
    assert len(revealed) == 5  # first, last, and 3 middle letters (about half of 9)
    assert hint(game) is None  # only two hints
    out = game.on_message(make_msg("alligator"), None)
    assert out.awards == {"id-alice": 4}


def test_one_hint_gives_seven_points(assets):
    game = make(assets)
    hint(game)
    assert game.on_message(make_msg("alligator"), None).awards == {"id-alice": 7}


def test_timeout_reveals_word(assets):
    out = make(assets).on_timeout()
    assert out.finished and out.result == "timeout"
    assert out.messages == ["⏰ Time's up! It was ALLIGATOR."]
    assert out.awards == {}


def test_g_command_also_guesses_and_stays_silent_when_wrong(assets):
    game = make(assets)
    wrong = game.on_command("g", "crocodile", make_msg("?g crocodile"), None)
    assert not wrong.finished and wrong.messages == []
    out = game.on_command("g", "Alligator", make_msg("?g Alligator"), None)
    assert out.finished and out.messages == ["✅ alice got it: ALLIGATOR (+10)"]
```

- [ ] **Step 3: Run the tests and see them fail**

Run: `.venv/bin/pytest tests/test_manager.py tests/test_scramble.py -q`
Expected: the new tests fail (for example `TypeError: ... got an unexpected keyword argument 'level'`).

- [ ] **Step 4: Write `bot/games/base.py`**

```python
"""The interface every game implements. Games are pure: messages and time in, outcomes out."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Literal, TypeVar

from bot.assets import Assets
from bot.connectors.base import ChatMessage

T = TypeVar("T")


@dataclass
class Outcome:
    messages: list[str] = field(default_factory=list)
    awards: dict[str, int] = field(default_factory=dict)  # user_id -> points
    winners: set[str] = field(default_factory=set)  # user_ids counted as winners
    finished: bool = False
    result: Literal["won", "timeout", "lost"] | None = None  # set when finished
    coalesce_key: str | None = None
    restart_timer: bool = False  # give the player a fresh time limit (streak games, after each right guess)


class Game(ABC):
    name: ClassVar[str]  # also the start command
    title: ClassVar[str]  # "Scramble"
    usage: ClassVar[str]  # "{p}scramble [category]"
    description: ClassVar[str]  # shown by ?help <game>; {p} becomes the prefix
    time_limit: int  # seconds; set on the class, and a game may change it for one round
    aliases: ClassVar[tuple[str, ...]] = ()  # other names for the start command
    # In-game commands: name -> (usage, description). Routed here only while this game runs.
    commands: ClassVar[dict[str, tuple[str, str]]] = {}
    # Optional second start option, such as Trivia's difficulty: "?trivia science hard".
    levels: ClassVar[tuple[str, ...]] = ()
    levels_label: ClassVar[str] = ""  # "difficulties", shown with the category list

    def __init__(
        self,
        category: str | None,
        rng: random.Random,
        assets: Assets,
        *,
        level: str | None = None,
        recent: tuple[str, ...] = (),
    ) -> None:
        self.category = category
        self.rng = rng
        self.assets = assets
        self.level = level  # one of `levels`, or None to let the game pick
        self.recent = recent  # ids of questions this player saw lately, oldest first
        self.item_id: str | None = None  # id of the question shown, so the manager can avoid repeats

    def pick_unseen(self, items: list[T], item_id: Callable[[T], str]) -> T:
        """A random item the player hasn't seen lately; if they've seen them all, the one seen longest ago."""
        seen = {key: age for age, key in enumerate(self.recent)}  # lower = seen longer ago
        fresh = [item for item in items if item_id(item) not in seen]
        if fresh:
            return self.rng.choice(fresh)
        return min(items, key=lambda item: seen[item_id(item)])

    @classmethod
    def category_names(cls, assets: Assets) -> list[str]:
        """Categories this game can be started with. [] means the game has no categories."""
        return []

    @abstractmethod
    def start(self) -> str: ...

    def on_message(self, msg: ChatMessage, now: datetime) -> Outcome | None:
        """Plain chat while the game runs. None = not an attempt."""
        return None

    def on_command(self, name: str, args: str, msg: ChatMessage, now: datetime) -> Outcome | None:
        """One of this game's in-game commands. None = rejected / not an attempt."""
        return None

    def on_tick(self, elapsed: float) -> Outcome | None:
        return None

    @abstractmethod
    def on_timeout(self) -> Outcome: ...

    @abstractmethod
    def reveal(self) -> str:
        """The answer, for skip and stop messages."""
```

- [ ] **Step 5: Write `bot/games/manager.py`**

```python
"""Runs personal games: each player has at most one game, many players can play at once."""

from __future__ import annotations

import logging
import math
import random
import traceback
import uuid
from collections import Counter, OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from bot.activity_log import ActivityLog
from bot.assets import Assets
from bot.clock import Clock
from bot.commands import Command, CommandContext, CommandRegistry, Handler
from bot.connectors.base import ChatMessage
from bot.cooldowns import Cooldowns
from bot.games.base import Game, Outcome
from bot.stats import PlayerResult, RoundRecord, StatsStore

logger = logging.getLogger(__name__)

Say = Callable[..., None]  # say(text, *, reply_to=None, coalesce_key=None, priority=False)

NOTICE_SECONDS = 5.0  # at most one "can't start" or category-list reply per player this often
RECENT_ITEMS = 50  # a player doesn't get the same question again within their last 50 of that game
RECENT_PLAYERS = 10_000  # remembered (game, player) pairs; the least recently active are forgotten
# Help for in-game commands that several games share; a command only one game uses keeps its own text.
SHARED_COMMAND_HELP = {
    "g": ("{p}g <guess>", "Guess in your current game."),
    "hint": ("{p}hint", "Get a hint in your current game (fewer points)."),
}


@dataclass
class Session:
    key: str  # short id that ties game_start and game_end log lines together
    game: Game
    category: str | None
    user_id: str
    login: str
    display_name: str
    started_at: datetime
    start_mono: float
    reply_to: str  # the player's latest message; bot replies are threaded under it


class GameManager:
    def __init__(
        self,
        *,
        games: dict[str, type[Game]],
        stats: StatsStore,
        log: ActivityLog,
        clock: Clock,
        assets: Assets,
        rng: random.Random,
        say: Say,
        prefix: str,
        cooldown_seconds: float,
        max_games: int,
        is_busy: Callable[[], bool],
    ) -> None:
        self.games = games
        self.stats = stats
        self.log = log
        self.clock = clock
        self.assets = assets
        self.rng = rng
        self._say = say
        self.prefix = prefix
        self.cooldown_seconds = cooldown_seconds
        self.max_games = max_games
        self._is_busy = is_busy
        self.sessions: dict[str, Session] = {}  # user_id -> that player's running game
        self._cooldowns = Cooldowns(clock)  # per-player game cooldowns and notice rate limits
        self._recent: OrderedDict[tuple[str, str], deque[str]] = OrderedDict()  # (game, user_id) -> item ids

    # registration

    def register(self, registry: CommandRegistry) -> None:
        # Start commands have no command cooldowns: the per-player game cooldown is the only limit
        # on starting, and refusal replies are rate-limited separately (see _notice).
        for cls in self.games.values():
            handler = self._start_handler(cls)
            registry.add(
                Command(cls.name, handler, cls.usage, cls.description, "Games", aliases=cls.aliases, cooldown=False)
            )
        registry.add(Command("skip", self._skip_command, "{p}skip", "End your current game.", "Games", cooldown=False))
        users = Counter(name for cls in self.games.values() for name in cls.commands)
        seen: set[str] = set()
        for cls in self.games.values():
            for name, own_help in cls.commands.items():
                if name not in seen:
                    seen.add(name)
                    usage, description = SHARED_COMMAND_HELP.get(name, own_help) if users[name] > 1 else own_help
                    registry.add(
                        Command(name, self._game_command, usage, description, "Games", cooldown=False, listed=False)
                    )

    # helpers

    def _reply(self, session: Session, text: str, coalesce_key: str | None = None) -> None:
        key = f"{coalesce_key}:{session.key}" if coalesce_key else None  # unique per player and round
        self._say(text.replace("{p}", self.prefix), reply_to=session.reply_to, coalesce_key=key)

    def _notice(self, ctx: CommandContext, cls: type[Game], text: str) -> None:
        """Reply to a start request we can't fulfil, at most once per NOTICE_SECONDS per player per game.
        Keyed by the game, not the name typed, so switching to an alias (?hl) doesn't get around it."""
        if self._cooldowns.check_command(f"notice:{cls.name}", ctx.msg.user_id, NOTICE_SECONDS, 0):
            ctx.reply(text)

    def cooldown_remaining(self, user_id: str) -> float:
        return self._cooldowns.remaining(("game", user_id))

    @staticmethod
    def _seen(session: Session, msg: ChatMessage) -> None:
        """Track the player's latest message (replies thread under it) and current names."""
        session.reply_to = msg.id
        session.login = msg.login
        session.display_name = msg.display_name

    def status(self) -> str:
        return f"{len(self.sessions)} running"

    def _guard(self, session: Session, where: str, fn: Callable[[], Outcome | str | None]) -> Outcome | str | None:
        """Run game code. On an exception: log it and end that player's game with no points."""
        try:
            return fn()
        except Exception as exc:
            logger.exception("game error in %s", where)
            self.log.write(
                "error",
                where=f"game:{where}",
                type=type(exc).__name__,
                message=str(exc),
                traceback=traceback.format_exc(),
            )
            if self.sessions.get(session.user_id) is session:
                self._finish(session, "stopped", ["Game ended due to an error."], {}, set())
            return None

    # commands

    def _start_handler(self, cls: type[Game]) -> Handler:
        async def handler(ctx: CommandContext) -> None:
            await self._start(cls, ctx)

        return handler

    @staticmethod
    def _options(cls: type[Game], categories: list[str]) -> str:
        parts = []
        if categories:
            parts.append(f"categories: {', '.join(categories)}")
        if cls.levels:
            parts.append(f"{cls.levels_label}: {', '.join(cls.levels)}")
        return f"{cls.title} {' · '.join(parts)}" if parts else f"{cls.title} has no options."

    async def _start(self, cls: type[Game], ctx: CommandContext) -> None:
        tokens = ctx.args.lower().split()
        try:
            categories = cls.category_names(self.assets)
        except Exception as exc:  # a missing or broken content file: say so instead of going quiet
            logger.exception("could not list %s categories", cls.name)
            self.log.write("error", where=f"game:{cls.name}.categories", type=type(exc).__name__, message=str(exc))
            self._notice(ctx, cls, "Couldn't start that game.")
            return
        uid = ctx.msg.user_id
        if tokens == ["categories"]:
            self._notice(ctx, cls, self._options(cls, categories))
            return
        if uid in self.sessions:
            self._notice(ctx, cls, f"You already have a {self.sessions[uid].game.name} game running.")
            return
        remaining = self.cooldown_remaining(uid)
        if remaining > 0:
            self._notice(ctx, cls, f"Your next game in {math.ceil(remaining)}s.")
            return
        if len(self.sessions) >= self.max_games or self._is_busy():
            self._notice(ctx, cls, "Too many games running right now, try again in a moment.")
            return
        if not categories and not cls.levels:
            tokens = []  # nothing to choose, so extra words ("?hl lets go") are ignored, as in Phase 1
        category: str | None = None
        level: str | None = None
        for token in tokens:
            if token in categories and category in (None, token):
                category = token
            elif token in cls.levels and level in (None, token):
                level = token
            else:  # never repeat the unknown word: it could be anything
                kind = "option" if cls.levels else "category"
                self._notice(ctx, cls, f"Unknown {kind}. {self._options(cls, categories)}")
                return
        if categories and category is None:
            category = self.rng.choice(categories)
        recent_key = (cls.name, uid)
        try:
            game = cls(category, self.rng, self.assets, level=level, recent=tuple(self._recent.get(recent_key, ())))
            opening = game.start()
        except Exception as exc:
            logger.exception("could not start %s", cls.name)
            self.log.write("error", where=f"game:{cls.name}.start", type=type(exc).__name__, message=str(exc))
            self._notice(ctx, cls, "Couldn't start that game.")
            return
        session = Session(
            key=uuid.uuid4().hex[:8],
            game=game,
            category=category,
            user_id=uid,
            login=ctx.msg.login,
            display_name=ctx.msg.display_name,
            started_at=self.clock.now(),
            start_mono=self.clock.mono(),
            reply_to=ctx.msg.id,
        )
        self.sessions[uid] = session
        if isinstance(game.item_id, str):
            self._remember(recent_key, game.item_id)
        self.log.write("game_start", round=session.key, game=cls.name, category=category, player=ctx.msg.login)
        self._reply(session, opening)

    def _remember(self, key: tuple[str, str], item_id: str) -> None:
        recent = self._recent.pop(key, None) or deque(maxlen=RECENT_ITEMS)
        recent.append(item_id)
        self._recent[key] = recent  # now the most recently used
        while len(self._recent) > RECENT_PLAYERS:
            self._recent.popitem(last=False)

    async def _skip_command(self, ctx: CommandContext) -> None:
        session = self.sessions.get(ctx.msg.user_id)
        if session is None:
            return
        self._seen(session, ctx.msg)
        answer = self._guard(session, f"{session.game.name}.reveal", session.game.reveal)
        if answer is not None:
            self._finish(session, "skipped", [f"⏭️ Skipped. It was {answer}."], {}, set())

    async def _game_command(self, ctx: CommandContext) -> None:
        session = self.sessions.get(ctx.msg.user_id)
        if session is None or ctx.name not in session.game.commands:
            return
        self._seen(session, ctx.msg)
        now = self.clock.now()
        outcome = self._guard(
            session,
            f"{session.game.name}.on_command",
            lambda: session.game.on_command(ctx.name, ctx.args, ctx.msg, now),
        )
        self._handle(session, outcome)

    # chat and time

    def on_message(self, msg: ChatMessage) -> None:
        session = self.sessions.get(msg.user_id)
        if session is None:
            return
        self._seen(session, msg)
        now = self.clock.now()
        outcome = self._guard(session, f"{session.game.name}.on_message", lambda: session.game.on_message(msg, now))
        self._handle(session, outcome)

    def _expired(self, session: Session, elapsed: float) -> bool | None:
        """Is the game past its time limit? None (and the game is ended) if the limit isn't a usable number."""
        limit = session.game.time_limit
        if isinstance(limit, (int, float)) and not isinstance(limit, bool) and math.isfinite(limit):
            return elapsed >= limit
        self.log.write("error", where=f"game:{session.game.name}.time_limit", type="ValueError",
                       message=f"time_limit is {limit!r}")
        self._finish(session, "stopped", ["Game ended due to an error."], {}, set())
        return None

    def tick(self) -> None:
        for session in list(self.sessions.values()):
            if self.sessions.get(session.user_id) is not session:
                continue
            elapsed = self.clock.mono() - session.start_mono
            game = session.game
            expired = self._expired(session, elapsed)
            if expired is None:
                continue
            if expired:
                outcome = self._guard(session, f"{game.name}.on_timeout", game.on_timeout)
                self._handle(session, outcome, default_result="timeout")
                if self.sessions.get(session.user_id) is session:  # the game didn't end itself: force it
                    self._finish(session, "timeout", [], {}, set())
            else:
                outcome = self._guard(session, f"{game.name}.on_tick", lambda g=game, e=elapsed: g.on_tick(e))
                self._handle(session, outcome)

    def stop_all(self) -> int:
        """End every running game with no points (?stopgame, ?bot off, shutdown). Returns how many."""
        stopped = list(self.sessions.values())
        for session in stopped:
            self._finish(session, "stopped", [], {}, set())
        return len(stopped)

    # outcomes

    def _handle(self, session: Session, outcome: Outcome | str | None, default_result: str = "won") -> None:
        if not isinstance(outcome, Outcome) or self.sessions.get(session.user_id) is not session:
            return
        if outcome.finished:
            result = outcome.result or default_result
            self._finish(session, result, outcome.messages, outcome.awards, outcome.winners)
        else:
            if outcome.restart_timer:
                session.start_mono = self.clock.mono()
            for text in outcome.messages:
                self._reply(session, text, outcome.coalesce_key)

    def _finish(
        self, session: Session, result: str, messages: list[str], awards: dict[str, int], winners: set[str]
    ) -> None:
        if self.sessions.get(session.user_id) is not session:  # already finished (or replaced): never twice
            return
        del self.sessions[session.user_id]
        self._cooldowns.trigger(("game", session.user_id), self.cooldown_seconds)
        uid = session.user_id
        player = PlayerResult(uid, session.login, session.display_name, awards.get(uid, 0), uid in winners)
        try:
            self.stats.record_round(
                RoundRecord(
                    game=session.game.name,
                    category=session.category,
                    started_by=uid,
                    started_at=session.started_at,
                    ended_at=self.clock.now(),
                    outcome=result,
                    players=[player],
                )
            )
        except Exception as exc:
            logger.exception("could not record round")
            self.log.write("error", where="stats.record_round", type=type(exc).__name__, message=str(exc))
        self.log.write(
            "game_end",
            round=session.key,
            game=session.game.name,
            outcome=result,
            player=session.login,
            points=player.points,
        )
        for text in messages:
            self._reply(session, text)
```

- [ ] **Step 6: Write `bot/games/scramble.py`**

```python
"""Scramble, a personal game: unscramble your word; hints lower the points."""

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
        "Your own word to unscramble: type it, or {p}g <word>. 10 points, or 7 or 4 if you take hints "
        "with {p}hint. {p}scramble categories lists topics. {p}skip ends your game."
    )
    time_limit = 45
    POINTS = (10, 7, 4)
    commands = {
        "hint": ("{p}hint", "Get a hint in your Scramble game (fewer points)."),
        "g": ("{p}g <word>", "Guess the word in your Scramble game."),
    }

    @classmethod
    def category_names(cls, assets: Assets) -> list[str]:
        return [c for c in assets.categories() if any(_valid(w) for w in assets.words(c))]

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
        return self._guess(msg.text, msg)

    def _guess(self, text: str, msg: ChatMessage) -> Outcome | None:
        guess = normalize(text)
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
        if name == "g":
            return self._guess(args, msg)  # a wrong guess stays silent, as in plain chat
        if name != "hint" or self.hints_shown >= len(self.POINTS) - 1:
            return None
        self.hints_shown += 1
        return Outcome(messages=[f"💡 Hint: {self._hint()}"])

    def on_timeout(self) -> Outcome:
        return Outcome(messages=[f"⏰ Time's up! It was {self.word}."], finished=True, result="timeout")

    def reveal(self) -> str:
        return self.word
```

- [ ] **Step 7: Write `bot/games/hangman.py`**

```python
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
```

- [ ] **Step 8: Run the tests**

Run: `.venv/bin/pytest tests/test_manager.py tests/test_scramble.py -q`, then `.venv/bin/pytest -q`.
Expected: `58 passed`, then the whole suite passes (327 passed).

- [ ] **Step 9: Commit**

```bash
git add tests/test_manager.py tests/test_scramble.py bot/games/base.py bot/games/manager.py bot/games/scramble.py bot/games/hangman.py
git commit -m "Phase 2: game options, repeat avoidance, timer restarts, aliases, shared ?g/?hint help"
```

### Task 3: Trivia game

**Files:**
- Replace: `tests/test_trivia.py`, `bot/games/trivia.py`

Spec §3. Questions come from `content/trivia.json` (built in Task 7). Each has an `id`, `category`, `difficulty`, `question`, `answer`, and, for easy ones, three `wrong` options.

- **Starting:** the category comes from the manager. A missing difficulty, or one this category has no questions for, becomes a random available one. Recently seen questions are skipped (`pick_unseen`).
- **Easy:** the four options are shuffled once and lettered A-D, 20 s. One guess: a letter or the option's text (if the text matches two options that read alike, the player is asked for the letter). Right: 5 points; wrong ends the game showing the right option. Nonsense gets one "Answer with ?g and a letter" reminder, then silence. No hints.
- **Medium and hard:** typed, 30 s, 3 guesses. A guess matches if `typo_match` accepts it against any accepted form of the answer (`accepted_answers`): with and without a leading article, accents and ligatures folded ("Solskjær"), apostrophes removed inside words ("Xi'an"), "&" read as "and", number words ("fifty seven"), ordinal words, Roman numerals II-XX and "WW2" as digits ("World War II" = "ww2" = "world war 2"), "St." as "saint"; the place before a comma ("Cupertino, California", "Laika, the dog"; not numbers or lists like "1,776 ft" or "2, 3, 1"), a number without its unit ("88 mph", "1000 km/h", "50's"), a name without its middle initial (letters only: "Class 3-E" keeps its 3), "Mt." as "mount" or left out, a name without its title ("Sir", "Pope", "Professor"...), the answer without a parenthetical (or the parenthetical itself when the rest can't be typed, "Φ (phi)"), an epithet left out ("Kahless the Unforgettable"), initials of a 3-4 word answer ("CPU"), words the question already says left out ("Pancreatic" for "pancreatic cancer", "108" for "Vault 108"), a pair in either order, the last word singular or plural, and for questions about a person ("who...", "which football player...") the surname alone (with its particle: "van halen"). A guess may also put up to 2 words before the answer ("New England Patriots" for "Patriots"), as long as no number is dropped and more than a bare number is left.
- **Hints:** word and letter count with the first letter, then about half the letters in place, describing what is typed (no parenthetical; "phi" for "Φ (phi)"; "characters" when there are digits). A number (also with a unit, "7 years"), or an answer of 1-2 characters, gets one hint that gives nothing away ("A 1-digit number"). Points: medium 10/7/4, hard 15/10/6 by hints used; hints never use up guesses.
- `?help trivia` credits Open Trivia DB and its CC BY-SA 4.0 license, since chat can't see the credits file.
- `opening()` builds the question message; the content test (Task 10) uses it to check every question fits in one chat message.

- [ ] **Step 1: Write `tests/test_trivia.py`**

```python
import random

import pytest

from bot.games.trivia import Trivia
from tests.helpers import make_msg


def make(assets, category="science", level=None, seed=1, recent=()) -> Trivia:
    return Trivia(category, random.Random(seed), assets, level=level, recent=recent)


def g(game: Trivia, text: str, login: str = "alice"):
    return game.on_command("g", text, make_msg(f"?g {text}", login), None)


def test_categories_come_from_the_question_bank(assets):
    assert Trivia.category_names(assets) == ["history", "science"]


def test_easy_is_multiple_choice_with_shuffled_lettered_options(assets):
    game = make(assets, level="easy")
    assert game.item_id == "e1" and game.time_limit == 20
    text = game.start()
    assert text.startswith("❓ (science, easy) What gas do plants absorb? A) ")
    assert text.endswith(" · 20s · answer with {p}g A-D")
    assert sorted(game.options) == ["Carbon dioxide", "Helium", "Nitrogen", "Oxygen"]


def test_easy_right_letter_wins_5(assets):
    game = make(assets, level="easy")
    letter = "ABCD"[game.options.index("Carbon dioxide")]
    out = g(game, letter.lower())
    assert out.finished and out.result == "won" and out.awards == {"id-alice": 5}
    assert out.messages == [f"✅ alice got it: {letter}) Carbon dioxide (+5)"]


def test_easy_option_text_also_counts(assets):
    out = g(make(assets, level="easy"), "carbon dioxide")
    assert out.result == "won"


def test_easy_wrong_answer_ends_the_game(assets):
    game = make(assets, level="easy")
    wrong = "ABCD"[game.options.index("Oxygen")]
    out = g(game, wrong)
    letter = "ABCD"[game.options.index("Carbon dioxide")]
    assert out.finished and out.result == "lost" and out.messages == [f"❌ It was {letter}) Carbon dioxide."]


def test_easy_nonsense_gets_one_reminder_then_silence(assets):
    game = make(assets, level="easy")
    assert g(game, "banana").messages == ["Answer with {p}g and a letter, A to D."]
    assert g(game, "banana") is None
    hint = lambda: game.on_command("hint", "", make_msg("?hint"), None)  # noqa: E731
    assert hint().messages == ["Multiple-choice questions have no hints."]  # said once
    assert hint() is None


def test_typed_start_and_right_answer(assets):
    game = make(assets, level="medium")
    assert game.start() == "❓ (science, medium) Which planet is the largest? · 30s · {p}g <answer> · {p}hint"
    out = g(game, "Jupiter!")
    assert out.result == "won" and out.awards == {"id-alice": 10}


def test_typed_forgives_one_typo_on_long_answers(assets):
    assert g(make(assets, level="medium"), "jupitor").result == "won"
    assert g(make(assets, level="medium"), "jpuitor").result is None  # two edits: a wrong guess


def test_numbers_must_be_exact(assets):
    game = make(assets, category="history", level="hard", recent=("h2",))
    assert game.answer == "1945"
    assert g(game, "1946").messages == ["❌ Not it, 2 guesses left."]
    assert g(game, "1945").awards == {"id-alice": 15}


def test_articles_spaces_and_punctuation_are_ignored(assets):
    game = make(assets, category="history", level="hard", recent=("h1",))
    assert game.answer == "Leonardo da Vinci"
    assert g(game, "leonardo davinci").result == "won"


def test_three_wrong_guesses_lose(assets):
    game = make(assets, level="medium")
    assert g(game, "mars").messages == ["❌ Not it, 2 guesses left."]
    assert g(game, "venus").messages == ["❌ Not it, 1 guess left."]
    out = g(game, "pluto")
    assert out.finished and out.result == "lost" and out.messages == ["💀 Out of guesses! It was Jupiter."]


def test_hints_lower_the_points(assets):
    game = make(assets, category="history", level="hard", recent=("h1",))
    hint = lambda: game.on_command("hint", "", make_msg("?hint"), None)  # noqa: E731
    assert hint().messages == ["💡 3 words, 15 letters, starts with L"]
    second = hint().messages[0]
    assert second.startswith("💡 L ") and second.endswith(" I") and " / " in second
    assert hint() is None  # at most two
    assert g(game, "leonardo da vinci").awards == {"id-alice": 6}


def test_level_is_random_when_not_given_and_falls_back_when_missing(assets):
    assert make(assets, category="history").level == "hard"  # history only has hard questions
    assert make(assets, category="history", level="easy").level == "hard"


def test_recent_questions_are_skipped_and_the_oldest_comes_back_first(assets):
    assert make(assets, category="history", level="hard", recent=("h1",)).item_id == "h2"
    assert make(assets, category="history", level="hard", recent=("h2", "h1")).item_id == "h2"  # seen longest ago
    assert make(assets, category="history", level="hard", recent=("h1", "h2")).item_id == "h1"


def test_timeout_and_reveal(assets):
    game = make(assets, level="medium")
    out = game.on_timeout()
    assert out.finished and out.result == "timeout" and out.messages == ["⏰ Time's up! It was Jupiter."]
    assert game.reveal() == "Jupiter"


def test_unknown_category_raises(assets):
    with pytest.raises(ValueError):
        make(assets, category="planets")


def one_question(tmp_path, answer: str, difficulty: str = "medium") -> Trivia:
    import json
    import uuid

    from bot.assets import Assets

    root = tmp_path / uuid.uuid4().hex / "content"  # content is cached per path: a fresh one each call
    root.mkdir(parents=True)
    q = {"id": "x", "category": "general", "difficulty": difficulty, "question": "Q?", "answer": answer}
    (root / "trivia.json").write_text(json.dumps({"questions": [q]}), encoding="utf-8")
    return Trivia("general", random.Random(1), Assets(root), level=difficulty)


@pytest.mark.parametrize("answer, guess, right", [
    ("Apollo 11", "apollo 13", False),  # numbers inside an answer are exact
    ("Louis XIV", "louis xvi", False),  # so are Roman numerals
    ("C minor", "e minor", False),  # and one-letter words
    ("A-ha", "aha", True),  # "A-" isn't an article
    ("Pokémon", "pokemon", True),  # accents never cost the typo
    ("Pokémon", "pokemno", True),  # ... so a real typo is still allowed
    ("The Beatles", "beatles", True),
    ("The Beatles", "the beatels", True),
    ("Leonardo da Vinci", "leonardo da vinsi", True),
    ("Leonardo da Vinci", "leonardi da vinsi", False),  # one typo in total
])
def test_typed_matching_rules(tmp_path, answer, guess, right):
    out = g(one_question(tmp_path, answer), guess)
    assert (out.result == "won") is right


@pytest.mark.parametrize("answer, guess", [
    ("Cupertino, California", "Cupertino"),
    ("88 mph", "88"),
    ("Three", "3"),
    ("8", "eight"),
    ("World War II", "world war 2"),
    ("September 23rd, 1889", "september 23 1889"),
    ("Hydrogen & Helium", "hydrogen and helium"),
    ("Harry S. Truman", "harry truman"),
    ("Mt. Everest", "everest"),
    ("Mt. Everest", "mount everest"),
    ("Paris (France)", "paris"),
    ("Φ (phi)", "phi"),
    ("Laika, the dog", "laika"),
    ("World War II", "ww2"),
    ("Second World War", "world war 2"),
    ("Sir Alex Ferguson", "alex ferguson"),
    ("Pope Leo III", "leo iii"),
    ("Fifty-Seven", "57"),
    ("Third", "3rd"),
    ("1000 km/h", "1000"),
    ("Xi'an", "xian"),
    ("Ole Gunnar Solskjær", "ole gunnar solskjaer"),
])
def test_natural_variants_of_the_answer_count(tmp_path, answer, guess):
    assert g(one_question(tmp_path, answer), guess).result == "won"


def test_hints_lower_points_without_using_guesses(tmp_path):
    game = one_question(tmp_path, "Leonardo da Vinci", "medium")
    game.on_command("hint", "", make_msg("?hint"), None)
    second = game.on_command("hint", "", make_msg("?hint"), None).messages[0]
    assert sum(ch.isalpha() for ch in second.removeprefix("💡 ")) == 2 + 6  # ends plus about half the middle
    assert game.guesses_left == 3
    assert g(game, "leonardo da vinci").awards == {"id-alice": 4}  # medium: 10, 7, 4


def test_one_hint_lowers_medium_points_to_7(tmp_path):
    game = one_question(tmp_path, "Jupiter", "medium")
    game.on_command("hint", "", make_msg("?hint"), None)
    assert g(game, "jupiter").awards == {"id-alice": 7}


@pytest.mark.parametrize("answer, hint", [("8", "💡 A 1-digit number"), ("1,000", "💡 A 4-digit number"),
                                          ("Ra", "💡 2 letters")])
def test_short_answers_get_one_hint_that_gives_nothing_away(tmp_path, answer, hint):
    game = one_question(tmp_path, answer)
    assert game.on_command("hint", "", make_msg("?hint"), None).messages == [hint]
    assert game.on_command("hint", "", make_msg("?hint"), None) is None


def test_hint_ignores_the_bracketed_part_and_symbols(tmp_path):
    game = one_question(tmp_path, "Shawn Crahan (Clown)")
    assert game.on_command("hint", "", make_msg("?hint"), None).messages == ["💡 2 words, 11 letters, starts with S"]
    game = one_question(tmp_path / "second", "Hydrogen & Helium")  # content is cached per path
    assert game.on_command("hint", "", make_msg("?hint"), None).messages[0].startswith("💡 2 words, 14 letters")


def test_options_that_read_alike_need_the_letter(tmp_path):
    import json

    from bot.assets import Assets

    root = tmp_path / "content"
    root.mkdir(exist_ok=True)
    q = {"id": "x", "category": "general", "difficulty": "easy", "question": "Q?", "answer": "Lord Genome",
         "wrong": ["Lordgenome", "Kingloname", "King Loname"]}
    (root / "trivia.json").write_text(json.dumps({"questions": [q]}), encoding="utf-8")
    game = Trivia("general", random.Random(1), Assets(root), level="easy")
    assert g(game, "lord genome").messages == ["Answer with {p}g and a letter, A to D."]


def test_who_questions_accept_the_surname(tmp_path):
    import json

    from bot.assets import Assets

    root = tmp_path / "content"
    root.mkdir()
    q = {"id": "x", "category": "general", "difficulty": "medium", "question": "Who directed Spirited Away?",
         "answer": "Hayao Miyazaki"}
    (root / "trivia.json").write_text(json.dumps({"questions": [q]}), encoding="utf-8")
    game = Trivia("general", random.Random(1), Assets(root), level="medium")
    assert g(game, "miyazaki").result == "won"


def test_help_credits_open_trivia_db():
    assert "Open Trivia DB, CC BY-SA 4.0" in Trivia.description


@pytest.mark.parametrize("answer, guess", [
    ("1,776 ft", "1"),  # the comma rule is for "City, Region", not numbers
    ("Oh, Inverted World", "oh"),
    ("2, 3, 1", "2"),
    ("low, all", "low"),
    ("Class 3-E", "class e"),  # only middle letters can be dropped, not numbers
])
def test_partial_answers_dont_win(tmp_path, answer, guess):
    assert g(one_question(tmp_path, answer), guess).result != "won"


def test_surname_with_a_particle(tmp_path):
    import json

    from bot.assets import Assets

    root = tmp_path / "content"
    root.mkdir()
    q = {"id": "x", "category": "music", "difficulty": "medium", "question": "Who founded the band?",
         "answer": "Eddie Van Halen"}
    (root / "trivia.json").write_text(json.dumps({"questions": [q]}), encoding="utf-8")
    assert g(Trivia("music", random.Random(1), Assets(root), level="medium"), "van halen").result == "won"


@pytest.mark.parametrize("answer, hint", [("7 years", "💡 A 1-digit number"), ("50's", "💡 A 2-digit number"),
                                          ("Φ (phi)", "💡 3 letters, starts with P")])
def test_hints_describe_what_is_typed(tmp_path, answer, hint):
    game = one_question(tmp_path, answer)
    assert game.on_command("hint", "", make_msg("?hint"), None).messages == [hint]


def test_unusual_digits_never_crash(tmp_path):
    game = one_question(tmp_path, "Fifty-Seven")
    assert g(game, "fifty " + chr(0x10A40)).messages == ["❌ Not it, 2 guesses left."]  # a Kharosthi digit


def test_who_shortcut_needs_a_plain_surname(tmp_path):
    import json

    from bot.assets import Assets

    root = tmp_path / "content"
    root.mkdir()
    q = {"id": "x", "category": "games", "difficulty": "medium", "question": "Who made King's Quest?",
         "answer": "Sierra On-Line"}
    (root / "trivia.json").write_text(json.dumps({"questions": [q]}), encoding="utf-8")
    assert g(Trivia("games", random.Random(1), Assets(root), level="medium"), "line").result != "won"


def asked(tmp_path, question: str, answer: str) -> Trivia:
    import json
    import uuid

    from bot.assets import Assets

    root = tmp_path / uuid.uuid4().hex / "content"
    root.mkdir(parents=True)
    q = {"id": "x", "category": "general", "difficulty": "medium", "question": question, "answer": answer}
    (root / "trivia.json").write_text(json.dumps({"questions": [q]}), encoding="utf-8")
    return Trivia("general", random.Random(1), Assets(root), level="medium")


@pytest.mark.parametrize("question, answer, guess, right", [
    ("Steve Jobs died from which form of cancer?", "Pancreatic", "pancreatic cancer", True),  # question words
    ("What vault in Fallout 3 is home to clones?", "Vault 108", "108", True),
    ("Who won Super Bowl LI?", "Patriots", "new england patriots", True),  # words before the answer
    ("Which football player is on the FIFA 19 cover?", "Lionel Messi", "messi", True),  # a person question
    ("What is the brain of the computer?", "Central Processing Unit", "cpu", True),  # initials
    ("Who founded the Klingon Empire?", "Kahless the Unforgettable", "kahless", True),
    ("How many times was Einstein married?", "Twice", "2", True),
    ("What gas do the sun's layers have most?", "Hydrogen & Helium", "helium and hydrogen", True),
    ("Which instrument has valves?", "French Horn", "french horns", True),  # plural
    ("Which Halo game came after Halo 3?", "Halo 3: ODST", "halo 4 odst", False),  # numbers are never dropped
    ("How many times was Einstein married?", "Twice", "dota 2", False),  # a bare number isn't left over
    ("Who played Ron Swanson?", "Nick Offerman", "no", False),  # no two-letter initials
])
def test_more_natural_forms(tmp_path, question, answer, guess, right):
    assert asked(tmp_path, question, answer)._matches(guess) is right
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/bin/pytest tests/test_trivia.py -q`
Expected: `ModuleNotFoundError: No module named 'bot.games.trivia'`.

- [ ] **Step 3: Write `bot/games/trivia.py`**

```python
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
    "once": "1", "twice": "2", "thrice": "3",
    "st": "saint",
    "ww1": "world war 1", "wwi": "world war 1", "ww2": "world war 2", "wwii": "world war 2",
}
_PHRASES = {"first world war": "world war 1", "second world war": "world war 2"}
_TITLES = frozenset(
    "sir dame count countess professor prof pope officer doctor dr captain lord lady king queen prince princess "
    "emperor empress duke duchess archduke general admiral president".split())
_PERSON_QUESTION = re.compile(
    r"(?i)\bwho\b|\bwhich (?:\w+ ){0,2}(?:person|people|player|actor|actress|singer|artist|rapper|president"
    r"|footballer|character|man|woman|author|writer|director|composer|scientist|athlete|manager|coach"
    r"|mathematician|inventor|painter|explorer|emperor|king|queen|poet|philosopher|musician|drummer"
    r"|guitarist|youtuber|streamer|founder|leader|ruler|monarch|pope|chef|designer)s?\b")
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
        if out and out[-1] in {str(n) for n in _TENS.values()} and w in "123456789" and len(w) == 1:
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
    asked = set(_canonical(question).split())
    for form in list(forms):
        words = form.split()
        rest = [w for w in words if w not in asked]  # "What type of cancer ...?" -> "pancreatic"
        if rest and len(rest) < len(words) and any(len(w) >= 4 or w.isdigit() for w in rest):
            forms.add(" ".join(rest))  # also "Vault 108" -> "108" when the question says "vault"
        if " the " in f" {form} " and words[0] != "the":  # "kahless the unforgettable" -> "kahless"
            before = form.split(" the ")[0]
            if len(before) >= 4:
                forms.add(before)
        if words[:1] == ["letter"] and len(words) == 2:  # "the letter a" -> "a"
            forms.add(words[1])
        if 3 <= len(words) <= 4 and all(w.isalpha() for w in words):  # "central processing unit" -> "cpu"
            forms.add("".join(w[0] for w in words))
        if form.count(" and ") == 1:  # "hydrogen and helium" = "helium and hydrogen"
            left, right = form.split(" and ")
            forms.add(f"{right} and {left}")
    for form in list(forms):  # the last word singular or plural: "french horns", "capillary"
        *head, last = form.split()
        if not last.isalpha() or len(last) < 3:
            continue
        if last.endswith("ies") and len(last) >= 5:
            other = last[:-3] + "y"
        elif last.endswith("s") and len(last) >= 5:
            other = last[:-1]
        elif last.endswith("y") and len(last) >= 4:
            other = last[:-1] + "ies"
        else:
            other = last + "s"
        forms.add(" ".join([*head, other]))
    raw_name = _PARENTHETICAL.sub("", answer).split()
    if _PERSON_QUESTION.search(question) and raw_name and raw_name[-1].isalpha():  # not "Sierra On-Line"
        name = _canonical(" ".join(raw_name)).split()  # "Who directed ...?" -> "miyazaki", "van halen"
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
        self._asked = set(_canonical(self.question).split())
        self.guesses_left = self.GUESSES
        self.hints_used = 0
        self._told_how = False  # the "answer with A-D" reminder is sent at most once
        self._told_no_hints = False
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
        guesses = _forms(guess)
        for form in list(guesses):
            words = form.split()
            rest = [w for w in words if w not in self._asked]  # "pancreatic cancer" when the question says cancer
            if rest and len(rest) < len(words):
                guesses.add(" ".join(rest))
            for n in (1, 2):  # "new england patriots" for "Patriots": the answer, with up to 2 words before it
                dropped, kept = words[:n], words[n:]
                # never drop a number ("halo 4 recon" isn't "recon"), and never leave only one ("dota 2" isn't "2")
                if kept and not any(ch.isdigit() for w in dropped for ch in w) and any(w.isalpha() for w in kept):
                    guesses.add(" ".join(kept))
        return any(typo_match(g, a, TYPO_MIN_LETTERS) for g in guesses for a in self._accepted)

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
        if self.easy:
            if self._told_no_hints:
                return None
            self._told_no_hints = True
            return Outcome(messages=["Multiple-choice questions have no hints."])
        if self.hints_used >= (1 if short else len(self.POINTS[self.level]) - 1):
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
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_trivia.py -q`, then `.venv/bin/pytest -q`.
Expected: `80 passed`, then the whole suite passes (407 passed).

- [ ] **Step 5: Commit**

```bash
git add tests/test_trivia.py bot/games/trivia.py
git commit -m "Phase 2: Trivia game"
```

### Task 4: Riddle game

**Files:**
- Replace: `tests/test_riddle.py`, `bot/games/riddle.py`

Spec §4. Riddles come from `content/riddles.json` (Task 8): `riddle`, `answers` (main answer first), and `clue`.

- **Start:** `🧩 <riddle> · 60s · ?g <answer> · ?hint`. The id is a hash of the riddle text, so it survives reordering the file.
- **Guesses:** 3. Guess and answers are compared as words: apostrophes removed (all kinds, after NFKC), so "I'm" can't leave a lone "m" that wins the letter riddles; a leading article dropped; accents folded. A guess wins if it contains an accepted answer, preferring the longest one it contains. Spacing may differ by one word ("rain bow") and the answer may be plural ("es" only after s, x, z, ch or sh, so "pin" never matches "pines").
- **Not a win:** a list, which costs a guess as "One answer per guess": more than 2 words beyond the answer (not counting filler like "I think it's a" or words from the riddle itself), or an either-or naming anything else ("nunu or mary"; a trailing "or something" is fine). Also not a win: a negation right before the answer ("not a clock", unless the answer appears again un-negated; an opening "no," is just an interjection); for number answers, a different number not in the riddle ("3-2=1" when the answer is 2); and for single-letter answers, any other letter ("a, e, i", "a e"; but "is it a m" and "e I think" are fine) or any "or".
- **Hints:** the clue, then the main answer's word and letter count and first letter (no first letter for a 1-2 letter answer, which it would give away). Points 10/7/4.

- [ ] **Step 1: Write `tests/test_riddle.py`**

```python
import random

import pytest

from bot.games.riddle import Riddle, riddle_id
from tests.helpers import make_msg


def make(assets, seed=1, recent=()) -> Riddle:
    game = Riddle(None, random.Random(seed), assets, recent=recent)
    if game.answers[0] != "clock":  # the tests below use the clock riddle
        clock_id = next(riddle_id(r) for r in assets.json("riddles") if r["answers"][0] == "clock")
        others = tuple(riddle_id(r) for r in assets.json("riddles") if riddle_id(r) != clock_id)
        game = Riddle(None, random.Random(seed), assets, recent=others)
    return game


def g(game: Riddle, text: str):
    return game.on_command("g", text, make_msg(f"?g {text}"), None)


def test_start_message_and_item_id(assets):
    game = make(assets)
    assert game.start() == "🧩 What has hands but can't clap? · 60s · {p}g <answer> · {p}hint"
    assert game.item_id == riddle_id({"riddle": "What has hands but can't clap?"})


def test_answer_inside_a_short_sentence_wins(assets):
    out = g(make(assets), "is it a clock?")
    assert out.finished and out.result == "won" and out.awards == {"id-alice": 10}
    assert out.messages == ["✅ alice got it: clock (+10)"]


def test_alternative_answers_and_plurals_count(assets):
    assert g(make(assets), "a watch").result == "won"
    assert g(make(assets), "clocks").result == "won"


def test_a_list_of_answers_costs_a_guess(assets):
    game = make(assets)
    out = g(game, "towel map keyboard piano candle clock")
    assert not out.finished and out.messages == ["❌ One answer per guess, 2 guesses left."]


def test_three_wrong_guesses_lose(assets):
    game = make(assets)
    assert g(game, "a map").messages == ["❌ Not it, 2 guesses left."]
    assert g(game, "piano").messages == ["❌ Not it, 1 guess left."]
    out = g(game, "teapot")
    assert out.finished and out.result == "lost" and out.messages == ["💀 Out of guesses! It was: clock."]


def test_hints_are_clue_then_letters_and_lower_the_points(assets):
    game = make(assets)
    hint = lambda: game.on_command("hint", "", make_msg("?hint"), None)  # noqa: E731
    assert hint().messages == ["💡 Clue: You probably check me several times a day."]
    assert hint().messages == ["💡 5 letters, starts with C"]
    assert hint() is None
    assert g(game, "clock").awards == {"id-alice": 4}


def test_empty_guess_is_ignored(assets):
    assert g(make(assets), "  ?! ") is None


def test_recent_riddles_are_skipped(assets):
    clock_id = riddle_id({"riddle": "What has hands but can't clap?"})
    assert Riddle(None, random.Random(1), assets, recent=(clock_id,)).answers == ["towel"]


def test_timeout_and_reveal(assets):
    game = make(assets)
    assert game.on_timeout().messages == ["⏰ Time's up! It was: clock."]
    assert game.reveal() == "clock"


def test_apostrophes_are_removed_not_split(tmp_path):
    import json

    from bot.assets import Assets

    root = tmp_path / "content"
    root.mkdir()
    riddle = {"riddle": "What comes once in a minute and twice in a moment?", "answers": ["m", "letter m"],
              "clue": "Look at the spelling."}
    (root / "riddles.json").write_text(json.dumps([riddle]), encoding="utf-8")
    game = Riddle(None, random.Random(1), Assets(root))
    assert g(game, "I'm guessing time").messages == ["❌ Not it, 2 guesses left."]  # not a lone "m"
    assert g(game, "the letter M").result == "won"


def riddle(tmp_path, text: str, answers: list[str]) -> Riddle:
    import json
    import uuid

    from bot.assets import Assets

    root = tmp_path / uuid.uuid4().hex / "content"  # content is cached per path: a fresh one each call
    root.mkdir(parents=True)
    entry = {"riddle": text, "answers": answers, "clue": "A clue."}
    (root / "riddles.json").write_text(json.dumps([entry]), encoding="utf-8")
    return Riddle(None, random.Random(1), Assets(root))


def outcome(game: Riddle, guess: str) -> str:
    out = g(game, guess)
    if out.result == "won":
        return "won"
    return "list" if "One answer per guess" in out.messages[0] else "wrong"


@pytest.mark.parametrize("answers, guess, expected", [
    (["clock"], "I think it's a clock", "won"),  # filler words don't make a sentence a list
    (["clock"], "could it be a big clock?", "won"),
    (["clock"], "map towel clock egg", "list"),
    (["clock"], "clock or watch", "list"),  # either-or is two guesses
    (["clock"], "not a clock", "wrong"),
    (["rainbow"], "rain bow", "won"),  # spacing may differ by a word
    (["tea pot"], "teapot", "won"),
    (["matches"], "a match", "won"),
    (["pines"], "a pin", "wrong"),  # "es" plurals only after s, x, z, ch, sh
    (["shoes"], "sho", "wrong"),
    (["pokemon"], "Pokémon!", "won"),  # accents don't matter
    (["problems", "too many problems"], "because it had too many problems", "won"),  # the longest answer counts
])
def test_matching_rules(tmp_path, answers, guess, expected):
    assert outcome(riddle(tmp_path, "What is it?", answers), guess) == expected


def test_words_from_the_riddle_are_not_extra_answers(tmp_path):
    game = riddle(tmp_path, "A rooster lays an egg on a barn roof. Which way does it roll?", ["dont lay", "no egg"])
    assert outcome(game, "roosters don't lay eggs silly") == "won"


def test_a_different_number_is_wrong(tmp_path):
    game = riddle(tmp_path, "You have three apples and take away two. How many do you have?", ["two", "2"])
    assert outcome(game, "3-2=1") == "wrong"
    assert outcome(game, "2 apples") == "won"


def test_letter_answers_reject_hedges(tmp_path):
    text = "What comes once in a minute and twice in a moment?"
    assert outcome(riddle(tmp_path, text, ["m", "letter m"]), "is it a m?") == "won"
    assert outcome(riddle(tmp_path, text, ["m", "letter m"]), "the letter M") == "won"
    assert outcome(riddle(tmp_path, text, ["m", "letter m"]), "is it a letter m") == "won"
    assert outcome(riddle(tmp_path, text, ["m", "letter m"]), "m or n") == "list"
    assert outcome(riddle(tmp_path, text, ["m", "letter m"]), "n m t") == "list"


def test_short_answers_get_no_first_letter_hint(tmp_path):
    game = riddle(tmp_path, "What comes once in a minute?", ["m"])
    game.on_command("hint", "", make_msg("?hint"), None)
    assert game.on_command("hint", "", make_msg("?hint"), None).messages == ["💡 1 letter"]


def test_multi_word_hint(tmp_path):
    game = riddle(tmp_path, "What do you call a deer with no eyes?", ["no idea"])
    game.on_command("hint", "", make_msg("?hint"), None)
    assert game.on_command("hint", "", make_msg("?hint"), None).messages == ["💡 2 words, 6 letters, starts with N"]


@pytest.mark.parametrize("riddle_text, answers, guess, expected", [
    ("Mary's father has five daughters: Nana, Nene, Nini, Nono. What's the fifth called?", ["mary"],
     "nunu or mary", "list"),  # either-or counts the riddle's own words too
    ("What has hands but can't clap?", ["clock"], "I know this one, it's a clock", "won"),  # "one" isn't a guess
    ("Some months have 30 days and some have 31. How many have 28?", ["all", "12"], "all 12 have 28 days", "won"),
    ("What has hands but can't clap?", ["clock"], "no, a clock", "won"),  # "no," is an interjection
    ("What has hands but can't clap?", ["clock", "watch"], "not a clock, it's a watch", "won"),
    ("What has hands but can't clap?", ["clock"], "a clock or something", "won"),
    ("What appears once in a year and twice in a week?", ["e", "letter e"], "a or e", "list"),
    ("What appears once in a year and twice in a week?", ["e", "letter e"], "a e", "list"),
    ("What appears once in a year and twice in a week?", ["e", "letter e"], "e I think", "won"),
    ("What comes once in a minute?", ["m", "letter m"], "I´m guessing time", "wrong"),  # ´ as an apostrophe
    ("What comes once in a minute?", ["m", "letter m"], "I'm pretty sure it's m", "won"),
])
def test_review_cases(tmp_path, riddle_text, answers, guess, expected):
    assert outcome(riddle(tmp_path, riddle_text, answers), guess) == expected
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/bin/pytest tests/test_riddle.py -q`
Expected: `ModuleNotFoundError: No module named 'bot.games.riddle'`.

- [ ] **Step 3: Write `bot/games/riddle.py`**

```python
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
NUMBER_VALUES = {
    **{w: str(n) for n, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
        "seventeen eighteen nineteen twenty".split())},
    **{w: str(10 * n) for n, w in enumerate("thirty forty fifty sixty seventy eighty ninety".split(), start=3)},
    "hundred": "100",
    "thousand": "1000",
}
_INTERJECTION = re.compile(r"(?i)\b(?:no|nope|nah)\s*[,.!;:]+")  # "no, a clock" isn't a negation
_VAGUE_TAIL = re.compile(r"(?i)\s+or\s+(?:something|smth|whatever|so|anything)(?:\s+like\s+that)?[\s.!?]*$")
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


def _words(text: str, drop_article: bool = True) -> list[str]:
    """A guess or answer as comparable words: apostrophes, a leading article, an opening "no," and a
    trailing "or something" dropped; accents folded."""
    text = _APOSTROPHES.sub("", text)  # before NFKC too, which turns "´" into a space and an accent
    text = _APOSTROPHES.sub("", unicodedata.normalize("NFKC", text))
    text = _VAGUE_TAIL.sub("", _INTERJECTION.sub(" ", text))
    if drop_article:
        text = strip_article(text)
    return fold_accents(normalize(text)).split()


def _numbers(words: list[str]) -> set[str]:
    """Numbers named, as digits: "three" and "3" are the same number."""
    digits = {w for w in words if w.isascii() and w.isdigit()}  # ASCII only: int() rejects other digit characters
    return {str(int(w)) for w in digits} | {NUMBER_VALUES[w] for w in words if w in NUMBER_VALUES}


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
        # when the answer is a number, a guess naming a different one ("3-2=1" for 2) is wrong
        self._answer_numbers = set().union(*(_numbers(a) for a in self._accepted))
        self._riddle_numbers = _numbers(self._context)
        self.guesses_left = self.GUESSES
        self.hints_used = 0

    def start(self) -> str:
        return f"🧩 {self.riddle} · {self.time_limit}s · {{p}}g <answer> · {{p}}hint"

    def _matches(self, words: list[str]) -> list[tuple[list[str], int, int]]:
        """Every place the guess names an accepted answer: (answer, start, length in guess words).
        Spacing may differ by one word ("rain bow", "tea pot"), and the answer may be plural."""
        found = []
        for answer in self._accepted:
            joined = "".join(answer)
            for size in sorted({len(answer) - 1, len(answer), len(answer) + 1} - {0}):
                for i in range(len(words) - size + 1):
                    if _same_word("".join(words[i : i + size]), joined):
                        found.append((answer, i, size))
        return found

    @staticmethod
    def _negated(words: list[str], start: int) -> bool:
        before = [w for w in words[:start] if w not in ("a", "an", "the")]
        return bool(before) and before[-1] in NEGATIONS

    def _is_answer(self, words: list[str], raw: list[str]) -> tuple[bool, bool]:
        """(right, a list): does the guess name the answer, and is it really several guesses at once?
        `raw` is the guess with its leading article kept, for the single-letter riddles."""
        found = [m for m in self._matches(words) if not self._negated(words, m[1])]  # "not a clock" doesn't count
        if not found:
            return False, False
        answer, start, size = max(found, key=lambda m: _content(m[0]))  # the longest answer named
        letter = len(answer) == 1 and len(answer[0]) == 1 and answer[0].isalpha()  # the M, E and W riddles
        if "or" in words:  # either-or: anything else named besides the answer makes it a hedge
            outside = words[:start] + words[start + size :]
            if letter or any(w not in FILLER for w in outside):
                return False, True
        elif _content(words, self._context) > max(1, _content(answer)) + EXTRA_WORDS:
            return False, True
        if self._answer_numbers and _numbers(words) - self._answer_numbers - self._riddle_numbers:
            return False, False  # "3-2=1" when the answer is 2
        if letter and any(self._other_letter(raw, i, answer[0]) for i in range(len(raw))):
            return False, True  # "a, e, i" or "y e a r" hedges between letters
        return True, False

    @staticmethod
    def _other_letter(words: list[str], i: int, answer: str) -> bool:
        """Is words[i] a single letter other than the answer? The pronoun "I" ("e I think") and "a" right
        before a consonant answer ("is it a m") don't count; "a e" is a hedge (it would be "an e")."""
        w = words[i]
        if len(w) != 1 or not w.isalpha() or w == answer:
            return False
        following = words[i + 1] if i + 1 < len(words) else None
        if w == "i" and (i == 0 or (following is not None and len(following) > 1)):
            return False
        if w == "a" and following in (answer, "letter") and answer not in "aeiou":  # "is it a letter m"
            return False
        return True

    def on_command(self, name: str, args: str, msg: ChatMessage, now: datetime) -> Outcome | None:
        if name == "hint":
            return self._hint()
        words = _words(args)
        if name != "g" or not words:
            return None
        right, too_long = self._is_answer(words, _words(args, drop_article=False))
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
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_riddle.py -q`, then `.venv/bin/pytest -q`.
Expected: `38 passed`, then the whole suite passes (445 passed).

- [ ] **Step 5: Commit**

```bash
git add tests/test_riddle.py bot/games/riddle.py
git commit -m "Phase 2: Riddle game"
```

### Task 5: Higher or Lower game

**Files:**
- Replace: `tests/test_higherlower.py`, `bot/games/higherlower.py`

Spec §5. Terms come from `content/higherlower.json` (Task 9): `name` and monthly `views`.

- **Pairs:** the next term differs from the current one by at least 15% and hasn't been used this game.
- **Answers:** `?g higher|h|more|high|up` or `?g lower|l|less|low|down`; a tie counts as right either way.
- **Right:** reveal the number, streak +1, the revealed term becomes the comparison, and `restart_timer` gives the next answer a fresh 20 s.
- **Wrong or timeout:** the game ends and the streak is the points (a first wrong answer just says "Game over."). A streak of 5 or more counts as a win in `?gamestats` (a choice made while building; the spec only fixes the points). Running out of terms wins.
- The game remembers the player from their answers, so a timeout can credit the streak.

- [ ] **Step 1: Write `tests/test_higherlower.py`**

```python
import random

from bot.games.higherlower import HigherLower
from tests.helpers import make_msg


def make(assets, seed=1) -> HigherLower:
    return HigherLower(None, random.Random(seed), assets)


def g(game: HigherLower, text: str):
    return game.on_command("g", text, make_msg(f"?g {text}"), None)


def right(game: HigherLower) -> str:
    return "higher" if game.next["views"] >= game.current["views"] else "lower"


def wrong(game: HigherLower) -> str:
    return "lower" if right(game) == "higher" else "higher"


def test_start_shows_the_first_number_and_asks_about_the_second(assets):
    game = make(assets)
    text = game.start()
    assert text.startswith(f"↕️ {game.current['name']} gets ")
    assert f"Does {game.next['name']} get higher or lower? · 20s · {{p}}g higher / {{p}}g lower" in text


def test_pairs_differ_by_at_least_15_percent(assets):
    for seed in range(30):
        game = make(assets, seed)
        a, b = game.current["views"], game.next["views"]
        assert max(a, b) >= 1.15 * min(a, b)


def test_right_answer_extends_the_streak_and_restarts_the_timer(assets):
    game = make(assets)
    revealed = game.next
    out = g(game, right(game)[0])  # "h" or "l" works too
    assert not out.finished and out.restart_timer and game.streak == 1
    assert out.messages[0].startswith(f"✅ {revealed['name']}: ")
    assert game.current is revealed  # the revealed term is the next comparison


def test_wrong_answer_ends_the_game_with_the_streak_as_points(assets):
    game = make(assets)
    g(game, right(game))
    g(game, right(game))
    out = g(game, wrong(game))
    assert out.finished and out.result == "lost" and out.awards == {"id-alice": 2} and out.winners == set()
    assert out.messages[0].endswith("Game over, streak 2 (+2).")


def test_wrong_first_answer_scores_nothing(assets):
    game = make(assets)
    out = g(game, wrong(game))
    assert out.finished and out.awards == {} and out.messages[0].endswith(". Game over.")


def test_up_and_down_work_too(assets):
    game = make(assets)
    assert g(game, "up" if right(game) == "higher" else "down").restart_timer


def test_using_up_every_term_wins(assets):
    game = make(assets)
    outs = []
    while True:
        out = g(game, right(game))
        outs.append(out)
        if out.finished:
            break
    assert out.result == "won" and "You used up every term!" in out.messages[0]
    assert game.streak == len(outs) <= 3


def test_streak_of_five_counts_as_a_win(assets):
    game = make(assets)
    game.streak = 5
    game.player_id = "id-alice"
    out = game.on_timeout()
    assert out.result == "timeout" and out.awards == {"id-alice": 5} and out.winners == {"id-alice"}


def test_nonsense_gets_one_reminder(assets):
    game = make(assets)
    assert g(game, "maybe").messages == ["Answer with {p}g higher or {p}g lower."]
    assert g(game, "maybe") is None


def test_reveal(assets):
    game = make(assets)
    assert game.reveal().startswith(f"{game.next['name']}: ")


def test_close_numbers_are_never_paired(tmp_path):
    import json

    from bot.assets import Assets

    root = tmp_path / "content"
    root.mkdir()
    terms = [{"name": "A", "views": 100_000}, {"name": "B", "views": 110_000}, {"name": "C", "views": 200_000}]
    (root / "higherlower.json").write_text(json.dumps({"terms": terms}), encoding="utf-8")
    for seed in range(30):
        game = HigherLower(None, random.Random(seed), Assets(root))
        assert {game.current["name"], game.next["name"]} != {"A", "B"}  # only 10% apart
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/bin/pytest tests/test_higherlower.py -q`
Expected: `ModuleNotFoundError: No module named 'bot.games.higherlower'`.

- [ ] **Step 3: Write `bot/games/higherlower.py`**

```python
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
HIGHER = {"higher", "h", "more", "high", "up"}
LOWER = {"lower", "l", "less", "low", "down"}


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
        recent: tuple[str, ...] = (),
    ) -> None:
        super().__init__(category, rng, assets, level=level, recent=recent)
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
            score = f", streak {self.streak} (+{self.streak})" if self.streak else ""
            return self._end(f"❌ {self._result()}. Game over{score}.", "lost")
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
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_higherlower.py -q`, then `.venv/bin/pytest -q`.
Expected: `11 passed`, then the whole suite passes (456 passed).

- [ ] **Step 5: Commit**

```bash
git add tests/test_higherlower.py bot/games/higherlower.py
git commit -m "Phase 2: Higher or Lower game"
```

### Task 6: Register the games; flows, config and README

**Files:**
- Replace: `tests/test_flows.py`, `tests/test_cli.py`, `tests/test_config.py`, `tests/test_stats_help_commands.py`, `bot/games/__init__.py`, `bot/stats_commands.py`, `config.toml`, `pyproject.toml`, `README.md`

`ALL_GAMES` gains Trivia, Riddle and Higher or Lower, and `config.toml` enables all five. `pyproject.toml` packages the JSON and Markdown content files. `?leaderboard` and `?gamestats` accept a game's aliases (`?leaderboard hl`). The flow tests play one game of each through `BotCore`, and the README documents the commands. The console test and the shipped-config test now expect all five games.

- [ ] **Step 1: Write `tests/test_flows.py`**

```python
"""End-to-end flows: BotCore driven through console-style chat lines, with a fake clock."""

import asyncio
import json
import random
import sqlite3
from itertools import count

import pytest

from bot.activity_log import ActivityLog
from bot.config import ConfigError
from bot.connectors.base import AuthRequired, ReadyInfo, SendResult
from bot.connectors.console import ConsoleConnector, parse_console_line
from bot.core import BotCore
from bot.stats import StatsStore
from tests.helpers import FakeHttp, make_config, make_msg


class Bot:
    def __init__(self, tmp_path, clock, assets, *, db=":memory:", lines=None, connector=None, http=None, **config):
        self.clock = clock
        self.ids = count(1)
        self.connector = connector or ConsoleConnector(clock=clock, lines=lines, out=lambda s: None)
        self.log = ActivityLog(tmp_path / "logs", clock)
        self.core = BotCore(
            config=make_config(tmp_path, **config),
            connector=self.connector,
            stats=StatsStore(db),
            log=self.log,
            clock=clock,
            assets=assets,
            http=http or FakeHttp(),
            rng=random.Random(1),
        )

    async def say(self, line: str) -> None:
        await self.core.on_message(parse_console_line(line, self.clock, self.ids))
        await self.core.outbox.flush_ready()

    async def wait(self, seconds: float) -> None:
        self.clock.advance(seconds)
        self.core.tick()
        await self.core.outbox.flush_ready()

    @property
    def out(self) -> list[str]:
        return self.connector.sent

    def events(self) -> list[dict]:
        path = self.log.path_for(self.clock.now().date())
        return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def bot(tmp_path, clock, assets) -> Bot:
    return Bot(tmp_path, clock, assets)


async def test_scramble_round_to_leaderboard(bot: Bot):
    await bot.say("alice: ?scramble animals")
    assert bot.out[-1].startswith("🔤 Unscramble (animals): ")
    await bot.say("bob: alligator")  # not bob's game
    await bot.say("alice: crocodile")
    await bot.say("alice: alligator")
    assert bot.out[-1] == "✅ alice got it: ALLIGATOR (+10)"
    await bot.say("carol: ?leaderboard")
    assert bot.out[-1] == "🏆 Top 1 overall: 1. alice (10)"
    await bot.say("alice: ?gamestats")
    assert bot.out[-1] == "📊 alice: 10 pts, 1 win, 1 played | scramble 1W/1P 10pts"


async def test_two_players_play_at_once(bot: Bot):
    await bot.say("alice: ?scramble animals")
    await bot.say("bob: ?scramble animals")  # no chat-wide cooldown on starting games
    assert len(bot.core.games.sessions) == 2
    await bot.say("bob: alligator")
    await bot.say("alice: alligator")
    assert bot.out[-2:] == ["✅ bob got it: ALLIGATOR (+10)", "✅ alice got it: ALLIGATOR (+10)"]


async def test_scramble_hint_lowers_points(bot: Bot):
    await bot.say("alice: ?scramble animals")
    await bot.say("alice: ?hint")
    assert bot.out[-1] == "💡 Hint: A _ _ _ _ _ _ _ R"
    await bot.say("alice: alligator")
    assert bot.out[-1] == "✅ alice got it: ALLIGATOR (+7)"


async def test_hangman_win_through_g_and_plain_letters_ignored(bot: Bot):
    await bot.say("alice: ?hangman animals")
    answer = bot.core.games.sessions["console-alice"].game.answer
    assert "guess with ?g <letter> or ?g <answer>" in bot.out[-1]
    sent_before = len(bot.out)
    await bot.say("alice: W")
    assert len(bot.out) == sent_before and bot.core.games.sessions["console-alice"].game.wrong == []
    await bot.say(f"alice: ?g {answer.lower()}")
    assert bot.out[-1] == f"🎉 alice solved it: {answer} (+10)"


async def test_hangman_loss(bot: Bot):
    await bot.say("alice: ?hangman animals")
    game = bot.core.games.sessions["console-alice"].game
    misses = [c for c in "ZQXJKVWYUBDF" if c not in game.answer][:6]
    for letter in misses:
        await bot.say(f"alice: ?g {letter}")
        bot.clock.advance(2)  # Hangman allows one guess every 2 s
    assert bot.out[-1] == f"💀 Out of lives! The word was {game.answer}."
    assert bot.core.games.sessions == {}


async def test_skip_ends_your_game(bot: Bot):
    await bot.say("alice: ?scramble animals")
    await bot.say("alice: ?skip")
    assert bot.out[-1] == "⏭️ Skipped. It was ALLIGATOR."


async def test_game_times_out(bot: Bot):
    await bot.say("alice: ?scramble animals")
    await bot.wait(45)
    assert bot.out[-1] == "⏰ Time's up! It was ALLIGATOR."


async def test_busy_brake_when_messages_back_up(tmp_path, clock, assets):
    bot = Bot(tmp_path, clock, assets)
    for i in range(10):
        bot.core.outbox.enqueue(f"backlog {i}")
    await bot.core.on_message(parse_console_line("alice: ?scramble", clock, bot.ids))
    assert bot.core.outbox.pending()[-1] == "Too many games running right now, try again in a moment."
    assert bot.core.games.sessions == {}


async def test_busy_brake_skips_fun_stats_and_help_but_not_control(tmp_path, clock, assets):
    bot = Bot(tmp_path, clock, assets)
    for i in range(10):
        bot.core.outbox.enqueue(f"backlog {i}")
    for line in ("alice: ?coinflip", "bob: ?gamestats", "carol: ?help", "dave: ?cookie"):
        await bot.core.on_message(parse_console_line(line, clock, bot.ids))
    assert len(bot.core.outbox) == 10
    await bot.core.on_message(parse_console_line("@mod: ?bot status", clock, bot.ids))
    assert len(bot.core.outbox) == 11


async def test_non_mod_cannot_control_and_mod_can_pause_and_resume(bot: Bot):
    await bot.say("random: ?bot shutdown")
    await bot.say("random: ?bot off")
    assert bot.out == [] and not bot.core.paused
    await bot.say("alice: ?scramble animals")
    await bot.say("@mod: ?bot off")
    assert bot.core.paused
    assert bot.core.games.sessions == {}
    assert "Bot paused by mod. ?bot on to resume." in bot.out
    before = len(bot.out)
    bot.clock.advance(60)
    await bot.say("alice: ?scramble animals")
    await bot.say("alice: ?8ball hi")
    assert len(bot.out) == before
    await bot.say("@mod: ?bot status")
    assert bot.out[-1].startswith("PAUSED · up 1m · games: 0 running · v")
    await bot.say("@mod: ?bot on")
    assert bot.out[-1] == "Bot resumed by mod."
    await bot.say("alice: ?coinflip")
    assert bot.out[-1] in ("🪙 Heads", "🪙 Tails")


async def test_non_mod_cannot_resume_a_paused_bot(bot: Bot):
    await bot.say("@mod: ?bot off")
    await bot.say("random: ?bot on")
    assert bot.core.paused


async def test_owner_can_control_without_mod_badge(bot: Bot):
    await bot.say("robert: ?bot off")
    assert bot.core.paused


async def test_stopgame_stops_everyones_games(bot: Bot):
    await bot.say("@mod: ?stopgame")
    assert bot.out[-1] == "No games are running."
    await bot.say("alice: ?scramble animals")
    await bot.say("bob: ?hangman animals")
    await bot.say("random: ?stopgame")  # not a mod: ignored
    assert len(bot.core.games.sessions) == 2
    await bot.say("@mod: ?stopgame")
    assert bot.out[-1] == "🛑 Stopped 2 games. No points awarded."
    assert bot.core.games.sessions == {}


async def test_paused_state_survives_restart(tmp_path, clock, assets):
    db = tmp_path / "data" / "bot.db"
    first = Bot(tmp_path, clock, assets, db=db)
    await first.say("@mod: ?bot off")
    first.core.stats.close()
    second = Bot(tmp_path, clock, assets, db=db)
    assert second.core.paused
    await second.say("alice: ?8ball hi")
    assert second.out == []


async def test_shared_chat_and_own_messages_are_ignored(bot: Bot):
    await bot.core.on_message(make_msg("?bot off", "othermod", mod=True, source_channel_id="other-channel"))
    await bot.core.on_message(make_msg("?coinflip", "me", user_id="console-bot"))
    await bot.core.on_message(make_msg("?coinflip", "local", source_channel_id="console"))
    await bot.core.outbox.flush_ready()
    assert not bot.core.paused
    assert len(bot.out) == 1  # only the message whose source is our own channel


async def test_cookie_daily_limit_across_midnight(bot: Bot):
    await bot.say("alice: ?cookie")
    assert bot.out[-1] == "🥠 Good things are coming."
    bot.clock.advance(11)
    await bot.say("alice: ?cookie")
    assert bot.out[-1].startswith("You already opened today's cookie. Next one in 11h 59m")
    await bot.wait(12 * 3600)
    await bot.say("alice: ?cookie")
    assert bot.out[-1] == "🥠 Good things are coming."


async def test_fact_api_failure_falls_back(tmp_path, clock, assets):
    bot = Bot(tmp_path, clock, assets, http=FakeHttp({}))
    await bot.say("alice: ?catfact")
    assert bot.out[-1] == "🐱 fallback catfacts line"


async def test_quick_commands_have_user_and_global_cooldowns(bot: Bot):
    await bot.say("alice: ?coinflip")
    await bot.say("alice: ?coinflip")
    await bot.say("bob: ?coinflip")
    assert len(bot.out) == 1
    bot.clock.advance(5)
    await bot.say("bob: ?coinflip")
    assert len(bot.out) == 2


async def test_personal_commands_are_not_blocked_by_someone_elses(bot: Bot):
    await bot.say("alice: ?gamestats")
    await bot.say("bob: ?gamestats")
    await bot.say("carol: ?help")
    await bot.say("dave: ?help")
    await bot.say("erin: ?cookie")
    await bot.say("frank: ?cookie")
    assert len(bot.out) == 6
    await bot.say("gina: ?coinflip")
    await bot.say("hank: ?coinflip")  # public commands keep the chat-wide cooldown
    assert len(bot.out) == 7


async def test_not_being_a_mod_slows_sending_down(tmp_path, clock, assets):
    bot = Bot(tmp_path, clock, assets)
    await bot.core._on_ready(ReadyInfo("chan", "chan", is_mod=False))
    assert bot.core.outbox.rate == 0.6 and bot.core.outbox.burst == 1


async def test_losing_mod_status_while_running_slows_sending_down(tmp_path, clock, assets):
    bot = Bot(tmp_path, clock, assets)
    await bot.core._on_ready(ReadyInfo("chan", "chan", is_mod=True))
    assert bot.core.outbox.rate > 0.6  # unchanged while modded
    await bot.core._on_ready(ReadyInfo("chan", "chan", is_mod=False))
    assert bot.core.outbox.rate == 0.6 and bot.core.outbox.burst == 1
    assert [e["event"] for e in bot.events()].count("startup") == 1


async def test_help_overview_lists_real_commands_under_500_chars(bot: Bot):
    await bot.say("alice: ?help")
    text = bot.out[-1]
    assert text == (
        "Games: ?scramble ?hangman ?skip | Stats: ?leaderboard ?gamestats | "
        "Fun: ?8ball ?coinflip ?catfact ?dogfact ?fact ?dadjoke ?cookie · ?help <command> for details"
    )
    for cmd in bot.core.registry.all():
        assert cmd.usage and cmd.description
        assert len(bot.core.registry.help_for(cmd.name)) <= 500
    bot.clock.advance(5)  # ?help has a 5 s global cooldown
    await bot.say("bob: ?help hangman")
    assert "?g <letter>" in bot.out[-1]


async def test_database_error_recording_a_user_does_not_crash(bot: Bot, monkeypatch):
    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(bot.core.stats, "touch_user", locked)
    await bot.say("alice: ?coinflip")
    assert any(e["event"] == "error" and e["where"] == "command:coinflip" for e in bot.events())


async def test_tick_survives_a_failing_log_rollover(bot: Bot, monkeypatch):
    def broken():
        raise OSError("disk gone")

    monkeypatch.setattr(bot.log, "maybe_rollover", broken)
    await bot.say("alice: ?scramble animals")
    await bot.wait(45)  # the game still times out even though rollover fails every tick
    assert bot.out[-1] == "⏰ Time's up! It was ALLIGATOR."
    assert any(e["event"] == "error" and e["where"] == "log_rollover" for e in bot.events())


async def test_command_logged_and_handler_error_does_not_crash(bot: Bot):
    async def broken(ctx):
        raise ValueError("bad handler")

    from bot.commands import Command

    bot.core.registry.add(Command("broken", broken, "{p}broken", "Breaks.", "Fun"))
    await bot.say("alice: ?broken")
    await bot.say("alice: ?coinflip")
    events = bot.events()
    assert any(e["event"] == "command" and e["command"] == "broken" for e in events)
    assert any(e["event"] == "error" and e["where"] == "command:broken" for e in events)
    assert bot.out[-1] in ("🪙 Heads", "🪙 Tails")


async def test_run_shutdown_from_chat_exits_zero(tmp_path, clock, assets):
    lines = ["alice: ?scramble animals", "@mod: ?bot shutdown", "alice: ?coinflip"]
    bot = Bot(tmp_path, clock, assets, lines=lines)
    code = await asyncio.wait_for(bot.core.run(), timeout=5)
    assert code == 0
    assert bot.out[1:] == ["Shutting down (requested by mod)."]
    assert not any(t in bot.out for t in ("🪙 Heads", "🪙 Tails"))  # ignored after shutdown
    assert bot.core.games.sessions == {}
    events = bot.events()
    assert events[0]["event"] == "startup" and events[0]["is_mod"] is True
    assert events[-1] == {**events[-1], "event": "shutdown", "by": "mod", "exit_code": 0}


async def test_run_ends_cleanly_when_console_input_ends(tmp_path, clock, assets):
    bot = Bot(tmp_path, clock, assets, lines=["alice: ?coinflip"])
    assert await asyncio.wait_for(bot.core.run(), timeout=5) == 0
    assert bot.out[0] in ("🪙 Heads", "🪙 Tails")


class FailingConnector:
    channel_id = "x"

    def __init__(self, exc: Exception):
        self.exc = exc
        self.sent: list[str] = []

    async def run(self, on_message, on_ready):
        await on_ready(ReadyInfo("x", "x", False))
        raise self.exc

    async def send(self, text, reply_to=None):
        self.sent.append(text)
        return SendResult(True)

    async def lookup_user(self, login):
        return None

    async def close(self):
        pass


@pytest.mark.parametrize(
    "exc, code",
    [(AuthRequired("token revoked"), 3), (ConfigError("channel not found"), 2), (RuntimeError("socket died"), 1)],
)
async def test_run_maps_connector_failures_to_exit_codes(tmp_path, clock, assets, exc, code):
    bot = Bot(tmp_path, clock, assets, connector=FailingConnector(exc))
    assert await asyncio.wait_for(bot.core.run(), timeout=5) == code
    assert bot.events()[-1]["exit_code"] == code


class BlockingConnector(FailingConnector):
    """Runs until close(); records the order of sends and close."""

    def __init__(self, close_error: Exception | None = None):
        super().__init__(RuntimeError("unused"))
        self.events: list[tuple[str, str]] = []
        self.closed = asyncio.Event()
        self.close_error = close_error

    async def run(self, on_message, on_ready):
        await on_ready(ReadyInfo("x", "x", True))
        await self.closed.wait()

    async def send(self, text, reply_to=None):
        self.events.append(("send", text))
        return SendResult(True)

    async def close(self):
        self.events.append(("close", ""))
        self.closed.set()
        if self.close_error:
            raise self.close_error


async def test_signal_shutdown_while_connected(tmp_path, clock, assets):
    conn = BlockingConnector()
    bot = Bot(tmp_path, clock, assets, connector=conn)
    asyncio.get_running_loop().call_later(0.05, bot.core.request_shutdown, "signal")
    assert await asyncio.wait_for(bot.core.run(), timeout=5) == 0
    assert bot.events()[-1]["by"] == "signal"
    assert conn.events[-1] == ("close", "")


async def test_shutdown_notice_is_sent_before_the_connector_closes(tmp_path, clock, assets):
    conn = BlockingConnector()
    bot = Bot(tmp_path, clock, assets, connector=conn)

    async def mod_shuts_down():
        await asyncio.sleep(0.05)
        await bot.core.on_message(parse_console_line("@mod: ?bot shutdown", clock, bot.ids))

    asyncio.get_running_loop().create_task(mod_shuts_down())
    assert await asyncio.wait_for(bot.core.run(), timeout=5) == 0
    assert conn.events == [("send", "Shutting down (requested by mod)."), ("close", "")]


async def test_error_while_closing_still_exits_cleanly(tmp_path, clock, assets):
    conn = BlockingConnector(close_error=OSError("could not save tokens"))
    http = FakeHttp()
    closed = []

    async def record_close():
        closed.append(True)

    http.close = record_close
    bot = Bot(tmp_path, clock, assets, connector=conn, http=http)
    asyncio.get_running_loop().call_later(0.05, bot.core.request_shutdown, "signal")
    assert await asyncio.wait_for(bot.core.run(), timeout=5) == 0
    events = bot.events()
    assert any(e["event"] == "error" and e["where"] == "shutdown:connector.close" for e in events)
    assert events[-1]["event"] == "shutdown" and events[-1]["exit_code"] == 0
    assert closed == [True]


async def test_connector_failure_discards_instead_of_sending(tmp_path, clock, assets):
    conn = FailingConnector(RuntimeError("socket died"))
    bot = Bot(tmp_path, clock, assets, connector=conn)
    bot.core.outbox._tokens = 0  # rate limit exhausted (the fake clock never refills it): message stays queued
    bot.core.outbox.enqueue("queued before the crash")
    assert await asyncio.wait_for(bot.core.run(), timeout=5) == 1
    assert conn.sent == []
    assert any(e.get("reason") == "connector_failed" for e in bot.events())


ALL_GAMES_ON = ("scramble", "hangman", "trivia", "riddle", "higherlower")


@pytest.fixture
def allbot(tmp_path, clock, assets) -> Bot:
    return Bot(tmp_path, clock, assets, enabled_games=ALL_GAMES_ON)


async def test_help_lists_every_game_and_explains_shared_commands(allbot: Bot):
    await allbot.say("alice: ?help")
    assert allbot.out[-1].startswith("Games: ?scramble ?hangman ?trivia ?riddle ?higherlower ?skip | ")
    await allbot.say("bob: ?help g")
    assert allbot.out[-1] == "?g <guess> · Guess in your current game."
    await allbot.say("carol: ?help hl")
    assert allbot.out[-1].startswith("?higherlower · Does the next thing") and allbot.out[-1].endswith("(also ?hl)")


async def test_trivia_round_to_gamestats(allbot: Bot):
    await allbot.say("alice: ?trivia medium science")
    assert allbot.out[-1] == "❓ (science, medium) Which planet is the largest? · 30s · ?g <answer> · ?hint"
    await allbot.say("alice: ?hint")
    assert allbot.out[-1] == "💡 7 letters, starts with J"
    await allbot.say("alice: ?g jupitr")
    assert allbot.out[-1] == "✅ alice got it: Jupiter (+7)"
    await allbot.say("alice: ?gamestats trivia")
    assert allbot.out[-1] == "📊 alice · trivia: 1 win / 1 played · 7 pts · rank #1"


async def test_trivia_unknown_option_is_not_echoed(allbot: Bot):
    await allbot.say("alice: ?trivia astrology")
    assert allbot.out[-1] == (
        "Unknown option. Trivia categories: history, science · difficulties: easy, medium, hard"
    )


async def test_riddle_round(allbot: Bot):
    await allbot.say("alice: ?riddle")
    answer = "clock" if "hands" in allbot.out[-1] else "towel"
    await allbot.say("alice: ?g nope")
    assert allbot.out[-1] == "❌ Not it, 2 guesses left."
    await allbot.say(f"alice: ?g is it a {answer}")
    assert allbot.out[-1] == f"✅ alice got it: {answer} (+10)"


async def test_higherlower_streak_then_timeout_keeps_the_points(allbot: Bot):
    await allbot.say("alice: ?hl")
    game = allbot.core.games.sessions["console-alice"].game
    guess = "higher" if game.next["views"] >= game.current["views"] else "lower"
    await allbot.wait(15)
    await allbot.say(f"alice: ?g {guess}")
    assert allbot.out[-1].startswith("✅ ") and "Streak 1." in allbot.out[-1]
    await allbot.wait(15)  # 30 s since the start, but the right answer restarted the 20 s timer
    assert "console-alice" in allbot.core.games.sessions
    await allbot.wait(6)
    assert allbot.out[-1].startswith("⏰ Time's up! ") and allbot.out[-1].endswith("Streak 1 (+1)")
    await allbot.say("bob: ?leaderboard higherlower")
    assert allbot.out[-1] == "🏆 Top 1 higherlower: 1. alice (1)"
```

- [ ] **Step 2: Write `tests/test_cli.py`**

```python
"""Runs the real `python -m bot` process, the way a person would."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text('channel = "test_channel"\n[outbox]\nrate_per_second = 3\nburst = 50\n', encoding="utf-8")
    return path


def run_bot(
    *args: str, stdin: str = "", env_file: str | None = None, tmp_path: Path, extra_env: dict | None = None
) -> subprocess.CompletedProcess:
    if env_file is not None:
        (tmp_path / ".env").write_text(env_file, encoding="utf-8")
    clean_env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), **(extra_env or {})}
    return subprocess.run(
        [sys.executable, "-m", "bot", *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=20,
        cwd=ROOT,
        env=clean_env,
    )


def test_console_mode_plays_and_shuts_down(tmp_path):
    config = write_config(tmp_path)
    result = run_bot(
        "console", "--config", str(config),
        stdin="alice: ?coinflip\nbob: ?help\n@mod: ?bot shutdown\nalice: typed after shutdown\n",
        tmp_path=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "bot → alice: 🪙" in result.stdout
    assert "bot → bob: Games: ?scramble ?hangman ?trivia ?riddle ?higherlower ?skip" in result.stdout
    assert "bot → mod: Shutting down (requested by mod)." in result.stdout
    assert (tmp_path / "data" / "console" / "bot.db").exists()
    assert list((tmp_path / "data" / "console" / "logs").glob("activity-*.jsonl"))


def test_run_without_secrets_exits_2(tmp_path):
    result = run_bot("--config", str(write_config(tmp_path)), env_file="", tmp_path=tmp_path)
    assert result.returncode == 2
    assert "TWITCH_CLIENT_ID is missing" in result.stderr


def test_auth_without_client_credentials_exits_2(tmp_path):
    result = run_bot("auth", "--config", str(write_config(tmp_path)), env_file="", tmp_path=tmp_path)
    assert result.returncode == 2
    assert "TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET" in result.stderr


def test_database_newer_than_code_exits_2(tmp_path):
    import sqlite3

    db = tmp_path / "data" / "console" / "bot.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version VALUES (99)")
    result = run_bot("console", "--config", str(write_config(tmp_path)), tmp_path=tmp_path)
    assert result.returncode == 2
    assert "newer than this code" in result.stderr


SECRETS = "TWITCH_CLIENT_ID=cid\nTWITCH_CLIENT_SECRET=secret\nBOT_ID=123\n"


def test_env_file_is_read_and_real_environment_wins(tmp_path):
    config = str(write_config(tmp_path))
    from_file = run_bot("--config", config, env_file=SECRETS + "OWNER_IDS=notnum\n", tmp_path=tmp_path)
    assert from_file.returncode == 2 and "got notnum" in from_file.stderr
    from_env = run_bot("--config", config, tmp_path=tmp_path, extra_env={"OWNER_IDS": "fromenv"})
    assert from_env.returncode == 2 and "got fromenv" in from_env.stderr
    empty_env = run_bot("--config", config, tmp_path=tmp_path, extra_env={"OWNER_IDS": ""})
    assert "got notnum" in empty_env.stderr  # an empty variable doesn't override .env


def test_corrupt_database_exits_2(tmp_path):
    db = tmp_path / "data" / "console" / "bot.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"this is not a sqlite database" * 100)
    result = run_bot("console", "--config", str(write_config(tmp_path)), tmp_path=tmp_path)
    assert result.returncode == 2
    assert "Setup error" in result.stderr


def test_sigterm_stops_cleanly(tmp_path):
    import json
    import select
    import signal
    import time

    config = write_config(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "bot", "console", "--config", str(config)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    try:
        ready, _, _ = select.select([proc.stdout], [], [], 10)  # don't hang if the bot never starts
        assert ready, "the bot did not start within 10 s"
        assert proc.stdout.readline().startswith("Console mode.")  # banner: the bot is running
        time.sleep(0.2)
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 0
    finally:
        proc.kill()
    logs = list((tmp_path / "data" / "console" / "logs").glob("activity-*.jsonl"))
    last = json.loads(logs[0].read_text().splitlines()[-1])
    assert last["event"] == "shutdown" and last["by"] == "signal"


def test_bad_config_exits_2(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('channel = "has spaces"\n', encoding="utf-8")
    result = run_bot("console", "--config", str(path), tmp_path=tmp_path)
    assert result.returncode == 2
    assert "channel must be a Twitch username" in result.stderr
```

- [ ] **Step 3: Write `tests/test_config.py`**

```python
from pathlib import Path

import pytest

from bot.config import ConfigError, load_config

ENV = {"TWITCH_CLIENT_ID": "cid", "TWITCH_CLIENT_SECRET": "secret", "BOT_ID": "123", "OWNER_IDS": "1, 2,"}


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_repo_config_file_is_valid_once_a_channel_is_set(tmp_path):
    shipped = (Path(__file__).parent.parent / "config.toml").read_text(encoding="utf-8")
    with pytest.raises(ConfigError, match="set channel"):
        load_config(write(tmp_path, shipped), ENV)  # the placeholder must be replaced
    load_config(write(tmp_path, shipped), {}, require_twitch=False)  # console mode works before it's set
    cfg = load_config(write(tmp_path, shipped.replace('"your_channel"', '"real_channel"')), ENV)
    assert cfg.prefix == "?" and cfg.enabled_games == ("scramble", "hangman", "trivia", "riddle", "higherlower")


def test_defaults_and_env(tmp_path):
    cfg = load_config(write(tmp_path, 'channel = "Robert_Channel"\n'), ENV)
    assert cfg.channel == "robert_channel"
    assert cfg.owner_ids == frozenset({"1", "2"})
    assert (cfg.user_cooldown, cfg.global_cooldown) == (10, 5)
    assert (cfg.max_games, cfg.game_cooldown, cfg.busy_queue) == (25, 10, 10)
    assert (cfg.outbox_rate, cfg.outbox_burst, cfg.outbox_max_queue) == (2, 3, 30)
    assert cfg.data_dir == tmp_path / "data"


@pytest.mark.parametrize(
    "toml, message",
    [
        ('channel = "no spaces allowed"', "channel"),
        ('channel = "ok_name"\nprefix = ""', "prefix"),
        ('channel = "ok_name"\n[cooldowns]\nuser_seconds = -1', "cooldowns.user_seconds"),
        ('channel = "ok_name"\n[games]\nmax_running = 0', "games.max_running"),
        ('channel = "ok_name"\n[games]\nenabled = ["chess"]', "chess"),
        ('channel = "ok_name"\n[outbox]\nburst = 1.5', "outbox.burst"),
        ("channel = ", "not valid TOML"),
        ('channel = "ok_name"\n[games]\nmax_runing = 5', "unknown setting games.max_runing"),
        ('channel = "ok_name"\ngames = "oops"', "games must be a \\[games\\] section"),
        ('channel = "ok_name"\ncolour = "blue"', "unknown setting 'colour'"),
        ('channel = "ok_name"\n[outbox]\nrate_per_second = 1000', "outbox.rate_per_second"),
        ('channel = "ok_name"\n[outbox]\nrate_per_second = nan', "outbox.rate_per_second"),
        ('channel = "ok_name"\n[outbox]\nrate_per_second = inf', "outbox.rate_per_second"),
        ('channel = "ok_name"\nprefix = "/"', "can't start with"),
        ('channel = "ok_name"\nprefix = ".b"', "can't start with"),
        ('channel = "ok_name"\n[games]\nenabled = []', "at least one game"),
        ("channel = 123", "channel must be a Twitch username"),
        ('channel = "ok_name"\n[games]\nbusy_queue = 40', "can't be larger than outbox.max_queue"),
    ],
)
def test_invalid_values_name_the_key(tmp_path, toml, message):
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, toml), ENV)


def test_missing_secrets_fail_only_when_twitch_required(tmp_path):
    path = write(tmp_path, 'channel = "ok_name"\n')
    with pytest.raises(ConfigError, match="TWITCH_CLIENT_ID"):
        load_config(path, {})
    assert load_config(path, {}, require_twitch=False).bot_id == "console-bot"


def test_owner_ids_must_be_numeric_for_twitch_but_not_console(tmp_path):
    path = write(tmp_path, 'channel = "ok_name"\n')
    with pytest.raises(ConfigError, match="OWNER_IDS"):
        load_config(path, {**ENV, "OWNER_IDS": "123,robert"})
    assert load_config(path, {"OWNER_IDS": "console-robert"}, require_twitch=False).owner_ids == {"console-robert"}


def test_duplicate_games_are_dropped(tmp_path):
    cfg = load_config(write(tmp_path, 'channel = "ok_name"\n[games]\nenabled = ["scramble", "scramble"]'), ENV)
    assert cfg.enabled_games == ("scramble",)


def test_bot_id_must_be_numeric(tmp_path):
    with pytest.raises(ConfigError, match="BOT_ID"):
        load_config(write(tmp_path, 'channel = "ok_name"\n'), {**ENV, "BOT_ID": "mybot"})
```

- [ ] **Step 4: Write `tests/test_stats_help_commands.py`**

```python
from datetime import datetime, timezone

import pytest

from bot.commands import CommandContext, CommandRegistry
from bot.help import register_help
from bot.stats import PlayerResult, RoundRecord, StatsStore
from bot.stats_commands import register_stats
from tests.helpers import make_msg

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


class Cmds:
    def __init__(self):
        self.stats = StatsStore(":memory:")
        self.registry = CommandRegistry("?")
        register_stats(self.registry, stats=self.stats, game_names=["scramble", "hangman"])
        register_help(self.registry)
        self.replies: list[str] = []

    def play(self, game: str, login: str, points: int, won: bool = True) -> None:
        self.stats.touch_user(f"id-{login}", login, login.title(), T0)
        self.stats.record_round(
            RoundRecord(game, None, f"id-{login}", T0, T0, "won",
                        [PlayerResult(f"id-{login}", login, login.title(), points, won)])
        )

    async def run(self, text: str, login: str = "alice") -> str:
        name, _, args = text.removeprefix("?").partition(" ")
        ctx = CommandContext(make_msg(text, login), name, args, "?", lambda t, **kw: self.replies.append(t), None)
        await self.registry.get(name).handler(ctx)
        return self.replies[-1]


@pytest.fixture
def c() -> Cmds:
    cmds = Cmds()
    cmds.play("scramble", "bob", 10)
    cmds.play("scramble", "bob", 7)
    cmds.play("scramble", "carol", 10)
    cmds.play("hangman", "carol", 12)
    cmds.play("hangman", "alice", 0, won=False)
    return cmds


async def test_leaderboard_overall_default(c: Cmds):
    assert await c.run("?leaderboard") == "🏆 Top 2 overall: 1. Carol (22) 2. Bob (17)"


async def test_leaderboard_game_and_limit_in_any_order(c: Cmds):
    assert await c.run("?leaderboard scramble 1") == "🏆 Top 1 scramble: 1. Bob (17)"
    assert await c.run("?leaderboard 1 hangman") == "🏆 Top 1 hangman: 1. Carol (12)"
    assert await c.run("?leaderboard 99") == "🏆 Top 2 overall: 1. Carol (22) 2. Bob (17)"


async def test_leaderboard_limit_edge_cases(c: Cmds):
    assert await c.run("?leaderboard 0") == "🏆 Top 1 overall: 1. Carol (22)"
    assert await c.run("?leaderboard -5") == "🏆 Top 1 overall: 1. Carol (22)"
    assert await c.run("?leaderboard " + chr(0xB2)) == "Unknown game. Games: scramble, hangman"  # superscript two
    assert await c.run("?leaderboard SCRAMBLE 1 extra words") == "🏆 Top 1 scramble: 1. Bob (17)"


async def test_leaderboard_unknown_game_and_empty(c: Cmds):
    assert await c.run("?leaderboard chess") == "Unknown game. Games: scramble, hangman"
    empty = Cmds()
    assert await empty.run("?leaderboard hangman") == "No hangman scores yet."


async def test_gamestats_self_overall(c: Cmds):
    assert await c.run("?gamestats", "carol") == (
        "📊 carol: 22 pts, 2 wins, 2 played | hangman 1W/1P 12pts | scramble 1W/1P 10pts"
    )


async def test_gamestats_game_and_other_user(c: Cmds):
    assert await c.run("?gamestats scramble @Bob") == "📊 Bob · scramble: 2 wins / 2 played · 17 pts · rank #1"
    assert await c.run("?gamestats bob") == "📊 Bob: 17 pts, 2 wins, 2 played | scramble 2W/2P 17pts"


async def test_gamestats_one_win_is_singular(c: Cmds):
    assert await c.run("?gamestats hangman carol") == "📊 Carol · hangman: 1 win / 1 played · 12 pts · rank #1"


async def test_gamestats_played_without_points_has_no_rank(c: Cmds):
    assert await c.run("?gamestats hangman") == "📊 alice · hangman: 0 wins / 1 played · 0 pts"


async def test_gamestats_missing(c: Cmds):
    assert await c.run("?gamestats nobody_here") == "No stats for that user yet."
    assert await c.run("?gamestats bad/name") == "That's not a valid username."
    assert await c.run("?gamestats @") == "That's not a valid username."
    assert await c.run("?gamestats hangman bob") == "No hangman stats for Bob yet."
    assert await c.run("?gamestats", "dave") == "No stats for dave yet."


async def test_help_overview_and_details(c: Cmds):
    assert await c.run("?help") == "Stats: ?leaderboard ?gamestats · ?help <command> for details"
    assert await c.run("?commands") == "Stats: ?leaderboard ?gamestats · ?help <command> for details"
    assert await c.run("?help ?leaderboard") == (
        "?leaderboard [game] [1-10] · Top players by points, overall or for one game."
    )


async def test_help_unknown_never_echoes_what_was_typed(c: Cmds):
    assert await c.run("?help nope") == "No command by that name. Try ?help."
    assert await c.run("?help jason_is_trash") == "No command by that name. Try ?help."


async def test_game_aliases_work_in_stats():
    cmds = Cmds()
    cmds.registry = CommandRegistry("?")
    register_stats(cmds.registry, stats=cmds.stats, game_names=["scramble", "higherlower"])
    cmds.play("higherlower", "dana", 6)
    assert await cmds.run("?leaderboard hl") == "🏆 Top 1 higherlower: 1. Dana (6)"
    assert await cmds.run("?gamestats hl dana") == "📊 Dana · higherlower: 1 win / 1 played · 6 pts · rank #1"
```

- [ ] **Step 5: Run the tests and see them fail**

Run: `.venv/bin/pytest tests/test_flows.py tests/test_cli.py tests/test_config.py tests/test_stats_help_commands.py -q`
Expected: the new flow tests fail (`?trivia` isn't a command yet).

- [ ] **Step 6: Write `bot/games/__init__.py`**

```python
"""All game classes, by name. config.toml's [games] enabled picks which ones run."""

from bot.games.base import Game
from bot.games.hangman import Hangman
from bot.games.higherlower import HigherLower
from bot.games.riddle import Riddle
from bot.games.scramble import Scramble
from bot.games.trivia import Trivia

ALL_GAMES: dict[str, type[Game]] = {cls.name: cls for cls in (Scramble, Hangman, Trivia, Riddle, HigherLower)}
```

- [ ] **Step 7: Write `bot/stats_commands.py`**

```python
"""?leaderboard and ?gamestats."""

from __future__ import annotations

import re
from collections.abc import Sequence

from bot.commands import Command, CommandContext, CommandRegistry
from bot.games import ALL_GAMES
from bot.stats import StatsStore
from bot.text import clean_username

DEFAULT_LIMIT = 5
MAX_LIMIT = 10
_NUMBER = re.compile(r"-?[0-9]+")  # ASCII only: str.isdigit() accepts "²", which int() rejects


def _plural(count: int, word: str) -> str:
    return word if count == 1 else word + "s"


def register_stats(registry: CommandRegistry, *, stats: StatsStore, game_names: Sequence[str]) -> None:
    games = [g.lower() for g in game_names]
    # a game's aliases work here too: "?leaderboard hl" means higherlower
    aliases = {a: cls.name for cls in ALL_GAMES.values() if cls.name in games for a in cls.aliases}

    def game_name(word: str) -> str | None:
        word = word.lower()
        word = aliases.get(word, word)
        return word if word in games else None

    async def leaderboard(ctx: CommandContext) -> None:
        game: str | None = None
        limit = DEFAULT_LIMIT
        for arg in ctx.argv[:2]:
            if _NUMBER.fullmatch(arg):
                limit = max(1, min(MAX_LIMIT, int(arg)))
            elif game_name(arg):
                game = game_name(arg)
            else:
                ctx.reply(f"Unknown game. Games: {', '.join(games)}")
                return
        rows = stats.leaderboard(game, limit)
        label = game or "overall"
        if not rows:
            ctx.reply(f"No {label} scores yet.")
            return
        body = " ".join(f"{i}. {r.display_name} ({r.points})" for i, r in enumerate(rows, start=1))
        ctx.reply(f"🏆 Top {len(rows)} {label}: {body}")

    async def gamestats(ctx: CommandContext) -> None:
        argv = ctx.argv
        game: str | None = None
        # A first argument that names a game is the game, even if someone's login is the same word.
        if argv and game_name(argv[0]):
            game = game_name(argv[0])
            argv = argv[1:]
        if argv:
            login = clean_username(argv[0])
            if login is None:
                ctx.reply("That's not a valid username.")
                return
            user = stats.find_user(login)
            if user is None:
                ctx.reply("No stats for that user yet.")  # never repeat the name the user typed
                return
            user_id, name = user.user_id, user.display_name
        else:
            user_id, name = ctx.msg.user_id, ctx.msg.display_name
        per_game = stats.user_stats(user_id)
        if game is not None:
            row = next((g for g in per_game if g.game == game), None)
            if row is None:
                ctx.reply(f"No {game} stats for {name} yet.")
                return
            rank = stats.rank(user_id, game)
            rank_text = f" · rank #{rank}" if rank else ""
            wins_text = f"{row.wins} {_plural(row.wins, 'win')}"
            ctx.reply(f"📊 {name} · {game}: {wins_text} / {row.played} played · {row.points} pts{rank_text}")
            return
        if not per_game:
            ctx.reply(f"No stats for {name} yet.")
            return
        points = sum(g.points for g in per_game)
        wins = sum(g.wins for g in per_game)
        played = sum(g.played for g in per_game)
        parts = " | ".join(f"{g.game} {g.wins}W/{g.played}P {g.points}pts" for g in per_game)
        ctx.reply(f"📊 {name}: {points} pts, {wins} {_plural(wins, 'win')}, {played} played | {parts}")

    registry.add(
        Command(
            "leaderboard",
            leaderboard,
            "{p}leaderboard [game] [1-10]",
            "Top players by points, overall or for one game.",
            "Stats",
        )
    )
    registry.add(
        Command(
            "gamestats",
            gamestats,
            "{p}gamestats [game] [username]",
            "Wins, games played, and points: yours or someone else's, overall or for one game.",
            "Stats",
            global_cooldown=False,  # personal lookup: never blocked by someone else's
        )
    )
```

- [ ] **Step 8: Write `config.toml`**

```toml
# Non-secret settings. Secrets (client id/secret, bot id, owner ids) live in .env.

channel = "your_channel"   # the Twitch channel to join; change to "jasontheween" to go live there
prefix = "?"

[cooldowns]
user_seconds = 10           # per person, per command
global_seconds = 5          # per command, across the whole chat (not for games, ?cookie, ?gamestats, ?help)

[games]
enabled = ["scramble", "hangman", "trivia", "riddle", "higherlower"]
max_running = 25            # personal games running at once, across the whole chat
cooldown_seconds = 10       # per person, after their game ends
busy_queue = 10             # refuse new games while this many bot messages are waiting to send

[outbox]
rate_per_second = 2         # sustained sending rate (a mod account may send about 3/s)
burst = 3                   # messages that can go out back to back
max_queue = 30              # extra messages beyond this are dropped and logged

[logs]
retention_days = 30
```

- [ ] **Step 9: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "offline-chat-bot"
version = "0.1.0"
description = "Twitch chat-games bot for jasontheween's offline chat"
requires-python = ">=3.11,<3.14"
dependencies = [
    "twitchio==3.3.2",
    "aiohttp>=3.9",
    "python-dotenv>=1.0",
    "certifi>=2024.2.2",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23"]

[tool.setuptools.packages.find]
include = ["bot*"]

[tool.setuptools.package-data]
bot = ["content/*.txt", "content/*.json", "content/*.md", "content/words/*.txt"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
filterwarnings = [
    # TwitchIO's web adapter subclasses aiohttp's Application; harmless, not ours to fix.
    "ignore:Inheritance class AiohttpAdapter from web.Application is discouraged:DeprecationWarning",
]
```

- [ ] **Step 10: Write `README.md`**

````markdown
# Offline Chat Bot

A Twitch chat bot for jasontheween's offline chat: personal chat games (Scramble, Hangman,
Trivia, Riddle, Higher or Lower), quick fun commands, per-game points with leaderboards, mod
controls (pause, resume, shut down), and a daily activity log. Designs:
`docs/superpowers/specs/` (Phase 1 core, Phase 2 games).

Games are personal: `?scramble` starts **your** game, only your answers count, and the bot
answers you in threaded replies. Many people can play at once (25 games by default), each
person runs one game at a time, and new games are refused ("try again in a moment") while the
bot's outgoing messages are backed up.

## Commands

| Command | Who | What it does |
|---|---|---|
| `?help` / `?commands`, `?help <command>` | anyone | List commands, or explain one |
| `?scramble [category]`, `?scramble categories` | anyone | Your own word to unscramble: type the answer (or `?g <word>`); `?hint` for a hint (10/7/4 points) |
| `?hangman [category]`, `?hangman categories` | anyone | Your own Hangman; guess with `?g <letter>` or `?g <answer>` |
| `?trivia [category] [easy\|medium\|hard]`, `?trivia categories` | anyone | Your own trivia question. Easy is multiple choice (`?g A`-`D`, 5 points); medium and hard are typed (`?g <answer>`, 3 guesses, `?hint`; medium 10/7/4, hard 15/10/6 points). Questions from Open Trivia DB (CC BY-SA 4.0) |
| `?riddle` | anyone | Your own riddle: `?g <answer>`, 3 guesses, `?hint` for a clue then the letter count (10/7/4 points) |
| `?higherlower` / `?hl` | anyone | Does the next thing get more monthly Wikipedia views? `?g higher` or `?g lower`; 1 point per right answer, one miss ends the streak |
| `?skip` | anyone | End your current game (no points) |
| `?leaderboard [game] [1-10]` | anyone | Top players by points |
| `?gamestats [game] [username]` | anyone | Wins, games played, points |
| `?8ball`, `?coinflip`, `?catfact`, `?dogfact`, `?fact`, `?dadjoke` | anyone | Quick fun |
| `?cookie`, `?cookie give <username>` | anyone | Daily fortune cookie (resets 00:00 UTC) |
| `?bot off` / `?bot on` / `?bot status` | mods, broadcaster, owners | Pause, resume, check. `?bot off` ends every running game with no points, and while paused the bot ignores everything except `?bot` from a mod |
| `?bot shutdown` | mods, broadcaster, owners | Stop the bot process. Only someone with access to the machine can start it again |
| `?stopgame` | mods, broadcaster, owners | End all running games with no points |

Scramble and Hangman categories: animals, countries, food, games, general, streamers. Trivia
categories: animals, anime, games, general, geography, history, movies, music, science, sports, tv.

A player doesn't get the same trivia question or riddle again within their last 50 since the bot
last started (a small pool, like animals/easy trivia, comes round sooner, oldest first).

## Install

```
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Any Python from 3.11 to 3.13 works.

## Try it without Twitch

```
.venv/bin/python -m bot console
```

Type lines like `alice: ?scramble animals`. A leading `@` makes the user a mod (`@mod: ?bot off`).
Console mode keeps its own database under `data/console/`, separate from the real one.

On macOS, the python.org installer ships without root certificates, so HTTPS would fail. The
bot detects this at startup and uses the `certifi` certificate bundle automatically.

## Set up on Twitch (one time)

1. **Bot account:** create a new Twitch account for the bot and verify its email.
2. **Twitch app:** at https://dev.twitch.tv/console, register an application (Twitch requires
   two-factor authentication on the account that registers it).
   - OAuth Redirect URL: `http://localhost:4343/oauth/callback` (exactly).
   - Category: Chat Bot. Client type: Confidential.
   - Copy the Client ID and create a Client Secret.
3. **Secrets:** `cp .env.example .env`, then fill in `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`.
   `.env` holds secrets: never share or commit it (it's git-ignored).
4. **Your numeric user ID** goes in `OWNER_IDS`. It's a number, not your username. To look it up
   (replace `yourname`):
   ```
   source .env
   TOKEN=$(curl -s -X POST "https://id.twitch.tv/oauth2/token?client_id=$TWITCH_CLIENT_ID&client_secret=$TWITCH_CLIENT_SECRET&grant_type=client_credentials" | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
   curl -s -H "Client-Id: $TWITCH_CLIENT_ID" -H "Authorization: Bearer $TOKEN" "https://api.twitch.tv/helix/users?login=yourname"
   ```
   The `"id"` in the answer is your user ID.
5. **Log the bot in:** run `.venv/bin/python -m bot auth`. Open the printed URL in a browser where
   you're logged in as the **bot** account and approve. Put the printed `BOT_ID=...` line in `.env`.
   The login is saved in `data/.tio.tokens.json`. Never share or commit that file.
6. **Channel:** set `channel` in `config.toml` to the channel the bot should join.
7. **Mod the bot** in that channel (`/mod <botaccount>` in its chat). Without mod status the bot
   still runs, but it sends more slowly (0.6 messages per second, under Twitch's non-mod limit),
   slow mode applies, and it won't show the Chat Bot badge. The startup log says `is_mod` either
   way. If a mod unmods the bot while it runs, it switches to the slower mode by itself.

## Run

```
.venv/bin/python -m bot
```

- Ctrl+C stops it cleanly.
- `?bot shutdown` from a mod also stops it, with exit code 0.

**Exit codes:**
- 0: stopped on purpose.
- 1: crashed.
- 2: config problem (the message names the setting).
- 3: the Twitch login needs redoing (`python -m bot auth`).
- 130: Ctrl+C before the bot finished starting.

## Settings

- `config.toml` holds the non-secret settings: channel, prefix, cooldowns, enabled games, how
  many games can run at once, the busy threshold, the send rate, and log retention.
- `.env` holds the secrets.
- The word lists are plain text in `bot/content/words/`, one entry per line. Adding a file adds
  a category.
- `bot/content/words/SOURCES.md` records where each streamer and game name was verified.

## Data and logs

- `data/bot.db` (SQLite) holds points, rounds, daily cookies, and the paused flag. The paused
  flag survives restarts.
- `data/logs/activity-YYYY-MM-DD.jsonl` is one file per UTC day. It records commands, game
  starts and ends, admin actions (who paused or shut down the bot), connection events, and
  errors. Ordinary chat is never logged. Files older than 30 days are deleted.

## Move to a server

1. Copy the project folder to the server (for example `/opt/offline-chat-bot`), including
   `.env` and `data/.tio.tokens.json`.
2. On the server: `python3 -m venv .venv && .venv/bin/pip install -e .` (any Python 3.11-3.13).
3. Create a user for the bot (`sudo useradd -r chatbot`), give it the folder, and make the two
   secret files readable only by it:
   ```
   sudo chown -R chatbot /opt/offline-chat-bot
   sudo chmod 600 /opt/offline-chat-bot/.env /opt/offline-chat-bot/data/.tio.tokens.json
   ```
4. `sudo cp deploy/offline-chat-bot.service /etc/systemd/system/`, then
   `sudo systemctl daemon-reload && sudo systemctl enable --now offline-chat-bot`.
5. **How it behaves on the server:**
   - **After a crash or a lost connection:** restarts after 30 seconds and keeps retrying, so a
     long Twitch outage heals on its own. A config error (exit 2) or a needed re-login (exit 3)
     is never restarted, because those need a person.
   - **After `?bot shutdown`:** stays down until someone with server access runs
     `sudo systemctl start offline-chat-bot`.
   - **Logs:** `journalctl -u offline-chat-bot -f`.
6. **Run only one copy of the bot at a time.** If it's running on both your laptop and the
   server, every command is answered twice.
7. **If it stops with exit 3 (login needed):** the login page needs a browser, which a server
   doesn't have. Either run `python -m bot auth` on your laptop and copy the new
   `data/.tio.tokens.json` to the server (then `chmod 600` it and restart the service), or tunnel
   the login port with `ssh -L 4343:localhost:4343 <server>` and run `auth` on the server.

## Go live in jasontheween's chat

1. A channel mod runs `/mod <botaccount>` there.
2. Set `channel = "jasontheween"` in `config.toml`.
3. Restart the bot (`sudo systemctl restart offline-chat-bot` on the server).

## Tests

```
.venv/bin/pytest
```

## Content

- Trivia questions come from [Open Trivia DB](https://opentdb.com/) (CC BY-SA 4.0; see
  `bot/content/TRIVIA_CREDITS.md`). `scripts/fetch_trivia.py` rebuilds `bot/content/trivia.json`
  (it takes several minutes because of the API's rate limit).
- Riddles (`bot/content/riddles.json`) were written for this bot and checked by a second reviewer.
- Higher or Lower uses last month's English Wikipedia page views. Edit
  `scripts/higherlower_terms.txt` and run `scripts/fetch_pageviews.py` to change the terms or
  refresh the numbers.
- `tests/test_content.py` checks every content file's rules (lengths, blocked words, clues that
  don't give the answer away).
````

- [ ] **Step 11: Run the tests**

Run: `.venv/bin/pytest tests/test_flows.py tests/test_cli.py tests/test_config.py tests/test_stats_help_commands.py -q`, then `.venv/bin/pytest -q`.
Expected: `83 passed`, then the whole suite passes (462 passed).

- [ ] **Step 12: Commit**

```bash
git add tests/test_flows.py tests/test_cli.py tests/test_config.py tests/test_stats_help_commands.py bot/games/__init__.py bot/stats_commands.py config.toml pyproject.toml README.md
git commit -m "Phase 2: register Trivia, Riddle and Higher or Lower; flows and README"
```

### Task 7: Trivia question bank

**Files:**
- Replace: `scripts/fetch_trivia.py`, `bot/content/TRIVIA_CREDITS.md`
- Generate: `bot/content/trivia.json`

`scripts/fetch_trivia.py` downloads every verified multiple-choice question for the 11 categories (spec §3's mapping) from Open Trivia DB, one request every 5.5 s with a session token so nothing repeats. With a token the API may answer "fewer left than you asked for" with either response code 1 or 4, so both halve the batch size; network errors and HTTP 429 are retried with backoff. Text is cleaned (invisible characters, spaces). `keep()` holds every rule, and `--refilter` re-applies them to the existing file offline. It drops:

- questions with blocked words or mature topics (drugs, alcohol, tobacco, sexual themes, self-harm, a few fan-service anime titles), questions over 300 characters, duplicates (ignoring punctuation and case), and a list of ids checked by hand and found wrong, dated, mature, option-dependent or unwinnable;
- easy questions too long for one message, or whose options read alike or include a lone letter ("E", which a player would read as A-D);
- medium/hard questions that can't be typed fairly: answer over 3 words or 25 characters, empty once normalized ("?:"), carrying meaning in symbols (C++, -40, 13.8, 2-3, 4/4, %), a date with a month, a number of 5+ digits, an exact number for an "approximately" question, or a question that needs its options ("these", "following", "not", "except"), except a short list of ids checked by hand.

The credits file covers CC BY-SA 4.0 and lists the changes made.

- [ ] **Step 1: Write `scripts/fetch_trivia.py`**

```python
"""Build bot/content/trivia.json from Open Trivia DB (https://opentdb.com, CC BY-SA 4.0).

Run once from the repo root: .venv/bin/python scripts/fetch_trivia.py
The API allows one request per 5 seconds per IP, so this takes several minutes. It only serves
verified questions. Easy questions keep their options (multiple choice); medium and hard ones
are kept only if the answer can reasonably be typed.

`--refilter` re-applies the filters below to the existing trivia.json without any network access.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.assets import Assets  # noqa: E402
from bot.fun import BlockedWords  # noqa: E402
from bot.text import normalize, strip_invisible  # noqa: E402

API = "https://opentdb.com"
OUT = Path(__file__).resolve().parent.parent / "bot" / "content" / "trivia.json"
USER_AGENT = "offline-chat-bot (https://github.com/rrong12/offline-chat-bot)"
DELAY = 5.5  # seconds between requests

# Our category -> Open Trivia DB category IDs.
CATEGORIES: dict[str, tuple[int, ...]] = {
    "general": (9,),
    "games": (15,),
    "movies": (11,),
    "music": (12,),
    "tv": (14,),
    "anime": (31,),
    "sports": (21,),
    "science": (17, 18, 19),
    "geography": (22,),
    "history": (23,),
    "animals": (27,),
}
DIFFICULTIES = ("easy", "medium", "hard")
# Typed questions must make sense without seeing the options ("Which is not a country in Africa?").
NEEDS_OPTIONS = re.compile(r"\b(?:these|following|below|above|not|isn't|isnt|except|none of|released first"
                           r"|came first)\b", re.IGNORECASE)
# Typed answers nobody types the same way twice: dates with a month, long numbers, approximate figures.
_MONTH = (r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?"
          r"|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b")  # whole month names only: not "Mario Party 4"
MONTH_DATE = re.compile(rf"{_MONTH}.*\d|\d.*{_MONTH}", re.IGNORECASE)
LONG_NUMBER = re.compile(r"\d{5,}")
APPROXIMATE = re.compile(r"\b(?:approximately|roughly|about how|around how|estimated)\b", re.IGNORECASE)
# Topics that don't belong in a young, family-friendly chat, beyond the blocked-word list: drugs, alcohol,
# tobacco, sexual themes, self-harm, and a few fan-service anime titles.
MATURE_TOPICS = re.compile(
    r"\b(?:cocaine|heroin|cannabis|marijuana|thc|weed|drugs?|cartel|overdose|beer|brewery|vodka|whisk(?:e)?y|rum"
    r"|cocktails?|alcohol(?:ic)?|liquor|drunk|tobacco|cigarettes?|smoking|sex(?:ual|y)?|breasts?|harem|hot coffee"
    r"|stripper|suicide|kill (?:themselves|himself|herself|yourself)|schutzstaffel|to love-ru"
    r"|high ?school (?:dxd|of the dead)|copulat\w*|courtesans?|testic\w*|morenatsu|breweries|beerbongs?|cider"
    r"|smokin|pills?|meth|poopy\w*|butthole|skinny dipping)\b|f\*\*\*",
    re.IGNORECASE,
)
# Checked and wrong, garbled, or out of date (see docs/superpowers/plans, Phase 2 execution log).
EXCLUDED_IDS = frozenset({
    "4be33db662", "5efa52ea29", "0d5228c649", "ac2967fc00", "0508b9f490", "358cd17e26", "01495b878f",
    "7732c495a3", "96ae8a7764", "5db409db5a",
    # second review: mature, need their options, out of date, unwinnable or too loose as typed questions
    "0a60a0d744", "9b1d123380", "8c394874bc", "4ed32265c4", "4edefa5a85", "975a5db97b", "c51570b283",
    "1059611032", "5561256950", "edee009d10", "6e0ed953fc", "9ea627bce0", "6addd9f6e9", "87737bf23e",
    "58c424f37e", "2a4bb44099",
    # final content check: drug, alcohol, crude or sexual references
    "b24b2ec6aa", "73250405bd", "c83119d927", "7b10c8f2f4", "42ad40f1e2", "bfe6f9c09a", "87cae92ada", "e624668a3d",
    "90da5b293c", "18ae936edf", "4a552ee754", "ee23034f51", "c2b44eb8fb", "92d20bd2ba", "efac808e7c", "de05405af0",
    "36c06af8e7", "77d6f53911", "4753e66b33", "0fc6d7fffd", "2422cc1091", "8a1e491575", "2bf8aaeeef", "dd2bd4c0c2",
    "d47d9e3117", "a2b28d227f", "7b60cf9d2c", "377aea9bec", "cda3197f67", "5f73d1ec4d", "b665177bd4", "cd05af5050",
    "48e8ef921d", "44137d054a", "5658e8c7ed", "3baa0215cc", "38402e4d13",
    # real tragedies asked as trivia; graphic horror or violence; political flashpoints
    "dfaa821c00", "9c4037dac2", "b80d786341", "3b391d6b14", "57cdce9ef6", "988d7a8357", "33242191b5", "15364ba138",
    "c39015cf72", "474216f98c", "85bd4e31e7", "d8117c67fa", "97127fb761", "c4652602c5", "34e3ac73be", "b9dc508a27",
    "7a08b7408e", "bd654a3270", "8ee79243f7", "e8fbc67d8b", "117834b7bc", "8418188f53", "cbc8dd1211", "2181f83cac",
    "4728ca8a42", "18c2806ac2", "6243576a4d", "47fdbadd42", "9ab5a7037e", "8e1992cc3e", "c8ae5e49b8", "1ef2cacab3",
    "e20b11145d", "0535be57ab",
    # wrong, disputed, outdated or misspelled
    "d36be0c6b3", "8f2e689589", "967cd0585b", "2f5173e788", "698b3fcb16", "6b04a405c0", "d957b5ebc1", "a087e2c231",
    "5b7e24e95e", "bd77947a49", "f05d2bd06c", "1c2b34a9d4", "e1865026f0", "a5a816db95", "9d1664bf8c", "1428729d73",
    "4a066cdd4f", "0c6bac2620", "5a3fe091bb", "53defe178e", "25c4d6db63", "c630b1ae24", "de84760186", "9fdf44eeb8",
    "e9e2cddf5c", "947d4001a4", "95cdbc54ea", "89263f34b5", "75dde8bc87", "ab4e2f29d5", "afe6a659c6", "dba06a6755",
    "57bed4fc07", "4c8184b541", "0503212f1e", "850e33e09a", "7956f9d43a", "795f421ab4", "4e57dcbb57", "976350cbe8",
    "ab0e72f545", "999384a64c", "4743af3412", "6bafaee378", "9e23bb25e9", "c66fffc21a", "cbd1fcc6c2", "0254780543",
    "e21b77c3b1", "266b7ab855",
    # typed questions that need their options or have several right answers
    "28b9949d5a", "23a7861c7f", "5be9b74e3d", "aa8b57cdf5", "f15f3a1dd2", "fc4692f4a1", "ae648bca41", "88f137cd88",
    "57d3a3b40e", "4aa43368fd", "b630474c0b", "39397a83f4", "6b31e0682e", "ea68f2ae68", "0e3eb290c0", "58f88e8388",
    "c2262c53f0", "83478bc71a", "ae367cae75", "8fea975549", "8910491353", "e2f1097a0e", "15c665e1a0",
    # stored answers in a form nobody types
    "4b4d08eda9", "73b2fb60a5", "78d25ae8e4", "8473a3da17", "56bd2fab46", "4169066b55", "27dbcb43fc", "f104bb9f27",
})
# Checked by hand: typed questions the "needs its options" or date filter would wrongly drop.
KEEP_IDS = frozenset({
    "95c4855061", "cc8223f928", "9a3af53f71", "60cde368d5", "e3b9706abe", "1df1830466", "af81c2f47c",
    "769ed5ba08",
})
MAX_TYPED_WORDS = 3
MAX_TYPED_CHARS = 25
MAX_QUESTION = 300
MAX_EASY_TEXT = 400  # question plus options, so the multiple-choice message fits in one chat message
# Typed answers whose meaning is in symbols the matcher can't compare: C++, -40, 13.8, 2-3, 4/4, V = I*R.
MEANINGFUL_SYMBOLS = re.compile(r"[+#=*^<>°%?!♡♪]|\d\s*[.\-/:]\s*\d|(?:^|\s)-\s*\d")


def get(path: str, **params: object) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:  # includes HTTP 429 and dropped connections
            if attempt == 4:
                raise
            print(f"  retrying after {exc}", flush=True)
            time.sleep(DELAY * 2 ** (attempt + 1))
    raise AssertionError("unreachable")


def clean(text: str) -> str:
    """Invisible characters (soft hyphens, direction marks) removed and spaces collapsed."""
    return " ".join(strip_invisible(text).split())


def typeable(question: str, answer: str, qid: str = "") -> bool:
    lowered = question.lower()
    reviewed = qid in KEEP_IDS
    return (
        len(answer.split()) <= MAX_TYPED_WORDS
        and len(answer) <= MAX_TYPED_CHARS
        and normalize(answer) != ""  # "♡♪!?" or "?:" can't be typed as a guess
        and not MEANINGFUL_SYMBOLS.search(answer)
        and not MONTH_DATE.search(answer)
        and not LONG_NUMBER.search(answer.replace(",", ""))
        and not (APPROXIMATE.search(lowered) and re.search(r"\d", answer))
        and (reviewed or not NEEDS_OPTIONS.search(question))
    )


def clear_options(options: list[str]) -> bool:
    """Easy options must read differently once spaces and case are ignored, and none may be a lone
    letter, which a player would read as A-D ("E", "A", "I", "O")."""
    compact = [normalize(o).replace(" ", "") for o in options]
    lone_letter = any(len(c) == 1 and c.isalpha() for c in compact)
    return len(set(compact)) == len(options) and "" not in compact and not lone_letter


def keep(entry: dict, blocked: BlockedWords) -> bool:
    """Every rule a question must pass, used both while downloading and by --refilter."""
    question, answer = entry["question"], entry["answer"]
    texts = [question, answer, *entry.get("wrong", [])]
    if entry["id"] in EXCLUDED_IDS or len(question) > MAX_QUESTION:
        return False
    if any(blocked.found_in(t) or MATURE_TOPICS.search(t) for t in texts):
        return False
    if entry["difficulty"] == "easy":
        options = [answer, *entry["wrong"]]
        return sum(len(t) + 4 for t in options) + len(question) <= MAX_EASY_TEXT and clear_options(options)
    return typeable(question, answer, entry["id"])


def fetch_all(token: str, category_id: int, difficulty: str) -> list[dict]:
    """Every multiple-choice question for one category and difficulty (the token prevents repeats)."""
    found: list[dict] = []
    amount = 50
    while amount >= 1:
        time.sleep(DELAY)
        data = get("api.php", amount=amount, category=category_id, difficulty=difficulty,
                   type="multiple", encode="url3986", token=token)
        code = data["response_code"]
        if code == 0:
            found.extend(data["results"])
        elif code in (1, 4):  # fewer than `amount` left (with a token, Open Trivia DB may say either)
            amount //= 2
        elif code == 5:  # rate limited: wait and retry
            time.sleep(DELAY)
        else:
            raise RuntimeError(f"Open Trivia DB returned response code {code}")
    return found


def question_key(question: str) -> str:
    """Questions that differ only in punctuation or case are the same question."""
    return re.sub(r"[^a-z0-9]", "", question.lower())


def tidy(entry: dict) -> dict:
    entry = dict(entry, question=clean(entry["question"]), answer=clean(entry["answer"]))
    if "wrong" in entry:
        entry["wrong"] = [clean(w) for w in entry["wrong"]]
    return entry


def refilter() -> None:
    blocked = BlockedWords.load(Assets())
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    before = len(payload["questions"])
    kept, keys = [], set()
    for q in map(tidy, payload["questions"]):
        if keep(q, blocked) and question_key(q["question"]) not in keys:
            keys.add(question_key(q["question"]))
            kept.append(q)
    payload["questions"] = kept
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"kept {len(payload['questions'])} of {before} questions in {OUT}")


def main() -> None:
    if "--refilter" in sys.argv[1:]:
        refilter()
        return
    blocked = BlockedWords.load(Assets())
    token = get("api_token.php", command="request")["token"]
    questions: list[dict] = []
    seen: set[str] = set()  # question keys
    for ours, ids in CATEGORIES.items():
        for difficulty in DIFFICULTIES:
            raw = [q for category_id in ids for q in fetch_all(token, category_id, difficulty)]
            kept = 0
            for q in raw:
                question = clean(urllib.parse.unquote(q["question"]))
                answer = clean(urllib.parse.unquote(q["correct_answer"]))
                wrong = [clean(urllib.parse.unquote(a)) for a in q["incorrect_answers"]]
                qid = hashlib.sha1(question.encode()).hexdigest()[:10]
                entry = {"id": qid, "category": ours, "difficulty": difficulty, "question": question, "answer": answer}
                if difficulty == "easy":
                    entry["wrong"] = wrong
                if question_key(question) in seen or not keep(entry, blocked):
                    continue
                seen.add(question_key(question))
                questions.append(entry)
                kept += 1
            print(f"{ours:10} {difficulty:6} fetched {len(raw):4} kept {kept:4}", flush=True)
    payload = {
        "source": "Open Trivia DB (https://opentdb.com), licensed CC BY-SA 4.0",
        "fetched": date.today().isoformat(),
        "questions": questions,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"wrote {len(questions)} questions to {OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `bot/content/TRIVIA_CREDITS.md`**

```markdown
# Trivia credits

The trivia questions in `trivia.json` come from [Open Trivia DB](https://opentdb.com/), licensed
under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), downloaded on 2026-10-05
with `scripts/fetch_trivia.py`. `?help trivia` names the source and license in chat.

Changes made to the original questions:

- Text was decoded from the API's URL encoding, with invisible characters removed and spaces tidied.
- Easy questions keep their four options. Medium and hard questions are asked without options
  (typed answers), and were kept only if the answer can reasonably be typed.
- Questions were left out if they contained blocked words or mature topics, needed their options to
  make sense, duplicated another question, or were found to be wrong or out of date.

The adapted question bank is shared under the same license.
```

- [ ] **Step 3: Generate `bot/content/trivia.json`**

Run: `.venv/bin/python scripts/fetch_trivia.py`
Expected: it takes about 25 minutes; the last line reads `wrote N questions` with N around 2,800.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: 462 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_trivia.py bot/content/TRIVIA_CREDITS.md bot/content/trivia.json
git commit -m "Phase 2: trivia question bank from Open Trivia DB"
```

### Task 8: Riddles

**Files:**
- Replace: `bot/content/riddles.json`

About 200 classic, clean riddles, written for the bot by one agent and checked by a second (answers right, clues helpful but not giving the answer away, no generic alternative answers that a wrong guess could hit, nothing inappropriate). Task 10's content test enforces the mechanical rules.

- [ ] **Step 1: Write `bot/content/riddles.json`**

```json
[
  {"riddle": "What has hands but can't clap?", "answers": ["clock", "watch", "clocks", "stopwatch"], "clue": "You probably check me several times a day."},
  {"riddle": "What has to be broken before you can use it?", "answers": ["egg", "eggs"], "clue": "Breakfast often starts by cracking one open."},
  {"riddle": "What gets wetter the more it dries?", "answers": ["towel", "towels"], "clue": "You grab one after a shower or a swim."},
  {"riddle": "What has 88 keys but can't open a single door?", "answers": ["piano", "pianos", "keyboard"], "clue": "It makes music when you press its black and white parts."},
  {"riddle": "What has a head and a tail but no body?", "answers": ["coin", "coins", "penny", "pennies", "quarter", "dime", "nickel"], "clue": "Flip me to settle a tough choice."},
  {"riddle": "What goes up but never comes down?", "answers": ["age"], "clue": "Every birthday makes this number bigger."},
  {"riddle": "What has one eye but can't see, and is very sharp at the other end?", "answers": ["needle", "needles"], "clue": "Tailors push thread through me."},
  {"riddle": "What has lots of teeth but never bites?", "answers": ["comb", "combs", "zipper"], "clue": "You run me through your hair to tidy it."},
  {"riddle": "What can you catch but not throw?", "answers": ["cold", "colds", "flu", "breath"], "clue": "Sniffles and sneezes usually come with it."},
  {"riddle": "What has a mouth but never eats, a bed but never sleeps, and runs but never walks?", "answers": ["river", "rivers", "stream", "creek"], "clue": "It flows from the mountains down to the sea."},
  {"riddle": "What has a neck but no head, and wears a cap?", "answers": ["bottle", "bottles"], "clue": "You might find soda or water inside me."},
  {"riddle": "The more you take, the more you leave behind. What are they?", "answers": ["footsteps", "footstep", "steps", "step", "footprints", "footprint", "tracks"], "clue": "Walking across wet sand shows them clearly."},
  {"riddle": "What has a thumb and four fingers but isn't alive?", "answers": ["glove", "gloves"], "clue": "You wear one on each hand when it's chilly outside."},
  {"riddle": "What is full of holes but still holds water?", "answers": ["sponge", "sponges"], "clue": "You use me to scrub the dishes."},
  {"riddle": "What goes up when the rain comes down?", "answers": ["umbrella", "umbrellas", "brolly"], "clue": "You open me over your head on a stormy day."},
  {"riddle": "What has four legs but can't walk, and holds your dinner every night?", "answers": ["table", "tables", "dinner table", "kitchen table"], "clue": "You set plates and forks on me."},
  {"riddle": "I'm tall when I'm young and short when I'm old. What am I?", "answers": ["candle", "candles", "pencil", "pencils"], "clue": "I have a wick and I melt as I glow."},
  {"riddle": "What can travel around the world while staying in a corner?", "answers": ["stamp", "stamps", "postage stamp"], "clue": "You stick me on an envelope before mailing it."},
  {"riddle": "I have a spine but no bones, a cover but no blanket, and pages full of stories. What am I?", "answers": ["book", "books", "novel"], "clue": "Libraries are full of me."},
  {"riddle": "What has an eye but can't see, and spins with powerful winds?", "answers": ["hurricane", "hurricanes", "tornado", "tornadoes", "storm", "cyclone", "typhoon"], "clue": "Weather reporters warn people when one is coming."},
  {"riddle": "What belongs to you, but other people use it more than you do?", "answers": ["name", "names"], "clue": "People call it out when they want your attention."},
  {"riddle": "What can you hold in your right hand but never in your left hand?", "answers": ["left hand", "left elbow", "left arm"], "clue": "Think about a body part on the opposite side."},
  {"riddle": "What room has no doors, no windows, and no walls?", "answers": ["mushroom", "mushrooms"], "clue": "It's a fungus you might find on a pizza."},
  {"riddle": "What has a ring but no finger, and lets you talk to friends far away?", "answers": ["phone", "phones", "telephone", "cellphone", "cell phone", "smartphone"], "clue": "Many people keep one in their pocket."},
  {"riddle": "I'm lighter than a feather, yet the strongest person can't hold me for more than a few minutes. What am I?", "answers": ["breath", "breathing", "air"], "clue": "You take one in and let it out all day long."},
  {"riddle": "What is always in front of you but can never be seen?", "answers": ["future"], "clue": "It's everything that hasn't happened yet."},
  {"riddle": "What can fill a room but takes up no space?", "answers": ["light", "sunlight", "darkness", "dark", "sound"], "clue": "Flip a switch and it shows up instantly."},
  {"riddle": "What gets bigger the more you take away from it?", "answers": ["hole", "holes", "pit"], "clue": "Grab a shovel and start digging."},
  {"riddle": "If you drop me I'm sure to crack, but smile at me and I'll always smile back. What am I?", "answers": ["mirror", "mirrors"], "clue": "You check your reflection in me."},
  {"riddle": "What comes once in a minute, twice in a moment, but never in a thousand years?", "answers": ["m", "letter m"], "clue": "Look at the spelling, not the clock."},
  {"riddle": "What word is always spelled wrong in the dictionary?", "answers": ["wrong"], "clue": "The answer is hiding right there in the question."},
  {"riddle": "What building has the most stories?", "answers": ["library", "libraries", "bookstore", "book store"], "clue": "Quiet please, people are reading here."},
  {"riddle": "What has cities but no houses, forests but no trees, and water but no fish?", "answers": ["map", "maps", "atlas", "globe"], "clue": "Explorers unfold me to find their way."},
  {"riddle": "What starts with T, ends with T, and has T in it?", "answers": ["teapot", "teapots", "tea pot"], "clue": "You brew a hot drink in me and pour it into cups."},
  {"riddle": "What kind of band never plays any music?", "answers": ["rubber band", "rubber bands", "elastic band", "elastic bands", "elastic"], "clue": "It's stretchy and can snap if you pull it too far."},
  {"riddle": "What has lots of eyes but can't see a thing?", "answers": ["potato", "potatoes"], "clue": "You can mash me, bake me, or fry me."},
  {"riddle": "What has one head, one foot, and four legs?", "answers": ["bed", "beds"], "clue": "You sleep on me every night."},
  {"riddle": "What goes up a hill and down a hill but always stays in the same place?", "answers": ["road", "roads", "street", "path", "highway", "trail"], "clue": "Cars drive on me all day long."},
  {"riddle": "What is so fragile that saying its name breaks it?", "answers": ["silence", "quiet"], "clue": "A library asks you to keep it."},
  {"riddle": "What can you break even if you never pick it up, touch it, or see it?", "answers": ["promise", "promises", "rule", "rules", "word", "silence", "record", "law", "laws"], "clue": "You make one when you say you'll definitely do something."},
  {"riddle": "What goes up and down but never moves?", "answers": ["stairs", "stair", "staircase", "stairway", "steps", "temperature"], "clue": "You climb them to reach the next floor."},
  {"riddle": "I have branches but no fruit, trunk, or leaves. What am I?", "answers": ["bank", "banks"], "clue": "People keep their money safe here."},
  {"riddle": "I can't talk, but I always reply when spoken to. What am I?", "answers": ["echo", "echoes", "echos"], "clue": "Shout in a canyon or cave to hear me."},
  {"riddle": "The more of me there is, the less you can see. What am I?", "answers": ["darkness", "dark", "fog", "night"], "clue": "Turning off the lamps brings it."},
  {"riddle": "Mary's father has five daughters: Nana, Nene, Nini, and Nono. What is the fifth daughter's name?", "answers": ["mary"], "clue": "Read the very first word again."},
  {"riddle": "I follow you everywhere and copy every move, but you can never touch me or catch me. What am I?", "answers": ["shadow", "shadows"], "clue": "I show up when the sun is behind you."},
  {"riddle": "What has lots of needles but never sews, and stays green all year long?", "answers": ["pine tree", "pine trees", "pine", "pines", "evergreen", "fir", "fir tree", "spruce", "christmas tree", "cactus"], "clue": "You'll find cones and sticky sap on me in the forest."},
  {"riddle": "What starts with an E, ends with an E, but usually has only one letter inside?", "answers": ["envelope", "envelopes"], "clue": "You seal me and send me through the mail."},
  {"riddle": "Some months have 30 days and some have 31. How many have 28?", "answers": ["all", "all of them", "all months", "every month", "each month", "every one", "twelve", "12"], "clue": "Does February have at least that many days?"},
  {"riddle": "I have keys but no locks, space but no room, and you can enter but never go inside. What am I?", "answers": ["keyboard", "keyboards"], "clue": "Gamers press WASD on me to move around."},
  {"riddle": "What's black when you buy it, red when you use it, and gray when you throw it away?", "answers": ["charcoal", "coal", "coals"], "clue": "It's used to grill burgers at a cookout."},
  {"riddle": "What gets sharper the more you use it?", "answers": ["brain", "brains", "mind", "skill", "skills"], "clue": "Puzzles like this one help exercise it."},
  {"riddle": "What is always coming but never arrives?", "answers": ["tomorrow"], "clue": "When it finally shows up, everyone calls it today."},
  {"riddle": "What can be cracked, made, told, and played?", "answers": ["joke", "jokes"], "clue": "Comedians share these to get laughs."},
  {"riddle": "What has bark but no bite, and rings but no fingers?", "answers": ["tree", "trees"], "clue": "Birds build nests in my branches."},
  {"riddle": "Where does today come before yesterday?", "answers": ["dictionary", "dictionaries"], "clue": "Words are listed there in alphabetical order."},
  {"riddle": "What has four wheels and lots of flies?", "answers": ["garbage truck", "garbage trucks", "trash truck", "trash trucks", "dump truck", "rubbish truck", "bin lorry", "dumpster"], "clue": "It visits your street on collection day."},
  {"riddle": "What kind of tree can you carry in your hand?", "answers": ["palm", "palms", "palm tree"], "clue": "Coconuts grow on it, and you have one on each hand."},
  {"riddle": "What five-letter word becomes shorter when you add two letters to it?", "answers": ["short"], "clue": "Try adding 'er' to the end."},
  {"riddle": "What is easy to get into but hard to get out of?", "answers": ["trouble", "bed"], "clue": "Kids land here after breaking the rules."},
  {"riddle": "What has a tongue but can't talk, and goes everywhere your feet go?", "answers": ["shoe", "shoes", "sneaker", "sneakers", "boot", "boots"], "clue": "You tie my laces before heading out."},
  {"riddle": "What kind of coat can only be put on when it's wet?", "answers": ["paint"], "clue": "You brush it onto walls to change their color."},
  {"riddle": "What do you call a bear with no teeth?", "answers": ["gummy bear", "gummy bears", "gummi bear", "gummy"], "clue": "It's a chewy candy shaped like an animal."},
  {"riddle": "What has ears but cannot hear?", "answers": ["corn", "corncob", "corn cob", "maize", "sweetcorn"], "clue": "It grows tall on farms and pops into a movie snack."},
  {"riddle": "What lets you look right through a wall?", "answers": ["window", "windows"], "clue": "It's made of glass and lets sunlight in."},
  {"riddle": "I have a foot but no legs, and I help you draw straight lines. What am I?", "answers": ["ruler", "rulers", "yardstick", "measuring tape", "tape measure"], "clue": "You keep me in your pencil case for math class."},
  {"riddle": "What gets cut on a table but is never eaten?", "answers": ["cards", "card", "deck", "deck of cards", "playing cards"], "clue": "You shuffle it before poker or solitaire."},
  {"riddle": "What is orange and sounds like a parrot?", "answers": ["carrot", "carrots"], "clue": "Rabbits love to munch on this vegetable."},
  {"riddle": "What can you serve but never eat?", "answers": ["ball", "balls", "tennis ball", "tennis", "volleyball", "shuttlecock", "badminton"], "clue": "Athletes hit it over a net to start a point."},
  {"riddle": "Which weighs more, a pound of feathers or a pound of bricks?", "answers": ["neither", "same", "equal", "weigh the same", "same weight"], "clue": "Look closely at how much of each there is."},
  {"riddle": "What starts with P, ends with E, and has thousands of letters?", "answers": ["post office", "post offices", "postoffice"], "clue": "You go there to send packages and buy stamps."},
  {"riddle": "What kind of cup can you eat?", "answers": ["cupcake", "cupcakes", "cup cake"], "clue": "It's a small frosted treat at birthday parties."},
  {"riddle": "What has a neck but no head, and two arms but no hands?", "answers": ["shirt", "shirts", "t shirt", "tshirt", "sweater", "hoodie", "jacket", "coat"], "clue": "You pull it over your head every morning."},
  {"riddle": "Forward I'm heavy, but backward I'm not. What am I?", "answers": ["ton", "tons"], "clue": "Spell it backward and see what you get."},
  {"riddle": "What is at the end of a rainbow?", "answers": ["w", "letter w"], "clue": "Look closely at how that last word is spelled."},
  {"riddle": "I'm found in socks, scarves, and mittens, and often in the paws of playful kittens. What am I?", "answers": ["yarn", "wool", "string", "thread"], "clue": "Knitters use whole balls of it."},
  {"riddle": "I'm not alive, but I grow. I need air but have no lungs, and water makes me disappear. What am I?", "answers": ["fire", "fires", "flame", "flames", "campfire"], "clue": "It's hot and bright, and you roast marshmallows over it."},
  {"riddle": "What runs all the way around the yard without ever moving?", "answers": ["fence", "fences", "wall", "walls", "hedge"], "clue": "It keeps the dog from wandering off."},
  {"riddle": "What do you throw out when you want to use it, and take in when you're done with it?", "answers": ["anchor", "anchors"], "clue": "Ships drop it to stay in one place."},
  {"riddle": "What question can you never honestly answer 'yes' to?", "answers": ["are you asleep", "asleep", "sleeping", "sleep"], "clue": "Think about what a snoozing person can't do."},
  {"riddle": "What do you call a fish with no eye?", "answers": ["fsh"], "clue": "Take one letter out of its name."},
  {"riddle": "What has four eyes but can't see?", "answers": ["mississippi"], "clue": "It's a long river and a tricky word to spell."},
  {"riddle": "What's black and white and read all over?", "answers": ["newspaper", "newspapers", "news paper", "paper", "newsprint"], "clue": "People used to get one delivered to their doorstep every morning."},
  {"riddle": "What kind of key opens a banana?", "answers": ["monkey", "monkeys"], "clue": "It swings through the jungle trees."},
  {"riddle": "What kind of dog keeps the best time?", "answers": ["watchdog", "watchdogs", "watch dog"], "clue": "It guards your house, and part of its name sits on your wrist."},
  {"riddle": "What type of music are balloons afraid of?", "answers": ["pop", "pop music"], "clue": "It's the sound they make when they burst."},
  {"riddle": "What kind of ship never sails but can last forever between two people?", "answers": ["friendship", "friendships", "friends"], "clue": "Best buddies share this bond."},
  {"riddle": "What can run but has no legs, and needs a tissue when it does?", "answers": ["nose", "noses"], "clue": "It sits in the middle of your face and smells things."},
  {"riddle": "What appears once in a year, twice in a week, but never in a day?", "answers": ["e", "letter e"], "clue": "It's the most-used vowel in English."},
  {"riddle": "What has six faces but no makeup, and twenty-one eyes but can't see?", "answers": ["dice", "die"], "clue": "You roll it in lots of board games."},
  {"riddle": "What flies without wings when you're having fun?", "answers": ["time"], "clue": "Clocks and calendars keep track of it."},
  {"riddle": "What has a crown but no head, and roots but no leaves?", "answers": ["tooth", "teeth", "molar"], "clue": "The dentist checks these at every visit."},
  {"riddle": "I'm an odd number, but take away one letter and I become even. What am I?", "answers": ["seven", "7"], "clue": "Try dropping the first letter from the names of a few odd numbers."},
  {"riddle": "What is taller than the trees, has roots no one can see, and never grows an inch?", "answers": ["mountain", "mountains", "mount", "hill", "volcano", "volcanoes"], "clue": "Hikers and climbers try to reach my peak."},
  {"riddle": "What looks like a horse wearing black-and-white striped pajamas?", "answers": ["zebra", "zebras"], "clue": "It lives on the African savanna."},
  {"riddle": "What animal is always ready to play baseball?", "answers": ["bat", "bats"], "clue": "It sleeps upside down in caves."},
  {"riddle": "What has a trunk but no suitcase, big flappy ears, and never forgets?", "answers": ["elephant", "elephants"], "clue": "It's the largest animal that lives on land."},
  {"riddle": "In what game can you chop trees, dig up diamonds, and build anything out of blocks?", "answers": ["minecraft"], "clue": "Steve and Alex are its default characters."},
  {"riddle": "Trainers in this famous series want to catch them all. What are they?", "answers": ["pokemon", "pokemons", "pocket monsters"], "clue": "Pikachu is the most famous one."},
  {"riddle": "What button stops the game without making you lose any progress?", "answers": ["pause", "pause button", "pause menu"], "clue": "Hit it when you need a snack break mid-match."},
  {"riddle": "The more quests you finish, the more I fill up, and when I'm full you level up. What am I?", "answers": ["xp", "exp", "experience", "xp bar", "experience bar", "experience points"], "clue": "Gamers grind for hours to earn it."},
  {"riddle": "I remember your progress, and when you fall you come back to me instead of the start. What am I?", "answers": ["checkpoint", "checkpoints", "save point", "savepoint", "save", "spawn point", "respawn point"], "clue": "In platformers, touching a flag usually sets one."},
  {"riddle": "I'm purple, I'm packed with streamers, and my name also means a sudden little muscle movement. What am I?", "answers": ["twitch"], "clue": "It's where you are right now."},
  {"riddle": "I can be wired or wireless, I have buttons and sticks, and I make your character move. What am I?", "answers": ["controller", "controllers", "gamepad", "joystick", "joypad", "remote"], "clue": "You grip me with both hands while playing on a console."},
  {"riddle": "What has a mouse but no cheese, and a screen but no door?", "answers": ["computer", "computers", "pc", "laptop", "desktop"], "clue": "You can browse websites and play games on it."},
  {"riddle": "What web catches no flies but connects the whole world?", "answers": ["internet", "world wide web", "online"], "clue": "You're using it right now to watch this stream."},
  {"riddle": "What is something you will never see again?", "answers": ["yesterday", "past"], "clue": "It came right before today."},
  {"riddle": "What two meals can you never eat for breakfast?", "answers": ["lunch and dinner", "lunch", "dinner", "supper"], "clue": "Think about the meals that come later in the day."},
  {"riddle": "What is the longest word in the dictionary?", "answers": ["smiles", "smile"], "clue": "Measure the distance between its first and last letters."},
  {"riddle": "What contains all 26 letters but only has eight letters itself?", "answers": ["alphabet", "alphabets", "abc", "abcs"], "clue": "Kids sing a song to learn it, from A to Z."},
  {"riddle": "What always points north, has a needle, and helps hikers find their way?", "answers": ["compass", "compasses"], "clue": "Sailors carried one long before phones had maps."},
  {"riddle": "What kind of nut has a hole in the middle but no shell?", "answers": ["doughnut", "doughnuts", "donut", "donuts"], "clue": "It's a round sweet treat, often covered in sprinkles."},
  {"riddle": "What has a hundred legs but can only lean against the wall?", "answers": ["broom", "brooms", "broomstick", "mop", "brush"], "clue": "You sweep the floor with me."},
  {"riddle": "I'm lighter than what I'm made of, and most of me hides below the surface. What am I?", "answers": ["iceberg", "icebergs", "ice", "ice cube"], "clue": "I float in freezing seas near the poles."},
  {"riddle": "What comes down but never goes up?", "answers": ["rain", "raindrop", "raindrops", "rainfall", "snow"], "clue": "Grab an umbrella when it starts falling."},
  {"riddle": "What becomes whiter the dirtier it gets?", "answers": ["chalkboard", "chalkboards", "blackboard", "blackboards"], "clue": "Teachers wrote on it in classrooms before whiteboards."},
  {"riddle": "What did the ocean say to the beach?", "answers": ["waved", "wave", "waves"], "clue": "Think about how water moves on the shore."},
  {"riddle": "What did one wall say to the other wall?", "answers": ["corner", "at the corner"], "clue": "Think about where two walls touch."},
  {"riddle": "Why did the bicycle fall over?", "answers": ["two tired", "too tired", "tired"], "clue": "It needed a rest, and it has a pair of wheels."},
  {"riddle": "What do you call a deer with no eyes?", "answers": ["no idea", "no eye deer", "no eyes deer", "no eyed deer", "noidea"], "clue": "Say the answer out loud: it sounds like a shrug."},
  {"riddle": "Where does a sheep go to get a haircut?", "answers": ["baa baa shop", "baabaa shop", "baa shop", "barber shop", "barbershop"], "clue": "Think about the noise a sheep makes."},
  {"riddle": "What do you call a fake noodle?", "answers": ["impasta", "impostor", "imposter"], "clue": "It sounds like someone pretending to be somebody else."},
  {"riddle": "What do you call cheese that isn't yours?", "answers": ["nacho cheese", "nacho", "nachos"], "clue": "Say 'not your' really fast."},
  {"riddle": "Why can't a nose be twelve inches long?", "answers": ["foot", "feet", "be a foot"], "clue": "Think about units of length."},
  {"riddle": "What do you call a sleeping bull?", "answers": ["bulldozer", "bulldozers", "bull dozer"], "clue": "Construction sites use this big yellow machine."},
  {"riddle": "What has a head like a cat, feet like a cat, and a tail like a cat, but isn't a cat?", "answers": ["kitten", "kittens", "kitty", "kitties"], "clue": "It's a baby version of a pet that purrs."},
  {"riddle": "What is full of holes but as strong as steel?", "answers": ["chain", "chains"], "clue": "Bikes and swings both use links of this."},
  {"riddle": "I have no feet, hands, or wings, but I climb up to the sky. What am I?", "answers": ["smoke", "steam"], "clue": "Chimneys puff it out."},
  {"riddle": "What do you call a snowman in the summer?", "answers": ["puddle", "puddles", "water"], "clue": "It's what's left after warm sunshine melts the ice."},
  {"riddle": "What falls all winter but never gets hurt?", "answers": ["snow", "snowflake", "snowflakes"], "clue": "Kids build forts and people out of it."},
  {"riddle": "What walks on four legs in the morning, two legs at noon, and three legs in the evening?", "answers": ["human", "humans", "person", "people", "man", "mankind"], "clue": "Think of a whole lifetime: crawling, walking, then using a cane."},
  {"riddle": "If you have me, you want to share me. If you share me, you don't have me anymore. What am I?", "answers": ["secret", "secrets"], "clue": "Friends whisper these and promise to keep them."},
  {"riddle": "What has eight arms, three hearts, and can change color to hide?", "answers": ["octopus", "octopuses", "octopi", "squid"], "clue": "It lives in the sea and sprays ink when scared."},
  {"riddle": "I'm the tallest animal around, with a spotted coat and a super long neck. What am I?", "answers": ["giraffe", "giraffes"], "clue": "I nibble leaves from the tops of trees."},
  {"riddle": "What kind of bow can never be tied?", "answers": ["rainbow", "rainbows"], "clue": "Look up after a storm when the sun comes out."},
  {"riddle": "What kind of shoes do ninjas wear?", "answers": ["sneakers", "sneaker", "sneaks"], "clue": "Think about moving quietly so nobody hears you."},
  {"riddle": "I'm sweet and golden, and tiny buzzing workers make me. What am I?", "answers": ["honey"], "clue": "Bears love to dip their paws into a pot of me."},
  {"riddle": "What has a pupil but never goes to school?", "answers": ["eye", "eyes", "eyeball", "eyeballs"], "clue": "You blink it many times a minute."},
  {"riddle": "What is the strongest day of the week?", "answers": ["sunday", "sundays", "saturday"], "clue": "The rest are just weak days."},
  {"riddle": "What did the big flower say to the little flower?", "answers": ["bud", "buddy"], "clue": "It's a baby blossom and also a nickname for a pal."},
  {"riddle": "What's an astronaut's favorite key on the keyboard?", "answers": ["space bar", "spacebar", "space"], "clue": "It's the longest one, right under your thumbs."},
  {"riddle": "Where do cows go on a Saturday night?", "answers": ["moovies", "movies", "movie", "movie theater", "cinema"], "clue": "Think of the sound a cow makes and a night out with popcorn."},
  {"riddle": "What do you call a pig that knows karate?", "answers": ["pork chop", "pork chops", "porkchop"], "clue": "It's a dinner dish and also a martial arts move."},
  {"riddle": "Why was the math book sad?", "answers": ["problems", "problem", "too many problems"], "clue": "Think about what homework pages are full of."},
  {"riddle": "What tastes better than it smells?", "answers": ["tongue", "tongues"], "clue": "It's a muscle inside your mouth."},
  {"riddle": "What is a cat's favorite color?", "answers": ["purrple", "purple"], "clue": "Think about the sound a happy kitty makes."},
  {"riddle": "I go around and around but always straight ahead, and I never complain wherever I'm led. What am I?", "answers": ["wheel", "wheels", "tire", "tires", "tyre"], "clue": "Cars and bikes roll along on me."},
  {"riddle": "I fly high on windy days with a long tail, but someone always holds my string. What am I?", "answers": ["kite", "kites"], "clue": "Kids run across the park to launch me into the air."},
  {"riddle": "What do you leave on everything you touch without even trying?", "answers": ["fingerprints", "fingerprint", "prints"], "clue": "Every person has a unique swirly pattern of these."},
  {"riddle": "What do you get if you cross a fish with an elephant?", "answers": ["swimming trunks", "swim trunks", "trunks", "swimsuit"], "clue": "Think about beachwear and an elephant's nose."},
  {"riddle": "I have a head but no brain, and I drive nails all day. What am I?", "answers": ["hammer", "hammers", "mallet"], "clue": "Builders keep me in their toolbox."},
  {"riddle": "What do you call a belt made out of watches?", "answers": ["waist of time", "waste of time"], "clue": "Think about where a belt goes and what clocks measure."},
  {"riddle": "What do you call an alligator wearing a vest?", "answers": ["investigator", "investigators", "detective"], "clue": "Someone who solves mysteries has this job title, and it hides a piece of clothing."},
  {"riddle": "What do you call a boomerang that doesn't come back?", "answers": ["stick", "sticks"], "clue": "It's just a plain piece of wood now."},
  {"riddle": "If a red house is made of red bricks, what is a greenhouse made of?", "answers": ["glass"], "clue": "Plants grow inside because sunlight shines straight through it."},
  {"riddle": "If you have three apples and you take away two, how many do you have?", "answers": ["two", "2"], "clue": "Count the ones in your hands, not the ones left behind."},
  {"riddle": "Imagine you're stuck in a dark room with no doors or windows. How do you get out?", "answers": ["stop imagining", "quit imagining"], "clue": "Look at the very first word of the question."},
  {"riddle": "I shave every day, but my beard stays the same. What am I?", "answers": ["barber", "barbers", "hairdresser", "hair stylist"], "clue": "People visit this person's shop when their locks get too long."},
  {"riddle": "I fly without wings and cry without eyes. What am I?", "answers": ["cloud", "clouds", "raincloud", "rain cloud", "storm cloud"], "clue": "I float in the sky and sometimes block the sun."},
  {"riddle": "I'm yellow and sour, and people turn me into a summer drink with sugar and water. What am I?", "answers": ["lemon", "lemons"], "clue": "Take a bite of me and your face will pucker."},
  {"riddle": "What fruit is never lonely?", "answers": ["pear", "pears", "pair"], "clue": "Its name sounds like a word for two of something."},
  {"riddle": "I have layers and I make you cry, but I never say a mean word. What am I?", "answers": ["onion", "onions"], "clue": "Chopping me makes your eyes water."},
  {"riddle": "I'm a red fruit that wears my seeds on the outside. What am I?", "answers": ["strawberry", "strawberries"], "clue": "I'm often dipped in chocolate or piled on shortcake."},
  {"riddle": "I'm round, but you cut me into triangles, and I'm covered in melted cheese. What am I?", "answers": ["pizza", "pizzas"], "clue": "Delivery drivers bring me in a flat cardboard box."},
  {"riddle": "What has a core, seeds, and a stem, and supposedly keeps the doctor away?", "answers": ["apple", "apples"], "clue": "It can be red, green, or yellow and grows in orchards."},
  {"riddle": "What do you lose every time you stand up?", "answers": ["lap"], "clue": "It's where a cat curls up while you're sitting."},
  {"riddle": "I light up the night but I'm not a lamp, and my shape changes every few days. What am I?", "answers": ["moon", "full moon", "crescent"], "clue": "Astronauts first walked on me in 1969."},
  {"riddle": "I'm a star, but you can only see me during the day. What am I?", "answers": ["sun", "sunshine"], "clue": "Plants need me to grow, and I set every evening."},
  {"riddle": "I'm always running but I never move, and I keep your snacks nice and cool. What am I?", "answers": ["fridge", "fridges", "refrigerator", "freezer"], "clue": "Magnets and drawings often hang on my door."},
  {"riddle": "I'm soft and fluffy, and I hold your head up every night. What am I?", "answers": ["pillow", "pillows"], "clue": "Fresh cases go on me when the sheets get washed."},
  {"riddle": "I whistle when I'm hot, I have a spout, and I sit on the stove. What am I?", "answers": ["kettle", "kettles", "tea kettle", "teapot"], "clue": "I boil water for cocoa or noodles."},
  {"riddle": "When is a door not a door?", "answers": ["ajar", "jar"], "clue": "It's slightly open, and it sounds like something you keep jam in."},
  {"riddle": "What do you call a fly with no wings?", "answers": ["walk", "walker"], "clue": "Without wings, it has to get around on foot."},
  {"riddle": "What did one pencil say to the other pencil?", "answers": ["sharp", "sharpened"], "clue": "Think of a pencil's pointy tip and a word for looking stylish."},
  {"riddle": "What kind of flower grows on your face?", "answers": ["tulips", "tulip", "two lips"], "clue": "Say its name slowly: it sounds like a pair of mouth parts."},
  {"riddle": "What's the smartest insect?", "answers": ["spelling bee", "spelling bees"], "clue": "Think of a school contest where kids sound out tricky words letter by letter."},
  {"riddle": "What kind of key goes 'gobble gobble'?", "answers": ["turkey", "turkeys"], "clue": "It's a big farm bird with a colorful fanned tail."},
  {"riddle": "What has eight bits but you can't take a single bite of it?", "answers": ["byte", "bytes"], "clue": "Computers measure memory in huge groups of me."},
  {"riddle": "Why did the computer go to the doctor?", "answers": ["virus", "viruses", "bug", "malware", "had a virus"], "clue": "It's also what can give people the sniffles."},
  {"riddle": "What do you call a really funny mountain?", "answers": ["hilarious", "hillarious"], "clue": "It starts with a smaller kind of mountain."},
  {"riddle": "What season is the best for jumping on a trampoline?", "answers": ["spring", "springtime"], "clue": "Think of a bouncy metal coil and the season after winter."},
  {"riddle": "What is a tornado's favorite game?", "answers": ["twister"], "clue": "It's a party game where you put hands and feet on colored circles."},
  {"riddle": "What did the paper say to the pencil?", "answers": ["write on", "right on"], "clue": "Think of what a pencil does and a cool way to say 'awesome'."},
  {"riddle": "What do you call a pony with a sore throat?", "answers": ["hoarse", "little hoarse", "little horse"], "clue": "It sounds like the word for a scratchy voice."},
  {"riddle": "Why are fish so smart?", "answers": ["schools", "school", "live in schools"], "clue": "Think about where groups of fish swim and kids learn."},
  {"riddle": "What kind of bird can write?", "answers": ["penguin", "penguins"], "clue": "It waddles on the ice and can't fly."},
  {"riddle": "What bird is always out of breath?", "answers": ["puffin", "puffins"], "clue": "It's a seabird with a bright, colorful beak."},
  {"riddle": "What kind of fish only comes out at night?", "answers": ["starfish", "star fish", "starfishes"], "clue": "It has five arms and lives on the seafloor."},
  {"riddle": "Why is a sports stadium always so cool?", "answers": ["fans", "fan", "full of fans"], "clue": "Think about who cheers in the stands."},
  {"riddle": "Why did the scarecrow win an award?", "answers": ["outstanding", "in his field", "in the field"], "clue": "Think about where he spends all day on a farm."},
  {"riddle": "What do you call a factory that makes okay products?", "answers": ["satisfactory"], "clue": "Think of a word that means just good enough."},
  {"riddle": "I have a mane and a mighty roar, and they call me king of the jungle. What am I?", "answers": ["lion", "lions"], "clue": "I'm a big cat that lives in a pride."},
  {"riddle": "What jumps when it walks and sits when it stands?", "answers": ["kangaroo", "kangaroos", "roo"], "clue": "It carries its baby in a pouch."},
  {"riddle": "I carry my house on my back, move very slowly, and leave a shiny trail. What am I?", "answers": ["snail", "snails"], "clue": "Gardeners find me munching lettuce after the rain."},
  {"riddle": "What has a bill but never pays it?", "answers": ["duck", "ducks", "platypus"], "clue": "It quacks and paddles across ponds."},
  {"riddle": "What animal can jump higher than a house?", "answers": ["any animal", "every animal", "all animals", "cant jump", "cannot jump", "dont jump", "doesnt jump", "do not jump", "does not jump", "never jump"], "clue": "Think about how high a building is able to leap."},
  {"riddle": "What has to be taken before you can get it?", "answers": ["picture", "pictures", "photo", "photos", "photograph", "selfie"], "clue": "Someone says cheese right before it happens."},
  {"riddle": "Turn me on my side and I'm everything. Cut me in half and I'm nothing. What am I?", "answers": ["eight", "8"], "clue": "Sideways, I look like the infinity symbol."},
  {"riddle": "What gets smaller every time it takes a bath?", "answers": ["soap", "soaps", "soap bar"], "clue": "It makes bubbles when you wash your hands."},
  {"riddle": "Who wears a red cap, says 'Let's-a go!', and jumps on Goombas?", "answers": ["mario", "super mario"], "clue": "His brother Luigi dresses in green."},
  {"riddle": "Which blue hedgehog runs super fast and collects golden rings?", "answers": ["sonic"], "clue": "His best buddy Tails is a fox who can fly."},
  {"riddle": "In which game do crewmates do tasks while an impostor sneaks around the ship?", "answers": ["among us", "amongus"], "clue": "Emergency meetings get called when someone acts sus."},
  {"riddle": "In which classic game do you twist and drop falling blocks to clear lines?", "answers": ["tetris"], "clue": "It's a puzzle game with a very catchy theme song."},
  {"riddle": "Which round yellow hero gobbles dots while ghosts chase him through a maze?", "answers": ["pac man", "pacman"], "clue": "He famously goes 'waka waka' in arcades."},
  {"riddle": "Streamers always ask you to do this, and it rhymes with 'describe'. What is it?", "answers": ["subscribe", "subscribing", "subscription", "sub", "subs"], "clue": "Hit that button so you never miss a stream."},
  {"riddle": "What two letters do gamers type at the end of a match to show good sportsmanship?", "answers": ["gg", "ggs", "ggwp", "good game"], "clue": "Players say it to the other team after the final round."},
  {"riddle": "What three-letter word reads the same backward and forward, and chat spams it when something is hilarious?", "answers": ["lol", "lul"], "clue": "Each of its letters stands for a word about laughing."},
  {"riddle": "I hold your loot, your potions, and your pickaxe, but I'm usually just a grid of squares. What am I?", "answers": ["inventory", "backpack", "bag", "bags"], "clue": "Press I or Tab to open me in many games."},
  {"riddle": "A man walked in the rain without an umbrella or hat, but not one hair on his head got wet. How?", "answers": ["bald", "no hair"], "clue": "Look at what's on top of his head."},
  {"riddle": "I have a seat but I'm not a chair, a chain but I'm not a necklace, and two wheels to take you anywhere. What am I?", "answers": ["bicycle", "bicycles", "bike", "bikes", "cycle"], "clue": "Kids learn to ride me with training wheels."},
  {"riddle": "I come in bunches, I wear a yellow jacket, and you peel me before you eat me. What am I?", "answers": ["banana", "bananas"], "clue": "Monkeys go wild for me."},
  {"riddle": "What kind of dog has no tail, never barks, and tastes great with ketchup?", "answers": ["hot dog", "hot dogs", "hotdog", "sausage", "frankfurter"], "clue": "You'll find it in a bun at a baseball game."},
  {"riddle": "What do you call a dinosaur with a really big vocabulary?", "answers": ["thesaurus"], "clue": "It's a book full of words that mean the same thing."},
  {"riddle": "A rooster lays an egg on the very top of a barn roof. Which way does the egg roll?", "answers": ["no egg", "nowhere", "dont lay", "cant lay", "cannot lay", "do not lay", "doesnt lay", "does not lay", "never lay"], "clue": "Is a rooster a boy bird or a girl bird?"}
]
```

- [ ] **Step 2: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: 462 passed.

- [ ] **Step 3: Commit**

```bash
git add bot/content/riddles.json
git commit -m "Phase 2: riddles"
```

### Task 9: Higher or Lower terms and page views

**Files:**
- Replace: `scripts/higherlower_terms.txt`, `scripts/fetch_pageviews.py`
- Generate: `bot/content/higherlower.json`

`scripts/higherlower_terms.txt` lists about 440 well-known, family-friendly terms (display name, exact English Wikipedia title, category). `scripts/fetch_pageviews.py` resolves each title through redirects, then sums last month's user page views from the Wikimedia REST API. It sends a generic User-Agent with the repo URL (no personal email), waits 1 s between requests, and retries HTTP 429 and dropped connections with backoff. Missing and disambiguation pages are skipped; a term whose article differs from the title asked for, or with under 3,000 views, is printed for a check by hand. If more than 5% of the terms fail, the old file is left alone. The game never shows a category, so a display name says what is meant when it could be read two ways: "Venom (the movie)", "Titanic (the movie)", "FIFA (video games)", "Wednesday (TV show)", "Apple (the fruit)", "Turkey (the country)"; Star Wars and Harry Potter use the franchise articles. Two creators with recent controversies were left out.

- [ ] **Step 1: Write `scripts/higherlower_terms.txt`**

```text
# Higher or Lower term list for the Twitch chat game.
# Format: Display name|Exact English Wikipedia article title|category
# Categories: games, streamers, celebrities, food, brands, animals, countries, movies, tv, sports
# A later script fetches each title's English Wikipedia monthly page views. Do not reorder
# fields. Keep display names short (<=30 chars) and free of disambiguation text.

# --- games ---
Minecraft|Minecraft|games
Fortnite|Fortnite|games
Roblox|Roblox|games
League of Legends|League of Legends|games
Valorant|Valorant|games
Among Us|Among Us|games
Grand Theft Auto V|Grand Theft Auto V|games
Apex Legends|Apex Legends|games
Overwatch 2|Overwatch 2|games
Counter-Strike|Counter-Strike 2|games
Rainbow Six Siege|Tom Clancy's Rainbow Six Siege|games
Super Mario Bros.|Super Mario Bros.|games
The Legend of Zelda|The Legend of Zelda|games
Pokémon|Pokémon|games
Animal Crossing|Animal Crossing|games
Super Smash Bros.|Super Smash Bros.|games
Mario Kart|Mario Kart|games
Tetris|Tetris|games
Candy Crush Saga|Candy Crush Saga|games
Genshin Impact|Genshin Impact|games
World of Warcraft|World of Warcraft|games
Dota 2|Dota 2|games
Hearthstone|Hearthstone|games
Overcooked|Overcooked|games
Stardew Valley|Stardew Valley|games
Terraria|Terraria|games
Cyberpunk 2077|Cyberpunk 2077|games
Breath of the Wild|The Legend of Zelda: Breath of the Wild|games
The Witcher 3|The Witcher 3: Wild Hunt|games
Red Dead Redemption 2|Red Dead Redemption 2|games
Elden Ring|Elden Ring|games
Dark Souls|Dark Souls|games
Super Mario 64|Super Mario 64|games
Halo|Halo (franchise)|games
Halo Infinite|Halo Infinite|games
Fall Guys|Fall Guys|games
Rocket League|Rocket League|games
Battlefield|Battlefield (video game series)|games
Destiny 2|Destiny 2|games
Final Fantasy VII|Final Fantasy VII|games
Final Fantasy|Final Fantasy|games
Kingdom Hearts|Kingdom Hearts|games
Sonic the Hedgehog|Sonic the Hedgehog (franchise)|games
Pac-Man|Pac-Man|games
Donkey Kong|Donkey Kong|games
Street Fighter|Street Fighter|games
Mortal Kombat|Mortal Kombat|games
FIFA (video games)|FIFA (video game series)|games
NBA 2K|NBA 2K|games
Madden NFL|Madden NFL|games
Splatoon|Splatoon|games
Metroid|Metroid|games
Resident Evil|Resident Evil|games
Five Nights at Freddy's|Five Nights at Freddy's|games
Geometry Dash|Geometry Dash|games
Subway Surfers|Subway Surfers|games
Clash of Clans|Clash of Clans|games
Clash Royale|Clash Royale|games
Brawl Stars|Brawl Stars|games
Angry Birds|Angry Birds|games

# --- streamers ---
Kai Cenat|Kai Cenat|streamers
xQc|xQc|streamers
Pokimane|Pokimane|streamers
Technoblade|Technoblade|streamers
Shroud (streamer)|Shroud (streamer)|streamers
Sodapoppin|Sodapoppin|streamers
Asmongold|Asmongold|streamers
Tyler1|Tyler1|streamers
Ludwig Ahgren|Ludwig Ahgren|streamers
Valkyrae|Valkyrae|streamers
TimTheTatman|TimTheTatman|streamers
Moistcr1tikal|Moistcr1tikal|streamers
Northernlion|Northernlion|streamers
Ironmouse|Ironmouse|streamers
Sykkuno|Sykkuno|streamers
IShowSpeed|IShowSpeed|streamers
Quackity|Quackity|streamers
TommyInnit|TommyInnit|streamers
Summit1g|Summit1g|streamers
Forsen|Forsen|streamers
Nadeshot|Nadeshot|streamers
FaZe Rug|FaZe Rug|streamers
VanossGaming|VanossGaming|streamers
Markiplier|Markiplier|streamers
Jacksepticeye|Jacksepticeye|streamers
DanTDM|DanTDM|streamers
Jacksfilms|Jacksfilms|streamers
Corpse Husband|Corpse Husband|streamers
CaptainSparklez|CaptainSparklez|streamers
Disguised Toast|Disguised Toast|streamers
Imaqtpie|Imaqtpie|streamers
DrLupo|DrLupo|streamers
Tfue|Tfue|streamers
Jerma985|Jerma985|streamers

# --- celebrities: musicians, actors, athletes, internet personalities ---
Taylor Swift|Taylor Swift|celebrities
Drake|Drake (musician)|celebrities
Ariana Grande|Ariana Grande|celebrities
Beyoncé|Beyoncé|celebrities
Ed Sheeran|Ed Sheeran|celebrities
Billie Eilish|Billie Eilish|celebrities
The Weeknd|The Weeknd|celebrities
Rihanna|Rihanna|celebrities
Justin Bieber|Justin Bieber|celebrities
Bruno Mars|Bruno Mars|celebrities
Dua Lipa|Dua Lipa|celebrities
Olivia Rodrigo|Olivia Rodrigo|celebrities
Post Malone|Post Malone|celebrities
Kendrick Lamar|Kendrick Lamar|celebrities
Travis Scott|Travis Scott|celebrities
Doja Cat|Doja Cat|celebrities
Lady Gaga|Lady Gaga|celebrities
Adele|Adele|celebrities
Harry Styles|Harry Styles|celebrities
BTS|BTS|celebrities
Tom Hanks|Tom Hanks|celebrities
Leonardo DiCaprio|Leonardo DiCaprio|celebrities
Dwayne Johnson|Dwayne Johnson|celebrities
Will Smith|Will Smith|celebrities
Zendaya|Zendaya|celebrities
Tom Holland|Tom Holland|celebrities
Robert Downey Jr.|Robert Downey Jr.|celebrities
Scarlett Johansson|Scarlett Johansson|celebrities
Chris Hemsworth|Chris Hemsworth|celebrities
Ryan Reynolds|Ryan Reynolds|celebrities
Keanu Reeves|Keanu Reeves|celebrities
Margot Robbie|Margot Robbie|celebrities
Emma Watson|Emma Watson|celebrities
Jennifer Lawrence|Jennifer Lawrence|celebrities
Tom Cruise|Tom Cruise|celebrities
LeBron James|LeBron James|celebrities
Cristiano Ronaldo|Cristiano Ronaldo|celebrities
Lionel Messi|Lionel Messi|celebrities
Serena Williams|Serena Williams|celebrities
Stephen Curry|Stephen Curry|celebrities
Kevin Durant|Kevin Durant|celebrities
Tom Brady|Tom Brady|celebrities
Simone Biles|Simone Biles|celebrities
Usain Bolt|Usain Bolt|celebrities
Michael Jordan|Michael Jordan|celebrities
Shohei Ohtani|Shohei Ohtani|celebrities
Patrick Mahomes|Patrick Mahomes|celebrities
Novak Djokovic|Novak Djokovic|celebrities
Rafael Nadal|Rafael Nadal|celebrities
Caitlin Clark|Caitlin Clark|celebrities
MrBeast|MrBeast|celebrities
PewDiePie|PewDiePie|celebrities
KSI|KSI|celebrities
Emma Chamberlain|Emma Chamberlain|celebrities
iJustine|iJustine|celebrities
Charli D'Amelio|Charli D'Amelio|celebrities
Khaby Lame|Khaby Lame|celebrities
Addison Rae|Addison Rae|celebrities
Zach King|Zach King|celebrities
Liza Koshy|Liza Koshy|celebrities

# --- food ---
Pizza|Pizza|food
Sushi|Sushi|food
Hamburger|Hamburger|food
Hot Dog|Hot dog|food
Taco|Taco|food
Burrito|Burrito|food
Ramen|Ramen|food
Pasta|Pasta|food
Spaghetti|Spaghetti|food
Pancake|Pancake|food
Waffle|Waffle|food
Ice Cream|Ice cream|food
Chocolate|Chocolate|food
Cake|Cake|food
Cookie|Cookie|food
Doughnut|Doughnut|food
Bagel|Bagel|food
Sandwich|Sandwich|food
French Fries|French fries|food
Fried Chicken|Fried chicken|food
Popcorn|Popcorn|food
Nachos|Nachos|food
Guacamole|Guacamole|food
Pretzel|Pretzel|food
Churro|Churro|food
Dumpling|Dumpling|food
Curry|Curry|food
Pho|Pho|food
Pad Thai|Pad thai|food
Lasagne|Lasagne|food
Falafel|Falafel|food
Hummus|Hummus|food
Kebab|Kebab|food
Croissant|Croissant|food
Cheesecake|Cheesecake|food
Brownie|Chocolate brownie|food
Muffin|Muffin|food
Oatmeal|Oatmeal|food
Egg|Egg as food|food
Bacon|Bacon|food
Cheese|Cheese|food
Honey|Honey|food
Avocado|Avocado|food
Mango|Mango|food
Watermelon|Watermelon|food
Strawberry|Strawberry|food
Banana|Banana|food
Apple (the fruit)|Apple|food
Pineapple|Pineapple|food
Peanut Butter|Peanut butter|food

# --- brands ---
YouTube|YouTube|brands
Google|Google|brands
Amazon (the company)|Amazon (company)|brands
Netflix|Netflix|brands
Disney|The Walt Disney Company|brands
Nike|Nike, Inc.|brands
Adidas|Adidas|brands
Coca-Cola|Coca-Cola|brands
Pepsi|Pepsi|brands
McDonald's|McDonald's|brands
Starbucks|Starbucks|brands
Walmart|Walmart|brands
Target|Target Corporation|brands
Lego|Lego|brands
Nintendo|Nintendo|brands
Sony|Sony|brands
Microsoft|Microsoft|brands
Apple Inc.|Apple Inc.|brands
Samsung|Samsung Electronics|brands
Tesla|Tesla, Inc.|brands
SpaceX|SpaceX|brands
Instagram|Instagram|brands
TikTok|TikTok|brands
Snapchat|Snapchat|brands
Facebook|Facebook|brands
Twitter|X (social network)|brands
Discord|Discord|brands
Spotify|Spotify|brands
Twitch|Twitch (service)|brands
Red Bull|Red Bull|brands
Oreo|Oreo|brands
Doritos|Doritos|brands
Lay's|Lay's|brands
Pringles|Pringles|brands
Hershey's|The Hershey Company|brands
M&M's|M&M's|brands
Skittles|Skittles (confectionery)|brands
Reese's|Reese's Peanut Butter Cups|brands
Kit Kat|Kit Kat|brands
Gatorade|Gatorade|brands
Monster Energy|Monster Energy|brands
Chick-fil-A|Chick-fil-A|brands
Subway (restaurant)|Subway (restaurant)|brands
Domino's Pizza|Domino's Pizza|brands
Pizza Hut|Pizza Hut|brands
Burger King|Burger King|brands
KFC|KFC|brands
Taco Bell|Taco Bell|brands
Wendy's|Wendy's|brands
Dunkin'|Dunkin'|brands

# --- animals ---
Dog|Dog|animals
Cat|Cat|animals
Lion|Lion|animals
Tiger|Tiger|animals
Elephant|Elephant|animals
Giraffe|Giraffe|animals
Zebra|Zebra|animals
Gorilla|Gorilla|animals
Chimpanzee|Chimpanzee|animals
Panda|Giant panda|animals
Koala|Koala|animals
Kangaroo|Kangaroo|animals
Platypus|Platypus|animals
Axolotl|Axolotl|animals
Capybara|Capybara|animals
Sloth|Sloth|animals
Red Panda|Red panda|animals
Penguin|Penguin|animals
Polar Bear|Polar bear|animals
Brown Bear|Brown bear|animals
Wolf|Wolf|animals
Fox|Fox|animals
Rabbit|Rabbit|animals
Squirrel|Squirrel|animals
Hedgehog|Hedgehog|animals
Raccoon|Raccoon|animals
Otter|Otter|animals
Beaver|Beaver|animals
Deer|Deer|animals
Moose|Moose|animals
Bison|Bison|animals
Horse|Horse|animals
Cow|Cattle|animals
Pig|Pig|animals
Sheep|Sheep|animals
Goat|Goat|animals
Chicken|Chicken|animals
Duck|Duck|animals
Owl|Owl|animals
Eagle|Eagle|animals
Parrot|Parrot|animals
Flamingo|Flamingo|animals
Peacock|Peacock|animals
Shark|Shark|animals
Dolphin|Dolphin|animals
Octopus|Octopus|animals
Jellyfish|Jellyfish|animals
Crab|Crab|animals
Turtle|Turtle|animals
Snake|Snake|animals

# --- countries ---
United States|United States|countries
Canada|Canada|countries
Mexico|Mexico|countries
Brazil|Brazil|countries
United Kingdom|United Kingdom|countries
France|France|countries
Germany|Germany|countries
Italy|Italy|countries
Spain|Spain|countries
Russia|Russia|countries
China|China|countries
Japan|Japan|countries
South Korea|South Korea|countries
India|India|countries
Australia|Australia|countries
Egypt|Egypt|countries
South Africa|South Africa|countries
Nigeria|Nigeria|countries
Kenya|Kenya|countries
Saudi Arabia|Saudi Arabia|countries
Turkey (the country)|Turkey|countries
Greece|Greece|countries
Netherlands|Netherlands|countries
Sweden|Sweden|countries
Norway|Norway|countries
Switzerland|Switzerland|countries
Portugal|Portugal|countries
Ireland|Ireland|countries
Iceland|Iceland|countries
New Zealand|New Zealand|countries
Argentina|Argentina|countries
Chile|Chile|countries
Colombia|Colombia|countries
Peru|Peru|countries
Thailand|Thailand|countries
Vietnam|Vietnam|countries
Philippines|Philippines|countries
Indonesia|Indonesia|countries
Jamaica|Jamaica|countries
Cuba|Cuba|countries

# --- movies ---
Titanic (the movie)|Titanic (1997 film)|movies
The Avengers|The Avengers (2012 film)|movies
Avengers: Endgame|Avengers: Endgame|movies
Spider-Man: No Way Home|Spider-Man: No Way Home|movies
Star Wars|Star Wars|movies
The Lion King|The Lion King (1994 film)|movies
Frozen|Frozen (2013 film)|movies
Shrek|Shrek|movies
The Dark Knight|The Dark Knight|movies
Jurassic Park|Jurassic Park (film)|movies
Harry Potter|Harry Potter|movies
Toy Story|Toy Story|movies
Finding Nemo|Finding Nemo|movies
The Matrix|The Matrix|movies
Inception|Inception|movies
Deadpool (the movie)|Deadpool (film)|movies
Barbie (the movie)|Barbie (film)|movies
Oppenheimer|Oppenheimer (film)|movies
Minions|Minions (film)|movies
Despicable Me|Despicable Me|movies
Encanto|Encanto|movies
Moana|Moana (2016 film)|movies
Coco|Coco (2017 film)|movies
Up (the movie)|Up (2009 film)|movies
The Incredibles|The Incredibles|movies
Cars (the movie)|Cars (film)|movies
Ratatouille (the movie)|Ratatouille (film)|movies
WALL-E|WALL-E|movies
Inside Out|Inside Out (2015 film)|movies
Guardians of the Galaxy|Guardians of the Galaxy (film)|movies
Black Panther (the movie)|Black Panther (film)|movies
Iron Man (the movie)|Iron Man (2008 film)|movies
Joker (the movie)|Joker (2019 film)|movies
It (the movie)|It (2017 film)|movies
Venom (the movie)|Venom (2018 film)|movies
The Super Mario Bros. Movie|The Super Mario Bros. Movie|movies
Jaws|Jaws (film)|movies
E.T. the Extra-Terrestrial|E.T. the Extra-Terrestrial|movies
Home Alone|Home Alone|movies
Night at the Museum|Night at the Museum|movies

# --- tv ---
The Office|The Office (American TV series)|tv
Friends|Friends|tv
Breaking Bad|Breaking Bad|tv
Stranger Things|Stranger Things|tv
Game of Thrones|Game of Thrones|tv
The Simpsons|The Simpsons|tv
SpongeBob SquarePants|SpongeBob SquarePants|tv
Naruto|Naruto|tv
One Piece|One Piece|tv
Attack on Titan|Attack on Titan|tv
Dragon Ball Z|Dragon Ball Z|tv
My Hero Academia|My Hero Academia|tv
Demon Slayer|Demon Slayer: Kimetsu no Yaiba|tv
Death Note|Death Note|tv
Avatar: The Last Airbender|Avatar: The Last Airbender|tv
Rick and Morty|Rick and Morty|tv
South Park|South Park|tv
Family Guy|Family Guy|tv
The Big Bang Theory|The Big Bang Theory|tv
How I Met Your Mother|How I Met Your Mother|tv
Brooklyn Nine-Nine|Brooklyn Nine-Nine|tv
Grey's Anatomy|Grey's Anatomy|tv
The Mandalorian|The Mandalorian|tv
Wednesday (TV show)|Wednesday (TV series)|tv
Squid Game|Squid Game|tv
The Boys|The Boys (TV series)|tv
Doctor Who|Doctor Who|tv
The Walking Dead|The Walking Dead (TV series)|tv
Cobra Kai|Cobra Kai|tv
Suits|Suits (American TV series)|tv

# --- sports ---
Basketball|Basketball|sports
Soccer|Association football|sports
American Football|American football|sports
Baseball|Baseball|sports
Tennis|Tennis|sports
Golf|Golf|sports
Boxing|Boxing|sports
Volleyball|Volleyball|sports
Ice Hockey|Ice hockey|sports
Cricket (the sport)|Cricket|sports
Rugby|Rugby union|sports
Table Tennis|Table tennis|sports
Badminton|Badminton|sports
Skateboarding|Skateboarding|sports
Gymnastics|Gymnastics|sports
Olympic Games|Olympic Games|sports
FIFA World Cup|FIFA World Cup|sports
Super Bowl|Super Bowl|sports
Formula One|Formula One|sports
```

- [ ] **Step 2: Write `scripts/fetch_pageviews.py`**

```python
"""Build bot/content/higherlower.json: each term's English Wikipedia page views for the last full month.

Run from the repo root: .venv/bin/python scripts/fetch_pageviews.py
Terms come from scripts/higherlower_terms.txt (display name|article title|category). Titles are
resolved through redirects first, since page views are counted per exact title. Re-run it any
time to refresh the numbers.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bot  # noqa: E402, F401  (points Python at certifi's certificates when the system has none)

TERMS = ROOT / "scripts" / "higherlower_terms.txt"
OUT = ROOT / "bot" / "content" / "higherlower.json"
USER_AGENT = "offline-chat-bot/0.1 (https://github.com/rrong12/offline-chat-bot)"
ACTION_API = "https://en.wikipedia.org/w/api.php"
VIEWS_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user"
REVIEW_BELOW = 3000  # monthly views this low usually mean the wrong article
MAX_FAILURES = 0.05  # if more terms than this fail, keep the old file rather than lose them


def get(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 5:
                raise
            retry_after = exc.headers.get("Retry-After") or ""
            wait = int(retry_after) if retry_after.isdigit() else 5 * 2**attempt  # rate limited: back off
            time.sleep(min(wait, 120))
        except (urllib.error.URLError, TimeoutError):  # dropped connection: try again
            if attempt == 5:
                raise
            time.sleep(5 * 2**attempt)
    raise AssertionError("unreachable")


def last_full_month(today: date) -> tuple[date, date]:
    end = today.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def resolve(titles: list[str]) -> dict[str, str | None]:
    """Title -> canonical title after normalization and redirects, or None if the page doesn't exist."""
    result: dict[str, str | None] = {}
    for i in range(0, len(titles), 50):
        batch = titles[i : i + 50]
        query = urllib.parse.urlencode({
            "action": "query", "format": "json", "redirects": 1, "titles": "|".join(batch),
            "prop": "pageprops", "ppprop": "disambiguation",  # a disambiguation page is the wrong article
        })
        data = get(f"{ACTION_API}?{query}")["query"]
        step = {n["from"]: n["to"] for n in data.get("normalized", [])}
        step.update({r["from"]: r["to"] for r in data.get("redirects", [])})
        missing = {
            p["title"] for p in data["pages"].values()
            if "missing" in p or "invalid" in p or "disambiguation" in p.get("pageprops", {})
        }
        for title in batch:
            current = title
            for _ in range(3):  # normalized, then redirected
                current = step.get(current, current)
            result[title] = None if current in missing else current
        time.sleep(0.5)
    return result


def monthly_views(title: str, start: date, end: date) -> int:
    article = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = f"{VIEWS_API}/{article}/monthly/{start:%Y%m%d}00/{end:%Y%m%d}00"
    return sum(item["views"] for item in get(url)["items"])


def main() -> None:
    rows = []
    for line in TERMS.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, title, category = (part.strip() for part in line.split("|"))
            rows.append((name, title, category))
    start, end = last_full_month(date.today())
    canonical = resolve([title for _, title, _ in rows])
    terms, problems = [], []
    for name, title, category in rows:
        real = canonical.get(title)
        if real is None:
            problems.append(f"missing or disambiguation page: {title}")
            continue
        try:
            views = monthly_views(real, start, end)
        except urllib.error.HTTPError as exc:
            problems.append(f"no views ({exc.code}): {real}")
            continue
        terms.append({"name": name, "article": real, "category": category, "views": views})
        if real != title or views < REVIEW_BELOW:
            problems.append(f"check by hand: {name} -> {real} ({views} views)")
        time.sleep(1.0)  # stay well under Wikimedia's rate limit
    for problem in problems:
        print("  " + problem)
    if len(terms) < (1 - MAX_FAILURES) * len(rows):  # don't overwrite good data with a failed run
        sys.exit(f"only {len(terms)} of {len(rows)} terms found; {OUT} left unchanged")
    payload = {
        "source": "English Wikipedia page views (Wikimedia REST API), user agents only",
        "month": f"{start:%Y-%m}",
        "terms": terms,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"wrote {len(terms)} terms for {start:%Y-%m} to {OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Generate `bot/content/higherlower.json`**

Run: `.venv/bin/python scripts/fetch_pageviews.py`
Expected: it takes a few minutes; it prints `wrote N terms for <month>` and any missing pages.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: 462 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/higherlower_terms.txt scripts/fetch_pageviews.py bot/content/higherlower.json
git commit -m "Phase 2: Higher or Lower terms and page views"
```

### Task 10: Content tests

**Files:**
- Replace: `tests/test_content.py`

Rules for the new content, run against the real files:

- **Trivia:** 1,000+ questions, unique ids, exactly the 11 categories with 30+ questions each, easy questions with three wrong options that differ from each other and pass the script's `clear_options`, typed answers that pass the script's `typeable` and have accepted forms, every question message at most 480 characters, no blocked words, and the credits file.
- **Riddles:** 150+, no duplicates, riddle at most 300 characters, answers lowercase with 1-3 words and not starting with an article (guesses lose theirs), no blocked words, and no clue word equal to an answer word or sharing its first 4 letters with one.
- **Higher or Lower:** 300+ terms, unique names of at most 30 characters, positive integer views, no blocked words, and every term has at least 50 possible partners.
- **Games:** no game has a category with the same name as one of its levels.

- [ ] **Step 1: Write `tests/test_content.py`**

```python
"""Rules for the bundled content files. These run against the real bot/content folder."""

import re

import pytest

from bot.assets import Assets
from bot.fun import BlockedWords
from bot.games.hangman import _valid as hangman_valid
from bot.games.scramble import _valid as scramble_valid

CATEGORIES = ["animals", "countries", "food", "games", "general", "streamers"]
REAL = Assets()


def test_categories_are_exactly_the_approved_six():
    assert REAL.categories() == CATEGORIES


@pytest.mark.parametrize("category", CATEGORIES)
def test_word_lists(category):
    words = REAL.words(category)
    assert len(words) >= 100, f"{category}: need at least 100 entries, have {len(words)}"
    lowered = [w.lower() for w in words]
    dupes = sorted({w for w in lowered if lowered.count(w) > 1})
    assert not dupes, f"{category}: duplicates {dupes}"
    bad = [w for w in words if not hangman_valid(w)]
    assert not bad, f"{category}: entries Hangman can't use (letters, spaces, - and ' only; 3+ letters): {bad}"
    scramble = [w for w in words if scramble_valid(w)]
    assert len(scramble) >= 40, f"{category}: need 40+ single words of 4-10 letters for Scramble, have {len(scramble)}"


@pytest.mark.parametrize("category", ["games", "streamers"])
def test_every_game_and_streamer_has_a_recorded_source(category):
    sources = (REAL.root / "words" / "SOURCES.md").read_text(encoding="utf-8").lower()
    missing = [w for w in REAL.words(category) if f"| {w.lower()} |" not in sources]
    assert not missing, f"{category}: no source row in words/SOURCES.md for {missing}"


def test_blocked_fragment_list_exists():
    import codecs

    fragments = [codecs.decode(line, "rot13") for line in REAL.lines("blocked_rot13")]
    assert len(fragments) >= 20
    assert all(f.isalpha() and f == f.lower() for f in fragments)


def _prose_patterns():
    import codecs

    return [codecs.decode(line, "rot13") for line in REAL.lines("blocked_prose_rot13")]


def test_prose_blocked_list_format():
    patterns = _prose_patterns()
    assert len(patterns) >= 50
    for p in patterns:
        assert re.fullmatch(r"\*?[a-z]+\*?", p) and (p.startswith("*") <= p.endswith("*")), p


def test_prose_blocked_list_catches_every_pattern_in_its_forms():
    # Built from the encoded list, so no blocked word is spelled out in this file.
    blocked = BlockedWords.load(REAL)
    for p in _prose_patterns():
        core = p.strip("*")
        if p.startswith("*"):
            forms = [core, "x" + core + "y", core.capitalize() + "ed"]
        elif p.endswith("*"):
            forms = [core, core + "ed", core.upper() + "S"]
        else:
            forms = [core, core + "s", core.capitalize()]
        for form in forms:
            assert blocked.found_in(f"They said {form} once."), p


def test_prose_blocked_list_allows_common_words():
    blocked = BlockedWords.load(REAL)
    for fine in (
        "The night sky over Japan is beautiful.", "Japanese analysts studied spices from Pakistan.",
        "Mustard is a condiment.", "Charles Dickens and Emily Dickinson wrote a lot.",
        "Homo sapiens evolved in Africa.",
        "Homo erectus used fire.", "Homologous structures share an origin.", "The title of the book.",
        "Cumulative rainfall rose.", "A cocktail party in Cockney London.", "Tardigrades survive space.",
        "Maine Coon cats are large.", "The Main Coon cat.", "Puss in Boots is a cat.",
        "Males are bigger than the opposite sex.",
        "Felis nigripes is the black-footed cat.", "The shitzu is a toy breed.", "The siege lasted a year.",
        "Blue-footed boobies dance.", "Spica is a bright star.", "Milford Sound is in New Zealand.",
        "The Wankel engine is a rotary engine.", "Cats reach sexual maturity early.", "A cocky rooster crowed.",
        "Scunthorpe is a town.", "Grapes, drapes and scrapes.", "Cockatoos and cockroaches.",
    ):
        assert not blocked.found_in(fine), fine


def test_8ball_has_20_answers():
    assert len(REAL.lines("8ball")) == 20


@pytest.mark.parametrize("name, minimum", [
    ("fortunes", 50), ("fallback_catfacts", 50), ("fallback_dogfacts", 50),
    ("fallback_facts", 50), ("fallback_dadjokes", 50),
])
def test_text_lists(name, minimum):
    lines = REAL.lines(name)
    assert len(lines) >= minimum
    assert len(set(lines)) == len(lines), f"{name} has duplicate lines"
    too_long = [line for line in lines if len(line) > 400]
    assert not too_long, f"{name}: lines over 400 characters: {too_long}"
    assert all(not re.search(r"https?://", line) for line in lines), f"{name}: no links in chat content"


# Phase 2 content: trivia (Open Trivia DB), riddles (written for the bot), Higher or Lower (Wikipedia views).
TRIVIA_CATEGORIES = ["anime", "animals", "games", "general", "geography", "history", "movies", "music",
                     "science", "sports", "tv"]


def test_trivia_bank():
    import importlib.util

    from bot.games.trivia import Trivia, accepted_answers, opening

    script = REAL.root.parent.parent / "scripts" / "fetch_trivia.py"
    spec = importlib.util.spec_from_file_location("fetch_trivia", script)
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)
    clear_options, typeable = fetch.clear_options, fetch.typeable

    questions = REAL.json("trivia")["questions"]
    assert len(questions) >= 1000
    assert len({q["id"] for q in questions}) == len(questions)
    assert Trivia.category_names(REAL) == sorted(TRIVIA_CATEGORIES)
    blocked = BlockedWords.load(REAL)
    assert all(fetch.keep(q, blocked) for q in questions)  # every filter in the script, incl. mature topics
    for category in TRIVIA_CATEGORIES:
        assert sum(q["category"] == category for q in questions) >= 30, category
    for q in questions:
        assert q["difficulty"] in ("easy", "medium", "hard"), q["id"]
        texts = [q["question"], q["answer"], *q.get("wrong", [])]
        assert not any(blocked.found_in(t) for t in texts), q["id"]
        if q["difficulty"] == "easy":
            options = [q["answer"], *q["wrong"]]
            assert len(q["wrong"]) == 3 and len({o.lower() for o in options}) == 4, q["id"]
            assert clear_options(options), q["id"]  # options don't read alike, and none is a lone letter
        else:
            assert typeable(q["question"], q["answer"], q["id"]), q["id"]  # short, typeable, no C++ or 13.8
            assert accepted_answers(q["answer"]), q["id"]
            options = []
        assert len(opening(q["category"], q["difficulty"], q["question"], options, 30)) <= 480, q["id"]


def test_trivia_is_credited():
    credits = (REAL.root / "TRIVIA_CREDITS.md").read_text(encoding="utf-8")
    assert "Open Trivia DB" in credits and "CC BY-SA 4.0" in credits


def _stems(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def test_riddles():
    riddles = REAL.json("riddles")
    assert len(riddles) >= 150
    texts = [r["riddle"] for r in riddles]
    assert len(set(texts)) == len(texts)
    blocked = BlockedWords.load(REAL)
    for r in riddles:
        assert len(r["riddle"]) <= 300 and r["clue"], r["riddle"]
        assert r["answers"] and all(re.fullmatch(r"[a-z0-9]+( [a-z0-9]+){0,2}", a) for a in r["answers"]), r["riddle"]
        # guesses lose a leading article before matching, so an answer must not start with one
        assert not any(re.match(r"(a|an|the) ", a) for a in r["answers"]), r["riddle"]
        clue_words = _stems(r["clue"])
        answer_words = {w for a in r["answers"] for w in a.split()}
        for cw in clue_words:
            for aw in answer_words:
                assert cw != aw, (r["riddle"], aw)
                if len(cw) >= 4 and len(aw) >= 4:
                    assert cw[:4] != aw[:4], (r["riddle"], aw)  # the clue mustn't give the answer away
        assert not any(blocked.found_in(t) for t in (r["riddle"], r["clue"], *r["answers"])), r["riddle"]


def test_higherlower_terms():
    from bot.games.higherlower import MIN_RATIO

    terms = REAL.json("higherlower")["terms"]
    assert len(terms) >= 300
    names = [t["name"] for t in terms]
    assert len(set(names)) == len(names)
    blocked = BlockedWords.load(REAL)
    for t in terms:
        assert isinstance(t["views"], int) and t["views"] > 0, t["name"]
        assert len(t["name"]) <= 30 and not blocked.found_in(t["name"]), t["name"]
        partners = sum(max(o["views"], t["views"]) >= MIN_RATIO * min(o["views"], t["views"]) for o in terms)
        assert partners >= 50, t["name"]


def test_no_game_has_a_category_named_like_a_level():
    from bot.games import ALL_GAMES

    for cls in ALL_GAMES.values():  # "?trivia easy" must mean the difficulty, unambiguously
        assert not set(cls.category_names(REAL)) & set(cls.levels), cls.name
```

- [ ] **Step 2: Run the tests**

Run: `.venv/bin/pytest tests/test_content.py -q`, then `.venv/bin/pytest -q`.
Expected: `24 passed`, then the whole suite passes (467 passed).

- [ ] **Step 3: Commit**

```bash
git add tests/test_content.py
git commit -m "Phase 2: content tests for trivia, riddles and Higher or Lower"
```

## Execution log

Built from a tested prototype on 2026-10-05: implementer subagents applied each task from this plan
(code extracted verbatim), then a spec-compliance review and a code-quality review checked each one.
Content (trivia download, riddles, page views) was generated while prototyping and copied in.

- **Tasks 1-10** were committed as 6b47f0b, 30f0a52, 1c7e383, 9a669e9, fe0f9d4, a91737a, 533b836,
  38cf96f, b5cfbab and 1a7d28e. Every task's tests failed first and then passed with the plan's counts.
- **Review fixes, round 1:**
  - 57ffefe: answer matching keeps numbers exact, strips only real articles, folds accents.
  - 70cd470: refusal notices keyed by game, so an alias can't get around them.
  - 3003a72: a test that close view counts are never paired.
- **Review fixes, round 2 (cff37d1):**
  - Framework: games without options ignore extra words; the repeat history is ordered, so small
    pools never repeat back to back; a broken time limit ends only its game; the memory bound is tested.
  - Trivia: natural answer variants, digit-group and first-letter rules for typos, no-giveaway hints,
    and credits in `?help`.
  - Trivia content: mature topics, symbol answers, dates, option-dependent questions and wrong ids
    removed (3,199 to 2,985 questions).
  - Riddle: filler-aware word limit, spacing, plurals, negation, numbers and letter hedges.
  - Higher or Lower: film articles corrected, and `?leaderboard hl` works.
- **Review fixes, round 3 (885c5a4):**
  - Riddle: either-or hedges, number and letter edge cases.
  - Trivia: a stricter comma rule, titles, surname particles, WW2 and number words; 15 more questions
    excluded and 10 good ones restored (2,979).
  - Higher or Lower: display names say what they mean, and up/down are accepted.
- **Riddle content:** 216 written by one agent; an independent checker fixed 30 and removed 2. Later
  reviews removed alternatives that let wrong guesses win.
- **Final review (whole branch):** the code review found it ready to merge; its minor items were
  fixed:
  - ASCII-only digits; "is it a letter m"; the surname shortcut needs a plain surname;
  - easy questions say once that they have no hints; a broken content file gets a reply;
  - README gaps; test helpers that could read stale cached content.
- **Final content check:** about 150 more trivia questions excluded: real tragedies, drug, alcohol and
  crude titles, graphic horror, wrong or outdated facts, misspellings, option-dependent questions, and
  answers nobody types. 2,826 remain. Matching now also accepts question words left out, initials,
  epithets, pairs in either order, plurals and words before the answer. Riddles gained a few answers.
  Higher or Lower dropped two creators and clarified ambiguous names.
