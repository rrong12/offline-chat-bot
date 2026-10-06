"""Twitch connector: reads chat over EventSub WebSocket, sends through Helix with the app token."""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import socket
import tempfile
from collections.abc import Awaitable, Callable, Mapping
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
AUTH_PORT = 4343  # the Twitch app's OAuth redirect must be exactly http://localhost:4343/oauth/callback
# force_verify makes Twitch show which account is approving, so the wrong account can't slip through.
AUTH_URL = f"http://localhost:{AUTH_PORT}/oauth?scopes=" + "%20".join(BOT_SCOPES) + "&force_verify=true"
WATCHDOG_SECONDS = 30  # how often to check that the bot is still logged in and subscribed
NO_SUBSCRIPTION_GRACE = 240  # seconds without a chat subscription before giving up (systemd restarts us)
AUTH_FAILURE_STATUSES = {400, 401, 403}  # Twitch rejected the token itself; anything else may be transient
_CREDENTIALS_REJECTED = (
    "Twitch rejected the app login (HTTP {status}): check TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET in .env"
)


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
    """Return (access token, refresh token) for the bot from the token file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = data.get(bot_id) if isinstance(data, dict) else None
        if not entry:
            raise AuthRequired(f"no token for bot user {bot_id} in {path}")
        return entry["token"], entry["refresh"]
    except FileNotFoundError:
        raise AuthRequired(f"no token file at {path}") from None
    except json.JSONDecodeError:
        raise AuthRequired(f"token file {path} is corrupt") from None
    except (KeyError, TypeError):
        raise AuthRequired(f"token file {path} has no usable entry for bot user {bot_id}") from None


def write_token_file(path: Path, tokens: Mapping[str, Any]) -> None:
    """Atomically write tokens as JSON, readable only by this user (0600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tokens-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump({uid: dict(entry) for uid, entry in tokens.items()}, fp)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class _Client(twitchio.Client):
    def __init__(self, connector: TwitchConnector) -> None:
        cfg = connector.config
        super().__init__(
            client_id=cfg.client_id, client_secret=cfg.client_secret, bot_id=cfg.bot_id, fetch_client_user=False
        )
        self.connector = connector

    async def load_tokens(self, path: str | None = None) -> None:
        token, refresh = read_bot_token(self.connector.token_path, self.connector.config.bot_id)
        try:
            await self.add_token(token, refresh)
        except twitchio.InvalidTokenException as exc:
            if exc.status in AUTH_FAILURE_STATUSES:
                raise AuthRequired("the saved bot token is invalid and could not be refreshed") from exc
            # 5xx or 429 while validating: probably a Twitch hiccup, so crash and let systemd retry.
            raise RuntimeError(f"Twitch login check failed (HTTP {exc.status}); will retry") from exc

    async def save_tokens(self, path: str | None = None) -> None:
        self.connector.save_bot_token()  # never raises; TwitchIO's own save would be a no-op here

    async def setup_hook(self) -> None:
        await self.connector._setup(self)

    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        await self.connector._incoming(payload)

    async def event_token_refreshed(self, payload: Any) -> None:
        self.connector.save_bot_token()  # persist right away, so a hard kill doesn't lose the refresh

    async def event_stream_online(self, payload: Any) -> None:
        await self.connector._live_changed(True)

    async def event_stream_offline(self, payload: Any) -> None:
        await self.connector._live_changed(False)

    async def event_websocket_welcome(self, payload: Any) -> None:
        self.connector._welcomed()

    async def event_websocket_closed(self, payload: Any) -> None:
        if not self.connector._closing:
            self.connector.log.write("disconnected")

    async def event_subscription_revoked(self, payload: Any) -> None:
        reason = getattr(getattr(payload, "reason", None), "value", None) or "unknown"
        await self.connector._fail(AuthRequired(f"Twitch revoked the chat subscription ({reason})"))


class TwitchConnector:
    def __init__(self, config: Config, log: ActivityLog, clock: Clock) -> None:
        self.config = config
        self.log = log
        self.clock = clock
        self.token_path = config.data_dir / ".tio.tokens.json"
        self.channel_id = ""
        self.is_mod = False
        self._client: _Client | None = None
        self._on_message: OnMessage | None = None
        self._on_ready: OnReady | None = None
        self._fatal: BaseException | None = None
        self._closing = False
        self._welcomes = 0
        self._watchdog: asyncio.Task[None] | None = None
        self.on_live: Callable[[bool], Awaitable[None]] | None = None  # set by BotCore

    async def run(self, on_message: OnMessage, on_ready: OnReady) -> None:
        self._on_message, self._on_ready = on_message, on_ready
        self._client = _Client(self)
        try:
            async with self._client:
                await self._client.start(with_adapter=False)
        except twitchio.HTTPException as exc:
            if not self.channel_id and exc.status in AUTH_FAILURE_STATUSES:  # failed before setup finished
                raise ConfigError(_CREDENTIALS_REJECTED.format(status=exc.status)) from exc
            raise
        finally:
            if self._watchdog is not None:
                self._watchdog.cancel()
        if self._fatal is not None:
            raise self._fatal
        if not self._closing:  # nobody asked to stop: treat it as a crash so systemd restarts us
            raise RuntimeError("Twitch connection ended unexpectedly")

    async def _setup(self, client: _Client) -> None:
        users = await client.fetch_users(logins=[self.config.channel])
        if not users:
            raise ConfigError(f"Twitch channel {self.config.channel!r} not found")
        self.channel_id = str(users[0].id)
        self.is_mod = self.channel_id == self.config.bot_id
        if not self.is_mod:
            try:
                bot = client.create_partialuser(user_id=self.config.bot_id)
                async for ch in bot.fetch_moderated_channels(first=100, token_for=self.config.bot_id):
                    if str(ch.id) == self.channel_id:
                        self.is_mod = True
                        break
            except twitchio.HTTPException as exc:
                logger.warning("could not check moderator status: %s", exc)
        await client.subscribe_websocket(
            eventsub.ChatMessageSubscription(broadcaster_user_id=self.channel_id, user_id=self.config.bot_id),
            as_bot=True,
        )
        for live_sub in (
            eventsub.StreamOnlineSubscription(broadcaster_user_id=self.channel_id),
            eventsub.StreamOfflineSubscription(broadcaster_user_id=self.channel_id),
        ):
            try:  # instant live/offline notices; the core also checks every few minutes, so this is optional
                await client.subscribe_websocket(live_sub, as_bot=True)
            except twitchio.HTTPException as exc:
                logger.warning("could not subscribe to %s: %s", live_sub.type, exc)
        self._watchdog = asyncio.create_task(self._watch(client))
        assert self._on_ready is not None
        await self._on_ready(ReadyInfo(self.config.channel, self.channel_id, self.is_mod))

    async def _watch(self, client: _Client) -> None:
        """TwitchIO can lose the login or the chat subscription without ending; detect that and fail loudly."""
        loop = asyncio.get_running_loop()
        empty_since: float | None = None
        while not self._closing:
            await asyncio.sleep(WATCHDOG_SECONDS)
            if self.config.bot_id not in client.tokens:  # a runtime refresh failed and TwitchIO dropped it
                await self._fail(AuthRequired("the bot's Twitch login expired and could not be refreshed"))
                return
            if client.websocket_subscriptions():
                empty_since = None
            elif empty_since is None:
                empty_since = loop.time()
            elif loop.time() - empty_since >= NO_SUBSCRIPTION_GRACE:
                await self._fail(RuntimeError("lost the chat connection and could not get it back"))
                return

    def save_bot_token(self) -> None:
        """Write the bot's current (possibly refreshed) token to disk. Never raises."""
        client = self._client
        if client is None or self.config.bot_id not in client.tokens:
            return
        try:
            write_token_file(self.token_path, {self.config.bot_id: client.tokens[self.config.bot_id]})
        except OSError as exc:
            logger.exception("could not save the Twitch token")
            self.log.write("error", where="twitch.save_token", type=type(exc).__name__, message=str(exc))

    def _welcomed(self) -> None:
        self._welcomes += 1
        self.log.write("connected" if self._welcomes == 1 else "reconnected")

    async def _incoming(self, payload: twitchio.ChatMessage) -> None:
        if self._on_message is not None:
            await self._on_message(to_chat_message(payload, self.clock))

    async def _fail(self, exc: BaseException) -> None:
        self._fatal = exc
        await self.close()

    async def _live_changed(self, live: bool) -> None:
        if self.on_live is not None:
            await self.on_live(live)

    async def is_live(self) -> bool:
        assert self._client is not None
        async for _ in self._client.fetch_streams(user_ids=[self.channel_id], type="live", first=1):
            return True
        return False

    async def send(self, text: str, reply_to: str | None = None) -> SendResult:
        assert self._client is not None
        channel = self._client.create_partialuser(user_id=self.channel_id)
        # The app token gives a modded bot the Chat Bot badge; without mod status Twitch only accepts
        # the bot's own user token.
        token_for = None if self.is_mod else self.config.bot_id
        try:
            await channel.send_message(
                text, sender=self.config.bot_id, token_for=token_for, reply_to_message_id=reply_to
            )
        except twitchio.MessageRejectedError as exc:
            return SendResult(False, exc.code, exc.message)
        except twitchio.HTTPException as exc:
            if exc.status == 403 and self.is_mod:  # mod status was removed while running
                self.is_mod = False
                self.log.write("error", where="twitch.send", type="LostModStatus", message="sending as the bot now")
                if self._on_ready is not None:
                    await self._on_ready(ReadyInfo(self.config.channel, self.channel_id, False))
                return await self.send(text, reply_to)
            return SendResult(False, f"http_{exc.status}", str(exc))
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
        if self._watchdog is not None and self._watchdog is not asyncio.current_task():
            self._watchdog.cancel()
        if self._client is not None:
            await self._client.close()


def _check_port_free(port: int) -> None:
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
        except OSError:  # this address family isn't available here
            continue
        with sock:
            try:
                sock.bind((host, port))
            except OSError as exc:
                if family == socket.AF_INET6 and exc.errno == errno.EADDRNOTAVAIL:  # no IPv6 loopback here
                    continue
                raise ConfigError(f"port {port} is in use; close whatever is using it and run auth again") from None


async def authorize(config: Config) -> UserRef:
    """One-time login: serve http://localhost:4343, wait for the bot account to approve, save the token."""
    _check_port_free(AUTH_PORT)
    done: asyncio.Future[UserRef] = asyncio.get_running_loop().create_future()
    token_path = config.data_dir / ".tio.tokens.json"

    class AuthClient(twitchio.Client):
        async def event_oauth_authorized(self, payload: Any) -> None:
            try:
                valid = await self.add_token(payload.access_token, payload.refresh_token)
                write_token_file(token_path, {str(valid.user_id): self.tokens[str(valid.user_id)]})
            except Exception as exc:
                if not done.done():
                    done.set_exception(exc)
                return
            if not done.done():
                done.set_result(UserRef(str(valid.user_id), valid.login or "", valid.login or ""))

    client = AuthClient(client_id=config.client_id, client_secret=config.client_secret, fetch_client_user=False)
    async with client:
        try:
            await client.login(load_tokens=False, save_tokens=False)
        except twitchio.HTTPException as exc:
            if exc.status in AUTH_FAILURE_STATUSES:
                raise ConfigError(_CREDENTIALS_REJECTED.format(status=exc.status)) from exc
            raise
        await client.adapter.run()
        print(f"Open this URL in a browser where you're logged in as the BOT account:\n\n  {AUTH_URL}\n")
        user = await done
    return user
