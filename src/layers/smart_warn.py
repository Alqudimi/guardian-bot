"""
Smart Warn System — Escalating Punishment Ladder
==================================================
Replaces the simple warn counter with a full escalating punishment
system that remembers per-user, per-group history and automatically
escalates punishments on repeated violations.

Warn ladder (per group, configurable):
  Warn 1 → Delete + send warning message
  Warn 2 → Delete + mute (10 min)
  Warn 3 → Delete + mute (1 hour)
  Warn 4 → Delete + temporary ban (24 hours)
  Warn 5 → Delete + permanent ban

Each warn record includes:
  - Timestamp (for decay calculation)
  - Violation type (spam / toxic / nsfw / etc.)
  - Risk score at time of warn
  - Action taken

Warn decay:
  - Warns older than WARN_DECAY_DAYS are discounted
  - Active warn count = warns within decay window
  - Full warn history is preserved for analytics

Admin overrides:
  /resetwarns <user_id>  — reset warn count for user in this group
  /warns <user_id>       — view warn history
  /setwarnlimit <n>      — set max warns before ban (default 5)
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

from redis.exceptions import WatchError

from config.settings import get_settings
from src.management.group_settings import get_setting, set_setting
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

WARN_DECAY_DAYS = 30         # Warns older than this are discounted
DEFAULT_MAX_WARNS = 5        # Warns before permanent ban
_WARN_HISTORY_RETRIES = 4
_WARN_RETRY_DELAY_SECONDS = 0.01


@dataclass
class WarnRecord:
    timestamp: float
    violation_type: str
    risk_score: float
    action_taken: str
    message_preview: str = ""


@dataclass
class WarnStatus:
    active_warn_count: int
    total_warn_count: int
    next_action: str
    next_mute_seconds: int
    next_ban_seconds: int
    history: list[WarnRecord] = field(default_factory=list)


def _build_ladder(max_warns: int = DEFAULT_MAX_WARNS) -> list[dict]:
    """
    Build the escalation ladder based on max_warns.
    """
    return [
        {"action": "warn_delete",  "mute": 0,       "ban": 0},
        {"action": "mute_temp",    "mute": 600,     "ban": 0},
        {"action": "mute_temp",    "mute": 3600,    "ban": 0},
        {"action": "ban_temp",     "mute": 0,       "ban": 86400},
        {"action": "ban_perm",     "mute": 0,       "ban": 0},
    ]


async def get_max_warns(chat_id: int) -> int:
    """Read the effective warning limit from canonical group settings."""
    raw = await get_setting(chat_id, "warn_limit")
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        logger.warning("warn_limit_invalid_at_runtime", chat_id=chat_id)
        return DEFAULT_MAX_WARNS
    return max(1, min(10, limit))


async def set_max_warns(chat_id: int, limit: int) -> None:
    """Persist the warning limit through the canonical group-settings manager."""
    if not 1 <= limit <= 10:
        raise ValueError("Warn limit must be between 1 and 10")
    await set_setting(chat_id, "warn_limit", str(limit))


def _decode_warn_history(raw: str | bytes | None) -> list[WarnRecord]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [WarnRecord(**record) for record in data]
    except (TypeError, ValueError, KeyError):
        return []


def _warn_status(history: list[WarnRecord], max_warns: int, cutoff: float) -> WarnStatus:
    active = [record for record in history if record.timestamp > cutoff]
    ladder = _build_ladder(max_warns)
    ladder_idx = min(len(active) - 1, len(ladder) - 1)
    step = ladder[ladder_idx]
    return WarnStatus(
        active_warn_count=len(active),
        total_warn_count=len(history),
        next_action=step["action"],
        next_mute_seconds=step["mute"],
        next_ban_seconds=step["ban"],
        history=history[-5:],
    )


async def add_warn(
    user_id: int,
    chat_id: int,
    violation_type: str,
    risk_score: float,
    message_preview: str = "",
) -> WarnStatus:
    """Atomically append a warn and return the committed escalation status."""
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}warns:{chat_id}:{user_id}"
    now = time.time()
    cutoff = now - (WARN_DECAY_DAYS * 86400)
    max_warns = await get_max_warns(chat_id)
    new_warn = WarnRecord(
        timestamp=now,
        violation_type=violation_type,
        risk_score=risk_score,
        action_taken="pending",
        message_preview=message_preview[:100],
    )

    committed_history: list[WarnRecord] | None = None
    for attempt in range(_WARN_HISTORY_RETRIES):
        try:
            async with redis.pipeline(transaction=True) as pipe:
                await pipe.watch(key)
                raw = await pipe.get(key)
                history = _decode_warn_history(raw)
                history.append(new_warn)
                history_data = [vars(record) for record in history[-50:]]
                pipe.multi()
                pipe.set(key, json.dumps(history_data))
                pipe.expire(key, (WARN_DECAY_DAYS + 10) * 86400)
                await pipe.execute()
            committed_history = history
            break
        except WatchError:
            if attempt == _WARN_HISTORY_RETRIES - 1:
                logger.error(
                    "warn_history_conflict_exhausted",
                    user_id=user_id,
                    chat_id=chat_id,
                    retries=_WARN_HISTORY_RETRIES,
                )
                raise
            await asyncio.sleep(_WARN_RETRY_DELAY_SECONDS * (attempt + 1))

    if committed_history is None:
        raise RuntimeError("warn history was not committed")

    status = _warn_status(committed_history, max_warns, cutoff)
    logger.info(
        "warn_added",
        user_id=user_id,
        chat_id=chat_id,
        active_count=status.active_warn_count,
        next_action=status.next_action,
        violation=violation_type,
    )
    return status


async def reset_warns(user_id: int, chat_id: int) -> None:
    """Reset all warns for a user in a specific group."""
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}warns:{chat_id}:{user_id}"
    await redis.delete(key)
    logger.info("warns_reset", user_id=user_id, chat_id=chat_id)


async def get_warn_status(user_id: int, chat_id: int) -> WarnStatus:
    """Get current warn status without adding a warn."""
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}warns:{chat_id}:{user_id}"
    now = time.time()
    decay_cutoff = now - (WARN_DECAY_DAYS * 86400)

    raw = await redis.get(key)
    history: list[WarnRecord] = []
    if raw:
        try:
            data = json.loads(raw)
            history = [WarnRecord(**r) for r in data]
        except Exception:
            pass

    active = [w for w in history if w.timestamp > decay_cutoff]
    max_warns = await get_max_warns(chat_id)
    ladder = _build_ladder(max_warns)
    ladder_idx = min(len(active), len(ladder) - 1)
    step = ladder[ladder_idx]

    return WarnStatus(
        active_warn_count=len(active),
        total_warn_count=len(history),
        next_action=step["action"],
        next_mute_seconds=step["mute"],
        next_ban_seconds=step["ban"],
        history=history[-5:],
    )
