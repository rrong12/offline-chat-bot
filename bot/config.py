"""Loads config.toml (settings) and .env values (secrets) into one validated Config."""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from bot.games import ALL_GAMES

_CHANNEL = re.compile(r"^[a-z0-9_]{3,25}$")
MAX_SEND_RATE = 3.0  # messages/s; Twitch allows a mod account about 100 per 30 s
PLACEHOLDER_CHANNEL = "your_channel"  # the value shipped in config.toml

# Every setting config.toml may contain. Anything else is almost certainly a typo.
_SCHEMA: dict[str, set[str] | None] = {
    "channel": None,
    "prefix": None,
    "cooldowns": {"user_seconds", "global_seconds"},
    "games": {"enabled", "max_running", "cooldown_seconds", "busy_queue"},
    "outbox": {"rate_per_second", "burst", "max_queue"},
    "logs": {"retention_days"},
    "rng": {"meme_badges"},
}


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
    rng_meme_badges: bool = True  # ?rng's 69/420 badges


def _get(table: Mapping[str, Any], dotted: str, default: Any) -> Any:
    node: Any = table
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return default
        node = node[part]
    return node


def _check_schema(table: Mapping[str, Any]) -> None:
    for key, value in table.items():
        if key not in _SCHEMA:
            raise ConfigError(f"unknown setting {key!r} (known: {', '.join(_SCHEMA)})")
        allowed = _SCHEMA[key]
        if allowed is None:
            continue
        if not isinstance(value, Mapping):
            raise ConfigError(f"{key} must be a [{key}] section, got {value!r}")
        for sub_key in value:
            if sub_key not in allowed:
                raise ConfigError(f"unknown setting {key}.{sub_key} (known: {', '.join(sorted(allowed))})")


def _number(
    table: Mapping[str, Any],
    key: str,
    default: float,
    *,
    integer: bool = False,
    minimum: float = 0,
    maximum: float = math.inf,
) -> Any:
    value = _get(table, key, default)
    ok_type = isinstance(value, int) if integer else isinstance(value, (int, float))
    if isinstance(value, bool) or not ok_type or not math.isfinite(value) or not minimum <= value <= maximum:
        kind = "an integer" if integer else "a number"
        limits = f">= {minimum}" if maximum == math.inf else f"between {minimum} and {maximum}"
        raise ConfigError(f"{key} must be {kind} {limits}, got {value!r}")
    return value


def load_config(path: Path, env: Mapping[str, str], *, require_twitch: bool = True) -> Config:
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from None

    _check_schema(table)

    raw_channel = _get(table, "channel", "")
    channel = raw_channel.strip().lower() if isinstance(raw_channel, str) else ""
    if not _CHANNEL.fullmatch(channel):
        raise ConfigError(f"channel must be a Twitch username, got {raw_channel!r}")
    if require_twitch and channel == PLACEHOLDER_CHANNEL:  # console mode and auth work before it's set
        raise ConfigError("set channel in config.toml to the Twitch channel the bot should join")

    prefix = _get(table, "prefix", "?")
    if not isinstance(prefix, str) or not 1 <= len(prefix) <= 3 or any(c.isspace() for c in prefix):
        raise ConfigError(f"prefix must be 1-3 non-space characters, got {prefix!r}")
    if prefix[0] in "/.":
        raise ConfigError(f"prefix can't start with '/' or '.' (Twitch's own commands), got {prefix!r}")

    enabled = _get(table, "games.enabled", list(ALL_GAMES))
    if not isinstance(enabled, list) or not all(isinstance(g, str) for g in enabled):
        raise ConfigError("games.enabled must be a list of game names")
    unknown = [g for g in enabled if g not in ALL_GAMES]
    if unknown:
        raise ConfigError(f"games.enabled has unknown games: {', '.join(unknown)} (known: {', '.join(ALL_GAMES)})")
    if not enabled:
        raise ConfigError(f"games.enabled must list at least one game (known: {', '.join(ALL_GAMES)})")
    enabled = list(dict.fromkeys(enabled))  # drop duplicates, keep order

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
    if require_twitch:
        bad = sorted(o for o in owner_ids if not o.isdigit())
        if bad:
            raise ConfigError(f"OWNER_IDS must be numeric Twitch user IDs, got {', '.join(bad)}")

    config = Config(
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
        outbox_rate=_number(table, "outbox.rate_per_second", 2, minimum=0.1, maximum=MAX_SEND_RATE),
        outbox_burst=_number(table, "outbox.burst", 3, integer=True, minimum=1),
        outbox_max_queue=_number(table, "outbox.max_queue", 30, integer=True, minimum=1),
        log_retention_days=_number(table, "logs.retention_days", 30, integer=True, minimum=1),
        data_dir=path.parent / "data",
    )
    meme_badges = _get(table, "rng.meme_badges", True)
    if not isinstance(meme_badges, bool):
        raise ConfigError(f"rng.meme_badges must be true or false, got {meme_badges!r}")
    config = replace(config, rng_meme_badges=meme_badges)
    if config.busy_queue > config.outbox_max_queue:
        raise ConfigError(
            f"games.busy_queue ({config.busy_queue}) can't be larger than outbox.max_queue ({config.outbox_max_queue})"
        )
    return config
