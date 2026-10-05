"""All game classes, by name. config.toml's [games] enabled picks which ones run."""

from bot.games.base import Game
from bot.games.hangman import Hangman
from bot.games.scramble import Scramble

ALL_GAMES: dict[str, type[Game]] = {cls.name: cls for cls in (Scramble, Hangman)}
