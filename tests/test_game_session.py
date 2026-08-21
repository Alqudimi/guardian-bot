from unittest.mock import AsyncMock, patch

import pytest

from src.games.base import BaseGame
from src.games.manager import GameManager
from src.games.session import GameSessionManager


class MockGame(BaseGame):
    async def start(self, update, context): pass
    async def handle_callback(self, update, context): pass
    async def handle_message(self, update, context): pass
    async def stop(self): pass
    def get_game_state(self): return {"status": self.status}
    def load_game_state(self, state): self.status = state["status"]

@pytest.mark.asyncio
async def test_create_session():
    GameManager._games = {}
    GameManager.register_game("mock", MockGame)
    GameSessionManager._active_sessions = {}
    
    with patch("src.games.session.get_redis", return_value=AsyncMock()):
        game = await GameSessionManager.create_session(123, "mock")
        assert isinstance(game, MockGame)
        assert game.chat_id == 123
        assert len(GameSessionManager._active_sessions) == 1

from collections import OrderedDict


@pytest.mark.asyncio
async def test_get_session_memory():
    GameManager._games = {}
    GameManager.register_game("mock", MockGame)
    GameSessionManager._active_sessions = OrderedDict()
    
    game_instance = MockGame(123, "mock")
    session_key = "game_session:123:mock"
    GameSessionManager._active_sessions[session_key] = game_instance
    
    game = await GameSessionManager.get_session(123, "mock")
    assert game == game_instance

@pytest.mark.asyncio
async def test_delete_session():
    GameSessionManager._active_sessions = OrderedDict({"game_session:123:mock": MockGame(123, "mock")})
    
    with patch("src.games.session.get_redis", return_value=AsyncMock()):
        await GameSessionManager.delete_session(123, "mock")
        assert len(GameSessionManager._active_sessions) == 0
