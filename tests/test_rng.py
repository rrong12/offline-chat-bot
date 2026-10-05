from collections import Counter

import pytest

from bot.clock import FakeClock
from bot.commands import CommandContext, CommandRegistry
from bot.rng import BADGES, MAX_ROLL, TIER_POINTS, badges_for, register_rng
from bot.stats import StatsStore
from tests.helpers import make_msg


def names(number: int, meme: bool = True) -> set[str]:
    return {b.name for b in badges_for(number, meme)}


@pytest.mark.parametrize("number, expected", [
    (0, {"Zero", "Palindrome", "All even digits"}),
    (MAX_ROLL, {"Max", "Perfect cube", "Perfect square"}),
    (777_777, {"Six of a kind", "Palindrome", "All odd digits"}),
    (123_456, {"Straight", "Lucky sum"}),  # 1+2+3+4+5+6 = 21
    (300_000, {"Round hundred-thousand", "Five in a row", "Near palindrome"}),
    (524_288, {"Power of two"}),
    (13, {"Fibonacci", "Prime", "Four in a row"}),  # 000013
    (1_337, {"1337", "Doubles"}),  # 001337: two different repeated pairs
    (50_000, {"Round ten-thousand", "Four in a row"}),
    (111_222, {"Triple", "Doubles"}),
    (123_321, {"Palindrome"}),  # one repeated pair is not Doubles
    (482_193, set()),
])
def test_badge_rules(number, expected):
    assert names(number) == expected


def test_meme_badges_can_be_turned_off():
    assert names(696_969) == {"Nice nice nice", "Contains 69", "Near palindrome"}
    assert names(696_969, meme=False) == {"Near palindrome"}
    assert names(420_420) == {"Blaze it", "Contains 420", "All even digits"}
    assert names(420_420, meme=False) == {"All even digits"}


def test_badges_are_listed_highest_tier_first():
    points = [b.points for b in badges_for(0)]
    assert points == sorted(points, reverse=True) == [100, 40, 15]


def test_tiers_match_real_rarity_over_every_number():
    counts = Counter()
    for n in range(MAX_ROLL + 1):
        digits = f"{n:06d}"
        for b in BADGES:
            if b.test(n, digits):
                counts[b.name] += 1
    by_tier = {tier: [counts[b.name] for b in BADGES if b.tier == tier] for tier in TIER_POINTS}
    assert all(c >= 1 for c in counts.values()) and len(counts) == len(BADGES)  # every badge can happen
    assert max(by_tier["legendary"]) <= 10  # about 1 in 100,000 or rarer
    assert max(by_tier["rare"]) <= 1_000  # 1 in 1,000 or rarer
    assert max(by_tier["uncommon"]) <= 25_000  # up to about 1 in 40
    assert max(by_tier["legendary"]) < min(by_tier["rare"])
    assert max(by_tier["rare"]) < min(by_tier["uncommon"])
    assert max(by_tier["uncommon"]) < min(by_tier["common"])


class FixedRng:
    def __init__(self, *numbers: int):
        self.numbers = list(numbers)

    def randint(self, low, high):
        return self.numbers.pop(0)


class Rng:
    def __init__(self, *numbers: int, meme: bool = True):
        self.clock = FakeClock()  # 2026-10-04 12:00 UTC
        self.stats = StatsStore(":memory:")
        self.registry = CommandRegistry("?")
        register_rng(self.registry, stats=self.stats, clock=self.clock, rng=FixedRng(*numbers), meme_badges=meme)
        self.replies: list[str] = []

    async def run(self, text: str, login: str = "alice") -> str:
        name, _, args = text.removeprefix("?").partition(" ")
        ctx = CommandContext(make_msg(text, login), name, args, "?", lambda t, **kw: self.replies.append(t), None)
        await self.registry.get(name).handler(ctx)
        return self.replies[-1]


async def test_daily_roll_then_repeat_then_next_day():
    r = Rng(1_337, 482_193)
    assert await r.run("?rng") == "🎲 alice rolled 1,337 · 🏅 1337 (rare, 40) · 🏅 Doubles (common, 5) · 45 pts"
    assert await r.run("?rng") == "🎲 You already rolled 1,337 (45 pts) today. Next roll in 12h 0m (00:00 UTC)."
    r.clock.advance(12 * 3600)
    assert await r.run("?rng") == "🎲 alice rolled 482,193 · no badges this time"
    assert [(row.user_id, row.points) for row in r.stats.leaderboard("rng", 5)] == [("id-alice", 45)]


async def test_me_other_user_and_unknown_user():
    r = Rng(1_337)
    assert await r.run("?rng me") == "You haven't rolled yet. Try ?rng."
    await r.run("?rng", "bob")
    assert await r.run("?rng me", "bob") == "🎲 bob: today 1,337 (45 pts) · best ever 1,337 (45 pts)"
    assert await r.run("?rng @Bob") == "🎲 bob: today 1,337 (45 pts) · best ever 1,337 (45 pts)"
    r.clock.advance(24 * 3600)
    assert await r.run("?rng bob") == "🎲 bob: no roll today yet · best ever 1,337 (45 pts)"
    assert await r.run("?rng some_troll_name") == "No rolls for that user yet."  # never echoed


async def test_today_and_top():
    r = Rng(13, 0, 1_337)
    assert await r.run("?rng today") == "No rolls today."
    assert await r.run("?rng top") == "No rolls yet."
    await r.run("?rng", "alice")
    await r.run("?rng", "bob")
    await r.run("?rng", "carol")
    assert await r.run("?rng today") == "🎲 Today's best rolls: 1. bob 0 (155) 2. alice 13 (60) 3. carol 1,337 (45)"
    r.clock.advance(24 * 3600)
    assert await r.run("?rng today") == "No rolls today."
    assert (await r.run("?rng top")).startswith("🎲 Best rolls ever: 1. bob 0 (155)")


async def test_meme_badges_off_changes_the_score():
    r = Rng(696_969, meme=False)
    assert await r.run("?rng") == "🎲 alice rolled 696,969 · 🏅 Near palindrome (uncommon, 15) · 15 pts"
