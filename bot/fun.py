"""Quick one-shot commands: ?8ball ?coinflip ?catfact ?dogfact ?fact ?dadjoke ?cookie."""

from __future__ import annotations

import asyncio
import codecs
import json
import random
import re
import unicodedata
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta, timezone
from typing import Any

from bot.assets import Assets
from bot.clock import Clock
from bot.commands import Command, CommandContext, CommandRegistry
from bot.connectors.base import UserRef
from bot.http import HttpClient
from bot.stats import StatsStore
from bot.text import clean_username, format_duration, strip_invisible

MAX_FACT = 400
LOOKUP_TIMEOUT = 5.0  # seconds to wait for Twitch to confirm a user exists
# Third-party text must not carry links or @mentions into Jason's chat (the bot, as a mod,
# bypasses Twitch's link filter). Every reply also starts with an emoji, so it can never begin
# with "/" or "." and be read as a chat command; keep that prefix.
_UNSAFE = re.compile(r"://|www\.|@\w", re.IGNORECASE)

LookupUser = Callable[[str], Awaitable[UserRef | None]]


def _get(data: Any, *path: str | int) -> Any:
    for key in path:
        data = data[key]
    return data


# Innocent words that look like blocked ones, checked as prefixes of each word.
_INNOCENT = (
    "analects", "analges", "analog", "analy", "booby", "boobies", "cockat", "cocker", "cockfight", "cockle",
    "cockney", "cockp", "cockr", "cockscomb", "cockt", "cocky", "cummings", "dicken", "dickey", "dickinson", "milford",
    "negroni", "penistone", "pissarro", "pussyc", "pussyf", "pussyw", "rapese", "retardant", "scunthorpe",
    "shitzu", "titter", "tittle", "wankel",
)
_ES_PLURALS = ("ses", "xes", "zes", "ches", "shes")  # "-es" plurals ("spices" is not one)
_HOMO_SPECIES = {"antecessor", "erectus", "ergaster", "floresiensis", "habilis", "heidelbergensis", "naledi",
                 "neanderthalensis", "sapiens"}


class BlockedWords:
    """Finds blocked words in prose, by the patterns in content/blocked_prose_rot13.txt:
    "word" is the whole word or its plural, "word*" a word start, "*word*" anywhere in a word."""

    def __init__(self, patterns: list[str]) -> None:
        self.whole = {p for p in patterns if "*" not in p}
        self.prefix = tuple(p[:-1] for p in patterns if p.endswith("*") and not p.startswith("*"))
        self.inside = tuple(p[1:-1] for p in patterns if p.startswith("*") and p.endswith("*"))

    @classmethod
    def load(cls, assets: Assets) -> BlockedWords:
        try:
            return cls([codecs.decode(line, "rot13") for line in assets.lines("blocked_prose_rot13")])
        except FileNotFoundError:
            return cls([])

    def found_in(self, text: str) -> bool:
        words = re.findall(r"[a-z]+", text.lower())
        for i, word in enumerate(words):
            if word.startswith(_INNOCENT):
                continue
            stems = (word, word[:-1] if word.endswith("s") else "", word[:-2] if word.endswith(_ES_PLURALS) else "")
            if any(stem in self.whole for stem in stems) and not _fine_in_context(words, i):
                return True
            if word.startswith(self.prefix) or any(part in word for part in self.inside):
                return True
        return False


def _fine_in_context(words: list[str], i: int) -> bool:
    """A few blocked whole words are fine next to a specific word: "Homo sapiens", "Maine Coon"."""
    if words[i] in ("homo", "homos"):
        return i + 1 < len(words) and words[i + 1] in _HOMO_SPECIES
    if words[i] in ("coon", "coons"):
        return i > 0 and words[i - 1] in ("maine", "main")  # the breed, often misspelled
    return False


def _safe_text(value: Any, blocked: BlockedWords | None = None) -> str | None:
    """API text cleaned for chat, or None if it's unusable: missing, too long, cut off at the start,
    or carrying links, @mentions or blocked words (the bot is a mod, so Twitch won't filter it)."""
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFC", value)  # compose accents first so stripping marks keeps them
    text = " ".join(strip_invisible(text).split())  # all whitespace (incl. newlines) becomes one space
    text = "".join(ch for ch in text if ch.isprintable())  # then drop control characters
    if not text or len(text) > MAX_FACT or _UNSAFE.search(text):
        return None
    if text[0].islower():  # looks cut off mid-sentence
        return None
    if blocked is not None and blocked.found_in(text):
        return None
    return text


def _mention(display_name: str, login: str) -> str:
    """@display name if it's just a capitalised login, else @login (localised names don't ping)."""
    return f"@{display_name}" if display_name.lower() == login.lower() else f"@{login}"


# command name -> (emoji, url, path to the text in the JSON, extra headers, fallback file, help)
FACT_SOURCES: dict[str, tuple[str, str, tuple[str | int, ...], dict[str, str], str, str]] = {
    "catfact": ("🐱", "https://catfact.ninja/fact", ("fact",), {}, "fallback_catfacts", "Get a random cat fact."),
    "dogfact": (
        "🐶", "https://dogapi.dog/api/v2/facts", ("data", 0, "attributes", "body"), {},
        "fallback_dogfacts", "Get a random dog fact.",
    ),
    "fact": (
        "💡", "https://uselessfacts.jsph.pl/api/v2/facts/random?language=en", ("text",), {},
        "fallback_facts", "Get a random fact.",
    ),
    "dadjoke": (
        "😄", "https://icanhazdadjoke.com/", ("joke",), {"Accept": "application/json"},
        "fallback_dadjokes", "Get a random dad joke.",
    ),
}


def register_fun(
    registry: CommandRegistry,
    *,
    assets: Assets,
    rng: random.Random,
    http: HttpClient,
    stats: StatsStore,
    clock: Clock,
    lookup_user: LookupUser,
) -> None:
    async def eightball(ctx: CommandContext) -> None:
        ctx.reply(f"🎱 {rng.choice(assets.lines('8ball'))}")

    async def coinflip(ctx: CommandContext) -> None:
        ctx.reply(f"🪙 {rng.choice(['Heads', 'Tails'])}")

    registry.add(Command("8ball", eightball, "{p}8ball [question]", "Ask the magic 8-ball a question.", "Fun"))
    registry.add(Command("coinflip", coinflip, "{p}coinflip", "Flip a coin.", "Fun"))

    blocked = BlockedWords.load(assets)

    def fact_handler(emoji: str, url: str, path: tuple, headers: dict, fallback: str):
        async def handler(ctx: CommandContext) -> None:
            data = await http.get_json(url, headers=headers or None)
            try:
                text = _safe_text(_get(data, *path), blocked) if data is not None else None
            except (KeyError, IndexError, TypeError):
                text = None
            ctx.reply(f"{emoji} {text or rng.choice(assets.lines(fallback))}")

        return handler

    for name, (emoji, url, path, headers, fallback, help_text) in FACT_SOURCES.items():
        registry.add(Command(name, fact_handler(emoji, url, path, headers, fallback), f"{{p}}{name}", help_text, "Fun"))

    def already_message() -> str:
        now = clock.now()
        midnight = datetime.combine(now.date() + timedelta(days=1), time(0, 0), tzinfo=timezone.utc)
        wait = format_duration((midnight - now).total_seconds())
        return f"You already opened today's cookie. Next one in {wait} (00:00 UTC)."

    async def cookie(ctx: CommandContext) -> None:
        today = clock.now().date().isoformat()
        uid = ctx.msg.user_id
        argv = ctx.argv
        usage = f"Usage: {ctx.prefix}cookie or {ctx.prefix}cookie give <username>"
        if argv and argv[0].lower() != "give":
            ctx.reply(usage)  # e.g. "?cookie gift bob": don't silently spend the cookie
            return
        if argv:
            if len(argv) < 2:
                ctx.reply(usage)
                return
            login = clean_username(argv[1])
            if login is None:
                ctx.reply("That's not a valid username.")
                return
            if login == ctx.msg.login:
                ctx.reply("You can't give a cookie to yourself.")
                return
            if stats.get_daily(uid, "cookie", today) is not None:
                ctx.reply(already_message())
                return
            try:
                target = await asyncio.wait_for(lookup_user(login), LOOKUP_TIMEOUT)
            except TimeoutError:
                ctx.reply("Couldn't check that user right now. Try again in a bit.")
                return
            if target is None:
                ctx.reply("Couldn't find that user.")  # never repeat the name the user typed
                return
            if target.user_id == uid:
                ctx.reply("You can't give a cookie to yourself.")
                return
            fortune = rng.choice(assets.lines("fortunes"))
            record = json.dumps({"gave_to": target.login, "fortune": fortune})
            if not stats.claim_daily(uid, "cookie", today, record):
                ctx.reply(already_message())
                return
            giver = _mention(ctx.msg.display_name, ctx.msg.login)
            receiver = _mention(target.display_name, target.login)
            ctx.say(f"🥠 {giver} gave {receiver} a fortune cookie: {fortune}")
            return
        fortune = rng.choice(assets.lines("fortunes"))
        if not stats.claim_daily(uid, "cookie", today, json.dumps({"fortune": fortune})):
            ctx.reply(already_message())
            return
        ctx.reply(f"🥠 {fortune}")

    registry.add(
        Command(
            "cookie",
            cookie,
            "{p}cookie | {p}cookie give <username>",
            "Open your daily fortune cookie, or give it to someone. Resets at 00:00 UTC.",
            "Fun",
            global_cooldown=False,  # personal: one person's cookie shouldn't block another's
        )
    )
