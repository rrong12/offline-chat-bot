# Offline Chat Bot Phase 3 (?rng) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `?rng`: one roll per person per UTC day, scored by rarity badges, counting on the main leaderboard.

**Architecture:** A pure badge module (`bot/rng.py`) scores numbers; migration 2 stores rolls; each roll also writes an `rng` round so existing leaderboard queries include it. A config switch turns the meme badges off.

**Tech Stack:** Python 3.12, pytest + pytest-asyncio, SQLite, the existing bot packages.

**Spec:** `docs/superpowers/specs/2026-10-04-offline-chat-bot-phase3-design.md`

---

## Conventions

- Work in the repo root with the project venv (`.venv/bin/python`, `.venv/bin/pytest`). Lint with
  `ruff check --select F,E,W,B,I --line-length 120 bot tests scripts` if ruff is available.
- Every code step gives the **whole file**. Write it exactly; where a file already exists, replace
  it completely. The code was run and tested before this plan was written.
- Commit after each task with the message given, and never add AI attribution to commits.
- Text the bot posts never repeats what a user typed, and content never contains blocked words
  (`content/blocked_prose_rot13.txt`, checked by `BlockedWords`).

## File map

| File | Task |
|---|---|
| `README.md` | 4 |
| `bot/config.py` | 1 |
| `bot/core.py` | 4 |
| `bot/rng.py` | 3 |
| `bot/stats.py` | 2 |
| `config.toml` | 1 |
| `tests/test_config.py` | 1 |
| `tests/test_flows.py` | 4 |
| `tests/test_rng.py` | 3 |
| `tests/test_stats.py` | 2 |

### Task 1: The meme-badge switch

**Files:**
- Replace: `tests/test_config.py`, `bot/config.py`, `config.toml`

Spec §2: `[rng] meme_badges` in `config.toml` (default `true`) turns the 69 and 420 badges on or off without a code change. Anything but a boolean is a config error naming the key.

- [ ] **Step 1: Write `tests/test_config.py`**

```python
from pathlib import Path

import pytest

from bot.config import ConfigError, load_config

ENV = {"TWITCH_CLIENT_ID": "cid", "TWITCH_CLIENT_SECRET": "secret", "BOT_ID": "123", "OWNER_IDS": "1, 2,"}


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_repo_config_file_is_valid_once_a_channel_is_set(tmp_path):
    shipped = (Path(__file__).parent.parent / "config.toml").read_text(encoding="utf-8")
    with pytest.raises(ConfigError, match="set channel"):
        load_config(write(tmp_path, shipped), ENV)  # the placeholder must be replaced
    load_config(write(tmp_path, shipped), {}, require_twitch=False)  # console mode works before it's set
    cfg = load_config(write(tmp_path, shipped.replace('"your_channel"', '"real_channel"')), ENV)
    assert cfg.prefix == "?" and cfg.enabled_games == ("scramble", "hangman", "trivia", "riddle", "higherlower")


def test_defaults_and_env(tmp_path):
    cfg = load_config(write(tmp_path, 'channel = "Robert_Channel"\n'), ENV)
    assert cfg.channel == "robert_channel"
    assert cfg.owner_ids == frozenset({"1", "2"})
    assert (cfg.user_cooldown, cfg.global_cooldown) == (10, 5)
    assert (cfg.max_games, cfg.game_cooldown, cfg.busy_queue) == (25, 10, 10)
    assert (cfg.outbox_rate, cfg.outbox_burst, cfg.outbox_max_queue) == (2, 3, 30)
    assert cfg.data_dir == tmp_path / "data"


@pytest.mark.parametrize(
    "toml, message",
    [
        ('channel = "no spaces allowed"', "channel"),
        ('channel = "ok_name"\nprefix = ""', "prefix"),
        ('channel = "ok_name"\n[cooldowns]\nuser_seconds = -1', "cooldowns.user_seconds"),
        ('channel = "ok_name"\n[games]\nmax_running = 0', "games.max_running"),
        ('channel = "ok_name"\n[games]\nenabled = ["chess"]', "chess"),
        ('channel = "ok_name"\n[outbox]\nburst = 1.5', "outbox.burst"),
        ("channel = ", "not valid TOML"),
        ('channel = "ok_name"\n[games]\nmax_runing = 5', "unknown setting games.max_runing"),
        ('channel = "ok_name"\ngames = "oops"', "games must be a \\[games\\] section"),
        ('channel = "ok_name"\ncolour = "blue"', "unknown setting 'colour'"),
        ('channel = "ok_name"\n[outbox]\nrate_per_second = 1000', "outbox.rate_per_second"),
        ('channel = "ok_name"\n[outbox]\nrate_per_second = nan', "outbox.rate_per_second"),
        ('channel = "ok_name"\n[outbox]\nrate_per_second = inf', "outbox.rate_per_second"),
        ('channel = "ok_name"\nprefix = "/"', "can't start with"),
        ('channel = "ok_name"\nprefix = ".b"', "can't start with"),
        ('channel = "ok_name"\n[games]\nenabled = []', "at least one game"),
        ("channel = 123", "channel must be a Twitch username"),
        ('channel = "ok_name"\n[games]\nbusy_queue = 40', "can't be larger than outbox.max_queue"),
        ('channel = "ok_name"\n[rng]\nmeme_badges = "yes"', "rng.meme_badges must be true or false"),
    ],
)
def test_invalid_values_name_the_key(tmp_path, toml, message):
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, toml), ENV)


def test_missing_secrets_fail_only_when_twitch_required(tmp_path):
    path = write(tmp_path, 'channel = "ok_name"\n')
    with pytest.raises(ConfigError, match="TWITCH_CLIENT_ID"):
        load_config(path, {})
    assert load_config(path, {}, require_twitch=False).bot_id == "console-bot"


def test_owner_ids_must_be_numeric_for_twitch_but_not_console(tmp_path):
    path = write(tmp_path, 'channel = "ok_name"\n')
    with pytest.raises(ConfigError, match="OWNER_IDS"):
        load_config(path, {**ENV, "OWNER_IDS": "123,robert"})
    assert load_config(path, {"OWNER_IDS": "console-robert"}, require_twitch=False).owner_ids == {"console-robert"}


def test_duplicate_games_are_dropped(tmp_path):
    cfg = load_config(write(tmp_path, 'channel = "ok_name"\n[games]\nenabled = ["scramble", "scramble"]'), ENV)
    assert cfg.enabled_games == ("scramble",)


def test_bot_id_must_be_numeric(tmp_path):
    with pytest.raises(ConfigError, match="BOT_ID"):
        load_config(write(tmp_path, 'channel = "ok_name"\n'), {**ENV, "BOT_ID": "mybot"})


def test_rng_meme_badges_default_on_and_can_be_turned_off(tmp_path):
    assert load_config(write(tmp_path, 'channel = "ok_name"'), ENV).rng_meme_badges is True
    off = load_config(write(tmp_path, 'channel = "ok_name"\n[rng]\nmeme_badges = false'), ENV)
    assert off.rng_meme_badges is False
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/bin/pytest tests/test_config.py -q`
Expected: the new tests fail (`unknown setting 'rng'`).

- [ ] **Step 3: Write `bot/config.py`**

```python
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
```

- [ ] **Step 4: Write `config.toml`**

```toml
# Non-secret settings. Secrets (client id/secret, bot id, owner ids) live in .env.

channel = "your_channel"   # the Twitch channel to join; change to "jasontheween" to go live there
prefix = "?"

[cooldowns]
user_seconds = 10           # per person, per command
global_seconds = 5          # per command, across the whole chat (not for games, ?cookie, ?gamestats, ?help)

[games]
enabled = ["scramble", "hangman", "trivia", "riddle", "higherlower"]
max_running = 25            # personal games running at once, across the whole chat
cooldown_seconds = 10       # per person, after their game ends
busy_queue = 10             # refuse new games while this many bot messages are waiting to send

[outbox]
rate_per_second = 2         # sustained sending rate (a mod account may send about 3/s)
burst = 3                   # messages that can go out back to back
max_queue = 30              # extra messages beyond this are dropped and logged

[logs]
retention_days = 30

[rng]
meme_badges = true          # ?rng's 69 and 420 badges; false turns them off
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_config.py -q`, then `.venv/bin/pytest -q`.
Expected: `26 passed`, then the whole suite passes (454 passed).

- [ ] **Step 6: Commit**

```bash
git add tests/test_config.py bot/config.py config.toml
git commit -m "Phase 3: [rng] meme_badges setting"
```

### Task 2: Roll storage (migration 2)

**Files:**
- Replace: `tests/test_stats.py`, `bot/stats.py`

Spec §3. Migration 2 adds `rng_rolls(user_id, utc_date, number, score, badges_json, rolled_at)` with primary key `(user_id, utc_date)`, so a second roll the same day can't be stored. `record_rng_roll` writes the roll and an `rng` round (outcome `won`, no win counted, points = score) in one transaction, which is how rng points reach `?leaderboard` and `?gamestats`; a test forces the round insert to fail and checks the roll was rolled back with it. Ties in the top lists go to whoever rolled first (`rolled_at`, a column the spec's table didn't list). An existing version-1 database upgrades in place.

- [ ] **Step 1: Write `tests/test_stats.py`**

```python
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot import stats as stats_module
from bot.stats import GameStats, PlayerResult, RoundRecord, StatsStore

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store():
    s = StatsStore(":memory:")
    s.touch_user("u1", "alice", "Alice", T0)
    yield s
    s.close()


def count(store: StatsStore, table: str) -> int:
    return store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def player(uid: str, points: int = 0, won: bool = False) -> PlayerResult:
    return PlayerResult(uid, f"user_{uid}", f"User_{uid}", points, won)


def record(store: StatsStore, game: str, players: list[PlayerResult], outcome: str = "won") -> int:
    return store.record_round(
        RoundRecord(game, "animals", "u1", T0, T0 + timedelta(seconds=30), outcome, players)
    )


def test_migrations_create_schema_and_are_idempotent(tmp_path: Path):
    path = tmp_path / "bot.db"
    StatsStore(path).close()
    again = StatsStore(path)
    assert again.schema_version() == 2
    again.close()


def test_version_1_database_upgrades_and_keeps_its_data(tmp_path: Path, monkeypatch):
    path = tmp_path / "bot.db"
    monkeypatch.setattr(stats_module, "MIGRATIONS", stats_module.MIGRATIONS[:1])
    old = StatsStore(path)
    old.set_state("paused", "1")
    old.close()
    monkeypatch.undo()
    s = StatsStore(path)
    assert s.schema_version() == 2 and s.get_state("paused") == "1"
    assert s.top_rng_rolls(None, 5) == []
    s.close()


def test_failed_migration_rolls_back_completely(tmp_path: Path, monkeypatch):
    broken = "CREATE TABLE first_table (x INTEGER); CREATE TABLE broken ("
    monkeypatch.setattr(stats_module, "MIGRATIONS", [stats_module.MIGRATIONS[0], broken])
    path = tmp_path / "bot.db"
    with pytest.raises(sqlite3.Error):
        StatsStore(path)
    monkeypatch.setattr(stats_module, "MIGRATIONS", stats_module.MIGRATIONS[:1])
    s = StatsStore(path)  # migration 1 committed, migration 2 left nothing behind
    assert s.schema_version() == 1
    tables = {r[0] for r in s._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "first_table" not in tables
    s.close()


def test_database_newer_than_code_is_refused(tmp_path: Path):
    path = tmp_path / "bot.db"
    s = StatsStore(path)
    with s._conn:
        s._conn.execute("UPDATE schema_version SET version = 99")
    s.close()
    with pytest.raises(RuntimeError, match="newer than this code"):
        StatsStore(path)


def test_touch_and_find_user_case_insensitive(store: StatsStore):
    assert store.find_user("ALICE").user_id == "u1"
    assert store.find_user("nobody") is None


def test_touch_user_updates_renamed_login(store: StatsStore):
    store.touch_user("u1", "alice_new", "Alice_New", T0 + timedelta(days=1))
    assert store.find_user("alice_new").display_name == "Alice_New"


def test_find_user_prefers_most_recent_owner_of_a_login(store: StatsStore):
    store.touch_user("old", "bob", "Bob", T0)  # renamed away later, but never seen again
    store.touch_user("new", "bob", "Bob", T0 + timedelta(days=30))  # took the name "bob"
    assert store.find_user("bob").user_id == "new"


def test_record_round_upserts_players_and_returns_id(store: StatsStore):
    rid = record(store, "scramble", [player("u2", 10, True), player("u3")])
    assert rid == 1
    assert store.find_user("user_u2").user_id == "u2"


def test_record_round_with_unknown_starter_writes_nothing(store: StatsStore):
    rec = RoundRecord("scramble", None, "nobody", T0, T0, "won", [player("u2", 10, True)])
    with pytest.raises(sqlite3.IntegrityError):
        store.record_round(rec)
    assert count(store, "rounds") == 0 and count(store, "round_players") == 0
    assert store.find_user("user_u2") is None  # the player upsert was rolled back too


def test_record_round_with_bad_outcome_writes_nothing(store: StatsStore):
    with pytest.raises(sqlite3.IntegrityError):
        record(store, "scramble", [player("u2", 10, True)], outcome="exploded")
    assert count(store, "rounds") == 0 and count(store, "round_players") == 0


def test_leaderboard_orders_by_points_then_wins_then_login(store: StatsStore):
    record(store, "scramble", [player("b", 10, True)])
    record(store, "scramble", [player("a", 10, True)])
    record(store, "hangman", [player("c", 7, False), player("d", 0)])
    rows = store.leaderboard(None, 10)
    assert [r.user_id for r in rows] == ["a", "b", "c"]  # d has 0 points and is left out
    assert [r.user_id for r in store.leaderboard("hangman", 10)] == ["c"]
    assert len(store.leaderboard(None, 2)) == 2


def test_leaderboard_ties_on_points_go_to_more_wins(store: StatsStore):
    record(store, "scramble", [player("aaa", 5, False)])
    record(store, "scramble", [player("aaa", 5, False)])
    record(store, "scramble", [player("zzz", 10, True)])
    assert [r.user_id for r in store.leaderboard(None, 10)] == ["zzz", "aaa"]  # same points, zzz has a win
    assert store.rank("aaa", None) == 2


def test_user_stats_per_game_and_rank(store: StatsStore):
    record(store, "scramble", [player("a", 10, True), player("b")])
    record(store, "scramble", [player("b", 7, True)])
    record(store, "hangman", [player("a", 3)], outcome="lost")
    assert store.user_stats("a") == [GameStats("scramble", 1, 1, 10), GameStats("hangman", 1, 0, 3)]
    assert store.rank("a", "scramble") == 1
    assert store.rank("b", "scramble") == 2
    assert store.rank("zzz", "scramble") is None
    assert store.rank("a", None) == 1  # 13 points overall
    record(store, "hangman", [player("z", 0)], outcome="lost")
    assert store.rank("z", "hangman") is None  # played, but no points


def test_iso_timestamps_are_stored_in_utc(store: StatsStore):
    eastern = timezone(timedelta(hours=-5))
    store.touch_user("u9", "late", "Late", datetime(2026, 10, 4, 22, 0, tzinfo=eastern))
    row = store._conn.execute("SELECT last_seen FROM users WHERE user_id = 'u9'").fetchone()
    assert row[0] == "2026-10-05T03:00:00Z"


def test_claim_daily_only_once_per_day(store: StatsStore):
    assert store.claim_daily("u1", "cookie", "2026-10-04", "fortune A")
    assert not store.claim_daily("u1", "cookie", "2026-10-04", "fortune B")
    assert store.get_daily("u1", "cookie", "2026-10-04") == "fortune A"
    assert store.claim_daily("u1", "cookie", "2026-10-05", "fortune C")


def test_state_round_trip_survives_reopen(tmp_path: Path):
    path = tmp_path / "bot.db"
    s = StatsStore(path)
    assert s.get_state("paused", "0") == "0"
    s.set_state("paused", "1")
    s.close()
    reopened = StatsStore(path)
    assert reopened.get_state("paused") == "1"
    reopened.close()


def test_file_database_uses_wal_with_normal_sync(tmp_path: Path):
    s = StatsStore(tmp_path / "bot.db")
    assert s._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert s._conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL


def _player(uid="u1", points=45):
    from bot.stats import PlayerResult

    return PlayerResult(uid, uid, uid.upper(), points, False)


def test_rng_roll_once_per_day_and_counts_on_the_leaderboard(store: StatsStore):
    assert store.record_rng_roll(_player(points=45), "2026-10-05", 123321, ["Palindrome", "Prime"], T0)
    assert not store.record_rng_roll(_player(points=100), "2026-10-05", 0, ["Zero"], T0)  # already rolled
    roll = store.rng_roll("u1", "2026-10-05")
    assert (roll.number, roll.score, roll.badges, roll.display_name) == (123321, 45, ["Palindrome", "Prime"], "U1")
    assert store.rng_roll("u1", "2026-10-06") is None
    board = store.leaderboard("rng", 5)
    assert [(r.user_id, r.points, r.wins) for r in board] == [("u1", 45, 0)]
    assert store.leaderboard(None, 5)[0].points == 45
    assert [(g.game, g.played) for g in store.user_stats("u1")] == [("rng", 1)]


def test_rng_top_and_best(store: StatsStore):
    store.record_rng_roll(_player("u1", 5), "2026-10-05", 7, ["Prime"], T0)
    store.record_rng_roll(_player("u2", 40), "2026-10-05", 524288, ["Power of two"], T0 + timedelta(minutes=1))
    store.record_rng_roll(_player("u3", 40), "2026-10-05", 1337, ["1337"], T0 + timedelta(minutes=2))
    store.record_rng_roll(_player("u1", 155), "2026-10-06", 0, ["Zero"], T0 + timedelta(days=1))
    today = store.top_rng_rolls("2026-10-05", 5)
    assert [(r.user_id, r.score) for r in today] == [("u2", 40), ("u3", 40), ("u1", 5)]  # tie: earlier first
    assert [r.user_id for r in store.top_rng_rolls(None, 2)] == ["u1", "u2"]
    assert store.best_rng_roll("u1").number == 0
    assert store.best_rng_roll("nobody") is None


def test_rng_roll_and_its_round_are_written_together(store: StatsStore):
    store._conn.execute("CREATE TRIGGER fail BEFORE INSERT ON rounds BEGIN SELECT RAISE(ABORT, 'boom'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.record_rng_roll(_player(points=45), "2026-10-05", 123321, ["Palindrome"], T0)
    store._conn.execute("DROP TRIGGER fail")
    assert store.rng_roll("u1", "2026-10-05") is None  # the roll was rolled back with its round
    assert store.record_rng_roll(_player(points=45), "2026-10-05", 123321, ["Palindrome"], T0)
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/bin/pytest tests/test_stats.py -q`
Expected: the new tests fail (`schema_version() == 1`, and `record_rng_roll` doesn't exist).

- [ ] **Step 3: Write `bot/stats.py`**

```python
"""SQLite storage: users, game rounds and players, daily uses, ?rng rolls, and persistent bot state."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS: list[str] = [
    """
    CREATE TABLE users (
      user_id      TEXT PRIMARY KEY,
      login        TEXT NOT NULL,
      display_name TEXT NOT NULL,
      last_seen    TEXT NOT NULL
    );
    CREATE INDEX users_login ON users(login);

    CREATE TABLE rounds (
      round_id    INTEGER PRIMARY KEY,
      game        TEXT NOT NULL,
      category    TEXT,
      started_by  TEXT NOT NULL REFERENCES users(user_id),
      started_at  TEXT NOT NULL,
      ended_at    TEXT NOT NULL,
      outcome     TEXT NOT NULL CHECK (outcome IN ('won','timeout','lost','skipped','stopped'))
    );

    CREATE TABLE round_players (
      round_id INTEGER NOT NULL REFERENCES rounds(round_id),
      user_id  TEXT NOT NULL REFERENCES users(user_id),
      points   INTEGER NOT NULL DEFAULT 0,
      won      INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (round_id, user_id)
    );

    CREATE TABLE daily_uses (
      user_id  TEXT NOT NULL,
      feature  TEXT NOT NULL,
      utc_date TEXT NOT NULL,
      result   TEXT,
      PRIMARY KEY (user_id, feature, utc_date)
    );

    CREATE TABLE bot_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);

    -- Covering index for per-user totals (leaderboards, ranks, ?gamestats); game filter.
    CREATE INDEX round_players_user ON round_players(user_id, points, won);
    CREATE INDEX rounds_game ON rounds(game);
    """,
    """
    -- ?rng: one roll per user per UTC day. Its points also go into rounds as game 'rng'.
    CREATE TABLE rng_rolls (
      user_id     TEXT NOT NULL REFERENCES users(user_id),
      utc_date    TEXT NOT NULL,
      number      INTEGER NOT NULL,
      score       INTEGER NOT NULL,
      badges_json TEXT NOT NULL,
      rolled_at   TEXT NOT NULL,
      PRIMARY KEY (user_id, utc_date)
    );
    CREATE INDEX rng_rolls_day ON rng_rolls(utc_date, score);
    CREATE INDEX rng_rolls_score ON rng_rolls(score);
    """,
]


class DatabaseTooNew(RuntimeError):
    """The database was written by a newer version of the bot."""


@dataclass(frozen=True)
class UserRow:
    user_id: str
    login: str
    display_name: str


@dataclass(frozen=True)
class PlayerResult:
    user_id: str
    login: str
    display_name: str
    points: int
    won: bool


@dataclass(frozen=True)
class RoundRecord:
    game: str
    category: str | None
    started_by: str
    started_at: datetime
    ended_at: datetime
    outcome: str
    players: list[PlayerResult]


@dataclass(frozen=True)
class LeaderRow:
    user_id: str
    login: str
    display_name: str
    points: int
    wins: int


@dataclass(frozen=True)
class RngRoll:
    user_id: str
    display_name: str
    utc_date: str
    number: int
    score: int
    badges: list[str]


@dataclass(frozen=True)
class GameStats:
    game: str
    played: int
    wins: int
    points: int


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StatsStore:
    def __init__(self, path: Path | str) -> None:
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")  # safe with WAL; every command commits
        self._migrate()

    def _migrate(self) -> None:
        with self._conn:
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            if self._conn.execute("SELECT version FROM schema_version").fetchone() is None:
                self._conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        version = self.schema_version()
        if version > len(MIGRATIONS):
            self._conn.close()
            raise DatabaseTooNew(
                f"database schema is version {version}, newer than this code (version {len(MIGRATIONS)})"
            )
        for number, sql in enumerate(MIGRATIONS[version:], start=version + 1):
            # sqlite3 doesn't wrap CREATE statements in a transaction by itself, so BEGIN/COMMIT
            # make each migration all-or-nothing; on an error, the `with` block rolls it back.
            with self._conn:
                self._conn.executescript(f"BEGIN;\n{sql}\nUPDATE schema_version SET version = {number};\nCOMMIT;")

    def schema_version(self) -> int:
        return self._conn.execute("SELECT version FROM schema_version").fetchone()["version"]

    def close(self) -> None:
        self._conn.close()

    # users

    def touch_user(self, user_id: str, login: str, display_name: str, now: datetime) -> None:
        with self._conn:
            self._upsert_user(user_id, login, display_name, now)

    def _upsert_user(self, user_id: str, login: str, display_name: str, now: datetime) -> None:
        self._conn.execute(
            """INSERT INTO users (user_id, login, display_name, last_seen) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 login = excluded.login, display_name = excluded.display_name, last_seen = excluded.last_seen""",
            (user_id, login.lower(), display_name, _iso(now)),
        )

    def find_user(self, login: str) -> UserRow | None:
        row = self._conn.execute(
            "SELECT user_id, login, display_name FROM users WHERE login = ? ORDER BY last_seen DESC LIMIT 1",
            (login.lower(),),
        ).fetchone()
        return UserRow(row["user_id"], row["login"], row["display_name"]) if row else None

    # rounds

    def record_round(self, rec: RoundRecord) -> int:
        """Write a finished round and its players in one transaction. Returns the round id.

        Players' user rows are upserted here, before the round row, so a starter who is also a
        player (always true for personal games) needs no separate user row.
        """
        with self._conn:
            for p in rec.players:
                self._upsert_user(p.user_id, p.login, p.display_name, rec.ended_at)
            cur = self._conn.execute(
                """INSERT INTO rounds (game, category, started_by, started_at, ended_at, outcome)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (rec.game, rec.category, rec.started_by, _iso(rec.started_at), _iso(rec.ended_at), rec.outcome),
            )
            round_id = int(cur.lastrowid)
            self._conn.executemany(
                "INSERT INTO round_players (round_id, user_id, points, won) VALUES (?, ?, ?, ?)",
                [(round_id, p.user_id, p.points, int(p.won)) for p in rec.players],
            )
        return round_id

    @staticmethod
    def _totals_sql(game: str | None) -> str:
        """Per-user totals with points > 0, for all games or one (`:game`)."""
        if game is None:
            return """SELECT user_id, SUM(points) AS points, SUM(won) AS wins
                      FROM round_players GROUP BY user_id HAVING SUM(points) > 0"""
        return """SELECT rp.user_id, SUM(rp.points) AS points, SUM(rp.won) AS wins
                  FROM round_players rp JOIN rounds r ON r.round_id = rp.round_id
                  WHERE r.game = :game GROUP BY rp.user_id HAVING SUM(rp.points) > 0"""

    def leaderboard(self, game: str | None, limit: int) -> list[LeaderRow]:
        rows = self._conn.execute(
            f"""WITH t AS ({self._totals_sql(game)})
                SELECT t.user_id, u.login, u.display_name, t.points, t.wins
                FROM t JOIN users u ON u.user_id = t.user_id
                ORDER BY t.points DESC, t.wins DESC, u.login ASC
                LIMIT :limit""",
            {"game": game, "limit": max(0, limit)},
        ).fetchall()
        return [LeaderRow(r["user_id"], r["login"], r["display_name"], r["points"], r["wins"]) for r in rows]

    def rank(self, user_id: str, game: str | None) -> int | None:
        """1-based position on the leaderboard, or None if the user has no points there."""
        row = self._conn.execute(
            f"""WITH t AS ({self._totals_sql(game)}),
                ranked AS (
                  SELECT t.user_id,
                         ROW_NUMBER() OVER (ORDER BY t.points DESC, t.wins DESC, u.login ASC) AS position
                  FROM t JOIN users u ON u.user_id = t.user_id)
                SELECT position FROM ranked WHERE user_id = :user_id""",
            {"game": game, "user_id": user_id},
        ).fetchone()
        return row["position"] if row else None

    def user_stats(self, user_id: str) -> list[GameStats]:
        rows = self._conn.execute(
            """SELECT r.game, COUNT(*) AS played, SUM(rp.won) AS wins, SUM(rp.points) AS points
               FROM round_players rp JOIN rounds r ON r.round_id = rp.round_id
               WHERE rp.user_id = ?
               GROUP BY r.game
               ORDER BY points DESC, r.game ASC""",
            (user_id,),
        ).fetchall()
        return [GameStats(r["game"], r["played"], r["wins"], r["points"]) for r in rows]

    # daily uses

    def claim_daily(self, user_id: str, feature: str, utc_date: str, result: str) -> bool:
        """Record today's use. Returns False if this user already used the feature today."""
        with self._conn:
            cur = self._conn.execute(
                """INSERT INTO daily_uses (user_id, feature, utc_date, result) VALUES (?, ?, ?, ?)
                   ON CONFLICT (user_id, feature, utc_date) DO NOTHING""",
                (user_id, feature, utc_date, result),
            )
        return cur.rowcount == 1

    def get_daily(self, user_id: str, feature: str, utc_date: str) -> str | None:
        row = self._conn.execute(
            "SELECT result FROM daily_uses WHERE user_id = ? AND feature = ? AND utc_date = ?",
            (user_id, feature, utc_date),
        ).fetchone()
        return row["result"] if row else None

    # ?rng

    def record_rng_roll(
        self, player: PlayerResult, utc_date: str, number: int, badges: list[str], now: datetime
    ) -> bool:
        """Store today's roll and its points (as an 'rng' round) together. False if already rolled today."""
        with self._conn:
            self._upsert_user(player.user_id, player.login, player.display_name, now)
            cur = self._conn.execute(
                """INSERT INTO rng_rolls (user_id, utc_date, number, score, badges_json, rolled_at)
                   VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (user_id, utc_date) DO NOTHING""",
                (player.user_id, utc_date, number, player.points, json.dumps(badges), _iso(now)),
            )
            if cur.rowcount != 1:
                return False
            round_cur = self._conn.execute(
                """INSERT INTO rounds (game, category, started_by, started_at, ended_at, outcome)
                   VALUES ('rng', NULL, ?, ?, ?, 'won')""",
                (player.user_id, _iso(now), _iso(now)),
            )
            self._conn.execute(
                "INSERT INTO round_players (round_id, user_id, points, won) VALUES (?, ?, ?, 0)",
                (int(round_cur.lastrowid), player.user_id, player.points),
            )
        return True

    _ROLL_COLUMNS = "r.user_id, u.display_name, r.utc_date, r.number, r.score, r.badges_json"

    @staticmethod
    def _roll(row: sqlite3.Row) -> RngRoll:
        return RngRoll(row["user_id"], row["display_name"], row["utc_date"], row["number"], row["score"],
                       json.loads(row["badges_json"]))

    def rng_roll(self, user_id: str, utc_date: str) -> RngRoll | None:
        row = self._conn.execute(
            f"""SELECT {self._ROLL_COLUMNS} FROM rng_rolls r JOIN users u ON u.user_id = r.user_id
                WHERE r.user_id = ? AND r.utc_date = ?""",
            (user_id, utc_date),
        ).fetchone()
        return self._roll(row) if row else None

    def best_rng_roll(self, user_id: str) -> RngRoll | None:
        row = self._conn.execute(
            f"""SELECT {self._ROLL_COLUMNS} FROM rng_rolls r JOIN users u ON u.user_id = r.user_id
                WHERE r.user_id = ? ORDER BY r.score DESC, r.rolled_at ASC LIMIT 1""",
            (user_id,),
        ).fetchone()
        return self._roll(row) if row else None

    def top_rng_rolls(self, utc_date: str | None, limit: int) -> list[RngRoll]:
        """Best single rolls by score, for one day or all time; ties go to whoever rolled first."""
        where = "WHERE r.utc_date = :day" if utc_date is not None else ""
        rows = self._conn.execute(
            f"""SELECT {self._ROLL_COLUMNS} FROM rng_rolls r JOIN users u ON u.user_id = r.user_id
                {where} ORDER BY r.score DESC, r.rolled_at ASC LIMIT :limit""",
            {"day": utc_date, "limit": max(0, limit)},
        ).fetchall()
        return [self._roll(r) for r in rows]

    # bot state

    def get_state(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT INTO bot_state (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key, value),
            )
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_stats.py -q`, then `.venv/bin/pytest -q`.
Expected: `20 passed`, then the whole suite passes (458 passed).

- [ ] **Step 5: Commit**

```bash
git add tests/test_stats.py bot/stats.py
git commit -m "Phase 3: rng_rolls table and roll storage"
```

### Task 3: Badges and the ?rng command

**Files:**
- Replace: `tests/test_rng.py`, `bot/rng.py`

Spec §1-2, with the tiers set by real rarity. The test counts every badge over all 1,000,001 numbers (about 4 s) and pins each badge's exact count and tier, and checks each tier is strictly rarer than the next. Measured, a few badges moved from the spec's draft lists: Round hundred-thousand (9 numbers) is legendary; Round ten-thousand (90), Palindrome and Perfect square (1,000 each) are rare; Ends in 00 (9,900) is uncommon; Contains 69 and Contains 67 (49,401 each) are common. "Palindrome (5 digits)" is called "Five-digit palindrome". Numbers are scored and shown as 6 digits with leading zeros ("rolled 001,337"), so the zeros that earn a badge are visible; 1,000,000 is the only 7-digit roll and earns Max.

- `?rng`: today's roll, or today's roll again plus the time until 00:00 UTC.
- `?rng me` / `?rng <user>`: today's roll and best ever; a name that isn't found is never echoed.
- `?rng today` / `?rng top`: the top 5 single rolls today or ever. Everyone gets the same reply, so each is limited to once per 5 s chat-wide.
- `?rng help` lists the forms. The time is read once per command, so a roll at midnight can't be checked on one day and stored on the next.
- It's a Fun-group command with only the per-user cooldown, so the busy brake applies.

- [ ] **Step 1: Write `tests/test_rng.py`**

```python
from collections import Counter

import pytest

from bot.clock import FakeClock
from bot.commands import CommandContext, CommandRegistry
from bot.rng import BADGES, MAX_ROLL, badges_for, register_rng, show
from bot.stats import StatsStore
from tests.helpers import make_msg

# Every badge's tier and exact count over all 1,000,001 numbers (measured; the tiers follow the counts).
EXPECTED = {
    "Zero": ("legendary", 1),
    "Max": ("legendary", 1),
    "Six of a kind": ("legendary", 9),
    "Straight": ("legendary", 10),
    "Round hundred-thousand": ("legendary", 9),
    "Nice nice nice": ("legendary", 1),
    "Blaze it": ("legendary", 1),
    "Power of two": ("rare", 20),
    "Fibonacci": ("rare", 29),
    "Round ten-thousand": ("rare", 90),
    "Perfect cube": ("rare", 100),
    "Five in a row": ("rare", 180),
    "1337": ("rare", 300),
    "Palindrome": ("rare", 1_000),
    "Perfect square": ("rare", 1_000),
    "Four in a row": ("uncommon", 2_610),
    "Contains 420": ("uncommon", 3_999),
    "Ends in 00": ("uncommon", 9_900),
    "All even digits": ("uncommon", 15_625),
    "All odd digits": ("uncommon", 15_625),
    "Five-digit palindrome": ("uncommon", 19_890),
    "Triple": ("common", 34_110),
    "Doubles": ("common", 47_160),
    "Lucky sum": ("common", 48_686),
    "Contains 69": ("common", 49_401),
    "Contains 67": ("common", 49_401),
    "Prime": ("common", 78_498),
}
MEME = {"Nice nice nice", "Blaze it", "Contains 420", "Contains 69"}


def names(number: int, meme: bool = True) -> set[str]:
    return {b.name for b in badges_for(number, meme)}


@pytest.mark.parametrize("number, expected", [
    (0, {"Zero", "Palindrome", "All even digits"}),
    (MAX_ROLL, {"Max", "Perfect cube", "Perfect square"}),
    (1, {"Power of two", "Fibonacci", "Perfect cube", "Perfect square", "Five in a row", "Five-digit palindrome"}),
    (7, {"Five in a row", "Five-digit palindrome", "Lucky sum", "Prime"}),
    (13, {"Fibonacci", "Prime", "Four in a row"}),  # 000013
    (1_337, {"1337", "Doubles"}),  # 001337: two different repeated pairs
    (1_039, {"Lucky sum", "Prime"}),
    (9_900, {"Palindrome", "Ends in 00", "Doubles"}),
    (10_000, {"Round ten-thousand", "Perfect square", "Four in a row"}),
    (12_345, {"Straight"}),  # 012345
    (50_000, {"Round ten-thousand", "Four in a row"}),
    (106_700, {"Ends in 00", "Contains 67"}),
    (111_222, {"Triple", "Doubles"}),
    (123_321, {"Palindrome"}),  # one repeated pair is not Doubles
    (123_456, {"Straight", "Lucky sum"}),  # 1+2+3+4+5+6 = 21
    (300_000, {"Round hundred-thousand", "Five in a row", "Five-digit palindrome"}),
    (482_193, set()),
    (524_288, {"Power of two"}),
    (777_777, {"Six of a kind", "Palindrome", "All odd digits"}),
    (864_202, {"All even digits", "Contains 420"}),
    (975_319, {"All odd digits"}),
    (987_654, {"Straight"}),
    (999_983, {"Four in a row", "Prime"}),
])
def test_badge_rules(number, expected):
    assert names(number) == expected


def test_meme_badges_can_be_turned_off():
    assert names(696_969) == {"Nice nice nice", "Contains 69", "Five-digit palindrome"}
    assert names(696_969, meme=False) == {"Five-digit palindrome"}
    assert names(420_420) == {"Blaze it", "Contains 420", "All even digits"}
    assert names(420_420, meme=False) == {"All even digits"}
    assert {b.name for b in BADGES if b.meme} == MEME


def test_badges_are_listed_highest_tier_first():
    points = [b.points for b in badges_for(0)]
    assert points == sorted(points, reverse=True) == [100, 40, 15]


def test_every_badge_has_its_measured_count_and_tier():
    counts = Counter(b.name for n in range(MAX_ROLL + 1) for b in badges_for(n))
    assert {b.name: (b.tier, counts[b.name]) for b in BADGES} == EXPECTED
    by_tier = {}
    for tier, count in EXPECTED.values():
        by_tier.setdefault(tier, []).append(count)
    # each tier is strictly rarer than the next
    assert max(by_tier["legendary"]) < min(by_tier["rare"])
    assert max(by_tier["rare"]) < min(by_tier["uncommon"])
    assert max(by_tier["uncommon"]) < min(by_tier["common"])


def test_rolls_show_six_digits():
    assert (show(1_337), show(13), show(140_891), show(MAX_ROLL)) == ("001,337", "000,013", "140,891", "1,000,000")


class FixedRng:
    def __init__(self, *numbers: int):
        self.numbers = list(numbers)

    def randint(self, low, high):
        return self.numbers.pop(0)


class Rng:
    def __init__(self, *numbers: int, meme: bool = True):
        self.clock = FakeClock()  # 2026-10-04 12:00 UTC
        self.stats = StatsStore(":memory:")
        self.registry = CommandRegistry("?")
        register_rng(self.registry, stats=self.stats, clock=self.clock, rng=FixedRng(*numbers), meme_badges=meme)
        self.replies: list[str] = []

    async def run(self, text: str, login: str = "alice") -> str | None:
        name, _, args = text.removeprefix("?").partition(" ")
        before = len(self.replies)
        ctx = CommandContext(make_msg(text, login), name, args, "?", lambda t, **kw: self.replies.append(t), None)
        await self.registry.get(name).handler(ctx)
        return self.replies[-1] if len(self.replies) > before else None


async def test_daily_roll_then_repeat_then_next_day():
    r = Rng(1_337, 482_193)
    assert await r.run("?rng") == "🎲 alice rolled 001,337 · 🏅 1337 (rare, 40) · 🏅 Doubles (common, 5) · 45 pts"
    assert await r.run("?rng") == "🎲 You already rolled 001,337 (45 pts) today. Next roll in 12h 0m (00:00 UTC)."
    r.clock.advance(12 * 3600)
    assert await r.run("?rng") == "🎲 alice rolled 482,193 · no badges this time"
    assert [(row.user_id, row.points) for row in r.stats.leaderboard("rng", 5)] == [("id-alice", 45)]


async def test_a_roll_stored_by_a_racing_message_is_shown(monkeypatch):
    from bot.stats import PlayerResult

    r = Rng(482_193)
    real = r.stats.record_rng_roll

    def racing(player, day, number, badges, now):
        real(PlayerResult("id-alice", "alice", "alice", 45, False), day, 1_337, ["1337", "Doubles"], now)
        return real(player, day, number, badges, now)  # the other message got there first: refused

    monkeypatch.setattr(r.stats, "record_rng_roll", racing)
    assert await r.run("?rng") == "🎲 You already rolled 001,337 (45 pts) today. Next roll in 12h 0m (00:00 UTC)."


async def test_me_other_user_and_unknown_user():
    r = Rng(1_337)
    assert await r.run("?rng me") == "You haven't rolled yet. Try ?rng."
    await r.run("?rng", "bob")
    assert await r.run("?rng me", "bob") == "🎲 bob: today 001,337 (45 pts) · best ever 001,337 (45 pts)"
    assert await r.run("?rng @Bob") == "🎲 bob: today 001,337 (45 pts) · best ever 001,337 (45 pts)"
    r.clock.advance(24 * 3600)
    assert await r.run("?rng bob") == "🎲 bob: no roll today yet · best ever 001,337 (45 pts)"
    assert await r.run("?rng some_troll_name") == "No rolls for that user yet."  # never echoed
    r.stats.touch_user("id-carol", "carol", "carol", r.clock.now())  # chatted, never rolled
    assert await r.run("?rng carol") == "No rolls for that user yet."
    assert await r.run("?rng help") == "Try ?rng, ?rng me, ?rng today, ?rng top or ?rng <username>."


async def test_today_and_top_with_a_chat_wide_limit():
    r = Rng(13, 0, 1_337)
    assert await r.run("?rng today") == "No rolls today."
    assert await r.run("?rng top") == "No rolls yet."
    await r.run("?rng", "alice")
    await r.run("?rng", "bob")
    await r.run("?rng", "carol")
    assert await r.run("?rng today", "dave") is None  # the same reply went out less than 5 s ago
    r.clock.advance(5)
    expected = "🎲 Today's best rolls: 1. bob 000,000 (155) 2. alice 000,013 (60) 3. carol 001,337 (45)"
    assert await r.run("?rng today", "dave") == expected
    r.clock.advance(24 * 3600)
    assert await r.run("?rng today") == "No rolls today."
    assert (await r.run("?rng top")).startswith("🎲 Best rolls ever: 1. bob 000,000 (155)")


async def test_meme_badges_off_changes_the_score():
    r = Rng(696_969, meme=False)
    assert await r.run("?rng") == "🎲 alice rolled 696,969 · 🏅 Five-digit palindrome (uncommon, 15) · 15 pts"
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/bin/pytest tests/test_rng.py -q`
Expected: `ModuleNotFoundError: No module named 'bot.rng'`.

- [ ] **Step 3: Write `bot/rng.py`**

```python
"""?rng: one roll per person per UTC day, from 0 to 1,000,000, scored by badges.

Badge tiers follow each badge's real rarity over all 1,000,001 numbers (see tests/test_rng.py):
legendary about 1 in 100,000 or rarer, rare 1 in 1,000 or rarer, uncommon up to about 1 in 40,
common the rest. Numbers are scored and shown as six digits with leading zeros ("001,337"), so the
zeros that earn a badge are visible. A roll earns every badge it matches; its score is the sum.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from functools import cache

from bot.clock import Clock
from bot.commands import Command, CommandContext, CommandRegistry
from bot.stats import PlayerResult, RngRoll, StatsStore
from bot.text import clean_username, format_duration

MAX_ROLL = 1_000_000
TOP_LIMIT = 5
SHARED_COOLDOWN = 5.0  # seconds: ?rng today/top give everyone the same reply, so they're limited chat-wide
TIER_POINTS = {"legendary": 100, "rare": 40, "uncommon": 15, "common": 5}
STRAIGHTS = {"012345", "123456", "234567", "345678", "456789", "987654", "876543", "765432", "654321", "543210"}


@dataclass(frozen=True)
class Badge:
    name: str
    tier: str
    test: Callable[[int, str], bool]  # (number, 6-digit string) -> earned
    meme: bool = False

    @property
    def points(self) -> int:
        return TIER_POINTS[self.tier]


@cache
def _primes() -> bytearray:
    sieve = bytearray([1]) * (MAX_ROLL + 1)
    sieve[0] = sieve[1] = 0
    for i in range(2, int(MAX_ROLL**0.5) + 1):
        if sieve[i]:
            sieve[i * i :: i] = bytearray(len(sieve[i * i :: i]))
    return sieve


def _fibonacci() -> frozenset[int]:
    numbers, a, b = {1}, 1, 2
    while b <= MAX_ROLL:
        numbers.add(b)
        a, b = b, a + b
    return frozenset(numbers)


FIBONACCI = _fibonacci()
SQUARES = frozenset(k * k for k in range(1, 1001))
CUBES = frozenset(k**3 for k in range(1, 101))
POWERS_OF_TWO = frozenset(2**k for k in range(21))


def _longest_run(s: str) -> int:
    best = current = 1
    for prev, ch in zip(s, s[1:], strict=False):
        current = current + 1 if ch == prev else 1
        best = max(best, current)
    return best


def _digit_sum(s: str) -> int:
    return sum(int(ch) for ch in s)


BADGES: tuple[Badge, ...] = (
    Badge("Zero", "legendary", lambda n, s: n == 0),
    Badge("Max", "legendary", lambda n, s: n == MAX_ROLL),
    Badge("Six of a kind", "legendary", lambda n, s: 0 < n < MAX_ROLL and len(set(s)) == 1),
    Badge("Straight", "legendary", lambda n, s: s in STRAIGHTS),
    Badge("Round hundred-thousand", "legendary", lambda n, s: 0 < n < MAX_ROLL and n % 100_000 == 0),
    Badge("Nice nice nice", "legendary", lambda n, s: n == 696_969, meme=True),
    Badge("Blaze it", "legendary", lambda n, s: n == 420_420, meme=True),
    Badge("Power of two", "rare", lambda n, s: n in POWERS_OF_TWO),
    Badge("Fibonacci", "rare", lambda n, s: n in FIBONACCI),
    Badge("Round ten-thousand", "rare", lambda n, s: n % 10_000 == 0 and n % 100_000 != 0),
    Badge("Perfect cube", "rare", lambda n, s: n in CUBES),
    Badge("Five in a row", "rare", lambda n, s: _longest_run(s) == 5),
    Badge("1337", "rare", lambda n, s: "1337" in s),
    Badge("Palindrome", "rare", lambda n, s: n < MAX_ROLL and s == s[::-1]),
    Badge("Perfect square", "rare", lambda n, s: n in SQUARES),
    Badge("Four in a row", "uncommon", lambda n, s: _longest_run(s) == 4),
    Badge("Contains 420", "uncommon", lambda n, s: "420" in s, meme=True),
    Badge("Ends in 00", "uncommon", lambda n, s: n % 100 == 0 and n % 10_000 != 0),
    Badge("All even digits", "uncommon", lambda n, s: all(ch in "02468" for ch in s)),
    Badge("All odd digits", "uncommon", lambda n, s: all(ch in "13579" for ch in s)),
    Badge(  # five of the six digits read the same backwards
        "Five-digit palindrome", "uncommon",
        lambda n, s: n < MAX_ROLL and s != s[::-1] and (s[:5] == s[4::-1] or s[1:] == s[:0:-1]),
    ),
    Badge("Triple", "common", lambda n, s: _longest_run(s) == 3),
    Badge("Doubles", "common", lambda n, s: len({a for a, b in zip(s, s[1:], strict=False) if a == b}) >= 2),
    Badge("Lucky sum", "common", lambda n, s: _digit_sum(s) in (7, 13, 21)),
    Badge("Contains 69", "common", lambda n, s: "69" in s, meme=True),
    Badge("Contains 67", "common", lambda n, s: "67" in s),
    Badge("Prime", "common", lambda n, s: bool(_primes()[n])),
)


def badges_for(number: int, meme_badges: bool = True) -> list[Badge]:
    """Every badge the number earns, highest tier first."""
    digits = f"{number:06d}"
    earned = [b for b in BADGES if (meme_badges or not b.meme) and b.test(number, digits)]
    return sorted(earned, key=lambda b: -b.points)


def show(number: int) -> str:
    """The roll as players see it: six digits, so leading zeros that earn badges are visible."""
    if number >= MAX_ROLL:
        return f"{number:,}"
    digits = f"{number:06d}"
    return f"{digits[:3]},{digits[3:]}"


def _describe(roll: RngRoll) -> str:
    return f"{show(roll.number)} ({roll.score} pts)"


def register_rng(
    registry: CommandRegistry, *, stats: StatsStore, clock: Clock, rng: random.Random, meme_badges: bool
) -> None:
    last_shared: dict[str, float] = {}  # "today"/"top" -> when that reply last went out (monotonic)

    def until_reset(now: datetime) -> str:
        midnight = datetime.combine(now.date() + timedelta(days=1), time(0), tzinfo=timezone.utc)
        return format_duration((midnight - now).total_seconds())

    def roll(ctx: CommandContext, now: datetime, day: str) -> None:
        uid = ctx.msg.user_id
        existing = stats.rng_roll(uid, day)
        if existing is None:
            number = rng.randint(0, MAX_ROLL)
            earned = badges_for(number, meme_badges)
            score = sum(b.points for b in earned)
            player = PlayerResult(uid, ctx.msg.login, ctx.msg.display_name, score, False)
            if stats.record_rng_roll(player, day, number, [b.name for b in earned], now):
                parts = [f"🏅 {b.name} ({b.tier}, {b.points})" for b in earned]
                tail = " · ".join([*parts, f"{score} pts"]) if earned else "no badges this time"
                ctx.reply(f"🎲 {ctx.msg.display_name} rolled {show(number)} · {tail}")
                return
            existing = stats.rng_roll(uid, day)  # rolled at the same moment in another message
        if existing is not None:
            wait = until_reset(now)
            ctx.reply(f"🎲 You already rolled {_describe(existing)} today. Next roll in {wait} (00:00 UTC).")

    def player_summary(user_id: str, name: str, day: str) -> str | None:
        best = stats.best_rng_roll(user_id)
        if best is None:
            return None
        current = stats.rng_roll(user_id, day)
        today_text = f"today {_describe(current)}" if current else "no roll today yet"
        return f"🎲 {name}: {today_text} · best ever {_describe(best)}"

    def top(day: str | None, label: str) -> str | None:
        key = "today" if day else "top"
        if clock.mono() - last_shared.get(key, -SHARED_COOLDOWN) < SHARED_COOLDOWN:
            return None
        last_shared[key] = clock.mono()
        rows = stats.top_rng_rolls(day, TOP_LIMIT)
        if not rows:
            return f"No rolls {'today' if day else 'yet'}."
        body = " ".join(f"{i}. {r.display_name} {show(r.number)} ({r.score})" for i, r in enumerate(rows, start=1))
        return f"🎲 {label}: {body}"

    async def rng_command(ctx: CommandContext) -> None:
        now = clock.now()  # read once, so a roll at midnight can't be checked on one day and stored on the next
        day = now.date().isoformat()
        arg = ctx.argv[0].lower() if ctx.argv else ""
        reply: str | None
        if not arg:
            roll(ctx, now, day)
            return
        if arg in ("today", "top"):
            reply = top(day if arg == "today" else None, "Today's best rolls" if arg == "today" else "Best rolls ever")
        elif arg == "me":
            reply = player_summary(ctx.msg.user_id, ctx.msg.display_name, day)
            reply = reply or f"You haven't rolled yet. Try {ctx.prefix}rng."
        elif arg == "help":
            reply = f"Try {ctx.prefix}rng, {ctx.prefix}rng me, {ctx.prefix}rng today, {ctx.prefix}rng top or " \
                    f"{ctx.prefix}rng <username>."
        else:
            login = clean_username(ctx.argv[0])
            user = stats.find_user(login) if login else None
            reply = player_summary(user.user_id, user.display_name, day) if user else None
            reply = reply or "No rolls for that user yet."  # never repeat the name the user typed
        if reply:
            ctx.reply(reply)

    registry.add(
        Command(
            "rng",
            rng_command,
            "{p}rng | {p}rng me|today|top|<username>",
            "Your daily roll from 0 to 1,000,000, scored by badges (points count on the leaderboard). "
            "Resets at 00:00 UTC.",
            "Fun",
            global_cooldown=False,  # personal: one person's roll never blocks another's
        )
    )
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_rng.py -q`, then `.venv/bin/pytest -q`.
Expected: `32 passed`, then the whole suite passes (490 passed).

- [ ] **Step 5: Commit**

```bash
git add tests/test_rng.py bot/rng.py
git commit -m "Phase 3: ?rng badges and commands"
```

### Task 4: Wire ?rng into the bot

**Files:**
- Replace: `tests/test_flows.py`, `bot/core.py`, `README.md`

`BotCore` registers `?rng` with the config's meme setting, and `rng` joins the game names `?leaderboard` and `?gamestats` accept. The flow tests roll with the seeded RNG, check the main leaderboard, and run `?rng <user>`, `today`, `top` and `me` through the bot; the help overview gains `?rng`.

- [ ] **Step 1: Write `tests/test_flows.py`**

```python
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
        "Fun: ?8ball ?coinflip ?catfact ?dogfact ?fact ?dadjoke ?cookie ?rng · ?help <command> for details"
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


async def test_rng_roll_counts_on_the_main_leaderboard(bot: Bot):
    await bot.say("alice: ?rng")  # the seeded RNG's first roll
    assert bot.out[-1] == "🎲 alice rolled 140,891 · 🏅 Prime (common, 5) · 5 pts"
    await bot.say("bob: ?gamestats alice")
    assert bot.out[-1] == "📊 alice: 5 pts, 0 wins, 1 played | rng 0W/1P 5pts"
    await bot.say("carol: ?leaderboard rng")
    assert bot.out[-1] == "🏆 Top 1 rng: 1. alice (5)"
    await bot.wait(6)  # ?leaderboard has a 5 s chat-wide cooldown
    await bot.say("dave: ?leaderboard")
    assert bot.out[-1] == "🏆 Top 1 overall: 1. alice (5)"


async def test_rng_subcommands_through_the_bot(bot: Bot):
    await bot.say("alice: ?rng")
    await bot.say("bob: ?rng alice")
    assert bot.out[-1] == "🎲 alice: today 140,891 (5 pts) · best ever 140,891 (5 pts)"
    await bot.say("carol: ?rng today")
    assert bot.out[-1] == "🎲 Today's best rolls: 1. alice 140,891 (5)"
    await bot.say("dave: ?rng top")
    assert bot.out[-1] == "🎲 Best rolls ever: 1. alice 140,891 (5)"
    await bot.wait(11)  # alice's per-user cooldown on ?rng
    await bot.say("alice: ?rng me")
    assert bot.out[-1] == "🎲 alice: today 140,891 (5 pts) · best ever 140,891 (5 pts)"
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/bin/pytest tests/test_flows.py -q`
Expected: the new flow test fails (`?rng` isn't registered).

- [ ] **Step 3: Write `bot/core.py`**

```python
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
from bot.rng import register_rng
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
        register_stats(self.registry, stats=stats, game_names=[*games, "rng"])
        register_fun(
            self.registry,
            assets=assets,
            rng=rng,
            http=http,
            stats=stats,
            clock=clock,
            lookup_user=connector.lookup_user,
        )
        register_rng(self.registry, stats=stats, clock=clock, rng=rng, meme_badges=config.rng_meme_badges)
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
```

- [ ] **Step 4: Write `README.md`**

````markdown
# Offline Chat Bot

A Twitch chat bot for jasontheween's offline chat: personal chat games (Scramble, Hangman,
Trivia, Riddle, Higher or Lower), quick fun commands, per-game points with leaderboards, mod
controls (pause, resume, shut down), and a daily activity log. Designs:
`docs/superpowers/specs/` (Phase 1 core, Phase 2 games).

Games are personal: `?scramble` starts **your** game, only your answers count, and the bot
answers you in threaded replies. Many people can play at once (25 games by default), each
person runs one game at a time, and new games are refused ("try again in a moment") while the
bot's outgoing messages are backed up.

## Commands

| Command | Who | What it does |
|---|---|---|
| `?help` / `?commands`, `?help <command>` | anyone | List commands, or explain one |
| `?scramble [category]`, `?scramble categories` | anyone | Your own word to unscramble: type the answer; `?hint` for a hint (10/7/4 points) |
| `?hangman [category]`, `?hangman categories` | anyone | Your own Hangman; guess with `?g <letter>` or `?g <answer>` |
| `?trivia [category] [easy\|medium\|hard]`, `?trivia categories` | anyone | Your own trivia question. Easy is multiple choice (`?g A`-`D`, 5 points); medium and hard are typed (`?g <answer>`, 3 guesses, `?hint`; medium 10/7/4, hard 15/10/6 points). Questions from Open Trivia DB (CC BY-SA 4.0) |
| `?riddle` | anyone | Your own riddle: `?g <answer>`, 3 guesses, `?hint` for a clue then the letter count (10/7/4 points) |
| `?higherlower` / `?hl` | anyone | Does the next thing get more monthly Wikipedia views? `?g higher` or `?g lower`; 1 point per right answer, one miss ends the streak |
| `?skip` | anyone | End your current game (no points) |
| `?leaderboard [game] [1-10]` | anyone | Top players by points |
| `?gamestats [game] [username]` | anyone | Wins, games played, points |
| `?8ball`, `?coinflip`, `?catfact`, `?dogfact`, `?fact`, `?dadjoke` | anyone | Quick fun |
| `?cookie`, `?cookie give <username>` | anyone | Daily fortune cookie (resets 00:00 UTC) |
| `?rng`, `?rng me\|today\|top\|<username>` | anyone | Your daily roll from 0 to 1,000,000 (resets 00:00 UTC), scored by about 27 badges in four tiers (legendary 100, rare 40, uncommon 15, common 5). Points count on the main leaderboard. `[rng] meme_badges = false` in `config.toml` turns off the 69 and 420 badges |
| `?bot off` / `?bot on` / `?bot status` | mods, broadcaster, owners | Pause, resume, check. `?bot off` ends every running game with no points, and while paused the bot ignores everything except `?bot` from a mod |
| `?bot shutdown` | mods, broadcaster, owners | Stop the bot process. Only someone with access to the machine can start it again |
| `?stopgame` | mods, broadcaster, owners | End all running games with no points |

Scramble and Hangman categories: animals, countries, food, games, general, streamers. Trivia
categories: animals, anime, games, general, geography, history, movies, music, science, sports, tv.

A player doesn't get the same trivia question or riddle again within their last 50.

## Install

```
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Any Python from 3.11 to 3.13 works.

## Try it without Twitch

```
.venv/bin/python -m bot console
```

Type lines like `alice: ?scramble animals`. A leading `@` makes the user a mod (`@mod: ?bot off`).
Console mode keeps its own database under `data/console/`, separate from the real one.

On macOS, the python.org installer ships without root certificates, so HTTPS would fail. The
bot detects this at startup and uses the `certifi` certificate bundle automatically.

## Set up on Twitch (one time)

1. **Bot account:** create a new Twitch account for the bot and verify its email.
2. **Twitch app:** at https://dev.twitch.tv/console, register an application (Twitch requires
   two-factor authentication on the account that registers it).
   - OAuth Redirect URL: `http://localhost:4343/oauth/callback` (exactly).
   - Category: Chat Bot. Client type: Confidential.
   - Copy the Client ID and create a Client Secret.
3. **Secrets:** `cp .env.example .env`, then fill in `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`.
   `.env` holds secrets: never share or commit it (it's git-ignored).
4. **Your numeric user ID** goes in `OWNER_IDS`. It's a number, not your username. To look it up
   (replace `yourname`):
   ```
   source .env
   TOKEN=$(curl -s -X POST "https://id.twitch.tv/oauth2/token?client_id=$TWITCH_CLIENT_ID&client_secret=$TWITCH_CLIENT_SECRET&grant_type=client_credentials" | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
   curl -s -H "Client-Id: $TWITCH_CLIENT_ID" -H "Authorization: Bearer $TOKEN" "https://api.twitch.tv/helix/users?login=yourname"
   ```
   The `"id"` in the answer is your user ID.
5. **Log the bot in:** run `.venv/bin/python -m bot auth`. Open the printed URL in a browser where
   you're logged in as the **bot** account and approve. Put the printed `BOT_ID=...` line in `.env`.
   The login is saved in `data/.tio.tokens.json`. Never share or commit that file.
6. **Channel:** set `channel` in `config.toml` to the channel the bot should join.
7. **Mod the bot** in that channel (`/mod <botaccount>` in its chat). Without mod status the bot
   still runs, but it sends more slowly (0.6 messages per second, under Twitch's non-mod limit),
   slow mode applies, and it won't show the Chat Bot badge. The startup log says `is_mod` either
   way. If a mod unmods the bot while it runs, it switches to the slower mode by itself.

## Run

```
.venv/bin/python -m bot
```

- Ctrl+C stops it cleanly.
- `?bot shutdown` from a mod also stops it, with exit code 0.

**Exit codes:**
- 0: stopped on purpose.
- 1: crashed.
- 2: config problem (the message names the setting).
- 3: the Twitch login needs redoing (`python -m bot auth`).
- 130: Ctrl+C before the bot finished starting.

## Settings

- `config.toml` holds the non-secret settings: channel, prefix, cooldowns, enabled games, how
  many games can run at once, the busy threshold, the send rate, and log retention.
- `.env` holds the secrets.
- The word lists are plain text in `bot/content/words/`, one entry per line. Adding a file adds
  a category.
- `bot/content/words/SOURCES.md` records where each streamer and game name was verified.

## Data and logs

- `data/bot.db` (SQLite) holds points, rounds, daily cookies, and the paused flag. The paused
  flag survives restarts.
- `data/logs/activity-YYYY-MM-DD.jsonl` is one file per UTC day. It records commands, game
  starts and ends, admin actions (who paused or shut down the bot), connection events, and
  errors. Ordinary chat is never logged. Files older than 30 days are deleted.

## Move to a server

1. Copy the project folder to the server (for example `/opt/offline-chat-bot`), including
   `.env` and `data/.tio.tokens.json`.
2. On the server: `python3 -m venv .venv && .venv/bin/pip install -e .` (any Python 3.11-3.13).
3. Create a user for the bot (`sudo useradd -r chatbot`), give it the folder, and make the two
   secret files readable only by it:
   ```
   sudo chown -R chatbot /opt/offline-chat-bot
   sudo chmod 600 /opt/offline-chat-bot/.env /opt/offline-chat-bot/data/.tio.tokens.json
   ```
4. `sudo cp deploy/offline-chat-bot.service /etc/systemd/system/`, then
   `sudo systemctl daemon-reload && sudo systemctl enable --now offline-chat-bot`.
5. **How it behaves on the server:**
   - **After a crash or a lost connection:** restarts after 30 seconds and keeps retrying, so a
     long Twitch outage heals on its own. A config error (exit 2) or a needed re-login (exit 3)
     is never restarted, because those need a person.
   - **After `?bot shutdown`:** stays down until someone with server access runs
     `sudo systemctl start offline-chat-bot`.
   - **Logs:** `journalctl -u offline-chat-bot -f`.
6. **Run only one copy of the bot at a time.** If it's running on both your laptop and the
   server, every command is answered twice.
7. **If it stops with exit 3 (login needed):** the login page needs a browser, which a server
   doesn't have. Either run `python -m bot auth` on your laptop and copy the new
   `data/.tio.tokens.json` to the server (then `chmod 600` it and restart the service), or tunnel
   the login port with `ssh -L 4343:localhost:4343 <server>` and run `auth` on the server.

## Go live in jasontheween's chat

1. A channel mod runs `/mod <botaccount>` there.
2. Set `channel = "jasontheween"` in `config.toml`.
3. Restart the bot (`sudo systemctl restart offline-chat-bot` on the server).

## Tests

```
.venv/bin/pytest
```

## Content

- Trivia questions come from [Open Trivia DB](https://opentdb.com/) (CC BY-SA 4.0; see
  `bot/content/TRIVIA_CREDITS.md`). `scripts/fetch_trivia.py` rebuilds `bot/content/trivia.json`
  (it takes several minutes because of the API's rate limit).
- Riddles (`bot/content/riddles.json`) were written for this bot and checked by a second reviewer.
- Higher or Lower uses last month's English Wikipedia page views. Edit
  `scripts/higherlower_terms.txt` and run `scripts/fetch_pageviews.py` to change the terms or
  refresh the numbers.
- `tests/test_content.py` checks every content file's rules (lengths, blocked words, clues that
  don't give the answer away).
````

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_flows.py -q`, then `.venv/bin/pytest -q`.
Expected: `41 passed`, then the whole suite passes (492 passed).

- [ ] **Step 6: Commit**

```bash
git add tests/test_flows.py bot/core.py README.md
git commit -m "Phase 3: register ?rng; rng counts on the leaderboard"
```

## Execution log

Added while the plan is executed.
