from itertools import count

from bot.clock import FakeClock
from bot.connectors.console import ConsoleConnector, parse_console_line


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


async def test_console_lookup_user(clock: FakeClock):
    conn = ConsoleConnector(clock=clock, lines=[])
    assert (await conn.lookup_user("@Bob")).login == "bob"
    assert await conn.lookup_user("x") is None
