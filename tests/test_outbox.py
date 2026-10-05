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
