"""The boundary between the bot core and a chat platform (Twitch, or the console)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ChatMessage:
    id: str
    user_id: str
    login: str  # lowercase username
    display_name: str
    text: str
    is_broadcaster: bool
    is_moderator: bool
    source_channel_id: str | None  # set during shared chat
    received_at: datetime  # UTC


@dataclass(frozen=True)
class SendResult:
    sent: bool
    drop_code: str | None = None
    drop_message: str | None = None


@dataclass(frozen=True)
class UserRef:
    user_id: str
    login: str
    display_name: str


@dataclass(frozen=True)
class ReadyInfo:
    channel_login: str
    channel_id: str
    is_mod: bool


OnMessage = Callable[[ChatMessage], Awaitable[None]]
OnReady = Callable[[ReadyInfo], Awaitable[None]]  # once connected, and again if mod status is lost


class Connector(Protocol):
    channel_id: str

    async def run(self, on_message: OnMessage, on_ready: OnReady) -> None:
        """Connect and deliver messages until closed. Raises on fatal errors."""

    async def send(self, text: str, reply_to: str | None = None) -> SendResult: ...

    async def lookup_user(self, login: str) -> UserRef | None: ...

    async def close(self) -> None: ...


class AuthRequired(Exception):
    """The bot's Twitch login is missing or no longer valid; `python -m bot auth` must be re-run."""
