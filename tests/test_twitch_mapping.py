import json
from types import SimpleNamespace

import pytest

from bot.clock import FakeClock
from bot.connectors.base import AuthRequired
from bot.connectors.twitch import AUTH_URL, read_bot_token, to_chat_message


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
    path.write_text(json.dumps({"123": {"user_id": "123", "token": "t", "refresh": "r"}}))
    assert read_bot_token(path, "123") == ("t", "r")


def test_auth_url_requests_all_bot_scopes():
    assert AUTH_URL == (
        "http://localhost:4343/oauth?scopes=user:read:chat%20user:write:chat%20user:bot%20user:read:moderated_channels"
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
