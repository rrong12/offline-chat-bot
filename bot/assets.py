"""Loads the bundled text files in bot/content/ (one item per line)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

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


@cache
def _read(path: Path) -> tuple[str, ...]:
    text = path.read_text(encoding="utf-8")
    return tuple(
        line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    )
