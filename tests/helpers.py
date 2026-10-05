from datetime import datetime, timezone
from itertools import count

from bot.connectors.base import ChatMessage

_ids = count(1)


def make_msg(
    text: str,
    login: str = "alice",
    *,
    user_id: str | None = None,
    mod: bool = False,
    broadcaster: bool = False,
    source_channel_id: str | None = None,
    at: datetime | None = None,
) -> ChatMessage:
    return ChatMessage(
        id=f"msg-{next(_ids)}",
        user_id=user_id or f"id-{login}",
        login=login.lower(),
        display_name=login,
        text=text,
        is_broadcaster=broadcaster,
        is_moderator=mod,
        source_channel_id=source_channel_id,
        received_at=at or datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc),
    )


class FakeHttp:
    def __init__(self, responses: dict[str, object] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict | None]] = []

    async def get_json(self, url, headers=None):
        self.calls.append((url, headers))
        return self.responses.get(url)

    async def close(self):
        pass
