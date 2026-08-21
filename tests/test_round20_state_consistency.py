from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import TelegramError

from config.settings import get_settings
from src.utils.redis_client import get_redis


async def _cleanup_lockdown(chat_id: int) -> None:
    redis = await get_redis()
    prefix = get_settings().redis_prefix
    await redis.delete(
        f"{prefix}lockdown:{chat_id}",
        f"{prefix}raid_activation:{chat_id}",
    )


@pytest.mark.asyncio
async def test_release_clears_redis_only_after_primary_telegram_success() -> None:
    from src.pipeline import raid_detector

    redis = MagicMock()
    redis.delete = AsyncMock()
    bot = SimpleNamespace(
        set_chat_slow_mode_delay=AsyncMock(),
        set_chat_permissions=AsyncMock(),
        send_message=AsyncMock(),
    )
    settings = SimpleNamespace(redis_prefix="test:")

    with (
        patch.object(raid_detector, "get_settings", return_value=settings),
        patch.object(raid_detector, "get_redis", new=AsyncMock(return_value=redis)),
        patch.object(
            raid_detector,
            "_persist_raid_db_state",
            new=AsyncMock(return_value=True),
        ) as persist_db,
    ):
        await raid_detector.release_lockdown(bot, -100)

    persist_db.assert_awaited_once_with(-100, active=False)
    redis.delete.assert_awaited_once_with("test:lockdown:-100")


@pytest.mark.asyncio
async def test_release_telegram_failure_keeps_redis_marker_and_db_state() -> None:
    from src.pipeline import raid_detector

    redis = MagicMock()
    redis.delete = AsyncMock()
    bot = SimpleNamespace(
        set_chat_slow_mode_delay=AsyncMock(side_effect=TelegramError("forbidden")),
        set_chat_permissions=AsyncMock(),
        send_message=AsyncMock(),
    )
    settings = SimpleNamespace(redis_prefix="test:")

    with (
        patch.object(raid_detector, "get_settings", return_value=settings),
        patch.object(raid_detector, "get_redis", new=AsyncMock(return_value=redis)),
        patch.object(
            raid_detector,
            "_persist_raid_db_state",
            new=AsyncMock(),
        ) as persist_db,
    ):
        await raid_detector.release_lockdown(bot, -100)

    redis.delete.assert_not_awaited()
    persist_db.assert_not_awaited()
    bot.set_chat_permissions.assert_not_awaited()


@pytest.mark.asyncio
async def test_release_permission_failure_restores_slow_mode_and_keeps_marker() -> None:
    from src.pipeline import raid_detector

    redis = MagicMock()
    redis.delete = AsyncMock()
    bot = SimpleNamespace(
        set_chat_slow_mode_delay=AsyncMock(),
        set_chat_permissions=AsyncMock(side_effect=TelegramError("forbidden")),
        send_message=AsyncMock(),
    )
    settings = SimpleNamespace(redis_prefix="test:")

    with (
        patch.object(raid_detector, "get_settings", return_value=settings),
        patch.object(raid_detector, "get_redis", new=AsyncMock(return_value=redis)),
    ):
        await raid_detector.release_lockdown(bot, -100)

    assert [call.kwargs["slow_mode_delay"] for call in bot.set_chat_slow_mode_delay.await_args_list] == [0, 30]
    redis.delete.assert_not_awaited()
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_release_clears_redis_even_when_db_mirror_fails() -> None:
    from src.pipeline import raid_detector

    redis = MagicMock()
    redis.delete = AsyncMock()
    bot = SimpleNamespace(
        set_chat_slow_mode_delay=AsyncMock(),
        set_chat_permissions=AsyncMock(),
        send_message=AsyncMock(),
    )
    settings = SimpleNamespace(redis_prefix="test:")

    with (
        patch.object(raid_detector, "get_settings", return_value=settings),
        patch.object(raid_detector, "get_redis", new=AsyncMock(return_value=redis)),
        patch.object(
            raid_detector,
            "_persist_raid_db_state",
            new=AsyncMock(return_value=False),
        ),
    ):
        await raid_detector.release_lockdown(bot, -100)

    redis.delete.assert_awaited_once_with("test:lockdown:-100")
