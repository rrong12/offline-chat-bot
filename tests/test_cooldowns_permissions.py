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


def test_ready(clock: FakeClock):
    cd = Cooldowns(clock)
    assert cd.ready("k")
    cd.trigger("k", 5)
    assert not cd.ready("k")
    clock.advance(5)
    assert cd.ready("k")


def test_prune_drops_expired_entries(clock: FakeClock, monkeypatch):
    monkeypatch.setattr("bot.cooldowns._PRUNE_AT", 10)
    cd = Cooldowns(clock)
    for i in range(10):
        cd.trigger(("old", i), 1)
    clock.advance(2)  # all ten have expired
    cd.trigger("new", 5)  # reaching the threshold prunes first
    assert len(cd._until) == 1


def test_prune_backs_off_when_entries_are_still_active(clock: FakeClock, monkeypatch):
    monkeypatch.setattr("bot.cooldowns._PRUNE_AT", 10)
    cd = Cooldowns(clock)
    for i in range(10):
        cd.trigger(("live", i), 60)
    cd.trigger("one more", 60)  # prune finds nothing expired
    assert cd._prune_at == 20  # next scan waits until the dict doubles
    for i in range(8):
        cd.trigger(("more", i), 60)
    assert len(cd._until) == 19  # no rescans in between, nothing lost


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
