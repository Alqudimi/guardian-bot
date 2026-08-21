"""
Feature Rate Limiter
---------------------
Redis-backed per-user sliding-window rate limiter shared across all feature
modules.  Completely separate from the moderation pipeline rate limiting.
"""
from __future__ import annotations

import time

from config.settings import get_settings
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)


async def check_rate_limit(
    user_id: int,
    command: str,
    limit: int = 3,
    window: int = 60,
) -> tuple[bool, int]:
    """
    Sliding-window rate limiter.
    Returns (allowed: bool, retry_after_seconds: int).
    """
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}feat_rl:{command}:{user_id}"
    now = time.time()

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, "-inf", now - window)
    pipe.zadd(key, {str(now): now})
    pipe.zcard(key)
    pipe.expire(key, window * 2)
    results = await pipe.execute()
    count = int(results[2])

    if count > limit:
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        retry_after = (
            int(window - (now - float(oldest[0][1]))) + 1 if oldest else window
        )
        logger.debug(
            "feature_rate_limited",
            command=command,
            user_id=user_id,
            retry_after=retry_after,
        )
        return False, max(1, retry_after)

    return True, 0


async def rate_limit_check(
    user_id: int,
    command: str,
    limit: int = 3,
    window: int = 60,
) -> tuple[bool, str]:
    """
    Convenience wrapper.
    Returns (allowed: bool, error_message_if_blocked: str).
    """
    allowed, retry = await check_rate_limit(user_id, command, limit, window)
    if not allowed:
        msg = (
            f"⏳ الرجاء الانتظار {retry} ثانية | Please wait {retry}s before using "
            f"this command again."
        )
        return False, msg
    return True, ""
