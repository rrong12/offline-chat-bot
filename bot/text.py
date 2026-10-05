"""Text helpers: answer normalization and matching, truncation, usernames, durations, numbers."""

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


_LEADING_ARTICLE = re.compile(r"(?i)^\s*(?:a|an|the)\s+(?=\S)")
_ROMAN = re.compile(r"[ivxlcdm]+")
_DIGITS = re.compile(r"\d+")


def strip_article(text: str) -> str:
    """'The Eiffel Tower' -> 'Eiffel Tower'. Use on raw text, before normalize: only a whole leading
    word followed by real whitespace counts, so "A-ha" and "A$AP" keep their "A"."""
    return _LEADING_ARTICLE.sub("", text, count=1)


def fold_accents(text: str) -> str:
    """'pokémon' -> 'pokemon', so a missing accent never costs a player their one typo."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def within_one_edit(a: str, b: str) -> bool:
    """True if a and b differ by at most one insertion, deletion, substitution, or swap of neighbours."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(short) and short[i] == long[i]:
        i += 1
    return short[i:] == long[i + 1:]


def typo_match(guess: str, answer: str, min_letters: int = 5) -> bool:
    """Do two normalized answers match? Equal ignoring spaces, or off by one typo in a word of
    `min_letters`+ letters that keeps its first letter (so Mario isn't Wario). Numbers must be the same
    groups of digits ("1 38" isn't "13 8", "Apollo 13" isn't 11), and short words ("A minor") and Roman
    numerals ("Louis XIV") must match exactly: there one character is the whole answer."""
    if _DIGITS.findall(guess) != _DIGITS.findall(answer):
        return False
    if guess.replace(" ", "") == answer.replace(" ", ""):
        return True
    guess_words, answer_words = guess.split(), answer.split()
    if len(guess_words) == len(answer_words):
        typos = 0
        for g, a in zip(guess_words, answer_words, strict=True):
            if g == a:
                continue
            if not _typo_ok(g, a, min_letters):
                return False
            typos += 1
        return typos <= 1
    # split differently ("shaquile oneal" for "shaquille o neal"): one typo over the whole answer
    joined_guess, joined_answer = guess.replace(" ", ""), answer.replace(" ", "")
    if any(_ROMAN.fullmatch(a) and len(a) > 1 for a in answer_words) or len(joined_answer) < 2 * min_letters:
        return False
    return _typo_ok(joined_guess, joined_answer, min_letters)


def _typo_ok(guess: str, answer: str, min_letters: int) -> bool:
    return (
        answer.isalpha()
        and len(answer) >= min_letters
        and not _ROMAN.fullmatch(answer)
        and guess[:1] == answer[:1]
        and within_one_edit(guess, answer)
    )


def short_number(n: int) -> str:
    """950, 1.2K, 55K, 241K, 1.2M, 12M: at most three significant digits, rounded half up."""
    if n < 0:
        raise ValueError(f"short_number needs a count, got {n}")
    if n < 1000:
        return str(n)
    for divisor, suffix in ((1_000, "K"), (1_000_000, "M"), (1_000_000_000, "B")):
        tenths = (n * 10 + divisor // 2) // divisor  # integer maths: no float rounding surprises
        if tenths < 100:
            return f"{tenths // 10}.{tenths % 10}".removesuffix(".0") + suffix
        whole = (n + divisor // 2) // divisor
        if whole < 1000 or suffix == "B":
            return f"{whole}{suffix}"
    raise AssertionError("unreachable")
