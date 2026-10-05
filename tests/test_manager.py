import json
import random

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


class Harness:
    def __init__(self, tmp_path, clock: FakeClock, assets, max_games: int = 25):
        self.clock = clock
        self.said: list[tuple[str, dict]] = []  # everything the manager sent: (text, kwargs)
        self.replies: list[str] = []  # direct command replies (ctx.reply)
        self.busy = False
        self.stats = StatsStore(":memory:")
        self.log = ActivityLog(tmp_path / "logs", clock)
        self.manager = GameManager(
            games={"scramble": Scramble, "hangman": Hangman, "boom": Boom},
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
    assert names == {"scramble", "hangman", "boom", "skip", "hint", "g"}
    start = h.registry.get("scramble")
    assert start.cooldown and not start.global_cooldown  # anyone can start their own game
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
    h.chat("alligator")
    await h.command("?scramble animals")
    assert h.replies[-1] == "Your next game in 10s."
    await h.command("?scramble animals", "bob")  # other players aren't blocked
    assert "id-bob" in h.manager.sessions
    h.clock.advance(10)
    await h.command("?scramble animals")
    assert "id-alice" in h.manager.sessions


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


async def test_hangman_board_updates_coalesce_per_player(h: Harness):
    await h.command("?hangman animals", "alice")
    await h.command("?g z", "alice")
    text, kw = h.said[-1]
    assert "wrong: Z (1/6)" in text
    assert kw["coalesce_key"] == "hangman-board:id-alice"


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
    h.chat("anything", "alice")
    assert h.texts()[-1] == "Game ended due to an error."
    assert set(h.manager.sessions) == {"id-bob"}
    assert any(e["event"] == "error" and e["where"] == "game:boom.on_message" for e in h.events())


async def test_game_messages_get_prefix_substituted(h: Harness):
    await h.command("?hangman animals")
    assert "guess with ?g <letter>" in h.texts()[0]
