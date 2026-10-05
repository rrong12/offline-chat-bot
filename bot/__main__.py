"""Command line: `python -m bot` (run on Twitch), `python -m bot auth`, `python -m bot console`."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import os
import random
import signal
import sqlite3
import sys
from pathlib import Path

from dotenv import dotenv_values

from bot import certs
from bot.activity_log import ActivityLog
from bot.assets import Assets
from bot.clock import Clock
from bot.config import Config, ConfigError, load_config
from bot.core import EXIT_CONFIG, BotCore
from bot.http import HttpClient
from bot.stats import DatabaseTooNew, StatsStore

logger = logging.getLogger("bot")
EXIT_INTERRUPTED = 130  # Ctrl+C before the bot finished starting


class _HideStarletteHint(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "StarletteAdapter" not in record.getMessage()


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("twitchio.client").addFilter(_HideStarletteHint())
    if certs.USING_CERTIFI:
        logger.info("Python has no CA bundle here; using certifi's")


async def _serve(config: Config, *, console: bool) -> int:
    clock = Clock()
    try:
        log = ActivityLog(config.data_dir / "logs", clock, config.log_retention_days)
        stats = StatsStore(config.data_dir / "bot.db")
    except (DatabaseTooNew, OSError, sqlite3.DatabaseError) as exc:  # bad data folder or database
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
    signals = 0

    def on_signal() -> None:
        nonlocal signals
        signals += 1
        if signals == 1:
            core.request_shutdown("signal")
            return
        print("Second signal: exiting now.", file=sys.stderr)  # shutdown is stuck; leave now
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass
        os._exit(core.exit_code)

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

    try:
        file_env = dotenv_values(args.config.parent / ".env")
    except OSError as exc:
        print(f"Config error: can't read .env: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    # Real environment variables win, but only if they have a value.
    env = {k: v for k, v in file_env.items() if v} | {k: v for k, v in os.environ.items() if v}
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

    try:
        if args.mode == "auth":
            try:
                return asyncio.run(_auth(config))
            except ConfigError as exc:  # e.g. port 4343 in use, or Twitch rejected the app login
                print(f"Setup error: {exc}", file=sys.stderr)
                return EXIT_CONFIG
        if args.mode == "console":
            config = dataclasses.replace(config, data_dir=config.data_dir / "console")
        return asyncio.run(_serve(config, console=args.mode == "console"))
    except KeyboardInterrupt:  # Ctrl+C before the signal handlers were installed
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
