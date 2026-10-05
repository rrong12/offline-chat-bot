"""Rules for the bundled content files. These run against the real bot/content folder."""

import re

import pytest

from bot.assets import Assets
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
