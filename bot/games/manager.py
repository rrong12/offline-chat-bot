"""Runs personal games: each player has at most one game, many players can play at once."""

from __future__ import annotations

import logging
import math
import random
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from bot.activity_log import ActivityLog
from bot.assets import Assets
from bot.clock import Clock
from bot.commands import Command, CommandContext, CommandRegistry
from bot.connectors.base import ChatMessage
from bot.games.base import Game, Outcome
from bot.stats import PlayerResult, RoundRecord, StatsStore

logger = logging.getLogger(__name__)

Say = Callable[..., None]  # say(text, *, reply_to=None, coalesce_key=None, priority=False)


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
        self._cooldown_until: dict[str, float] = {}  # user_id -> when they may start again

    # registration

    def register(self, registry: CommandRegistry) -> None:
        for cls in self.games.values():
            registry.add(
                Command(cls.name, self._start_command, cls.usage, cls.description, "Games", global_cooldown=False)
            )
        registry.add(Command("skip", self._skip_command, "{p}skip", "End your current game.", "Games", cooldown=False))
        seen: set[str] = set()
        for cls in self.games.values():
            for name, (usage, description) in cls.commands.items():
                if name not in seen:
                    seen.add(name)
                    registry.add(
                        Command(name, self._game_command, usage, description, "Games", cooldown=False, listed=False)
                    )

    # helpers

    def _reply(self, session: Session, text: str, coalesce_key: str | None = None) -> None:
        key = f"{coalesce_key}:{session.user_id}" if coalesce_key else None
        self._say(text.replace("{p}", self.prefix), reply_to=session.reply_to, coalesce_key=key)

    def cooldown_remaining(self, user_id: str) -> float:
        return max(0.0, self._cooldown_until.get(user_id, 0.0) - self.clock.mono())

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
                self._finish(session, "stopped", ["Game ended due to an error."], {}, set())
            return None

    # commands

    async def _start_command(self, ctx: CommandContext) -> None:
        cls = self.games[ctx.name]
        arg = ctx.args.strip().lower()
        categories = cls.category_names(self.assets)
        uid = ctx.msg.user_id
        if arg == "categories":
            ctx.reply(f"{cls.title} categories: {', '.join(categories)}")
            return
        if uid in self.sessions:
            ctx.reply(f"You already have a {self.sessions[uid].game.name} game running.")
            return
        remaining = self.cooldown_remaining(uid)
        if remaining > 0:
            ctx.reply(f"Your next game in {math.ceil(remaining)}s.")
            return
        if len(self.sessions) >= self.max_games or self._is_busy():
            ctx.reply("Too many games running right now, try again in a moment.")
            return
        if categories and arg and arg not in categories:
            ctx.reply(f"Unknown category. {cls.title} categories: {', '.join(categories)}")
            return
        category = (arg or self.rng.choice(categories)) if categories else None
        try:
            game = cls(category, self.rng, self.assets)
            opening = game.start()
        except Exception as exc:
            logger.exception("could not start %s", cls.name)
            self.log.write("error", where=f"game:{cls.name}.start", type=type(exc).__name__, message=str(exc))
            ctx.reply("Couldn't start that game.")
            return
        self.stats.touch_user(uid, ctx.msg.login, ctx.msg.display_name, self.clock.now())
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
        self.log.write("game_start", round=session.key, game=cls.name, category=category, player=ctx.msg.login)
        self._reply(session, opening)

    async def _skip_command(self, ctx: CommandContext) -> None:
        session = self.sessions.get(ctx.msg.user_id)
        if session is None:
            return
        session.reply_to = ctx.msg.id
        answer = self._guard(session, f"{session.game.name}.reveal", session.game.reveal)
        if answer is not None:
            self._finish(session, "skipped", [f"⏭️ Skipped. It was {answer}."], {}, set())

    async def _game_command(self, ctx: CommandContext) -> None:
        session = self.sessions.get(ctx.msg.user_id)
        if session is None or ctx.name not in session.game.commands:
            return
        session.reply_to = ctx.msg.id
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
        now = self.clock.now()
        outcome = self._guard(session, f"{session.game.name}.on_message", lambda: session.game.on_message(msg, now))
        if outcome is not None:
            session.reply_to = msg.id  # thread the reply under the answer that produced it
        self._handle(session, outcome)

    def tick(self) -> None:
        for session in list(self.sessions.values()):
            if self.sessions.get(session.user_id) is not session:
                continue
            elapsed = self.clock.mono() - session.start_mono
            game = session.game
            if elapsed >= game.time_limit:
                outcome = self._guard(session, f"{game.name}.on_timeout", game.on_timeout)
            else:
                outcome = self._guard(session, f"{game.name}.on_tick", lambda g=game, e=elapsed: g.on_tick(e))
            self._handle(session, outcome)

    def stop_all(self) -> int:
        """End every running game with no points (?stopgame, ?bot off, shutdown). Returns how many."""
        stopped = list(self.sessions.values())
        for session in stopped:
            self._finish(session, "stopped", [], {}, set())
        return len(stopped)

    # outcomes

    def _handle(self, session: Session, outcome: Outcome | str | None) -> None:
        if not isinstance(outcome, Outcome) or self.sessions.get(session.user_id) is not session:
            return
        if outcome.finished:
            self._finish(session, outcome.result or "won", outcome.messages, outcome.awards, outcome.winners)
        else:
            for text in outcome.messages:
                self._reply(session, text, outcome.coalesce_key)

    def _finish(
        self, session: Session, result: str, messages: list[str], awards: dict[str, int], winners: set[str]
    ) -> None:
        self.sessions.pop(session.user_id, None)
        self._cooldown_until[session.user_id] = self.clock.mono() + self.cooldown_seconds
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
