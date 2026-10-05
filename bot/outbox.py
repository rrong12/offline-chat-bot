"""Every message the bot sends goes through here: rate limit, bounded queue, coalescing."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from bot.activity_log import ActivityLog
from bot.clock import Clock
from bot.connectors.base import SendResult
from bot.text import truncate

logger = logging.getLogger(__name__)

SendFn = Callable[[str, str | None], Awaitable[SendResult]]


@dataclass
class OutMessage:
    text: str
    reply_to: str | None = None
    coalesce_key: str | None = None
    priority: bool = False


class Outbox:
    def __init__(
        self,
        send: SendFn,
        clock: Clock,
        log: ActivityLog,
        *,
        rate: float = 1.0,
        burst: int = 3,
        max_queue: int = 20,
    ) -> None:
        self._send = send
        self._clock = clock
        self._log = log
        self.rate = rate
        self.burst = burst
        self.max_queue = max_queue
        self._queue: list[OutMessage] = []
        self._tokens = float(burst)
        self._last_refill = clock.mono()
        self._wake = asyncio.Event()

    def __len__(self) -> int:
        return len(self._queue)

    def pending(self) -> list[str]:
        return [m.text for m in self._queue]

    def enqueue(
        self,
        text: str,
        *,
        reply_to: str | None = None,
        coalesce_key: str | None = None,
        priority: bool = False,
    ) -> bool:
        """Queue a message. Returns False if it was dropped because the queue is full."""
        msg = OutMessage(truncate(text), reply_to, coalesce_key, priority)
        if coalesce_key is not None:
            for i, queued in enumerate(self._queue):
                if queued.coalesce_key == coalesce_key:
                    self._queue[i] = msg
                    return True
        if len(self._queue) >= self.max_queue:
            normal = [i for i, m in enumerate(self._queue) if not m.priority]
            if not priority or not normal:
                self._log.write("send_dropped", reason="queue_full", text=msg.text[:100])
                return False
            dropped = self._queue.pop(normal[-1])
            self._log.write("send_dropped", reason="queue_full", text=dropped.text[:100])
        if priority:
            position = sum(1 for m in self._queue if m.priority)
            self._queue.insert(position, msg)
        else:
            self._queue.append(msg)
        self._wake.set()
        return True

    def _refill(self) -> None:
        now = self._clock.mono()
        self._tokens = min(float(self.burst), self._tokens + (now - self._last_refill) * self.rate)
        self._last_refill = now

    async def flush_ready(self) -> int:
        """Send as many queued messages as the rate limit allows right now."""
        self._refill()
        sent = 0
        while self._queue and self._tokens >= 1:
            msg = self._queue.pop(0)
            self._tokens -= 1
            sent += 1
            try:
                result = await self._send(msg.text, msg.reply_to)
            except Exception as exc:  # network errors must not kill the send loop
                logger.exception("send failed")
                self._log.write("error", where="outbox.send", type=type(exc).__name__, message=str(exc))
                continue
            if not result.sent:
                self._log.write(
                    "send_dropped", reason=result.drop_code or "unknown", message=result.drop_message
                )
        return sent

    async def run(self, stop: asyncio.Event) -> None:
        """Background loop: send whenever there is something queued and a token available."""
        while not stop.is_set():
            await self.flush_ready()
            self._wake.clear()
            delay = 0.25 if self._queue else 1.0
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def drain(self, timeout: float = 3.0) -> None:
        """Send what's left (still rate limited), giving up after `timeout` real seconds."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while self._queue and loop.time() < deadline:
            await self.flush_ready()
            if self._queue:
                await asyncio.sleep(0.05)
