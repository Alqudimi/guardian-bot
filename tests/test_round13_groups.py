from __future__ import annotations

import asyncio
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from config.settings import get_settings
from src.games.base import BaseGame
from src.games.manager import GameManager
from src.games.session import GameSessionManager
from src.utils.redis_client import get_redis


class Round13Game(BaseGame):
    async def start(self, update, context):
        self.status = "running"

    async def handle_callback(self, update, context):
        return None

    async def handle_message(self, update, context):
        return None

    async def stop(self):
        self.status = "ended"

    def get_game_state(self):
        return {"status": self.status, "players": self.players}

    def load_game_state(self, state):
        self.status = state.get("status", "waiting")
        self.players = state.get("players", {})


@pytest.mark.asyncio
async def test_concurrent_game_creation_is_serialized_by_redis_lock() -> None:
    game_name = "round13-race"
    chat_id = -100130013
    GameManager.register_game(game_name, Round13Game)
    GameSessionManager._active_sessions = OrderedDict()
    redis = await get_redis()
    settings = get_settings()
    session_key = f"{settings.redis_prefix}game_session:{chat_id}:{game_name}"
    lock_key = f"{settings.redis_prefix}game_session_lock:{chat_id}:{game_name}"
    await redis.delete(session_key, lock_key)

    results = await asyncio.gather(
        GameSessionManager.create_session(chat_id, game_name),
        GameSessionManager.create_session(chat_id, game_name),
        return_exceptions=True,
    )

    assert sum(isinstance(result, Round13Game) for result in results) == 1
    errors = [result for result in results if isinstance(result, ValueError)]
    assert len(errors) == 1
    assert await redis.exists(lock_key) == 0
    await GameSessionManager.delete_session(chat_id, game_name)


@pytest.mark.asyncio
async def test_group_smart_response_setting_blocks_automatic_quran_reply() -> None:
    from src.features import smart_detect

    update = SimpleNamespace(
        effective_message=SimpleNamespace(text="آية الكرسي"),
        effective_chat=SimpleNamespace(id=-100, type="supergroup"),
        effective_user=SimpleNamespace(id=7),
    )
    context = SimpleNamespace(bot=object())
    with (
        patch.object(smart_detect, "get_setting", new=AsyncMock(return_value="off")),
        patch.object(smart_detect, "create_background_task") as create_task,
    ):
        await smart_detect.handle_smart_message(update, context)

    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_group_smart_response_reserves_one_quran_reply_per_window() -> None:
    from src.features import smart_detect

    redis = SimpleNamespace(set=AsyncMock(side_effect=[True, False]))
    with patch.object(smart_detect, "get_redis", new=AsyncMock(return_value=redis)):
        assert await smart_detect._reserve_auto_response(-100, "quran") is True
        assert await smart_detect._reserve_auto_response(-100, "quran") is False

    assert redis.set.await_count == 2
    assert redis.set.await_args.kwargs == {"ex": 30, "nx": True}


@pytest.mark.asyncio
async def test_explicit_download_intent_bypasses_smart_response_toggle() -> None:
    from src.features import smart_detect

    update = SimpleNamespace(
        effective_message=SimpleNamespace(
            text="download https://youtu.be/abcdefghijk"
        ),
        effective_chat=SimpleNamespace(id=-100, type="supergroup"),
        effective_user=SimpleNamespace(id=7),
    )
    context = SimpleNamespace(bot=object())
    with (
        patch.object(smart_detect, "get_setting", new=AsyncMock(return_value="off")) as setting,
        patch.object(smart_detect, "_auto_download", new=AsyncMock()) as download,
    ):
        await smart_detect.handle_smart_message(update, context)

    download.assert_awaited_once()
    setting.assert_not_awaited()


@pytest.mark.asyncio
async def test_chameleon_private_topic_callback_targets_bound_group_session() -> None:
    from src.handlers.message_handler import handle_game_callback

    game = SimpleNamespace(status="running", handle_callback=AsyncMock())
    query = SimpleNamespace(
        data="game:chameleon:select_topic:Animals:-100",
        message=SimpleNamespace(chat_id=12345),
        answer=AsyncMock(),
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=12345, type="private"),
        effective_user=SimpleNamespace(id=7),
    )
    with patch(
        "src.handlers.message_handler.GameSessionManager.get_session",
        new=AsyncMock(return_value=game),
    ) as get_session, patch(
        "src.handlers.message_handler.GameSessionManager.update_session",
        new=AsyncMock(),
    ):
        await handle_game_callback(update, SimpleNamespace())

    get_session.assert_awaited_once_with(-100, "chameleon")
    game.handle_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_setsmart_validates_and_persists_group_setting() -> None:
    from src.handlers import admin_commands

    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        message=message,
        effective_message=message,
        effective_chat=SimpleNamespace(id=-100, type="supergroup"),
        effective_user=SimpleNamespace(id=7),
    )
    context = SimpleNamespace(args=["invalid"], bot=SimpleNamespace())
    with patch.object(admin_commands, "is_authorized_admin", new=AsyncMock(return_value=True)):
        await admin_commands.cmd_setsmart(update, context)
    assert "on|off" in message.reply_text.await_args.args[0]

    message.reply_text.reset_mock()
    context.args = ["off"]
    with (
        patch.object(admin_commands, "is_authorized_admin", new=AsyncMock(return_value=True)),
        patch.object(admin_commands, "set_setting", new=AsyncMock()) as set_setting,
    ):
        await admin_commands.cmd_setsmart(update, context)

    set_setting.assert_awaited_once_with(-100, "smart_responses", "off")
    assert "off" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_undo_reverses_latest_recorded_ban_only_after_telegram_success() -> None:
    from src.db.models import ActionType
    from src.handlers import admin_commands

    event = SimpleNamespace(action_taken=ActionType.BAN_TEMP)
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: event)
    )

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    message = SimpleNamespace(reply_text=AsyncMock())
    bot = SimpleNamespace(unban_chat_member=AsyncMock())
    update = SimpleNamespace(
        message=message,
        effective_message=message,
        effective_chat=SimpleNamespace(id=-100, type="supergroup"),
        effective_user=SimpleNamespace(id=7),
    )
    context = SimpleNamespace(args=["42"], bot=bot)
    with (
        patch.object(admin_commands, "is_authorized_admin", new=AsyncMock(return_value=True)),
        patch("src.db.session.db_session", return_value=SessionContext()),
        patch(
            "src.intelligence.adaptive_thresholds.record_false_positive",
            new=AsyncMock(),
        ) as false_positive,
        patch.object(admin_commands, "log_admin_command", new=AsyncMock()),
    ):
        await admin_commands.cmd_undo(update, context)

    bot.unban_chat_member.assert_awaited_once_with(
        chat_id=-100, user_id=42, only_if_banned=True
    )
    false_positive.assert_awaited_once_with(-100)
    assert "تم التراجع" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_leave_message_uses_group_setting_and_real_send() -> None:
    from src.management import welcome_manager

    message = SimpleNamespace(message_id=123)
    bot = SimpleNamespace(send_message=AsyncMock(return_value=message))
    with (
        patch.object(
            welcome_manager,
            "get_setting",
            new=AsyncMock(side_effect=["on", "وداعاً {name} في {group}" ]),
        ),
        patch.object(
            welcome_manager,
            "create_background_task",
            side_effect=lambda coroutine, name: coroutine.close(),
        ) as background_task,
    ):
        await welcome_manager.send_leave_message(
            bot,
            -100,
            42,
            "Ali",
            "ali_user",
            "Guardian Group",
        )

    bot.send_message.assert_awaited_once_with(
        chat_id=-100,
        text="وداعاً Ali في Guardian Group",
        parse_mode="Markdown",
    )
    background_task.assert_called_once()


@pytest.mark.asyncio
async def test_member_update_routes_real_departure_to_leave_message() -> None:
    from src.handlers import message_handler

    user = SimpleNamespace(id=42, first_name="Ali", username="ali_user", is_bot=False)
    update = SimpleNamespace(
        chat_member=SimpleNamespace(
            chat=SimpleNamespace(id=-100, title="Guardian Group"),
            old_chat_member=SimpleNamespace(status="member", user=user),
            new_chat_member=SimpleNamespace(status="left", user=user),
        )
    )
    leave = AsyncMock()
    context = SimpleNamespace(bot=object())
    with patch("src.management.welcome_manager.send_leave_message", new=leave):
        await message_handler.handle_member_update(update, context)

    leave.assert_awaited_once_with(
        context.bot,
        -100,
        42,
        "Ali",
        "ali_user",
        "Guardian Group",
    )


@pytest.mark.asyncio
async def test_game_scores_persist_once_and_survive_session_cleanup() -> None:
    game = Round13Game(chat_id=-100130014, game_id="round13-score")
    game.players = {
        101: {"score": 3},
        202: {"score": 1},
    }
    manager = GameSessionManager
    redis = await get_redis()
    score_key = await manager._score_key(game.chat_id, game.game_id)
    marker_key = await manager._score_marker_key(game.chat_id, game.game_id)
    await redis.delete(score_key, marker_key)

    assert await manager.persist_scores(game) is True
    assert await manager.persist_scores(game) is False
    assert await manager.get_scoreboard(game.chat_id, game.game_id) == [(101, 3.0), (202, 1.0)]

    await redis.delete(score_key, marker_key)
