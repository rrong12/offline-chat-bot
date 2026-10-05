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
    from bot.games.trivia import Trivia, opening

    questions = REAL.json("trivia")["questions"]
    assert len(questions) >= 1000
    assert len({q["id"] for q in questions}) == len(questions)
    assert Trivia.category_names(REAL) == sorted(TRIVIA_CATEGORIES)
    blocked = BlockedWords.load(REAL)
    for category in TRIVIA_CATEGORIES:
        assert sum(q["category"] == category for q in questions) >= 30, category
    for q in questions:
        assert q["difficulty"] in ("easy", "medium", "hard"), q["id"]
        texts = [q["question"], q["answer"], *q.get("wrong", [])]
        assert not any(blocked.found_in(t) for t in texts), q["id"]
        if q["difficulty"] == "easy":
            assert len(q["wrong"]) == 3 and q["answer"] not in q["wrong"], q["id"]
            options = [q["answer"], *q["wrong"]]
        else:
            assert len(q["answer"].split()) <= 3 and len(q["answer"]) <= 25, q["id"]
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
