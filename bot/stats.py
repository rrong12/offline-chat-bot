"""SQLite storage: users, game rounds and players, daily uses, and persistent bot state."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
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
    """,
]


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
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class StatsStore:
    def __init__(self, path: Path | str) -> None:
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self._conn:
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self._conn.execute("SELECT version FROM schema_version").fetchone()
            version = row["version"] if row else 0
            if row is None:
                self._conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        for number, sql in enumerate(MIGRATIONS[version:], start=version + 1):
            with self._conn:
                for statement in sql.split(";"):
                    if statement.strip():
                        self._conn.execute(statement)
                self._conn.execute("UPDATE schema_version SET version = ?", (number,))

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
        """Write a finished round and its players in one transaction. Returns the round id."""
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

    def _ranked(self, game: str | None) -> list[LeaderRow]:
        rows = self._conn.execute(
            """SELECT rp.user_id, u.login, u.display_name,
                      SUM(rp.points) AS points, SUM(rp.won) AS wins
               FROM round_players rp
               JOIN rounds r ON r.round_id = rp.round_id
               JOIN users u ON u.user_id = rp.user_id
               WHERE (:game IS NULL OR r.game = :game)
               GROUP BY rp.user_id
               HAVING SUM(rp.points) > 0
               ORDER BY points DESC, wins DESC, u.login ASC""",
            {"game": game},
        ).fetchall()
        return [LeaderRow(r["user_id"], r["login"], r["display_name"], r["points"], r["wins"]) for r in rows]

    def leaderboard(self, game: str | None, limit: int) -> list[LeaderRow]:
        return self._ranked(game)[:limit]

    def rank(self, user_id: str, game: str | None) -> int | None:
        for position, row in enumerate(self._ranked(game), start=1):
            if row.user_id == user_id:
                return position
        return None

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
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO daily_uses (user_id, feature, utc_date, result) VALUES (?, ?, ?, ?)",
                    (user_id, feature, utc_date, result),
                )
        except sqlite3.IntegrityError:
            return False
        return True

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
