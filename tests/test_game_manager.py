import pytest

from src.games.base import BaseGame
from src.games.manager import GameManager


class MockGame(BaseGame):
    async def start(self, update, context): pass
    async def handle_callback(self, update, context): pass
    async def handle_message(self, update, context): pass
    async def stop(self): pass
    def get_game_state(self): return {}
    def load_game_state(self, state): pass

def test_register_and_get_game():
    GameManager._games = {} # Reset for test
    GameManager.register_game("mock", MockGame)
    assert GameManager.get_game_class("mock") == MockGame
    assert "mock" in GameManager.list_games()

def test_get_nonexistent_game():
    GameManager._games = {}
    with pytest.raises(ValueError):
        GameManager.get_game_class("nonexistent")

def test_duplicate_registration():
    GameManager._games = {}
    GameManager.register_game("mock", MockGame)
    with pytest.raises(ValueError):
        GameManager.register_game("mock", MockGame)
