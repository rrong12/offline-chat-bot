import json
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
    (root / "blocked_rot13.txt").write_text("# test fragment: 'gat'\ntng\n", encoding="utf-8")
    (root / "fortunes.txt").write_text("Good things are coming.\n", encoding="utf-8")
    for name in ("catfacts", "dogfacts", "facts", "dadjokes"):
        (root / f"fallback_{name}.txt").write_text(f"fallback {name} line\n", encoding="utf-8")
    trivia = [
        {"id": "e1", "category": "science", "difficulty": "easy", "question": "What gas do plants absorb?",
         "answer": "Carbon dioxide", "wrong": ["Oxygen", "Nitrogen", "Helium"]},
        {"id": "m1", "category": "science", "difficulty": "medium", "question": "Which planet is the largest?",
         "answer": "Jupiter"},
        {"id": "h1", "category": "history", "difficulty": "hard", "question": "In what year did WW2 end?",
         "answer": "1945"},
        {"id": "h2", "category": "history", "difficulty": "hard", "question": "Who painted the Mona Lisa?",
         "answer": "Leonardo da Vinci"},
    ]
    (root / "trivia.json").write_text(json.dumps({"questions": trivia}), encoding="utf-8")
    riddles = [
        {"riddle": "What has hands but can't clap?", "answers": ["clock", "watch"],
         "clue": "You probably check me several times a day."},
        {"riddle": "What gets wetter the more it dries?", "answers": ["towel"], "clue": "Find me in a bathroom."},
    ]
    (root / "riddles.json").write_text(json.dumps(riddles), encoding="utf-8")
    terms = [{"name": "Minecraft", "views": 241_000}, {"name": "Pizza", "views": 55_000},
             {"name": "Axolotl", "views": 30_000}, {"name": "YouTube", "views": 1_200_000}]
    (root / "higherlower.json").write_text(json.dumps({"terms": terms}), encoding="utf-8")
    return root


@pytest.fixture
def assets(content_dir: Path) -> Assets:
    return Assets(content_dir)
