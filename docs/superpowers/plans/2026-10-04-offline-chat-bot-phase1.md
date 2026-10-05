# Offline Chat Bot Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 1 of the Twitch chat bot for jasontheween's offline chat. It covers the
core (Twitch connection, mod controls, activity log, rate-limited outbox, stats database, game
manager), `?help`, `?leaderboard`, `?gamestats`, personal Scramble (`?hint`) and Hangman (`?g`),
`?skip`, and the quick fun commands including `?cookie`. It is playable in a terminal (console mode) and live on
Twitch.

**Architecture:**
- `BotCore` filters incoming chat and routes it to a command registry, or to the active game.
  It talks to the chat platform only through a small `Connector` interface. There are two
  connectors: Twitch (TwitchIO: EventSub WebSocket in, Helix with the app token out) and the
  console.
- Games are pure classes: messages and time in, `Outcome` out. Games are **personal**: a
  `GameManager` runs one game per player, many players at once, with limits (25 running, a
  per-player cooldown, and a busy brake), timers, and scoring. Replies are threaded to the player.
- Everything the bot says goes through a rate-limited `Outbox`. State lives in one SQLite file;
  activity goes to daily JSONL logs.

**Tech Stack:** Python 3.12, TwitchIO 3.3.2, aiohttp, python-dotenv, SQLite (stdlib), pytest +
pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-10-04-offline-chat-bot-design.md` (approved 2026-10-04).

---

## Conventions

- **Where to run:** every command runs from the project root, `offline-chat-bot/`. Tests run
  with `.venv/bin/pytest`.
- **Code is pre-verified:** the code in this plan was written and run before the plan was
  saved. Each task's tests pass using only the files from that task and the ones before it, in
  this order (265 tests in total before the content task). Copy the code exactly. If a step's
  output differs from "Expected", stop and investigate (superpowers:systematic-debugging).
  Don't adjust the test to match.
- **TDD rhythm:** write the test file, run it and see it fail, write the implementation, run it
  and see it pass, commit.
- **Commits:** one per task. Never add AI attribution to commit messages: no `Co-Authored-By`
  trailer and no "Generated with" line.
- **Spec refinements:** this plan refines the spec in a few places, all compatible with it.
  1. `Game.commands` is a dict `name -> (usage, description)`, so in-game commands like `?g`
     carry their own help text.
  2. `Game.category_names(assets)` replaces a static `categories` list, because categories come
     from the word files.
  3. `?help` lives in its own `bot/help.py`.
  4. Hangman's solve check ignores spaces (`?g sealion` solves `SEA LION`).
  5. A small `bot/clock.py` provides the real clock and a fake one for tests.
  6. The console mode uses its own `data/console/` database, so local play never touches real
     stats.
  7. `deploy/offline-chat-bot.service` is the spec's systemd unit as a file.
- **Revision 2026-10-04 (during execution):** Tasks 1-6 were built and code-reviewed first.
  Reviews hardened text normalization, the activity log, the stats store, and the outbox, and
  Robert switched every Phase 1 game to personal (single-player) play. The code blocks below are
  the reviewed, current versions; Tasks 1-6 are already committed on branch `phase1`.
- **Not built in Phase 1:** trivia, riddles, Family Feud, Higher or Lower, `?rng`, `?ascii`,
  `?chatsummary`, and the commands web page. These are spec §17.

## File map

| File | Responsibility | Task |
|---|---|---|
| `pyproject.toml`, `bot/__init__.py` | Package, dependencies, pytest config, version | 1 |
| `bot/clock.py` | `Clock` (real) and `FakeClock` (tests) | 2 |
| `bot/text.py` | normalize, truncate, username validation, durations | 2 |
| `bot/assets.py` | Read bundled `bot/content/*.txt` | 3 |
| `bot/activity_log.py` | Daily JSONL activity log + retention | 3 |
| `bot/stats.py` | SQLite: users, rounds, players, daily uses, bot state | 4 |
| `bot/connectors/base.py` | `ChatMessage`, `SendResult`, `UserRef`, `ReadyInfo`, `Connector`, `AuthRequired` | 5 |
| `bot/outbox.py` | Token-bucket send queue: priority, coalescing, truncation | 5 |
| `bot/cooldowns.py`, `bot/permissions.py` | Cooldowns; `is_controller` | 6 |
| `bot/commands.py` | `parse_command`, `Command`, `CommandRegistry`, help text | 7 |
| `bot/games/base.py`, `bot/games/scramble.py` | `Game` + `Outcome`; Scramble | 8 |
| `bot/games/hangman.py` | Hangman with `?g` | 9 |
| `bot/games/__init__.py`, `bot/games/manager.py` | `ALL_GAMES`; `GameManager` (personal sessions) | 10 |
| `bot/http.py`, `bot/fun.py` | HTTP client; quick commands + `?cookie` | 11 |
| `bot/stats_commands.py`, `bot/help.py` | `?leaderboard`, `?gamestats`; `?help` | 12 |
| `bot/config.py`, `config.toml`, `.env.example` | Settings + validation | 13 |
| `bot/connectors/console.py` | Terminal connector | 14 |
| `bot/admin.py`, `bot/core.py` | `?bot`, `?stopgame`; `BotCore` + run loop | 15 |
| `bot/connectors/twitch.py` | TwitchIO connector + `auth` flow | 16 |
| `bot/__main__.py` | CLI: run / auth / console | 17 |
| `bot/content/**` | 8-ball, fortunes, fallbacks, six word lists, `SOURCES.md`, blocked lists | 18 |
| `README.md`, `deploy/offline-chat-bot.service` | Docs, systemd unit | 19 |
| `tests/helpers.py` | `make_msg` (6), `FakeHttp` (11), `make_config` (15) | 6, 11, 15 |


### Task 1: Project scaffold

The package, its dependencies, and pytest configuration. `asyncio_mode = "auto"` lets async test functions run without decorators.

**Files:**
- Create: `pyproject.toml`, `bot/__init__.py`, `tests/__init__.py` (empty), `tests/test_version.py`
- Existing: `.gitignore` (already ignores `.env`, `data/`, `.venv/`)

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "offline-chat-bot"
version = "0.1.0"
description = "Twitch chat-games bot for jasontheween's offline chat"
requires-python = ">=3.11,<3.14"
dependencies = [
    "twitchio==3.3.2",
    "aiohttp>=3.9",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23"]

[tool.setuptools.packages.find]
include = ["bot*"]

[tool.setuptools.package-data]
bot = ["content/*.txt", "content/words/*.txt"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
filterwarnings = [
    # TwitchIO's web adapter subclasses aiohttp's Application; harmless, not ours to fix.
    "ignore:Inheritance class AiohttpAdapter from web.Application is discouraged:DeprecationWarning",
]
```

- [ ] **Step 2: Write `bot/__init__.py` and an empty `tests/__init__.py`**

```python
__version__ = "0.1.0"
```

```bash
touch tests/__init__.py
```

- [ ] **Step 3: Create the virtualenv and install**

Run: `python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'`

Expected: ends with `Successfully installed ... offline-chat-bot-0.1.0 ... twitchio-3.3.2`.

- [ ] **Step 4: Write `tests/test_version.py`**

```python
import bot


def test_version():
    assert bot.__version__ == "0.1.0"
```

- [ ] **Step 5: Run it**

Run: `.venv/bin/pytest -q`

Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml bot/__init__.py tests/__init__.py tests/test_version.py
git commit -m "Scaffold the package and test setup"
```

### Task 2: Clock and text helpers

`Clock` gives wall time (UTC, for dates and logs) and monotonic time (for timers and rate limits). `FakeClock` lets tests move time by hand. `text.py` holds the answer normalization from spec §6: NFKC, then lowercase, then drop format characters (Cf), combining marks (Mn, Me), and the tag block U+E0000-E007F (Chatterino's U+E0000 duplicate tag is unassigned, so it needs the explicit range), then punctuation to spaces. It also has 500-character truncation, Twitch username validation, and `3h 12m` formatting. Test strings build special characters with `chr()`, so the source has no raw invisible characters.

**Files:**
- Create: `bot/clock.py`, `bot/text.py`
- Test: `tests/test_text.py`

- [ ] **Step 1: Write the failing test `tests/test_text.py`**

```python
from bot.text import clean_username, format_duration, normalize, strip_invisible, truncate


def test_normalize_lowercases_and_collapses_spaces():
    assert normalize("  Hello   WORLD ") == "hello world"


def test_normalize_turns_punctuation_into_spaces():
    assert normalize("spider-man!") == "spider man"


def test_normalize_drops_chatterino_duplicate_tag():
    assert normalize("alligator \U000e0000") == "alligator"


def test_normalize_drops_zero_width_characters():
    assert normalize("alli" + chr(0x200B) + "gator") == "alligator"


def test_normalize_removes_combining_marks_instead_of_splitting_words():
    stroke = chr(0x0336)  # combining long stroke overlay: strikethrough "fancy text"
    assert normalize(f"h{stroke}e{stroke}l{stroke}l{stroke}o{stroke}") == "hello"


def test_normalize_removes_format_characters_mid_word():
    for invisible in (chr(0x00AD), chr(0x2066), chr(0xFE0F)):  # soft hyphen, directional isolate, variation selector
        assert normalize(f"alli{invisible}gator") == "alligator"


def test_normalize_keeps_accented_letters():
    assert normalize("Cafe" + chr(0x0301)) == "caf" + chr(0x00E9)  # NFKC composes the accent before marks are dropped


def test_normalize_applies_nfkc():
    assert normalize("ｆｕｌｌｗｉｄｔｈ") == "fullwidth"


def test_strip_invisible_keeps_visible_text():
    assert strip_invisible("?scramble\U000e0000") == "?scramble"


def test_truncate_leaves_short_text_alone():
    assert truncate("hi") == "hi"


def test_truncate_cuts_at_word_boundary_with_ellipsis():
    text = "word " * 200
    out = truncate(text)
    assert len(out) <= 500
    assert out.endswith("word…")


def test_truncate_hard_cuts_one_long_word():
    out = truncate("x" * 600)
    assert len(out) == 500
    assert out.endswith("…")


def test_clean_username_accepts_valid_names():
    assert clean_username("@Some_User") == "some_user"


def test_clean_username_accepts_boundary_lengths():
    assert clean_username("abc") == "abc"
    assert clean_username("x" * 25) == "x" * 25


def test_clean_username_rejects_bad_names():
    assert clean_username("ab") is None
    assert clean_username("has space") is None
    assert clean_username("emoji😀") is None
    assert clean_username("x" * 26) is None


def test_format_duration():
    assert format_duration(45) == "45s"
    assert format_duration(12 * 60 + 5) == "12m"
    assert format_duration(3 * 3600 + 12 * 60) == "3h 12m"
    assert format_duration(-5) == "0s"
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_text.py -q`

Expected: FAIL. `ModuleNotFoundError: No module named 'bot.text'`

- [ ] **Step 3: Write `bot/clock.py`**

```python
"""Time sources. Real code uses Clock; tests use FakeClock to control time."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone


class Clock:
    def now(self) -> datetime:
        """Current wall-clock time in UTC (for dates, logs, and the database)."""
        return datetime.now(timezone.utc)

    def mono(self) -> float:
        """Monotonic seconds (for timers and rate limits; never jumps backwards)."""
        return time.monotonic()


class FakeClock(Clock):
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
        self._mono = 1000.0

    def now(self) -> datetime:
        return self._now

    def mono(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._mono += seconds
```

- [ ] **Step 4: Write `bot/text.py`**

```python
"""Text helpers: answer normalization, truncation, usernames, durations."""

from __future__ import annotations

import re
import unicodedata

MAX_MESSAGE = 500

# Removed outright rather than turned into spaces, so a word stays one word:
# - format characters (category Cf): zero-width spaces and joiners, BOM, soft hyphen,
#   directional marks;
# - combining marks (Mn, Me): strikethrough and "fancy text" overlays, variation selectors;
# - the Unicode tag block U+E0000-E007F. Chatterino and 7TV append U+E0000 to repeated
#   messages, and it is unassigned (category Cn), so the category check alone misses it.
_DROP_CATEGORIES = frozenset({"Cf", "Mn", "Me"})
_TAG_BLOCK = range(0xE0000, 0xE0080)
_USERNAME = re.compile(r"^[A-Za-z0-9_]{3,25}$")


def strip_invisible(text: str) -> str:
    return "".join(
        ch for ch in text if unicodedata.category(ch) not in _DROP_CATEGORIES and ord(ch) not in _TAG_BLOCK
    )


def normalize(text: str) -> str:
    """Lowercase, drop invisible characters, turn punctuation into spaces, collapse spaces."""
    t = unicodedata.normalize("NFKC", text).lower()
    t = strip_invisible(t)
    t = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in t)
    return " ".join(t.split())


def truncate(text: str, limit: int = MAX_MESSAGE) -> str:
    """Cut to at most `limit` characters at a word boundary, ending with an ellipsis."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def clean_username(raw: str) -> str | None:
    """Strip a leading @ and return the lowercase login, or None if it isn't a valid name."""
    name = strip_invisible(raw).strip().lstrip("@")
    if not _USERNAME.fullmatch(name):
        return None
    return name.lower()


def format_duration(seconds: float) -> str:
    """3h 12m, 12m, or 45s."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_text.py -q`

Expected: PASS (16 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add bot/clock.py bot/text.py tests/test_text.py
git commit -m "Add clock and text helpers"
```

### Task 3: Assets, shared test fixtures, activity log

`Assets` reads the bundled text files (one item per line, `#` comments allowed). `conftest.py` gives every test a `FakeClock` and a tiny temporary content folder, so game tests never depend on the real word lists. `ActivityLog` appends one JSON object per line to `activity-YYYY-MM-DD.jsonl` (UTC) and prunes files older than the retention window, once per day (spec §11). `write()` never raises: a logging failure must not crash the bot, and a caller can't overwrite `ts`.

**Files:**
- Create: `bot/assets.py`, `bot/activity_log.py`, `tests/conftest.py`
- Test: `tests/test_assets.py`, `tests/test_activity_log.py`

- [ ] **Step 1: Write the failing test `tests/conftest.py`**

```python
from pathlib import Path

import pytest

from bot.assets import Assets
from bot.clock import FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def content_dir(tmp_path: Path) -> Path:
    """A tiny content folder so game tests don't depend on the real word lists."""
    root = tmp_path / "content"
    (root / "words").mkdir(parents=True)
    (root / "words" / "animals.txt").write_text("# comment\nalligator\ncat\nsea lion\n", encoding="utf-8")
    (root / "words" / "food.txt").write_text("ramen\nhot cheetos\n", encoding="utf-8")
    (root / "8ball.txt").write_text("Yes.\nNo.\n", encoding="utf-8")
    (root / "blocked_rot13.txt").write_text("# test fragment: 'gat'\ntng\n", encoding="utf-8")
    (root / "fortunes.txt").write_text("Good things are coming.\n", encoding="utf-8")
    for name in ("catfacts", "dogfacts", "facts", "dadjokes"):
        (root / f"fallback_{name}.txt").write_text(f"fallback {name} line\n", encoding="utf-8")
    return root


@pytest.fixture
def assets(content_dir: Path) -> Assets:
    return Assets(content_dir)
```

- [ ] **Step 2: Write the failing test `tests/test_assets.py`**

```python
from bot.assets import Assets


def test_lines_skip_blank_and_comment_lines(assets: Assets):
    assert assets.words("animals") == ["alligator", "cat", "sea lion"]


def test_categories_are_sorted_file_stems(assets: Assets):
    assert assets.categories() == ["animals", "food"]


def test_lines_reads_top_level_files(assets: Assets):
    assert assets.lines("8ball") == ["Yes.", "No."]
```

- [ ] **Step 3: Write the failing test `tests/test_activity_log.py`**

```python
import json
from datetime import date

from bot.activity_log import ActivityLog
from bot.clock import FakeClock


def test_write_appends_json_line_to_todays_file(tmp_path, clock: FakeClock):
    log = ActivityLog(tmp_path, clock)
    log.write("command", user_id="1", command="scramble")
    log.write("admin", action="off")
    lines = log.path_for(date(2026, 10, 4)).read_text().splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["command", "admin"]
    assert json.loads(lines[0]) == {
        "ts": "2026-10-04T12:00:00Z",
        "event": "command",
        "user_id": "1",
        "command": "scramble",
    }


def test_caller_cannot_overwrite_timestamp(tmp_path, clock: FakeClock):
    log = ActivityLog(tmp_path, clock)
    log.write("command", ts="bogus")
    record = json.loads(log.path_for(date(2026, 10, 4)).read_text())
    assert record["ts"] == "2026-10-04T12:00:00Z"


def test_write_failure_is_swallowed(tmp_path, clock: FakeClock):
    log = ActivityLog(tmp_path / "logs", clock)
    (tmp_path / "logs").rmdir()  # the log folder disappears while the bot runs
    log.write("error", where="test")  # must not raise


def test_new_utc_day_starts_new_file(tmp_path, clock: FakeClock):
    log = ActivityLog(tmp_path, clock)
    log.write("a")
    clock.advance(12 * 3600)
    log.write("b")
    assert log.path_for(date(2026, 10, 4)).exists()
    assert log.path_for(date(2026, 10, 5)).exists()


def test_prune_deletes_files_older_than_retention(tmp_path, clock: FakeClock):
    log = ActivityLog(tmp_path, clock, retention_days=30)
    old = tmp_path / "activity-2026-09-03.jsonl"
    kept = tmp_path / "activity-2026-09-04.jsonl"
    other = tmp_path / "notes.txt"
    malformed = tmp_path / "activity-not-a-date.jsonl"
    for p in (old, kept, other, malformed):
        p.write_text("x")
    assert log.prune() == 1
    assert not old.exists() and kept.exists() and other.exists() and malformed.exists()


def test_maybe_rollover_prunes_once_per_day(tmp_path, clock: FakeClock):
    log = ActivityLog(tmp_path, clock, retention_days=30)
    log.maybe_rollover()
    stale = tmp_path / "activity-2026-01-01.jsonl"
    stale.write_text("x")
    log.maybe_rollover()
    assert stale.exists()
    clock.advance(24 * 3600)
    log.maybe_rollover()
    assert not stale.exists()
```

- [ ] **Step 4: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_assets.py tests/test_activity_log.py -q`

Expected: FAIL. `ImportError` while loading conftest (`No module named 'bot.assets'`)

- [ ] **Step 5: Write `bot/assets.py`**

```python
"""Loads the bundled text files in bot/content/ (one item per line)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

DEFAULT_ROOT = Path(__file__).parent / "content"


class Assets:
    def __init__(self, root: Path = DEFAULT_ROOT) -> None:
        self.root = root

    def lines(self, name: str) -> list[str]:
        """Non-blank, non-comment lines of content/<name>.txt."""
        return list(_read(self.root / f"{name}.txt"))

    def words(self, category: str) -> list[str]:
        return list(_read(self.root / "words" / f"{category}.txt"))

    def categories(self) -> list[str]:
        return sorted(p.stem for p in (self.root / "words").glob("*.txt"))


@cache  # content is bundled and read-only, so each file is read once per process
def _read(path: Path) -> tuple[str, ...]:
    text = path.read_text(encoding="utf-8")
    return tuple(
        line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    )
```

- [ ] **Step 6: Write `bot/activity_log.py`**

```python
"""Append-only JSONL activity log: one file per UTC day, old files pruned."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from bot.clock import Clock

logger = logging.getLogger("bot.activity")
_PREFIX = "activity-"


class ActivityLog:
    def __init__(self, directory: Path, clock: Clock, retention_days: int = 30) -> None:
        self.directory = directory
        self.clock = clock
        self.retention_days = retention_days
        self._last_prune_day: date | None = None
        directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, day: date) -> Path:
        return self.directory / f"{_PREFIX}{day.isoformat()}.jsonl"

    def write(self, event: str, **fields: Any) -> None:
        """Append one event. Never raises: a logging failure must not crash the bot."""
        now = self.clock.now()
        stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        record = {"ts": stamp, "event": event, **fields}
        record["ts"] = stamp  # a caller-supplied "ts" field must not replace the real timestamp
        line = json.dumps(record, ensure_ascii=False, default=str)
        logger.info("%s %s", event, json.dumps(fields, ensure_ascii=False, default=str))
        try:
            with self.path_for(now.date()).open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")
        except OSError:
            logger.exception("could not write the activity log")

    def prune(self) -> int:
        """Delete files older than the retention window. Returns how many were deleted."""
        today = self.clock.now().date()
        cutoff = today - timedelta(days=self.retention_days)
        deleted = 0
        for path in self.directory.glob(f"{_PREFIX}*.jsonl"):
            try:
                day = date.fromisoformat(path.stem.removeprefix(_PREFIX))
            except ValueError:
                continue
            if day < cutoff:
                try:
                    path.unlink()
                except OSError:
                    logger.exception("could not delete old log %s", path)
                    continue
                deleted += 1
        self._last_prune_day = today
        return deleted

    def maybe_rollover(self) -> None:
        """Prune once per UTC day; called from the bot's 1-second tick."""
        if self._last_prune_day != self.clock.now().date():
            self.prune()
```

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_assets.py tests/test_activity_log.py -q`

Expected: PASS (9 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add bot/assets.py bot/activity_log.py tests/conftest.py tests/test_assets.py tests/test_activity_log.py
git commit -m "Add asset loading and the activity log"
```

### Task 4: Stats store (SQLite)

The schema from spec §8, applied through numbered migrations keyed off `schema_version`. Each migration runs as one `BEGIN; ...; COMMIT;` script, because sqlite3 doesn't wrap CREATE statements in a transaction, and a database newer than the code is refused. Migration 1 also creates indexes for the ranking queries. Rounds and their players are written in one transaction when a round ends; `record_round` also upserts each player's user row. Leaderboards and ranks are computed from `round_players` (no stored totals), ordered by points, then wins, then login, and only list people with points; they aggregate first and join users after. `claim_daily` uses `ON CONFLICT DO NOTHING` on the primary key, so a second claim on the same UTC day fails atomically.

**Files:**
- Create: `bot/stats.py`
- Test: `tests/test_stats.py`

- [ ] **Step 1: Write the failing test `tests/test_stats.py`**

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
    assert again.schema_version() == 1
    again.close()


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
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_stats.py -q`

Expected: FAIL. `ModuleNotFoundError: No module named 'bot.stats'`

- [ ] **Step 3: Write `bot/stats.py`**

```python
"""SQLite storage: users, game rounds and players, daily uses, and persistent bot state."""

from __future__ import annotations

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

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_stats.py -q`

Expected: PASS (16 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bot/stats.py tests/test_stats.py
git commit -m "Add the SQLite stats store"
```

### Task 5: Connector types and the outbox

`connectors/base.py` defines the platform-neutral types from spec §4. The `Outbox` (spec §9) does several things:

- truncates each message to 500 characters;
- coalesces messages that share a `coalesce_key` (for example the Hangman board) by replacing the unsent one in place;
- puts priority messages at the front, and evicts the newest normal message if the queue is full;
- drops and logs new normal messages when the queue is full;
- sends through a token bucket (the class defaults to 1/s and a burst of 3; the bot configures 2/s);
- gives up on any send after 10 s (TwitchIO's HTTP client otherwise waits up to 300 s).

`flush_ready()` sends what the bucket allows right now, which makes it testable with `FakeClock`. `run()` is the background loop: it paces by tokens, wakes on new messages, stops promptly, and logs and survives unexpected errors. `drain()` flushes for at most 3 real seconds at shutdown and logs what it had to drop. A lock keeps `run()` and `drain()` from sending at the same time. `close()` makes later enqueues log as dropped (replies from handlers that finish after shutdown), and `discard()` drops the queue with one log line.

**Files:**
- Create: `bot/connectors/__init__.py` (empty), `bot/connectors/base.py`, `bot/outbox.py`
- Test: `tests/test_outbox.py`

- [ ] **Step 1: Write the failing test `tests/test_outbox.py`**

```python
import asyncio
from itertools import pairwise

import pytest

from bot.activity_log import ActivityLog
from bot.clock import Clock, FakeClock
from bot.connectors.base import SendResult
from bot.outbox import Outbox


class Recorder:
    def __init__(self, result: SendResult | None = None):
        self.sent: list[tuple[str, str | None]] = []
        self.result = result or SendResult(True)

    async def __call__(self, text: str, reply_to: str | None) -> SendResult:
        self.sent.append((text, reply_to))
        return self.result


@pytest.fixture
def log(tmp_path, clock):
    return ActivityLog(tmp_path / "logs", clock)


def make(clock, log, recorder, **kw) -> Outbox:
    return Outbox(recorder, clock, log, **kw)


async def test_burst_then_one_per_second(clock: FakeClock, log):
    rec = Recorder()
    box = make(clock, log, rec, rate=1, burst=3)
    for i in range(5):
        box.enqueue(f"m{i}")
    assert await box.flush_ready() == 3
    assert await box.flush_ready() == 0
    clock.advance(1)
    assert await box.flush_ready() == 1
    clock.advance(10)
    assert await box.flush_ready() == 1
    assert [t for t, _ in rec.sent] == ["m0", "m1", "m2", "m3", "m4"]


async def test_tokens_cap_at_burst(clock: FakeClock, log):
    rec = Recorder()
    box = make(clock, log, rec, rate=1, burst=3)
    clock.advance(100)
    for i in range(6):
        box.enqueue(f"m{i}")
    assert await box.flush_ready() == 3


async def test_reply_to_is_passed_through(clock, log):
    rec = Recorder()
    box = make(clock, log, rec)
    box.enqueue("hi", reply_to="msg-1")
    await box.flush_ready()
    assert rec.sent == [("hi", "msg-1")]


async def test_full_queue_drops_new_normal_messages_and_logs(clock, log, tmp_path):
    box = make(clock, log, Recorder(), max_queue=2)
    assert box.enqueue("a") and box.enqueue("b")
    assert not box.enqueue("c")
    assert box.pending() == ["a", "b"]
    assert "queue_full" in (tmp_path / "logs" / "activity-2026-10-04.jsonl").read_text()


async def test_priority_goes_first_and_evicts_newest_normal_when_full(clock, log):
    box = make(clock, log, Recorder(), max_queue=3)
    for t in ("a", "b", "c"):
        box.enqueue(t)
    assert box.enqueue("STOP", priority=True)
    assert box.pending() == ["STOP", "a", "b"]


async def test_priority_messages_keep_their_order(clock, log):
    box = make(clock, log, Recorder())
    box.enqueue("a")
    box.enqueue("P1", priority=True)
    box.enqueue("P2", priority=True)
    assert box.pending() == ["P1", "P2", "a"]


async def test_coalesce_replaces_unsent_message_in_place(clock, log):
    box = make(clock, log, Recorder())
    box.enqueue("board 1", coalesce_key="board")
    box.enqueue("other")
    box.enqueue("board 2", coalesce_key="board")
    assert box.pending() == ["board 2", "other"]


async def test_long_messages_are_truncated(clock, log):
    rec = Recorder()
    box = make(clock, log, rec)
    box.enqueue("word " * 200)
    await box.flush_ready()
    assert len(rec.sent[0][0]) <= 500


async def test_dropped_by_twitch_is_logged(clock, log, tmp_path):
    rec = Recorder(SendResult(False, "msg_rejected", "AutoMod held it"))
    box = make(clock, log, rec)
    box.enqueue("hello")
    await box.flush_ready()
    text = (tmp_path / "logs" / "activity-2026-10-04.jsonl").read_text()
    assert "msg_rejected" in text


async def test_send_exception_is_logged_and_loop_continues(clock, log, tmp_path):
    calls = []

    async def flaky(text, reply_to):
        calls.append(text)
        if text == "boom":
            raise ConnectionError("network down")
        return SendResult(True)

    box = Outbox(flaky, clock, log)
    box.enqueue("boom")
    box.enqueue("ok")
    assert await box.flush_ready() == 2
    assert calls == ["boom", "ok"]
    assert "network down" in (tmp_path / "logs" / "activity-2026-10-04.jsonl").read_text()


async def test_drain_sends_remaining_with_real_clock(tmp_path):
    clock = Clock()
    log = ActivityLog(tmp_path, clock)
    rec = Recorder()
    box = Outbox(rec, clock, log, rate=50, burst=1)
    for i in range(5):
        box.enqueue(f"m{i}")
    await box.drain(timeout=2)
    assert len(rec.sent) == 5


async def test_run_loop_sends_and_stops(tmp_path):
    clock = Clock()
    rec = Recorder()
    box = Outbox(rec, clock, ActivityLog(tmp_path, clock))
    stop = asyncio.Event()
    task = asyncio.create_task(box.run(stop))
    box.enqueue("hello")
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert rec.sent == [("hello", None)]


async def test_coalescing_into_priority_keeps_priority_order(clock, log):
    box = make(clock, log, Recorder())
    box.enqueue("P1", priority=True)
    box.enqueue("K1", coalesce_key="k")
    box.enqueue("b")
    box.enqueue("K2", coalesce_key="k", priority=True)  # changes lane: must move up front
    box.enqueue("P2", priority=True)
    assert box.pending() == ["P1", "K2", "P2", "b"]


async def test_coalescing_into_normal_moves_back(clock, log):
    box = make(clock, log, Recorder())
    box.enqueue("K1", coalesce_key="k", priority=True)
    box.enqueue("P1", priority=True)
    box.enqueue("a")
    box.enqueue("K2", coalesce_key="k")
    box.enqueue("P2", priority=True)
    assert box.pending() == ["P1", "P2", "a", "K2"]


async def test_coalescing_when_full_replaces_instead_of_dropping(clock, log):
    box = make(clock, log, Recorder(), max_queue=2)
    box.enqueue("board 1", coalesce_key="board")
    box.enqueue("x")
    assert box.enqueue("board 2", coalesce_key="board")
    assert box.pending() == ["board 2", "x"]


async def test_coalescing_after_original_was_sent_appends(clock, log):
    rec = Recorder()
    box = make(clock, log, rec)
    box.enqueue("board 1", coalesce_key="board")
    await box.flush_ready()
    box.enqueue("board 2", coalesce_key="board")
    assert box.pending() == ["board 2"]


async def test_partial_refill_accumulates(clock: FakeClock, log):
    box = make(clock, log, Recorder(), rate=1, burst=1)
    for t in ("a", "b"):
        box.enqueue(t)
    assert await box.flush_ready() == 1
    clock.advance(0.5)
    assert await box.flush_ready() == 0
    clock.advance(0.5)
    assert await box.flush_ready() == 1


async def test_bad_send_result_is_logged_and_loop_continues(clock, log, tmp_path):
    async def returns_none(text, reply_to):
        return None

    box = Outbox(returns_none, clock, log)
    box.enqueue("one")
    box.enqueue("two")
    assert await box.flush_ready() == 2
    assert "outbox.send" in (tmp_path / "logs" / "activity-2026-10-04.jsonl").read_text()


async def test_hung_send_times_out(tmp_path):
    clock = Clock()
    log = ActivityLog(tmp_path, clock)
    sent = []

    async def hangs_then_works(text, reply_to):
        if text == "hang":
            await asyncio.sleep(10)
        sent.append(text)
        return SendResult(True)

    box = Outbox(hangs_then_works, clock, log, send_timeout=0.1)
    box.enqueue("hang")
    box.enqueue("ok")
    await asyncio.wait_for(box.flush_ready(), timeout=2)
    assert sent == ["ok"]


async def test_drain_gives_up_at_timeout_even_mid_send(tmp_path):
    clock = Clock()
    log = ActivityLog(tmp_path, clock)

    async def slow(text, reply_to):
        await asyncio.sleep(5)
        return SendResult(True)

    box = Outbox(slow, clock, log)
    for t in ("a", "b", "c"):
        box.enqueue(t)
    loop = asyncio.get_running_loop()
    start = loop.time()
    await box.drain(timeout=0.2)
    assert loop.time() - start < 1
    assert len(box) == 0
    assert '"reason": "shutdown"' in log.path_for(clock.now().date()).read_text()


async def test_run_wakes_promptly_for_new_messages_and_stops_promptly(tmp_path):
    clock = Clock()
    rec = Recorder()
    box = Outbox(rec, clock, ActivityLog(tmp_path, clock))
    stop = asyncio.Event()
    task = asyncio.create_task(box.run(stop))
    await asyncio.sleep(0.05)  # loop is now idle, waiting
    box.enqueue("late")
    await asyncio.sleep(0.05)
    assert rec.sent == [("late", None)]
    loop = asyncio.get_running_loop()
    start = loop.time()
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert loop.time() - start < 0.2


async def test_run_paces_to_the_configured_rate(tmp_path):
    clock = Clock()
    times = []

    async def timed(text, reply_to):
        times.append(asyncio.get_running_loop().time())
        return SendResult(True)

    box = Outbox(timed, clock, ActivityLog(tmp_path, clock), rate=10, burst=1)
    stop = asyncio.Event()
    for i in range(4):
        box.enqueue(f"m{i}")
    task = asyncio.create_task(box.run(stop))
    await asyncio.sleep(0.5)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    gaps = [b - a for a, b in pairwise(times)]
    assert len(times) == 4
    assert all(0.07 < g < 0.15 for g in gaps), gaps


async def test_closed_outbox_drops_and_logs_late_messages(clock, log, tmp_path):
    box = make(clock, log, Recorder())
    box.close()
    assert not box.enqueue("reply from a handler that finished late")
    assert len(box) == 0
    assert '"reason": "shutdown"' in (tmp_path / "logs" / "activity-2026-10-04.jsonl").read_text()


async def test_discard_logs_count_and_clears(clock, log, tmp_path):
    box = make(clock, log, Recorder())
    box.enqueue("a")
    box.enqueue("b")
    assert box.discard("connector_failed") == 2
    assert len(box) == 0
    text = (tmp_path / "logs" / "activity-2026-10-04.jsonl").read_text()
    assert '"reason": "connector_failed"' in text and '"count": 2' in text
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_outbox.py -q`

Expected: FAIL. `ModuleNotFoundError: No module named 'bot.connectors'`

- [ ] **Step 3: Create the empty package file**

```bash
mkdir -p bot/connectors && touch bot/connectors/__init__.py
```

- [ ] **Step 4: Write `bot/connectors/base.py`**

```python
"""The boundary between the bot core and a chat platform (Twitch, or the console)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ChatMessage:
    id: str
    user_id: str
    login: str  # lowercase username
    display_name: str
    text: str
    is_broadcaster: bool
    is_moderator: bool
    source_channel_id: str | None  # set during shared chat
    received_at: datetime  # UTC


@dataclass(frozen=True)
class SendResult:
    sent: bool
    drop_code: str | None = None
    drop_message: str | None = None


@dataclass(frozen=True)
class UserRef:
    user_id: str
    login: str
    display_name: str


@dataclass(frozen=True)
class ReadyInfo:
    channel_login: str
    channel_id: str
    is_mod: bool


OnMessage = Callable[[ChatMessage], Awaitable[None]]
OnReady = Callable[[ReadyInfo], Awaitable[None]]  # once connected, and again if mod status is lost


class Connector(Protocol):
    channel_id: str

    async def run(self, on_message: OnMessage, on_ready: OnReady) -> None:
        """Connect and deliver messages until closed. Raises on fatal errors."""

    async def send(self, text: str, reply_to: str | None = None) -> SendResult: ...

    async def lookup_user(self, login: str) -> UserRef | None: ...

    async def close(self) -> None: ...


class AuthRequired(Exception):
    """The bot's Twitch login is missing or no longer valid; `python -m bot auth` must be re-run."""
```

- [ ] **Step 5: Write `bot/outbox.py`**

```python
"""Every message the bot sends goes through here: rate limit, bounded queue, coalescing."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from bot.activity_log import ActivityLog
from bot.clock import Clock
from bot.connectors.base import SendResult
from bot.text import truncate

logger = logging.getLogger(__name__)

SendFn = Callable[[str, str | None], Awaitable[SendResult]]


@dataclass
class OutMessage:
    text: str
    reply_to: str | None = None
    coalesce_key: str | None = None
    priority: bool = False


class Outbox:
    def __init__(
        self,
        send: SendFn,
        clock: Clock,
        log: ActivityLog,
        *,
        rate: float = 1.0,
        burst: int = 3,
        max_queue: int = 20,
        send_timeout: float = 10.0,
    ) -> None:
        self._send = send
        self._clock = clock
        self._log = log
        self.rate = rate
        self.burst = burst
        self.max_queue = max_queue
        self.send_timeout = send_timeout
        self._queue: list[OutMessage] = []
        self._tokens = float(burst)
        self._last_refill = clock.mono()
        self._wake = asyncio.Event()
        self._flush_lock = asyncio.Lock()  # run() and drain() must never send concurrently
        self._closed = False

    def __len__(self) -> int:
        return len(self._queue)

    def pending(self) -> list[str]:
        return [m.text for m in self._queue]

    def enqueue(
        self,
        text: str,
        *,
        reply_to: str | None = None,
        coalesce_key: str | None = None,
        priority: bool = False,
    ) -> bool:
        """Queue a message. Returns False if it was dropped (queue full, or the bot is shutting down)."""
        msg = OutMessage(truncate(text), reply_to, coalesce_key, priority)
        if self._closed:
            self._log.write("send_dropped", reason="shutdown", text=msg.text[:100])
            return False
        if coalesce_key is not None:
            for i, queued in enumerate(self._queue):
                if queued.coalesce_key == coalesce_key:
                    if queued.priority == priority:
                        self._queue[i] = msg  # same lane: replace in place
                        return True
                    del self._queue[i]  # changing lanes: re-insert below to keep priority order
                    break
        if len(self._queue) >= self.max_queue:
            normal = [i for i, m in enumerate(self._queue) if not m.priority]
            if not priority or not normal:
                self._log.write("send_dropped", reason="queue_full", text=msg.text[:100])
                return False
            dropped = self._queue.pop(normal[-1])
            self._log.write("send_dropped", reason="queue_full", text=dropped.text[:100])
        if priority:
            position = sum(1 for m in self._queue if m.priority)
            self._queue.insert(position, msg)
        else:
            self._queue.append(msg)
        self._wake.set()
        return True

    def _refill(self) -> None:
        now = self._clock.mono()
        self._tokens = min(float(self.burst), self._tokens + (now - self._last_refill) * self.rate)
        self._last_refill = now

    async def flush_ready(self) -> int:
        """Send as many queued messages as the rate limit allows right now."""
        async with self._flush_lock:
            self._refill()
            sent = 0
            while self._queue and self._tokens >= 1:
                msg = self._queue.pop(0)
                self._tokens -= 1
                sent += 1
                await self._send_one(msg)
            return sent

    async def _send_one(self, msg: OutMessage) -> None:
        """Send one message. Logs failures and drops; never raises (except cancellation)."""
        try:
            result = await asyncio.wait_for(self._send(msg.text, msg.reply_to), self.send_timeout)
            if not result.sent:
                self._log.write(
                    "send_dropped",
                    reason=result.drop_code or "unknown",
                    message=result.drop_message,
                    text=msg.text[:100],
                )
        except Exception as exc:  # timeouts and network errors must not kill the send loop
            logger.exception("send failed")
            self._log.write(
                "error", where="outbox.send", type=type(exc).__name__, message=str(exc), text=msg.text[:100]
            )

    def _next_delay(self) -> float:
        """How long the loop should wait: until the next token if messages are queued, else idle."""
        if not self._queue:
            return 1.0
        self._refill()
        return max(0.0, (1 - self._tokens) / self.rate)

    async def run(self, stop: asyncio.Event) -> None:
        """Background loop: send whenever there is something queued and a token available."""
        while not stop.is_set():
            try:
                await self.flush_ready()
                self._wake.clear()
                waiters = [asyncio.ensure_future(stop.wait()), asyncio.ensure_future(self._wake.wait())]
                try:
                    await asyncio.wait(waiters, timeout=self._next_delay(), return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for waiter in waiters:
                        waiter.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never let the loop die silently
                logger.exception("outbox loop error")
                self._log.write("error", where="outbox.run", type=type(exc).__name__, message=str(exc))
                await asyncio.sleep(1)

    def close(self) -> None:
        """Refuse new messages from now on (each one is logged as dropped)."""
        self._closed = True

    def discard(self, reason: str) -> int:
        """Drop everything queued, logging how many. Returns the count."""
        count = len(self._queue)
        if count:
            self._log.write("send_dropped", reason=reason, count=count)
            self._queue.clear()
        return count

    async def drain(self, timeout: float = 3.0) -> None:
        """Send what's left (still rate limited), giving up after `timeout` real seconds."""
        try:
            async with asyncio.timeout(timeout):
                while self._queue:
                    await self.flush_ready()
                    if self._queue:
                        await asyncio.sleep(self._next_delay() or 0.01)
        except TimeoutError:
            pass
        self.discard("shutdown")
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_outbox.py -q`

Expected: PASS (24 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add bot/connectors/__init__.py bot/connectors/base.py bot/outbox.py tests/test_outbox.py
git commit -m "Add connector types and the rate-limited outbox"
```

### Task 6: Cooldowns, permissions, test helpers

`check_command` starts both the per-user and the global cooldown only when neither is running, so a blocked attempt doesn't extend the wait. Expired entries are pruned at 10,000; if most are still live, the next prune waits until the dict doubles. `is_controller` is spec §10. `tests/helpers.py` starts here with `make_msg`; Tasks 11 and 15 append to it.

**Files:**
- Create: `bot/cooldowns.py`, `bot/permissions.py`, `tests/helpers.py`
- Test: `tests/test_cooldowns_permissions.py`

- [ ] **Step 1: Write `tests/helpers.py`**

```python
from datetime import datetime, timezone
from itertools import count

from bot.connectors.base import ChatMessage

_ids = count(1)


def make_msg(
    text: str,
    login: str = "alice",
    *,
    user_id: str | None = None,
    mod: bool = False,
    broadcaster: bool = False,
    source_channel_id: str | None = None,
    at: datetime | None = None,
) -> ChatMessage:
    return ChatMessage(
        id=f"msg-{next(_ids)}",
        user_id=user_id or f"id-{login}",
        login=login.lower(),
        display_name=login,
        text=text,
        is_broadcaster=broadcaster,
        is_moderator=mod,
        source_channel_id=source_channel_id,
        received_at=at or datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc),
    )
```

- [ ] **Step 2: Write the failing test `tests/test_cooldowns_permissions.py`**

```python
from bot.clock import FakeClock
from bot.cooldowns import Cooldowns
from bot.permissions import is_controller
from tests.helpers import make_msg


def test_user_cooldown_blocks_same_user_only(clock: FakeClock):
    cd = Cooldowns(clock)
    assert cd.check_command("8ball", "u1", 10, 0)
    assert not cd.check_command("8ball", "u1", 10, 0)
    assert cd.check_command("8ball", "u2", 10, 0)
    clock.advance(10)
    assert cd.check_command("8ball", "u1", 10, 0)


def test_global_cooldown_blocks_everyone(clock: FakeClock):
    cd = Cooldowns(clock)
    assert cd.check_command("dadjoke", "u1", 10, 5)
    assert not cd.check_command("dadjoke", "u2", 10, 5)
    clock.advance(5)
    assert cd.check_command("dadjoke", "u2", 10, 5)


def test_blocked_attempt_does_not_restart_cooldown(clock: FakeClock):
    cd = Cooldowns(clock)
    cd.check_command("fact", "u1", 10, 0)
    clock.advance(9)
    assert not cd.check_command("fact", "u1", 10, 0)
    clock.advance(1)
    assert cd.check_command("fact", "u1", 10, 0)


def test_ready(clock: FakeClock):
    cd = Cooldowns(clock)
    assert cd.ready("k")
    cd.trigger("k", 5)
    assert not cd.ready("k")
    clock.advance(5)
    assert cd.ready("k")


def test_prune_drops_expired_entries(clock: FakeClock, monkeypatch):
    monkeypatch.setattr("bot.cooldowns._PRUNE_AT", 10)
    cd = Cooldowns(clock)
    for i in range(10):
        cd.trigger(("old", i), 1)
    clock.advance(2)  # all ten have expired
    cd.trigger("new", 5)  # reaching the threshold prunes first
    assert len(cd._until) == 1


def test_prune_backs_off_when_entries_are_still_active(clock: FakeClock, monkeypatch):
    monkeypatch.setattr("bot.cooldowns._PRUNE_AT", 10)
    cd = Cooldowns(clock)
    for i in range(10):
        cd.trigger(("live", i), 60)
    cd.trigger("one more", 60)  # prune finds nothing expired
    assert cd._prune_at == 20  # next scan waits until the dict doubles
    for i in range(8):
        cd.trigger(("more", i), 60)
    assert len(cd._until) == 19  # no rescans in between, nothing lost


def test_remaining(clock: FakeClock):
    cd = Cooldowns(clock)
    cd.trigger("game", 30)
    clock.advance(12)
    assert cd.remaining("game") == 18


def test_is_controller():
    owners = {"id-robert"}
    assert is_controller(make_msg("x", broadcaster=True), owners)
    assert is_controller(make_msg("x", mod=True), owners)
    assert is_controller(make_msg("x", "robert"), owners)
    assert not is_controller(make_msg("x", "random"), owners)
```

- [ ] **Step 3: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_cooldowns_permissions.py -q`

Expected: FAIL. `ModuleNotFoundError: No module named 'bot.cooldowns'`

- [ ] **Step 4: Write `bot/cooldowns.py`**

```python
"""Per-user and global command cooldowns, measured on the monotonic clock."""

from __future__ import annotations

from collections.abc import Hashable

from bot.clock import Clock

_PRUNE_AT = 10_000


class Cooldowns:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._until: dict[Hashable, float] = {}
        self._prune_at = _PRUNE_AT

    def remaining(self, key: Hashable) -> float:
        """Seconds until `key` is ready again (0 if ready)."""
        return max(0.0, self._until.get(key, 0.0) - self._clock.mono())

    def ready(self, key: Hashable) -> bool:
        return self.remaining(key) == 0.0

    def trigger(self, key: Hashable, seconds: float) -> None:
        """Start (or restart) the cooldown for `key`."""
        if len(self._until) >= self._prune_at:
            now = self._clock.mono()
            self._until = {k: v for k, v in self._until.items() if v > now}
            # If most entries are still active, wait until the dict doubles before scanning again,
            # so a large live set costs amortized O(1) per call instead of a rescan every time.
            self._prune_at = max(_PRUNE_AT, 2 * len(self._until))
        self._until[key] = self._clock.mono() + seconds

    def check_command(self, command: str, user_id: str, user_seconds: float, global_seconds: float) -> bool:
        """True (and start both cooldowns) if neither the user's nor the global cooldown is running."""
        user_key, global_key = ("user", command, user_id), ("global", command)
        if not (self.ready(user_key) and self.ready(global_key)):
            return False
        self.trigger(user_key, user_seconds)
        self.trigger(global_key, global_seconds)
        return True
```

- [ ] **Step 5: Write `bot/permissions.py`**

```python
"""Who may use control commands: the broadcaster, any moderator, or a listed owner."""

from __future__ import annotations

from collections.abc import Collection

from bot.connectors.base import ChatMessage


def is_controller(msg: ChatMessage, owner_ids: Collection[str]) -> bool:
    return msg.is_broadcaster or msg.is_moderator or msg.user_id in owner_ids
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_cooldowns_permissions.py -q`

Expected: PASS (8 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add bot/cooldowns.py bot/permissions.py tests/helpers.py tests/test_cooldowns_permissions.py
git commit -m "Add cooldowns, permissions, and test helpers"
```

### Task 7: Command parsing, registry, and help text

`parse_command` strips invisible characters first, so a Chatterino duplicate like `?scramble\U000E0000` still parses, and splits on any whitespace. `add()` rejects duplicate names or aliases, names that aren't lowercase (lookup lowercases, so they'd be unreachable), and unknown groups (they'd silently vanish from `?help`). `usage` and `description` use `{p}` for the prefix, so changing the prefix in `config.toml` updates all help text. `cooldown` turns the per-user cooldown on; `global_cooldown` adds the chat-wide one, which game start commands and personal lookups (`?cookie`, `?gamestats`, `?help`) turn off, so one person's use never blocks another's. `help_overview()` lists the `listed` commands grouped Games, Stats, Fun; control commands and `?help` itself are unlisted.

**Files:**
- Create: `bot/commands.py`
- Test: `tests/test_commands.py`

- [ ] **Step 1: Write the failing test `tests/test_commands.py`**

```python
import pytest

from bot.commands import Command, CommandRegistry, parse_command


async def noop(ctx):
    pass


def cmd(name: str, group: str = "Fun", **kw) -> Command:
    return Command(name, noop, f"{{p}}{name}", f"Does {name}.", group, **kw)


def test_parse_command_basic():
    assert parse_command("?Scramble Animals", "?") == ("scramble", "Animals")
    assert parse_command("?help", "?") == ("help", "")


def test_parse_command_rejects_non_commands():
    assert parse_command("hello ?scramble", "?") is None
    assert parse_command("?", "?") is None
    assert parse_command("? scramble", "?") is None


def test_parse_command_strips_invisible_and_extra_spaces():
    assert parse_command("  ?cookie   give  bob \U000e0000", "?") == ("cookie", "give  bob")


def test_parse_command_splits_on_any_whitespace():
    assert parse_command("?scramble\tAnimals", "?") == ("scramble", "Animals")
    assert parse_command("?scramble" + chr(0xA0) + "food", "?") == ("scramble", "food")  # no-break space


def test_parse_command_custom_prefix():
    assert parse_command("!scramble", "!") == ("scramble", "")
    assert parse_command("!scramble", "?") is None


def test_registry_get_by_name_or_alias():
    reg = CommandRegistry("?")
    reg.add(cmd("help", group="Info", aliases=("commands",)))
    assert reg.get("commands").name == "help"
    assert reg.get("HELP").name == "help"
    assert reg.get("nope") is None


def test_command_cooldown_flags_default_on():
    c = cmd("fact")
    assert c.cooldown and c.global_cooldown


def test_registry_rejects_duplicates():
    reg = CommandRegistry("?")
    reg.add(cmd("fact"))
    with pytest.raises(ValueError, match="'fact' is already registered"):
        reg.add(cmd("other", aliases=("fact",)))


def test_registry_rejects_uppercase_names_and_unknown_groups():
    reg = CommandRegistry("?")
    with pytest.raises(ValueError, match="lowercase"):
        reg.add(cmd("Fact"))
    with pytest.raises(ValueError, match="unknown group"):
        reg.add(cmd("fact", group="Game"))


def test_help_overview_groups_in_order_and_skips_unlisted():
    reg = CommandRegistry("?")
    reg.add(cmd("8ball"))
    reg.add(cmd("scramble", group="Games"))
    reg.add(cmd("leaderboard", group="Stats"))
    reg.add(cmd("bot", group="Control", controller_only=True))
    reg.add(cmd("g", group="Games", listed=False))
    assert reg.help_overview() == (
        "Games: ?scramble | Stats: ?leaderboard | Fun: ?8ball · ?help <command> for details"
    )


def test_help_for_formats_usage_aliases_and_mod_note():
    reg = CommandRegistry("!")
    reg.add(cmd("help", group="Info", aliases=("commands",)))
    reg.add(cmd("bot", group="Control", controller_only=True))
    assert reg.help_for("help") == "!help · Does help. (also !commands)"
    assert reg.help_for("!bot") == "!bot · Does bot. Mods only."
    assert reg.help_for("missing") is None
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_commands.py -q`

Expected: FAIL. `ModuleNotFoundError: No module named 'bot.commands'`

- [ ] **Step 3: Write `bot/commands.py`**

```python
"""Command parsing, the command registry, and help text generated from it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from bot.connectors.base import ChatMessage
from bot.text import strip_invisible, truncate

GROUP_ORDER = ("Games", "Stats", "Fun")  # groups shown in the ?help overview, in this order
GROUPS = (*GROUP_ORDER, "Control", "Info")


def parse_command(text: str, prefix: str) -> tuple[str, str] | None:
    """'?Scramble animals' -> ('scramble', 'animals'). None if the text isn't a command."""
    text = strip_invisible(text).strip()
    if not text.startswith(prefix):
        return None
    body = text[len(prefix):]
    if not body or body[0].isspace():
        return None
    name, *rest = body.split(maxsplit=1)
    return name.lower(), rest[0].strip() if rest else ""


@dataclass
class CommandContext:
    msg: ChatMessage
    name: str  # the name typed, lowercase (may be an alias)
    args: str
    prefix: str
    reply: Callable[..., None]  # reply(text, priority=False): threaded reply to msg
    say: Callable[..., None]  # say(text, priority=False, coalesce_key=None): plain message

    @property
    def argv(self) -> list[str]:
        return self.args.split()


Handler = Callable[[CommandContext], Awaitable[None]]


@dataclass(frozen=True)
class Command:
    name: str
    handler: Handler
    usage: str  # "{p}leaderboard [game] [limit]"; {p} becomes the prefix
    description: str
    group: str  # "Games", "Stats", "Fun", "Control", or "Info"
    aliases: tuple[str, ...] = ()
    controller_only: bool = False
    cooldown: bool = True  # per-user cooldown applies
    global_cooldown: bool = True  # chat-wide cooldown also applies (off for personal commands like ?cookie)
    listed: bool = True  # shown in the ?help overview


@dataclass
class CommandRegistry:
    prefix: str
    _commands: dict[str, Command] = field(default_factory=dict)  # name and aliases -> command
    _order: list[Command] = field(default_factory=list)

    def add(self, cmd: Command) -> None:
        if cmd.group not in GROUPS:
            raise ValueError(f"command {cmd.name!r} has unknown group {cmd.group!r} (known: {', '.join(GROUPS)})")
        for name in (cmd.name, *cmd.aliases):
            if name != name.lower() or not name:
                raise ValueError(f"command names must be lowercase and non-empty, got {name!r}")
            if name in self._commands:
                raise ValueError(f"command name or alias {name!r} is already registered")
        for name in (cmd.name, *cmd.aliases):
            self._commands[name] = cmd
        self._order.append(cmd)

    def get(self, name: str) -> Command | None:
        return self._commands.get(name.lower())

    def all(self) -> list[Command]:
        return list(self._order)

    def _fmt(self, text: str) -> str:
        return text.replace("{p}", self.prefix)

    def help_overview(self) -> str:
        parts = []
        for group in GROUP_ORDER:
            names = [f"{self.prefix}{c.name}" for c in self._order if c.group == group and c.listed]
            if names:
                parts.append(f"{group}: {' '.join(names)}")
        return truncate(" | ".join(parts) + f" · {self.prefix}help <command> for details")

    def help_for(self, name: str) -> str | None:
        cmd = self.get(name.removeprefix(self.prefix))
        if cmd is None:
            return None
        text = f"{self._fmt(cmd.usage)} · {self._fmt(cmd.description)}"
        if cmd.aliases:
            text += " (also " + ", ".join(f"{self.prefix}{a}" for a in cmd.aliases) + ")"
        if cmd.controller_only:
            text += " Mods only."
        return truncate(text)
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_commands.py -q`

Expected: PASS (11 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bot/commands.py tests/test_commands.py
git commit -m "Add command parsing, registry, and help text"
```

### Task 8: Game interface and Scramble

`Game` and `Outcome` are spec §6. Games are pure and return `None` for chatter that isn't an attempt, so people just chatting don't count as players.

Scramble (spec §7) is a personal game:

- **Words:** single words of 4 to 10 ASCII letters with at least two distinct letters.
- **Scramble:** reshuffled until it differs from the word and spells none of the blocked fragments in `content/blocked_rot13.txt` (stored ROT13 so the file doesn't display them). Random letter orders can otherwise spell slurs: "giraffe" does about 5% of the time. A word that can't be scrambled cleanly is skipped.
- **Hints only on request:** the first `?hint` shows the first and last letters. The second shows about half the letters (first, last, and `max(1, ceil(n/2) - 2)` random middle letters). Further `?hint`s are ignored.
- **Points:** 10, 7, or 4 by hints taken.
- **Anagrams:** any word from the same category with exactly the same letters also wins (UNDERTALE or DELTARUNE), since the scramble fits both.
- **Attempt:** a single word with the same letter count as the answer.

`bot/games/__init__.py` starts as a docstring stub; Task 10 fills it in.

**Files:**
- Create: `bot/games/__init__.py` (stub), `bot/games/base.py`, `bot/games/scramble.py`
- Test: `tests/test_scramble.py`

- [ ] **Step 1: Write the failing test `tests/test_scramble.py`**

```python
import random

from bot.games.scramble import Scramble
from tests.helpers import make_msg


def make(assets, seed=1, category="animals") -> Scramble:
    return Scramble(category, random.Random(seed), assets)


def test_only_valid_words_and_categories(assets):
    # "cat" is too short and "sea lion" has a space; "hot cheetos" too
    assert Scramble.category_names(assets) == ["animals", "food"]
    game = make(assets)
    assert game.word == "ALLIGATOR"


def test_words_that_cannot_be_scrambled_are_skipped():
    from bot.games.scramble import _valid

    assert not _valid("aaaa") and not _valid("AaAa")
    assert _valid("abba")


def test_an_anagram_from_the_same_category_also_wins(tmp_path):
    import random as random_module

    from bot.assets import Assets

    root = tmp_path / "content"
    (root / "words").mkdir(parents=True)
    (root / "words" / "general.txt").write_text("canoe\nocean\n", encoding="utf-8")
    game = Scramble("general", random_module.Random(1), Assets(root))
    other = "ocean" if game.word == "CANOE" else "canoe"
    out = game.on_message(make_msg(other), None)
    assert out.finished and out.messages == [f"✅ alice got it: {other.upper()} (+10)"]


def test_scrambles_never_spell_a_blocked_fragment(assets):
    # the test content blocks "GAT"; unfiltered, some shuffles of ALLIGATOR would contain it
    scrambles = {make(assets, seed=seed).scrambled for seed in range(300)}
    assert scrambles and not any("GAT" in s for s in scrambles)


def test_word_that_cannot_be_scrambled_cleanly_is_skipped(tmp_path, monkeypatch):
    import random as random_module

    from bot.assets import Assets
    from bot.games import scramble as scramble_module

    root = tmp_path / "content"
    (root / "words").mkdir(parents=True)
    (root / "words" / "only.txt").write_text("abcd\nwxyz\n", encoding="utf-8")
    (root / "blocked_rot13.txt").write_text("n\n", encoding="utf-8")  # blocks every scramble containing "A"
    monkeypatch.setattr(scramble_module, "MAX_SHUFFLES", 50)
    for seed in range(20):
        assert scramble_module.Scramble("only", random_module.Random(seed), Assets(root)).word == "WXYZ"


def test_start_message_shows_scramble_that_differs(assets):
    game = make(assets)
    assert game.scrambled != game.word
    assert sorted(game.scrambled) == sorted(game.word)
    assert game.start() == f"🔤 Unscramble (animals): {game.scrambled} · 45s · {{p}}hint for a hint"


def test_unrelated_chatter_is_not_an_attempt(assets):
    game = make(assets)
    assert game.on_message(make_msg("lol"), None) is None
    assert game.on_message(make_msg("is it gator lol"), None) is None


def test_wrong_same_length_word_is_an_attempt(assets):
    game = make(assets)
    out = game.on_message(make_msg("crocodile"), None)
    assert out is not None and not out.finished


def test_correct_answer_wins_ten_points_case_insensitive(assets):
    game = make(assets)
    out = game.on_message(make_msg("AlLiGaToR \U000e0000", "bob"), None)
    assert out.finished and out.result == "won"
    assert out.awards == {"id-bob": 10} and out.winners == {"id-bob"}
    assert out.messages == ["✅ bob got it: ALLIGATOR (+10)"]


def hint(game: Scramble):
    return game.on_command("hint", "", make_msg("?hint"), None)


def test_hints_on_request_reduce_points(assets):
    game = make(assets)
    assert game.on_tick(30) is None  # no automatic hints
    assert hint(game).messages == ["💡 Hint: A _ _ _ _ _ _ _ R"]
    hint2 = hint(game).messages[0]
    revealed = [c for c in hint2.removeprefix("💡 Hint: ").split(" ") if c != "_"]
    assert len(revealed) == 5  # first, last, and 3 middle letters (about half of 9)
    assert hint(game) is None  # only two hints
    out = game.on_message(make_msg("alligator"), None)
    assert out.awards == {"id-alice": 4}


def test_one_hint_gives_seven_points(assets):
    game = make(assets)
    hint(game)
    assert game.on_message(make_msg("alligator"), None).awards == {"id-alice": 7}


def test_timeout_reveals_word(assets):
    out = make(assets).on_timeout()
    assert out.finished and out.result == "timeout"
    assert out.messages == ["⏰ Time's up! It was ALLIGATOR."]
    assert out.awards == {}
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_scramble.py -q`

Expected: FAIL. `ModuleNotFoundError: No module named 'bot.games'`

- [ ] **Step 3: Write the stub `bot/games/__init__.py`**

```python
"""Games. ALL_GAMES (added with the game manager) maps names to game classes."""
```

- [ ] **Step 4: Write `bot/games/base.py`**

```python
"""The interface every game implements. Games are pure: messages and time in, outcomes out."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Literal

from bot.assets import Assets
from bot.connectors.base import ChatMessage


@dataclass
class Outcome:
    messages: list[str] = field(default_factory=list)
    awards: dict[str, int] = field(default_factory=dict)  # user_id -> points
    winners: set[str] = field(default_factory=set)  # user_ids counted as winners
    finished: bool = False
    result: Literal["won", "timeout", "lost"] | None = None  # set when finished
    coalesce_key: str | None = None


class Game(ABC):
    name: ClassVar[str]  # also the start command
    title: ClassVar[str]  # "Scramble"
    usage: ClassVar[str]  # "{p}scramble [category]"
    description: ClassVar[str]  # shown by ?help <game>; {p} becomes the prefix
    time_limit: ClassVar[int]  # seconds
    # In-game commands: name -> (usage, description). Routed here only while this game runs.
    commands: ClassVar[dict[str, tuple[str, str]]] = {}

    def __init__(self, category: str | None, rng: random.Random, assets: Assets) -> None:
        self.category = category
        self.rng = rng
        self.assets = assets

    @classmethod
    def category_names(cls, assets: Assets) -> list[str]:
        """Categories this game can be started with. [] means the game has no categories."""
        return []

    @abstractmethod
    def start(self) -> str: ...

    def on_message(self, msg: ChatMessage, now: datetime) -> Outcome | None:
        """Plain chat while the game runs. None = not an attempt."""
        return None

    def on_command(self, name: str, args: str, msg: ChatMessage, now: datetime) -> Outcome | None:
        """One of this game's in-game commands. None = rejected / not an attempt."""
        return None

    def on_tick(self, elapsed: float) -> Outcome | None:
        return None

    @abstractmethod
    def on_timeout(self) -> Outcome: ...

    @abstractmethod
    def reveal(self) -> str:
        """The answer, for skip and stop messages."""
```

- [ ] **Step 5: Write `bot/games/scramble.py`**

```python
"""Scramble, a personal game: unscramble your word; hints lower the points."""

from __future__ import annotations

import codecs
import logging
import math
import random
from datetime import datetime

from bot.assets import Assets
from bot.connectors.base import ChatMessage
from bot.games.base import Game, Outcome
from bot.text import normalize

logger = logging.getLogger(__name__)

MAX_SHUFFLES = 200


def _blocked_fragments(assets: Assets) -> tuple[str, ...]:
    """Words a scramble must never spell by accident (stored ROT13 in content/blocked_rot13.txt)."""
    try:
        return tuple(codecs.decode(line, "rot13").upper() for line in assets.lines("blocked_rot13"))
    except FileNotFoundError:
        logger.warning("content/blocked_rot13.txt is missing: scrambles are not being filtered")
        return ()


def _valid(entry: str) -> bool:
    # Needs two distinct letters, or no scramble can differ from the word ("aaaa").
    return entry.isascii() and entry.isalpha() and 4 <= len(entry) <= 10 and len(set(entry.lower())) > 1


class Scramble(Game):
    name = "scramble"
    title = "Scramble"
    usage = "{p}scramble [category]"
    description = (
        "Your own word to unscramble: 10 points, or 7 or 4 if you take hints with {p}hint. "
        "{p}scramble categories lists topics. {p}skip ends your game."
    )
    time_limit = 45
    POINTS = (10, 7, 4)
    commands = {"hint": ("{p}hint", "Get a hint in your Scramble game (fewer points).")}

    @classmethod
    def category_names(cls, assets: Assets) -> list[str]:
        return [c for c in assets.categories() if any(_valid(w) for w in assets.words(c))]

    def __init__(self, category: str | None, rng: random.Random, assets: Assets) -> None:
        super().__init__(category, rng, assets)
        assert category is not None
        blocked = _blocked_fragments(assets)
        candidates = [w.upper() for w in assets.words(category) if _valid(w)]
        rng.shuffle(candidates)
        for word in candidates:  # almost always the first word works
            scrambled = self._scramble(word, blocked)
            if scrambled is not None:
                self.word, self.scrambled = word, scrambled
                break
        else:
            raise ValueError(f"no word in {category!r} can be scrambled cleanly")
        # Any word from this category that uses exactly the same letters is also a right answer
        # (e.g. UNDERTALE and DELTARUNE), since the scramble fits both.
        letters = sorted(self.word)
        self._answers = {w.lower() for w in candidates if sorted(w) == letters}
        self.hints_shown = 0
        middle = list(range(1, len(self.word) - 1))
        rng.shuffle(middle)
        self._reveal_order = middle

    def _scramble(self, word: str, blocked: tuple[str, ...]) -> str | None:
        """A shuffle that differs from the word and spells none of the blocked fragments, or None."""
        letters = list(word)
        for _ in range(MAX_SHUFFLES):
            self.rng.shuffle(letters)
            candidate = "".join(letters)
            if candidate != word and not any(fragment in candidate for fragment in blocked):
                return candidate
        return None

    def start(self) -> str:
        return f"🔤 Unscramble ({self.category}): {self.scrambled} · {self.time_limit}s · {{p}}hint for a hint"

    def _hint(self) -> str:
        shown = {0, len(self.word) - 1}
        if self.hints_shown >= 2:
            middle = max(1, math.ceil(len(self.word) / 2) - 2)  # about half the word in total
            shown |= set(self._reveal_order[:middle])
        return " ".join(ch if i in shown else "_" for i, ch in enumerate(self.word))

    def on_message(self, msg: ChatMessage, now: datetime) -> Outcome | None:
        guess = normalize(msg.text)
        if " " in guess or len(guess) != len(self.word):
            return None
        if guess not in self._answers:
            return Outcome()
        points = self.POINTS[self.hints_shown]
        return Outcome(
            messages=[f"✅ {msg.display_name} got it: {guess.upper()} (+{points})"],
            awards={msg.user_id: points},
            winners={msg.user_id},
            finished=True,
            result="won",
        )

    def on_command(self, name: str, args: str, msg: ChatMessage, now: datetime) -> Outcome | None:
        if name != "hint" or self.hints_shown >= len(self.POINTS) - 1:
            return None
        self.hints_shown += 1
        return Outcome(messages=[f"💡 Hint: {self._hint()}"])

    def on_timeout(self) -> Outcome:
        return Outcome(messages=[f"⏰ Time's up! It was {self.word}."], finished=True, result="timeout")

    def reveal(self) -> str:
        return self.word
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_scramble.py -q`

Expected: PASS (12 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add bot/games/__init__.py bot/games/base.py bot/games/scramble.py tests/test_scramble.py
git commit -m "Add the game interface and Scramble"
```

### Task 9: Hangman

Spec §7: a personal game with `?g` guessing (Robert's choice; plain chat is ignored so "W" and "L" never count).

- **Entries:** ASCII letters, spaces, hyphens, and apostrophes, 3+ letters, at most 30 characters. Word gaps show as `/` on the board.
- **Guessing:** at most one `?g` every 2 s. Repeated or non-letter single characters are rejected (`None`), and the cooldown isn't consumed.
- **Letter points:** each correct letter holds 1 point for its guesser.
- **Solving:** a wrong solve costs no lives and gets "❌ Not it.". The solve check ignores spaces and punctuation.
- **Win:** solving it, or revealing the last letter, gives 10 plus the held letter points.
- **Loss:** after 6 wrong letters or a timeout, nobody gets points.
- **Board:** wrong letters are listed alphabetically, so guess order can't make the bot spell a word.

The start message contains a literal `{p}`; the manager substitutes the prefix.

**Files:**
- Create: `bot/games/hangman.py`
- Test: `tests/test_hangman.py`

- [ ] **Step 1: Write the failing test `tests/test_hangman.py`**

```python
import random
from datetime import datetime, timedelta, timezone

from bot.games.hangman import Hangman
from tests.helpers import make_msg

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def make(assets, answer: str = "sea lion") -> Hangman:
    game = Hangman("animals", random.Random(1), assets)
    game.answer = answer.upper()  # pin the answer so tests are readable
    return game


def g(game: Hangman, args: str, login: str = "alice", at: float = 0):
    return game.on_command("g", args, make_msg(f"?g {args}", login), T0 + timedelta(seconds=at))


def test_categories_include_phrases(assets):
    assert Hangman.category_names(assets) == ["animals", "food"]


def test_start_shows_blank_board_with_word_gap(assets):
    game = make(assets)
    assert game.board() == "_ _ _ / _ _ _ _"
    assert game.start() == (
        "🪢 Hangman (animals): _ _ _ / _ _ _ _ · guess with {p}g <letter> or {p}g <answer> · 6 lives, 120s"
    )


def test_plain_chat_is_ignored(assets):
    game = make(assets)
    assert game.on_message(make_msg("W"), T0) is None
    assert game.on_message(make_msg("sea lion"), T0) is None


def test_correct_letter_reveals_and_holds_a_point(assets):
    game = make(assets)
    out = g(game, "a")
    assert out.messages == ["_ _ A / _ _ _ _ | wrong: - (0/6)"]
    assert out.coalesce_key == "hangman-board"
    assert game.held == {"id-alice": 1}


def test_wrong_letter_costs_a_life(assets):
    game = make(assets)
    out = g(game, "z")
    assert out.messages == ["_ _ _ / _ _ _ _ | wrong: Z (1/6)"]


def test_wrong_letters_are_shown_sorted_so_guess_order_cannot_spell_words(assets):
    game = make(assets, "sea lion")
    for i, letter in enumerate("zxb"):
        out = g(game, letter, at=2 * i)
    assert out.messages == ["_ _ _ / _ _ _ _ | wrong: B X Z (3/6)"]


def test_repeated_letter_is_ignored(assets):
    game = make(assets)
    g(game, "a", "alice")
    assert g(game, "A", "bob") is None


def test_non_letter_single_character_is_ignored(assets):
    assert g(make(assets), "7") is None


def test_guess_cooldown(assets):
    game = make(assets)
    assert g(game, "a", at=0) is not None
    assert g(game, "e", at=1) is None
    assert g(game, "e", at=2) is not None


def test_wrong_solve_attempt_costs_no_lives(assets):
    game = make(assets)
    out = g(game, "walrus")
    assert out is not None and not out.finished and out.messages == ["❌ Not it."]
    assert game.wrong == []


def test_extra_words_after_g_are_a_solve_attempt(assets):
    game = make(assets)
    out = g(game, "e please")
    assert out.messages == ["❌ Not it."] and game.guessed == set()


def test_repeated_letters_reveal_together_for_one_point(assets):
    game = make(assets, "lollipop")
    out = g(game, "l")
    assert game.board() == "L _ L L _ _ _ _"
    assert game.held == {"id-alice": 1}
    assert not out.finished


def test_punctuation_is_shown_and_optional_when_solving(assets):
    game = make(assets, "x-ray")
    assert game.board() == "_ - _ _ _"
    assert g(game, "xray").result == "won"


def test_full_solve_wins_with_held_points(assets):
    game = make(assets)
    g(game, "a", "alice")
    out = g(game, "Sea-Lion", "bob")
    assert out.finished and out.result == "won"
    assert out.awards == {"id-alice": 1, "id-bob": 10}
    assert out.winners == {"id-bob"}
    assert out.messages == ["🎉 bob solved it: SEA LION (+10)"]


def test_solve_ignores_spaces(assets):
    out = g(make(assets), "sealion")
    assert out.result == "won"


def test_revealing_last_letter_wins(assets):
    game = make(assets, "cat")
    g(game, "c", "a1")
    g(game, "a", "a2")
    out = g(game, "t", "a3")
    assert out.result == "won"
    assert out.awards == {"id-a1": 1, "id-a2": 1, "id-a3": 11}


def test_six_wrong_letters_loses_and_awards_nothing(assets):
    game = make(assets)
    g(game, "a", "helper")
    outs = [g(game, letter, f"u{i}") for i, letter in enumerate("bdfghj")]
    last = outs[-1]
    assert last.finished and last.result == "lost"
    assert last.awards == {}
    assert last.messages == ["💀 Out of lives! The word was SEA LION."]


def test_timeout(assets):
    out = make(assets).on_timeout()
    assert out.result == "timeout" and out.messages == ["💀 Time's up! The word was SEA LION."]
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_hangman.py -q`

Expected: FAIL. `ModuleNotFoundError: No module named 'bot.games.hangman'`

- [ ] **Step 3: Write `bot/games/hangman.py`**

```python
"""Hangman, a personal game: guess with ?g <letter> or ?g <answer>. Plain chat never counts."""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import datetime

from bot.assets import Assets
from bot.connectors.base import ChatMessage
from bot.games.base import Game, Outcome
from bot.text import normalize

_ALLOWED_PUNCT = " -'"


def _valid(entry: str) -> bool:
    letters = sum(ch.isalpha() for ch in entry)
    return (
        entry.isascii()
        and letters >= 3
        and len(entry) <= 30
        and all(ch.isalpha() or ch in _ALLOWED_PUNCT for ch in entry)
    )


def _compact(text: str) -> str:
    return normalize(text).replace(" ", "")


class Hangman(Game):
    name = "hangman"
    title = "Hangman"
    usage = "{p}hangman [category]"
    description = (
        "Your own hidden word: guess with {p}g <letter> or {p}g <answer>. 6 wrong letters and you lose. "
        "Win to score 10 points plus 1 per correct letter. {p}hangman categories lists topics. "
        "{p}skip ends your game."
    )
    time_limit = 120
    LIVES = 6
    GUESS_COOLDOWN = 2.0
    WIN_POINTS = 10
    commands = {"g": ("{p}g <letter|answer>", "Guess a letter or the whole answer in your Hangman game.")}

    @classmethod
    def category_names(cls, assets: Assets) -> list[str]:
        return [c for c in assets.categories() if any(_valid(w) for w in assets.words(c))]

    def __init__(self, category: str | None, rng: random.Random, assets: Assets) -> None:
        super().__init__(category, rng, assets)
        assert category is not None
        self.answer = rng.choice([w for w in assets.words(category) if _valid(w)]).upper()
        self.guessed: set[str] = set()
        self.wrong: list[str] = []
        self.held: defaultdict[str, int] = defaultdict(int)  # user_id -> letter points
        self._last_guess: dict[str, datetime] = {}

    def board(self) -> str:
        cells = []
        for ch in self.answer:
            if ch == " ":
                cells.append("/")
            elif ch.isalpha():
                cells.append(ch if ch in self.guessed else "_")
            else:
                cells.append(ch)
        return " ".join(cells)

    def status(self) -> str:
        wrong = " ".join(sorted(self.wrong)) or "-"  # sorted, so guess order can't spell a word
        return f"{self.board()} | wrong: {wrong} ({len(self.wrong)}/{self.LIVES})"

    def _hidden(self) -> set[str]:
        return {ch for ch in self.answer if ch.isalpha()} - self.guessed

    def start(self) -> str:
        return (
            f"🪢 Hangman ({self.category}): {self.board()} · guess with {{p}}g <letter> or "
            f"{{p}}g <answer> · {self.LIVES} lives, {self.time_limit}s"
        )

    def on_command(self, name: str, args: str, msg: ChatMessage, now: datetime) -> Outcome | None:
        guess = normalize(args)
        if name != "g" or not guess:
            return None
        last = self._last_guess.get(msg.user_id)
        if last is not None and (now - last).total_seconds() < self.GUESS_COOLDOWN:
            return None
        if len(guess) == 1:
            letter = guess.upper()
            if not ("A" <= letter <= "Z") or letter in self.guessed or letter in self.wrong:
                return None
            self._last_guess[msg.user_id] = now
            return self._guess_letter(letter, msg)
        self._last_guess[msg.user_id] = now
        if _compact(guess) == _compact(self.answer):
            return self._win(msg)
        return Outcome(messages=["❌ Not it."])  # a wrong solve attempt costs no lives

    def _guess_letter(self, letter: str, msg: ChatMessage) -> Outcome:
        if letter in self.answer:
            self.guessed.add(letter)
            self.held[msg.user_id] += 1
            if not self._hidden():
                return self._win(msg)
            return Outcome(messages=[self.status()], coalesce_key="hangman-board")
        self.wrong.append(letter)
        if len(self.wrong) >= self.LIVES:
            return Outcome(
                messages=[f"💀 Out of lives! The word was {self.answer}."], finished=True, result="lost"
            )
        return Outcome(messages=[self.status()], coalesce_key="hangman-board")

    def _win(self, msg: ChatMessage) -> Outcome:
        awards = dict(self.held)
        awards[msg.user_id] = awards.get(msg.user_id, 0) + self.WIN_POINTS
        return Outcome(
            messages=[f"🎉 {msg.display_name} solved it: {self.answer} (+{awards[msg.user_id]})"],
            awards=awards,
            winners={msg.user_id},
            finished=True,
            result="won",
        )

    def on_timeout(self) -> Outcome:
        return Outcome(messages=[f"💀 Time's up! The word was {self.answer}."], finished=True, result="timeout")

    def reveal(self) -> str:
        return self.answer
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_hangman.py -q`

Expected: PASS (18 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bot/games/hangman.py tests/test_hangman.py
git commit -m "Add Hangman with ?g guessing"
```

### Task 10: Game registry and GameManager (personal games)

`ALL_GAMES` maps names to classes; `config.toml` picks which run. `GameManager` runs **personal** games (spec §6, revised): each player has at most one game, keyed by user ID, and many players can play at once.

- **Registration:** one start command per game (no command cooldowns: the per-player game cooldown is the only limit, and "can't start" and category-list replies are rate-limited to one per 5 s per player and game), `?skip`, and each game's in-game commands (`?hint`, `?g`) as hidden, cooldown-free commands that reach only the sender's own game.
- **Starting:** `?<game> categories`, one game per player, the per-player cooldown (10 s after a game ends), the running limit (25), the busy brake (an `is_busy()` callback the core wires to the outbox backlog), unknown categories, and the random category pick.
- **Routing:** a player's plain chat goes only to their own game.
- **Replies:** threaded under the player's latest message, with coalesce keys unique per round (`hangman-board:<round key>`). The player's current names refresh on every message.
- **Ending:** the tick ends timed-out games (forcing it if a game's `on_timeout` doesn't finish). `?skip` ends the sender's game. `stop_all()` ends every game (for `?stopgame`, `?bot off`, and shutdown).
- **Errors:** an exception in game code ends only that player's game, as `stopped` with "Game ended due to an error."
- **Finishing:** never runs twice for a session. It records a one-player round, logs `game_end`, replies, and starts that player's cooldown (kept in a `Cooldowns`, so it's pruned).

**Files:**
- Modify: `bot/games/__init__.py` (replace the stub)
- Create: `bot/games/manager.py`
- Test: `tests/test_manager.py`

- [ ] **Step 1: Write the failing test `tests/test_manager.py`**

```python
import json
import random

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


class Harness:
    def __init__(self, tmp_path, clock: FakeClock, assets, max_games: int = 25):
        self.clock = clock
        self.said: list[tuple[str, dict]] = []  # everything the manager sent: (text, kwargs)
        self.replies: list[str] = []  # direct command replies (ctx.reply)
        self.busy = False
        self.stats = StatsStore(":memory:")
        self.log = ActivityLog(tmp_path / "logs", clock)
        self.manager = GameManager(
            games={"scramble": Scramble, "hangman": Hangman, "boom": Boom, "stubborn": Stubborn,
                   "noresult": NoResult, "anycommand": AnyCommand, "brokenstart": BrokenStart},
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
        "scramble", "hangman", "boom", "stubborn", "noresult", "anycommand", "brokenstart", "skip", "hint", "g"
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
    h.clock.advance(44)
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
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_manager.py -q`

Expected: FAIL. `ModuleNotFoundError: No module named 'bot.games.manager'`

- [ ] **Step 3: Write `bot/games/__init__.py`**

```python
"""All game classes, by name. config.toml's [games] enabled picks which ones run."""

from bot.games.base import Game
from bot.games.hangman import Hangman
from bot.games.scramble import Scramble

ALL_GAMES: dict[str, type[Game]] = {cls.name: cls for cls in (Scramble, Hangman)}
```

- [ ] **Step 4: Write `bot/games/manager.py`**

```python
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
from bot.commands import Command, CommandContext, CommandRegistry, Handler
from bot.connectors.base import ChatMessage
from bot.cooldowns import Cooldowns
from bot.games.base import Game, Outcome
from bot.stats import PlayerResult, RoundRecord, StatsStore

logger = logging.getLogger(__name__)

Say = Callable[..., None]  # say(text, *, reply_to=None, coalesce_key=None, priority=False)

NOTICE_SECONDS = 5.0  # at most one "can't start" or category-list reply per player this often


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

    # registration

    def register(self, registry: CommandRegistry) -> None:
        # Start commands have no command cooldowns: the per-player game cooldown is the only limit
        # on starting, and refusal replies are rate-limited separately (see _notice).
        for cls in self.games.values():
            handler = self._start_handler(cls)
            registry.add(Command(cls.name, handler, cls.usage, cls.description, "Games", cooldown=False))
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
        key = f"{coalesce_key}:{session.key}" if coalesce_key else None  # unique per player and round
        self._say(text.replace("{p}", self.prefix), reply_to=session.reply_to, coalesce_key=key)

    def _notice(self, ctx: CommandContext, text: str) -> None:
        """Reply to a start request we can't fulfil, at most once per NOTICE_SECONDS per player per game."""
        if self._cooldowns.check_command(f"notice:{ctx.name}", ctx.msg.user_id, NOTICE_SECONDS, 0):
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
                self._finish(session, "stopped", ["Game ended due to an error."], {}, set())
            return None

    # commands

    def _start_handler(self, cls: type[Game]) -> Handler:
        async def handler(ctx: CommandContext) -> None:
            await self._start(cls, ctx)

        return handler

    async def _start(self, cls: type[Game], ctx: CommandContext) -> None:
        arg = ctx.args.strip().lower()
        categories = cls.category_names(self.assets)
        uid = ctx.msg.user_id
        if arg == "categories":
            self._notice(ctx, f"{cls.title} categories: {', '.join(categories)}")
            return
        if uid in self.sessions:
            self._notice(ctx, f"You already have a {self.sessions[uid].game.name} game running.")
            return
        remaining = self.cooldown_remaining(uid)
        if remaining > 0:
            self._notice(ctx, f"Your next game in {math.ceil(remaining)}s.")
            return
        if len(self.sessions) >= self.max_games or self._is_busy():
            self._notice(ctx, "Too many games running right now, try again in a moment.")
            return
        if categories and arg and arg not in categories:
            self._notice(ctx, f"Unknown category. {cls.title} categories: {', '.join(categories)}")
            return
        category = (arg or self.rng.choice(categories)) if categories else None
        try:
            game = cls(category, self.rng, self.assets)
            opening = game.start()
        except Exception as exc:
            logger.exception("could not start %s", cls.name)
            self.log.write("error", where=f"game:{cls.name}.start", type=type(exc).__name__, message=str(exc))
            self._notice(ctx, "Couldn't start that game.")
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
        self.log.write("game_start", round=session.key, game=cls.name, category=category, player=ctx.msg.login)
        self._reply(session, opening)

    async def _skip_command(self, ctx: CommandContext) -> None:
        session = self.sessions.get(ctx.msg.user_id)
        if session is None:
            return
        self._seen(session, ctx.msg)
        answer = self._guard(session, f"{session.game.name}.reveal", session.game.reveal)
        if answer is not None:
            self._finish(session, "skipped", [f"⏭️ Skipped. It was {answer}."], {}, set())

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

    def tick(self) -> None:
        for session in list(self.sessions.values()):
            if self.sessions.get(session.user_id) is not session:
                continue
            elapsed = self.clock.mono() - session.start_mono
            game = session.game
            if elapsed >= game.time_limit:
                outcome = self._guard(session, f"{game.name}.on_timeout", game.on_timeout)
                self._handle(session, outcome, default_result="timeout")
                if self.sessions.get(session.user_id) is session:  # the game didn't end itself: force it
                    self._finish(session, "timeout", [], {}, set())
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

    def _handle(self, session: Session, outcome: Outcome | str | None, default_result: str = "won") -> None:
        if not isinstance(outcome, Outcome) or self.sessions.get(session.user_id) is not session:
            return
        if outcome.finished:
            result = outcome.result or default_result
            self._finish(session, result, outcome.messages, outcome.awards, outcome.winners)
        else:
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
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_manager.py -q`

Expected: PASS (28 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add bot/games/__init__.py bot/games/manager.py tests/test_manager.py
git commit -m "Add the game registry and personal-game manager"
```

### Task 11: HTTP client and fun commands

`HttpClient.get_json` never raises. On a timeout (3 s), an HTTP error, or bad JSON, it returns `None`, and the command uses a bundled fallback line (spec §5). API text must be a string. It's NFC-normalized and stripped of invisible and control characters. It falls back if it's over 400 characters, contains a link or @mention, starts with a lowercase letter (it looks cut off), or contains a blocked word: the bot as a mod skips Twitch's chat filters, so this is the only filter. `BlockedWords` reads `content/blocked_prose_rot13.txt` (written in Task 18; until then nothing is blocked). Each pattern says how it matches: `word` is the whole word or its plural, `word*` any word starting with it, and `*word*` any word containing it. A short list of innocent look-alikes (analysis, Dickinson, Scunthorpe, ...) is exempt, as are "Homo sapiens" and "Maine Coon". Response bodies are capped at 64 KB. All four API URLs and response shapes were checked live on 2026-10-04.

`?cookie` rules:

- One cookie per user per UTC day.
- `?cookie give <user>` validates the name and checks that the account exists through the connector's `lookup_user` (5 s timeout). A name that isn't found is never echoed back. Mentions use the login when a display name is localized.
- `?cookie` with any argument other than `give` shows usage instead of spending the cookie.
- A rejected give doesn't use up the cookie.
- Giving uses the giver's daily cookie; the recipient's own cookie is unaffected.

`FakeHttp` goes into `tests/helpers.py` because Task 15 reuses it.

**Files:**
- Create: `bot/http.py`, `bot/fun.py`
- Modify: `tests/helpers.py` (append `FakeHttp`)
- Test: `tests/test_http.py`, `tests/test_fun.py`

- [ ] **Step 1: Write the failing test `tests/test_http.py`**

```python
import asyncio

from aiohttp import web
from aiohttp.test_utils import TestServer

from bot.http import HttpClient


async def serve(handler) -> TestServer:
    app = web.Application()
    app.router.add_get("/", handler)
    server = TestServer(app)
    await server.start_server()
    return server


async def test_get_json_returns_parsed_body():
    async def ok(request):
        assert request.headers["User-Agent"].startswith("offline-chat-bot")
        return web.json_response({"fact": "cats sleep a lot"})

    server = await serve(ok)
    client = HttpClient(timeout=1)
    try:
        assert await client.get_json(str(server.make_url("/"))) == {"fact": "cats sleep a lot"}
    finally:
        await client.close()
        await server.close()


async def test_get_json_returns_none_on_timeout():
    async def slow(request):
        await asyncio.sleep(1)
        return web.json_response({})

    server = await serve(slow)
    client = HttpClient(timeout=0.2)
    try:
        assert await client.get_json(str(server.make_url("/"))) is None
    finally:
        await client.close()
        await server.close()


async def test_get_json_parses_json_sent_as_text_and_sends_headers():
    seen = {}

    async def plain(request):
        seen["accept"] = request.headers.get("Accept")
        return web.Response(text='{"joke": "ha"}', content_type="text/plain")

    server = await serve(plain)
    client = HttpClient(timeout=1)
    try:
        url = str(server.make_url("/"))
        assert await client.get_json(url, headers={"Accept": "application/json"}) == {"joke": "ha"}
        assert seen["accept"] == "application/json"
    finally:
        await client.close()
        await server.close()


async def test_get_json_reads_a_body_sent_in_pieces():
    async def chunked(request):
        resp = web.StreamResponse(headers={"Content-Type": "application/json"})
        await resp.prepare(request)
        await resp.write(b'{"fact": "cats ')
        await asyncio.sleep(0.02)
        await resp.write(b'purr"}')
        await resp.write_eof()
        return resp

    server = await serve(chunked)
    client = HttpClient(timeout=1)
    try:
        assert await client.get_json(str(server.make_url("/"))) == {"fact": "cats purr"}
    finally:
        await client.close()
        await server.close()


async def test_get_json_refuses_oversized_bodies(monkeypatch):
    import bot.http

    monkeypatch.setattr(bot.http, "MAX_BODY", 10)

    async def big(request):
        return web.json_response({"fact": "x" * 100})

    server = await serve(big)
    client = HttpClient(timeout=1)
    try:
        assert await client.get_json(str(server.make_url("/"))) is None
    finally:
        await client.close()
        await server.close()


async def test_get_json_returns_none_for_non_json_200():
    async def html(request):
        return web.Response(text="<html>challenge</html>", content_type="text/html")

    server = await serve(html)
    client = HttpClient(timeout=1)
    try:
        assert await client.get_json(str(server.make_url("/"))) is None
    finally:
        await client.close()
        await server.close()


async def test_get_json_returns_none_on_http_error():
    async def broken(request):
        return web.Response(status=500)

    server = await serve(broken)
    client = HttpClient(timeout=1)
    try:
        assert await client.get_json(str(server.make_url("/"))) is None
    finally:
        await client.close()
        await server.close()
```

- [ ] **Step 2: Write the failing test `tests/test_fun.py`**

```python
import asyncio
import random

import pytest

from bot.clock import FakeClock
from bot.commands import CommandContext, CommandRegistry
from bot.connectors.base import UserRef
from bot.fun import register_fun
from bot.stats import StatsStore
from tests.helpers import FakeHttp, make_msg


class Fun:
    def __init__(self, assets, clock: FakeClock, http: FakeHttp | None = None):
        self.http = http or FakeHttp()
        self.stats = StatsStore(":memory:")
        self.registry = CommandRegistry("?")
        self.replies: list[str] = []
        self.said: list[str] = []
        self.known = {"bob": UserRef("id-bob", "bob", "Bob")}

        async def default_lookup(login):
            return self.known.get(login)

        self.lookup = default_lookup

        async def lookup(login):
            return await self.lookup(login)

        register_fun(
            self.registry, assets=assets, rng=random.Random(1), http=self.http,
            stats=self.stats, clock=clock, lookup_user=lookup,
        )

    async def run(self, text: str, login: str = "alice") -> None:
        name, _, args = text.removeprefix("?").partition(" ")
        ctx = CommandContext(
            make_msg(text, login), name, args, "?",
            lambda t, **kw: self.replies.append(t), lambda t, **kw: self.said.append(t),
        )
        await self.registry.get(name).handler(ctx)


@pytest.fixture
def fun(assets, clock) -> Fun:
    return Fun(assets, clock)


async def test_8ball_and_coinflip(fun: Fun):
    await fun.run("?8ball will I win?")
    await fun.run("?coinflip")
    assert fun.replies[0] in ("🎱 Yes.", "🎱 No.")
    assert fun.replies[1] in ("🪙 Heads", "🪙 Tails")


async def test_facts_use_api_and_clean_whitespace(assets, clock):
    http = FakeHttp({
        "https://catfact.ninja/fact": {"fact": "Cats  have\nwhiskers."},
        "https://dogapi.dog/api/v2/facts": {"data": [{"attributes": {"body": "Dogs bark."}}]},
        "https://uselessfacts.jsph.pl/api/v2/facts/random?language=en": {"text": "Honey never spoils."},
        "https://icanhazdadjoke.com/": {"joke": "I'm reading a book on anti-gravity."},
    })
    fun = Fun(assets, clock, http)
    for name in ("catfact", "dogfact", "fact", "dadjoke"):
        await fun.run(f"?{name}")
    assert fun.replies == [
        "🐱 Cats have whiskers.",
        "🐶 Dogs bark.",
        "💡 Honey never spoils.",
        "😄 I'm reading a book on anti-gravity.",
    ]
    assert http.calls[3] == ("https://icanhazdadjoke.com/", {"Accept": "application/json"})


async def test_fact_falls_back_when_api_fails_or_is_malformed_or_too_long(assets, clock):
    http = FakeHttp({
        "https://catfact.ninja/fact": None,
        "https://dogapi.dog/api/v2/facts": {"unexpected": True},
        "https://uselessfacts.jsph.pl/api/v2/facts/random?language=en": {"text": "x" * 401},
        "https://icanhazdadjoke.com/": {"joke": None},
    })
    fun = Fun(assets, clock, http)
    for name in ("catfact", "dogfact", "fact", "dadjoke"):
        await fun.run(f"?{name}")
    assert fun.replies == [
        "🐱 fallback catfacts line",
        "🐶 fallback dogfacts line",
        "💡 fallback facts line",
        "😄 fallback dadjokes line",
    ]


@pytest.mark.parametrize("bad", [
    "Visit https://spam.example now", "see www.spam.example", "ask @someone about it", 42, ["a", "b"],
])
async def test_fact_with_links_mentions_or_wrong_type_falls_back(assets, clock, bad):
    fun = Fun(assets, clock, FakeHttp({"https://catfact.ninja/fact": {"fact": bad}}))
    await fun.run("?catfact")
    assert fun.replies == ["🐱 fallback catfacts line"]


async def test_fact_text_keeps_decomposed_accents(assets, clock):
    text = "E" + chr(0x0301) + "clairs are pastries."
    fun = Fun(assets, clock, FakeHttp({"https://catfact.ninja/fact": {"fact": text}}))
    await fun.run("?catfact")
    assert fun.replies == ["🐱 " + chr(0x00C9) + "clairs are pastries."]


@pytest.mark.parametrize("text, safe", [
    ("Gat is a whole word.", False),  # "gat": the whole word...
    ("Gats too.", False),  # ... or its plural
    ("Gather round.", True),  # ... but not a word starting with it
    ("Some people are gatoring around.", False),  # "gator*": any word starting with it
    ("Navigators use the stars.", True),  # ... but not one merely containing it
    ("A megablobfish swam by.", False),  # "*blob*": any word containing it
    (" was a famous idea.", False),  # starts lowercase: cut off
    ("42 is the answer.", True),
    ('"Quoted" facts are fine.', True),
    (chr(0x201C) + "Curly" + chr(0x201D) + " quotes and $5 are fine.", True),
])
async def test_fact_filter_blocks_bad_words_and_truncated_text(content_dir, clock, text, safe):
    from bot.assets import Assets

    (content_dir / "blocked_prose_rot13.txt").write_text("tng\ntngbe*\n*oybo*\n", encoding="utf-8")
    fun = Fun(Assets(content_dir), clock, FakeHttp({"https://catfact.ninja/fact": {"fact": text}}))
    await fun.run("?catfact")
    assert (fun.replies[0] != "🐱 fallback catfacts line") is safe


async def test_fact_text_is_stripped_of_invisible_and_control_characters(assets, clock):
    text = "Cats" + chr(0x202E) + " purr" + chr(0x07) + "."
    fun = Fun(assets, clock, FakeHttp({"https://catfact.ninja/fact": {"fact": text}}))
    await fun.run("?catfact")
    assert fun.replies == ["🐱 Cats purr."]


async def test_cookie_once_per_utc_day(fun: Fun, clock: FakeClock):
    await fun.run("?cookie")
    assert fun.replies[-1] == "🥠 Good things are coming."
    await fun.run("?cookie")
    assert fun.replies[-1] == "You already opened today's cookie. Next one in 12h 0m (00:00 UTC)."
    clock.advance(12 * 3600)
    await fun.run("?cookie")
    assert fun.replies[-1] == "🥠 Good things are coming."


async def test_cookie_give(fun: Fun):
    await fun.run("?cookie give @Bob")
    assert fun.said == ["🥠 @alice gave @Bob a fortune cookie: Good things are coming."]
    await fun.run("?cookie")
    assert fun.replies[-1].startswith("You already opened today's cookie.")
    await fun.run("?cookie", "bob")  # the recipient's own cookie is unaffected
    assert fun.replies[-1] == "🥠 Good things are coming."


async def test_cookie_give_rejections_do_not_use_the_cookie(fun: Fun):
    await fun.run("?cookie give")
    await fun.run("?cookie give not/valid")
    await fun.run("?cookie give alice")
    await fun.run("?cookie give ghost_user")
    await fun.run("?cookie gift bob")
    assert fun.replies == [
        "Usage: ?cookie or ?cookie give <username>",
        "That's not a valid username.",
        "You can't give a cookie to yourself.",
        "Couldn't find that user.",
        "Usage: ?cookie or ?cookie give <username>",
    ]
    await fun.run("?cookie")
    assert fun.replies[-1] == "🥠 Good things are coming."


async def test_cookie_give_after_cookie_used(fun: Fun):
    await fun.run("?cookie")
    await fun.run("?cookie give bob")
    assert fun.replies[-1].startswith("You already opened today's cookie.")
    assert fun.said == []


async def test_cookie_give_lookup_timeout(assets, clock, monkeypatch):
    import bot.fun

    monkeypatch.setattr(bot.fun, "LOOKUP_TIMEOUT", 0.05)
    fun = Fun(assets, clock)

    async def slow(login):
        await asyncio.sleep(1)

    fun.lookup = slow
    await fun.run("?cookie give bob")
    assert fun.replies == ["Couldn't check that user right now. Try again in a bit."]
    await fun.run("?cookie")
    assert fun.replies[-1] == "🥠 Good things are coming."


async def test_cookie_give_mentions_login_for_localised_display_names(fun: Fun):
    fun.known["bob"] = UserRef("id-bob", "bob", "\u9cf3\u51f0")
    await fun.run("?cookie give bob")
    assert fun.said == ["🥠 @alice gave @bob a fortune cookie: Good things are coming."]
```

- [ ] **Step 3: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_http.py tests/test_fun.py -q`

Expected: FAIL. `ModuleNotFoundError: No module named 'bot.http'`

- [ ] **Step 4: Append `FakeHttp` to the end of `tests/helpers.py`**

```python
class FakeHttp:
    def __init__(self, responses: dict[str, object] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict | None]] = []

    async def get_json(self, url, headers=None):
        self.calls.append((url, headers))
        return self.responses.get(url)

    async def close(self):
        pass
```

- [ ] **Step 5: Write `bot/http.py`**

```python
"""A small shared HTTP client for the fact and joke APIs. Never raises: failures return None."""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from bot import __version__

logger = logging.getLogger(__name__)

USER_AGENT = f"offline-chat-bot/{__version__} (Twitch chat bot)"
MAX_BODY = 64_000  # bytes; fact and joke responses are tiny


class HttpClient:
    def __init__(self, timeout: float = 3.0) -> None:
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    async def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any | None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout), headers={"User-Agent": USER_AGENT}
            )
        try:
            async with self._session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning("GET %s -> HTTP %s", url, resp.status)
                    return None
                body = bytearray()
                async for chunk in resp.content.iter_chunked(16_384):  # read() alone may return a partial body
                    body += chunk
                    if len(body) > MAX_BODY:
                        logger.warning("GET %s: body over %d bytes", url, MAX_BODY)
                        return None
                return json.loads(body)
        except Exception as exc:  # timeouts, DNS, bad JSON: all fall back
            logger.warning("GET %s failed: %s", url, type(exc).__name__)
            return None

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
```

- [ ] **Step 6: Write `bot/fun.py`**

```python
"""Quick one-shot commands: ?8ball ?coinflip ?catfact ?dogfact ?fact ?dadjoke ?cookie."""

from __future__ import annotations

import asyncio
import codecs
import json
import random
import re
import unicodedata
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta, timezone
from typing import Any

from bot.assets import Assets
from bot.clock import Clock
from bot.commands import Command, CommandContext, CommandRegistry
from bot.connectors.base import UserRef
from bot.http import HttpClient
from bot.stats import StatsStore
from bot.text import clean_username, format_duration, strip_invisible

MAX_FACT = 400
LOOKUP_TIMEOUT = 5.0  # seconds to wait for Twitch to confirm a user exists
# Third-party text must not carry links or @mentions into Jason's chat (the bot, as a mod,
# bypasses Twitch's link filter). Every reply also starts with an emoji, so it can never begin
# with "/" or "." and be read as a chat command; keep that prefix.
_UNSAFE = re.compile(r"://|www\.|@\w", re.IGNORECASE)

LookupUser = Callable[[str], Awaitable[UserRef | None]]


def _get(data: Any, *path: str | int) -> Any:
    for key in path:
        data = data[key]
    return data


# Innocent words that look like blocked ones, checked as prefixes of each word.
_INNOCENT = (
    "analects", "analges", "analog", "analy", "booby", "boobies", "cockat", "cocker", "cockfight", "cockle",
    "cockney", "cockp", "cockr", "cockscomb", "cockt", "cocky", "cummings", "dicken", "dickey", "dickinson", "milford",
    "negroni", "penistone", "pissarro", "pussyc", "pussyf", "pussyw", "rapese", "retardant", "scunthorpe",
    "shitzu", "titter", "tittle", "wankel",
)
_ES_PLURALS = ("ses", "xes", "zes", "ches", "shes")  # "-es" plurals ("spices" is not one)
_HOMO_SPECIES = {"antecessor", "erectus", "ergaster", "floresiensis", "habilis", "heidelbergensis", "naledi",
                 "neanderthalensis", "sapiens"}


class BlockedWords:
    """Finds blocked words in prose, by the patterns in content/blocked_prose_rot13.txt:
    "word" is the whole word or its plural, "word*" a word start, "*word*" anywhere in a word."""

    def __init__(self, patterns: list[str]) -> None:
        self.whole = {p for p in patterns if "*" not in p}
        self.prefix = tuple(p[:-1] for p in patterns if p.endswith("*") and not p.startswith("*"))
        self.inside = tuple(p[1:-1] for p in patterns if p.startswith("*") and p.endswith("*"))

    @classmethod
    def load(cls, assets: Assets) -> BlockedWords:
        try:
            return cls([codecs.decode(line, "rot13") for line in assets.lines("blocked_prose_rot13")])
        except FileNotFoundError:
            return cls([])

    def found_in(self, text: str) -> bool:
        words = re.findall(r"[a-z]+", text.lower())
        for i, word in enumerate(words):
            if word.startswith(_INNOCENT):
                continue
            stems = (word, word[:-1] if word.endswith("s") else "", word[:-2] if word.endswith(_ES_PLURALS) else "")
            if any(stem in self.whole for stem in stems) and not _fine_in_context(words, i):
                return True
            if word.startswith(self.prefix) or any(part in word for part in self.inside):
                return True
        return False


def _fine_in_context(words: list[str], i: int) -> bool:
    """A few blocked whole words are fine next to a specific word: "Homo sapiens", "Maine Coon"."""
    if words[i] in ("homo", "homos"):
        return i + 1 < len(words) and words[i + 1] in _HOMO_SPECIES
    if words[i] in ("coon", "coons"):
        return i > 0 and words[i - 1] in ("maine", "main")  # the breed, often misspelled
    return False


def _safe_text(value: Any, blocked: BlockedWords | None = None) -> str | None:
    """API text cleaned for chat, or None if it's unusable: missing, too long, cut off at the start,
    or carrying links, @mentions or blocked words (the bot is a mod, so Twitch won't filter it)."""
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFC", value)  # compose accents first so stripping marks keeps them
    text = " ".join(strip_invisible(text).split())  # all whitespace (incl. newlines) becomes one space
    text = "".join(ch for ch in text if ch.isprintable())  # then drop control characters
    if not text or len(text) > MAX_FACT or _UNSAFE.search(text):
        return None
    if text[0].islower():  # looks cut off mid-sentence
        return None
    if blocked is not None and blocked.found_in(text):
        return None
    return text


def _mention(display_name: str, login: str) -> str:
    """@display name if it's just a capitalised login, else @login (localised names don't ping)."""
    return f"@{display_name}" if display_name.lower() == login.lower() else f"@{login}"


# command name -> (emoji, url, path to the text in the JSON, extra headers, fallback file, help)
FACT_SOURCES: dict[str, tuple[str, str, tuple[str | int, ...], dict[str, str], str, str]] = {
    "catfact": ("🐱", "https://catfact.ninja/fact", ("fact",), {}, "fallback_catfacts", "Get a random cat fact."),
    "dogfact": (
        "🐶", "https://dogapi.dog/api/v2/facts", ("data", 0, "attributes", "body"), {},
        "fallback_dogfacts", "Get a random dog fact.",
    ),
    "fact": (
        "💡", "https://uselessfacts.jsph.pl/api/v2/facts/random?language=en", ("text",), {},
        "fallback_facts", "Get a random fact.",
    ),
    "dadjoke": (
        "😄", "https://icanhazdadjoke.com/", ("joke",), {"Accept": "application/json"},
        "fallback_dadjokes", "Get a random dad joke.",
    ),
}


def register_fun(
    registry: CommandRegistry,
    *,
    assets: Assets,
    rng: random.Random,
    http: HttpClient,
    stats: StatsStore,
    clock: Clock,
    lookup_user: LookupUser,
) -> None:
    async def eightball(ctx: CommandContext) -> None:
        ctx.reply(f"🎱 {rng.choice(assets.lines('8ball'))}")

    async def coinflip(ctx: CommandContext) -> None:
        ctx.reply(f"🪙 {rng.choice(['Heads', 'Tails'])}")

    registry.add(Command("8ball", eightball, "{p}8ball [question]", "Ask the magic 8-ball a question.", "Fun"))
    registry.add(Command("coinflip", coinflip, "{p}coinflip", "Flip a coin.", "Fun"))

    blocked = BlockedWords.load(assets)

    def fact_handler(emoji: str, url: str, path: tuple, headers: dict, fallback: str):
        async def handler(ctx: CommandContext) -> None:
            data = await http.get_json(url, headers=headers or None)
            try:
                text = _safe_text(_get(data, *path), blocked) if data is not None else None
            except (KeyError, IndexError, TypeError):
                text = None
            ctx.reply(f"{emoji} {text or rng.choice(assets.lines(fallback))}")

        return handler

    for name, (emoji, url, path, headers, fallback, help_text) in FACT_SOURCES.items():
        registry.add(Command(name, fact_handler(emoji, url, path, headers, fallback), f"{{p}}{name}", help_text, "Fun"))

    def already_message() -> str:
        now = clock.now()
        midnight = datetime.combine(now.date() + timedelta(days=1), time(0, 0), tzinfo=timezone.utc)
        wait = format_duration((midnight - now).total_seconds())
        return f"You already opened today's cookie. Next one in {wait} (00:00 UTC)."

    async def cookie(ctx: CommandContext) -> None:
        today = clock.now().date().isoformat()
        uid = ctx.msg.user_id
        argv = ctx.argv
        usage = f"Usage: {ctx.prefix}cookie or {ctx.prefix}cookie give <username>"
        if argv and argv[0].lower() != "give":
            ctx.reply(usage)  # e.g. "?cookie gift bob": don't silently spend the cookie
            return
        if argv:
            if len(argv) < 2:
                ctx.reply(usage)
                return
            login = clean_username(argv[1])
            if login is None:
                ctx.reply("That's not a valid username.")
                return
            if login == ctx.msg.login:
                ctx.reply("You can't give a cookie to yourself.")
                return
            if stats.get_daily(uid, "cookie", today) is not None:
                ctx.reply(already_message())
                return
            try:
                target = await asyncio.wait_for(lookup_user(login), LOOKUP_TIMEOUT)
            except TimeoutError:
                ctx.reply("Couldn't check that user right now. Try again in a bit.")
                return
            if target is None:
                ctx.reply("Couldn't find that user.")  # never repeat the name the user typed
                return
            if target.user_id == uid:
                ctx.reply("You can't give a cookie to yourself.")
                return
            fortune = rng.choice(assets.lines("fortunes"))
            record = json.dumps({"gave_to": target.login, "fortune": fortune})
            if not stats.claim_daily(uid, "cookie", today, record):
                ctx.reply(already_message())
                return
            giver = _mention(ctx.msg.display_name, ctx.msg.login)
            receiver = _mention(target.display_name, target.login)
            ctx.say(f"🥠 {giver} gave {receiver} a fortune cookie: {fortune}")
            return
        fortune = rng.choice(assets.lines("fortunes"))
        if not stats.claim_daily(uid, "cookie", today, json.dumps({"fortune": fortune})):
            ctx.reply(already_message())
            return
        ctx.reply(f"🥠 {fortune}")

    registry.add(
        Command(
            "cookie",
            cookie,
            "{p}cookie | {p}cookie give <username>",
            "Open your daily fortune cookie, or give it to someone. Resets at 00:00 UTC.",
            "Fun",
            global_cooldown=False,  # personal: one person's cookie shouldn't block another's
        )
    )
```

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_http.py tests/test_fun.py -q`

Expected: PASS (33 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add bot/http.py bot/fun.py tests/helpers.py tests/test_http.py tests/test_fun.py
git commit -m "Add the HTTP client and fun commands"
```

### Task 12: ?leaderboard, ?gamestats, ?help

Argument rules from spec §5:

- `?leaderboard [game] [limit]` accepts its arguments in either order. The limit is clamped to 1 to 10, and the default is 5.
- `?gamestats [game] [username]` treats the first argument as a game if it names one, and otherwise as a username. A leading `@` is stripped.
- A typed name that isn't found is never echoed ("No stats for that user yet.").
- `?help <x>` never echoes `x` ("No command by that name."). Underscore-joined troll phrases look like command names.
- Limits must be plain ASCII digits: `str.isdigit()` accepts "²", which `int()` rejects.

**Files:**
- Create: `bot/stats_commands.py`, `bot/help.py`
- Test: `tests/test_stats_help_commands.py`

- [ ] **Step 1: Write the failing test `tests/test_stats_help_commands.py`**

```python
from datetime import datetime, timezone

import pytest

from bot.commands import CommandContext, CommandRegistry
from bot.help import register_help
from bot.stats import PlayerResult, RoundRecord, StatsStore
from bot.stats_commands import register_stats
from tests.helpers import make_msg

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


class Cmds:
    def __init__(self):
        self.stats = StatsStore(":memory:")
        self.registry = CommandRegistry("?")
        register_stats(self.registry, stats=self.stats, game_names=["scramble", "hangman"])
        register_help(self.registry)
        self.replies: list[str] = []

    def play(self, game: str, login: str, points: int, won: bool = True) -> None:
        self.stats.touch_user(f"id-{login}", login, login.title(), T0)
        self.stats.record_round(
            RoundRecord(game, None, f"id-{login}", T0, T0, "won",
                        [PlayerResult(f"id-{login}", login, login.title(), points, won)])
        )

    async def run(self, text: str, login: str = "alice") -> str:
        name, _, args = text.removeprefix("?").partition(" ")
        ctx = CommandContext(make_msg(text, login), name, args, "?", lambda t, **kw: self.replies.append(t), None)
        await self.registry.get(name).handler(ctx)
        return self.replies[-1]


@pytest.fixture
def c() -> Cmds:
    cmds = Cmds()
    cmds.play("scramble", "bob", 10)
    cmds.play("scramble", "bob", 7)
    cmds.play("scramble", "carol", 10)
    cmds.play("hangman", "carol", 12)
    cmds.play("hangman", "alice", 0, won=False)
    return cmds


async def test_leaderboard_overall_default(c: Cmds):
    assert await c.run("?leaderboard") == "🏆 Top 2 overall: 1. Carol (22) 2. Bob (17)"


async def test_leaderboard_game_and_limit_in_any_order(c: Cmds):
    assert await c.run("?leaderboard scramble 1") == "🏆 Top 1 scramble: 1. Bob (17)"
    assert await c.run("?leaderboard 1 hangman") == "🏆 Top 1 hangman: 1. Carol (12)"
    assert await c.run("?leaderboard 99") == "🏆 Top 2 overall: 1. Carol (22) 2. Bob (17)"


async def test_leaderboard_limit_edge_cases(c: Cmds):
    assert await c.run("?leaderboard 0") == "🏆 Top 1 overall: 1. Carol (22)"
    assert await c.run("?leaderboard -5") == "🏆 Top 1 overall: 1. Carol (22)"
    assert await c.run("?leaderboard " + chr(0xB2)) == "Unknown game. Games: scramble, hangman"  # superscript two
    assert await c.run("?leaderboard SCRAMBLE 1 extra words") == "🏆 Top 1 scramble: 1. Bob (17)"


async def test_leaderboard_unknown_game_and_empty(c: Cmds):
    assert await c.run("?leaderboard chess") == "Unknown game. Games: scramble, hangman"
    empty = Cmds()
    assert await empty.run("?leaderboard hangman") == "No hangman scores yet."


async def test_gamestats_self_overall(c: Cmds):
    assert await c.run("?gamestats", "carol") == (
        "📊 carol: 22 pts, 2 wins, 2 played | hangman 1W/1P 12pts | scramble 1W/1P 10pts"
    )


async def test_gamestats_game_and_other_user(c: Cmds):
    assert await c.run("?gamestats scramble @Bob") == "📊 Bob · scramble: 2 wins / 2 played · 17 pts · rank #1"
    assert await c.run("?gamestats bob") == "📊 Bob: 17 pts, 2 wins, 2 played | scramble 2W/2P 17pts"


async def test_gamestats_one_win_is_singular(c: Cmds):
    assert await c.run("?gamestats hangman carol") == "📊 Carol · hangman: 1 win / 1 played · 12 pts · rank #1"


async def test_gamestats_played_without_points_has_no_rank(c: Cmds):
    assert await c.run("?gamestats hangman") == "📊 alice · hangman: 0 wins / 1 played · 0 pts"


async def test_gamestats_missing(c: Cmds):
    assert await c.run("?gamestats nobody_here") == "No stats for that user yet."
    assert await c.run("?gamestats bad/name") == "That's not a valid username."
    assert await c.run("?gamestats @") == "That's not a valid username."
    assert await c.run("?gamestats hangman bob") == "No hangman stats for Bob yet."
    assert await c.run("?gamestats", "dave") == "No stats for dave yet."


async def test_help_overview_and_details(c: Cmds):
    assert await c.run("?help") == "Stats: ?leaderboard ?gamestats · ?help <command> for details"
    assert await c.run("?commands") == "Stats: ?leaderboard ?gamestats · ?help <command> for details"
    assert await c.run("?help ?leaderboard") == (
        "?leaderboard [game] [1-10] · Top players by points, overall or for one game."
    )


async def test_help_unknown_never_echoes_what_was_typed(c: Cmds):
    assert await c.run("?help nope") == "No command by that name. Try ?help."
    assert await c.run("?help jason_is_trash") == "No command by that name. Try ?help."
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_stats_help_commands.py -q`

Expected: FAIL. `ModuleNotFoundError: No module named 'bot.help'`

- [ ] **Step 3: Write `bot/stats_commands.py`**

```python
"""?leaderboard and ?gamestats."""

from __future__ import annotations

import re
from collections.abc import Sequence

from bot.commands import Command, CommandContext, CommandRegistry
from bot.stats import StatsStore
from bot.text import clean_username

DEFAULT_LIMIT = 5
MAX_LIMIT = 10
_NUMBER = re.compile(r"-?[0-9]+")  # ASCII only: str.isdigit() accepts "²", which int() rejects


def _plural(count: int, word: str) -> str:
    return word if count == 1 else word + "s"


def register_stats(registry: CommandRegistry, *, stats: StatsStore, game_names: Sequence[str]) -> None:
    games = [g.lower() for g in game_names]

    async def leaderboard(ctx: CommandContext) -> None:
        game: str | None = None
        limit = DEFAULT_LIMIT
        for arg in ctx.argv[:2]:
            if _NUMBER.fullmatch(arg):
                limit = max(1, min(MAX_LIMIT, int(arg)))
            elif arg.lower() in games:
                game = arg.lower()
            else:
                ctx.reply(f"Unknown game. Games: {', '.join(games)}")
                return
        rows = stats.leaderboard(game, limit)
        label = game or "overall"
        if not rows:
            ctx.reply(f"No {label} scores yet.")
            return
        body = " ".join(f"{i}. {r.display_name} ({r.points})" for i, r in enumerate(rows, start=1))
        ctx.reply(f"🏆 Top {len(rows)} {label}: {body}")

    async def gamestats(ctx: CommandContext) -> None:
        argv = ctx.argv
        game: str | None = None
        # A first argument that names a game is the game, even if someone's login is the same word.
        if argv and argv[0].lower() in games:
            game = argv[0].lower()
            argv = argv[1:]
        if argv:
            login = clean_username(argv[0])
            if login is None:
                ctx.reply("That's not a valid username.")
                return
            user = stats.find_user(login)
            if user is None:
                ctx.reply("No stats for that user yet.")  # never repeat the name the user typed
                return
            user_id, name = user.user_id, user.display_name
        else:
            user_id, name = ctx.msg.user_id, ctx.msg.display_name
        per_game = stats.user_stats(user_id)
        if game is not None:
            row = next((g for g in per_game if g.game == game), None)
            if row is None:
                ctx.reply(f"No {game} stats for {name} yet.")
                return
            rank = stats.rank(user_id, game)
            rank_text = f" · rank #{rank}" if rank else ""
            wins_text = f"{row.wins} {_plural(row.wins, 'win')}"
            ctx.reply(f"📊 {name} · {game}: {wins_text} / {row.played} played · {row.points} pts{rank_text}")
            return
        if not per_game:
            ctx.reply(f"No stats for {name} yet.")
            return
        points = sum(g.points for g in per_game)
        wins = sum(g.wins for g in per_game)
        played = sum(g.played for g in per_game)
        parts = " | ".join(f"{g.game} {g.wins}W/{g.played}P {g.points}pts" for g in per_game)
        ctx.reply(f"📊 {name}: {points} pts, {wins} {_plural(wins, 'win')}, {played} played | {parts}")

    registry.add(
        Command(
            "leaderboard",
            leaderboard,
            "{p}leaderboard [game] [1-10]",
            "Top players by points, overall or for one game.",
            "Stats",
        )
    )
    registry.add(
        Command(
            "gamestats",
            gamestats,
            "{p}gamestats [game] [username]",
            "Wins, games played, and points: yours or someone else's, overall or for one game.",
            "Stats",
            global_cooldown=False,  # personal lookup: never blocked by someone else's
        )
    )
```

- [ ] **Step 4: Write `bot/help.py`**

```python
"""?help / ?commands, generated from the command registry."""

from __future__ import annotations

from bot.commands import Command, CommandContext, CommandRegistry


def register_help(registry: CommandRegistry) -> None:
    async def help_command(ctx: CommandContext) -> None:
        if not ctx.argv:
            ctx.reply(registry.help_overview())
            return
        text = registry.help_for(ctx.argv[0].lower().removeprefix(ctx.prefix))
        # Never repeat what was typed: an unknown name could be any phrase a troll chose.
        ctx.reply(text or f"No command by that name. Try {ctx.prefix}help.")

    registry.add(
        Command(
            "help",
            help_command,
            "{p}help [command]",
            "List commands, or explain one.",
            "Info",
            aliases=("commands",),
            listed=False,
            global_cooldown=False,  # personal: one person's ?help shouldn't block another's
        )
    )
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_stats_help_commands.py -q`

Expected: PASS (11 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add bot/stats_commands.py bot/help.py tests/test_stats_help_commands.py
git commit -m "Add leaderboard, gamestats, and help commands"
```

### Task 13: Configuration

`load_config` merges `config.toml` (settings) and the `.env` values (secrets) into a frozen `Config`. Game limits live under `[games]` (`max_running` 25, `cooldown_seconds` 10, `busy_queue` 10), and the outbox defaults to 2 messages/s with a queue of 30.

Mistakes fail loudly rather than silently:

- unknown or misspelled keys, and sections of the wrong type;
- non-finite numbers, and a send rate above 3/s (Twitch's mod limit);
- non-numeric OWNER_IDS on Twitch;
- a prefix starting with `/` or `.`, which Twitch intercepts;
- an empty game list;
- the placeholder `channel = "your_channel"` from the example config (Twitch mode only, so console mode and `auth` work before it's set);
- a `busy_queue` larger than the outbox queue, where the brake could never engage. Every invalid value raises `ConfigError` naming the key; the CLI turns that into exit code 2 (spec §12). Console mode passes `require_twitch=False`. `data_dir` is the `data/` folder next to the config file.

**Files:**
- Create: `bot/config.py`, `config.toml`, `.env.example`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test `tests/test_config.py`**

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
    assert cfg.prefix == "?" and cfg.enabled_games == ("scramble", "hangman")


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
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_config.py -q`

Expected: FAIL. `ModuleNotFoundError: No module named 'bot.config'`

- [ ] **Step 3: Write `bot/config.py`**

```python
"""Loads config.toml (settings) and .env values (secrets) into one validated Config."""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
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
enabled = ["scramble", "hangman"]
max_running = 25            # personal games running at once, across the whole chat
cooldown_seconds = 10       # per person, after their game ends
busy_queue = 10             # refuse new games while this many bot messages are waiting to send

[outbox]
rate_per_second = 2         # sustained sending rate (a mod account may send about 3/s)
burst = 3                   # messages that can go out back to back
max_queue = 30              # extra messages beyond this are dropped and logged

[logs]
retention_days = 30
```

- [ ] **Step 5: Write `.env.example`**

```text
# Copy to .env and fill in. Never commit .env.
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
# Printed by `python -m bot auth` after you log in as the bot account.
BOT_ID=
# Comma-separated Twitch user IDs that can always control the bot (yours).
OWNER_IDS=
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_config.py -q`

Expected: PASS (24 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add bot/config.py config.toml .env.example tests/test_config.py
git commit -m "Add configuration loading and validation"
```

### Task 14: Console connector

Lines look like `alice: ?scramble`, and a leading `@` marks a moderator. Users get IDs like `console-alice`, so `OWNER_IDS=console-robert` makes `robert` an owner in console mode. A scripted `lines=` list drives tests. Interactive mode reads stdin on a daemon thread (`pump_lines`), so `?bot shutdown` exits immediately instead of waiting for another Enter. A line typed after shutdown is dropped quietly instead of raising on the closed event loop.

**Files:**
- Create: `bot/connectors/console.py`
- Test: `tests/test_console.py`

- [ ] **Step 1: Write the failing test `tests/test_console.py`**

```python
import asyncio
import io
from itertools import count

from bot.clock import FakeClock
from bot.connectors.console import ConsoleConnector, parse_console_line, pump_lines


def test_parse_console_line_user_and_mod(clock: FakeClock):
    ids = count(1)
    msg = parse_console_line("alice: ?scramble animals", clock, ids)
    assert (msg.login, msg.user_id, msg.text) == ("alice", "console-alice", "?scramble animals")
    assert not msg.is_moderator
    mod = parse_console_line("@Mod_Bob: ?bot off", clock, ids)
    assert (mod.login, mod.display_name, mod.is_moderator) == ("mod_bob", "Mod_Bob", True)
    assert msg.id != mod.id


def test_parse_console_line_rejects_garbage(clock: FakeClock):
    ids = count(1)
    assert parse_console_line("no colon here", clock, ids) is None
    assert parse_console_line("alice:", clock, ids) is None
    assert parse_console_line("bad name!: hi", clock, ids) is None


async def test_console_send_marks_replies(clock: FakeClock):
    printed: list[str] = []
    conn = ConsoleConnector(clock=clock, lines=["alice: hi"], out=printed.append)
    seen = []

    async def on_message(msg):
        seen.append(msg)

    async def on_ready(info):
        assert info.is_mod

    await conn.run(on_message, on_ready)
    await conn.send("hello", reply_to=seen[0].id)
    await conn.send("plain")
    assert printed == ["bot → alice: hello", "bot: plain"]
    assert conn.sent == ["hello", "plain"]


async def test_close_before_run_returns_immediately(clock: FakeClock):
    conn = ConsoleConnector(clock=clock, lines=["alice: hi"])
    seen = []

    async def on_message(msg):
        seen.append(msg)

    async def on_ready(info):
        pass

    await conn.close()
    await conn.run(on_message, on_ready)
    assert seen == []


def test_stdin_pump_stops_quietly_after_the_loop_closes():
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    loop.close()
    pump_lines(io.StringIO("typed after shutdown\n"), loop, queue)  # must not raise


async def test_stdin_pump_delivers_lines_then_end_marker():
    queue: asyncio.Queue = asyncio.Queue()
    pump_lines(io.StringIO("a: hi\nb: yo\n"), asyncio.get_running_loop(), queue)
    await asyncio.sleep(0)
    assert [queue.get_nowait() for _ in range(3)] == ["a: hi\n", "b: yo\n", None]


async def test_console_lookup_user(clock: FakeClock):
    conn = ConsoleConnector(clock=clock, lines=[])
    assert (await conn.lookup_user("@Bob")).login == "bob"
    assert await conn.lookup_user("x") is None
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_console.py -q`

Expected: FAIL. `ModuleNotFoundError: No module named 'bot.connectors.console'`

- [ ] **Step 3: Write `bot/connectors/console.py`**

```python
"""Play with the bot in a terminal. Lines look like `alice: ?scramble`; a leading @ marks a mod."""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Callable, Iterable, Iterator
from itertools import count
from typing import TextIO

from bot.clock import Clock
from bot.connectors.base import ChatMessage, OnMessage, OnReady, ReadyInfo, SendResult, UserRef
from bot.text import clean_username

BANNER = "Console mode. Type lines like `alice: ?scramble` (a leading @ makes the user a mod). Ctrl+D to quit."


def parse_console_line(line: str, clock: Clock, ids: Iterator[int]) -> ChatMessage | None:
    who, sep, text = line.strip().partition(":")
    text = text.strip()
    if not sep or not text:
        return None
    who = who.strip()
    moderator = who.startswith("@")
    display = who.lstrip("@")
    login = clean_username(display)
    if login is None:
        return None
    return ChatMessage(
        id=f"console-{next(ids)}",
        user_id=f"console-{login}",
        login=login,
        display_name=display,
        text=text,
        is_broadcaster=False,
        is_moderator=moderator,
        source_channel_id=None,
        received_at=clock.now(),
    )


def pump_lines(stream: TextIO, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[str | None]) -> None:
    """Feed lines from a blocking stream into an asyncio queue (runs on a daemon thread).

    Stops quietly if the event loop has already closed, e.g. a line typed after ?bot shutdown.
    """
    try:
        for raw in stream:
            loop.call_soon_threadsafe(queue.put_nowait, raw)
        loop.call_soon_threadsafe(queue.put_nowait, None)
    except RuntimeError:  # "Event loop is closed"
        return


class ConsoleConnector:
    channel_id = "console"

    def __init__(
        self,
        *,
        clock: Clock,
        lines: Iterable[str] | None = None,
        out: Callable[[str], None] = print,
    ) -> None:
        self._clock = clock
        self._lines = lines
        self._out = out
        self._ids = count(1)
        self._names: dict[str, str] = {}  # message id -> display name, for reply arrows
        self._queue: asyncio.Queue[str | None] | None = None
        self._closed = False
        self.sent: list[str] = []

    async def _deliver(self, line: str, on_message: OnMessage) -> None:
        msg = parse_console_line(line, self._clock, self._ids)
        if msg is not None:
            self._names[msg.id] = msg.display_name
            await on_message(msg)

    async def run(self, on_message: OnMessage, on_ready: OnReady) -> None:
        await on_ready(ReadyInfo("console", self.channel_id, True))
        if self._closed:
            return
        if self._lines is not None:
            for line in self._lines:
                if self._closed:
                    return
                await self._deliver(line, on_message)
                await asyncio.sleep(0)
            return
        self._out(BANNER)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._queue = queue

        # Daemon thread, so a blocked read never keeps the process alive after shutdown.
        threading.Thread(target=pump_lines, args=(sys.stdin, loop, queue), daemon=True).start()
        while not self._closed:
            line = await queue.get()
            if line is None:
                return
            await self._deliver(line, on_message)

    async def send(self, text: str, reply_to: str | None = None) -> SendResult:
        self.sent.append(text)
        name = self._names.get(reply_to or "")
        self._out(f"bot → {name}: {text}" if name else f"bot: {text}")
        return SendResult(True)

    async def lookup_user(self, login: str) -> UserRef | None:
        clean = clean_username(login)
        return UserRef(f"console-{clean}", clean, clean) if clean else None

    async def close(self) -> None:
        self._closed = True
        if self._queue is not None:
            self._queue.put_nowait(None)
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_console.py -q`

Expected: PASS (7 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bot/connectors/console.py tests/test_console.py
git commit -m "Add the console connector"
```

### Task 15: Admin commands and BotCore

The heart of the bot. `BotCore.on_message` applies spec §3's filter in order:

1. Ignore everything once shutdown has started.
2. Ignore the bot's own messages.
3. Ignore shared-chat messages from other channels.
4. While paused, accept only `?bot ...` from a controller.
5. Route commands; anything else goes to the sender's own game, if they have one.

`_dispatch` checks permission, then cooldowns (the chat-wide one only if the command uses it), then touches the user, logs `command`, and runs the handler. Handler exceptions are logged and never crash the bot. The busy brake is wired here: games are refused while the outbox holds `busy_queue` or more messages. While the brake is on, Stats, Fun, and Info commands (`?coinflip`, `?gamestats`, `?help`, ...) are ignored too, so game messages keep flowing; control and in-game commands still work. When the connector reports the bot isn't a mod (at startup, or later if mod status is lost), sending slows to 0.6 messages/s with burst 1, under Twitch's non-mod limit of 20 per 30 s; `startup` is logged only once.

`run()` starts the connector, the outbox loop, and the 1 s tick loop. It returns an exit code:

- 0 for `?bot shutdown`, a signal, or the end of console input;
- 2 for a `ConfigError` raised by the connector, such as a channel that doesn't exist;
- 3 for `AuthRequired`;
- 1 for any other connector failure.

Before returning, it does the following. Every step is guarded, so a cleanup error never turns a deliberate stop into a crash.

1. Lets the send loop finish its current message (no cancel mid-send).
2. Drains the outbox, or discards it after a connector failure.
3. Closes the outbox.
4. Closes the connector, bounded to 5 s.
5. Logs `shutdown` (in `finally`).

The paused flag is read from the database at startup, so it survives restarts. The full-flow tests are spec §14.2.

**Files:**
- Create: `bot/admin.py`, `bot/core.py`
- Modify: `tests/helpers.py` (append `make_config`)
- Test: `tests/test_flows.py`

- [ ] **Step 1: Write the failing test `tests/test_flows.py`**

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
    def __init__(self, tmp_path, clock, assets, *, db=":memory:", lines=None, connector=None, http=None):
        self.clock = clock
        self.ids = count(1)
        self.connector = connector or ConsoleConnector(clock=clock, lines=lines, out=lambda s: None)
        self.log = ActivityLog(tmp_path / "logs", clock)
        self.core = BotCore(
            config=make_config(tmp_path),
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
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_flows.py -q`

Expected: FAIL. `ModuleNotFoundError: No module named 'bot.core'`

- [ ] **Step 3: Append `make_config` to the end of `tests/helpers.py`**

```python
def make_config(tmp_path, **overrides):
    from dataclasses import replace

    from bot.config import Config

    base = Config(
        client_id="",
        client_secret="",
        bot_id="console-bot",
        owner_ids=frozenset({"console-robert"}),
        channel="test_channel",
        prefix="?",
        user_cooldown=10,
        global_cooldown=5,
        enabled_games=("scramble", "hangman"),
        max_games=25,
        game_cooldown=10,
        busy_queue=10,
        outbox_rate=100,
        outbox_burst=100,
        outbox_max_queue=100,
        log_retention_days=30,
        data_dir=tmp_path / "data",
    )
    return replace(base, **overrides)
```

- [ ] **Step 4: Write `bot/admin.py`**

```python
"""Control commands for the broadcaster, mods, and owners: ?bot off/on/status/shutdown, ?stopgame."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.commands import Command, CommandContext, CommandRegistry

if TYPE_CHECKING:
    from bot.core import BotCore


def register_admin(registry: CommandRegistry, core: BotCore) -> None:
    async def bot_command(ctx: CommandContext) -> None:
        sub = ctx.argv[0].lower() if ctx.argv else ""
        who = ctx.msg.display_name
        if sub == "off":
            if core.paused:
                ctx.reply("Already paused.", priority=True)
                return
            core.log.write("admin", user_id=ctx.msg.user_id, login=ctx.msg.login, action="off")
            core.games.stop_all()
            core.set_paused(True)
            ctx.reply(f"Bot paused by {who}. {ctx.prefix}bot on to resume.", priority=True)
        elif sub == "on":
            if not core.paused:
                ctx.reply("Already on.", priority=True)
                return
            core.log.write("admin", user_id=ctx.msg.user_id, login=ctx.msg.login, action="on")
            core.set_paused(False)
            ctx.reply(f"Bot resumed by {who}.", priority=True)
        elif sub == "status":
            ctx.reply(core.status_line(), priority=True)
        elif sub == "shutdown":
            core.log.write("admin", user_id=ctx.msg.user_id, login=ctx.msg.login, action="shutdown")
            ctx.reply(f"Shutting down (requested by {who}).", priority=True)
            core.request_shutdown(by=ctx.msg.login)
        else:
            ctx.reply(f"Usage: {ctx.prefix}bot off|on|status|shutdown", priority=True)

    async def stopgame(ctx: CommandContext) -> None:
        if not core.games.sessions:
            ctx.reply("No games are running.")
            return
        core.log.write("admin", user_id=ctx.msg.user_id, login=ctx.msg.login, action="stopgame")
        stopped = core.games.stop_all()
        ctx.reply(f"🛑 Stopped {stopped} game{'s' if stopped != 1 else ''}. No points awarded.")

    registry.add(
        Command(
            "bot",
            bot_command,
            "{p}bot off|on|status|shutdown",
            "Pause, resume, check, or shut down the bot. Shutdown really stops it until someone restarts it.",
            "Control",
            controller_only=True,
            cooldown=False,
            listed=False,
        )
    )
    registry.add(
        Command(
            "stopgame",
            stopgame,
            "{p}stopgame",
            "End all running games with no points.",
            "Control",
            controller_only=True,
            cooldown=False,
            listed=False,
        )
    )
```

- [ ] **Step 5: Write `bot/core.py`**

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
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_flows.py -q`

Expected: PASS (34 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add bot/admin.py bot/core.py tests/helpers.py tests/test_flows.py
git commit -m "Add admin commands and the bot core"
```

### Task 16: Twitch connector and login flow

This follows the TwitchIO 3.3.2 source, which was read while writing the plan.

- **Startup:**
  1. The `_Client` subclass loads only the bot's token from `data/.tio.tokens.json`. A missing token, or one Twitch rejects (400/401/403), raises `AuthRequired`, which becomes exit 3. A 5xx or 429 while validating is a plain error, so systemd retries.
  2. In `setup_hook` it resolves the channel and checks `fetch_moderated_channels`. A channel that doesn't exist raises `ConfigError` (exit 2, so systemd doesn't restart-loop). A failed mod check logs a warning and continues.
  3. It subscribes to `channel.chat.message` over WebSocket with the bot token (`as_bot=True`).
- **Sending:** through Helix with the **app token** (`token_for=None`) when the bot is a mod, which gives it the Chat Bot badge. Without mod status it uses the bot's user token, since Twitch refuses app-token sends then. If mod status is removed while running, the first HTTP 403 switches to the user token, logs `LostModStatus`, retries once, and calls `on_ready` again so the core slows down. `MessageRejectedError` and HTTP errors become `SendResult(False, ...)`.
- **Tokens:** TwitchIO's own save is a no-op when tokens are loaded this way, so the connector writes the bot token itself. The write is atomic with mode 0600, on close and on every `token_refreshed` event.
- **Watchdog:** TwitchIO can lose the login or the chat subscription without ending. Every 30 s it checks both, and fails (exit 3, or a crash that systemd restarts) if the login was dropped or there has been no subscription for 4 minutes.
- **Connection events:** the first `websocket_welcome` logs `connected` and later ones log `reconnected`. `websocket_closed` logs `disconnected`.
- **Replies:** when a message is a Twitch reply that starts with "@<parent> ", that mention is stripped, so answering by replying to the bot works ("@bot alligator" reads "alligator").
- **Revocation:** a revoked subscription is fatal (`AuthRequired`).
- **Unexpected end:** if the connection ends without `close()` being called, `run()` raises, so systemd restarts the bot.
- **Token file safety:** tokens are saved on close only if they loaded. A startup failure would otherwise overwrite the token file with nothing and force a needless re-login.
- **`authorize()`:** runs TwitchIO's built-in web adapter on `localhost:4343`. Its default callback is `http://localhost:4343/oauth/callback`, which must match the app registration.

Only the pure parts are unit-tested here. The live behavior is verified in Task 20.

**Files:**
- Create: `bot/connectors/twitch.py`
- Test: `tests/test_twitch_mapping.py`

- [ ] **Step 1: Write the failing test `tests/test_twitch_mapping.py`**

```python
import asyncio
import json
import os
import socket
from types import SimpleNamespace

import pytest
import twitchio

import bot.connectors.twitch as twitch
from bot.activity_log import ActivityLog
from bot.clock import FakeClock
from bot.config import ConfigError
from bot.connectors.base import AuthRequired
from bot.connectors.twitch import AUTH_URL, read_bot_token, to_chat_message
from tests.helpers import make_config


def fake_payload(source=None, text="?scramble", reply=None, **chatter):
    defaults = dict(id="42", name="Alice", display_name="Alice", broadcaster=False, moderator=False)
    defaults.update(chatter)
    return SimpleNamespace(
        id="m1", text=text, chatter=SimpleNamespace(**defaults), source_broadcaster=source, reply=reply
    )


def reply_to(login: str):
    return SimpleNamespace(parent_user=SimpleNamespace(name=login))


def test_to_chat_message_maps_fields(clock: FakeClock):
    msg = to_chat_message(fake_payload(moderator=True), clock)
    assert (msg.id, msg.user_id, msg.login, msg.display_name, msg.text) == ("m1", "42", "alice", "Alice", "?scramble")
    assert msg.is_moderator and not msg.is_broadcaster
    assert msg.source_channel_id is None
    assert msg.received_at == clock.now()


def test_to_chat_message_shared_chat_source(clock: FakeClock):
    msg = to_chat_message(fake_payload(source=SimpleNamespace(id=999)), clock)
    assert msg.source_channel_id == "999"


def test_reply_mention_is_stripped(clock: FakeClock):
    msg = to_chat_message(fake_payload(text="@OfflineBot alligator", reply=reply_to("offlinebot")), clock)
    assert msg.text == "alligator"
    cmd = to_chat_message(fake_payload(text="@offlinebot ?g e", reply=reply_to("offlinebot")), clock)
    assert cmd.text == "?g e"


def test_mentions_are_kept_when_not_a_reply_or_not_the_parent(clock: FakeClock):
    assert to_chat_message(fake_payload(text="@offlinebot hi"), clock).text == "@offlinebot hi"
    other = to_chat_message(fake_payload(text="@someone hi", reply=reply_to("offlinebot")), clock)
    assert other.text == "@someone hi"
    bare = to_chat_message(fake_payload(text="@offlinebot", reply=reply_to("offlinebot")), clock)
    assert bare.text == "@offlinebot"


def test_read_bot_token(tmp_path):
    path = tmp_path / ".tio.tokens.json"
    with pytest.raises(AuthRequired, match="no token file"):
        read_bot_token(path, "123")
    path.write_text("{not json")
    with pytest.raises(AuthRequired, match="corrupt"):
        read_bot_token(path, "123")
    path.write_text(json.dumps({"999": {"token": "t", "refresh": "r"}}))
    with pytest.raises(AuthRequired, match="no token for bot user 123"):
        read_bot_token(path, "123")
    path.write_text(json.dumps({"123": {"user_id": "123", "token": "t"}}))  # no refresh token
    with pytest.raises(AuthRequired, match="no usable entry"):
        read_bot_token(path, "123")
    path.write_text(json.dumps(["not", "an", "object"]))
    with pytest.raises(AuthRequired, match="no token for bot user 123"):
        read_bot_token(path, "123")
    path.write_text(json.dumps({"123": {"user_id": "123", "token": "t", "refresh": "r"}}))
    assert read_bot_token(path, "123") == ("t", "r")


def test_auth_url_requests_all_bot_scopes_and_forces_account_check():
    assert AUTH_URL == (
        "http://localhost:4343/oauth?scopes=user:read:chat%20user:write:chat%20user:bot%20user:read:moderated_channels"
        "&force_verify=true"
    )


async def test_unexpected_end_of_connection_is_an_error(tmp_path, clock: FakeClock, monkeypatch):
    import bot.connectors.twitch as twitch
    from bot.activity_log import ActivityLog
    from tests.helpers import make_config

    class EndsAtOnce:
        def __init__(self, connector):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def start(self, with_adapter=False):
            return None  # returned without anyone calling close()

    monkeypatch.setattr(twitch, "_Client", EndsAtOnce)
    connector = twitch.TwitchConnector(make_config(tmp_path), ActivityLog(tmp_path, clock), clock)

    async def noop(*args):
        pass

    with pytest.raises(RuntimeError, match="ended unexpectedly"):
        await connector.run(noop, noop)


# ---- connector behavior with fake TwitchIO pieces (no network) ----


class FakeClient:
    def __init__(self, tokens=None, subscriptions=None):
        self.tokens = tokens if tokens is not None else {}
        self.subscriptions = subscriptions if subscriptions is not None else {}
        self.closed = False
        self.sent = []

    def websocket_subscriptions(self):
        return self.subscriptions

    async def close(self):
        self.closed = True

    def create_partialuser(self, user_id):
        client = self

        class Channel:
            async def send_message(self, text, sender, token_for=None, reply_to_message_id=None):
                client.sent.append((text, token_for))

        return Channel()


def connector_for(tmp_path, clock, client=None):
    cfg = make_config(tmp_path, bot_id="123")
    conn = twitch.TwitchConnector(cfg, ActivityLog(tmp_path / "logs", clock), clock)
    conn._client = client
    return conn


def test_save_bot_token_writes_the_current_token_atomically_and_privately(tmp_path, clock):
    client = FakeClient(tokens={"123": {"user_id": "123", "token": "NEW", "refresh": "R2"}})
    conn = connector_for(tmp_path, clock, client)
    conn.token_path.parent.mkdir(parents=True)
    conn.token_path.write_text(json.dumps({"123": {"user_id": "123", "token": "OLD", "refresh": "R1"}}))
    conn.save_bot_token()
    assert json.loads(conn.token_path.read_text())["123"]["token"] == "NEW"
    assert oct(os.stat(conn.token_path).st_mode & 0o777) == "0o600"
    assert not list(conn.token_path.parent.glob(".tokens-*"))  # no temp files left behind


def test_save_bot_token_never_raises_and_skips_without_a_token(tmp_path, clock):
    conn = connector_for(tmp_path, clock, FakeClient(tokens={}))
    conn.save_bot_token()
    assert not conn.token_path.exists()
    conn = connector_for(tmp_path, clock, FakeClient(tokens={"123": {"token": "t", "refresh": "r"}}))
    conn.token_path = tmp_path / "missing-dir" / "file" / "x"
    conn.token_path.parent.parent.write_text("a file where a folder should be")
    conn.save_bot_token()  # OSError is logged, not raised


def invalid_token(status):
    exc = twitchio.InvalidTokenException.__new__(twitchio.InvalidTokenException)
    exc.status = status
    return exc


async def test_startup_login_check_tells_outages_from_bad_tokens(tmp_path, clock, monkeypatch):
    conn = connector_for(tmp_path, clock)
    conn.token_path.parent.mkdir(parents=True)
    conn.token_path.write_text(json.dumps({"123": {"user_id": "123", "token": "t", "refresh": "r"}}))
    client = twitch._Client(conn)

    for status, expected in ((401, AuthRequired), (400, AuthRequired), (500, RuntimeError), (429, RuntimeError)):
        async def failing(token, refresh, status=status):
            raise invalid_token(status)

        monkeypatch.setattr(client, "add_token", failing)
        with pytest.raises(expected) as info:
            await client.load_tokens()
        assert type(info.value) is expected


async def test_watchdog_fails_when_the_login_is_dropped(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(twitch, "WATCHDOG_SECONDS", 0.01)
    client = FakeClient(tokens={}, subscriptions={"s": object()})
    conn = connector_for(tmp_path, clock, client)
    await asyncio.wait_for(conn._watch(client), timeout=2)
    assert isinstance(conn._fatal, AuthRequired) and client.closed


async def test_watchdog_fails_after_losing_the_subscription_for_too_long(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(twitch, "WATCHDOG_SECONDS", 0.01)
    monkeypatch.setattr(twitch, "NO_SUBSCRIPTION_GRACE", 0.05)
    client = FakeClient(tokens={"123": {}}, subscriptions={})
    conn = connector_for(tmp_path, clock, client)
    await asyncio.wait_for(conn._watch(client), timeout=2)
    assert isinstance(conn._fatal, RuntimeError) and "chat connection" in str(conn._fatal)


async def test_send_uses_app_token_when_modded_and_bot_token_otherwise(tmp_path, clock):
    client = FakeClient()
    conn = connector_for(tmp_path, clock, client)
    conn.channel_id = "999"
    conn.is_mod = True
    await conn.send("hi")
    conn.is_mod = False
    await conn.send("hi")
    assert client.sent == [("hi", None), ("hi", "123")]


async def test_send_falls_back_to_bot_token_when_mod_status_is_lost(tmp_path, clock):
    class ForbiddenForAppToken(FakeClient):
        def create_partialuser(self, user_id):
            client = self

            class Channel:
                async def send_message(self, text, sender, token_for=None, reply_to_message_id=None):
                    if token_for is None:
                        exc = twitchio.HTTPException.__new__(twitchio.HTTPException)
                        exc.status = 403
                        raise exc
                    client.sent.append((text, token_for))

            return Channel()

    client = ForbiddenForAppToken()
    conn = connector_for(tmp_path, clock, client)
    conn.channel_id, conn.is_mod = "999", True
    ready = []

    async def on_ready(info):
        ready.append(info)

    conn._on_ready = on_ready
    result = await conn.send("hi")
    assert result.sent and not conn.is_mod and client.sent == [("hi", "123")]
    assert [r.is_mod for r in ready] == [False]  # the core slows sending down


async def test_send_maps_http_errors_to_a_drop(tmp_path, clock):
    class Forbidden(FakeClient):
        def create_partialuser(self, user_id):
            class Channel:
                async def send_message(self, *args, **kwargs):
                    exc = twitchio.HTTPException.__new__(twitchio.HTTPException)
                    exc.status = 403
                    raise exc

            return Channel()

    conn = connector_for(tmp_path, clock, Forbidden())
    result = await conn.send("hi")
    assert (result.sent, result.drop_code) == (False, "http_403")


def test_auth_accepts_a_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    twitch._check_port_free(port)  # free again after the with-block: must not raise


def test_auth_refuses_a_busy_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("localhost", 0))
        sock.listen()
        port = sock.getsockname()[1]
        with pytest.raises(ConfigError, match="in use"):
            twitch._check_port_free(port)


async def test_disconnect_is_not_logged_during_a_deliberate_close(tmp_path, clock):
    conn = connector_for(tmp_path, clock, FakeClient())
    client = twitch._Client(conn)
    conn._closing = True
    await client.event_websocket_closed(None)
    assert not list((tmp_path / "logs").glob("*.jsonl"))


async def test_rejected_app_credentials_are_a_setup_error(tmp_path, clock, monkeypatch):
    class RejectsLogin:
        def __init__(self, connector):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def start(self, with_adapter=False):
            exc = twitchio.HTTPException.__new__(twitchio.HTTPException)
            exc.status = 403
            raise exc

    monkeypatch.setattr(twitch, "_Client", RejectsLogin)
    conn = twitch.TwitchConnector(make_config(tmp_path), ActivityLog(tmp_path, clock), clock)

    async def noop(*args):
        pass

    with pytest.raises(ConfigError, match="TWITCH_CLIENT_SECRET"):
        await conn.run(noop, noop)
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_twitch_mapping.py -q`

Expected: FAIL. `ModuleNotFoundError: No module named 'bot.connectors.twitch'`

- [ ] **Step 3: Write `bot/connectors/twitch.py`**

```python
"""Twitch connector: reads chat over EventSub WebSocket, sends through Helix with the app token."""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import socket
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import twitchio
from twitchio import eventsub

from bot.activity_log import ActivityLog
from bot.clock import Clock
from bot.config import Config, ConfigError
from bot.connectors.base import AuthRequired, ChatMessage, OnMessage, OnReady, ReadyInfo, SendResult, UserRef

logger = logging.getLogger(__name__)

BOT_SCOPES = ("user:read:chat", "user:write:chat", "user:bot", "user:read:moderated_channels")
AUTH_PORT = 4343  # the Twitch app's OAuth redirect must be exactly http://localhost:4343/oauth/callback
# force_verify makes Twitch show which account is approving, so the wrong account can't slip through.
AUTH_URL = f"http://localhost:{AUTH_PORT}/oauth?scopes=" + "%20".join(BOT_SCOPES) + "&force_verify=true"
WATCHDOG_SECONDS = 30  # how often to check that the bot is still logged in and subscribed
NO_SUBSCRIPTION_GRACE = 240  # seconds without a chat subscription before giving up (systemd restarts us)
AUTH_FAILURE_STATUSES = {400, 401, 403}  # Twitch rejected the token itself; anything else may be transient
_CREDENTIALS_REJECTED = (
    "Twitch rejected the app login (HTTP {status}): check TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET in .env"
)


def strip_reply_mention(text: str, reply: Any) -> str:
    """Drop the leading "@name " Twitch clients put on a reply, so "@bot alligator" reads "alligator"."""
    parent = getattr(getattr(reply, "parent_user", None), "name", None) if reply is not None else None
    if not parent:
        return text
    head, _, rest = text.partition(" ")
    if head.lower() == f"@{parent.lower()}" and rest:
        return rest.lstrip()
    return text


def to_chat_message(payload: Any, clock: Clock) -> ChatMessage:
    """Map a twitchio.ChatMessage to our platform-neutral ChatMessage."""
    chatter = payload.chatter
    source = payload.source_broadcaster
    return ChatMessage(
        id=payload.id,
        user_id=str(chatter.id),
        login=(chatter.name or "").lower(),
        display_name=chatter.display_name or chatter.name or "",
        text=strip_reply_mention(payload.text, getattr(payload, "reply", None)),
        is_broadcaster=bool(chatter.broadcaster),
        is_moderator=bool(chatter.moderator),
        source_channel_id=str(source.id) if source is not None else None,
        received_at=clock.now(),
    )


def read_bot_token(path: Path, bot_id: str) -> tuple[str, str]:
    """Return (access token, refresh token) for the bot from the token file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = data.get(bot_id) if isinstance(data, dict) else None
        if not entry:
            raise AuthRequired(f"no token for bot user {bot_id} in {path}")
        return entry["token"], entry["refresh"]
    except FileNotFoundError:
        raise AuthRequired(f"no token file at {path}") from None
    except json.JSONDecodeError:
        raise AuthRequired(f"token file {path} is corrupt") from None
    except (KeyError, TypeError):
        raise AuthRequired(f"token file {path} has no usable entry for bot user {bot_id}") from None


def write_token_file(path: Path, tokens: Mapping[str, Any]) -> None:
    """Atomically write tokens as JSON, readable only by this user (0600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tokens-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump({uid: dict(entry) for uid, entry in tokens.items()}, fp)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class _Client(twitchio.Client):
    def __init__(self, connector: TwitchConnector) -> None:
        cfg = connector.config
        super().__init__(
            client_id=cfg.client_id, client_secret=cfg.client_secret, bot_id=cfg.bot_id, fetch_client_user=False
        )
        self.connector = connector

    async def load_tokens(self, path: str | None = None) -> None:
        token, refresh = read_bot_token(self.connector.token_path, self.connector.config.bot_id)
        try:
            await self.add_token(token, refresh)
        except twitchio.InvalidTokenException as exc:
            if exc.status in AUTH_FAILURE_STATUSES:
                raise AuthRequired("the saved bot token is invalid and could not be refreshed") from exc
            # 5xx or 429 while validating: probably a Twitch hiccup, so crash and let systemd retry.
            raise RuntimeError(f"Twitch login check failed (HTTP {exc.status}); will retry") from exc

    async def save_tokens(self, path: str | None = None) -> None:
        self.connector.save_bot_token()  # never raises; TwitchIO's own save would be a no-op here

    async def setup_hook(self) -> None:
        await self.connector._setup(self)

    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        await self.connector._incoming(payload)

    async def event_token_refreshed(self, payload: Any) -> None:
        self.connector.save_bot_token()  # persist right away, so a hard kill doesn't lose the refresh

    async def event_websocket_welcome(self, payload: Any) -> None:
        self.connector._welcomed()

    async def event_websocket_closed(self, payload: Any) -> None:
        if not self.connector._closing:
            self.connector.log.write("disconnected")

    async def event_subscription_revoked(self, payload: Any) -> None:
        reason = getattr(getattr(payload, "reason", None), "value", None) or "unknown"
        await self.connector._fail(AuthRequired(f"Twitch revoked the chat subscription ({reason})"))


class TwitchConnector:
    def __init__(self, config: Config, log: ActivityLog, clock: Clock) -> None:
        self.config = config
        self.log = log
        self.clock = clock
        self.token_path = config.data_dir / ".tio.tokens.json"
        self.channel_id = ""
        self.is_mod = False
        self._client: _Client | None = None
        self._on_message: OnMessage | None = None
        self._on_ready: OnReady | None = None
        self._fatal: BaseException | None = None
        self._closing = False
        self._welcomes = 0
        self._watchdog: asyncio.Task[None] | None = None

    async def run(self, on_message: OnMessage, on_ready: OnReady) -> None:
        self._on_message, self._on_ready = on_message, on_ready
        self._client = _Client(self)
        try:
            async with self._client:
                await self._client.start(with_adapter=False)
        except twitchio.HTTPException as exc:
            if not self.channel_id and exc.status in AUTH_FAILURE_STATUSES:  # failed before setup finished
                raise ConfigError(_CREDENTIALS_REJECTED.format(status=exc.status)) from exc
            raise
        finally:
            if self._watchdog is not None:
                self._watchdog.cancel()
        if self._fatal is not None:
            raise self._fatal
        if not self._closing:  # nobody asked to stop: treat it as a crash so systemd restarts us
            raise RuntimeError("Twitch connection ended unexpectedly")

    async def _setup(self, client: _Client) -> None:
        users = await client.fetch_users(logins=[self.config.channel])
        if not users:
            raise ConfigError(f"Twitch channel {self.config.channel!r} not found")
        self.channel_id = str(users[0].id)
        self.is_mod = self.channel_id == self.config.bot_id
        if not self.is_mod:
            try:
                bot = client.create_partialuser(user_id=self.config.bot_id)
                async for ch in bot.fetch_moderated_channels(first=100, token_for=self.config.bot_id):
                    if str(ch.id) == self.channel_id:
                        self.is_mod = True
                        break
            except twitchio.HTTPException as exc:
                logger.warning("could not check moderator status: %s", exc)
        await client.subscribe_websocket(
            eventsub.ChatMessageSubscription(broadcaster_user_id=self.channel_id, user_id=self.config.bot_id),
            as_bot=True,
        )
        self._watchdog = asyncio.create_task(self._watch(client))
        assert self._on_ready is not None
        await self._on_ready(ReadyInfo(self.config.channel, self.channel_id, self.is_mod))

    async def _watch(self, client: _Client) -> None:
        """TwitchIO can lose the login or the chat subscription without ending; detect that and fail loudly."""
        loop = asyncio.get_running_loop()
        empty_since: float | None = None
        while not self._closing:
            await asyncio.sleep(WATCHDOG_SECONDS)
            if self.config.bot_id not in client.tokens:  # a runtime refresh failed and TwitchIO dropped it
                await self._fail(AuthRequired("the bot's Twitch login expired and could not be refreshed"))
                return
            if client.websocket_subscriptions():
                empty_since = None
            elif empty_since is None:
                empty_since = loop.time()
            elif loop.time() - empty_since >= NO_SUBSCRIPTION_GRACE:
                await self._fail(RuntimeError("lost the chat connection and could not get it back"))
                return

    def save_bot_token(self) -> None:
        """Write the bot's current (possibly refreshed) token to disk. Never raises."""
        client = self._client
        if client is None or self.config.bot_id not in client.tokens:
            return
        try:
            write_token_file(self.token_path, {self.config.bot_id: client.tokens[self.config.bot_id]})
        except OSError as exc:
            logger.exception("could not save the Twitch token")
            self.log.write("error", where="twitch.save_token", type=type(exc).__name__, message=str(exc))

    def _welcomed(self) -> None:
        self._welcomes += 1
        self.log.write("connected" if self._welcomes == 1 else "reconnected")

    async def _incoming(self, payload: twitchio.ChatMessage) -> None:
        if self._on_message is not None:
            await self._on_message(to_chat_message(payload, self.clock))

    async def _fail(self, exc: BaseException) -> None:
        self._fatal = exc
        await self.close()

    async def send(self, text: str, reply_to: str | None = None) -> SendResult:
        assert self._client is not None
        channel = self._client.create_partialuser(user_id=self.channel_id)
        # The app token gives a modded bot the Chat Bot badge; without mod status Twitch only accepts
        # the bot's own user token.
        token_for = None if self.is_mod else self.config.bot_id
        try:
            await channel.send_message(
                text, sender=self.config.bot_id, token_for=token_for, reply_to_message_id=reply_to
            )
        except twitchio.MessageRejectedError as exc:
            return SendResult(False, exc.code, exc.message)
        except twitchio.HTTPException as exc:
            if exc.status == 403 and self.is_mod:  # mod status was removed while running
                self.is_mod = False
                self.log.write("error", where="twitch.send", type="LostModStatus", message="sending as the bot now")
                if self._on_ready is not None:
                    await self._on_ready(ReadyInfo(self.config.channel, self.channel_id, False))
                return await self.send(text, reply_to)
            return SendResult(False, f"http_{exc.status}", str(exc))
        return SendResult(True)

    async def lookup_user(self, login: str) -> UserRef | None:
        assert self._client is not None
        try:
            users = await self._client.fetch_users(logins=[login])
        except twitchio.HTTPException:
            return None
        if not users:
            return None
        user = users[0]
        return UserRef(str(user.id), user.name or login, user.display_name or user.name or login)

    async def close(self) -> None:
        self._closing = True
        if self._watchdog is not None and self._watchdog is not asyncio.current_task():
            self._watchdog.cancel()
        if self._client is not None:
            await self._client.close()


def _check_port_free(port: int) -> None:
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
        except OSError:  # this address family isn't available here
            continue
        with sock:
            try:
                sock.bind((host, port))
            except OSError as exc:
                if family == socket.AF_INET6 and exc.errno == errno.EADDRNOTAVAIL:  # no IPv6 loopback here
                    continue
                raise ConfigError(f"port {port} is in use; close whatever is using it and run auth again") from None


async def authorize(config: Config) -> UserRef:
    """One-time login: serve http://localhost:4343, wait for the bot account to approve, save the token."""
    _check_port_free(AUTH_PORT)
    done: asyncio.Future[UserRef] = asyncio.get_running_loop().create_future()
    token_path = config.data_dir / ".tio.tokens.json"

    class AuthClient(twitchio.Client):
        async def event_oauth_authorized(self, payload: Any) -> None:
            try:
                valid = await self.add_token(payload.access_token, payload.refresh_token)
                write_token_file(token_path, {str(valid.user_id): self.tokens[str(valid.user_id)]})
            except Exception as exc:
                if not done.done():
                    done.set_exception(exc)
                return
            if not done.done():
                done.set_result(UserRef(str(valid.user_id), valid.login or "", valid.login or ""))

    client = AuthClient(client_id=config.client_id, client_secret=config.client_secret, fetch_client_user=False)
    async with client:
        try:
            await client.login(load_tokens=False, save_tokens=False)
        except twitchio.HTTPException as exc:
            if exc.status in AUTH_FAILURE_STATUSES:
                raise ConfigError(_CREDENTIALS_REJECTED.format(status=exc.status)) from exc
            raise
        await client.adapter.run()
        print(f"Open this URL in a browser where you're logged in as the BOT account:\n\n  {AUTH_URL}\n")
        user = await done
    return user
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_twitch_mapping.py -q`

Expected: PASS (19 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 5: Smoke-test the login page wiring (no real credentials needed)**

Run:

```bash
.venv/bin/python - <<'EOF'
import asyncio, aiohttp, twitchio
from bot.connectors.twitch import AUTH_URL
async def main():
    c = twitchio.Client(client_id="dummyclientid", client_secret="x")
    await c.adapter.run()
    await asyncio.sleep(0.3)
    async with aiohttp.ClientSession() as s:
        async with s.get(AUTH_URL, allow_redirects=False) as r:
            print(r.status, r.headers.get("Location"))
    await c.close()
asyncio.run(main())
EOF
```

Expected: `308 https://id.twitch.tv/oauth2/authorize?client_id=dummyclientid&redirect_uri=http://localhost:4343/oauth/callback&response_type=code&scope=...&force_verify=true...` with all four scopes (`user:read:chat`, `user:write:chat`, `user:bot`, `user:read:moderated_channels`) present in `scope=`, in any order.

- [ ] **Step 6: Commit**

```bash
git add bot/connectors/twitch.py tests/test_twitch_mapping.py
git commit -m "Add the Twitch connector and login flow"
```

### Task 17: Command-line entry point

`python -m bot` runs on Twitch, `python -m bot auth` does the one-time login, and `python -m bot console` plays in the terminal using `data/console/`.

- `.env` is read from next to the config file. Real environment variables win.
- SIGINT and SIGTERM call `request_shutdown("signal")`, which stops cleanly with exit 0 (spec §13). A second signal during a stuck shutdown exits immediately.
- A logging filter hides TwitchIO's irrelevant "install starlette" hint.
- A database written by a newer version of the bot exits with code 2, so systemd doesn't restart-loop. A setup error during `auth` (port 4343 busy) also exits 2 with a plain message.
- **Certificates:** the python.org macOS installers ship without root certificates, so every HTTPS call (Twitch, the fact APIs) fails until "Install Certificates.command" is run. That was found on Robert's laptop during review. `bot/certs.py` is imported from `bot/__init__.py`, so it runs before aiohttp builds its SSL contexts in every entry point. When Python has neither a CA file nor a non-empty CA folder, it points `SSL_CERT_FILE` at the `certifi` bundle (a new dependency).
- **Setup problems exit 2, which systemd never restarts:** an unreadable `.env`, an unwritable data folder, a corrupt database, a database from a newer bot, or Twitch rejecting the client ID or secret. Empty environment variables don't override `.env`.
- **Signals:** Ctrl+C before startup finishes exits 130 quietly. Only a genuine second signal force-exits, after flushing output.

The CLI tests run the real process, the way a person would.

**Files:**
- Create: `bot/__main__.py`, `bot/certs.py`
- Modify: `pyproject.toml` (add `certifi`), `bot/__init__.py` (import `bot.certs`)
- Test: `tests/test_certs.py`, `tests/test_cli.py`

- [ ] **Step 1: Write the failing test `tests/test_certs.py`**

```python
from types import SimpleNamespace

import certifi
import pytest

from bot import certs


def fake_paths(cafile=None, capath=None):
    # ssl.get_default_verify_paths() reports None for a CA file or folder that doesn't exist
    return lambda: SimpleNamespace(cafile=cafile, capath=capath)


@pytest.fixture
def clean_env(monkeypatch):
    # setenv first, so monkeypatch remembers and restores the original value after the test
    for name in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    return monkeypatch


def test_uses_certifi_when_python_has_no_ca_bundle(clean_env):
    clean_env.setattr(certs.ssl, "get_default_verify_paths", fake_paths())
    assert certs.ensure_ca_bundle()
    assert certs.os.environ["SSL_CERT_FILE"] == certifi.where()


def test_uses_certifi_when_the_cert_folder_is_empty(clean_env, tmp_path):
    clean_env.setattr(certs.ssl, "get_default_verify_paths", fake_paths(capath=str(tmp_path)))
    assert certs.ensure_ca_bundle()


def test_keeps_a_system_ca_file(clean_env, tmp_path):
    bundle = tmp_path / "cert.pem"
    bundle.write_text("x")
    clean_env.setattr(certs.ssl, "get_default_verify_paths", fake_paths(cafile=str(bundle)))
    assert not certs.ensure_ca_bundle()
    assert "SSL_CERT_FILE" not in certs.os.environ


def test_keeps_a_nonempty_system_cert_folder(clean_env, tmp_path):
    (tmp_path / "abcd1234.0").write_text("x")
    clean_env.setattr(certs.ssl, "get_default_verify_paths", fake_paths(capath=str(tmp_path)))
    assert not certs.ensure_ca_bundle()


def test_respects_explicit_settings(clean_env):
    clean_env.setenv("SSL_CERT_FILE", "/custom.pem")
    assert not certs.ensure_ca_bundle()
    assert certs.os.environ["SSL_CERT_FILE"] == "/custom.pem"
    clean_env.delenv("SSL_CERT_FILE")
    clean_env.setenv("SSL_CERT_DIR", "/custom/certs")
    assert not certs.ensure_ca_bundle()
```

- [ ] **Step 2: Write the failing test `tests/test_cli.py`**

```python
"""Runs the real `python -m bot` process, the way a person would."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text('channel = "test_channel"\n[outbox]\nrate_per_second = 3\nburst = 50\n', encoding="utf-8")
    return path


def run_bot(
    *args: str, stdin: str = "", env_file: str | None = None, tmp_path: Path, extra_env: dict | None = None
) -> subprocess.CompletedProcess:
    if env_file is not None:
        (tmp_path / ".env").write_text(env_file, encoding="utf-8")
    clean_env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), **(extra_env or {})}
    return subprocess.run(
        [sys.executable, "-m", "bot", *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=20,
        cwd=ROOT,
        env=clean_env,
    )


def test_console_mode_plays_and_shuts_down(tmp_path):
    config = write_config(tmp_path)
    result = run_bot(
        "console", "--config", str(config),
        stdin="alice: ?coinflip\nbob: ?help\n@mod: ?bot shutdown\nalice: typed after shutdown\n",
        tmp_path=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "bot → alice: 🪙" in result.stdout
    assert "bot → bob: Games: ?scramble ?hangman ?skip" in result.stdout
    assert "bot → mod: Shutting down (requested by mod)." in result.stdout
    assert (tmp_path / "data" / "console" / "bot.db").exists()
    assert list((tmp_path / "data" / "console" / "logs").glob("activity-*.jsonl"))


def test_run_without_secrets_exits_2(tmp_path):
    result = run_bot("--config", str(write_config(tmp_path)), env_file="", tmp_path=tmp_path)
    assert result.returncode == 2
    assert "TWITCH_CLIENT_ID is missing" in result.stderr


def test_auth_without_client_credentials_exits_2(tmp_path):
    result = run_bot("auth", "--config", str(write_config(tmp_path)), env_file="", tmp_path=tmp_path)
    assert result.returncode == 2
    assert "TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET" in result.stderr


def test_database_newer_than_code_exits_2(tmp_path):
    import sqlite3

    db = tmp_path / "data" / "console" / "bot.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version VALUES (99)")
    result = run_bot("console", "--config", str(write_config(tmp_path)), tmp_path=tmp_path)
    assert result.returncode == 2
    assert "newer than this code" in result.stderr


SECRETS = "TWITCH_CLIENT_ID=cid\nTWITCH_CLIENT_SECRET=secret\nBOT_ID=123\n"


def test_env_file_is_read_and_real_environment_wins(tmp_path):
    config = str(write_config(tmp_path))
    from_file = run_bot("--config", config, env_file=SECRETS + "OWNER_IDS=notnum\n", tmp_path=tmp_path)
    assert from_file.returncode == 2 and "got notnum" in from_file.stderr
    from_env = run_bot("--config", config, tmp_path=tmp_path, extra_env={"OWNER_IDS": "fromenv"})
    assert from_env.returncode == 2 and "got fromenv" in from_env.stderr
    empty_env = run_bot("--config", config, tmp_path=tmp_path, extra_env={"OWNER_IDS": ""})
    assert "got notnum" in empty_env.stderr  # an empty variable doesn't override .env


def test_corrupt_database_exits_2(tmp_path):
    db = tmp_path / "data" / "console" / "bot.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"this is not a sqlite database" * 100)
    result = run_bot("console", "--config", str(write_config(tmp_path)), tmp_path=tmp_path)
    assert result.returncode == 2
    assert "Setup error" in result.stderr


def test_sigterm_stops_cleanly(tmp_path):
    import json
    import select
    import signal
    import time

    config = write_config(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "bot", "console", "--config", str(config)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    try:
        ready, _, _ = select.select([proc.stdout], [], [], 10)  # don't hang if the bot never starts
        assert ready, "the bot did not start within 10 s"
        assert proc.stdout.readline().startswith("Console mode.")  # banner: the bot is running
        time.sleep(0.2)
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 0
    finally:
        proc.kill()
    logs = list((tmp_path / "data" / "console" / "logs").glob("activity-*.jsonl"))
    last = json.loads(logs[0].read_text().splitlines()[-1])
    assert last["event"] == "shutdown" and last["by"] == "signal"


def test_bad_config_exits_2(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('channel = "has spaces"\n', encoding="utf-8")
    result = run_bot("console", "--config", str(path), tmp_path=tmp_path)
    assert result.returncode == 2
    assert "channel must be a Twitch username" in result.stderr
```

- [ ] **Step 3: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_certs.py tests/test_cli.py -q`

Expected: FAIL. `cannot import name 'certs'` (and, once certs exists, the console test fails with `No module named bot.__main__`)

- [ ] **Step 4: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "offline-chat-bot"
version = "0.1.0"
description = "Twitch chat-games bot for jasontheween's offline chat"
requires-python = ">=3.11,<3.14"
dependencies = [
    "twitchio==3.3.2",
    "aiohttp>=3.9",
    "python-dotenv>=1.0",
    "certifi>=2024.2.2",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23"]

[tool.setuptools.packages.find]
include = ["bot*"]

[tool.setuptools.package-data]
bot = ["content/*.txt", "content/words/*.txt"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
filterwarnings = [
    # TwitchIO's web adapter subclasses aiohttp's Application; harmless, not ours to fix.
    "ignore:Inheritance class AiohttpAdapter from web.Application is discouraged:DeprecationWarning",
]
```

- [ ] **Step 5: Write `bot/__init__.py`**

```python
__version__ = "0.1.0"

# Set up a CA bundle before anything imports aiohttp (see bot/certs.py). Importing it here covers
# every entry point, since Python always imports the package first.
from bot import certs as _certs  # noqa: E402,F401
```

- [ ] **Step 6: Reinstall so `certifi` is available**

Run: `.venv/bin/pip install -e '.[dev]'`

Expected: ends with `Successfully installed ... certifi-...` (or "already satisfied").

- [ ] **Step 7: Write `bot/certs.py`**

```python
"""Make HTTPS work on Pythons that ship without root certificates.

The python.org macOS installers don't include a CA bundle until "Install Certificates.command"
is run, so every HTTPS connection (Twitch, the fact APIs) fails certificate checks. When
Python's default CA file is missing, point SSL_CERT_FILE at certifi's bundle. This must run
before aiohttp builds its SSL contexts, so `bot/__init__.py` imports this module.
"""

from __future__ import annotations

import os
import ssl

import certifi


def _has_certificates(directory: str | None) -> bool:
    if not directory or not os.path.isdir(directory):
        return False
    with os.scandir(directory) as entries:
        return any(True for _ in entries)


def ensure_ca_bundle() -> bool:
    """Set SSL_CERT_FILE to certifi's bundle if needed. Returns True if it was set."""
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return False
    paths = ssl.get_default_verify_paths()  # cafile/capath are None when missing
    if paths.cafile or _has_certificates(paths.capath):
        return False
    os.environ["SSL_CERT_FILE"] = certifi.where()
    return True


USING_CERTIFI = ensure_ca_bundle()
```

- [ ] **Step 8: Write `bot/__main__.py`**

```python
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
```

- [ ] **Step 9: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_certs.py tests/test_cli.py -q`

Expected: PASS (13 passed). Then run the full suite: `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 10: Play a round by hand**

Run: `.venv/bin/python -m bot console`, then type:

```text
alice: ?help
alice: ?coinflip
alice: ?catfact
@mod: ?bot status
@mod: ?bot shutdown
```

Expected: replies like `bot → alice: Games: ?scramble ?hangman ?skip | ...`, then a **live** cat fact. It mustn't be the built-in fallback line, which proves HTTPS works with the CA-bundle fallback. Then `bot → mod: ON · up 0s · games: 0 running · v0.1.0`, then `bot → mod: Shutting down (requested by mod).`, and the process exits on its own (`echo $?` prints `0`). Games can't start yet: the word lists arrive in Task 18.

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml bot/__init__.py bot/certs.py bot/__main__.py tests/test_certs.py tests/test_cli.py
git commit -m "Add the command-line entry point and a CA-bundle fallback"
```

### Task 18: Bundled content (word lists, 8-ball, fortunes, fallbacks)

This is content, not code, so this task gives exact rules plus a test that enforces them,
instead of listing every word.

**The streamer and game lists need extra care.** Robert asked to review them because made-up
entries are a real risk:
- Every entry in `streamers.txt` and `games.txt` must be checked against a public source while
  you write it. Don't take any name from memory alone.
- Record each entry's source in `bot/content/words/SOURCES.md`; the test enforces a row per
  entry.
- Robert signs off on both files in Task 20 before the bot goes live anywhere (spec §7, review
  gate).

**Files:**
- Test: `tests/test_content.py`
- Create:
  - `bot/content/8ball.txt` and `bot/content/fortunes.txt`
  - `bot/content/blocked_rot13.txt` and `bot/content/blocked_prose_rot13.txt`
  - `bot/content/fallback_catfacts.txt`, `fallback_dogfacts.txt`, `fallback_facts.txt`, and
    `fallback_dadjokes.txt`
  - `bot/content/words/{animals,countries,food,games,general,streamers}.txt`
  - `bot/content/words/SOURCES.md`

- [ ] **Step 1: Write the failing test `tests/test_content.py`**

```python
"""Rules for the bundled content files. These run against the real bot/content folder."""

import re

import pytest

from bot.assets import Assets
from bot.fun import BlockedWords
from bot.games.hangman import _valid as hangman_valid
from bot.games.scramble import _valid as scramble_valid

CATEGORIES = ["animals", "countries", "food", "games", "general", "streamers"]
REAL = Assets()


def test_categories_are_exactly_the_approved_six():
    assert REAL.categories() == CATEGORIES


@pytest.mark.parametrize("category", CATEGORIES)
def test_word_lists(category):
    words = REAL.words(category)
    assert len(words) >= 100, f"{category}: need at least 100 entries, have {len(words)}"
    lowered = [w.lower() for w in words]
    dupes = sorted({w for w in lowered if lowered.count(w) > 1})
    assert not dupes, f"{category}: duplicates {dupes}"
    bad = [w for w in words if not hangman_valid(w)]
    assert not bad, f"{category}: entries Hangman can't use (letters, spaces, - and ' only; 3+ letters): {bad}"
    scramble = [w for w in words if scramble_valid(w)]
    assert len(scramble) >= 40, f"{category}: need 40+ single words of 4-10 letters for Scramble, have {len(scramble)}"


@pytest.mark.parametrize("category", ["games", "streamers"])
def test_every_game_and_streamer_has_a_recorded_source(category):
    sources = (REAL.root / "words" / "SOURCES.md").read_text(encoding="utf-8").lower()
    missing = [w for w in REAL.words(category) if f"| {w.lower()} |" not in sources]
    assert not missing, f"{category}: no source row in words/SOURCES.md for {missing}"


def test_blocked_fragment_list_exists():
    import codecs

    fragments = [codecs.decode(line, "rot13") for line in REAL.lines("blocked_rot13")]
    assert len(fragments) >= 20
    assert all(f.isalpha() and f == f.lower() for f in fragments)


def _prose_patterns():
    import codecs

    return [codecs.decode(line, "rot13") for line in REAL.lines("blocked_prose_rot13")]


def test_prose_blocked_list_format():
    patterns = _prose_patterns()
    assert len(patterns) >= 50
    for p in patterns:
        assert re.fullmatch(r"\*?[a-z]+\*?", p) and (p.startswith("*") <= p.endswith("*")), p


def test_prose_blocked_list_catches_every_pattern_in_its_forms():
    # Built from the encoded list, so no blocked word is spelled out in this file.
    blocked = BlockedWords.load(REAL)
    for p in _prose_patterns():
        core = p.strip("*")
        if p.startswith("*"):
            forms = [core, "x" + core + "y", core.capitalize() + "ed"]
        elif p.endswith("*"):
            forms = [core, core + "ed", core.upper() + "S"]
        else:
            forms = [core, core + "s", core.capitalize()]
        for form in forms:
            assert blocked.found_in(f"They said {form} once."), p


def test_prose_blocked_list_allows_common_words():
    blocked = BlockedWords.load(REAL)
    for fine in (
        "The night sky over Japan is beautiful.", "Japanese analysts studied spices from Pakistan.",
        "Mustard is a condiment.", "Charles Dickens and Emily Dickinson wrote a lot.",
        "Homo sapiens evolved in Africa.",
        "Homo erectus used fire.", "Homologous structures share an origin.", "The title of the book.",
        "Cumulative rainfall rose.", "A cocktail party in Cockney London.", "Tardigrades survive space.",
        "Maine Coon cats are large.", "The Main Coon cat.", "Puss in Boots is a cat.",
        "Males are bigger than the opposite sex.",
        "Felis nigripes is the black-footed cat.", "The shitzu is a toy breed.", "The siege lasted a year.",
        "Blue-footed boobies dance.", "Spica is a bright star.", "Milford Sound is in New Zealand.",
        "The Wankel engine is a rotary engine.", "Cats reach sexual maturity early.", "A cocky rooster crowed.",
        "Scunthorpe is a town.", "Grapes, drapes and scrapes.", "Cockatoos and cockroaches.",
    ):
        assert not blocked.found_in(fine), fine


def test_8ball_has_20_answers():
    assert len(REAL.lines("8ball")) == 20


@pytest.mark.parametrize("name, minimum", [
    ("fortunes", 50), ("fallback_catfacts", 50), ("fallback_dogfacts", 50),
    ("fallback_facts", 50), ("fallback_dadjokes", 50),
])
def test_text_lists(name, minimum):
    lines = REAL.lines(name)
    assert len(lines) >= minimum
    assert len(set(lines)) == len(lines), f"{name} has duplicate lines"
    too_long = [line for line in lines if len(line) > 400]
    assert not too_long, f"{name}: lines over 400 characters: {too_long}"
    assert all(not re.search(r"https?://", line) for line in lines), f"{name}: no links in chat content"
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_content.py -q`

Expected: FAIL (`FileNotFoundError` for the missing content files; `categories()` returns `[]`).

- [ ] **Step 3: Write `bot/content/8ball.txt`**: the 20 classic Magic 8-Ball answers, one per line

```text
It is certain.
It is decidedly so.
Without a doubt.
Yes, definitely.
You may rely on it.
As I see it, yes.
Most likely.
Outlook good.
Yes.
Signs point to yes.
Reply hazy, try again.
Ask again later.
Better not tell you now.
Cannot predict now.
Concentrate and ask again.
Don't count on it.
My reply is no.
My sources say no.
Outlook not so good.
Very doubtful.
```

- [ ] **Step 4: Write `bot/content/blocked_rot13.txt`**: the fragments a Scramble puzzle must never show, ROT13-encoded (Task 8 decodes them). Copy exactly:

```text
# Fragments a Scramble puzzle must never show, ROT13-encoded so this file doesn't display them.
# Decode one with: python3 -c "import codecs; print(codecs.decode('fybg', 'rot13'))"  (prints 'slot')
nany
nahf
ovgpu
obbo
puvax
pyvg
pbpx
pbba
phz
phag
qvpx
qvyqb
qlxr
snt
shpx
tbbx
urvy
uvgyre
ubzb
wnc
wvmm
xvxr
xxx
xlf
zvys
anmv
arteb
avt
avtn
avtt
avte
ahqr
cnxv
cravf
cvff
cbea
chff
encr
ergneq
frzra
frk
fuvg
fvrt
fyhg
fcvp
gneq
gvg
genaal
gjng
intva
jnax
jrgonpx
juber
```

Then write `bot/content/blocked_prose_rot13.txt`: the words fact and joke text must never contain, ROT13-encoded, with the match rules in its header (Task 11's `BlockedWords` reads it). Copy exactly:

```text
# Words the bot must never post in fact or joke text, ROT13-encoded so this file doesn't display them.
# Decode one with: python3 -c "import codecs; print(codecs.decode('fybg', 'rot13'))"  (prints 'slot')
# "word" matches the whole word or its plural (+s, +es), "word*" any word starting with it, and
# "*word*" any word containing it. Innocent look-alikes (analysis, Scunthorpe, ...) are exempted in bot/fun.py.
nahf
pbba
phz
snt
urvy
ubzb
wnc
xxx
xlf
avt
avtn
cnxv
chffvrf
frkvre
frkvrfg
fvrt
fcvp
gneq
gvg
nany*
onfgneq*
ovgpu*
obyybpx*
obbo*
puvax*
pyvg*
pbpx*
phzz*
phzfu*
qvpx*
qlxr*
tbbx*
uvgyre*
vaprfg*
xvxr*
yvogneq*
znfgheong*
zvys*
zbyrfg*
anmv*
arteb*
ahqr*
ahqvg*
betnfz*
cnrqbcuvy*
crqbcuvy*
cravf*
cvff*
chffl*
encr*
encvat*
encvfg*
ergneq*
frzra*
frkl*
fxnax*
fyhg*
gvgg*
genaa*
gjng*
intva*
jnax*
jrgonpx*
*nefruby*
*nffuby*
*oybjwbo*
*phag*
*qvyqb*
*sntt*
*sntbg*
*shpx*
*unaqwbo*
*wvmm*
*avtt*
*cbea*
*fuvg*
*juber*
```

- [ ] **Step 5: Write the four general word lists**

Write `animals.txt`, `countries.txt`, `food.txt`, and `general.txt` in `bot/content/words/`,
with one entry per line.

**What goes in each file:**

| File | Contents |
|---|---|
| `animals` | Well-known animals anyone would recognize (`alligator`, `penguin`, `giraffe`, `sea lion`). |
| `countries` | Countries of the world (`france`, `brazil`, `japan`, `south korea`). |
| `food` | Everyday food plus snack and fast-food items: `ramen`, `pizza`, `takis`, `boba`, `wingstop`, `chipotle`, `hot cheetos`. Brand names are fine if they're widely known in the US. |
| `general` | Common, recognizable English nouns (`window`, `guitar`, `thunder`, `backpack`). Avoid obscure words; chat should be able to solve them. |

**Rules for every word file (the test checks most of these):**
- At least 100 entries.
- At least 40 single words of 4 to 10 letters, so Scramble has enough.
- Lowercase.
- ASCII letters, spaces, hyphens, and apostrophes only.
- 3+ letters and at most 30 characters.
- No duplicates.
- Nothing sexual, no slurs, nothing that's an insult when scrambled or revealed.

- [ ] **Step 6: Research and write `streamers.txt`, `games.txt`, and `SOURCES.md`**

Follow the same rules as Step 4, plus these:

**`streamers.txt`:**
- Well-known streamers (Twitch or YouTube or Kick), written as the name chat actually uses:
  `xqc`, `ludwig`, `pokimane`, `shroud`, `kai cenat`.
- Keep spaces as spaces and drop other symbols. A name with digits isn't allowed, so leave it out.
- Skip anyone best known for a scandal.

**`games.txt`:** popular and commonly streamed video games, for example `minecraft`, `valorant`,
`geoguessr`, `balatro`, `lethal company`, `elden ring`.

**Verifying entries:**
- **Streamers:** confirm the person exists and the spelling, using Wikipedia,
  TwitchTracker/StreamsCharts, or their official channel page.
- **Games:** confirm the title and spelling on Wikipedia, Steam, or the publisher's site.

**`SOURCES.md` format:** one table row per entry. The entry goes lowercase, exactly as in the
`.txt` file, between `| ` and ` |`:

```markdown
# Sources for streamers.txt and games.txt

Every entry was checked against the linked page on <date>. Robert reviews this file before go-live.

## streamers

| entry | source |
|---|---|
| xqc | https://en.wikipedia.org/wiki/XQc |

## games

| entry | source |
|---|---|
| minecraft | https://en.wikipedia.org/wiki/Minecraft |
```

- [ ] **Step 7: Write `fortunes.txt` and the four fallback files**

| File | Contents |
|---|---|
| `fortunes.txt` | 50+ short, upbeat fortune-cookie lines in the classic style ("A pleasant surprise is waiting for you."). One sentence each, no emoji, nothing negative. |
| `fallback_catfacts.txt`, `fallback_dogfacts.txt`, `fallback_facts.txt` | 50+ well-established facts each, one per line, under 400 characters, no links. These are the backups for when an API is down. Only use facts you're confident are true; if unsure, leave it out. |
| `fallback_dadjokes.txt` | 50+ clean dad jokes, one per line, setup and punchline on the same line. |

- [ ] **Step 8: Run the content test and the full suite**

Run: `.venv/bin/pytest tests/test_content.py -q`, then `.venv/bin/pytest -q`.
Expected: `19 passed`, then all 303 tests pass.

- [ ] **Step 9: Play every game by hand in console mode**

Run: `.venv/bin/python -m bot console`, then play `?scramble`, `?scramble categories`,
`?hangman streamers` (guess with `?g`), `?hint`, `?skip`, two names playing at once, `?cookie`,
and `?leaderboard`. Expected: words come from the new lists, and the bot never reveals a blank or
garbled word.

- [ ] **Step 10: Commit**

```bash
git add bot/content tests/test_content.py
git commit -m "Add bundled word lists, fortunes, 8-ball answers, and fallbacks"
```


### Task 19: README and systemd unit

Covers spec §15 and §16 ("A README covers setup, the commands, and the server move"). The service file encodes the restart rules:

- restart 30 s after a crash or lost connection, with no limit, so a long Twitch outage heals on its own;
- stay down after `?bot shutdown` (exit 0);
- never restart on exit 2 or 3, which need a person.

**Files:**
- Create: `README.md`, `deploy/offline-chat-bot.service`

- [ ] **Step 1: Write `deploy/offline-chat-bot.service`**

```ini
[Unit]
Description=Offline chat bot (Twitch)
After=network-online.target
Wants=network-online.target
# Never give up restarting after a crash: a long Twitch or network outage must not leave the bot
# stopped for good. Config errors (exit 2) and login problems (exit 3) are excluded below.
StartLimitIntervalSec=0

[Service]
User=chatbot
WorkingDirectory=/opt/offline-chat-bot
ExecStart=/opt/offline-chat-bot/.venv/bin/python -m bot
# Restart after a crash, but not after ?bot shutdown (exit 0),
# a config error (exit 2), or a needed re-login (exit 3).
Restart=on-failure
RestartSec=30
RestartPreventExitStatus=2 3
# A clean shutdown takes at most about 20 s (finish the current send, drain, close).
TimeoutStopSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Write `README.md`**

````markdown
# Offline Chat Bot

A Twitch chat bot for jasontheween's offline chat: personal chat games (Scramble, Hangman),
quick fun commands, per-game points with leaderboards, mod controls (pause, resume, shut down),
and a daily activity log. Design: `docs/superpowers/specs/2026-10-04-offline-chat-bot-design.md`.

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
| `?skip` | anyone | End your current game (no points) |
| `?leaderboard [game] [1-10]` | anyone | Top players by points |
| `?gamestats [game] [username]` | anyone | Wins, games played, points |
| `?8ball`, `?coinflip`, `?catfact`, `?dogfact`, `?fact`, `?dadjoke` | anyone | Quick fun |
| `?cookie`, `?cookie give <username>` | anyone | Daily fortune cookie (resets 00:00 UTC) |
| `?bot off` / `?bot on` / `?bot status` | mods, broadcaster, owners | Pause, resume, check. `?bot off` ends every running game with no points, and while paused the bot ignores everything except `?bot` from a mod |
| `?bot shutdown` | mods, broadcaster, owners | Stop the bot process. Only someone with access to the machine can start it again |
| `?stopgame` | mods, broadcaster, owners | End all running games with no points |

Categories: animals, countries, food, games, general, streamers.

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
````

- [ ] **Step 3: Full verification**

Run: `.venv/bin/pytest -q`. Expected: all tests pass (303).

Then follow the README's "Try it without Twitch" section exactly as written, from a fresh clone (`git clone . /tmp/ocb-check && cd /tmp/ocb-check`), to confirm the instructions work. Delete `/tmp/ocb-check` afterwards.

- [ ] **Step 4: Commit**

```bash
git add README.md deploy/offline-chat-bot.service
git commit -m "Add README and systemd unit"
```

- [ ] **Step 5: Update the workspace project profile**

In the outer workspace (`../projects/offline-chat-bot.md`):

- set Status to "Phase 1 built, awaiting live test" with the date;
- set the Run and Test commands to the real ones;
- add `README.md` under Authoritative Files.

Commit in the outer repo: `git -C .. add projects/offline-chat-bot.md && git -C .. commit -m "offline-chat-bot: Phase 1 built"`.

### Task 20: Live test on Twitch with Robert (manual)

This is spec §14.3 and the last items of §16. It needs Robert at the keyboard, because only he
can create accounts and approve logins. The agent walks him through it and records the results.

**Setup (Robert):**
- [ ] **Step 1:** Create the bot's Twitch account and verify its email.
- [ ] **Step 2:** Register the app at https://dev.twitch.tv/console:
  - redirect URL `http://localhost:4343/oauth/callback`;
  - category Chat Bot;
  - client type Confidential.
- [ ] **Step 3:** Fill in `.env` (`cp .env.example .env`), including his own user ID in
  `OWNER_IDS`.
- [ ] **Step 4:** Run `.venv/bin/python -m bot auth` and approve as the **bot** account (Twitch
  shows which account is approving). The printed "Authorized as ..." must name the bot account.
  Copy the printed `BOT_ID=` line into `.env`.
- [ ] **Step 5:** Set `channel` in `config.toml` to Robert's channel. **Before modding**, start
  the bot once and trigger one reply (`?coinflip`).
  - The log shows `is_mod: false`.
  - The reply arrives, sent with the bot's own token and no badge.
  - Stop the bot.
  Then, in Robert's chat, type `/mod <botaccount>`.
- [ ] **Step 6:** Have a second, non-mod Twitch account ready, or a friend.

**Checklist** (run `.venv/bin/python -m bot`; check each item off):
- [ ] **Step 7:** The startup log shows `startup ... "is_mod": true`, and the bot's chat
  messages show the purple Chat Bot badge. If it fails with `CERTIFICATE_VERIFY_FAILED`, the
  CA-bundle fallback in `bot/certs.py` didn't apply: check `SSL_CERT_FILE`.
- [ ] **Step 8:** Both accounts play their own games at the same time, and each one's answers
  only affect their own game. Scramble ends three ways: won (try `?hint`), timed out (wait
  45 s), and `?skip`. Hangman ends three ways too: won with `?g`, lost on 6 wrong letters, and
  timed out. Typing a plain "W" during Hangman does nothing. Replies show as threaded replies,
  and answering by using Twitch's reply button on the bot's message also works.
- [ ] **Step 9:** `?gamestats`, `?gamestats hangman <name>`, `?leaderboard`, and
  `?leaderboard scramble 3` show the right numbers.
- [ ] **Step 10:** Every quick command answers: `?8ball`, `?coinflip`, `?catfact`, `?dogfact`,
  `?fact`, `?dadjoke`, `?cookie`, `?cookie give <second account>`, `?help`, `?help hangman`.
- [ ] **Step 11:** The non-mod account's `?bot off` and `?stopgame` do nothing. A mod's
  `?stopgame` ends both accounts' games.
- [ ] **Step 12:** A mod's `?bot off` works: games are ignored. `?bot status` shows PAUSED.
  Restart the bot and it's still paused. `?bot on` resumes.
- [ ] **Step 13:** `?bot shutdown` posts "Shutting down (requested by ...)" and the process exits.
  `echo $?` prints `0`.
- [ ] **Step 14:** Connection and login robustness:
  - **Replies:** answering with Twitch's reply button on the bot's message works on **web and
    mobile**.
  - **Wi-Fi off for about 60 s:** chat resumes on its own, and the log shows `disconnected`
    then `reconnected`.
  - **Wi-Fi off for 5+ minutes:** after Wi-Fi returns, chat works again within a few minutes,
    either on its own or through a watchdog exit (code 1) that systemd would restart. A bot
    that stays deaf without exiting is a failure.
  - **Token file:** after a run of a few hours, `data/.tio.tokens.json` is updated on
    `?bot shutdown` (its mtime changes, and it's readable only by Robert, mode 0600).
  - **Failure exits:**
    - a bad `channel` exits 2;
    - deleting `data/.tio.tokens.json` exits 3;
    - Ctrl+C exits 0 with `shutdown` logged.
  - **Last:** remove the app under the bot account's Settings → Connections. The bot exits 3,
    naming the revocation. Re-run `auth` afterwards.
- [ ] **Step 15:** `data/logs/activity-<today>.jsonl` contains the following, and no ordinary
  chat lines:
  - `startup`, `connected`, `command`, `game_start`, `game_end`;
  - `admin` (off, on, shutdown, each with who did it);
  - `shutdown`.
- [ ] **Step 16:** Robert reviews `bot/content/words/streamers.txt`, `games.txt`, and
  `SOURCES.md`, and approves them or lists changes. Make the changes, rerun
  `.venv/bin/pytest tests/test_content.py`, and commit.
- [ ] **Step 17:** Record the results (date, what passed, anything changed) in the Execution log
  below. Then commit: `git add docs/superpowers/plans && git commit -m "Record Phase 1 live test results"`.

Phase 1 is done when every box above is checked (spec §16). Going live in jasontheween's chat
is then a config change: the contact mods the bot, `channel = "jasontheween"`, restart.

## Execution log

Record here anything that changes during execution: review findings, deviations from this
plan, and the live test results.

Tasks 1-19 were built on branch `phase1` on 2026-10-04 with subagents. Each task got:

- an exact-diff spec review against this plan;
- a code-quality review (Sonnet for small tasks, Opus for core ones).

The code blocks above are the final, reviewed versions; the entries below say what review changed.


- **Task 1** (`60acf1b`, `08da67a`): built as planned. The quality review found that `pip install -e .` leaves an untracked `offline_chat_bot.egg-info/`, so `*.egg-info/`, `build/`, and `dist/` were added to `.gitignore`.
- **Task 2** (`ae47724` + fix): the quality review found that `normalize` turned combining marks and format characters into spaces, so strikethrough "fancy text" became "h e l l o". It also found raw invisible characters in the source: a regex in `bot/text.py` and a test string. Cause: `\uXXXX` escapes in the agent's tool input were decoded into real characters while the prototype was being written, so the plan's Task 2 code blocks carry them too. Fix: `strip_invisible` now drops Unicode categories Cf, Mn, and Me plus the tag block U+E0000-E007F (U+E0000 itself is unassigned, category Cn). Tests build their special characters with `chr()`, and boundary tests for usernames were added. The plan's Task 2 code blocks are superseded by the committed files.
- **Task 3** (`7961ee5` + fix): the quality review found that `ActivityLog.write()` could raise on I/O errors, which would crash the error-reporting path itself. It also found that a caller field named `ts` could overwrite the timestamp. Fix: I/O errors in `write` and `prune` are caught and logged, `ts` is always the real timestamp, the asset cache got a comment, and tests were added.
- **Task 4** (`3d6c4d1` + fix): the quality review found four problems.
  - Migrations weren't atomic: sqlite3 doesn't wrap CREATE statements in a transaction, so one failed migration left the database unable to start.
  - The tests didn't cover the spec's wins tiebreak, the rename handling in `find_user`, or the foreign-key rule.
  - The leaderboard queries got slow at scale.
  - Smaller items: `claim_daily` reported any IntegrityError as "already used", `_iso` didn't convert to UTC, and a newer database was accepted silently.
  - Fix:
    - each migration runs as `BEGIN; ...; COMMIT;` through `executescript` inside `with conn`;
    - a database version newer than the code raises an error;
    - the ranking SQL aggregates before joining, with separate all-games and one-game queries, SQL `LIMIT`, and `ROW_NUMBER()` for rank;
    - migration 1 adds indexes `round_players(user_id, points, won)` and `rounds(game)`. Measured at 8k users and 373k player rows: overall leaderboard 220 to 14 ms, per game 125 to 61 ms;
    - `claim_daily` uses `ON CONFLICT DO NOTHING` and checks `rowcount`;
    - `_iso` converts to UTC;
    - 8 tests were added, and the tests close their stores.
- **Task 5** (`7784159` + fix): the quality review found that `drain()` didn't honor its timeout and that sends had no timeout of their own. TwitchIO uses aiohttp's 300 s default, so a dead network could hang shutdown or freeze the queue for minutes. It also found that an unexpected error (e.g. a bad send result) killed the `run()` loop silently. Minor findings: the fixed 0.25 s poll capped the real send rate (rate 3 gave 2/s), `run()` took up to 1 s to stop, coalescing across priority lanes broke ordering, and leftovers and drops weren't logged with their text. Fix: per-send `asyncio.wait_for` timeout (10 s), `drain` wrapped in `asyncio.timeout` that logs leftovers, result handling inside the try, `run()` catches and logs errors and continues, waits on stop or wake, and paces by tokens; a flush lock keeps `run`/`drain` from sending concurrently; coalescing that changes lanes re-inserts the message; 10 tests added.
- **Task 6** (`099bc29` + fix): the quality review found that pruning at 10,000 cooldown entries only drops expired ones. With a live set of 10k or more, every `trigger()` paid a full rescan and memory still grew. Fix: after a prune, the next one waits until the dict doubles (amortized O(1)). Tests were added for `ready()`, pruning, and the back-off.
- **Task 7** (`65cc4b0` + fix): the quality review found that a mixed-case command name registered fine but could never be found (lookup lowercases), and that a typo in `group` silently dropped a command from `?help`. Also, `parse_command` split only on a literal space, so a tab or no-break space glued words together. Fix: `add()` rejects non-lowercase names and unknown groups, the duplicate error names the clashing alias, and parsing splits on any whitespace. Tests were added.
- **Task 8** (`d94a50b` + fix): the quality review found that a word made of one repeated letter couldn't be scrambled and was shown unscrambled. Fix: Scramble requires two distinct letters, plus a test. Pushed back on: deduplicating word lists in the game (Task 18's content test already rejects case-insensitive duplicates). Deferred: a timer-reset hook on `Outcome` for streak games (Phase 2, Higher or Lower; it's one optional field plus one line in the manager).
- **Task 9** (`50d74a5` + follow-up): the quality review found no defects. Following its UX note, a wrong `?g <answer>` now replies "❌ Not it." instead of nothing; `?g` is explicit, and the 2 s cooldown bounds it. Tests were added for punctuation, repeated letters, and extra words after `?g`.
- **Task 10** (`f1c4172` + fix): the Opus quality review found three things.
  - **Stacked cooldowns:** the per-user command cooldown and the game cooldown stacked on start commands. A fast win followed by `?scramble` was silently ignored, then showed a wrong countdown, and the wait came to about 20 s instead of 10. Picking a category right after listing them was also silently ignored.
  - **Memory:** `_cooldown_until` grew forever.
  - **Tests:** the error paths were untested.
  - **Fix:**
    - start commands have no command cooldowns; the game cooldown is the only limit, and refusal and category replies are rate-limited separately to one per 5 s per player;
    - game cooldowns use `Cooldowns`, so they're pruned;
    - `_finish` checks itself and never runs twice;
    - a timeout is forced if a game's `on_timeout` doesn't finish, and an unfinished result defaults to "timeout";
    - coalesce keys are per round;
    - session names and `reply_to` refresh on every player message;
    - start handlers are bound per game class, so aliases work later;
    - the redundant `touch_user` was dropped (`record_round` upserts the player);
    - 8 tests added.
- **Task 10 cleanup** (after the re-review): "Couldn't start that game." goes through the 5 s notice rate limit, the stale `record_round` docstring was fixed, and tests were added for a finished timeout with no result, the category-list rate limit, and a real routing test for undeclared in-game commands. Spec §5 and §6 were updated to match (start commands have no command cooldowns; the manager rate-limits its replies).
- **Task 11** (`6dac3e1` + fix): the Opus quality review found three problems.
  - Fields that weren't strings (e.g. `{"fact": null}`) were posted as "None".
  - `?cookie give` echoed the typed login ("Couldn't find a user named X"), so a troll could make the mod-badged bot repeat words of their choosing. The same pattern was in `?gamestats`.
  - Third-party API text was posted with no filter for links, mentions, or control characters, and the bot as a mod skips Twitch's link filter.
  - Fix:
    - API text must be a string; it is stripped of invisible and control characters, and falls back if it contains `://`, `www.`, or `@name`;
    - the no-echo replies are "Couldn't find that user." and "No stats for that user yet." (the latter applied in Task 12's code before it was built);
    - user lookups time out after 5 s;
    - self-gifting is also checked by user ID;
    - `?cookie <anything but give>` shows usage instead of spending the cookie;
    - mentions use the login for localized display names;
    - cookie records are always JSON;
    - HTTP bodies are capped at 64 KB, and the User-Agent carries the version;
    - 9 tests added.
- **Task 11, second fix** (after the re-review): the 64 KB body cap used `resp.content.read(n)`, which returns only what has arrived so far. A response arriving in pieces was cut off and silently fell back. The fix reads with an `iter_chunked` loop capped at 64 KB, with tests for a two-piece body and an oversized body. Fact text is NFC-normalized first, so decomposed accents survive. The re-review also found that this Mac's python.org Python 3.12 has no root certificates (every HTTPS call fails), which is handled in Task 17.
- **Task 12** (`9ae5b99` + fix): the quality review found two problems.
  - `?help <x>` echoed any `^[a-z0-9_]{1,20}$` word, so underscore-joined troll phrases came back from the mod-badged bot.
  - `?leaderboard` used `str.isdigit()`, so "-5" was reported as an unknown game, and "²" (a digit to `isdigit` but rejected by `int`) crashed the handler.
  - Fix: `?help` never echoes ("No command by that name."), limits must match `-?[0-9]+` (ASCII) and are clamped, game names are lowercased defensively, and edge-case tests were added.
- **Task 13** (`8ca00dd` + fix): the quality review found that several config mistakes were silently accepted instead of exiting 2.
  - Unknown or misspelled keys, and sections of the wrong type, fell back to defaults.
  - `outbox.rate_per_second` had no maximum, and `nan` or `inf` passed and disabled throttling entirely.
  - Non-numeric OWNER_IDS were accepted.
  - The prefixes `/` and `.` were accepted, though Twitch intercepts them.
  - Fix: a schema check rejects unknown keys and non-table sections; numbers must be finite; the send rate is capped at 3/s; OWNER_IDS must be numeric on Twitch (console IDs are still allowed); prefixes can't start with `/` or `.`; at least one game must be enabled; duplicate games are dropped; the channel must be a string. Tests were added. Task 17's CLI test config now uses rate 3 with burst 50.
- **Task 14** (`3ebc45f` + fix): the quality review found that a line typed after `?bot shutdown` in interactive console mode raised "Event loop is closed" on the stdin thread and printed a traceback. Fix: the reader is now a testable `pump_lines` function that stops quietly when the loop has closed, and `run()` returns at once if `close()` came first. Tests were added; the closed-loop test fails against the old code. Pushed back on the shared-chat line syntax: that flow test builds the ChatMessage directly. Task 17's CLI test also sends a line after shutdown and asserts there's no traceback.
- **Task 15** (`9554d54` + fix): the Opus quality review confirmed the core is race-free under TwitchIO's one-task-per-message model, and found three things.
  - Cleanup in `run()` wasn't guarded. An error in `connector.close()` turned a deliberate `?bot shutdown` into exit 1 (and a systemd restart) and skipped the `shutdown` log.
  - `touch_user` ran outside the handler guard.
  - Minor: replies arriving after shutdown were lost unlogged; `wait_for(outbox_task, 1.0)` could cancel a send mid-flight; a failing log rollover could kill the tick loop; after a connector failure, drain tried to send to a dead connection; a second signal couldn't force an exit; and the Twitch connector ending without `close()` must count as a crash.
  - Fix:
    - each cleanup step is guarded and logged; `close()` is bounded to 5 s; the `shutdown` log is in `finally`; a cancelled `run()` still records games as stopped;
    - `touch_user` is inside the guard;
    - `Outbox.close()` makes late enqueues log as dropped, and `Outbox.discard()` is used instead of drain after a connector failure;
    - the send loop gets up to the send timeout to finish;
    - each tick step is guarded separately;
    - `__main__`: a second signal force-exits;
    - `TwitchConnector.run` raises if the connection ends without `close()`;
    - 11 tests added. Spans Tasks 5, 15, 16, and 17.
- **Task 16** (`cc6a532` + fix): the Opus quality review, checked against TwitchIO 3.3.2's source, found five problems.
  - **Critical, token saving was a no-op:** TwitchIO's save returns early unless its own loader ran, so a refreshed token was never written, and later restarts depended on the original refresh token.
  - **The bot could go silently deaf:** failed reconnects, failed re-subscribes, or a runtime refresh failure leave the process alive with no chat, and the "ended unexpectedly" branch can't be reached with the real TwitchIO.
  - **Startup outages looked like bad logins:** TwitchIO wraps 5xx and 429 validation errors in InvalidTokenException, so a brief outage became exit 3 with no restart.
  - **Non-mod sends fail:** an app-token send without mod status or `channel:bot` is refused.
  - Minors: HTTP errors escaped `send`; a busy port 4343 hung `auth`; a malformed token file crashed; "disconnected" was logged on deliberate shutdown.
  - Fix:
    - tokens are written by our own atomic, 0600 `write_token_file`, on close and on every `token_refreshed`, and saving never raises;
    - a 30 s watchdog fails with AuthRequired if the bot token is dropped, or with RuntimeError after 4 min without a chat subscription;
    - InvalidTokenException maps to AuthRequired only for 400/401/403, otherwise RuntimeError, so systemd retries;
    - sends use the app token when modded and the bot's user token otherwise;
    - HTTP errors become `SendResult(False, "http_<status>")`;
    - `auth` checks the port first, surfaces token errors, and uses `force_verify=true`;
    - a malformed token file means AuthRequired;
    - revocation messages name the reason;
    - `fetch_client_user=False`;
    - 9 tests added with fake TwitchIO pieces.
- **Task 16 follow-up** (after the re-review): the watchdog is cancelled when `run()` exits by any path, and the auth port check covers IPv6 too (using `errno.EADDRNOTAVAIL`, since its number differs between macOS and Linux). Task 17 maps a ConfigError during `auth` (busy port) to exit 2. Task 19's systemd unit now retries every 30 s with no start limit (`StartLimitIntervalSec=0`): the old "5 restarts in 10 minutes" would leave the bot stopped for good after an outage longer than about a minute. Exits 2 and 3 are still never restarted. Spec §15 is updated to match.
- **Task 17** (`ae9b14e` + follow-up): the Opus quality review said ready to merge, and its cheap follow-ups were taken.
  - Setup problems exit 2 instead of 1, so systemd stops instead of retrying forever: an unreadable `.env`, an unwritable data folder, a corrupt database, a new `DatabaseTooNew`, and Twitch rejecting the client ID or secret (in both `run` and `auth`).
  - A real signal count: only a genuine second signal force-exits, after flushing output, with the bot's current exit code.
  - `bot.certs` is imported from `bot/__init__.py`, so no import reordering can break HTTPS. An empty CA folder counts as missing, and a line is logged when certifi is used.
  - Empty environment variables don't override `.env`; Ctrl+C before startup finishes exits 130 quietly; a test that leaked `SSL_CERT_FILE` is fixed.
  - Tests added: `.env` precedence, a corrupt database, SIGTERM in a real process, rejected credentials, and the CA folder cases.
- **Task 17 nits** (after the final re-review): `authorize` maps only HTTP 400/401/403 to the "check your client ID/secret" ConfigError, so a Twitch outage keeps its real error. The SIGTERM test waits at most 10 s for the startup banner instead of possibly hanging.
- **Task 18** (`911b52f` + follow-up): the implementer verified every streamer and game against Wikipedia or TwitchTracker (281 sources) and found that random scrambles can spell slurs ("giraffe" about 5% of the time). The Opus content review found nothing wrong or made up.
  - Code fix: Scramble reshuffles until the scramble contains none of the fragments in `content/blocked_rot13.txt` (ROT13-encoded), and skips a word that can't be scrambled cleanly. Checked on the real lists: 20,760 scrambles, zero blocked fragments, every word scramblable.
  - Scramble accepts any same-letters word from its category (undertale/deltarune, canoe/ocean).
  - Content: the ~16 non-streamer words dropped only for scramble risk are restored, the streamer "sneaky" was removed (adult content since 2024), and two imprecise facts were reworded.
  - For Robert's review: 21 non-English-language streamers that Jason's chat may not recognize, Maya Higa (borderline), and mostly-YouTube creators.
  - Process note: one research request from the coordinator (4 calls) and one from the reviewer sent Robert's email in a User-Agent header to Wikimedia/Wikipedia. Disclosed to Robert; generic User-Agents only from then on.
- **Task 18 second follow-up** (after the re-review): 14 fragments added to the blocked list (a self-harm abbreviation, Nazi-salute words, two slurs that could form from 'Pakistan' and 'Japan', and a few sexual and anatomical terms), for 53 in total. Re-verified: no scramble contains a blocked fragment and every word stays scramblable. Scramble logs a warning if the blocked list is missing.
- **Task 19** (`4f4cb22` + fix): the review found no wrong claims, but five gaps: (1) `?bot off` didn't mention that it ends all games and ignores everything else while paused; (2) the install step was buried in the optional console section; (3) OWNER_IDS needs a numeric ID and nothing explained how to find it; (4) there was no way to re-run auth on a headless server; (5) secrets copied to the server could stay world-readable. Fix: a separate Install section, a curl lookup for the numeric ID, a server re-auth recipe (copy the token or use an SSH tunnel), `chmod 600` for the secrets, plus the minors (exit 130, 2FA note, "refused" wording, the systemctl restart). The systemd unit gains `TimeoutStopSec=30` and `PYTHONUNBUFFERED=1`.
- **Final whole-implementation review** (Opus, after Task 19; fixes in `4b6810c`): two critical, two important, and several minor findings.
  - **Critical, fact text was unfiltered for words:** API facts and jokes were checked for links and mentions but not for slurs, and text cut off mid-sentence could post. Fix: a `BlockedWords` check over `content/blocked_rot13.txt` (3-letter fragments as whole words or plurals, longer ones at a word start, with a short list of innocent words such as analysis and Pakistan), and text that doesn't start with a capital letter, digit, or quote falls back.
  - **Critical, Hangman could spell words:** wrong letters were listed in guess order, so a player could make the bot write a slur. Fix: wrong letters are sorted.
  - **Important, personal commands blocked everyone:** `?cookie`, `?gamestats`, and `?help` shared the 5 s chat-wide cooldown. Fix: per-user cooldown only.
  - **Important, non-mod sending:** a non-mod bot still sent at 2/s burst 3, over Twitch's 20 per 30 s, and losing mod status mid-run made every app-token send fail with 403. Fix: 0.6/s with burst 1 when not a mod; on a 403 while modded the connector switches to the bot token, logs `LostModStatus`, retries once, and calls `on_ready` again so the core slows down (`startup` is still logged once).
  - Minors: refusal notices keyed per game; config rejects the placeholder channel and a `busy_queue` above the outbox queue; SQLite `synchronous=NORMAL`; "1 win"; help texts, comments, README, and spec (§3, §4 `Connector.run`, §5 cooldowns and threading, facts filter, Hangman board, §13) brought up to date; the Task 20 Wi-Fi check now expects recovery (on its own or via a watchdog exit and restart) instead of a guaranteed exit. Family Feud is marked dropped in the spec.
  - Kept as designed: 25 games at once (Robert's choice).
  - Tests: 281 → 296.
- **Final re-review** (Opus): Hangman sorting, personal cooldowns, the non-mod rate, per-game notices, and the lost-mod path (no loop possible; probed with a double 403) all confirmed. Three problems found and fixed:
  - **Critical, the fact filter's length rule missed variants:** a 3-letter fragment only matched as a whole word, so longer spellings of the same slur, and an irregular plural of another, got through. **Important:** swears inside compounds were missed because matching was prefix-only. Fix: fact text now uses its own list, `content/blocked_prose_rot13.txt`, where each pattern states how it matches (whole word or plural, word start, or anywhere inside a word), plus a short innocent list ("Milford", "Scunthorpe", "Homo sapiens", "Maine Coon"). `-es` plurals are recognized only after s, x, z, ch, or sh, so "spices" isn't a plural. Tests derive every pattern's forms from the encoded list, so no blocked word is spelled out in the test files. On ~1,360 real API texts, the only text blocked is a fact naming Hitler, as intended.
  - **Important, the placeholder channel broke console mode and `auth`:** it's now rejected only when connecting to Twitch.
  - **Minors taken:** the cut-off check rejects only a lowercase first letter (curly quotes and `$` now pass); while the busy brake is on, Stats, Fun, and Info commands are ignored so personal replies can't crowd out game messages; the `config.toml` cooldown comment and spec notice wording are updated; tests added for "1 win" in the per-game line and for `synchronous=NORMAL`.
  - Kept: "Moby Dick" and "Van Dyke" still fall back (cheap); losing mod status is one-way until a restart.
  - Tests: 296 → 303.
