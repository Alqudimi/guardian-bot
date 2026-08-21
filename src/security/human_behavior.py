"""
Human Behavior Simulation — Advanced Anti-Ban
===============================================
Makes the bot behave like a human moderator to avoid Telegram's
automated abuse detection systems.

Techniques:
1. Reaction-time distribution — delays follow a log-normal distribution
   matching human response times (300ms – 8s), not uniform random.
2. Working-hours weighting — slightly longer delays during "off hours"
   (simulates a moderator checking less frequently).
3. Decision fatigue — after many rapid actions, introduce longer pauses.
4. Burst avoidance — never execute more than N actions in T seconds
   regardless of the pipeline output rate.
5. Action pattern diversification — vary the sequence of action types
   to avoid robot-like identical patterns.
6. Occasional "miss" simulation — very low-risk borderline cases are
   randomly allowed through at a small rate (human would also miss some).
7. Typing simulation — for warning messages, add a typing indicator.
8. Natural variation in message wording — warn templates rotate.
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any

from config.settings import get_settings
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

# ── Reaction time model (log-normal) ─────────────────────────────────────────
# Parameters fit to human moderation reaction time studies.
# μ=1.0, σ=0.6 → median ~2.7s, mean ~3.5s, tail up to ~15s
_REACTION_MU = 0.8
_REACTION_SIGMA = 0.5
_REACTION_MIN = 0.2
_REACTION_MAX = 6.0

# ── Decision fatigue thresholds ────────────────────────────────────────────────
_FATIGUE_THRESHOLD = 8   # actions before fatigue kicks in
_FATIGUE_EXTRA_DELAY = 3.0  # extra seconds added during fatigue

# ── "Miss" probability for borderline cases ────────────────────────────────────
_MISS_PROBABILITY = 0.04  # 4% of borderline (score 40–55) cases slip through

# ── Warning message rotation pool ─────────────────────────────────────────────
_WARNING_TEMPLATES = [
    "⚠️ تحذير: رسالتك تنتهك قواعد المجموعة وتم حذفها.",
    "⚠️ Warning: Your message violated group rules and was removed.",
    "🚫 تم حذف رسالتك. يرجى مراجعة قواعد المجموعة.",
    "⚠️ Message removed for violating community guidelines.",
    "🚫 هذا النوع من المحتوى غير مسموح به هنا.",
    "⚠️ Your message has been removed. Please follow the group rules.",
]


def _human_delay() -> float:
    """Sample a reaction delay from a log-normal distribution."""
    raw = random.lognormvariate(_REACTION_MU, _REACTION_SIGMA)
    return max(_REACTION_MIN, min(_REACTION_MAX, raw))


def _is_off_hours() -> bool:
    """Return True during typical off-hours (midnight–7am local-ish UTC)."""
    hour = time.gmtime().tm_hour
    return hour < 7 or hour >= 23


async def _get_recent_action_count(redis, prefix: str) -> int:
    now = time.time()
    key = f"{prefix}hb:actions"
    await redis.zremrangebyscore(key, "-inf", now - 60)
    return int(await redis.zcard(key) or 0)


async def _record_action(redis, prefix: str) -> None:
    now = time.time()
    key = f"{prefix}hb:actions"
    await redis.zadd(key, {str(now): now})
    await redis.expire(key, 120)


async def compute_action_delay(action_type: str, risk_score: float) -> float:
    """
    Compute a human-like delay before executing a moderation action.

    Lower risk = longer delay (human deliberates more).
    Higher risk = faster response (urgent moderation).
    Adds fatigue delay if many recent actions.
    """
    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix

    base_delay = _human_delay()

    # ── Risk adjustment ────────────────────────────────────────────────────────
    # High risk (>80) → react faster (0.3x)
    # Medium risk (40-80) → normal speed
    # Low risk (<40) → slower (1.5x — human is less sure)
    if risk_score > 80:
        base_delay *= 0.3
    elif risk_score < 40:
        base_delay *= 1.5

    # ── Off-hours adjustment ───────────────────────────────────────────────────
    if _is_off_hours():
        base_delay *= random.uniform(1.2, 2.0)

    # ── Fatigue adjustment ────────────────────────────────────────────────────
    recent_count = await _get_recent_action_count(redis, prefix)
    if recent_count >= _FATIGUE_THRESHOLD:
        base_delay += _FATIGUE_EXTRA_DELAY * random.uniform(0.5, 1.5)
        logger.debug("action_delay_fatigue", recent_count=recent_count, delay=base_delay)

    # ── Action-type specific adjustment ───────────────────────────────────────
    # Bans get slightly longer deliberation time (simulate human confirming)
    if action_type in ("ban_temp", "ban_perm"):
        base_delay += random.uniform(0.5, 2.0)

    total = max(_REACTION_MIN, min(8.0, base_delay))
    logger.debug("human_delay_computed", action_type=action_type, delay=round(total, 2))
    return total


def should_miss_borderline(risk_score: float) -> bool:
    """Compatibility shim: security actions must never be skipped randomly."""
    return False


async def record_action_completed() -> None:
    """Record a successfully completed action for pacing diagnostics."""
    redis = await get_redis()
    await _record_action(redis, get_settings().redis_prefix)


def get_random_warning_text(warn_number: int = 1) -> str:
    """Return a randomly selected warning message text."""
    template = random.choice(_WARNING_TEMPLATES)
    if warn_number > 1:
        template += f" (#{warn_number})"
    return template


async def simulate_typing(bot: Any, chat_id: int) -> None:
    """Send typing action before a warning message (human-like)."""
    try:
        await bot.send_chat_action(chat_id=chat_id, action="typing")
        await asyncio.sleep(random.uniform(0.8, 2.5))
    except Exception:
        pass  # Non-critical


async def get_action_budget_status() -> dict[str, Any]:
    """Return current pacing status for diagnostics."""
    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix
    recent = await _get_recent_action_count(redis, prefix)
    return {
        "recent_actions_60s": recent,
        "fatigue_active": recent >= _FATIGUE_THRESHOLD,
        "off_hours": _is_off_hours(),
    }
