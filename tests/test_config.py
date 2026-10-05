from pathlib import Path

import pytest

from bot.config import ConfigError, load_config

ENV = {"TWITCH_CLIENT_ID": "cid", "TWITCH_CLIENT_SECRET": "secret", "BOT_ID": "123", "OWNER_IDS": "1, 2,"}


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_repo_config_file_is_valid_once_a_channel_is_set(tmp_path):
    shipped = (Path(__file__).parent.parent / "config.toml").read_text(encoding="utf-8")
    with pytest.raises(ConfigError, match="set channel"):
        load_config(write(tmp_path, shipped), ENV)  # the placeholder must be replaced
    load_config(write(tmp_path, shipped), {}, require_twitch=False)  # console mode works before it's set
    cfg = load_config(write(tmp_path, shipped.replace('"your_channel"', '"real_channel"')), ENV)
    assert cfg.prefix == "?" and cfg.enabled_games == ("scramble", "hangman")


def test_defaults_and_env(tmp_path):
    cfg = load_config(write(tmp_path, 'channel = "Robert_Channel"\n'), ENV)
    assert cfg.channel == "robert_channel"
    assert cfg.owner_ids == frozenset({"1", "2"})
    assert (cfg.user_cooldown, cfg.global_cooldown) == (10, 5)
    assert (cfg.max_games, cfg.game_cooldown, cfg.busy_queue) == (25, 10, 10)
    assert (cfg.outbox_rate, cfg.outbox_burst, cfg.outbox_max_queue) == (2, 3, 30)
    assert cfg.data_dir == tmp_path / "data"


@pytest.mark.parametrize(
    "toml, message",
    [
        ('channel = "no spaces allowed"', "channel"),
        ('channel = "ok_name"\nprefix = ""', "prefix"),
        ('channel = "ok_name"\n[cooldowns]\nuser_seconds = -1', "cooldowns.user_seconds"),
        ('channel = "ok_name"\n[games]\nmax_running = 0', "games.max_running"),
        ('channel = "ok_name"\n[games]\nenabled = ["chess"]', "chess"),
        ('channel = "ok_name"\n[outbox]\nburst = 1.5', "outbox.burst"),
        ("channel = ", "not valid TOML"),
        ('channel = "ok_name"\n[games]\nmax_runing = 5', "unknown setting games.max_runing"),
        ('channel = "ok_name"\ngames = "oops"', "games must be a \\[games\\] section"),
        ('channel = "ok_name"\ncolour = "blue"', "unknown setting 'colour'"),
        ('channel = "ok_name"\n[outbox]\nrate_per_second = 1000', "outbox.rate_per_second"),
        ('channel = "ok_name"\n[outbox]\nrate_per_second = nan', "outbox.rate_per_second"),
        ('channel = "ok_name"\n[outbox]\nrate_per_second = inf', "outbox.rate_per_second"),
        ('channel = "ok_name"\nprefix = "/"', "can't start with"),
        ('channel = "ok_name"\nprefix = ".b"', "can't start with"),
        ('channel = "ok_name"\n[games]\nenabled = []', "at least one game"),
        ("channel = 123", "channel must be a Twitch username"),
        ('channel = "ok_name"\n[games]\nbusy_queue = 40', "can't be larger than outbox.max_queue"),
    ],
)
def test_invalid_values_name_the_key(tmp_path, toml, message):
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, toml), ENV)


def test_missing_secrets_fail_only_when_twitch_required(tmp_path):
    path = write(tmp_path, 'channel = "ok_name"\n')
    with pytest.raises(ConfigError, match="TWITCH_CLIENT_ID"):
        load_config(path, {})
    assert load_config(path, {}, require_twitch=False).bot_id == "console-bot"


def test_owner_ids_must_be_numeric_for_twitch_but_not_console(tmp_path):
    path = write(tmp_path, 'channel = "ok_name"\n')
    with pytest.raises(ConfigError, match="OWNER_IDS"):
        load_config(path, {**ENV, "OWNER_IDS": "123,robert"})
    assert load_config(path, {"OWNER_IDS": "console-robert"}, require_twitch=False).owner_ids == {"console-robert"}


def test_duplicate_games_are_dropped(tmp_path):
    cfg = load_config(write(tmp_path, 'channel = "ok_name"\n[games]\nenabled = ["scramble", "scramble"]'), ENV)
    assert cfg.enabled_games == ("scramble",)


def test_bot_id_must_be_numeric(tmp_path):
    with pytest.raises(ConfigError, match="BOT_ID"):
        load_config(write(tmp_path, 'channel = "ok_name"\n'), {**ENV, "BOT_ID": "mybot"})
