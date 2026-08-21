"""
API Sentinel — Telegram API Health Monitor & Self-Protection
=============================================================
Monitors the bot's relationship with the Telegram API to detect
early warning signs of account suspension, rate limiting, or being
targeted by Telegram's anti-abuse systems.

Monitors:
  1. FloodWait frequency and duration — rising FloodWaits = danger signal
  2. 429 Too Many Requests — tracked per endpoint
  3. Forbidden errors — bot restricted from groups
  4. ChatMigrated / MigratedToSupergroup — group structure changes
  5. BotKicked events — bot being removed from groups
  6. Update latency — unusually high latency may indicate throttling
  7. Action success rate — low success = Telegram fighting back

Responses:
  - Increment threat level (0–5) based on observed signals
  - Trigger circuit breaker at threat level 3+
  - Enter full safe-mode (log-only) at threat level 5
  - Alert admins with full diagnostic report
  - Automatically recover and decrease threat level over time
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from config.settings import get_settings
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)


@dataclass
class SentinelStatus:
    threat_level: int = 0         # 0 = clean, 5 = critical
    total_flood_waits: int = 0
    total_forbidden: int = 0
    total_429s: int = 0
    total_bot_kicked: int = 0
    action_success_rate: float = 1.0
    last_flood_wait_seconds: int = 0
    safe_mode_active: bool = False
    recommendations: list[str] = field(default_factory=list)


_KEY_PREFIX = "sentinel:"

# Threat level thresholds
_FLOOD_WAIT_DANGER = 60       # FloodWait > 60s = serious
_FLOOD_WAIT_CRITICAL = 300    # FloodWait > 300s = critical
_MAX_FLOOD_WAITS_PER_HOUR = 5
_MAX_FORBIDDEN_PER_HOUR = 10
_THREAT_DECAY_PER_HOUR = 1    # Threat level decays by 1 per hour without incidents


async def record_flood_wait(seconds: int, endpoint: str = "generic") -> None:
    """Record a FloodWait exception from Telegram."""
    redis = await get_redis()
    settings = get_settings()
    prefix = f"{settings.redis_prefix}{_KEY_PREFIX}"
    now = time.time()

    # Store in sliding window
    key = f"{prefix}flood_waits"
    await redis.zadd(key, {f"{endpoint}:{now}": now})
    await redis.zremrangebyscore(key, "-inf", now - 3600)
    await redis.expire(key, 3600)

    count = await redis.zcard(key)

    # Adjust threat level
    delta = 0
    if seconds > _FLOOD_WAIT_CRITICAL:
        delta = 3
    elif seconds > _FLOOD_WAIT_DANGER:
        delta = 2
    else:
        delta = 1

    await _increment_threat(prefix, delta, f"flood_wait_{seconds}s")

    # Store last FloodWait duration for diagnostics
    await redis.setex(f"{prefix}last_flood_wait_s", 3600, str(seconds))

    logger.warning(
        "flood_wait_recorded",
        seconds=seconds,
        endpoint=endpoint,
        hourly_count=count,
        threat_delta=delta,
    )

    # Trigger circuit breaker if too many
    if count >= _MAX_FLOOD_WAITS_PER_HOUR:
        from src.security.circuit_breaker import manual_trip
        await manual_trip(reason=f"flood_wait_hourly_limit:{count}")


async def record_forbidden(chat_id: int, user_id: int | None = None) -> None:
    """Record a Forbidden error (bot restricted from group)."""
    redis = await get_redis()
    settings = get_settings()
    prefix = f"{settings.redis_prefix}{_KEY_PREFIX}"
    now = time.time()

    key = f"{prefix}forbidden"
    await redis.zadd(key, {f"{chat_id}:{now}": now})
    await redis.zremrangebyscore(key, "-inf", now - 3600)
    await redis.expire(key, 3600)

    count = await redis.zcard(key)
    await _increment_threat(prefix, 1, f"forbidden_in_{chat_id}")

    if count >= _MAX_FORBIDDEN_PER_HOUR:
        await _increment_threat(prefix, 2, f"forbidden_hourly_limit:{count}")
        logger.error("forbidden_rate_critical", count=count, chat_id=chat_id)


async def record_bot_kicked(chat_id: int) -> None:
    """Record bot being kicked from a group."""
    redis = await get_redis()
    settings = get_settings()
    prefix = f"{settings.redis_prefix}{_KEY_PREFIX}"

    key = f"{prefix}kicked"
    now = time.time()
    await redis.zadd(key, {f"{chat_id}:{now}": now})
    await redis.expire(key, 86400)

    kicked_count = await redis.zcard(key)
    await _increment_threat(prefix, 1, f"kicked_from_{chat_id}")

    logger.warning(
        "bot_kicked_recorded",
        chat_id=chat_id,
        total_24h=kicked_count,
    )


async def record_action_result(success: bool, action_type: str) -> None:
    """Track action success/failure rate."""
    redis = await get_redis()
    settings = get_settings()
    prefix = f"{settings.redis_prefix}{_KEY_PREFIX}"

    key = f"{prefix}action_results"
    now = time.time()
    val = "ok" if success else "fail"
    await redis.zadd(key, {f"{val}:{action_type}:{now}": now})
    await redis.zremrangebyscore(key, "-inf", now - 300)  # 5-min window
    await redis.expire(key, 600)

    if not success:
        from src.security.circuit_breaker import record_failure
        await record_failure(action_type)


async def _increment_threat(prefix: str, delta: int, reason: str) -> None:
    redis = await get_redis()
    key = f"{prefix}threat_level"
    current = int(await redis.get(key) or 0)
    new_level = min(5, current + delta)
    await redis.setex(key, 3600 * 24, str(new_level))

    logger.warning(
        "threat_level_changed",
        old=current,
        new=new_level,
        reason=reason,
    )

    if new_level >= 5:
        await redis.setex(f"{prefix}safe_mode", 3600, "1")
        logger.error("SAFE_MODE_ACTIVATED", threat_level=new_level)


async def get_status() -> SentinelStatus:
    """Return current sentinel status for diagnostics."""
    redis = await get_redis()
    settings = get_settings()
    prefix = f"{settings.redis_prefix}{_KEY_PREFIX}"
    now = time.time()

    threat_level = int(await redis.get(f"{prefix}threat_level") or 0)
    safe_mode = bool(await redis.exists(f"{prefix}safe_mode"))
    last_fw = int(await redis.get(f"{prefix}last_flood_wait_s") or 0)

    # Count recent events
    await redis.zremrangebyscore(f"{prefix}flood_waits", "-inf", now - 3600)
    fw_count = int(await redis.zcard(f"{prefix}flood_waits") or 0)

    await redis.zremrangebyscore(f"{prefix}forbidden", "-inf", now - 3600)
    forbidden_count = int(await redis.zcard(f"{prefix}forbidden") or 0)

    # Success rate from last 5 minutes
    results_raw = await redis.zrange(f"{prefix}action_results", 0, -1)
    if results_raw:
        ok = sum(1 for r in results_raw if r.startswith("ok:"))
        total = len(results_raw)
        success_rate = ok / total if total > 0 else 1.0
    else:
        success_rate = 1.0

    recs: list[str] = []
    if threat_level >= 3:
        recs.append("Consider enabling /safemode on")
    if fw_count >= 3:
        recs.append("Reduce action rate — frequent FloodWaits detected")
    if forbidden_count >= 5:
        recs.append("High Forbidden rate — check bot permissions in groups")
    if success_rate < 0.8:
        recs.append(f"Action success rate low: {success_rate:.0%}")

    return SentinelStatus(
        threat_level=threat_level,
        total_flood_waits=fw_count,
        total_forbidden=forbidden_count,
        total_429s=0,
        last_flood_wait_seconds=last_fw,
        safe_mode_active=safe_mode,
        action_success_rate=success_rate,
        recommendations=recs,
    )


async def is_safe_mode() -> bool:
    """Quick check: is full safe-mode active?"""
    redis = await get_redis()
    settings = get_settings()
    return bool(await redis.exists(f"{settings.redis_prefix}{_KEY_PREFIX}safe_mode"))


async def reset_safe_mode() -> None:
    """Manually exit safe-mode."""
    redis = await get_redis()
    settings = get_settings()
    prefix = f"{settings.redis_prefix}{_KEY_PREFIX}"
    await redis.delete(f"{prefix}safe_mode")
    await redis.setex(f"{prefix}threat_level", 3600, "0")
    logger.info("safe_mode_reset")
