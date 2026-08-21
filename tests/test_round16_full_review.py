from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import WatchError

from config.settings import get_settings
from src.management.group_settings import (
    get_setting,
    reset_settings,
)
from src.utils.redis_client import get_redis


async def _cleanup_warn_keys(chat_id: int) -> None:
    redis = await get_redis()
    prefix = get_settings().redis_prefix
    await redis.delete(
        f"{prefix}group_settings:{chat_id}",
        f"{prefix}warnlimit:{chat_id}",
        f"{prefix}warns:{chat_id}:42",
        f"{prefix}warns:{chat_id}:43",
    )


@pytest.mark.asyncio
async def test_warn_limit_default_and_canonical_round_trip() -> None:
    from src.layers.smart_warn import get_max_warns, set_max_warns

    chat_id = -160001
    await _cleanup_warn_keys(chat_id)
    try:
        assert await get_max_warns(chat_id) == 5
        await set_max_warns(chat_id, 3)
        assert await get_max_warns(chat_id) == 3

        redis = await get_redis()
        prefix = get_settings().redis_prefix
        assert await redis.hget(f"{prefix}group_settings:{chat_id}", "warn_limit") == "3"
        assert await redis.get(f"{prefix}warnlimit:{chat_id}") is None
    finally:
        await _cleanup_warn_keys(chat_id)


@pytest.mark.asyncio
async def test_legacy_warn_limit_is_migrated_and_deleted() -> None:
    chat_id = -160002
    await _cleanup_warn_keys(chat_id)
    redis = await get_redis()
    prefix = get_settings().redis_prefix
    try:
        await redis.set(f"{prefix}warnlimit:{chat_id}", "4")
        assert await get_setting(chat_id, "warn_limit") == "4"
        assert await redis.hget(f"{prefix}group_settings:{chat_id}", "warn_limit") == "4"
        assert await redis.get(f"{prefix}warnlimit:{chat_id}") is None
    finally:
        await _cleanup_warn_keys(chat_id)


@pytest.mark.asyncio
async def test_invalid_legacy_warn_limit_is_discarded_to_default() -> None:
    chat_id = -160003
    await _cleanup_warn_keys(chat_id)
    redis = await get_redis()
    prefix = get_settings().redis_prefix
    try:
        await redis.set(f"{prefix}warnlimit:{chat_id}", "99")
        assert await get_setting(chat_id, "warn_limit") == "5"
        assert await redis.get(f"{prefix}warnlimit:{chat_id}") is None
    finally:
        await _cleanup_warn_keys(chat_id)


@pytest.mark.asyncio
async def test_reset_settings_removes_canonical_and_legacy_warn_limit() -> None:
    chat_id = -160004
    await _cleanup_warn_keys(chat_id)
    redis = await get_redis()
    prefix = get_settings().redis_prefix
    try:
        await redis.hset(f"{prefix}group_settings:{chat_id}", "warn_limit", "2")
        await redis.set(f"{prefix}warnlimit:{chat_id}", "4")
        await reset_settings(chat_id)
        assert await redis.hget(f"{prefix}group_settings:{chat_id}", "warn_limit") is None
        assert await redis.get(f"{prefix}warnlimit:{chat_id}") is None
        assert await get_setting(chat_id, "warn_limit") == "5"
    finally:
        await _cleanup_warn_keys(chat_id)


@pytest.mark.asyncio
async def test_set_max_warns_rejects_out_of_range_values() -> None:
    from src.layers.smart_warn import set_max_warns

    with pytest.raises(ValueError, match="between 1 and 10"):
        await set_max_warns(-160005, 11)


@pytest.mark.asyncio
async def test_concurrent_warns_preserve_both_history_records() -> None:
    from src.layers.smart_warn import add_warn, get_warn_status

    chat_id = -160006
    await _cleanup_warn_keys(chat_id)
    try:
        await asyncio.gather(
            add_warn(42, chat_id, "spam", 60.0, "first"),
            add_warn(42, chat_id, "flood", 65.0, "second"),
        )
        status = await get_warn_status(42, chat_id)
        assert status.total_warn_count == 2
        assert {record.violation_type for record in status.history} == {"spam", "flood"}
    finally:
        await _cleanup_warn_keys(chat_id)


class _FailingWarnPipeline:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def watch(self, key):
        return None

    async def get(self, key):
        return None

    def multi(self):
        return self

    def set(self, key, value):
        return self

    def expire(self, key, seconds):
        return self

    async def execute(self):
        raise RedisConnectionError("redis unavailable")


@pytest.mark.asyncio
async def test_warn_transaction_failure_does_not_report_success() -> None:
    from src.layers import smart_warn

    redis = MagicMock()
    redis.pipeline.return_value = _FailingWarnPipeline()
    with (
        patch.object(smart_warn, "get_redis", new=AsyncMock(return_value=redis)),
        patch.object(smart_warn, "get_max_warns", new=AsyncMock(return_value=5)),
    ):
        with pytest.raises(RedisConnectionError):
            await smart_warn.add_warn(42, -160007, "spam", 60.0)


class _SequenceWarnPipeline:
    def __init__(self, error=None):
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def watch(self, key):
        return None

    async def get(self, key):
        return None

    def multi(self):
        return self

    def set(self, key, value):
        return self

    def expire(self, key, seconds):
        return self

    async def execute(self):
        if self.error:
            raise self.error
        return [True, True]


@pytest.mark.asyncio
async def test_warn_transaction_retries_after_watch_conflict() -> None:
    from src.layers import smart_warn

    redis = MagicMock()
    redis.pipeline.side_effect = [
        _SequenceWarnPipeline(WatchError()),
        _SequenceWarnPipeline(),
    ]
    with (
        patch.object(smart_warn, "get_redis", new=AsyncMock(return_value=redis)),
        patch.object(smart_warn, "get_max_warns", new=AsyncMock(return_value=5)),
    ):
        status = await smart_warn.add_warn(42, -160008, "spam", 60.0)

    assert status.total_warn_count == 1
    assert redis.pipeline.call_count == 2
