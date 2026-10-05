"""Loads config.toml (settings) and .env values (secrets) into one validated Config."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot.games import ALL_GAMES

_CHANNEL = re.compile(r"^[a-z0-9_]{3,25}$")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    client_id: str
    client_secret: str
    bot_id: str
    owner_ids: frozenset[str]
    channel: str
    prefix: str
    user_cooldown: float
    global_cooldown: float
    enabled_games: tuple[str, ...]
    max_games: int
    game_cooldown: float
    busy_queue: int
    outbox_rate: float
    outbox_burst: int
    outbox_max_queue: int
    log_retention_days: int
    data_dir: Path


def _get(table: Mapping[str, Any], dotted: str, default: Any) -> Any:
    node: Any = table
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return default
        node = node[part]
    return node


def _number(table: Mapping[str, Any], key: str, default: float, *, integer: bool = False, minimum: float = 0) -> Any:
    value = _get(table, key, default)
    ok_type = isinstance(value, int) if integer else isinstance(value, (int, float))
    if isinstance(value, bool) or not ok_type or value < minimum:
        kind = "an integer" if integer else "a number"
        raise ConfigError(f"{key} must be {kind} >= {minimum}, got {value!r}")
    return value


def load_config(path: Path, env: Mapping[str, str], *, require_twitch: bool = True) -> Config:
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from None

    channel = str(_get(table, "channel", "")).strip().lower()
    if not _CHANNEL.fullmatch(channel):
        raise ConfigError(f"channel must be a Twitch username, got {channel!r}")

    prefix = _get(table, "prefix", "?")
    if not isinstance(prefix, str) or not 1 <= len(prefix) <= 3 or any(c.isspace() for c in prefix):
        raise ConfigError(f"prefix must be 1-3 non-space characters, got {prefix!r}")

    enabled = _get(table, "games.enabled", list(ALL_GAMES))
    if not isinstance(enabled, list) or not all(isinstance(g, str) for g in enabled):
        raise ConfigError("games.enabled must be a list of game names")
    unknown = [g for g in enabled if g not in ALL_GAMES]
    if unknown:
        raise ConfigError(f"games.enabled has unknown games: {', '.join(unknown)} (known: {', '.join(ALL_GAMES)})")

    client_id = env.get("TWITCH_CLIENT_ID", "").strip()
    client_secret = env.get("TWITCH_CLIENT_SECRET", "").strip()
    bot_id = env.get("BOT_ID", "").strip()
    if require_twitch:
        required = {"TWITCH_CLIENT_ID": client_id, "TWITCH_CLIENT_SECRET": client_secret, "BOT_ID": bot_id}
        for key, value in required.items():
            if not value:
                raise ConfigError(f"{key} is missing from .env")
        if not bot_id.isdigit():
            raise ConfigError(f"BOT_ID must be a numeric Twitch user ID, got {bot_id!r}")
    owner_ids = frozenset(part.strip() for part in env.get("OWNER_IDS", "").split(",") if part.strip())

    return Config(
        client_id=client_id,
        client_secret=client_secret,
        bot_id=bot_id or "console-bot",
        owner_ids=owner_ids,
        channel=channel,
        prefix=prefix,
        user_cooldown=_number(table, "cooldowns.user_seconds", 10),
        global_cooldown=_number(table, "cooldowns.global_seconds", 5),
        enabled_games=tuple(enabled),
        max_games=_number(table, "games.max_running", 25, integer=True, minimum=1),
        game_cooldown=_number(table, "games.cooldown_seconds", 10),
        busy_queue=_number(table, "games.busy_queue", 10, integer=True, minimum=1),
        outbox_rate=_number(table, "outbox.rate_per_second", 2, minimum=0.1),
        outbox_burst=_number(table, "outbox.burst", 3, integer=True, minimum=1),
        outbox_max_queue=_number(table, "outbox.max_queue", 30, integer=True, minimum=1),
        log_retention_days=_number(table, "logs.retention_days", 30, integer=True, minimum=1),
        data_dir=path.parent / "data",
    )
