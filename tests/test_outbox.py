import asyncio

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
