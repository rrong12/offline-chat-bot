from pathlib import Path

import pytest

from bot.assets import Assets
from bot.clock import FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def content_dir(tmp_path: Path) -> Path:
    """A tiny content folder so game tests don't depend on the real word lists."""
    root = tmp_path / "content"
    (root / "words").mkdir(parents=True)
    (root / "words" / "animals.txt").write_text("# comment\nalligator\ncat\nsea lion\n", encoding="utf-8")
    (root / "words" / "food.txt").write_text("ramen\nhot cheetos\n", encoding="utf-8")
    (root / "8ball.txt").write_text("Yes.\nNo.\n", encoding="utf-8")
    (root / "fortunes.txt").write_text("Good things are coming.\n", encoding="utf-8")
    for name in ("catfacts", "dogfacts", "facts", "dadjokes"):
        (root / f"fallback_{name}.txt").write_text(f"fallback {name} line\n", encoding="utf-8")
    return root


@pytest.fixture
def assets(content_dir: Path) -> Assets:
    return Assets(content_dir)
