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
        send_timeout: float = 10.0,
    ) -> None:
        self._send = send
        self._clock = clock
        self._log = log
        self.rate = rate
        self.burst = burst
        self.max_queue = max_queue
        self.send_timeout = send_timeout
        self._queue: list[OutMessage] = []
        self._tokens = float(burst)
        self._last_refill = clock.mono()
        self._wake = asyncio.Event()
        self._flush_lock = asyncio.Lock()  # run() and drain() must never send concurrently
        self._closed = False

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
        """Queue a message. Returns False if it was dropped (queue full, or the bot is shutting down)."""
        msg = OutMessage(truncate(text), reply_to, coalesce_key, priority)
        if self._closed:
            self._log.write("send_dropped", reason="shutdown", text=msg.text[:100])
            return False
        if coalesce_key is not None:
            for i, queued in enumerate(self._queue):
                if queued.coalesce_key == coalesce_key:
                    if queued.priority == priority:
                        self._queue[i] = msg  # same lane: replace in place
                        return True
                    del self._queue[i]  # changing lanes: re-insert below to keep priority order
                    break
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
        async with self._flush_lock:
            self._refill()
            sent = 0
            while self._queue and self._tokens >= 1:
                msg = self._queue.pop(0)
                self._tokens -= 1
                sent += 1
                await self._send_one(msg)
            return sent

    async def _send_one(self, msg: OutMessage) -> None:
        """Send one message. Logs failures and drops; never raises (except cancellation)."""
        try:
            result = await asyncio.wait_for(self._send(msg.text, msg.reply_to), self.send_timeout)
            if not result.sent:
                self._log.write(
                    "send_dropped",
                    reason=result.drop_code or "unknown",
                    message=result.drop_message,
                    text=msg.text[:100],
                )
        except Exception as exc:  # timeouts and network errors must not kill the send loop
            logger.exception("send failed")
            self._log.write(
                "error", where="outbox.send", type=type(exc).__name__, message=str(exc), text=msg.text[:100]
            )

    def _next_delay(self) -> float:
        """How long the loop should wait: until the next token if messages are queued, else idle."""
        if not self._queue:
            return 1.0
        self._refill()
        return max(0.0, (1 - self._tokens) / self.rate)

    async def run(self, stop: asyncio.Event) -> None:
        """Background loop: send whenever there is something queued and a token available."""
        while not stop.is_set():
            try:
                await self.flush_ready()
                self._wake.clear()
                waiters = [asyncio.ensure_future(stop.wait()), asyncio.ensure_future(self._wake.wait())]
                try:
                    await asyncio.wait(waiters, timeout=self._next_delay(), return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for waiter in waiters:
                        waiter.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never let the loop die silently
                logger.exception("outbox loop error")
                self._log.write("error", where="outbox.run", type=type(exc).__name__, message=str(exc))
                await asyncio.sleep(1)

    def close(self) -> None:
        """Refuse new messages from now on (each one is logged as dropped)."""
        self._closed = True

    def discard(self, reason: str) -> int:
        """Drop everything queued, logging how many. Returns the count."""
        count = len(self._queue)
        if count:
            self._log.write("send_dropped", reason=reason, count=count)
            self._queue.clear()
        return count

    async def drain(self, timeout: float = 3.0) -> None:
        """Send what's left (still rate limited), giving up after `timeout` real seconds."""
        try:
            async with asyncio.timeout(timeout):
                while self._queue:
                    await self.flush_ready()
                    if self._queue:
                        await asyncio.sleep(self._next_delay() or 0.01)
        except TimeoutError:
            pass
        self.discard("shutdown")
