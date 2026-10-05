import pytest

from bot.commands import Command, CommandRegistry, parse_command


async def noop(ctx):
    pass


def cmd(name: str, group: str = "Fun", **kw) -> Command:
    return Command(name, noop, f"{{p}}{name}", f"Does {name}.", group, **kw)


def test_parse_command_basic():
    assert parse_command("?Scramble Animals", "?") == ("scramble", "Animals")
    assert parse_command("?help", "?") == ("help", "")


def test_parse_command_rejects_non_commands():
    assert parse_command("hello ?scramble", "?") is None
    assert parse_command("?", "?") is None
    assert parse_command("? scramble", "?") is None


def test_parse_command_strips_invisible_and_extra_spaces():
    assert parse_command("  ?cookie   give  bob \U000e0000", "?") == ("cookie", "give  bob")


def test_parse_command_custom_prefix():
    assert parse_command("!scramble", "!") == ("scramble", "")
    assert parse_command("!scramble", "?") is None


def test_registry_get_by_name_or_alias():
    reg = CommandRegistry("?")
    reg.add(cmd("help", group="Info", aliases=("commands",)))
    assert reg.get("commands").name == "help"
    assert reg.get("HELP").name == "help"
    assert reg.get("nope") is None


def test_command_cooldown_flags_default_on():
    c = cmd("fact")
    assert c.cooldown and c.global_cooldown


def test_registry_rejects_duplicates():
    reg = CommandRegistry("?")
    reg.add(cmd("fact"))
    with pytest.raises(ValueError):
        reg.add(cmd("other", aliases=("fact",)))


def test_help_overview_groups_in_order_and_skips_unlisted():
    reg = CommandRegistry("?")
    reg.add(cmd("8ball"))
    reg.add(cmd("scramble", group="Games"))
    reg.add(cmd("leaderboard", group="Stats"))
    reg.add(cmd("bot", group="Control", controller_only=True))
    reg.add(cmd("g", group="Games", listed=False))
    assert reg.help_overview() == (
        "Games: ?scramble | Stats: ?leaderboard | Fun: ?8ball · ?help <command> for details"
    )


def test_help_for_formats_usage_aliases_and_mod_note():
    reg = CommandRegistry("!")
    reg.add(cmd("help", group="Info", aliases=("commands",)))
    reg.add(cmd("bot", group="Control", controller_only=True))
    assert reg.help_for("help") == "!help · Does help. (also !commands)"
    assert reg.help_for("!bot") == "!bot · Does bot. Mods only."
    assert reg.help_for("missing") is None
