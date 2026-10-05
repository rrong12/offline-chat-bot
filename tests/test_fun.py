import asyncio
import random

import pytest

from bot.clock import FakeClock
from bot.commands import CommandContext, CommandRegistry
from bot.connectors.base import UserRef
from bot.fun import register_fun
from bot.stats import StatsStore
from tests.helpers import FakeHttp, make_msg


class Fun:
    def __init__(self, assets, clock: FakeClock, http: FakeHttp | None = None):
        self.http = http or FakeHttp()
        self.stats = StatsStore(":memory:")
        self.registry = CommandRegistry("?")
        self.replies: list[str] = []
        self.said: list[str] = []
        self.known = {"bob": UserRef("id-bob", "bob", "Bob")}

        async def default_lookup(login):
            return self.known.get(login)

        self.lookup = default_lookup

        async def lookup(login):
            return await self.lookup(login)

        register_fun(
            self.registry, assets=assets, rng=random.Random(1), http=self.http,
            stats=self.stats, clock=clock, lookup_user=lookup,
        )

    async def run(self, text: str, login: str = "alice") -> None:
        name, _, args = text.removeprefix("?").partition(" ")
        ctx = CommandContext(
            make_msg(text, login), name, args, "?",
            lambda t, **kw: self.replies.append(t), lambda t, **kw: self.said.append(t),
        )
        await self.registry.get(name).handler(ctx)


@pytest.fixture
def fun(assets, clock) -> Fun:
    return Fun(assets, clock)


async def test_8ball_and_coinflip(fun: Fun):
    await fun.run("?8ball will I win?")
    await fun.run("?coinflip")
    assert fun.replies[0] in ("🎱 Yes.", "🎱 No.")
    assert fun.replies[1] in ("🪙 Heads", "🪙 Tails")


async def test_facts_use_api_and_clean_whitespace(assets, clock):
    http = FakeHttp({
        "https://catfact.ninja/fact": {"fact": "Cats  have\nwhiskers."},
        "https://dogapi.dog/api/v2/facts": {"data": [{"attributes": {"body": "Dogs bark."}}]},
        "https://uselessfacts.jsph.pl/api/v2/facts/random?language=en": {"text": "Honey never spoils."},
        "https://icanhazdadjoke.com/": {"joke": "I'm reading a book on anti-gravity."},
    })
    fun = Fun(assets, clock, http)
    for name in ("catfact", "dogfact", "fact", "dadjoke"):
        await fun.run(f"?{name}")
    assert fun.replies == [
        "🐱 Cats have whiskers.",
        "🐶 Dogs bark.",
        "💡 Honey never spoils.",
        "😄 I'm reading a book on anti-gravity.",
    ]
    assert http.calls[3] == ("https://icanhazdadjoke.com/", {"Accept": "application/json"})


async def test_fact_falls_back_when_api_fails_or_is_malformed_or_too_long(assets, clock):
    http = FakeHttp({
        "https://catfact.ninja/fact": None,
        "https://dogapi.dog/api/v2/facts": {"unexpected": True},
        "https://uselessfacts.jsph.pl/api/v2/facts/random?language=en": {"text": "x" * 401},
        "https://icanhazdadjoke.com/": {"joke": None},
    })
    fun = Fun(assets, clock, http)
    for name in ("catfact", "dogfact", "fact", "dadjoke"):
        await fun.run(f"?{name}")
    assert fun.replies == [
        "🐱 fallback catfacts line",
        "🐶 fallback dogfacts line",
        "💡 fallback facts line",
        "😄 fallback dadjokes line",
    ]


@pytest.mark.parametrize("bad", [
    "Visit https://spam.example now", "see www.spam.example", "ask @someone about it", 42, ["a", "b"],
])
async def test_fact_with_links_mentions_or_wrong_type_falls_back(assets, clock, bad):
    fun = Fun(assets, clock, FakeHttp({"https://catfact.ninja/fact": {"fact": bad}}))
    await fun.run("?catfact")
    assert fun.replies == ["🐱 fallback catfacts line"]


async def test_fact_text_is_stripped_of_invisible_and_control_characters(assets, clock):
    text = "Cats" + chr(0x202E) + " purr" + chr(0x07) + "."
    fun = Fun(assets, clock, FakeHttp({"https://catfact.ninja/fact": {"fact": text}}))
    await fun.run("?catfact")
    assert fun.replies == ["🐱 Cats purr."]


async def test_cookie_once_per_utc_day(fun: Fun, clock: FakeClock):
    await fun.run("?cookie")
    assert fun.replies[-1] == "🥠 Good things are coming."
    await fun.run("?cookie")
    assert fun.replies[-1] == "You already opened today's cookie. Next one in 12h 0m (00:00 UTC)."
    clock.advance(12 * 3600)
    await fun.run("?cookie")
    assert fun.replies[-1] == "🥠 Good things are coming."


async def test_cookie_give(fun: Fun):
    await fun.run("?cookie give @Bob")
    assert fun.said == ["🥠 @alice gave @Bob a fortune cookie: Good things are coming."]
    await fun.run("?cookie")
    assert fun.replies[-1].startswith("You already opened today's cookie.")
    await fun.run("?cookie", "bob")  # the recipient's own cookie is unaffected
    assert fun.replies[-1] == "🥠 Good things are coming."


async def test_cookie_give_rejections_do_not_use_the_cookie(fun: Fun):
    await fun.run("?cookie give")
    await fun.run("?cookie give not/valid")
    await fun.run("?cookie give alice")
    await fun.run("?cookie give ghost_user")
    await fun.run("?cookie gift bob")
    assert fun.replies == [
        "Usage: ?cookie or ?cookie give <username>",
        "That's not a valid username.",
        "You can't give a cookie to yourself.",
        "Couldn't find that user.",
        "Usage: ?cookie or ?cookie give <username>",
    ]
    await fun.run("?cookie")
    assert fun.replies[-1] == "🥠 Good things are coming."


async def test_cookie_give_after_cookie_used(fun: Fun):
    await fun.run("?cookie")
    await fun.run("?cookie give bob")
    assert fun.replies[-1].startswith("You already opened today's cookie.")
    assert fun.said == []


async def test_cookie_give_lookup_timeout(assets, clock, monkeypatch):
    import bot.fun

    monkeypatch.setattr(bot.fun, "LOOKUP_TIMEOUT", 0.05)
    fun = Fun(assets, clock)

    async def slow(login):
        await asyncio.sleep(1)

    fun.lookup = slow
    await fun.run("?cookie give bob")
    assert fun.replies == ["Couldn't check that user right now. Try again in a bit."]
    await fun.run("?cookie")
    assert fun.replies[-1] == "🥠 Good things are coming."


async def test_cookie_give_mentions_login_for_localised_display_names(fun: Fun):
    fun.known["bob"] = UserRef("id-bob", "bob", "\u9cf3\u51f0")
    await fun.run("?cookie give bob")
    assert fun.said == ["🥠 @alice gave @bob a fortune cookie: Good things are coming."]
