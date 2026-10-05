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

    from bot.assets import Assets

    root = tmp_path / "content"
    root.mkdir(exist_ok=True)
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
