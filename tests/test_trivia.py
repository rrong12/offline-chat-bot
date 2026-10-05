import random

import pytest

from bot.games.trivia import Trivia
from tests.helpers import make_msg


def make(assets, category="science", level=None, seed=1, avoid=frozenset()) -> Trivia:
    return Trivia(category, random.Random(seed), assets, level=level, avoid=avoid)


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
    assert not game.on_command("hint", "", make_msg("?hint"), None)  # no hints on easy


def test_typed_start_and_right_answer(assets):
    game = make(assets, level="medium")
    assert game.start() == "❓ (science, medium) Which planet is the largest? · 30s · {p}g <answer> · {p}hint"
    out = g(game, "Jupiter!")
    assert out.result == "won" and out.awards == {"id-alice": 10}


def test_typed_forgives_one_typo_on_long_answers(assets):
    assert g(make(assets, level="medium"), "jupitor").result == "won"
    assert g(make(assets, level="medium"), "jpuitor").result is None  # two edits: a wrong guess


def test_numbers_must_be_exact(assets):
    game = make(assets, category="history", level="hard", avoid=frozenset({"h2"}))
    assert game.answer == "1945"
    assert g(game, "1946").messages == ["❌ Not it, 2 guesses left."]
    assert g(game, "1945").awards == {"id-alice": 15}


def test_articles_spaces_and_punctuation_are_ignored(assets):
    game = make(assets, category="history", level="hard", avoid=frozenset({"h1"}))
    assert game.answer == "Leonardo da Vinci"
    assert g(game, "leonardo davinci").result == "won"


def test_three_wrong_guesses_lose(assets):
    game = make(assets, level="medium")
    assert g(game, "mars").messages == ["❌ Not it, 2 guesses left."]
    assert g(game, "venus").messages == ["❌ Not it, 1 guess left."]
    out = g(game, "pluto")
    assert out.finished and out.result == "lost" and out.messages == ["💀 Out of guesses! It was Jupiter."]


def test_hints_lower_the_points(assets):
    game = make(assets, category="history", level="hard", avoid=frozenset({"h1"}))
    hint = lambda: game.on_command("hint", "", make_msg("?hint"), None)  # noqa: E731
    assert hint().messages == ["💡 3 words, 15 letters, starts with L"]
    second = hint().messages[0]
    assert second.startswith("💡 L ") and second.endswith(" I") and " / " in second
    assert hint() is None  # at most two
    assert g(game, "leonardo da vinci").awards == {"id-alice": 6}


def test_level_is_random_when_not_given_and_falls_back_when_missing(assets):
    assert make(assets, category="history").level == "hard"  # history only has hard questions
    assert make(assets, category="history", level="easy").level == "hard"


def test_avoid_skips_recent_questions(assets):
    assert make(assets, category="history", level="hard", avoid=frozenset({"h1"})).item_id == "h2"
    both = frozenset({"h1", "h2"})
    assert make(assets, category="history", level="hard", avoid=both).item_id in {"h1", "h2"}


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

    from bot.assets import Assets

    root = tmp_path / "content"
    root.mkdir(exist_ok=True)
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
