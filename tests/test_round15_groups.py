from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_check_raid_enforces_when_group_anti_raid_is_on() -> None:
    from src.pipeline import raid_detector

    pipeline = MagicMock()
    pipeline.execute = AsyncMock(side_effect=[[0, 1, 2, None], [True, True]])
    redis = MagicMock()
    redis.pipeline.return_value = pipeline
    redis.exists = AsyncMock(return_value=False)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    settings = SimpleNamespace(
        redis_prefix="test:",
        raid_join_window_seconds=60,
        raid_join_threshold=2,
    )
    bot = SimpleNamespace()

    with (
        patch.object(raid_detector, "get_setting", new=AsyncMock(return_value="on")) as get_setting,
        patch.object(raid_detector, "get_redis", new=AsyncMock(return_value=redis)),
        patch.object(raid_detector, "get_settings", return_value=settings),
        patch.object(
            raid_detector,
            "_activate_lockdown",
            new=AsyncMock(return_value=True),
        ) as activate,
        patch.object(
            raid_detector,
            "_persist_raid_db_state",
            new=AsyncMock(return_value=True),
        ) as persist_db,
    ):
        result = await raid_detector.check_raid(bot, -100, 42)

    assert result is True
    get_setting.assert_awaited_once_with(-100, "anti_raid")
    activate.assert_awaited_once_with(bot, -100, 2)
    persist_db.assert_awaited_once_with(-100, active=True)
    redis.set.assert_awaited_once()
    assert pipeline.execute.await_count == 2


@pytest.mark.asyncio
async def test_check_raid_skips_without_redis_when_group_anti_raid_is_off() -> None:
    from src.pipeline import raid_detector

    get_redis = AsyncMock()
    with (
        patch.object(raid_detector, "get_setting", new=AsyncMock(return_value="off")),
        patch.object(raid_detector, "get_redis", new=get_redis),
        patch.object(raid_detector, "_activate_lockdown", new=AsyncMock()) as activate,
    ):
        result = await raid_detector.check_raid(SimpleNamespace(), -100, 42)

    assert result is False
    get_redis.assert_not_awaited()
    activate.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_raid_skips_safely_when_group_anti_raid_setting_fails() -> None:
    from src.pipeline import raid_detector

    get_redis = AsyncMock()
    with (
        patch.object(
            raid_detector,
            "get_setting",
            new=AsyncMock(side_effect=RuntimeError("redis unavailable")),
        ),
        patch.object(raid_detector, "get_redis", new=get_redis),
        patch.object(raid_detector, "_activate_lockdown", new=AsyncMock()) as activate,
    ):
        result = await raid_detector.check_raid(SimpleNamespace(), -100, 42)

    assert result is False
    get_redis.assert_not_awaited()
    activate.assert_not_awaited()


@pytest.mark.asyncio
async def test_setraid_validates_and_persists_group_setting() -> None:
    from src.handlers import admin_commands

    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        message=message,
        effective_message=message,
        effective_chat=SimpleNamespace(id=-100, type="supergroup"),
        effective_user=SimpleNamespace(id=7),
    )
    context = SimpleNamespace(args=["maybe"], bot=SimpleNamespace())

    with (
        patch.object(admin_commands, "is_authorized_admin", new=AsyncMock(return_value=True)),
        patch.object(admin_commands, "log_admin_command", new=AsyncMock()),
        patch.object(admin_commands, "set_setting", new=AsyncMock()) as set_setting,
    ):
        await admin_commands.cmd_setraid(update, context)

    assert "setraid on|off" in message.reply_text.await_args.args[0]
    set_setting.assert_not_awaited()

    message.reply_text.reset_mock()
    context.args = ["off"]
    with (
        patch.object(admin_commands, "is_authorized_admin", new=AsyncMock(return_value=True)),
        patch.object(admin_commands, "log_admin_command", new=AsyncMock()),
        patch.object(admin_commands, "set_setting", new=AsyncMock()) as set_setting,
    ):
        await admin_commands.cmd_setraid(update, context)

    set_setting.assert_awaited_once_with(-100, "anti_raid", "off")
    assert "off" in message.reply_text.await_args.args[0]
