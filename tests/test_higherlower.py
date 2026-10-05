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
