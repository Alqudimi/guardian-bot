from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_captcha_auto_kick_uses_background_task_registry() -> None:
    from src.layers import captcha_gate

    previous = captcha_gate._captcha_tasks.pop((-210001, 42), None)
    if previous and not previous.done():
        previous.cancel()
    task = MagicMock()
    task.done.return_value = False

    try:
        def register_and_close(coroutine, *, name):
            coroutine.close()
            return task

        with patch.object(
            captcha_gate,
            "create_background_task",
            side_effect=register_and_close,
        ) as create:
            captcha_gate._schedule_auto_kick(SimpleNamespace(), -210001, 42)

        create.assert_called_once()
        assert create.call_args.kwargs["name"] == "captcha-timeout:-210001:42"
        assert captcha_gate._captcha_tasks[(-210001, 42)] is task
    finally:
        captcha_gate._captcha_tasks.pop((-210001, 42), None)



import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_captcha_gate_reads_and_writes_canonical_settings() -> None:
    from src.layers import captcha_gate

    with patch(
        "src.management.group_settings.get_setting",
        new=AsyncMock(return_value="on"),
    ) as get_setting, patch(
        "src.management.group_settings.set_setting",
        new=AsyncMock(),
    ) as set_setting:
        assert await captcha_gate.is_captcha_enabled(-210002) is True
        await captcha_gate.set_captcha_enabled(-210002, False)

    get_setting.assert_awaited_once_with(-210002, "captcha")
    set_setting.assert_awaited_once_with(-210002, "captcha", "off")


@pytest.mark.asyncio
async def test_group_settings_migrates_legacy_captcha_key_and_deletes_it() -> None:
    from src.management import group_settings

    redis = MagicMock()
    redis.hget = AsyncMock(return_value=None)
    redis.get = AsyncMock(return_value=b"1")
    redis.hset = AsyncMock()
    redis.delete = AsyncMock()

    with (
        patch.object(group_settings, "get_settings", return_value=SimpleNamespace(redis_prefix="test:")),
        patch.object(group_settings, "get_redis", new=AsyncMock(return_value=redis)),
    ):
        result = await group_settings.get_setting(-210003, "captcha")

    assert result == "on"
    redis.hset.assert_awaited_once_with("test:group_settings:-210003", "captcha", "on")
    redis.delete.assert_awaited_once_with("test:captcha_enabled:-210003")


@pytest.mark.asyncio
async def test_group_settings_captcha_write_removes_legacy_key() -> None:
    from src.management import group_settings

    redis = MagicMock()
    redis.hset = AsyncMock()
    redis.delete = AsyncMock()

    with (
        patch.object(group_settings, "get_settings", return_value=SimpleNamespace(redis_prefix="test:")),
        patch.object(group_settings, "get_redis", new=AsyncMock(return_value=redis)),
    ):
        await group_settings.set_setting(-210004, "captcha", "off")

    redis.hset.assert_awaited_once_with("test:group_settings:-210004", "captcha", "off")
    redis.delete.assert_awaited_once_with("test:captcha_enabled:-210004")
