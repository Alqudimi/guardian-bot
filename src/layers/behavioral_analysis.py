"""
User Behavioral Analysis Layer
-------------------------------
Maintains dynamic per-user profiles stored in Redis (hot) and PostgreSQL (cold).
- Message frequency patterns
- Historical violation tracking
- Trust score computation
- Activity consistency analysis
- Long-term behavior trend evaluation
"""
from __future__ import annotations

import time

from sqlalchemy import select

from config.settings import get_settings
from src.db.models import GroupMember, User
from src.db.session import db_session
from src.pipeline.context import PipelineContext
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)


async def _get_or_create_member(
    user_id: int,
    chat_id: int,
    username: str | None,
    first_name: str | None,
) -> tuple[float, float, int, int]:
    """
    Returns (trust_score, risk_index, violation_count, warn_count).
    Creates DB records if not present.
    """
    settings = get_settings()
    async with db_session() as session:
        # Upsert user
        result = await session.execute(select(User).where(User.id == user_id))
        user_obj = result.scalar_one_or_none()
        if not user_obj:
            user_obj = User(
                id=user_id,
                username=username,
                first_name=first_name,
            )
            session.add(user_obj)

        # Upsert group_member
        result = await session.execute(
            select(GroupMember).where(
                GroupMember.user_id == user_id,
                GroupMember.group_id == chat_id,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            member = GroupMember(
                user_id=user_id,
                group_id=chat_id,
                trust_score=settings.trust_score_initial,
            )
            session.add(member)
            await session.flush()

        return (
            member.trust_score,
            member.risk_index,
            member.violation_count,
            member.warn_count,
        )


async def update_trust_score(
    user_id: int,
    chat_id: int,
    delta: float,
    reason: str = "",
) -> float:
    """
    Adjusts trust score for a member and persists to DB.
    Returns the new trust score.
    """
    settings = get_settings()
    async with db_session() as session:
        result = await session.execute(
            select(GroupMember).where(
                GroupMember.user_id == user_id,
                GroupMember.group_id == chat_id,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            return settings.trust_score_initial

        new_score = max(
            settings.trust_score_min,
            min(settings.trust_score_max, member.trust_score + delta),
        )
        member.trust_score = new_score
        if delta < 0:
            member.violation_count += 1

        logger.debug(
            "trust_score_updated",
            user_id=user_id,
            chat_id=chat_id,
            delta=delta,
            new_score=new_score,
            reason=reason,
        )
        return new_score


async def run_behavioral_analysis(ctx: PipelineContext) -> None:
    if ctx.short_circuit:
        return

    settings = get_settings()
    user_id = ctx.user_id
    chat_id = ctx.chat_id
    redis = await get_redis()
    prefix = settings.redis_prefix
    now = time.time()

    # ── 1. Load profile from Redis cache (fast path) ──────────────────────────
    cache_key = f"{prefix}profile:{chat_id}:{user_id}"
    cached_trust = await redis.hget(cache_key, "trust_score")
    cached_violations = await redis.hget(cache_key, "violation_count")

    if cached_trust is not None:
        trust_score = float(cached_trust)
        violation_count = int(cached_violations or 0)
        warn_count = int(await redis.hget(cache_key, "warn_count") or 0)
        risk_index = float(await redis.hget(cache_key, "risk_index") or 0)
    else:
        # Fallback to DB
        try:
            trust_score, risk_index, violation_count, warn_count = (
                await _get_or_create_member(
                    user_id,
                    chat_id,
                    ctx.user.username,
                    ctx.user.first_name,
                )
            )
        except Exception as exc:
            logger.warning("behavioral_db_error", error=str(exc))
            trust_score = settings.trust_score_initial
            risk_index = 0.0
            violation_count = 0
            warn_count = 0

        # Populate Redis cache (TTL 5 min)
        await redis.hset(
            cache_key,
            mapping={
                "trust_score": trust_score,
                "risk_index": risk_index,
                "violation_count": violation_count,
                "warn_count": warn_count,
            },
        )
        await redis.expire(cache_key, 300)

    # ── 2. Account age ─────────────────────────────────────────────────────────
    # Telegram does not provide account creation time in a regular message
    # update. Do not infer age from the numeric user ID.
    is_new_account = False
    account_age_days: int | None = None

    # ── 3. Message-rate anomaly detection ─────────────────────────────────────
    rate_key = f"{prefix}rate_history:{chat_id}:{user_id}"
    await redis.lpush(rate_key, now)
    await redis.ltrim(rate_key, 0, 99)
    await redis.expire(rate_key, 3600)
    history = await redis.lrange(rate_key, 0, -1)

    message_rate_anomaly = False
    if len(history) >= 10:
        timestamps = sorted([float(t) for t in history])
        recent = timestamps[-10:]
        intervals = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
        if intervals:
            avg_interval = sum(intervals) / len(intervals)
            if avg_interval < 0.5:  # > 2 messages/sec sustained
                message_rate_anomaly = True

    # ── 4. Compute behavioral risk score ─────────────────────────────────────
    behavioral_risk = 0.0

    # Low trust penalty
    if trust_score < 20:
        behavioral_risk += 40.0
    elif trust_score < 40:
        behavioral_risk += 20.0

    # Violation history
    behavioral_risk += min(30.0, violation_count * 5.0)
    behavioral_risk += min(15.0, warn_count * 5.0)

    # Rate anomaly
    if message_rate_anomaly:
        behavioral_risk += 20.0

    behavioral_risk = min(100.0, behavioral_risk)

    # ── 5. Populate context ───────────────────────────────────────────────────
    ctx.behavior.trust_score = trust_score
    ctx.behavior.risk_index = risk_index
    ctx.behavior.violation_count = violation_count
    ctx.behavior.warn_count = warn_count
    ctx.behavior.is_new_account = is_new_account
    ctx.behavior.account_age_days = account_age_days
    ctx.behavior.message_rate_anomaly = message_rate_anomaly
    ctx.behavior.behavioral_risk = behavioral_risk

    logger.debug(
        "behavioral_analysis_complete",
        user_id=user_id,
        chat_id=chat_id,
        trust_score=trust_score,
        violation_count=violation_count,
        is_new_account=is_new_account,
        behavioral_risk=behavioral_risk,
    )
