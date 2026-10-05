"""End-to-end flows: BotCore driven through console-style chat lines, with a fake clock."""

import asyncio
import json
import random
import sqlite3
from itertools import count

import pytest

from bot.activity_log import ActivityLog
from bot.config import ConfigError
from bot.connectors.base import AuthRequired, ReadyInfo, SendResult
from bot.connectors.console import ConsoleConnector, parse_console_line
from bot.core import BotCore
from bot.stats import StatsStore
from tests.helpers import FakeHttp, make_config, make_msg


class Bot:
    def __init__(self, tmp_path, clock, assets, *, db=":memory:", lines=None, connector=None, http=None, **config):
        self.clock = clock
        self.ids = count(1)
        self.connector = connector or ConsoleConnector(clock=clock, lines=lines, out=lambda s: None)
        self.log = ActivityLog(tmp_path / "logs", clock)
        self.core = BotCore(
            config=make_config(tmp_path, **config),
            connector=self.connector,
            stats=StatsStore(db),
            log=self.log,
            clock=clock,
            assets=assets,
            http=http or FakeHttp(),
            rng=random.Random(1),
        )

    async def say(self, line: str) -> None:
        await self.core.on_message(parse_console_line(line, self.clock, self.ids))
        await self.core.outbox.flush_ready()

    async def wait(self, seconds: float) -> None:
        self.clock.advance(seconds)
        self.core.tick()
        await self.core.outbox.flush_ready()

    @property
    def out(self) -> list[str]:
        return self.connector.sent

    def events(self) -> list[dict]:
        path = self.log.path_for(self.clock.now().date())
        return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def bot(tmp_path, clock, assets) -> Bot:
    return Bot(tmp_path, clock, assets)


async def test_scramble_round_to_leaderboard(bot: Bot):
    await bot.say("alice: ?scramble animals")
    assert bot.out[-1].startswith("🔤 Unscramble (animals): ")
    await bot.say("bob: alligator")  # not bob's game
    await bot.say("alice: crocodile")
    await bot.say("alice: alligator")
    assert bot.out[-1] == "✅ alice got it: ALLIGATOR (+10)"
    await bot.say("carol: ?leaderboard")
    assert bot.out[-1] == "🏆 Top 1 overall: 1. alice (10)"
    await bot.say("alice: ?gamestats")
    assert bot.out[-1] == "📊 alice: 10 pts, 1 win, 1 played | scramble 1W/1P 10pts"


async def test_two_players_play_at_once(bot: Bot):
    await bot.say("alice: ?scramble animals")
    await bot.say("bob: ?scramble animals")  # no chat-wide cooldown on starting games
    assert len(bot.core.games.sessions) == 2
    await bot.say("bob: alligator")
    await bot.say("alice: alligator")
    assert bot.out[-2:] == ["✅ bob got it: ALLIGATOR (+10)", "✅ alice got it: ALLIGATOR (+10)"]


async def test_scramble_hint_lowers_points(bot: Bot):
    await bot.say("alice: ?scramble animals")
    await bot.say("alice: ?hint")
    assert bot.out[-1] == "💡 Hint: A _ _ _ _ _ _ _ R"
    await bot.say("alice: alligator")
    assert bot.out[-1] == "✅ alice got it: ALLIGATOR (+7)"


async def test_hangman_win_through_g_and_plain_letters_ignored(bot: Bot):
    await bot.say("alice: ?hangman animals")
    answer = bot.core.games.sessions["console-alice"].game.answer
    assert "guess with ?g <letter> or ?g <answer>" in bot.out[-1]
    sent_before = len(bot.out)
    await bot.say("alice: W")
    assert len(bot.out) == sent_before and bot.core.games.sessions["console-alice"].game.wrong == []
    await bot.say(f"alice: ?g {answer.lower()}")
    assert bot.out[-1] == f"🎉 alice solved it: {answer} (+10)"


async def test_hangman_loss(bot: Bot):
    await bot.say("alice: ?hangman animals")
    game = bot.core.games.sessions["console-alice"].game
    misses = [c for c in "ZQXJKVWYUBDF" if c not in game.answer][:6]
    for letter in misses:
        await bot.say(f"alice: ?g {letter}")
        bot.clock.advance(2)  # Hangman allows one guess every 2 s
    assert bot.out[-1] == f"💀 Out of lives! The word was {game.answer}."
    assert bot.core.games.sessions == {}


async def test_skip_ends_your_game(bot: Bot):
    await bot.say("alice: ?scramble animals")
    await bot.say("alice: ?skip")
    assert bot.out[-1] == "⏭️ Skipped. It was ALLIGATOR."


async def test_game_times_out(bot: Bot):
    await bot.say("alice: ?scramble animals")
    await bot.wait(45)
    assert bot.out[-1] == "⏰ Time's up! It was ALLIGATOR."


async def test_busy_brake_when_messages_back_up(tmp_path, clock, assets):
    bot = Bot(tmp_path, clock, assets)
    for i in range(10):
        bot.core.outbox.enqueue(f"backlog {i}")
    await bot.core.on_message(parse_console_line("alice: ?scramble", clock, bot.ids))
    assert bot.core.outbox.pending()[-1] == "Too many games running right now, try again in a moment."
    assert bot.core.games.sessions == {}


async def test_busy_brake_skips_fun_stats_and_help_but_not_control(tmp_path, clock, assets):
    bot = Bot(tmp_path, clock, assets)
    for i in range(10):
        bot.core.outbox.enqueue(f"backlog {i}")
    for line in ("alice: ?coinflip", "bob: ?gamestats", "carol: ?help", "dave: ?cookie"):
        await bot.core.on_message(parse_console_line(line, clock, bot.ids))
    assert len(bot.core.outbox) == 10
    await bot.core.on_message(parse_console_line("@mod: ?bot status", clock, bot.ids))
    assert len(bot.core.outbox) == 11


async def test_non_mod_cannot_control_and_mod_can_pause_and_resume(bot: Bot):
    await bot.say("random: ?bot shutdown")
    await bot.say("random: ?bot off")
    assert bot.out == [] and not bot.core.paused
    await bot.say("alice: ?scramble animals")
    await bot.say("@mod: ?bot off")
    assert bot.core.paused
    assert bot.core.games.sessions == {}
    assert "Bot paused by mod. ?bot on to resume." in bot.out
    before = len(bot.out)
    bot.clock.advance(60)
    await bot.say("alice: ?scramble animals")
    await bot.say("alice: ?8ball hi")
    assert len(bot.out) == before
    await bot.say("@mod: ?bot status")
    assert bot.out[-1].startswith("PAUSED · up 1m · games: 0 running · v")
    await bot.say("@mod: ?bot on")
    assert bot.out[-1] == "Bot resumed by mod."
    await bot.say("alice: ?coinflip")
    assert bot.out[-1] in ("🪙 Heads", "🪙 Tails")


async def test_non_mod_cannot_resume_a_paused_bot(bot: Bot):
    await bot.say("@mod: ?bot off")
    await bot.say("random: ?bot on")
    assert bot.core.paused


async def test_owner_can_control_without_mod_badge(bot: Bot):
    await bot.say("robert: ?bot off")
    assert bot.core.paused


async def test_stopgame_stops_everyones_games(bot: Bot):
    await bot.say("@mod: ?stopgame")
    assert bot.out[-1] == "No games are running."
    await bot.say("alice: ?scramble animals")
    await bot.say("bob: ?hangman animals")
    await bot.say("random: ?stopgame")  # not a mod: ignored
    assert len(bot.core.games.sessions) == 2
    await bot.say("@mod: ?stopgame")
    assert bot.out[-1] == "🛑 Stopped 2 games. No points awarded."
    assert bot.core.games.sessions == {}


async def test_paused_state_survives_restart(tmp_path, clock, assets):
    db = tmp_path / "data" / "bot.db"
    first = Bot(tmp_path, clock, assets, db=db)
    await first.say("@mod: ?bot off")
    first.core.stats.close()
    second = Bot(tmp_path, clock, assets, db=db)
    assert second.core.paused
    await second.say("alice: ?8ball hi")
    assert second.out == []


async def test_shared_chat_and_own_messages_are_ignored(bot: Bot):
    await bot.core.on_message(make_msg("?bot off", "othermod", mod=True, source_channel_id="other-channel"))
    await bot.core.on_message(make_msg("?coinflip", "me", user_id="console-bot"))
    await bot.core.on_message(make_msg("?coinflip", "local", source_channel_id="console"))
    await bot.core.outbox.flush_ready()
    assert not bot.core.paused
    assert len(bot.out) == 1  # only the message whose source is our own channel


async def test_cookie_daily_limit_across_midnight(bot: Bot):
    await bot.say("alice: ?cookie")
    assert bot.out[-1] == "🥠 Good things are coming."
    bot.clock.advance(11)
    await bot.say("alice: ?cookie")
    assert bot.out[-1].startswith("You already opened today's cookie. Next one in 11h 59m")
    await bot.wait(12 * 3600)
    await bot.say("alice: ?cookie")
    assert bot.out[-1] == "🥠 Good things are coming."


async def test_fact_api_failure_falls_back(tmp_path, clock, assets):
    bot = Bot(tmp_path, clock, assets, http=FakeHttp({}))
    await bot.say("alice: ?catfact")
    assert bot.out[-1] == "🐱 fallback catfacts line"


async def test_quick_commands_have_user_and_global_cooldowns(bot: Bot):
    await bot.say("alice: ?coinflip")
    await bot.say("alice: ?coinflip")
    await bot.say("bob: ?coinflip")
    assert len(bot.out) == 1
    bot.clock.advance(5)
    await bot.say("bob: ?coinflip")
    assert len(bot.out) == 2


async def test_personal_commands_are_not_blocked_by_someone_elses(bot: Bot):
    await bot.say("alice: ?gamestats")
    await bot.say("bob: ?gamestats")
    await bot.say("carol: ?help")
    await bot.say("dave: ?help")
    await bot.say("erin: ?cookie")
    await bot.say("frank: ?cookie")
    assert len(bot.out) == 6
    await bot.say("gina: ?coinflip")
    await bot.say("hank: ?coinflip")  # public commands keep the chat-wide cooldown
    assert len(bot.out) == 7


async def test_not_being_a_mod_slows_sending_down(tmp_path, clock, assets):
    bot = Bot(tmp_path, clock, assets)
    await bot.core._on_ready(ReadyInfo("chan", "chan", is_mod=False))
    assert bot.core.outbox.rate == 0.6 and bot.core.outbox.burst == 1


async def test_losing_mod_status_while_running_slows_sending_down(tmp_path, clock, assets):
    bot = Bot(tmp_path, clock, assets)
    await bot.core._on_ready(ReadyInfo("chan", "chan", is_mod=True))
    assert bot.core.outbox.rate > 0.6  # unchanged while modded
    await bot.core._on_ready(ReadyInfo("chan", "chan", is_mod=False))
    assert bot.core.outbox.rate == 0.6 and bot.core.outbox.burst == 1
    assert [e["event"] for e in bot.events()].count("startup") == 1


async def test_help_overview_lists_real_commands_under_500_chars(bot: Bot):
    await bot.say("alice: ?help")
    text = bot.out[-1]
    assert text == (
        "Games: ?scramble ?hangman ?skip | Stats: ?leaderboard ?gamestats | "
        "Fun: ?8ball ?coinflip ?catfact ?dogfact ?fact ?dadjoke ?cookie · ?help <command> for details"
    )
    for cmd in bot.core.registry.all():
        assert cmd.usage and cmd.description
        assert len(bot.core.registry.help_for(cmd.name)) <= 500
    bot.clock.advance(5)  # ?help has a 5 s global cooldown
    await bot.say("bob: ?help hangman")
    assert "?g <letter>" in bot.out[-1]


async def test_database_error_recording_a_user_does_not_crash(bot: Bot, monkeypatch):
    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(bot.core.stats, "touch_user", locked)
    await bot.say("alice: ?coinflip")
    assert any(e["event"] == "error" and e["where"] == "command:coinflip" for e in bot.events())


async def test_tick_survives_a_failing_log_rollover(bot: Bot, monkeypatch):
    def broken():
        raise OSError("disk gone")

    monkeypatch.setattr(bot.log, "maybe_rollover", broken)
    await bot.say("alice: ?scramble animals")
    await bot.wait(45)  # the game still times out even though rollover fails every tick
    assert bot.out[-1] == "⏰ Time's up! It was ALLIGATOR."
    assert any(e["event"] == "error" and e["where"] == "log_rollover" for e in bot.events())


async def test_command_logged_and_handler_error_does_not_crash(bot: Bot):
    async def broken(ctx):
        raise ValueError("bad handler")

    from bot.commands import Command

    bot.core.registry.add(Command("broken", broken, "{p}broken", "Breaks.", "Fun"))
    await bot.say("alice: ?broken")
    await bot.say("alice: ?coinflip")
    events = bot.events()
    assert any(e["event"] == "command" and e["command"] == "broken" for e in events)
    assert any(e["event"] == "error" and e["where"] == "command:broken" for e in events)
    assert bot.out[-1] in ("🪙 Heads", "🪙 Tails")


async def test_run_shutdown_from_chat_exits_zero(tmp_path, clock, assets):
    lines = ["alice: ?scramble animals", "@mod: ?bot shutdown", "alice: ?coinflip"]
    bot = Bot(tmp_path, clock, assets, lines=lines)
    code = await asyncio.wait_for(bot.core.run(), timeout=5)
    assert code == 0
    assert bot.out[1:] == ["Shutting down (requested by mod)."]
    assert not any(t in bot.out for t in ("🪙 Heads", "🪙 Tails"))  # ignored after shutdown
    assert bot.core.games.sessions == {}
    events = bot.events()
    assert events[0]["event"] == "startup" and events[0]["is_mod"] is True
    assert events[-1] == {**events[-1], "event": "shutdown", "by": "mod", "exit_code": 0}


async def test_run_ends_cleanly_when_console_input_ends(tmp_path, clock, assets):
    bot = Bot(tmp_path, clock, assets, lines=["alice: ?coinflip"])
    assert await asyncio.wait_for(bot.core.run(), timeout=5) == 0
    assert bot.out[0] in ("🪙 Heads", "🪙 Tails")


class FailingConnector:
    channel_id = "x"

    def __init__(self, exc: Exception):
        self.exc = exc
        self.sent: list[str] = []

    async def run(self, on_message, on_ready):
        await on_ready(ReadyInfo("x", "x", False))
        raise self.exc

    async def send(self, text, reply_to=None):
        self.sent.append(text)
        return SendResult(True)

    async def lookup_user(self, login):
        return None

    async def close(self):
        pass


@pytest.mark.parametrize(
    "exc, code",
    [(AuthRequired("token revoked"), 3), (ConfigError("channel not found"), 2), (RuntimeError("socket died"), 1)],
)
async def test_run_maps_connector_failures_to_exit_codes(tmp_path, clock, assets, exc, code):
    bot = Bot(tmp_path, clock, assets, connector=FailingConnector(exc))
    assert await asyncio.wait_for(bot.core.run(), timeout=5) == code
    assert bot.events()[-1]["exit_code"] == code


class BlockingConnector(FailingConnector):
    """Runs until close(); records the order of sends and close."""

    def __init__(self, close_error: Exception | None = None):
        super().__init__(RuntimeError("unused"))
        self.events: list[tuple[str, str]] = []
        self.closed = asyncio.Event()
        self.close_error = close_error

    async def run(self, on_message, on_ready):
        await on_ready(ReadyInfo("x", "x", True))
        await self.closed.wait()

    async def send(self, text, reply_to=None):
        self.events.append(("send", text))
        return SendResult(True)

    async def close(self):
        self.events.append(("close", ""))
        self.closed.set()
        if self.close_error:
            raise self.close_error


async def test_signal_shutdown_while_connected(tmp_path, clock, assets):
    conn = BlockingConnector()
    bot = Bot(tmp_path, clock, assets, connector=conn)
    asyncio.get_running_loop().call_later(0.05, bot.core.request_shutdown, "signal")
    assert await asyncio.wait_for(bot.core.run(), timeout=5) == 0
    assert bot.events()[-1]["by"] == "signal"
    assert conn.events[-1] == ("close", "")


async def test_shutdown_notice_is_sent_before_the_connector_closes(tmp_path, clock, assets):
    conn = BlockingConnector()
    bot = Bot(tmp_path, clock, assets, connector=conn)

    async def mod_shuts_down():
        await asyncio.sleep(0.05)
        await bot.core.on_message(parse_console_line("@mod: ?bot shutdown", clock, bot.ids))

    asyncio.get_running_loop().create_task(mod_shuts_down())
    assert await asyncio.wait_for(bot.core.run(), timeout=5) == 0
    assert conn.events == [("send", "Shutting down (requested by mod)."), ("close", "")]


async def test_error_while_closing_still_exits_cleanly(tmp_path, clock, assets):
    conn = BlockingConnector(close_error=OSError("could not save tokens"))
    http = FakeHttp()
    closed = []

    async def record_close():
        closed.append(True)

    http.close = record_close
    bot = Bot(tmp_path, clock, assets, connector=conn, http=http)
    asyncio.get_running_loop().call_later(0.05, bot.core.request_shutdown, "signal")
    assert await asyncio.wait_for(bot.core.run(), timeout=5) == 0
    events = bot.events()
    assert any(e["event"] == "error" and e["where"] == "shutdown:connector.close" for e in events)
    assert events[-1]["event"] == "shutdown" and events[-1]["exit_code"] == 0
    assert closed == [True]


async def test_connector_failure_discards_instead_of_sending(tmp_path, clock, assets):
    conn = FailingConnector(RuntimeError("socket died"))
    bot = Bot(tmp_path, clock, assets, connector=conn)
    bot.core.outbox._tokens = 0  # rate limit exhausted (the fake clock never refills it): message stays queued
    bot.core.outbox.enqueue("queued before the crash")
    assert await asyncio.wait_for(bot.core.run(), timeout=5) == 1
    assert conn.sent == []
    assert any(e.get("reason") == "connector_failed" for e in bot.events())


ALL_GAMES_ON = ("scramble", "hangman", "trivia", "riddle", "higherlower")


@pytest.fixture
def allbot(tmp_path, clock, assets) -> Bot:
    return Bot(tmp_path, clock, assets, enabled_games=ALL_GAMES_ON)


async def test_help_lists_every_game_and_explains_shared_commands(allbot: Bot):
    await allbot.say("alice: ?help")
    assert allbot.out[-1].startswith("Games: ?scramble ?hangman ?trivia ?riddle ?higherlower ?skip | ")
    await allbot.say("bob: ?help g")
    assert allbot.out[-1] == "?g <guess> · Guess in your current game."
    await allbot.say("carol: ?help hl")
    assert allbot.out[-1].startswith("?higherlower · Does the next thing") and allbot.out[-1].endswith("(also ?hl)")


async def test_trivia_round_to_gamestats(allbot: Bot):
    await allbot.say("alice: ?trivia medium science")
    assert allbot.out[-1] == "❓ (science, medium) Which planet is the largest? · 30s · ?g <answer> · ?hint"
    await allbot.say("alice: ?hint")
    assert allbot.out[-1] == "💡 7 letters, starts with J"
    await allbot.say("alice: ?g jupitr")
    assert allbot.out[-1] == "✅ alice got it: Jupiter (+7)"
    await allbot.say("alice: ?gamestats trivia")
    assert allbot.out[-1] == "📊 alice · trivia: 1 win / 1 played · 7 pts · rank #1"


async def test_trivia_unknown_option_is_not_echoed(allbot: Bot):
    await allbot.say("alice: ?trivia astrology")
    assert allbot.out[-1] == (
        "Unknown option. Trivia categories: history, science · difficulties: easy, medium, hard"
    )


async def test_riddle_round(allbot: Bot):
    await allbot.say("alice: ?riddle")
    answer = "clock" if "hands" in allbot.out[-1] else "towel"
    await allbot.say("alice: ?g nope")
    assert allbot.out[-1] == "❌ Not it, 2 guesses left."
    await allbot.say(f"alice: ?g is it a {answer}")
    assert allbot.out[-1] == f"✅ alice got it: {answer} (+10)"


async def test_higherlower_streak_then_timeout_keeps_the_points(allbot: Bot):
    await allbot.say("alice: ?hl")
    game = allbot.core.games.sessions["console-alice"].game
    guess = "higher" if game.next["views"] >= game.current["views"] else "lower"
    await allbot.wait(15)
    await allbot.say(f"alice: ?g {guess}")
    assert allbot.out[-1].startswith("✅ ") and "Streak 1." in allbot.out[-1]
    await allbot.wait(15)  # 30 s since the start, but the right answer restarted the 20 s timer
    assert "console-alice" in allbot.core.games.sessions
    await allbot.wait(6)
    assert allbot.out[-1].startswith("⏰ Time's up! ") and allbot.out[-1].endswith("Streak 1 (+1)")
    await allbot.say("bob: ?leaderboard higherlower")
    assert allbot.out[-1] == "🏆 Top 1 higherlower: 1. alice (1)"
