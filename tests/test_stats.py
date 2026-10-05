from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot.stats import GameStats, PlayerResult, RoundRecord, StatsStore

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store() -> StatsStore:
    s = StatsStore(":memory:")
    s.touch_user("u1", "alice", "Alice", T0)
    return s


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


def test_touch_and_find_user_case_insensitive(store: StatsStore):
    assert store.find_user("ALICE").user_id == "u1"
    assert store.find_user("nobody") is None


def test_touch_user_updates_renamed_login(store: StatsStore):
    store.touch_user("u1", "alice_new", "Alice_New", T0 + timedelta(days=1))
    assert store.find_user("alice_new").display_name == "Alice_New"


def test_record_round_upserts_players_and_returns_id(store: StatsStore):
    rid = record(store, "scramble", [player("u2", 10, True), player("u3")])
    assert rid == 1
    assert store.find_user("user_u2").user_id == "u2"


def test_leaderboard_orders_by_points_then_wins_then_login(store: StatsStore):
    record(store, "scramble", [player("b", 10, True)])
    record(store, "scramble", [player("a", 10, True)])
    record(store, "hangman", [player("c", 7, False), player("d", 0)])
    rows = store.leaderboard(None, 10)
    assert [r.user_id for r in rows] == ["a", "b", "c"]  # d has 0 points and is left out
    assert [r.user_id for r in store.leaderboard("hangman", 10)] == ["c"]
    assert len(store.leaderboard(None, 2)) == 2


def test_user_stats_per_game_and_rank(store: StatsStore):
    record(store, "scramble", [player("a", 10, True), player("b")])
    record(store, "scramble", [player("b", 7, True)])
    record(store, "hangman", [player("a", 3)], outcome="lost")
    assert store.user_stats("a") == [GameStats("scramble", 1, 1, 10), GameStats("hangman", 1, 0, 3)]
    assert store.rank("a", "scramble") == 1
    assert store.rank("b", "scramble") == 2
    assert store.rank("zzz", "scramble") is None


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
    assert StatsStore(path).get_state("paused") == "1"
