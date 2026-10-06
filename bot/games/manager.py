"""Runs personal games: each player has at most one game, many players can play at once."""

from __future__ import annotations

import logging
import math
import random
import traceback
import uuid
from collections import Counter, OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from bot.activity_log import ActivityLog
from bot.assets import Assets
from bot.clock import Clock
from bot.commands import Command, CommandContext, CommandRegistry, Handler
from bot.connectors.base import ChatMessage
from bot.cooldowns import Cooldowns
from bot.games.base import Game, Outcome
from bot.stats import PlayerResult, RoundRecord, StatsStore

logger = logging.getLogger(__name__)

Say = Callable[..., None]  # say(text, *, reply_to=None, coalesce_key=None, priority=False)

NOTICE_SECONDS = 5.0  # at most one "can't start" or category-list reply per player this often
MAX_OPENING = 480  # characters: an opening message with the topic tip still fits in one chat message
RECENT_ITEMS = 50  # a player doesn't get the same question again within their last 50 of that game
RECENT_PLAYERS = 10_000  # remembered (game, player) pairs; the least recently active are forgotten
# Help for in-game commands that several games share; a command only one game uses keeps its own text.
SHARED_COMMAND_HELP = {
    "g": ("{p}g <guess>", "Guess in your current game."),
    "hint": ("{p}hint", "Get a hint in your current game (fewer points)."),
}


@dataclass
class Session:
    key: str  # short id that ties game_start and game_end log lines together
    game: Game
    category: str | None
    user_id: str
    login: str
    display_name: str
    started_at: datetime
    start_mono: float
    reply_to: str  # the player's latest message; bot replies are threaded under it


class GameManager:
    def __init__(
        self,
        *,
        games: dict[str, type[Game]],
        stats: StatsStore,
        log: ActivityLog,
        clock: Clock,
        assets: Assets,
        rng: random.Random,
        say: Say,
        prefix: str,
        cooldown_seconds: float,
        max_games: int,
        is_busy: Callable[[], bool],
    ) -> None:
        self.games = games
        self.stats = stats
        self.log = log
        self.clock = clock
        self.assets = assets
        self.rng = rng
        self._say = say
        self.prefix = prefix
        self.cooldown_seconds = cooldown_seconds
        self.max_games = max_games
        self._is_busy = is_busy
        self.sessions: dict[str, Session] = {}  # user_id -> that player's running game
        self._cooldowns = Cooldowns(clock)  # per-player game cooldowns and notice rate limits
        self._recent: OrderedDict[tuple[str, str], deque[str]] = OrderedDict()  # (game, user_id) -> item ids

    # registration

    def register(self, registry: CommandRegistry) -> None:
        # Start commands have no command cooldowns: the per-player game cooldown is the only limit
        # on starting, and refusal replies are rate-limited separately (see _notice).
        for cls in self.games.values():
            handler = self._start_handler(cls)
            registry.add(
                Command(cls.name, handler, cls.usage, cls.description, "Games", aliases=cls.aliases, cooldown=False)
            )
        registry.add(Command(
            "skip", self._skip_command, "{p}skip", "Give up: end your current game and see the answer.", "Games",
            aliases=("giveup",), cooldown=False,
        ))
        users = Counter(name for cls in self.games.values() for name in cls.commands)
        seen: set[str] = set()
        for cls in self.games.values():
            for name, own_help in cls.commands.items():
                if name not in seen:
                    seen.add(name)
                    usage, description = SHARED_COMMAND_HELP.get(name, own_help) if users[name] > 1 else own_help
                    registry.add(
                        Command(name, self._game_command, usage, description, "Games", cooldown=False, listed=False)
                    )

    # helpers

    def _reply(self, session: Session, text: str, coalesce_key: str | None = None) -> None:
        key = f"{coalesce_key}:{session.key}" if coalesce_key else None  # unique per player and round
        self._say(text.replace("{p}", self.prefix), reply_to=session.reply_to, coalesce_key=key)

    def _notice(self, ctx: CommandContext, cls: type[Game], text: str) -> None:
        """Reply to a start request we can't fulfil, at most once per NOTICE_SECONDS per player per game.
        Keyed by the game, not the name typed, so switching to an alias (?hl) doesn't get around it."""
        if self._cooldowns.check_command(f"notice:{cls.name}", ctx.msg.user_id, NOTICE_SECONDS, 0):
            ctx.reply(text)

    def cooldown_remaining(self, user_id: str) -> float:
        return self._cooldowns.remaining(("game", user_id))

    @staticmethod
    def _seen(session: Session, msg: ChatMessage) -> None:
        """Track the player's latest message (replies thread under it) and current names."""
        session.reply_to = msg.id
        session.login = msg.login
        session.display_name = msg.display_name

    def status(self) -> str:
        return f"{len(self.sessions)} running"

    def _guard(self, session: Session, where: str, fn: Callable[[], Outcome | str | None]) -> Outcome | str | None:
        """Run game code. On an exception: log it and end that player's game with no points."""
        try:
            return fn()
        except Exception as exc:
            logger.exception("game error in %s", where)
            self.log.write(
                "error",
                where=f"game:{where}",
                type=type(exc).__name__,
                message=str(exc),
                traceback=traceback.format_exc(),
            )
            if self.sessions.get(session.user_id) is session:
                self._finish(session, "stopped", ["Game ended due to an error."], *self._banked(session))
            return None

    # commands

    def _start_handler(self, cls: type[Game]) -> Handler:
        async def handler(ctx: CommandContext) -> None:
            await self._start(cls, ctx)

        return handler

    @staticmethod
    def _options(cls: type[Game], categories: list[str]) -> str:
        parts = []
        if categories:
            parts.append(f"categories: {', '.join(categories)}")
        if cls.levels:
            parts.append(f"{cls.levels_label}: {', '.join(cls.levels)}")
        return f"{cls.title} {' · '.join(parts)}" if parts else f"{cls.title} has no options."

    async def _start(self, cls: type[Game], ctx: CommandContext) -> None:
        tokens = ctx.args.lower().split()
        try:
            categories = cls.category_names(self.assets)
        except Exception as exc:  # a missing or broken content file: say so instead of going quiet
            logger.exception("could not list %s categories", cls.name)
            self.log.write("error", where=f"game:{cls.name}.categories", type=type(exc).__name__, message=str(exc))
            self._notice(ctx, cls, "Couldn't start that game.")
            return
        uid = ctx.msg.user_id
        if tokens == ["categories"]:
            self._notice(ctx, cls, self._options(cls, categories))
            return
        if uid in self.sessions:
            self._notice(ctx, cls, f"You already have a {self.sessions[uid].game.name} game running.")
            return
        remaining = self.cooldown_remaining(uid)
        if remaining > 0:
            self._notice(ctx, cls, f"Your next game in {math.ceil(remaining)}s.")
            return
        if len(self.sessions) >= self.max_games or self._is_busy():
            self._notice(ctx, cls, "Too many games running right now, try again in a moment.")
            return
        if not categories and not cls.levels:
            tokens = []  # nothing to choose, so extra words ("?hl lets go") are ignored, as in Phase 1
        category: str | None = None
        level: str | None = None
        for token in tokens:
            if token in categories and category in (None, token):
                category = token
            elif token in cls.levels and level in (None, token):
                level = token
            else:  # never repeat the unknown word: it could be anything
                kind = "option" if cls.levels else "category"
                self._notice(ctx, cls, f"Unknown {kind}. {self._options(cls, categories)}")
                return
        random_topic = bool(categories) and category is None
        if random_topic:
            category = self.rng.choice(categories)
        recent_key = (cls.name, uid)
        try:
            game = cls(category, self.rng, self.assets, level=level, recent=tuple(self._recent.get(recent_key, ())))
            opening = game.start()
        except Exception as exc:
            logger.exception("could not start %s", cls.name)
            self.log.write("error", where=f"game:{cls.name}.start", type=type(exc).__name__, message=str(exc))
            self._notice(ctx, cls, "Couldn't start that game.")
            return
        session = Session(
            key=uuid.uuid4().hex[:8],
            game=game,
            category=category,
            user_id=uid,
            login=ctx.msg.login,
            display_name=ctx.msg.display_name,
            started_at=self.clock.now(),
            start_mono=self.clock.mono(),
            reply_to=ctx.msg.id,
        )
        self.sessions[uid] = session
        if isinstance(game.item_id, str):
            self._remember(recent_key, game.item_id)
        self.log.write("game_start", round=session.key, game=cls.name, category=category, player=ctx.msg.login)
        tip = f" · random topic, see {{p}}{cls.name} categories"
        if random_topic and len(opening) + len(tip) <= MAX_OPENING:  # tell players they can pick one
            opening += tip
        self._reply(session, opening)

    def _remember(self, key: tuple[str, str], item_id: str) -> None:
        recent = self._recent.pop(key, None) or deque(maxlen=RECENT_ITEMS)
        recent.append(item_id)
        self._recent[key] = recent  # now the most recently used
        while len(self._recent) > RECENT_PLAYERS:
            self._recent.popitem(last=False)

    async def _skip_command(self, ctx: CommandContext) -> None:
        session = self.sessions.get(ctx.msg.user_id)
        if session is None:
            return
        self._seen(session, ctx.msg)
        answer = self._guard(session, f"{session.game.name}.reveal", session.game.reveal)
        if answer is not None:
            awards, winners = self._banked(session)
            kept = awards.get(session.user_id, 0)
            note = f" You keep {kept} point{'' if kept == 1 else 's'}." if kept else ""
            self._finish(session, "skipped", [f"⏭️ Skipped. It was {answer}.{note}"], awards, winners)

    async def _game_command(self, ctx: CommandContext) -> None:
        session = self.sessions.get(ctx.msg.user_id)
        if session is None or ctx.name not in session.game.commands:
            return
        self._seen(session, ctx.msg)
        now = self.clock.now()
        outcome = self._guard(
            session,
            f"{session.game.name}.on_command",
            lambda: session.game.on_command(ctx.name, ctx.args, ctx.msg, now),
        )
        self._handle(session, outcome)

    # chat and time

    def on_message(self, msg: ChatMessage) -> None:
        session = self.sessions.get(msg.user_id)
        if session is None:
            return
        self._seen(session, msg)
        now = self.clock.now()
        outcome = self._guard(session, f"{session.game.name}.on_message", lambda: session.game.on_message(msg, now))
        self._handle(session, outcome)

    def _expired(self, session: Session, elapsed: float) -> bool | None:
        """Is the game past its time limit? None (and the game is ended) if the limit isn't a usable number."""
        limit = session.game.time_limit
        if isinstance(limit, (int, float)) and not isinstance(limit, bool) and math.isfinite(limit):
            return elapsed >= limit
        self.log.write("error", where=f"game:{session.game.name}.time_limit", type="ValueError",
                       message=f"time_limit is {limit!r}")
        self._finish(session, "stopped", ["Game ended due to an error."], *self._banked(session))
        return None

    def tick(self) -> None:
        for session in list(self.sessions.values()):
            if self.sessions.get(session.user_id) is not session:
                continue
            elapsed = self.clock.mono() - session.start_mono
            game = session.game
            expired = self._expired(session, elapsed)
            if expired is None:
                continue
            if expired:
                outcome = self._guard(session, f"{game.name}.on_timeout", game.on_timeout)
                self._handle(session, outcome, default_result="timeout")
                if self.sessions.get(session.user_id) is session:  # the game didn't end itself: force it
                    self._finish(session, "timeout", [], {}, set())
            else:
                outcome = self._guard(session, f"{game.name}.on_tick", lambda g=game, e=elapsed: g.on_tick(e))
                self._handle(session, outcome)

    def stop_all(self) -> int:
        """End every running game (?stopgame, ?bot off, shutdown), keeping only points already banked
        (a Higher or Lower streak). Returns how many."""
        stopped = list(self.sessions.values())
        for session in stopped:
            self._finish(session, "stopped", [], *self._banked(session))
        return len(stopped)

    def _banked(self, session: Session) -> tuple[dict[str, int], set[str]]:
        """The awards and winners for points a game had already banked when it ended early."""
        try:
            points, won = session.game.banked()
        except Exception as exc:  # a broken game keeps nothing, and never stops the others from ending
            logger.exception("banked points failed in %s", session.game.name)
            self.log.write("error", where=f"game:{session.game.name}.banked", type=type(exc).__name__, message=str(exc))
            return {}, set()
        uid = session.user_id
        return ({uid: points} if points > 0 else {}), ({uid} if won else set())

    # outcomes

    def _handle(self, session: Session, outcome: Outcome | str | None, default_result: str = "won") -> None:
        if not isinstance(outcome, Outcome) or self.sessions.get(session.user_id) is not session:
            return
        if outcome.finished:
            result = outcome.result or default_result
            self._finish(session, result, outcome.messages, outcome.awards, outcome.winners)
        else:
            if outcome.restart_timer:
                session.start_mono = self.clock.mono()
            for text in outcome.messages:
                self._reply(session, text, outcome.coalesce_key)

    def _finish(
        self, session: Session, result: str, messages: list[str], awards: dict[str, int], winners: set[str]
    ) -> None:
        if self.sessions.get(session.user_id) is not session:  # already finished (or replaced): never twice
            return
        del self.sessions[session.user_id]
        self._cooldowns.trigger(("game", session.user_id), self.cooldown_seconds)
        uid = session.user_id
        player = PlayerResult(uid, session.login, session.display_name, awards.get(uid, 0), uid in winners)
        try:
            self.stats.record_round(
                RoundRecord(
                    game=session.game.name,
                    category=session.category,
                    started_by=uid,
                    started_at=session.started_at,
                    ended_at=self.clock.now(),
                    outcome=result,
                    players=[player],
                )
            )
        except Exception as exc:
            logger.exception("could not record round")
            self.log.write("error", where="stats.record_round", type=type(exc).__name__, message=str(exc))
        self.log.write(
            "game_end",
            round=session.key,
            game=session.game.name,
            outcome=result,
            player=session.login,
            points=player.points,
        )
        for text in messages:
            self._reply(session, text)
