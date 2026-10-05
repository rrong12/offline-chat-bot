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
