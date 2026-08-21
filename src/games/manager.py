
from typing import ClassVar

from src.games.base import BaseGame


class GameManager:
    _games: ClassVar[dict[str, type[BaseGame]]] = {}

    @classmethod
    def register_game(cls, name: str, game_class: type[BaseGame]):
        if name in cls._games:
            raise ValueError(f"Game '{name}' is already registered.")
        cls._games[name] = game_class

    @classmethod
    def get_game_class(cls, name: str) -> type[BaseGame]:
        game_class = cls._games.get(name)
        if not game_class:
            raise ValueError(f"Game '{name}' not found.")
        return game_class

    @classmethod
    def list_games(cls) -> dict[str, type[BaseGame]]:
        return cls._games
