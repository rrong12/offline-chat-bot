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


async def test_console_can_simulate_going_live(clock: FakeClock):
    from bot.connectors.console import ConsoleConnector

    changes = []

    async def on_live(live):
        changes.append(live)

    conn = ConsoleConnector(clock=clock, lines=["!live", "!offline"], out=lambda s: None)
    conn.on_live = on_live
    seen = []

    async def on_message(msg):
        seen.append(msg)

    async def on_ready(info):
        pass

    await conn.run(on_message, on_ready)
    assert changes == [True, False] and seen == [] and await conn.is_live() is False
