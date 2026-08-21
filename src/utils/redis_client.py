"""
Async Redis client singleton with connection pooling.
"""
from __future__ import annotations

import asyncio

import redis.asyncio as aioredis
from redis.asyncio import Redis

from config.settings import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_redis: Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


async def get_redis() -> Redis:
    global _redis, _redis_loop
    current_loop = asyncio.get_running_loop()

    # Test runners and embedded workers can create multiple event loops. A
    # connection pool must never be reused by a loop that has already closed.
    if _redis is not None and _redis_loop is not current_loop:
        previous_redis = _redis
        previous_loop = _redis_loop
        _redis = None
        _redis_loop = None
        if previous_loop is not None and not previous_loop.is_closed():
            try:
                await previous_redis.aclose()
            except RuntimeError:
                logger.debug("redis_pool_close_skipped", reason="previous_loop_closed")

    if _redis is None:
        settings = get_settings()
        _redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
        )
        await _redis.ping()
        _redis_loop = current_loop
        logger.info("redis_connected")
    return _redis


async def close_redis() -> None:
    global _redis, _redis_loop
    if _redis:
        await _redis.aclose()
        _redis = None
        _redis_loop = None
        logger.info("redis_closed")
