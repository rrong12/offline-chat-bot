"""Control commands for the broadcaster, mods, and owners: ?bot off/on/status/shutdown, ?stopgame."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.commands import Command, CommandContext, CommandRegistry

if TYPE_CHECKING:
    from bot.core import BotCore


def register_admin(registry: CommandRegistry, core: BotCore) -> None:
    async def bot_command(ctx: CommandContext) -> None:
        sub = ctx.argv[0].lower() if ctx.argv else ""
        who = ctx.msg.display_name
        if sub == "off":
            if core.paused:
                ctx.reply("Already paused.", priority=True)
                return
            core.log.write("admin", user_id=ctx.msg.user_id, login=ctx.msg.login, action="off")
            core.games.stop_all()
            core.set_paused(True)
            ctx.reply(f"Bot paused by {who}. {ctx.prefix}bot on to resume.", priority=True)
        elif sub == "on":
            if not core.paused:
                ctx.reply("Already on.", priority=True)
                return
            core.log.write("admin", user_id=ctx.msg.user_id, login=ctx.msg.login, action="on")
            core.set_paused(False)
            ctx.reply(f"Bot resumed by {who}.", priority=True)
        elif sub == "status":
            ctx.reply(core.status_line(), priority=True)
        elif sub == "shutdown":
            core.log.write("admin", user_id=ctx.msg.user_id, login=ctx.msg.login, action="shutdown")
            ctx.reply(f"Shutting down (requested by {who}).", priority=True)
            core.request_shutdown(by=ctx.msg.login)
        else:
            ctx.reply(f"Usage: {ctx.prefix}bot off|on|status|shutdown", priority=True)

    async def stopgame(ctx: CommandContext) -> None:
        if not core.games.sessions:
            ctx.reply("No games are running.")
            return
        core.log.write("admin", user_id=ctx.msg.user_id, login=ctx.msg.login, action="stopgame")
        stopped = core.games.stop_all()
        ctx.reply(f"🛑 Stopped {stopped} game{'s' if stopped != 1 else ''}. No points awarded.")

    registry.add(
        Command(
            "bot",
            bot_command,
            "{p}bot off|on|status|shutdown",
            "Pause, resume, check, or shut down the bot. Shutdown really stops it until someone restarts it.",
            "Control",
            controller_only=True,
            cooldown=False,
            listed=False,
        )
    )
    registry.add(
        Command(
            "stopgame",
            stopgame,
            "{p}stopgame",
            "End all running games with no points.",
            "Control",
            controller_only=True,
            cooldown=False,
            listed=False,
        )
    )
