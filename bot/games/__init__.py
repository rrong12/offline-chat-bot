"""All game classes, by name. config.toml's [games] enabled picks which ones run."""

from bot.games.base import Game
from bot.games.hangman import Hangman
from bot.games.higherlower import HigherLower
from bot.games.riddle import Riddle
from bot.games.scramble import Scramble
from bot.games.trivia import Trivia

ALL_GAMES: dict[str, type[Game]] = {cls.name: cls for cls in (Scramble, Hangman, Trivia, Riddle, HigherLower)}
