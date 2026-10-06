import json
import random
import re

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


class Stubborn(Boom):
    """A game whose on_timeout forgets to finish, and whose reveal raises."""

    name = "stubborn"

    def on_message(self, msg, now):
        return None

    def on_timeout(self) -> Outcome:
        return Outcome(messages=["still going"])

    def reveal(self) -> str:
        raise RuntimeError("no answer")


class NoResult(Boom):
    """Times out with finished=True but no result."""

    name = "noresult"

    def on_message(self, msg, now):
        return None

    def on_timeout(self) -> Outcome:
        return Outcome(messages=["over"], finished=True)


class AnyCommand(Boom):
    """Answers any in-game command, to prove the manager only routes declared ones."""

    name = "anycommand"
    commands = {"g": ("{p}g", "Guess.")}

    def on_message(self, msg, now):
        return None

    def on_command(self, name, args, msg, now):
        return Outcome(messages=[f"got {name}"])


class BrokenStart(Boom):
    name = "brokenstart"

    def start(self) -> str:
        raise RuntimeError("cannot start")


class Quiz(Boom):
    """Has categories, levels, an alias, and question ids, to test start options and repeat avoidance."""

    name = "quiz"
    title = "Quiz"
    aliases = ("qz",)
    levels = ("easy", "hard")
    levels_label = "difficulties"
    ITEMS = ("q1", "q2", "q3")

    @classmethod
    def category_names(cls, assets):
        return ["science", "history"]

    def __init__(self, category, rng, assets, *, level=None, recent=()):
        super().__init__(category, rng, assets, level=level, recent=recent)
        self.item_id = self.pick_unseen(list(self.ITEMS), lambda item: item)

    def start(self) -> str:
        return f"quiz {self.category} {self.level} {self.item_id}"

    def on_message(self, msg, now):
        return None


class Streak(Boom):
    """Every guess is right and restarts the timer."""

    name = "streak"
    commands = {"g": ("{p}g", "Guess.")}

    def on_message(self, msg, now):
        return None

    def on_command(self, name, args, msg, now):
        return Outcome(messages=["right"], restart_timer=True)


class Harness:
    def __init__(self, tmp_path, clock: FakeClock, assets, max_games: int = 25, extra_games=None):
        self.clock = clock
        self.said: list[tuple[str, dict]] = []  # everything the manager sent: (text, kwargs)
        self.replies: list[str] = []  # direct command replies (ctx.reply)
        self.busy = False
        self.stats = StatsStore(":memory:")
        self.log = ActivityLog(tmp_path / "logs", clock)
        self.manager = GameManager(
            games={"scramble": Scramble, "hangman": Hangman, "boom": Boom, "stubborn": Stubborn,
                   "noresult": NoResult, "anycommand": AnyCommand, "brokenstart": BrokenStart,
                   "quiz": Quiz, "streak": Streak, **(extra_games or {})},
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
    assert names == {
        "scramble", "hangman", "boom", "stubborn", "noresult", "anycommand", "brokenstart", "quiz", "streak",
        "skip", "hint", "g",
    }
    start = h.registry.get("scramble")
    assert not start.cooldown  # the per-player game cooldown is the only limit on starting
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
    h.chat("alligator")  # alice wins; her 10 s cooldown starts now
    h.clock.advance(5)
    await h.command("?scramble animals")
    assert h.replies[-1] == "Your next game in 5s."
    await h.command("?scramble animals", "bob")  # other players aren't blocked
    assert "id-bob" in h.manager.sessions
    h.clock.advance(5)
    await h.command("?scramble animals")
    assert "id-alice" in h.manager.sessions


async def test_refusal_replies_are_rate_limited_per_player(h: Harness):
    await h.command("?scramble animals")
    await h.command("?scramble animals")
    await h.command("?scramble animals")
    assert h.replies == ["You already have a scramble game running."]
    h.clock.advance(5)
    await h.command("?scramble animals")
    assert len(h.replies) == 2


async def test_category_list_is_rate_limited_per_game(h: Harness):
    await h.command("?scramble categories")
    await h.command("?scramble categories")
    await h.command("?hangman categories")
    assert h.replies == ["Scramble categories: animals, food", "Hangman categories: animals, food"]


async def test_categories_then_pick_works_immediately(h: Harness):
    await h.command("?scramble categories")
    await h.command("?scramble food")
    assert h.texts()[0].startswith("🔤 Unscramble (food)")


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


async def test_hangman_board_updates_coalesce_per_game(h: Harness):
    await h.command("?hangman animals", "alice")
    await h.command("?hangman animals", "bob")
    await h.command("?g z", "alice")
    await h.command("?g z", "bob")
    (text_a, kw_a), (_, kw_b) = h.said[-2], h.said[-1]
    assert "wrong: Z (1/6)" in text_a
    assert kw_a["coalesce_key"] == f"hangman-board:{h.manager.sessions['id-alice'].key}"
    assert kw_a["coalesce_key"] != kw_b["coalesce_key"]


async def test_timeout_ends_the_game(h: Harness):
    await h.command("?scramble animals")
    h.clock.advance(59)
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
    msg = h.chat("anything", "alice")
    text, kw = h.said[-1]
    assert text == "Game ended due to an error." and kw["reply_to"] == msg.id
    assert set(h.manager.sessions) == {"id-bob"}
    assert any(e["event"] == "error" and e["where"] == "game:boom.on_message" for e in h.events())
    ends = [e for e in h.events() if e["event"] == "game_end"]
    assert ends == [{**ends[0], "game": "boom", "outcome": "stopped"}]


async def test_reveal_error_during_skip_ends_the_game_once(h: Harness):
    await h.command("?stubborn", "alice")
    await h.command("?skip", "alice")
    ends = [e for e in h.events() if e["event"] == "game_end"]
    assert len(ends) == 1 and ends[0]["outcome"] == "stopped"
    assert h.manager.sessions == {}
    assert h.stats._conn.execute("SELECT COUNT(*) FROM rounds").fetchone()[0] == 1


async def test_timeout_is_forced_if_the_game_does_not_finish(h: Harness):
    await h.command("?stubborn", "alice")
    h.clock.advance(10)
    h.manager.tick()
    h.manager.tick()
    assert h.manager.sessions == {}
    assert [e["outcome"] for e in h.events() if e["event"] == "game_end"] == ["timeout"]


async def test_start_failure_is_reported_once_and_starts_nothing(h: Harness):
    await h.command("?brokenstart")
    await h.command("?brokenstart")
    assert h.replies == ["Couldn't start that game."]
    assert h.manager.sessions == {}


async def test_finished_timeout_without_result_counts_as_timeout(h: Harness):
    await h.command("?noresult")
    h.clock.advance(10)
    h.manager.tick()
    assert [e["outcome"] for e in h.events() if e["event"] == "game_end"] == ["timeout"]


async def test_stats_failure_still_ends_the_game(h: Harness, monkeypatch):
    def broken(rec):
        raise RuntimeError("disk full")

    monkeypatch.setattr(h.stats, "record_round", broken)
    await h.command("?scramble animals")
    h.chat("alligator")
    assert h.manager.sessions == {}
    assert h.texts()[-1] == "✅ alice got it: ALLIGATOR (+10)"
    assert h.manager.cooldown_remaining("id-alice") == 10
    assert any(e["event"] == "error" and e["where"] == "stats.record_round" for e in h.events())


async def test_in_game_command_for_a_different_game_is_ignored(h: Harness):
    await h.command("?anycommand", "bob")
    await h.command("?hint", "bob")  # registered by Scramble; bob's game doesn't declare it
    assert h.texts() == ["boom started"]
    await h.command("?g", "bob")  # declared: reaches the game
    assert h.texts()[-1] == "got g"


async def test_finish_records_the_players_current_name(h: Harness):
    await h.command("?scramble animals")
    renamed = make_msg("alligator", "alice")
    renamed = renamed.__class__(**{**renamed.__dict__, "login": "alice_new", "display_name": "Alice_New"})
    h.manager.on_message(renamed)
    assert h.stats.find_user("alice_new") is not None


async def test_game_messages_get_prefix_substituted(h: Harness):
    await h.command("?hangman animals")
    assert "guess with ?g <letter>" in h.texts()[0]


def test_shared_in_game_commands_get_generic_help(h: Harness):
    assert h.registry.get("g").description == "Guess in your current game."  # several games use ?g
    assert h.registry.get("hint").description == "Get a hint in your Scramble game (fewer points)."  # only Scramble


async def test_category_and_level_in_either_order(h: Harness):
    await h.command("?quiz hard science")
    assert h.texts()[-1] == "quiz science hard q1"


async def test_level_without_category_picks_a_category(h: Harness):
    await h.command("?quiz easy")
    assert re.fullmatch(r"quiz (science|history) easy q[123]", h.texts()[-1])


async def test_categories_list_includes_levels(h: Harness):
    await h.command("?quiz categories")
    assert h.replies == ["Quiz categories: science, history · difficulties: easy, hard"]


async def test_unknown_option_lists_categories_and_levels_without_echoing(h: Harness):
    await h.command("?quiz science planets")
    assert h.replies == ["Unknown option. Quiz categories: science, history · difficulties: easy, hard"]
    assert h.manager.sessions == {}


async def test_alias_starts_the_game(h: Harness):
    await h.command("?qz science")
    assert h.texts()[-1] == "quiz science None q1"


async def test_recent_questions_are_not_repeated_for_that_player(h: Harness):
    seen = []
    for _ in range(4):
        await h.command("?quiz science")
        seen.append(h.texts()[-1].split()[-1])
        await h.command("?skip")
        h.clock.advance(10)
    assert sorted(seen[:3]) == ["q1", "q2", "q3"] and seen[3] == seen[0]  # all seen: the oldest comes back


async def test_each_player_has_their_own_question_history(h: Harness):
    for _ in range(2):
        await h.command("?quiz science", "alice")
        await h.command("?skip", "alice")
        h.clock.advance(10)
    await h.command("?quiz science", "bob")
    assert h.manager.sessions["id-bob"].game.recent == ()  # alice's history isn't bob's


async def test_refusal_notices_are_limited_per_game_even_through_an_alias(h: Harness):
    await h.command("?quiz science")
    await h.command("?qz science")
    await h.command("?quiz science")
    assert h.replies == ["You already have a quiz game running."]


async def test_restart_timer_gives_a_fresh_time_limit(h: Harness):
    await h.command("?streak")
    h.clock.advance(8)
    await h.command("?g x")
    h.clock.advance(8)  # 16 s since the start, but only 8 s since the right guess
    h.manager.tick()
    assert "id-alice" in h.manager.sessions
    h.clock.advance(2)
    h.manager.tick()
    assert h.manager.sessions == {}


class Plain(Boom):
    """No categories and no levels, like Riddle and Higher or Lower."""

    name = "plain"
    title = "Plain"

    def on_message(self, msg, now):
        return None


async def test_extra_words_are_ignored_by_a_game_without_options(tmp_path, clock, assets):
    h = Harness(tmp_path, clock, assets, extra_games={"plain": Plain})
    await h.command("?plain lets go")
    assert "id-alice" in h.manager.sessions
    await h.command("?plain categories", "bob")
    assert h.replies == ["Plain has no options."]


async def test_duplicate_and_uppercase_words_are_fine(h: Harness):
    await h.command("?quiz HARD hard Science")
    assert h.texts()[-1] == "quiz science hard q1"


async def test_a_broken_time_limit_ends_only_that_game(h: Harness):
    await h.command("?scramble animals", "alice")
    await h.command("?hangman animals", "bob")
    h.manager.sessions["id-alice"].game.time_limit = float("nan")
    h.manager.tick()
    assert set(h.manager.sessions) == {"id-bob"}
    assert h.texts()[-1] == "Game ended due to an error."
    h.clock.advance(200)
    h.manager.tick()  # bob's game still times out normally
    assert h.manager.sessions == {}


async def test_remembered_questions_are_bounded(h: Harness, monkeypatch):
    import bot.games.manager as manager_module

    monkeypatch.setattr(manager_module, "RECENT_ITEMS", 2)
    monkeypatch.setattr(manager_module, "RECENT_PLAYERS", 2)
    for login in ("alice", "bob", "carol"):
        for _ in range(3):
            await h.command("?quiz science", login)
            await h.command("?skip", login)
            h.clock.advance(10)
    assert list(h.manager._recent) == [("quiz", "id-bob"), ("quiz", "id-carol")]  # alice, the oldest, is gone
    assert all(len(ids) == 2 for ids in h.manager._recent.values())


class Sticky(Streak):
    """Asks for more time when it times out."""

    name = "sticky"

    def on_timeout(self):
        return Outcome(messages=["one more?"], restart_timer=True)


async def test_a_restart_timer_from_on_timeout_cannot_extend_a_game(tmp_path, clock, assets):
    h = Harness(tmp_path, clock, assets, extra_games={"sticky": Sticky})
    await h.command("?sticky")
    h.clock.advance(10)
    h.manager.tick()
    assert h.manager.sessions == {}  # force-finished anyway


class BadId(Quiz):
    name = "badid"
    aliases = ()

    def __init__(self, category, rng, assets, *, level=None, recent=()):
        super().__init__(category, rng, assets, level=level, recent=recent)
        self.item_id = ["not", "a", "string"]


async def test_a_non_string_item_id_is_not_remembered(tmp_path, clock, assets):
    h = Harness(tmp_path, clock, assets, extra_games={"badid": BadId})
    await h.command("?badid science")
    assert "id-alice" in h.manager.sessions and h.manager._recent == {}


class BrokenContent(Quiz):
    name = "brokencontent"
    aliases = ()

    @classmethod
    def category_names(cls, assets):
        raise FileNotFoundError("content/missing.json")


async def test_a_broken_content_file_gets_a_reply(tmp_path, clock, assets):
    h = Harness(tmp_path, clock, assets, extra_games={"brokencontent": BrokenContent})
    await h.command("?brokencontent")
    assert h.replies == ["Couldn't start that game."]


class Banker(Streak):
    """Each right answer banks a point the player keeps even if the game ends early."""

    name = "banker"

    def __init__(self, category, rng, assets, *, level=None, recent=()):
        super().__init__(category, rng, assets, level=level, recent=recent)
        self.score = 0

    def on_command(self, name, args, msg, now):
        self.score += 1
        return Outcome(messages=["right"], restart_timer=True)

    def banked(self):
        return self.score, self.score >= 2


async def test_skipping_keeps_banked_points(tmp_path, clock, assets):
    h = Harness(tmp_path, clock, assets, extra_games={"banker": Banker})
    await h.command("?banker")
    await h.command("?g x")
    await h.command("?skip")
    assert h.texts()[-1] == "⏭️ Skipped. It was nothing. You keep 1 point."
    assert [(r.user_id, r.points, r.wins) for r in h.stats.leaderboard("banker", 5)] == [("id-alice", 1, 0)]


async def test_stopping_keeps_banked_points_and_wins(tmp_path, clock, assets):
    h = Harness(tmp_path, clock, assets, extra_games={"banker": Banker})
    await h.command("?banker")
    await h.command("?g x")
    await h.command("?g x")
    assert h.manager.stop_all() == 1
    assert [(r.user_id, r.points, r.wins) for r in h.stats.leaderboard("banker", 5)] == [("id-alice", 2, 1)]


async def test_games_without_banked_points_still_score_nothing_on_skip(h: Harness):
    await h.command("?scramble animals")
    await h.command("?skip")
    assert h.texts()[-1] == "⏭️ Skipped. It was ALLIGATOR."
    assert h.stats.leaderboard(None, 5) == []
