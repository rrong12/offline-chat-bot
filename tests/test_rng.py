from collections import Counter

import pytest

from bot.clock import FakeClock
from bot.commands import CommandContext, CommandRegistry
from bot.rng import BADGES, MAX_ROLL, badges_for, register_rng, show
from bot.stats import StatsStore
from tests.helpers import make_msg

# Every badge's tier and exact count over all 1,000,001 numbers (measured; the tiers follow the counts).
EXPECTED = {
    "Zero": ("legendary", 1),
    "Max": ("legendary", 1),
    "Six of a kind": ("legendary", 9),
    "Straight": ("legendary", 10),
    "Round hundred-thousand": ("legendary", 9),
    "Nice nice nice": ("legendary", 1),
    "Blaze it": ("legendary", 1),
    "Power of two": ("rare", 20),
    "Fibonacci": ("rare", 29),
    "Round ten-thousand": ("rare", 90),
    "Perfect cube": ("rare", 100),
    "Five in a row": ("rare", 180),
    "1337": ("rare", 300),
    "Palindrome": ("rare", 1_000),
    "Perfect square": ("rare", 1_000),
    "Four in a row": ("uncommon", 2_610),
    "Contains 420": ("uncommon", 3_999),
    "Ends in 00": ("uncommon", 9_900),
    "All even digits": ("uncommon", 15_625),
    "All odd digits": ("uncommon", 15_625),
    "Five-digit palindrome": ("uncommon", 19_890),
    "Triple": ("common", 34_110),
    "Doubles": ("common", 47_160),
    "Lucky sum": ("common", 48_686),
    "Contains 69": ("common", 49_401),
    "Contains 67": ("common", 49_401),
    "Prime": ("common", 78_498),
}
MEME = {"Nice nice nice", "Blaze it", "Contains 420", "Contains 69"}


def names(number: int, meme: bool = True) -> set[str]:
    return {b.name for b in badges_for(number, meme)}


@pytest.mark.parametrize("number, expected", [
    (0, {"Zero", "Palindrome", "All even digits"}),
    (MAX_ROLL, {"Max", "Perfect cube", "Perfect square"}),
    (1, {"Power of two", "Fibonacci", "Perfect cube", "Perfect square", "Five in a row", "Five-digit palindrome"}),
    (7, {"Five in a row", "Five-digit palindrome", "Lucky sum", "Prime"}),
    (13, {"Fibonacci", "Prime", "Four in a row"}),  # 000013
    (1_337, {"1337", "Doubles"}),  # 001337: two different repeated pairs
    (1_039, {"Lucky sum", "Prime"}),
    (9_900, {"Palindrome", "Ends in 00", "Doubles"}),
    (10_000, {"Round ten-thousand", "Perfect square", "Four in a row"}),
    (12_345, {"Straight"}),  # 012345
    (50_000, {"Round ten-thousand", "Four in a row"}),
    (106_700, {"Ends in 00", "Contains 67"}),
    (111_222, {"Triple", "Doubles"}),
    (123_321, {"Palindrome"}),  # one repeated pair is not Doubles
    (123_456, {"Straight", "Lucky sum"}),  # 1+2+3+4+5+6 = 21
    (300_000, {"Round hundred-thousand", "Five in a row", "Five-digit palindrome"}),
    (482_193, set()),
    (524_288, {"Power of two"}),
    (777_777, {"Six of a kind", "Palindrome", "All odd digits"}),
    (864_202, {"All even digits", "Contains 420"}),
    (975_319, {"All odd digits"}),
    (987_654, {"Straight"}),
    (999_983, {"Four in a row", "Prime"}),
])
def test_badge_rules(number, expected):
    assert names(number) == expected


def test_meme_badges_can_be_turned_off():
    assert names(696_969) == {"Nice nice nice", "Contains 69", "Five-digit palindrome"}
    assert names(696_969, meme=False) == {"Five-digit palindrome"}
    assert names(420_420) == {"Blaze it", "Contains 420", "All even digits"}
    assert names(420_420, meme=False) == {"All even digits"}
    assert {b.name for b in BADGES if b.meme} == MEME


def test_badges_are_listed_highest_tier_first():
    points = [b.points for b in badges_for(0)]
    assert points == sorted(points, reverse=True) == [100, 40, 15]


def test_every_badge_has_its_measured_count_and_tier():
    counts = Counter(b.name for n in range(MAX_ROLL + 1) for b in badges_for(n))
    assert {b.name: (b.tier, counts[b.name]) for b in BADGES} == EXPECTED
    by_tier = {}
    for tier, count in EXPECTED.values():
        by_tier.setdefault(tier, []).append(count)
    # each tier is strictly rarer than the next
    assert max(by_tier["legendary"]) < min(by_tier["rare"])
    assert max(by_tier["rare"]) < min(by_tier["uncommon"])
    assert max(by_tier["uncommon"]) < min(by_tier["common"])


def test_rolls_show_six_digits():
    assert (show(1_337), show(13), show(140_891), show(MAX_ROLL)) == ("001,337", "000,013", "140,891", "1,000,000")


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

    async def run(self, text: str, login: str = "alice") -> str | None:
        name, _, args = text.removeprefix("?").partition(" ")
        before = len(self.replies)
        ctx = CommandContext(make_msg(text, login), name, args, "?", lambda t, **kw: self.replies.append(t), None)
        await self.registry.get(name).handler(ctx)
        return self.replies[-1] if len(self.replies) > before else None


async def test_daily_roll_then_repeat_then_next_day():
    r = Rng(1_337, 482_193)
    assert await r.run("?rng") == "🎲 alice rolled 001,337 · 🏅 1337 (rare, 40) · 🏅 Doubles (common, 5) · 45 pts"
    assert await r.run("?rng") == "🎲 You already rolled 001,337 (45 pts) today. Next roll in 12h 0m (00:00 UTC)."
    r.clock.advance(12 * 3600)
    assert await r.run("?rng") == "🎲 alice rolled 482,193 · no badges this time"
    assert [(row.user_id, row.points) for row in r.stats.leaderboard("rng", 5)] == [("id-alice", 45)]


async def test_a_roll_stored_by_a_racing_message_is_shown(monkeypatch):
    from bot.stats import PlayerResult

    r = Rng(482_193)
    real = r.stats.record_rng_roll

    def racing(player, day, number, badges, now):
        real(PlayerResult("id-alice", "alice", "alice", 45, False), day, 1_337, ["1337", "Doubles"], now)
        return real(player, day, number, badges, now)  # the other message got there first: refused

    monkeypatch.setattr(r.stats, "record_rng_roll", racing)
    assert await r.run("?rng") == "🎲 You already rolled 001,337 (45 pts) today. Next roll in 12h 0m (00:00 UTC)."


async def test_me_other_user_and_unknown_user():
    r = Rng(1_337)
    assert await r.run("?rng me") == "You haven't rolled yet. Try ?rng."
    await r.run("?rng", "bob")
    assert await r.run("?rng me", "bob") == "🎲 bob: today 001,337 (45 pts) · best ever 001,337 (45 pts)"
    assert await r.run("?rng @Bob") == "🎲 bob: today 001,337 (45 pts) · best ever 001,337 (45 pts)"
    r.clock.advance(24 * 3600)
    assert await r.run("?rng bob") == "🎲 bob: no roll today yet · best ever 001,337 (45 pts)"
    assert await r.run("?rng some_troll_name") == "No rolls for that user yet."  # never echoed
    r.stats.touch_user("id-carol", "carol", "carol", r.clock.now())  # chatted, never rolled
    assert await r.run("?rng carol") == "No rolls for that user yet."
    assert await r.run("?rng help") == "Try ?rng, ?rng me, ?rng today, ?rng top or ?rng <username>."


async def test_today_and_top_with_a_chat_wide_limit():
    r = Rng(13, 0, 1_337)
    assert await r.run("?rng today") == "No rolls today."
    assert await r.run("?rng top") == "No rolls yet."
    await r.run("?rng", "alice")
    await r.run("?rng", "bob")
    await r.run("?rng", "carol")
    assert await r.run("?rng today", "dave") is None  # the same reply went out less than 5 s ago
    r.clock.advance(5)
    expected = "🎲 Today's best rolls: 1. bob 000,000 (155) 2. alice 000,013 (60) 3. carol 001,337 (45)"
    assert await r.run("?rng today", "dave") == expected
    r.clock.advance(24 * 3600)
    assert await r.run("?rng today") == "No rolls today."
    assert (await r.run("?rng top")).startswith("🎲 Best rolls ever: 1. bob 000,000 (155)")


async def test_meme_badges_off_changes_the_score():
    r = Rng(696_969, meme=False)
    assert await r.run("?rng") == "🎲 alice rolled 696,969 · 🏅 Five-digit palindrome (uncommon, 15) · 15 pts"
