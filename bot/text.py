"""Text helpers: answer normalization, truncation, usernames, durations."""

from __future__ import annotations

import re
import unicodedata

MAX_MESSAGE = 500

# Removed outright rather than turned into spaces, so a word stays one word:
# - format characters (category Cf): zero-width spaces and joiners, BOM, soft hyphen,
#   directional marks;
# - combining marks (Mn, Me): strikethrough and "fancy text" overlays, variation selectors;
# - the Unicode tag block U+E0000-E007F. Chatterino and 7TV append U+E0000 to repeated
#   messages, and it is unassigned (category Cn), so the category check alone misses it.
_DROP_CATEGORIES = frozenset({"Cf", "Mn", "Me"})
_TAG_BLOCK = range(0xE0000, 0xE0080)
_USERNAME = re.compile(r"^[A-Za-z0-9_]{3,25}$")


def strip_invisible(text: str) -> str:
    return "".join(
        ch for ch in text if unicodedata.category(ch) not in _DROP_CATEGORIES and ord(ch) not in _TAG_BLOCK
    )


def normalize(text: str) -> str:
    """Lowercase, drop invisible characters, turn punctuation into spaces, collapse spaces."""
    t = unicodedata.normalize("NFKC", text).lower()
    t = strip_invisible(t)
    t = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in t)
    return " ".join(t.split())


def truncate(text: str, limit: int = MAX_MESSAGE) -> str:
    """Cut to at most `limit` characters at a word boundary, ending with an ellipsis."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def clean_username(raw: str) -> str | None:
    """Strip a leading @ and return the lowercase login, or None if it isn't a valid name."""
    name = strip_invisible(raw).strip().lstrip("@")
    if not _USERNAME.fullmatch(name):
        return None
    return name.lower()


def format_duration(seconds: float) -> str:
    """3h 12m, 12m, or 45s."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"
