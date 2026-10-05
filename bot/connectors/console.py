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
