"""Twitch connector: reads chat over EventSub WebSocket, sends through Helix with the app token."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import twitchio
from twitchio import eventsub

from bot.activity_log import ActivityLog
from bot.clock import Clock
from bot.config import Config, ConfigError
from bot.connectors.base import AuthRequired, ChatMessage, OnMessage, OnReady, ReadyInfo, SendResult, UserRef

logger = logging.getLogger(__name__)

BOT_SCOPES = ("user:read:chat", "user:write:chat", "user:bot", "user:read:moderated_channels")
REDIRECT_URI = "http://localhost:4343/oauth/callback"  # register this exact URL on the Twitch app
AUTH_URL = "http://localhost:4343/oauth?scopes=" + "%20".join(BOT_SCOPES)


def strip_reply_mention(text: str, reply: Any) -> str:
    """Drop the leading "@name " Twitch clients put on a reply, so "@bot alligator" reads "alligator"."""
    parent = getattr(getattr(reply, "parent_user", None), "name", None) if reply is not None else None
    if not parent:
        return text
    head, _, rest = text.partition(" ")
    if head.lower() == f"@{parent.lower()}" and rest:
        return rest.lstrip()
    return text


def to_chat_message(payload: Any, clock: Clock) -> ChatMessage:
    """Map a twitchio.ChatMessage to our platform-neutral ChatMessage."""
    chatter = payload.chatter
    source = payload.source_broadcaster
    return ChatMessage(
        id=payload.id,
        user_id=str(chatter.id),
        login=(chatter.name or "").lower(),
        display_name=chatter.display_name or chatter.name or "",
        text=strip_reply_mention(payload.text, getattr(payload, "reply", None)),
        is_broadcaster=bool(chatter.broadcaster),
        is_moderator=bool(chatter.moderator),
        source_channel_id=str(source.id) if source is not None else None,
        received_at=clock.now(),
    )


def read_bot_token(path: Path, bot_id: str) -> tuple[str, str]:
    """Return (access token, refresh token) for the bot from TwitchIO's token file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AuthRequired(f"no token file at {path}") from None
    except json.JSONDecodeError:
        raise AuthRequired(f"token file {path} is corrupt") from None
    entry = data.get(bot_id)
    if not entry:
        raise AuthRequired(f"no token for bot user {bot_id} in {path}")
    return entry["token"], entry["refresh"]


class _Client(twitchio.Client):
    def __init__(self, connector: TwitchConnector) -> None:
        cfg = connector.config
        super().__init__(client_id=cfg.client_id, client_secret=cfg.client_secret, bot_id=cfg.bot_id)
        self.connector = connector
        self._tokens_loaded = False

    async def load_tokens(self, path: str | None = None) -> None:
        token, refresh = read_bot_token(self.connector.token_path, self.connector.config.bot_id)
        try:
            await self.add_token(token, refresh)
        except twitchio.InvalidTokenException as exc:
            raise AuthRequired("the saved bot token is invalid and could not be refreshed") from exc
        self._tokens_loaded = True

    async def save_tokens(self, path: str | None = None) -> None:
        # TwitchIO saves on close. If startup failed before the token loaded, saving would
        # overwrite the token file with nothing and force a needless re-login.
        if self._tokens_loaded:
            await super().save_tokens(str(self.connector.token_path))

    async def setup_hook(self) -> None:
        await self.connector._setup(self)

    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        await self.connector._incoming(payload)

    async def event_websocket_welcome(self, payload: Any) -> None:
        self.connector._welcomed()

    async def event_websocket_closed(self, payload: Any) -> None:
        self.connector.log.write("disconnected")

    async def event_subscription_revoked(self, payload: Any) -> None:
        await self.connector._fail(AuthRequired(f"chat subscription revoked: {getattr(payload, 'reason', '?')}"))


class TwitchConnector:
    def __init__(self, config: Config, log: ActivityLog, clock: Clock) -> None:
        self.config = config
        self.log = log
        self.clock = clock
        self.token_path = config.data_dir / ".tio.tokens.json"
        self.channel_id = ""
        self._client: _Client | None = None
        self._on_message: OnMessage | None = None
        self._on_ready: OnReady | None = None
        self._fatal: BaseException | None = None
        self._closing = False
        self._welcomes = 0

    async def run(self, on_message: OnMessage, on_ready: OnReady) -> None:
        self._on_message, self._on_ready = on_message, on_ready
        self._client = _Client(self)
        async with self._client:
            await self._client.start(with_adapter=False)
        if self._fatal is not None:
            raise self._fatal
        if not self._closing:  # nobody asked to stop: treat it as a crash so systemd restarts us
            raise RuntimeError("Twitch connection ended unexpectedly")

    async def _setup(self, client: _Client) -> None:
        users = await client.fetch_users(logins=[self.config.channel])
        if not users:
            raise ConfigError(f"Twitch channel {self.config.channel!r} not found")
        channel = users[0]
        self.channel_id = str(channel.id)
        is_mod = self.channel_id == self.config.bot_id
        if not is_mod:
            try:
                bot = client.create_partialuser(user_id=self.config.bot_id)
                async for ch in bot.fetch_moderated_channels(first=100, token_for=self.config.bot_id):
                    if str(ch.id) == self.channel_id:
                        is_mod = True
                        break
            except twitchio.HTTPException as exc:
                logger.warning("could not check moderator status: %s", exc)
        await client.subscribe_websocket(
            eventsub.ChatMessageSubscription(broadcaster_user_id=self.channel_id, user_id=self.config.bot_id),
            as_bot=True,
        )
        assert self._on_ready is not None
        await self._on_ready(ReadyInfo(self.config.channel, self.channel_id, is_mod))

    def _welcomed(self) -> None:
        self._welcomes += 1
        self.log.write("connected" if self._welcomes == 1 else "reconnected")

    async def _incoming(self, payload: twitchio.ChatMessage) -> None:
        if self._on_message is not None:
            await self._on_message(to_chat_message(payload, self.clock))

    async def _fail(self, exc: BaseException) -> None:
        self._fatal = exc
        await self.close()

    async def send(self, text: str, reply_to: str | None = None) -> SendResult:
        assert self._client is not None
        channel = self._client.create_partialuser(user_id=self.channel_id)
        try:
            await channel.send_message(
                text, sender=self.config.bot_id, token_for=None, reply_to_message_id=reply_to
            )
        except twitchio.MessageRejectedError as exc:
            return SendResult(False, exc.code, exc.message)
        return SendResult(True)

    async def lookup_user(self, login: str) -> UserRef | None:
        assert self._client is not None
        try:
            users = await self._client.fetch_users(logins=[login])
        except twitchio.HTTPException:
            return None
        if not users:
            return None
        user = users[0]
        return UserRef(str(user.id), user.name or login, user.display_name or user.name or login)

    async def close(self) -> None:
        self._closing = True
        if self._client is not None:
            await self._client.close()


async def authorize(config: Config) -> UserRef:
    """One-time login: serve http://localhost:4343, wait for the bot account to approve, save the token."""
    import asyncio

    done: asyncio.Future[UserRef] = asyncio.get_running_loop().create_future()
    token_path = config.data_dir / ".tio.tokens.json"
    token_path.parent.mkdir(parents=True, exist_ok=True)

    class AuthClient(twitchio.Client):
        async def event_oauth_authorized(self, payload: Any) -> None:
            valid = await self.add_token(payload.access_token, payload.refresh_token)
            await self.save_tokens(str(token_path))
            if not done.done():
                done.set_result(UserRef(str(valid.user_id), valid.login or "", valid.login or ""))

    client = AuthClient(client_id=config.client_id, client_secret=config.client_secret)
    async with client:
        await client.login(load_tokens=False, save_tokens=False)
        await client.adapter.run()
        print(f"Open this URL in a browser where you're logged in as the BOT account:\n\n  {AUTH_URL}\n")
        user = await done
    return user
