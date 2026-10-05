"""?help / ?commands, generated from the command registry."""

from __future__ import annotations

from bot.commands import Command, CommandContext, CommandRegistry


def register_help(registry: CommandRegistry) -> None:
    async def help_command(ctx: CommandContext) -> None:
        if not ctx.argv:
            ctx.reply(registry.help_overview())
            return
        text = registry.help_for(ctx.argv[0].lower().removeprefix(ctx.prefix))
        # Never repeat what was typed: an unknown name could be any phrase a troll chose.
        ctx.reply(text or f"No command by that name. Try {ctx.prefix}help.")

    registry.add(
        Command(
            "help",
            help_command,
            "{p}help [command]",
            "List commands, or explain one.",
            "Info",
            aliases=("commands",),
            listed=False,
            global_cooldown=False,  # personal: one person's ?help shouldn't block another's
        )
    )
