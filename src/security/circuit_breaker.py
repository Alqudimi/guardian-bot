"""
Circuit Breaker — Anti-Ban Core Safety
========================================
Implements the Circuit Breaker pattern for Telegram API calls.

States:
  CLOSED   → Normal operation. All actions allowed.
  OPEN     → Telegram is fighting back (429s, FloodWaits, Forbidden spam).
             All punitive actions are suppressed. Only logging continues.
  HALF_OPEN→ Recovery probe. One test action allowed. If it succeeds,
             transition to CLOSED. If it fails, back to OPEN.

Triggers that open the breaker:
  - N consecutive Telegram 429 / RetryAfter errors within a window
  - Sudden spike in Forbidden errors (bot restricted by Telegram)
  - Ban rate exceeding the hourly cap by 2×
  - Manual trip via admin command /safemode on

Recovery:
  - Automatic after configurable cooldown (default 10 min)
  - Manual via admin command /safemode off

Persistence: state stored in Redis so it survives restarts.
"""
from __future__ import annotations

import time
from enum import Enum

from config.settings import get_settings
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

_PREFIX = "cb:"  # circuit breaker Redis prefix


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# Thresholds
_FAILURE_THRESHOLD = 5       # failures in window before opening
_FAILURE_WINDOW_S = 120      # 2-minute window for failure counting
_RECOVERY_TIMEOUT_S = 600    # 10 minutes before attempting recovery
_SUCCESS_THRESHOLD = 2       # consecutive successes needed to close


async def get_state() -> BreakerState:
    redis = await get_redis()
    settings = get_settings()
    state = await redis.get(f"{settings.redis_prefix}{_PREFIX}state")
    return BreakerState(state) if state else BreakerState.CLOSED


async def _set_state(state: BreakerState, ttl: int | None = None) -> None:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}{_PREFIX}state"
    if ttl:
        await redis.setex(key, ttl, state.value)
    else:
        await redis.set(key, state.value)
    logger.warning("circuit_breaker_state_change", new_state=state.value)


async def record_failure(error_type: str = "generic") -> None:
    """
    Record a Telegram API failure. May trip the breaker to OPEN.
    """
    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix
    now = time.time()

    fail_key = f"{prefix}{_PREFIX}failures"
    await redis.zadd(fail_key, {f"{error_type}:{now}": now})
    await redis.zremrangebyscore(fail_key, "-inf", now - _FAILURE_WINDOW_S)
    await redis.expire(fail_key, _FAILURE_WINDOW_S * 2)

    failure_count = await redis.zcard(fail_key)

    current_state = await get_state()

    if current_state == BreakerState.CLOSED and failure_count >= _FAILURE_THRESHOLD:
        await _set_state(BreakerState.OPEN)
        # Auto-recovery attempt after timeout
        await redis.setex(
            f"{prefix}{_PREFIX}recovery_at",
            _RECOVERY_TIMEOUT_S,
            str(now + _RECOVERY_TIMEOUT_S),
        )
        logger.error(
            "circuit_breaker_opened",
            failure_count=failure_count,
            error_type=error_type,
            recovery_in_seconds=_RECOVERY_TIMEOUT_S,
        )

    elif current_state == BreakerState.HALF_OPEN:
        # Probe failed — go back to OPEN
        await _set_state(BreakerState.OPEN)
        await redis.setex(
            f"{prefix}{_PREFIX}recovery_at",
            _RECOVERY_TIMEOUT_S,
            str(now + _RECOVERY_TIMEOUT_S),
        )
        # Reset consecutive success counter
        await redis.delete(f"{prefix}{_PREFIX}consec_success")


async def record_success() -> None:
    """
    Record a successful Telegram API call. May close the breaker.
    """
    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix
    current_state = await get_state()

    if current_state == BreakerState.HALF_OPEN:
        success_key = f"{prefix}{_PREFIX}consec_success"
        count = await redis.incr(success_key)
        await redis.expire(success_key, 300)

        if count >= _SUCCESS_THRESHOLD:
            await _set_state(BreakerState.CLOSED)
            await redis.delete(success_key)
            await redis.delete(f"{prefix}{_PREFIX}failures")
            logger.info("circuit_breaker_closed", consecutive_successes=count)


async def can_act() -> tuple[bool, str]:
    """
    Returns (allowed: bool, reason: str).
    Must be checked before every punitive Telegram API call.
    """
    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix
    state = await get_state()

    if state == BreakerState.CLOSED:
        return True, ""

    if state == BreakerState.OPEN:
        # Check if recovery window has elapsed
        recovery_at = await redis.get(f"{prefix}{_PREFIX}recovery_at")
        if recovery_at and time.time() >= float(recovery_at):
            await _set_state(BreakerState.HALF_OPEN)
            return True, ""  # Allow probe action
        return False, "circuit_breaker_open"

    if state == BreakerState.HALF_OPEN:
        return True, "probe"

    return False, "unknown_state"


async def manual_trip(reason: str = "admin") -> None:
    """Manually open the circuit breaker (safe mode)."""
    await _set_state(BreakerState.OPEN)
    redis = await get_redis()
    settings = get_settings()
    await redis.setex(
        f"{settings.redis_prefix}{_PREFIX}recovery_at",
        _RECOVERY_TIMEOUT_S,
        str(time.time() + _RECOVERY_TIMEOUT_S),
    )
    logger.warning("circuit_breaker_manual_trip", reason=reason)


async def manual_reset() -> None:
    """Manually close the circuit breaker."""
    await _set_state(BreakerState.CLOSED)
    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix
    await redis.delete(f"{prefix}{_PREFIX}failures")
    await redis.delete(f"{prefix}{_PREFIX}consec_success")
    await redis.delete(f"{prefix}{_PREFIX}recovery_at")
    logger.info("circuit_breaker_manual_reset")
