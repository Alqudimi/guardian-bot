from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.features.register import register_game_features
from src.games.base import BaseGame
from src.games.manager import GameManager
from src.games.plugins.text_based.chameleon import ChameleonGame
from src.games.plugins.text_based.mafia import MafiaGame


@dataclass
class FakeUser:
    id: int
    full_name: str


@dataclass
class FakeChat:
    id: int


@dataclass
class FakeBot:
    sent: list[dict[str, Any]] = field(default_factory=list)

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
        self.sent.append({"chat_id": chat_id, "text": text, **kwargs})


@dataclass
class FakeMessage:
    text: str = ""
    bot: FakeBot | None = None
    replies: list[str] = field(default_factory=list)

    async def reply_text(self, text: str, **kwargs: Any) -> None:
        self.replies.append(text)

    def get_bot(self) -> FakeBot:
        assert self.bot is not None
        return self.bot


@dataclass
class FakeQuery:
    data: str
    message: FakeMessage
    answers: list[str] = field(default_factory=list)

    async def answer(self, text: str = "", **kwargs: Any) -> None:
        self.answers.append(text)


@dataclass
class FakeUpdate:
    user: FakeUser
    chat_id: int
    bot: FakeBot
    text: str = ""
    query_data: str | None = None

    def __post_init__(self) -> None:
        self.effective_user = self.user
        self.effective_chat = FakeChat(self.chat_id)
        self.message = FakeMessage(self.text, self.bot)
        self.callback_query = (
            FakeQuery(self.query_data, self.message) if self.query_data else None
        )


@dataclass
class FakeContext:
    bot: FakeBot


@pytest.fixture(autouse=True)
def reset_game_registry() -> None:
    GameManager._games = {}


def callback_update(user_id: int, chat_id: int, bot: FakeBot, data: str) -> FakeUpdate:
    return FakeUpdate(FakeUser(user_id, f"Player {user_id}"), chat_id, bot, query_data=data)


def test_only_bot_owned_games_are_registered() -> None:
    register_game_features(None)
    assert set(GameManager.list_games()) == {"mafia", "chameleon"}
    for game_name, game_class in GameManager.list_games().items():
        assert issubclass(game_class, BaseGame)
        assert game_class.__module__.startswith("src.games.plugins")
        assert not hasattr(game_class, "web_url")
        assert game_name in {"mafia", "chameleon"}


@pytest.mark.asyncio
async def test_mafia_runs_real_registration_night_and_day_flow() -> None:
    bot = FakeBot()
    context = FakeContext(bot)
    game = MafiaGame(chat_id=100, game_id="mafia")
    await game.start(FakeUpdate(FakeUser(1, "Player 1"), 100, bot), context)

    for player_id in (2, 3, 4):
        await game.handle_callback(
            callback_update(player_id, 100, bot, "game:mafia:join"), context
        )
    await game.handle_message(
        FakeUpdate(FakeUser(1, "Player 1"), 100, bot, text="/mafia_start"), context
    )
    assert game.game_phase == "night"
    assert len(game.players) == 4
    assert all(player["role"] != "unassigned" for player in game.players.values())

    mafia_id = game.mafia_ids[0]
    target_id = next(
        pid for pid in game.players if pid not in game.mafia_ids and pid != game.doctor_id
    )
    await game.handle_callback(
        callback_update(mafia_id, 100, bot, f"game:mafia:night:kill:{target_id}:100"),
        context,
    )
    assert game.doctor_id is not None
    await game.handle_callback(
        callback_update(game.doctor_id, 100, bot, f"game:mafia:night:protect:{target_id}:100"),
        context,
    )
    assert game.game_phase == "day"

    for voter_id in list(game.players):
        if game.players[voter_id]["is_alive"]:
            vote_target = next(pid for pid in game.players if pid != voter_id and game.players[pid]["is_alive"])
            await game.handle_callback(
                callback_update(voter_id, 100, bot, f"game:mafia:vote:{vote_target}:100"),
                context,
            )
    assert game.game_phase in {"night", "ended"}
    assert any("Mafia" in item["text"] or "Day" in item["text"] for item in bot.sent)


@pytest.mark.asyncio
async def test_chameleon_runs_real_topic_clue_and_vote_flow() -> None:
    bot = FakeBot()
    context = FakeContext(bot)
    game = ChameleonGame(chat_id=200, game_id="chameleon")
    await game.start(FakeUpdate(FakeUser(1, "Player 1"), 200, bot), context)
    for player_id in (2, 3):
        await game.handle_callback(
            callback_update(player_id, 200, bot, "game:chameleon:join"), context
        )

    await game.handle_message(
        FakeUpdate(FakeUser(1, "Player 1"), 200, bot, text="/cham_start"), context
    )
    assert game.game_phase == "topic_selection"
    selector_id = game.turn_order[0]
    await game.handle_callback(
        callback_update(selector_id, 200, bot, "game:chameleon:select_topic:Animals:200"),
        context,
    )
    assert game.game_phase == "clue_giving"
    assert game.current_word in {"Dog", "Cat", "Elephant", "Lion", "Giraffe", "Monkey", "Tiger", "Rabbit"}

    for player_id in game.turn_order:
        await game.handle_message(
            FakeUpdate(FakeUser(player_id, f"Player {player_id}"), 200, bot, text="A useful clue"),
            context,
        )
    assert game.game_phase == "voting"

    for voter_id in game.players:
        target_id = next(pid for pid in game.players if pid != voter_id)
        await game.handle_callback(
            callback_update(voter_id, 200, bot, f"game:chameleon:vote:{target_id}:200"),
            context,
        )
    assert game.status == "ended"
    assert game.game_phase == "ended"
    assert game.current_word is None


def test_game_state_roundtrip_preserves_game_owned_state() -> None:
    mafia = MafiaGame(1, "mafia")
    mafia.host_id = 10
    mafia.players = {10: {"name": "Host", "role": "villager", "is_alive": True}}
    mafia.game_phase = "day"
    mafia.votes = {10: 11}
    state = mafia.get_game_state()
    restored_mafia = MafiaGame(1, "mafia")
    restored_mafia.load_game_state(state)
    assert restored_mafia.host_id == 10
    assert restored_mafia.game_phase == "day"
    assert restored_mafia.votes == {10: 11}

    chameleon = ChameleonGame(2, "chameleon")
    chameleon.host_id = 20
    chameleon.players = {20: {"name": "Host", "score": 2}}
    chameleon.turn_order = [20]
    chameleon.current_turn_index = 1
    state = chameleon.get_game_state()
    restored_chameleon = ChameleonGame(2, "chameleon")
    restored_chameleon.load_game_state(state)
    assert restored_chameleon.host_id == 20
    assert restored_chameleon.turn_order == [20]
    assert restored_chameleon.current_turn_index == 1


@pytest.mark.asyncio
async def test_bot_owned_game_session_reloads_from_real_redis() -> None:
    from collections import OrderedDict

    from src.games.session import GameSessionManager

    GameManager.register_game("mafia", MafiaGame)
    game = await GameSessionManager.create_session(300, "mafia")
    game.status = "running"
    game.host_id = 77
    game.players = {77: {"name": "Host", "role": "villager", "is_alive": True}}
    await GameSessionManager.update_session(game)
    GameSessionManager._active_sessions = OrderedDict()

    loaded = await GameSessionManager.get_session(300, "mafia")
    assert isinstance(loaded, MafiaGame)
    assert loaded.host_id == 77
    active = await GameSessionManager.get_active_game_for_chat(300)
    assert active is not None
    assert active.game_id == "mafia"
    await GameSessionManager.delete_session(300, "mafia")


@pytest.mark.asyncio
async def test_explicit_game_commands_select_the_registered_games() -> None:
    from unittest.mock import AsyncMock, patch

    from src.handlers.message_handler import cmd_cham_start, cmd_mafia_start

    update = object()
    context = object()
    with patch("src.handlers.message_handler._start_game", new_callable=AsyncMock) as start_game:
        await cmd_mafia_start(update, context)
        await cmd_cham_start(update, context)

    assert [call.args[2] for call in start_game.await_args_list] == ["mafia", "chameleon"]
