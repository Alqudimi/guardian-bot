from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from telegram.error import TelegramError

from config.settings import get_settings
from src.utils.redis_client import get_redis


async def _cleanup_raid_keys(chat_id: int) -> None:
    redis = await get_redis()
    prefix = get_settings().redis_prefix
    await redis.delete(
        f"{prefix}joins:{chat_id}",
        f"{prefix}lockdown:{chat_id}",
        f"{prefix}raid_activation:{chat_id}",
    )


def _raid_settings() -> SimpleNamespace:
    return SimpleNamespace(
        redis_prefix=get_settings().redis_prefix,
        raid_join_window_seconds=60,
        raid_join_threshold=1,
        telegram_admin_ids=[],
    )


@pytest.mark.asyncio
async def test_concurrent_joins_activate_lockdown_once() -> None:
    from src.pipeline import raid_detector

    chat_id = -180001
    await _cleanup_raid_keys(chat_id)
    try:
        with (
            patch.object(raid_detector, "get_setting", new=AsyncMock(return_value="on")),
            patch.object(raid_detector, "get_settings", return_value=_raid_settings()),
            patch.object(
                raid_detector,
                "_activate_lockdown",
                new=AsyncMock(return_value=True),
            ) as activate,
            patch.object(
                raid_detector,
                "_persist_raid_db_state",
                new=AsyncMock(return_value=True),
            ),
        ):
            results = await asyncio.gather(
                *(raid_detector.check_raid(SimpleNamespace(), chat_id, user_id) for user_id in range(5))
            )

        assert sum(results) == 1
        activate.assert_awaited_once()
    finally:
        await _cleanup_raid_keys(chat_id)


@pytest.mark.asyncio
async def test_raid_telegram_failure_releases_reservation_without_active_marker() -> None:
    from src.pipeline import raid_detector

    join_pipe = MagicMock()
    join_pipe.execute = AsyncMock(return_value=[0, 1, 1, None])
    redis = MagicMock()
    redis.pipeline.return_value = join_pipe
    redis.exists = AsyncMock(return_value=False)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    settings = SimpleNamespace(
        redis_prefix="test:",
        raid_join_window_seconds=60,
        raid_join_threshold=1,
    )

    with (
        patch.object(raid_detector, "get_setting", new=AsyncMock(return_value="on")),
        patch.object(raid_detector, "get_redis", new=AsyncMock(return_value=redis)),
        patch.object(raid_detector, "get_settings", return_value=settings),
        patch.object(
            raid_detector,
            "_activate_lockdown",
            new=AsyncMock(return_value=False),
        ) as activate,
    ):
        result = await raid_detector.check_raid(SimpleNamespace(), -100, 42)

    assert result is False
    activate.assert_awaited_once()
    redis.set.assert_awaited_once()
    redis.delete.assert_awaited_once_with("test:raid_activation:-100")
    assert join_pipe.execute.await_count == 1


@pytest.mark.asyncio
async def test_raid_state_commit_failure_does_not_report_lockdown_success() -> None:
    from src.pipeline import raid_detector

    join_pipe = MagicMock()
    join_pipe.execute = AsyncMock(return_value=[0, 1, 1, None])
    state_pipe = MagicMock()
    state_pipe.execute = AsyncMock(side_effect=RedisConnectionError("redis unavailable"))
    redis = MagicMock()
    redis.pipeline.side_effect = [join_pipe, state_pipe]
    redis.exists = AsyncMock(return_value=False)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    settings = SimpleNamespace(
        redis_prefix="test:",
        raid_join_window_seconds=60,
        raid_join_threshold=1,
    )

    with (
        patch.object(raid_detector, "get_setting", new=AsyncMock(return_value="on")),
        patch.object(raid_detector, "get_redis", new=AsyncMock(return_value=redis)),
        patch.object(raid_detector, "get_settings", return_value=settings),
        patch.object(
            raid_detector,
            "_activate_lockdown",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await raid_detector.check_raid(SimpleNamespace(), -100, 42)

    assert result is False
    state_pipe.execute.assert_awaited_once()
    redis.set.assert_awaited_once()
    redis.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_raid_failure_compensates_slow_mode_and_permissions() -> None:
    from src.pipeline import raid_detector

    bot = SimpleNamespace(
        set_chat_slow_mode_delay=AsyncMock(),
        set_chat_permissions=AsyncMock(),
        send_message=AsyncMock(side_effect=TelegramError("group notification failed")),
    )
    settings = SimpleNamespace(
        raid_join_window_seconds=60,
        telegram_admin_ids=[],
    )

    with patch.object(raid_detector, "get_settings", return_value=settings):
        result = await raid_detector._activate_lockdown(bot, -100, 2)

    assert result is False
    assert [call.kwargs["slow_mode_delay"] for call in bot.set_chat_slow_mode_delay.await_args_list] == [30, 0]
    assert bot.set_chat_permissions.await_count == 2
    assert bot.set_chat_permissions.await_args_list[1].kwargs["permissions"].can_send_other_messages is True


@pytest.mark.asyncio
async def test_permission_failure_compensates_slow_mode_only() -> None:
    from src.pipeline import raid_detector

    bot = SimpleNamespace(
        set_chat_slow_mode_delay=AsyncMock(),
        set_chat_permissions=AsyncMock(side_effect=TelegramError("permission update failed")),
        send_message=AsyncMock(),
    )
    settings = SimpleNamespace(
        raid_join_window_seconds=60,
        telegram_admin_ids=[],
    )

    with patch.object(raid_detector, "get_settings", return_value=settings):
        result = await raid_detector._activate_lockdown(bot, -100, 2)

    assert result is False
    assert [call.kwargs["slow_mode_delay"] for call in bot.set_chat_slow_mode_delay.await_args_list] == [30, 0]
    bot.send_message.assert_not_awaited()
