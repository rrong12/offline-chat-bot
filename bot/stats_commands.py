"""?leaderboard and ?gamestats."""

from __future__ import annotations

import re
from collections.abc import Sequence

from bot.commands import Command, CommandContext, CommandRegistry
from bot.stats import StatsStore
from bot.text import clean_username

DEFAULT_LIMIT = 5
MAX_LIMIT = 10
_NUMBER = re.compile(r"-?[0-9]+")  # ASCII only: str.isdigit() accepts "²", which int() rejects


def _plural(count: int, word: str) -> str:
    return word if count == 1 else word + "s"


def register_stats(registry: CommandRegistry, *, stats: StatsStore, game_names: Sequence[str]) -> None:
    games = [g.lower() for g in game_names]

    async def leaderboard(ctx: CommandContext) -> None:
        game: str | None = None
        limit = DEFAULT_LIMIT
        for arg in ctx.argv[:2]:
            if _NUMBER.fullmatch(arg):
                limit = max(1, min(MAX_LIMIT, int(arg)))
            elif arg.lower() in games:
                game = arg.lower()
            else:
                ctx.reply(f"Unknown game. Games: {', '.join(games)}")
                return
        rows = stats.leaderboard(game, limit)
        label = game or "overall"
        if not rows:
            ctx.reply(f"No {label} scores yet.")
            return
        body = " ".join(f"{i}. {r.display_name} ({r.points})" for i, r in enumerate(rows, start=1))
        ctx.reply(f"🏆 Top {len(rows)} {label}: {body}")

    async def gamestats(ctx: CommandContext) -> None:
        argv = ctx.argv
        game: str | None = None
        # A first argument that names a game is the game, even if someone's login is the same word.
        if argv and argv[0].lower() in games:
            game = argv[0].lower()
            argv = argv[1:]
        if argv:
            login = clean_username(argv[0])
            if login is None:
                ctx.reply("That's not a valid username.")
                return
            user = stats.find_user(login)
            if user is None:
                ctx.reply("No stats for that user yet.")  # never repeat the name the user typed
                return
            user_id, name = user.user_id, user.display_name
        else:
            user_id, name = ctx.msg.user_id, ctx.msg.display_name
        per_game = stats.user_stats(user_id)
        if game is not None:
            row = next((g for g in per_game if g.game == game), None)
            if row is None:
                ctx.reply(f"No {game} stats for {name} yet.")
                return
            rank = stats.rank(user_id, game)
            rank_text = f" · rank #{rank}" if rank else ""
            wins_text = f"{row.wins} {_plural(row.wins, 'win')}"
            ctx.reply(f"📊 {name} · {game}: {wins_text} / {row.played} played · {row.points} pts{rank_text}")
            return
        if not per_game:
            ctx.reply(f"No stats for {name} yet.")
            return
        points = sum(g.points for g in per_game)
        wins = sum(g.wins for g in per_game)
        played = sum(g.played for g in per_game)
        parts = " | ".join(f"{g.game} {g.wins}W/{g.played}P {g.points}pts" for g in per_game)
        ctx.reply(f"📊 {name}: {points} pts, {wins} {_plural(wins, 'win')}, {played} played | {parts}")

    registry.add(
        Command(
            "leaderboard",
            leaderboard,
            "{p}leaderboard [game] [1-10]",
            "Top players by points, overall or for one game.",
            "Stats",
        )
    )
    registry.add(
        Command(
            "gamestats",
            gamestats,
            "{p}gamestats [game] [username]",
            "Wins, games played, and points: yours or someone else's, overall or for one game.",
            "Stats",
            global_cooldown=False,  # personal lookup: never blocked by someone else's
        )
    )
