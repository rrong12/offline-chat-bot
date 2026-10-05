"""?help / ?commands, generated from the command registry."""

from __future__ import annotations

import re

from bot.commands import Command, CommandContext, CommandRegistry

_SAFE_NAME = re.compile(r"^[a-z0-9_]{1,20}$")


def register_help(registry: CommandRegistry) -> None:
    async def help_command(ctx: CommandContext) -> None:
        if not ctx.argv:
            ctx.reply(registry.help_overview())
            return
        name = ctx.argv[0].lower().removeprefix(ctx.prefix)
        text = registry.help_for(name)
        if text is None:
            shown = f" named {name}" if _SAFE_NAME.fullmatch(name) else ""
            text = f"No command{shown}. Try {ctx.prefix}help."
        ctx.reply(text)

    registry.add(
        Command(
            "help",
            help_command,
            "{p}help [command]",
            "List commands, or explain one.",
            "Info",
            aliases=("commands",),
            listed=False,
        )
    )
