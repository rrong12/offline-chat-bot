"""BotCore: filters incoming chat, routes commands and game input, owns the background loops."""

from __future__ import annotations

import asyncio
import logging
import random
import traceback
from collections.abc import Awaitable, Callable

from bot import __version__
from bot.activity_log import ActivityLog
from bot.admin import register_admin
from bot.assets import Assets
from bot.clock import Clock
from bot.commands import Command, CommandContext, CommandRegistry, parse_command
from bot.config import Config, ConfigError
from bot.connectors.base import AuthRequired, ChatMessage, Connector, ReadyInfo
from bot.cooldowns import Cooldowns
from bot.fun import register_fun
from bot.games import ALL_GAMES
from bot.games.manager import GameManager
from bot.help import register_help
from bot.http import HttpClient
from bot.outbox import Outbox
from bot.permissions import is_controller
from bot.stats import StatsStore
from bot.stats_commands import register_stats
from bot.text import format_duration

logger = logging.getLogger(__name__)

EXIT_OK, EXIT_CRASH, EXIT_CONFIG, EXIT_AUTH = 0, 1, 2, 3
# While the busy brake is on, these groups are ignored so game messages keep flowing.
BUSY_SKIPPED_GROUPS = ("Stats", "Fun", "Info")
NON_MOD_RATE = 0.6  # messages/s; Twitch's limit for a non-mod account is 20 per 30 s


class BotCore:
    def __init__(
        self,
        *,
        config: Config,
        connector: Connector,
        stats: StatsStore,
        log: ActivityLog,
        clock: Clock,
        assets: Assets,
        http: HttpClient,
        rng: random.Random,
    ) -> None:
        self.config = config
        self.connector = connector
        self.stats = stats
        self.log = log
        self.clock = clock
        self.http = http
        self.started_mono = clock.mono()
        self._ready = False
        self.outbox = Outbox(
            connector.send,
            clock,
            log,
            rate=config.outbox_rate,
            burst=config.outbox_burst,
            max_queue=config.outbox_max_queue,
        )
        self.cooldowns = Cooldowns(clock)
        self.registry = CommandRegistry(config.prefix)
        games = {name: ALL_GAMES[name] for name in config.enabled_games}
        self.games = GameManager(
            games=games,
            stats=stats,
            log=log,
            clock=clock,
            assets=assets,
            rng=rng,
            say=self.outbox.enqueue,
            prefix=config.prefix,
            cooldown_seconds=config.game_cooldown,
            max_games=config.max_games,
            is_busy=self.is_busy,
        )
        self.games.register(self.registry)
        register_stats(self.registry, stats=stats, game_names=list(games))
        register_fun(
            self.registry,
            assets=assets,
            rng=rng,
            http=http,
            stats=stats,
            clock=clock,
            lookup_user=connector.lookup_user,
        )
        register_help(self.registry)
        register_admin(self.registry, self)
        self.paused = stats.get_state("paused", "0") == "1"
        self.exit_code = EXIT_OK
        self.shutdown_by: str | None = None
        self._stop = asyncio.Event()

    # state

    def is_busy(self) -> bool:
        """The busy brake: too many bot messages are waiting to be sent."""
        return len(self.outbox) >= self.config.busy_queue

    def is_controller(self, msg: ChatMessage) -> bool:
        return is_controller(msg, self.config.owner_ids)

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.stats.set_state("paused", "1" if paused else "0")

    def status_line(self) -> str:
        state = "PAUSED" if self.paused else "ON"
        uptime = format_duration(self.clock.mono() - self.started_mono).replace(" ", "")
        return f"{state} · up {uptime} · games: {self.games.status()} · v{__version__}"

    def request_shutdown(self, by: str, exit_code: int = EXIT_OK) -> None:
        if self.shutdown_by is None:
            self.shutdown_by = by
            self.exit_code = exit_code
        self.games.stop_all()
        self._stop.set()

    # incoming chat

    async def on_message(self, msg: ChatMessage) -> None:
        if self._stop.is_set():  # shutting down: ignore anything still arriving
            return
        if msg.user_id == self.config.bot_id:
            return
        if msg.source_channel_id is not None and msg.source_channel_id != self.connector.channel_id:
            return
        parsed = parse_command(msg.text, self.config.prefix)
        if self.paused:
            if parsed is not None and parsed[0] == "bot" and self.is_controller(msg):
                await self._dispatch(self.registry.get("bot"), msg, *parsed)
            return
        if parsed is not None:
            cmd = self.registry.get(parsed[0])
            if cmd is not None:
                await self._dispatch(cmd, msg, *parsed)
            return
        self.games.on_message(msg)

    def _context(self, msg: ChatMessage, name: str, args: str) -> CommandContext:
        def reply(text: str, priority: bool = False) -> None:
            self.outbox.enqueue(text, reply_to=msg.id, priority=priority)

        def say(text: str, priority: bool = False, coalesce_key: str | None = None) -> None:
            self.outbox.enqueue(text, priority=priority, coalesce_key=coalesce_key)

        return CommandContext(msg, name, args, self.config.prefix, reply, say)

    async def _dispatch(self, cmd: Command | None, msg: ChatMessage, name: str, args: str) -> None:
        if cmd is None:
            return
        if cmd.controller_only and not self.is_controller(msg):
            return
        if cmd.group in BUSY_SKIPPED_GROUPS and self.is_busy():
            return
        global_seconds = self.config.global_cooldown if cmd.global_cooldown else 0
        if cmd.cooldown and not self.cooldowns.check_command(
            cmd.name, msg.user_id, self.config.user_cooldown, global_seconds
        ):
            return
        try:
            self.stats.touch_user(msg.user_id, msg.login, msg.display_name, self.clock.now())
            self.log.write("command", user_id=msg.user_id, login=msg.login, command=cmd.name, args=args[:100])
            await cmd.handler(self._context(msg, name, args))
        except Exception as exc:
            logger.exception("command %s failed", cmd.name)
            self.log.write(
                "error",
                where=f"command:{cmd.name}",
                type=type(exc).__name__,
                message=str(exc),
                traceback=traceback.format_exc(),
            )

    # background loops

    def tick(self) -> None:
        for where, step in (("tick", self.games.tick), ("log_rollover", self.log.maybe_rollover)):
            try:
                step()
            except Exception as exc:  # one failing step must never stop the timer loop
                logger.exception("%s failed", where)
                self.log.write("error", where=where, type=type(exc).__name__, message=str(exc))

    async def _tick_loop(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(1)
            self.tick()

    async def _on_ready(self, info: ReadyInfo) -> None:
        if not self._ready:  # called again only when mod status is lost while running
            self._ready = True
            self.log.write("startup", version=__version__, channel=info.channel_login, is_mod=info.is_mod)
        if not info.is_mod:
            # Twitch allows a non-mod 20 messages per 30 s; stay under it.
            self.outbox.rate = min(self.outbox.rate, NON_MOD_RATE)
            self.outbox.burst = 1
            logger.warning(
                "The bot is not a mod in %s: no Chat Bot badge, slow mode applies, sending slowed to %.1f/s.",
                info.channel_login,
                self.outbox.rate,
            )

    async def _cleanup_step(self, where: str, make: Callable[[], Awaitable[object]]) -> None:
        """Run one shutdown step; log any error instead of letting it turn a clean stop into a crash."""
        try:
            await make()
        except Exception as exc:
            logger.exception("shutdown step %s failed", where)
            self.log.write("error", where=f"shutdown:{where}", type=type(exc).__name__, message=str(exc))

    async def run(self) -> int:
        """Run until shutdown or a fatal connector error. Returns the process exit code."""
        self.log.prune()
        connector_task = asyncio.create_task(self.connector.run(self.on_message, self._on_ready))
        outbox_task = asyncio.create_task(self.outbox.run(self._stop))
        tick_task = asyncio.create_task(self._tick_loop())
        stop_task = asyncio.create_task(self._stop.wait())
        try:
            await asyncio.wait({connector_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
            if connector_task.done():
                connector_task.result()  # re-raises a connector failure
                self.request_shutdown(by="connector closed")
        except ConfigError as exc:
            logger.error("Setup problem: %s", exc)
            self.log.write("error", where="setup", type="ConfigError", message=str(exc))
            self.request_shutdown(by="config", exit_code=EXIT_CONFIG)
        except AuthRequired as exc:
            logger.error("Twitch login needed: re-run `python -m bot auth`. (%s)", exc)
            self.log.write("error", where="auth", type="AuthRequired", message=str(exc))
            self.request_shutdown(by="auth", exit_code=EXIT_AUTH)
        except Exception as exc:
            logger.exception("connector crashed")
            self.log.write(
                "error", where="connector", type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc()
            )
            self.request_shutdown(by="crash", exit_code=EXIT_CRASH)
        finally:
            if self.shutdown_by is None:  # run() itself was cancelled
                self.request_shutdown(by="cancelled")
            self._stop.set()
            for task in (tick_task, stop_task):
                task.cancel()
            await asyncio.gather(tick_task, stop_task, return_exceptions=True)
            # Let the send loop finish its current message (each send is bounded by the outbox's
            # send timeout) instead of cancelling it mid-send.
            done, _ = await asyncio.wait({outbox_task}, timeout=self.outbox.send_timeout)
            if not done:
                outbox_task.cancel()
            await asyncio.gather(outbox_task, return_exceptions=True)
            if self.exit_code == EXIT_OK:
                await self._cleanup_step("drain", lambda: self.outbox.drain(3.0))
            else:
                self.outbox.discard("connector_failed")  # nothing can be delivered now
            self.outbox.close()  # replies from handlers still finishing are logged as dropped
            await self._cleanup_step("connector.close", lambda: asyncio.wait_for(self.connector.close(), 5.0))
            if not connector_task.done():
                connector_task.cancel()
            await asyncio.gather(connector_task, return_exceptions=True)
            await self._cleanup_step("http.close", self.http.close)
            self.log.write("shutdown", by=self.shutdown_by, exit_code=self.exit_code)
        return self.exit_code
