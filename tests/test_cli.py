"""Runs the real `python -m bot` process, the way a person would."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text('channel = "test_channel"\n[outbox]\nrate_per_second = 3\nburst = 50\n', encoding="utf-8")
    return path


def run_bot(
    *args: str, stdin: str = "", env_file: str | None = None, tmp_path: Path, extra_env: dict | None = None
) -> subprocess.CompletedProcess:
    if env_file is not None:
        (tmp_path / ".env").write_text(env_file, encoding="utf-8")
    clean_env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), **(extra_env or {})}
    return subprocess.run(
        [sys.executable, "-m", "bot", *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=20,
        cwd=ROOT,
        env=clean_env,
    )


def test_console_mode_plays_and_shuts_down(tmp_path):
    config = write_config(tmp_path)
    result = run_bot(
        "console", "--config", str(config),
        stdin="alice: ?coinflip\nbob: ?help\n@mod: ?bot shutdown\nalice: typed after shutdown\n",
        tmp_path=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "bot → alice: 🪙" in result.stdout
    assert "bot → bob: Games: ?scramble ?hangman ?skip" in result.stdout
    assert "bot → mod: Shutting down (requested by mod)." in result.stdout
    assert (tmp_path / "data" / "console" / "bot.db").exists()
    assert list((tmp_path / "data" / "console" / "logs").glob("activity-*.jsonl"))


def test_run_without_secrets_exits_2(tmp_path):
    result = run_bot("--config", str(write_config(tmp_path)), env_file="", tmp_path=tmp_path)
    assert result.returncode == 2
    assert "TWITCH_CLIENT_ID is missing" in result.stderr


def test_auth_without_client_credentials_exits_2(tmp_path):
    result = run_bot("auth", "--config", str(write_config(tmp_path)), env_file="", tmp_path=tmp_path)
    assert result.returncode == 2
    assert "TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET" in result.stderr


def test_database_newer_than_code_exits_2(tmp_path):
    import sqlite3

    db = tmp_path / "data" / "console" / "bot.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version VALUES (99)")
    result = run_bot("console", "--config", str(write_config(tmp_path)), tmp_path=tmp_path)
    assert result.returncode == 2
    assert "newer than this code" in result.stderr


SECRETS = "TWITCH_CLIENT_ID=cid\nTWITCH_CLIENT_SECRET=secret\nBOT_ID=123\n"


def test_env_file_is_read_and_real_environment_wins(tmp_path):
    config = str(write_config(tmp_path))
    from_file = run_bot("--config", config, env_file=SECRETS + "OWNER_IDS=notnum\n", tmp_path=tmp_path)
    assert from_file.returncode == 2 and "got notnum" in from_file.stderr
    from_env = run_bot("--config", config, tmp_path=tmp_path, extra_env={"OWNER_IDS": "fromenv"})
    assert from_env.returncode == 2 and "got fromenv" in from_env.stderr
    empty_env = run_bot("--config", config, tmp_path=tmp_path, extra_env={"OWNER_IDS": ""})
    assert "got notnum" in empty_env.stderr  # an empty variable doesn't override .env


def test_corrupt_database_exits_2(tmp_path):
    db = tmp_path / "data" / "console" / "bot.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"this is not a sqlite database" * 100)
    result = run_bot("console", "--config", str(write_config(tmp_path)), tmp_path=tmp_path)
    assert result.returncode == 2
    assert "Setup error" in result.stderr


def test_sigterm_stops_cleanly(tmp_path):
    import json
    import select
    import signal
    import time

    config = write_config(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "bot", "console", "--config", str(config)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    try:
        ready, _, _ = select.select([proc.stdout], [], [], 10)  # don't hang if the bot never starts
        assert ready, "the bot did not start within 10 s"
        assert proc.stdout.readline().startswith("Console mode.")  # banner: the bot is running
        time.sleep(0.2)
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 0
    finally:
        proc.kill()
    logs = list((tmp_path / "data" / "console" / "logs").glob("activity-*.jsonl"))
    last = json.loads(logs[0].read_text().splitlines()[-1])
    assert last["event"] == "shutdown" and last["by"] == "signal"


def test_bad_config_exits_2(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('channel = "has spaces"\n', encoding="utf-8")
    result = run_bot("console", "--config", str(path), tmp_path=tmp_path)
    assert result.returncode == 2
    assert "channel must be a Twitch username" in result.stderr
