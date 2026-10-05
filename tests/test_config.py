from pathlib import Path

import pytest

from bot.config import ConfigError, load_config

ENV = {"TWITCH_CLIENT_ID": "cid", "TWITCH_CLIENT_SECRET": "secret", "BOT_ID": "123", "OWNER_IDS": "1, 2,"}


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_repo_config_file_is_valid():
    cfg = load_config(Path(__file__).parent.parent / "config.toml", ENV)
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


def test_bot_id_must_be_numeric(tmp_path):
    with pytest.raises(ConfigError, match="BOT_ID"):
        load_config(write(tmp_path, 'channel = "ok_name"\n'), {**ENV, "BOT_ID": "mybot"})
