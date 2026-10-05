from datetime import datetime, timezone

import pytest

from bot.commands import CommandContext, CommandRegistry
from bot.help import register_help
from bot.stats import PlayerResult, RoundRecord, StatsStore
from bot.stats_commands import register_stats
from tests.helpers import make_msg

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


class Cmds:
    def __init__(self):
        self.stats = StatsStore(":memory:")
        self.registry = CommandRegistry("?")
        register_stats(self.registry, stats=self.stats, game_names=["scramble", "hangman"])
        register_help(self.registry)
        self.replies: list[str] = []

    def play(self, game: str, login: str, points: int, won: bool = True) -> None:
        self.stats.touch_user(f"id-{login}", login, login.title(), T0)
        self.stats.record_round(
            RoundRecord(game, None, f"id-{login}", T0, T0, "won",
                        [PlayerResult(f"id-{login}", login, login.title(), points, won)])
        )

    async def run(self, text: str, login: str = "alice") -> str:
        name, _, args = text.removeprefix("?").partition(" ")
        ctx = CommandContext(make_msg(text, login), name, args, "?", lambda t, **kw: self.replies.append(t), None)
        await self.registry.get(name).handler(ctx)
        return self.replies[-1]


@pytest.fixture
def c() -> Cmds:
    cmds = Cmds()
    cmds.play("scramble", "bob", 10)
    cmds.play("scramble", "bob", 7)
    cmds.play("scramble", "carol", 10)
    cmds.play("hangman", "carol", 12)
    cmds.play("hangman", "alice", 0, won=False)
    return cmds


async def test_leaderboard_overall_default(c: Cmds):
    assert await c.run("?leaderboard") == "🏆 Top 2 overall: 1. Carol (22) 2. Bob (17)"


async def test_leaderboard_game_and_limit_in_any_order(c: Cmds):
    assert await c.run("?leaderboard scramble 1") == "🏆 Top 1 scramble: 1. Bob (17)"
    assert await c.run("?leaderboard 1 hangman") == "🏆 Top 1 hangman: 1. Carol (12)"
    assert await c.run("?leaderboard 99") == "🏆 Top 2 overall: 1. Carol (22) 2. Bob (17)"


async def test_leaderboard_unknown_game_and_empty(c: Cmds):
    assert await c.run("?leaderboard chess") == "Unknown game. Games: scramble, hangman"
    empty = Cmds()
    assert await empty.run("?leaderboard hangman") == "No hangman scores yet."


async def test_gamestats_self_overall(c: Cmds):
    assert await c.run("?gamestats", "carol") == (
        "📊 carol: 22 pts, 2 wins, 2 played | hangman 1W/1P 12pts | scramble 1W/1P 10pts"
    )


async def test_gamestats_game_and_other_user(c: Cmds):
    assert await c.run("?gamestats scramble @Bob") == "📊 Bob · scramble: 2 wins / 2 played · 17 pts · rank #1"
    assert await c.run("?gamestats bob") == "📊 Bob: 17 pts, 2 wins, 2 played | scramble 2W/2P 17pts"


async def test_gamestats_played_without_points_has_no_rank(c: Cmds):
    assert await c.run("?gamestats hangman") == "📊 alice · hangman: 0 wins / 1 played · 0 pts"


async def test_gamestats_missing(c: Cmds):
    assert await c.run("?gamestats nobody_here") == "No stats for that user yet."
    assert await c.run("?gamestats bad/name") == "That's not a valid username."
    assert await c.run("?gamestats hangman bob") == "No hangman stats for Bob yet."
    assert await c.run("?gamestats", "dave") == "No stats for dave yet."


async def test_help_overview_and_details(c: Cmds):
    assert await c.run("?help") == "Stats: ?leaderboard ?gamestats · ?help <command> for details"
    assert await c.run("?commands") == "Stats: ?leaderboard ?gamestats · ?help <command> for details"
    assert await c.run("?help ?leaderboard") == (
        "?leaderboard [game] [1-10] · Top players by points, overall or for one game."
    )


async def test_help_unknown_never_echoes_unsafe_text(c: Cmds):
    assert await c.run("?help nope") == "No command named nope. Try ?help."
    assert await c.run("?help <script>") == "No command. Try ?help."
