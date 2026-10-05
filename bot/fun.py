"""Quick one-shot commands: ?8ball ?coinflip ?catfact ?dogfact ?fact ?dadjoke ?cookie."""

from __future__ import annotations

import json
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta, timezone
from typing import Any

from bot.assets import Assets
from bot.clock import Clock
from bot.commands import Command, CommandContext, CommandRegistry
from bot.connectors.base import UserRef
from bot.http import HttpClient
from bot.stats import StatsStore
from bot.text import clean_username, format_duration

MAX_FACT = 400

LookupUser = Callable[[str], Awaitable[UserRef | None]]


def _get(data: Any, *path: str | int) -> Any:
    for key in path:
        data = data[key]
    return data


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

    def fact_handler(emoji: str, url: str, path: tuple, headers: dict, fallback: str):
        async def handler(ctx: CommandContext) -> None:
            data = await http.get_json(url, headers=headers or None)
            text = None
            try:
                text = " ".join(str(_get(data, *path)).split()) if data is not None else None
            except (KeyError, IndexError, TypeError):
                text = None
            if not text or len(text) > MAX_FACT:
                text = rng.choice(assets.lines(fallback))
            ctx.reply(f"{emoji} {text}")

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
        if argv and argv[0].lower() == "give":
            if len(argv) < 2:
                ctx.reply(f"Usage: {ctx.prefix}cookie give <username>")
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
            target = await lookup_user(login)
            if target is None:
                ctx.reply(f"Couldn't find a user named {login}.")
                return
            fortune = rng.choice(assets.lines("fortunes"))
            record = json.dumps({"gave_to": target.login, "fortune": fortune})
            if not stats.claim_daily(uid, "cookie", today, record):
                ctx.reply(already_message())
                return
            ctx.say(f"🥠 @{ctx.msg.display_name} gave @{target.display_name} a fortune cookie: {fortune}")
            return
        fortune = rng.choice(assets.lines("fortunes"))
        if not stats.claim_daily(uid, "cookie", today, fortune):
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
        )
    )
