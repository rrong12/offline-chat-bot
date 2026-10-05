"""The interface every game implements. Games are pure: messages and time in, outcomes out."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Literal

from bot.assets import Assets
from bot.connectors.base import ChatMessage


@dataclass
class Outcome:
    messages: list[str] = field(default_factory=list)
    awards: dict[str, int] = field(default_factory=dict)  # user_id -> points
    winners: set[str] = field(default_factory=set)  # user_ids counted as winners
    finished: bool = False
    result: Literal["won", "timeout", "lost"] | None = None  # set when finished
    coalesce_key: str | None = None
    restart_timer: bool = False  # give the player a fresh time limit (streak games, after each right guess)


class Game(ABC):
    name: ClassVar[str]  # also the start command
    title: ClassVar[str]  # "Scramble"
    usage: ClassVar[str]  # "{p}scramble [category]"
    description: ClassVar[str]  # shown by ?help <game>; {p} becomes the prefix
    time_limit: int  # seconds; set on the class, and a game may change it for one round
    aliases: ClassVar[tuple[str, ...]] = ()  # other names for the start command
    # In-game commands: name -> (usage, description). Routed here only while this game runs.
    commands: ClassVar[dict[str, tuple[str, str]]] = {}
    # Optional second start option, such as Trivia's difficulty: "?trivia science hard".
    levels: ClassVar[tuple[str, ...]] = ()
    levels_label: ClassVar[str] = ""  # "difficulties", shown with the category list

    def __init__(
        self,
        category: str | None,
        rng: random.Random,
        assets: Assets,
        *,
        level: str | None = None,
        avoid: frozenset[str] = frozenset(),
    ) -> None:
        self.category = category
        self.rng = rng
        self.assets = assets
        self.level = level  # one of `levels`, or None to let the game pick
        self.avoid = avoid  # ids of questions this player saw recently
        self.item_id: str | None = None  # id of the question shown, so the manager can avoid repeats

    @classmethod
    def category_names(cls, assets: Assets) -> list[str]:
        """Categories this game can be started with. [] means the game has no categories."""
        return []

    @abstractmethod
    def start(self) -> str: ...

    def on_message(self, msg: ChatMessage, now: datetime) -> Outcome | None:
        """Plain chat while the game runs. None = not an attempt."""
        return None

    def on_command(self, name: str, args: str, msg: ChatMessage, now: datetime) -> Outcome | None:
        """One of this game's in-game commands. None = rejected / not an attempt."""
        return None

    def on_tick(self, elapsed: float) -> Outcome | None:
        return None

    @abstractmethod
    def on_timeout(self) -> Outcome: ...

    @abstractmethod
    def reveal(self) -> str:
        """The answer, for skip and stop messages."""
