"""A small shared HTTP client for the fact and joke APIs. Never raises: failures return None."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

USER_AGENT = "offline-chat-bot/0.1 (Twitch chat bot)"


class HttpClient:
    def __init__(self, timeout: float = 3.0) -> None:
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    async def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any | None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout), headers={"User-Agent": USER_AGENT}
            )
        try:
            async with self._session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning("GET %s -> HTTP %s", url, resp.status)
                    return None
                return await resp.json(content_type=None)
        except Exception as exc:  # timeouts, DNS, bad JSON: all fall back
            logger.warning("GET %s failed: %s", url, type(exc).__name__)
            return None

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
