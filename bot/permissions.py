"""Who may use control commands: the broadcaster, any moderator, or a listed owner."""

from __future__ import annotations

from collections.abc import Collection

from bot.connectors.base import ChatMessage


def is_controller(msg: ChatMessage, owner_ids: Collection[str]) -> bool:
    return msg.is_broadcaster or msg.is_moderator or msg.user_id in owner_ids
