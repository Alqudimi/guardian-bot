"""
Anti-Ban Safety Module
-----------------------
Provides utilities to prevent Telegram from flagging the bot as abusive.

Strategies:
1. Global action pacing with token-bucket rate limiting (Redis-backed)
2. Per-user cooldown periods between repeated actions
3. Hourly caps on bans/kicks
4. Jitter injection between API calls
5. Slow-mode preference over immediate bans when limits are near
6. Exponential back-off on Telegram API 429 (rate limit) responses
7. Detection of anomalous action bursts and automatic self-throttling

This module is imported by action_execution.py but can also be used
standalone for any layer that needs pacing.
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass

from config.settings import get_settings
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)


@dataclass
class ActionBudget:
    """Tracks remaining action capacity within current window."""
    global_remaining: int = 0
    ban_remaining: int = 0
    delete_remaining: int = 0
    is_throttled: bool = False
    throttle_reason: str = ""


async def get_action_budget() -> ActionBudget:
    """
    Query current action budget from Redis counters.
    Returns an ActionBudget describing how much capacity is left.
    """
    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix
    now = time.time()

    # Count actions in last minute
    global_key = f"{prefix}act_global"
    await redis.zremrangebyscore(global_key, "-inf", now - 60)
    global_count = int(await redis.zcard(global_key) or 0)

    # Count bans in last hour
    bans_key = f"{prefix}bans_hourly"
    await redis.zremrangebyscore(bans_key, "-inf", now - 3600)
    ban_count = int(await redis.zcard(bans_key) or 0)

    # Count deletes in last minute
    delete_key = f"{prefix}deletes_minute"
    await redis.zremrangebyscore(delete_key, "-inf", now - 60)
    delete_count = int(await redis.zcard(delete_key) or 0)

    global_remaining = max(0, settings.action_rate_limit_per_minute - global_count)
    ban_remaining = max(0, settings.ban_hourly_limit - ban_count)
    delete_remaining = max(0, settings.delete_rate_per_minute - delete_count)

    is_throttled = global_remaining == 0
    throttle_reason = ""
    if global_remaining == 0:
        throttle_reason = "global_rate_limit"
    elif ban_remaining == 0:
        throttle_reason = "hourly_ban_cap"

    return ActionBudget(
        global_remaining=global_remaining,
        ban_remaining=ban_remaining,
        delete_remaining=delete_remaining,
        is_throttled=is_throttled,
        throttle_reason=throttle_reason,
    )


async def record_delete(chat_id: int, message_id: int) -> None:
    """Track a delete action in the rate counter."""
    redis = await get_redis()
    settings = get_settings()
    now = time.time()
    delete_key = f"{settings.redis_prefix}deletes_minute"
    await redis.zadd(delete_key, {f"{chat_id}:{message_id}:{now}": now})
    await redis.expire(delete_key, 120)


async def jitter_sleep(min_s: float | None = None, max_s: float | None = None) -> None:
    """Sleep for a random duration within [min_s, max_s]."""
    settings = get_settings()
    lo = min_s if min_s is not None else settings.action_jitter_min
    hi = max_s if max_s is not None else settings.action_jitter_max
    await asyncio.sleep(random.uniform(lo, hi))


async def backoff_sleep(attempt: int, base: float = 1.0, cap: float = 30.0) -> None:
    """
    Exponential back-off with jitter for Telegram API 429 retries.
    attempt: 0-indexed retry count
    """
    delay = min(cap, base * (2 ** attempt) + random.uniform(0, 1))
    logger.warning("backoff_sleep", attempt=attempt, delay=round(delay, 2))
    await asyncio.sleep(delay)


async def is_safe_to_act(action_type: str = "generic") -> tuple[bool, str]:
    """
    Check whether it's currently safe to perform the given action type.
    Returns (safe: bool, reason: str).
    """
    budget = await get_action_budget()

    if budget.is_throttled:
        return False, budget.throttle_reason

    if action_type in ("ban_temp", "ban_perm") and budget.ban_remaining == 0:
        return False, "hourly_ban_cap_reached"

    if action_type == "delete" and budget.delete_remaining == 0:
        return False, "delete_rate_limit_reached"

    return True, ""
