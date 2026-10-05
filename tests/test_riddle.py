import random

from bot.games.riddle import Riddle, riddle_id
from tests.helpers import make_msg


def make(assets, seed=1, avoid=frozenset()) -> Riddle:
    game = Riddle(None, random.Random(seed), assets, avoid=avoid)
    if game.answers[0] != "clock":  # the tests below use the clock riddle
        clock_id = next(riddle_id(r) for r in assets.json("riddles") if r["answers"][0] == "clock")
        others = frozenset(riddle_id(r) for r in assets.json("riddles")) - {clock_id}
        game = Riddle(None, random.Random(seed), assets, avoid=others)
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


def test_avoid_skips_recent_riddles(assets):
    clock_id = riddle_id({"riddle": "What has hands but can't clap?"})
    assert Riddle(None, random.Random(1), assets, avoid=frozenset({clock_id})).answers == ["towel"]


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
