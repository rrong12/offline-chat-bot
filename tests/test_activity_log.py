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
