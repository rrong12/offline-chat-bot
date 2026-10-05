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
