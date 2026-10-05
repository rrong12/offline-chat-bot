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
