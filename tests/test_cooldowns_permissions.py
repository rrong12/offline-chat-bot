from bot.clock import FakeClock
from bot.cooldowns import Cooldowns
from bot.permissions import is_controller
from tests.helpers import make_msg


def test_user_cooldown_blocks_same_user_only(clock: FakeClock):
    cd = Cooldowns(clock)
    assert cd.check_command("8ball", "u1", 10, 0)
    assert not cd.check_command("8ball", "u1", 10, 0)
    assert cd.check_command("8ball", "u2", 10, 0)
    clock.advance(10)
    assert cd.check_command("8ball", "u1", 10, 0)


def test_global_cooldown_blocks_everyone(clock: FakeClock):
    cd = Cooldowns(clock)
    assert cd.check_command("dadjoke", "u1", 10, 5)
    assert not cd.check_command("dadjoke", "u2", 10, 5)
    clock.advance(5)
    assert cd.check_command("dadjoke", "u2", 10, 5)


def test_blocked_attempt_does_not_restart_cooldown(clock: FakeClock):
    cd = Cooldowns(clock)
    cd.check_command("fact", "u1", 10, 0)
    clock.advance(9)
    assert not cd.check_command("fact", "u1", 10, 0)
    clock.advance(1)
    assert cd.check_command("fact", "u1", 10, 0)


def test_remaining(clock: FakeClock):
    cd = Cooldowns(clock)
    cd.trigger("game", 30)
    clock.advance(12)
    assert cd.remaining("game") == 18


def test_is_controller():
    owners = {"id-robert"}
    assert is_controller(make_msg("x", broadcaster=True), owners)
    assert is_controller(make_msg("x", mod=True), owners)
    assert is_controller(make_msg("x", "robert"), owners)
    assert not is_controller(make_msg("x", "random"), owners)
