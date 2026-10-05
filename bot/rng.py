"""?rng: one roll per person per UTC day, from 0 to 1,000,000, scored by badges.

Badge tiers follow each badge's real rarity over all 1,000,001 numbers (see tests/test_rng.py):
legendary about 1 in 100,000 or rarer, rare 1 in 1,000 or rarer, uncommon up to about 1 in 50,
common the rest. A roll earns every badge it matches; its score is the sum.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from functools import cache

from bot.clock import Clock
from bot.commands import Command, CommandContext, CommandRegistry
from bot.stats import PlayerResult, RngRoll, StatsStore
from bot.text import clean_username, format_duration

MAX_ROLL = 1_000_000
TOP_LIMIT = 5
TIER_POINTS = {"legendary": 100, "rare": 40, "uncommon": 15, "common": 5}
STRAIGHTS = {"012345", "123456", "234567", "345678", "456789", "987654", "876543", "765432", "654321", "543210"}


@dataclass(frozen=True)
class Badge:
    name: str
    tier: str
    test: Callable[[int, str], bool]  # (number, 6-digit string) -> earned
    meme: bool = False

    @property
    def points(self) -> int:
        return TIER_POINTS[self.tier]


@cache
def _primes() -> bytearray:
    sieve = bytearray([1]) * (MAX_ROLL + 1)
    sieve[0] = sieve[1] = 0
    for i in range(2, int(MAX_ROLL**0.5) + 1):
        if sieve[i]:
            sieve[i * i :: i] = bytearray(len(sieve[i * i :: i]))
    return sieve


def _fibonacci() -> frozenset[int]:
    numbers, a, b = {1}, 1, 2
    while b <= MAX_ROLL:
        numbers.add(b)
        a, b = b, a + b
    return frozenset(numbers)


FIBONACCI = _fibonacci()
SQUARES = frozenset(k * k for k in range(1, 1001))
CUBES = frozenset(k**3 for k in range(1, 101))
POWERS_OF_TWO = frozenset(2**k for k in range(21))


def _longest_run(s: str) -> int:
    best = current = 1
    for prev, ch in zip(s, s[1:], strict=False):
        current = current + 1 if ch == prev else 1
        best = max(best, current)
    return best


def _digit_sum(s: str) -> int:
    return sum(int(ch) for ch in s)


BADGES: tuple[Badge, ...] = (
    Badge("Zero", "legendary", lambda n, s: n == 0),
    Badge("Max", "legendary", lambda n, s: n == MAX_ROLL),
    Badge("Six of a kind", "legendary", lambda n, s: 0 < n < MAX_ROLL and len(set(s)) == 1),
    Badge("Straight", "legendary", lambda n, s: s in STRAIGHTS),
    Badge("Round hundred-thousand", "legendary", lambda n, s: 0 < n < MAX_ROLL and n % 100_000 == 0),
    Badge("Nice nice nice", "legendary", lambda n, s: n == 696_969, meme=True),
    Badge("Blaze it", "legendary", lambda n, s: n == 420_420, meme=True),
    Badge("Power of two", "rare", lambda n, s: n in POWERS_OF_TWO),
    Badge("Fibonacci", "rare", lambda n, s: n in FIBONACCI),
    Badge("Round ten-thousand", "rare", lambda n, s: n % 10_000 == 0 and n % 100_000 != 0),
    Badge("Perfect cube", "rare", lambda n, s: n in CUBES),
    Badge("Five in a row", "rare", lambda n, s: _longest_run(s) == 5),
    Badge("1337", "rare", lambda n, s: "1337" in s),
    Badge("Palindrome", "rare", lambda n, s: n < MAX_ROLL and s == s[::-1]),
    Badge("Perfect square", "rare", lambda n, s: n in SQUARES),
    Badge("Four in a row", "uncommon", lambda n, s: _longest_run(s) == 4),
    Badge("Contains 420", "uncommon", lambda n, s: "420" in s, meme=True),
    Badge("Ends in 00", "uncommon", lambda n, s: n % 100 == 0 and n % 10_000 != 0),
    Badge("All even digits", "uncommon", lambda n, s: all(ch in "02468" for ch in s)),
    Badge("All odd digits", "uncommon", lambda n, s: all(ch in "13579" for ch in s)),
    Badge(  # five of the six digits read the same backwards
        "Near palindrome", "uncommon",
        lambda n, s: n < MAX_ROLL and s != s[::-1] and (s[:5] == s[4::-1] or s[1:] == s[:0:-1]),
    ),
    Badge("Triple", "common", lambda n, s: _longest_run(s) == 3),
    Badge("Doubles", "common", lambda n, s: len({a for a, b in zip(s, s[1:], strict=False) if a == b}) >= 2),
    Badge("Lucky sum", "common", lambda n, s: _digit_sum(s) in (7, 13, 21)),
    Badge("Contains 69", "common", lambda n, s: "69" in s, meme=True),
    Badge("Contains 67", "common", lambda n, s: "67" in s),
    Badge("Prime", "common", lambda n, s: bool(_primes()[n])),
)


def badges_for(number: int, meme_badges: bool = True) -> list[Badge]:
    """Every badge the number earns, highest tier first."""
    digits = f"{number:06d}"
    earned = [b for b in BADGES if (meme_badges or not b.meme) and b.test(number, digits)]
    return sorted(earned, key=lambda b: -b.points)


def _describe(roll: RngRoll) -> str:
    return f"{roll.number:,} ({roll.score} pts)"


def register_rng(
    registry: CommandRegistry, *, stats: StatsStore, clock: Clock, rng: random.Random, meme_badges: bool
) -> None:
    def today() -> str:
        return clock.now().date().isoformat()

    def until_reset() -> str:
        now = clock.now()
        midnight = datetime.combine(now.date() + timedelta(days=1), time(0), tzinfo=timezone.utc)
        return format_duration((midnight - now).total_seconds())

    def roll(ctx: CommandContext) -> None:
        uid = ctx.msg.user_id
        existing = stats.rng_roll(uid, today())
        if existing is None:
            number = rng.randint(0, MAX_ROLL)
            earned = badges_for(number, meme_badges)
            score = sum(b.points for b in earned)
            player = PlayerResult(uid, ctx.msg.login, ctx.msg.display_name, score, False)
            if stats.record_rng_roll(player, today(), number, [b.name for b in earned], clock.now()):
                parts = [f"🏅 {b.name} ({b.tier}, {b.points})" for b in earned]
                tail = " · ".join([*parts, f"{score} pts"]) if earned else "no badges this time"
                ctx.reply(f"🎲 {ctx.msg.display_name} rolled {number:,} · {tail}")
                return
            existing = stats.rng_roll(uid, today())  # rolled at the same moment in another message
        assert existing is not None
        ctx.reply(f"🎲 You already rolled {_describe(existing)} today. Next roll in {until_reset()} (00:00 UTC).")

    def player_summary(user_id: str, name: str) -> str | None:
        best = stats.best_rng_roll(user_id)
        if best is None:
            return None
        current = stats.rng_roll(user_id, today())
        today_text = f"today {_describe(current)}" if current else "no roll today yet"
        return f"🎲 {name}: {today_text} · best ever {_describe(best)}"

    def top(day: str | None, label: str) -> str:
        rows = stats.top_rng_rolls(day, TOP_LIMIT)
        if not rows:
            return f"No rolls {'today' if day else 'yet'}."
        body = " ".join(f"{i}. {r.display_name} {r.number:,} ({r.score})" for i, r in enumerate(rows, start=1))
        return f"🎲 {label}: {body}"

    async def rng_command(ctx: CommandContext) -> None:
        arg = ctx.argv[0].lower() if ctx.argv else ""
        if not arg:
            roll(ctx)
        elif arg == "today":
            ctx.reply(top(today(), "Today's best rolls"))
        elif arg == "top":
            ctx.reply(top(None, "Best rolls ever"))
        elif arg == "me":
            summary = player_summary(ctx.msg.user_id, ctx.msg.display_name)
            ctx.reply(summary or f"You haven't rolled yet. Try {ctx.prefix}rng.")
        else:
            login = clean_username(ctx.argv[0])
            user = stats.find_user(login) if login else None
            summary = player_summary(user.user_id, user.display_name) if user else None
            ctx.reply(summary or "No rolls for that user yet.")  # never repeat the name the user typed

    registry.add(
        Command(
            "rng",
            rng_command,
            "{p}rng | {p}rng me|today|top|<username>",
            "Your daily roll from 0 to 1,000,000, scored by badges (points count on the leaderboard). "
            "Resets at 00:00 UTC.",
            "Fun",
            global_cooldown=False,  # personal: one person's roll never blocks another's
        )
    )
