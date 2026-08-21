"""
Adaptive Threshold Engine
==========================
Dynamically adjusts moderation thresholds based on:

1. **Group activity level** — busy groups get slightly relaxed thresholds
   to avoid false positives during legitimate high-volume conversations.
2. **Time-of-day patterns** — groups often have peak activity windows.
   Thresholds are tightened during off-peak hours when spam is more likely.
3. **Recent attack history** — groups that just experienced a raid or
   spam wave get temporarily tightened thresholds for 30 minutes.
4. **Group-specific learning** — maintain per-group baseline noise levels
   and adjust relative to that baseline.
5. **False positive feedback** — when an admin uses /undo or removes the
   bot's action, record it as a false positive and relax the triggering
   threshold slightly.
6. **Seasonal patterns** — Fridays/weekends see different spam profiles
   in Arabic-speaking communities; adjust accordingly.

Output: A `GroupThresholds` object with per-group overrides for all
thresholds defined in settings.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from config.settings import get_settings
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)


@dataclass
class GroupThresholds:
    """Per-group threshold overrides. None = use global default."""
    toxicity_threshold: float | None = None
    nsfw_threshold: float | None = None
    spam_score_threshold: float | None = None
    flood_max_messages: int | None = None
    flood_window_seconds: int | None = None
    trust_initial: float | None = None
    moderation_level: str = "moderate"
    attack_mode: bool = False     # Temporarily tightened after recent attack


_CACHE_TTL_S = 300  # Recompute every 5 minutes
_POST_ATTACK_TIGHTEN_S = 1800  # 30 minutes of tightened mode after attack


async def get_group_thresholds(chat_id: int) -> GroupThresholds:
    """
    Compute adaptive thresholds for a specific group.
    Returns GroupThresholds with overrides.
    """
    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix
    now = time.time()

    # ── Check cache ───────────────────────────────────────────────────────────
    cache_key = f"{prefix}athresh:{chat_id}"
    cached = await redis.hgetall(cache_key)
    if cached and float(cached.get("computed_at", 0)) > now - _CACHE_TTL_S:
        return GroupThresholds(
            toxicity_threshold=_safe_float(cached.get("toxicity")),
            nsfw_threshold=_safe_float(cached.get("nsfw")),
            spam_score_threshold=_safe_float(cached.get("spam")),
            flood_max_messages=_safe_int(cached.get("flood_msgs")),
            moderation_level=_safe_level(cached.get("moderation_level")),
            attack_mode=_as_text(cached.get("attack_mode")) == "1",
        )

    thresholds = GroupThresholds()
    configured_level = await _get_moderation_level(chat_id)
    thresholds.moderation_level = configured_level
    attack_mode = False

    # ── 1. Recent attack detection ────────────────────────────────────────────
    raid_key = f"{prefix}lockdown:{chat_id}"
    recent_raids_key = f"{prefix}raid_history:{chat_id}"
    in_lockdown = bool(await redis.exists(raid_key))
    recent_raids = await redis.zcount(
        recent_raids_key, now - 3600, now
    )

    if in_lockdown or int(recent_raids or 0) >= 1:
        attack_mode = True
        thresholds.attack_mode = True
        # Tighten all thresholds by 15% during attack
        thresholds.toxicity_threshold = max(0.5, settings.toxicity_threshold - 0.15)
        thresholds.nsfw_threshold = max(0.6, settings.nsfw_threshold - 0.15)
        thresholds.spam_score_threshold = max(45.0, settings.spam_score_threshold - 10.0)
        thresholds.flood_max_messages = max(4, (settings.flood_max_messages or 8) - 3)

    # ── 2. Group activity level ───────────────────────────────────────────────
    activity_key = f"{prefix}group_activity:{chat_id}"
    recent_msgs = await redis.zcount(activity_key, now - 300, now)  # 5-min window
    recent_msgs = int(recent_msgs or 0)

    if not attack_mode:
        if recent_msgs > 100:
            # Very active group: relax slightly to reduce false positives
            thresholds.toxicity_threshold = min(0.80, settings.toxicity_threshold + 0.05)
            thresholds.flood_max_messages = min(15, (settings.flood_max_messages or 8) + 3)
        elif recent_msgs < 5:
            # Quiet group: tighten (off-peak spam more likely)
            thresholds.flood_max_messages = max(4, (settings.flood_max_messages or 8) - 2)

    # ── 3. Time-of-day adjustment ─────────────────────────────────────────────
    hour = time.gmtime(now).tm_hour
    weekday = time.gmtime(now).tm_wday  # 0=Mon ... 6=Sun
    is_friday_weekend = weekday in (4, 5, 6)  # Fri/Sat/Sun

    if not attack_mode:
        # Late night / early morning (1am–6am UTC) — more spam
        if 1 <= hour <= 6:
            base_flood = thresholds.flood_max_messages or settings.flood_max_messages or 8
            thresholds.flood_max_messages = max(4, base_flood - 1)

        # Friday/weekend — adjust for Arabic community patterns
        if is_friday_weekend:
            base_tox = thresholds.toxicity_threshold or settings.toxicity_threshold
            thresholds.toxicity_threshold = max(0.55, base_tox - 0.05)

    # ── 4. False positive rate adjustment ────────────────────────────────────
    fp_key = f"{prefix}false_positives:{chat_id}"
    fp_count = int(await redis.get(fp_key) or 0)
    if fp_count >= 5:
        # High FP rate — relax thresholds
        base_tox = thresholds.toxicity_threshold or settings.toxicity_threshold
        thresholds.toxicity_threshold = min(0.85, base_tox + 0.05)
        logger.info("adaptive_threshold_fp_relaxed", chat_id=chat_id, fp_count=fp_count)

    # ── Cache result ──────────────────────────────────────────────────────────
    await redis.hset(cache_key, mapping={
        "computed_at": now,
        "toxicity": thresholds.toxicity_threshold or "",
        "nsfw": thresholds.nsfw_threshold or "",
        "spam": thresholds.spam_score_threshold or "",
        "flood_msgs": thresholds.flood_max_messages or "",
        "moderation_level": thresholds.moderation_level,
        "attack_mode": "1" if attack_mode else "0",
    })
    await redis.expire(cache_key, _CACHE_TTL_S)

    logger.debug(
        "adaptive_thresholds_computed",
        chat_id=chat_id,
        attack_mode=attack_mode,
        toxicity=thresholds.toxicity_threshold,
        flood_msgs=thresholds.flood_max_messages,
    )

    return thresholds


async def record_group_message(chat_id: int) -> None:
    """Record message activity for adaptive threshold computation."""
    redis = await get_redis()
    settings = get_settings()
    now = time.time()
    key = f"{settings.redis_prefix}group_activity:{chat_id}"
    await redis.zadd(key, {str(now): now})
    await redis.zremrangebyscore(key, "-inf", now - 600)  # Keep 10-min window
    await redis.expire(key, 1200)


async def invalidate_group_thresholds(chat_id: int) -> None:
    """Invalidate cached per-group thresholds after an admin setting change."""
    redis = await get_redis()
    settings = get_settings()
    await redis.delete(f"{settings.redis_prefix}athresh:{chat_id}")


async def record_false_positive(chat_id: int) -> None:
    """Record an admin-corrected false positive for threshold adaptation."""
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}false_positives:{chat_id}"
    await redis.incr(key)
    await redis.expire(key, 86400 * 7)  # 7-day window

    # Invalidate cached thresholds
    await redis.delete(f"{settings.redis_prefix}athresh:{chat_id}")
    logger.info("false_positive_recorded", chat_id=chat_id)


async def record_raid(chat_id: int) -> None:
    """Record a raid event for adaptive threshold history."""
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}raid_history:{chat_id}"
    now = time.time()
    await redis.zadd(key, {str(now): now})
    await redis.expire(key, 86400)

    # Invalidate threshold cache
    await redis.delete(f"{settings.redis_prefix}athresh:{chat_id}")


async def _get_moderation_level(chat_id: int) -> str:
    try:
        from src.management.group_settings import get_setting

        value = await get_setting(chat_id, "moderation_level")
    except Exception as exc:
        logger.warning("moderation_level_read_failed", chat_id=chat_id, error=type(exc).__name__)
        return "moderate"
    return value if value in {"light", "moderate", "strict"} else "moderate"


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="ignore")
    return str(value or "")


def _safe_level(value: Any) -> str:
    level = _as_text(value)
    return level if level in {"light", "moderate", "strict"} else "moderate"


def _safe_float(val: str | None) -> float | None:
    if not val:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: str | None) -> int | None:
    if not val:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
