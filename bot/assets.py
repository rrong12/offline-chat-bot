"""Loads the bundled content in bot/content/: text files (one item per line) and JSON files."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(__file__).parent / "content"


class Assets:
    def __init__(self, root: Path = DEFAULT_ROOT) -> None:
        self.root = root

    def lines(self, name: str) -> list[str]:
        """Non-blank, non-comment lines of content/<name>.txt."""
        return list(_read(self.root / f"{name}.txt"))

    def words(self, category: str) -> list[str]:
        return list(_read(self.root / "words" / f"{category}.txt"))

    def categories(self) -> list[str]:
        return sorted(p.stem for p in (self.root / "words").glob("*.txt"))

    def json(self, name: str) -> Any:
        """Parsed content/<name>.json. Cached and shared: callers must not modify it."""
        return _read_json(self.root / f"{name}.json")


@cache  # content is bundled and read-only, so each file is read once per process
def _read(path: Path) -> tuple[str, ...]:
    text = path.read_text(encoding="utf-8")
    return tuple(
        line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    )


@cache
def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
