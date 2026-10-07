import asyncio
import json
import os
import socket
from types import SimpleNamespace

import pytest
import twitchio

import bot.connectors.twitch as twitch
from bot.activity_log import ActivityLog
from bot.clock import FakeClock
from bot.config import ConfigError
from bot.connectors.base import AuthRequired
from bot.connectors.twitch import AUTH_URL, read_bot_token, to_chat_message
from tests.helpers import make_config


def fake_payload(source=None, text="?scramble", reply=None, **chatter):
    defaults = dict(id="42", name="Alice", display_name="Alice", broadcaster=False, moderator=False)
    defaults.update(chatter)
    return SimpleNamespace(
        id="m1", text=text, chatter=SimpleNamespace(**defaults), source_broadcaster=source, reply=reply
    )


def reply_to(login: str):
    return SimpleNamespace(parent_user=SimpleNamespace(name=login))


def test_to_chat_message_maps_fields(clock: FakeClock):
    msg = to_chat_message(fake_payload(moderator=True), clock)
    assert (msg.id, msg.user_id, msg.login, msg.display_name, msg.text) == ("m1", "42", "alice", "Alice", "?scramble")
    assert msg.is_moderator and not msg.is_broadcaster
    assert msg.source_channel_id is None
    assert msg.received_at == clock.now()


def test_to_chat_message_shared_chat_source(clock: FakeClock):
    msg = to_chat_message(fake_payload(source=SimpleNamespace(id=999)), clock)
    assert msg.source_channel_id == "999"


def test_reply_mention_is_stripped(clock: FakeClock):
    msg = to_chat_message(fake_payload(text="@OfflineBot alligator", reply=reply_to("offlinebot")), clock)
    assert msg.text == "alligator"
    cmd = to_chat_message(fake_payload(text="@offlinebot ?g e", reply=reply_to("offlinebot")), clock)
    assert cmd.text == "?g e"


def test_mentions_are_kept_when_not_a_reply_or_not_the_parent(clock: FakeClock):
    assert to_chat_message(fake_payload(text="@offlinebot hi"), clock).text == "@offlinebot hi"
    other = to_chat_message(fake_payload(text="@someone hi", reply=reply_to("offlinebot")), clock)
    assert other.text == "@someone hi"
    bare = to_chat_message(fake_payload(text="@offlinebot", reply=reply_to("offlinebot")), clock)
    assert bare.text == "@offlinebot"


def test_read_bot_token(tmp_path):
    path = tmp_path / ".tio.tokens.json"
    with pytest.raises(AuthRequired, match="no token file"):
        read_bot_token(path, "123")
    path.write_text("{not json")
    with pytest.raises(AuthRequired, match="corrupt"):
        read_bot_token(path, "123")
    path.write_text(json.dumps({"999": {"token": "t", "refresh": "r"}}))
    with pytest.raises(AuthRequired, match="no token for bot user 123"):
        read_bot_token(path, "123")
    path.write_text(json.dumps({"123": {"user_id": "123", "token": "t"}}))  # no refresh token
    with pytest.raises(AuthRequired, match="no usable entry"):
        read_bot_token(path, "123")
    path.write_text(json.dumps(["not", "an", "object"]))
    with pytest.raises(AuthRequired, match="no token for bot user 123"):
        read_bot_token(path, "123")
    path.write_text(json.dumps({"123": {"user_id": "123", "token": "t", "refresh": "r"}}))
    assert read_bot_token(path, "123") == ("t", "r")


def test_auth_url_requests_all_bot_scopes_and_forces_account_check():
    assert AUTH_URL == (
        "http://localhost:4343/oauth?scopes=user:read:chat%20user:write:chat%20user:bot%20user:read:moderated_channels"
        "&force_verify=true"
    )


async def test_unexpected_end_of_connection_is_an_error(tmp_path, clock: FakeClock, monkeypatch):
    import bot.connectors.twitch as twitch
    from bot.activity_log import ActivityLog
    from tests.helpers import make_config

    class EndsAtOnce:
        def __init__(self, connector):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def start(self, with_adapter=False):
            return None  # returned without anyone calling close()

    monkeypatch.setattr(twitch, "_Client", EndsAtOnce)
    connector = twitch.TwitchConnector(make_config(tmp_path), ActivityLog(tmp_path, clock), clock)

    async def noop(*args):
        pass

    with pytest.raises(RuntimeError, match="ended unexpectedly"):
        await connector.run(noop, noop)


# ---- connector behavior with fake TwitchIO pieces (no network) ----


class FakeClient:
    def __init__(self, tokens=None, subscriptions=None, on_twitch=("channel.chat.message",)):
        self.tokens = tokens if tokens is not None else {}
        self.subscriptions = subscriptions if subscriptions is not None else {}
        self.on_twitch = on_twitch  # enabled subscription types Twitch reports; an exception = unreachable
        self.closed = False
        self.sent = []

    async def fetch_eventsub_subscriptions(self, *, token_for, status):
        assert status == "enabled"
        if isinstance(self.on_twitch, Exception):
            raise self.on_twitch
        types = self.on_twitch

        class Sub:
            def __init__(self, type_):
                self.type = type_

        async def gen():
            for t in types:
                yield Sub(t)

        class Result:
            subscriptions = gen()

        return Result()

    def websocket_subscriptions(self):
        return self.subscriptions

    async def close(self):
        self.closed = True

    def create_partialuser(self, user_id):
        client = self

        class Channel:
            async def send_message(self, text, sender, token_for=None, reply_to_message_id=None):
                client.sent.append((text, token_for))

        return Channel()


def connector_for(tmp_path, clock, client=None):
    cfg = make_config(tmp_path, bot_id="123")
    conn = twitch.TwitchConnector(cfg, ActivityLog(tmp_path / "logs", clock), clock)
    conn._client = client
    return conn


def test_save_bot_token_writes_the_current_token_atomically_and_privately(tmp_path, clock):
    client = FakeClient(tokens={"123": {"user_id": "123", "token": "NEW", "refresh": "R2"}})
    conn = connector_for(tmp_path, clock, client)
    conn.token_path.parent.mkdir(parents=True)
    conn.token_path.write_text(json.dumps({"123": {"user_id": "123", "token": "OLD", "refresh": "R1"}}))
    conn.save_bot_token()
    assert json.loads(conn.token_path.read_text())["123"]["token"] == "NEW"
    assert oct(os.stat(conn.token_path).st_mode & 0o777) == "0o600"
    assert not list(conn.token_path.parent.glob(".tokens-*"))  # no temp files left behind


def test_save_bot_token_never_raises_and_skips_without_a_token(tmp_path, clock):
    conn = connector_for(tmp_path, clock, FakeClient(tokens={}))
    conn.save_bot_token()
    assert not conn.token_path.exists()
    conn = connector_for(tmp_path, clock, FakeClient(tokens={"123": {"token": "t", "refresh": "r"}}))
    conn.token_path = tmp_path / "missing-dir" / "file" / "x"
    conn.token_path.parent.parent.write_text("a file where a folder should be")
    conn.save_bot_token()  # OSError is logged, not raised


def invalid_token(status):
    exc = twitchio.InvalidTokenException.__new__(twitchio.InvalidTokenException)
    exc.status = status
    return exc


async def test_startup_login_check_tells_outages_from_bad_tokens(tmp_path, clock, monkeypatch):
    conn = connector_for(tmp_path, clock)
    conn.token_path.parent.mkdir(parents=True)
    conn.token_path.write_text(json.dumps({"123": {"user_id": "123", "token": "t", "refresh": "r"}}))
    client = twitch._Client(conn)

    for status, expected in ((401, AuthRequired), (400, AuthRequired), (500, RuntimeError), (429, RuntimeError)):
        async def failing(token, refresh, status=status):
            raise invalid_token(status)

        monkeypatch.setattr(client, "add_token", failing)
        with pytest.raises(expected) as info:
            await client.load_tokens()
        assert type(info.value) is expected


async def test_watchdog_fails_when_the_login_is_dropped(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(twitch, "WATCHDOG_SECONDS", 0.01)
    client = FakeClient(tokens={}, subscriptions={"s": object()})
    conn = connector_for(tmp_path, clock, client)
    await asyncio.wait_for(conn._watch(client), timeout=2)
    assert isinstance(conn._fatal, AuthRequired) and client.closed


async def test_watchdog_fails_after_losing_the_subscription_for_too_long(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(twitch, "WATCHDOG_SECONDS", 0.01)
    monkeypatch.setattr(twitch, "NO_SUBSCRIPTION_GRACE", 0.05)
    client = FakeClient(tokens={"123": {}}, subscriptions={})
    conn = connector_for(tmp_path, clock, client)
    await asyncio.wait_for(conn._watch(client), timeout=2)
    assert isinstance(conn._fatal, RuntimeError) and "chat connection" in str(conn._fatal)


async def test_send_uses_app_token_when_modded_and_bot_token_otherwise(tmp_path, clock):
    client = FakeClient()
    conn = connector_for(tmp_path, clock, client)
    conn.channel_id = "999"
    conn.is_mod = True
    await conn.send("hi")
    conn.is_mod = False
    await conn.send("hi")
    assert client.sent == [("hi", None), ("hi", "123")]


async def test_send_falls_back_to_bot_token_when_mod_status_is_lost(tmp_path, clock):
    class ForbiddenForAppToken(FakeClient):
        def create_partialuser(self, user_id):
            client = self

            class Channel:
                async def send_message(self, text, sender, token_for=None, reply_to_message_id=None):
                    if token_for is None:
                        exc = twitchio.HTTPException.__new__(twitchio.HTTPException)
                        exc.status = 403
                        raise exc
                    client.sent.append((text, token_for))

            return Channel()

    client = ForbiddenForAppToken()
    conn = connector_for(tmp_path, clock, client)
    conn.channel_id, conn.is_mod = "999", True
    ready = []

    async def on_ready(info):
        ready.append(info)

    conn._on_ready = on_ready
    result = await conn.send("hi")
    assert result.sent and not conn.is_mod and client.sent == [("hi", "123")]
    assert [r.is_mod for r in ready] == [False]  # the core slows sending down


async def test_send_maps_http_errors_to_a_drop(tmp_path, clock):
    class Forbidden(FakeClient):
        def create_partialuser(self, user_id):
            class Channel:
                async def send_message(self, *args, **kwargs):
                    exc = twitchio.HTTPException.__new__(twitchio.HTTPException)
                    exc.status = 403
                    raise exc

            return Channel()

    conn = connector_for(tmp_path, clock, Forbidden())
    result = await conn.send("hi")
    assert (result.sent, result.drop_code) == (False, "http_403")


def test_auth_accepts_a_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    twitch._check_port_free(port)  # free again after the with-block: must not raise


def test_auth_refuses_a_busy_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("localhost", 0))
        sock.listen()
        port = sock.getsockname()[1]
        with pytest.raises(ConfigError, match="in use"):
            twitch._check_port_free(port)


async def test_disconnect_is_not_logged_during_a_deliberate_close(tmp_path, clock):
    conn = connector_for(tmp_path, clock, FakeClient())
    client = twitch._Client(conn)
    conn._closing = True
    await client.event_websocket_closed(None)
    assert not list((tmp_path / "logs").glob("*.jsonl"))


async def test_rejected_app_credentials_are_a_setup_error(tmp_path, clock, monkeypatch):
    class RejectsLogin:
        def __init__(self, connector):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def start(self, with_adapter=False):
            exc = twitchio.HTTPException.__new__(twitchio.HTTPException)
            exc.status = 403
            raise exc

    monkeypatch.setattr(twitch, "_Client", RejectsLogin)
    conn = twitch.TwitchConnector(make_config(tmp_path), ActivityLog(tmp_path, clock), clock)

    async def noop(*args):
        pass

    with pytest.raises(ConfigError, match="TWITCH_CLIENT_SECRET"):
        await conn.run(noop, noop)


async def test_stream_events_and_live_check(tmp_path, clock):
    class Streams(FakeClient):
        live = True

        def fetch_streams(self, *, user_ids, type, first):
            assert user_ids == ["999"] and type == "live"
            streams = [object()] if self.live else []

            async def gen():
                for s in streams:
                    yield s

            return gen()

    client = Streams()
    conn = connector_for(tmp_path, clock, client)
    conn.channel_id = "999"
    assert await conn.is_live() is True
    client.live = False
    assert await conn.is_live() is False
    changes = []

    async def on_live(live):
        changes.append(live)

    conn.on_live = on_live
    twitch_client = twitch._Client.__new__(twitch._Client)
    twitch_client.connector = conn
    await twitch_client.event_stream_online(None)
    await twitch_client.event_stream_offline(None)
    assert changes == [True, False]


async def test_watchdog_trusts_twitch_over_the_local_subscription_list(tmp_path, clock, monkeypatch):
    # After a laptop sleep, TwitchIO can still list a subscription that Twitch has dropped: the bot is deaf.
    monkeypatch.setattr(twitch, "WATCHDOG_SECONDS", 0.01)
    monkeypatch.setattr(twitch, "NO_SUBSCRIPTION_GRACE", 0.05)
    client = FakeClient(tokens={"123": {}}, subscriptions={"s": object()}, on_twitch=())
    conn = connector_for(tmp_path, clock, client)
    await asyncio.wait_for(conn._watch(client), timeout=2)
    assert isinstance(conn._fatal, RuntimeError) and "chat connection" in str(conn._fatal)


async def test_watchdog_waits_while_twitch_cannot_be_reached(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(twitch, "WATCHDOG_SECONDS", 0.01)
    monkeypatch.setattr(twitch, "NO_SUBSCRIPTION_GRACE", 0.05)
    client = FakeClient(tokens={"123": {}}, subscriptions={"s": object()}, on_twitch=OSError("offline"))
    conn = connector_for(tmp_path, clock, client)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(conn._watch(client), timeout=0.3)  # no restart loop while offline
    assert conn._fatal is None


async def test_watchdog_is_quiet_while_the_chat_subscription_is_enabled(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(twitch, "WATCHDOG_SECONDS", 0.01)
    monkeypatch.setattr(twitch, "NO_SUBSCRIPTION_GRACE", 0.05)
    client = FakeClient(tokens={"123": {}}, subscriptions={"s": object()})
    conn = connector_for(tmp_path, clock, client)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(conn._watch(client), timeout=0.3)
    assert conn._fatal is None
