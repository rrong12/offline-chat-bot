"""Command parsing, the command registry, and help text generated from it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from bot.connectors.base import ChatMessage
from bot.text import strip_invisible, truncate

GROUP_ORDER = ("Games", "Stats", "Fun")  # groups shown in the ?help overview, in this order
GROUPS = (*GROUP_ORDER, "Control", "Info")


def parse_command(text: str, prefix: str) -> tuple[str, str] | None:
    """'?Scramble animals' -> ('scramble', 'animals'). None if the text isn't a command."""
    text = strip_invisible(text).strip()
    if not text.startswith(prefix):
        return None
    body = text[len(prefix):]
    if not body or body[0].isspace():
        return None
    name, *rest = body.split(maxsplit=1)
    return name.lower(), rest[0].strip() if rest else ""


@dataclass
class CommandContext:
    msg: ChatMessage
    name: str  # the name typed, lowercase (may be an alias)
    args: str
    prefix: str
    reply: Callable[..., None]  # reply(text, priority=False): threaded reply to msg
    say: Callable[..., None]  # say(text, priority=False, coalesce_key=None): plain message

    @property
    def argv(self) -> list[str]:
        return self.args.split()


Handler = Callable[[CommandContext], Awaitable[None]]


@dataclass(frozen=True)
class Command:
    name: str
    handler: Handler
    usage: str  # "{p}leaderboard [game] [limit]"; {p} becomes the prefix
    description: str
    group: str  # "Games", "Stats", "Fun", "Control", or "Info"
    aliases: tuple[str, ...] = ()
    controller_only: bool = False
    cooldown: bool = True  # per-user cooldown applies
    global_cooldown: bool = True  # chat-wide cooldown also applies (off for personal commands like ?cookie)
    listed: bool = True  # shown in the ?help overview


@dataclass
class CommandRegistry:
    prefix: str
    _commands: dict[str, Command] = field(default_factory=dict)  # name and aliases -> command
    _order: list[Command] = field(default_factory=list)

    def add(self, cmd: Command) -> None:
        if cmd.group not in GROUPS:
            raise ValueError(f"command {cmd.name!r} has unknown group {cmd.group!r} (known: {', '.join(GROUPS)})")
        for name in (cmd.name, *cmd.aliases):
            if name != name.lower() or not name:
                raise ValueError(f"command names must be lowercase and non-empty, got {name!r}")
            if name in self._commands:
                raise ValueError(f"command name or alias {name!r} is already registered")
        for name in (cmd.name, *cmd.aliases):
            self._commands[name] = cmd
        self._order.append(cmd)

    def get(self, name: str) -> Command | None:
        return self._commands.get(name.lower())

    def all(self) -> list[Command]:
        return list(self._order)

    def _fmt(self, text: str) -> str:
        return text.replace("{p}", self.prefix)

    def help_overview(self) -> str:
        parts = []
        for group in GROUP_ORDER:
            names = [f"{self.prefix}{c.name}" for c in self._order if c.group == group and c.listed]
            if names:
                parts.append(f"{group}: {' '.join(names)}")
        return truncate(" | ".join(parts) + f" · {self.prefix}help <command> for details")

    def help_for(self, name: str) -> str | None:
        cmd = self.get(name.removeprefix(self.prefix))
        if cmd is None:
            return None
        text = f"{self._fmt(cmd.usage)} · {self._fmt(cmd.description)}"
        if cmd.aliases:
            text += " (also " + ", ".join(f"{self.prefix}{a}" for a in cmd.aliases) + ")"
        if cmd.controller_only:
            text += " Mods only."
        return truncate(text)
