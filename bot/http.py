"""A small shared HTTP client for the fact and joke APIs. Never raises: failures return None."""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from bot import __version__

logger = logging.getLogger(__name__)

USER_AGENT = f"offline-chat-bot/{__version__} (Twitch chat bot)"
MAX_BODY = 64_000  # bytes; fact and joke responses are tiny


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
                body = bytearray()
                async for chunk in resp.content.iter_chunked(16_384):  # read() alone may return a partial body
                    body += chunk
                    if len(body) > MAX_BODY:
                        logger.warning("GET %s: body over %d bytes", url, MAX_BODY)
                        return None
                return json.loads(body)
        except Exception as exc:  # timeouts, DNS, bad JSON: all fall back
            logger.warning("GET %s failed: %s", url, type(exc).__name__)
            return None

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
