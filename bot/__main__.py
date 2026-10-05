"""Command line: `python -m bot` (run on Twitch), `python -m bot auth`, `python -m bot console`."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import os
import random
import signal
import sys
from pathlib import Path

from dotenv import dotenv_values

from bot import certs  # noqa: F401  (first: sets up the CA bundle before aiohttp loads)
from bot.activity_log import ActivityLog
from bot.assets import Assets
from bot.clock import Clock
from bot.config import Config, ConfigError, load_config
from bot.core import EXIT_CONFIG, EXIT_OK, BotCore
from bot.http import HttpClient
from bot.stats import StatsStore


class _HideStarletteHint(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "StarletteAdapter" not in record.getMessage()


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("twitchio.client").addFilter(_HideStarletteHint())


async def _serve(config: Config, *, console: bool) -> int:
    clock = Clock()
    log = ActivityLog(config.data_dir / "logs", clock, config.log_retention_days)
    try:
        stats = StatsStore(config.data_dir / "bot.db")
    except RuntimeError as exc:  # the database was written by a newer version of the bot
        print(f"Setup error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    if console:
        from bot.connectors.console import ConsoleConnector

        connector = ConsoleConnector(clock=clock)
    else:
        from bot.connectors.twitch import TwitchConnector

        connector = TwitchConnector(config, log, clock)
    core = BotCore(
        config=config,
        connector=connector,
        stats=stats,
        log=log,
        clock=clock,
        assets=Assets(),
        http=HttpClient(),
        rng=random.Random(),
    )
    def on_signal() -> None:
        if core.shutdown_by is None:
            core.request_shutdown("signal")
        else:  # a second Ctrl+C / SIGTERM while shutdown is stuck: leave now
            os._exit(EXIT_OK)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, on_signal)
    try:
        return await core.run()
    finally:
        stats.close()


async def _auth(config: Config) -> int:
    from bot.connectors.twitch import authorize

    user = await authorize(config)
    print(f"\nAuthorized as {user.login} (user id {user.user_id}).")
    print(f"Put this line in .env:  BOT_ID={user.user_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bot", description="Offline chat bot")
    parser.add_argument("mode", nargs="?", default="run", choices=["run", "auth", "console"])
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    args = parser.parse_args(argv)
    _setup_logging()

    env = {**dotenv_values(args.config.parent / ".env"), **os.environ}
    env = {k: v for k, v in env.items() if v is not None}
    try:
        if args.mode == "run":
            config = load_config(args.config, env)
        else:
            config = load_config(args.config, env, require_twitch=False)
            if args.mode == "auth" and not (config.client_id and config.client_secret):
                raise ConfigError("TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET must be set in .env")
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if args.mode == "auth":
        try:
            return asyncio.run(_auth(config))
        except ConfigError as exc:  # e.g. port 4343 already in use
            print(f"Setup error: {exc}", file=sys.stderr)
            return EXIT_CONFIG
    if args.mode == "console":
        config = dataclasses.replace(config, data_dir=config.data_dir / "console")
    return asyncio.run(_serve(config, console=args.mode == "console"))


if __name__ == "__main__":
    sys.exit(main())
