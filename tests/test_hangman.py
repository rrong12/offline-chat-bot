import random
from datetime import datetime, timedelta, timezone

from bot.games.hangman import Hangman
from tests.helpers import make_msg

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def make(assets, answer: str = "sea lion") -> Hangman:
    game = Hangman("animals", random.Random(1), assets)
    game.answer = answer.upper()  # pin the answer so tests are readable
    return game


def g(game: Hangman, args: str, login: str = "alice", at: float = 0):
    return game.on_command("g", args, make_msg(f"?g {args}", login), T0 + timedelta(seconds=at))


def test_categories_include_phrases(assets):
    assert Hangman.category_names(assets) == ["animals", "food"]


def test_start_shows_blank_board_with_word_gap(assets):
    game = make(assets)
    assert game.board() == "_ _ _ / _ _ _ _"
    assert game.start() == (
        "🪢 Hangman (animals): _ _ _ / _ _ _ _ · guess with {p}g <letter> or {p}g <answer> · 6 lives, 120s"
    )


def test_plain_chat_is_ignored(assets):
    game = make(assets)
    assert game.on_message(make_msg("W"), T0) is None
    assert game.on_message(make_msg("sea lion"), T0) is None


def test_correct_letter_reveals_and_holds_a_point(assets):
    game = make(assets)
    out = g(game, "a")
    assert out.messages == ["_ _ A / _ _ _ _ | wrong: - (0/6)"]
    assert out.coalesce_key == "hangman-board"
    assert game.held == {"id-alice": 1}


def test_wrong_letter_costs_a_life(assets):
    game = make(assets)
    out = g(game, "z")
    assert out.messages == ["_ _ _ / _ _ _ _ | wrong: Z (1/6)"]


def test_repeated_letter_is_ignored(assets):
    game = make(assets)
    g(game, "a", "alice")
    assert g(game, "A", "bob") is None


def test_non_letter_single_character_is_ignored(assets):
    assert g(make(assets), "7") is None


def test_guess_cooldown(assets):
    game = make(assets)
    assert g(game, "a", at=0) is not None
    assert g(game, "e", at=1) is None
    assert g(game, "e", at=2) is not None


def test_wrong_solve_attempt_is_free_attempt(assets):
    game = make(assets)
    out = g(game, "walrus")
    assert out is not None and not out.finished and out.messages == []
    assert game.wrong == []


def test_full_solve_wins_with_held_points(assets):
    game = make(assets)
    g(game, "a", "alice")
    out = g(game, "Sea-Lion", "bob")
    assert out.finished and out.result == "won"
    assert out.awards == {"id-alice": 1, "id-bob": 10}
    assert out.winners == {"id-bob"}
    assert out.messages == ["🎉 bob solved it: SEA LION (+10)"]


def test_solve_ignores_spaces(assets):
    out = g(make(assets), "sealion")
    assert out.result == "won"


def test_revealing_last_letter_wins(assets):
    game = make(assets, "cat")
    g(game, "c", "a1")
    g(game, "a", "a2")
    out = g(game, "t", "a3")
    assert out.result == "won"
    assert out.awards == {"id-a1": 1, "id-a2": 1, "id-a3": 11}


def test_six_wrong_letters_loses_and_awards_nothing(assets):
    game = make(assets)
    g(game, "a", "helper")
    outs = [g(game, letter, f"u{i}") for i, letter in enumerate("bdfghj")]
    last = outs[-1]
    assert last.finished and last.result == "lost"
    assert last.awards == {}
    assert last.messages == ["💀 Out of lives! The word was SEA LION."]


def test_timeout(assets):
    out = make(assets).on_timeout()
    assert out.result == "timeout" and out.messages == ["💀 Time's up! The word was SEA LION."]
