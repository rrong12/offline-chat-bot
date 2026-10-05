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
