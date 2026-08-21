"""
Spam & Flood Detection Layer
----------------------------
- Sliding window rate limiting per user (Redis-backed)
- Burst detection for sudden message spikes
- Adaptive thresholds based on group activity
- Duplicate message detection (fingerprint TTL cache)
- Shannon entropy analysis of message content
- Coordinated spam detection across multiple users
"""
from __future__ import annotations

import math
import time
from collections import Counter
from uuid import uuid4

from config.settings import get_settings
from src.pipeline.context import PipelineContext
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)


def _shannon_entropy(text: str) -> float:
    """Compute normalized Shannon entropy of the text (0.0 – 1.0)."""
    if not text:
        return 0.0
    counts = Counter(text)
    total = len(text)
    entropy = -sum((c / total) * math.log2(c / total) for c in counts.values())
    max_entropy = math.log2(len(counts)) if len(counts) > 1 else 1.0
    return entropy / max_entropy if max_entropy > 0 else 0.0


async def _sliding_window_count(
    redis,
    key: str,
    window_seconds: int,
    now: float,
) -> int:
    """
    Redis sorted-set sliding window.
    Returns the number of events in the last `window_seconds`.
    """
    window_start = now - window_seconds
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, "-inf", window_start)
    pipe.zadd(key, {f"{now:.6f}:{uuid4().hex}": now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds * 2)
    results = await pipe.execute()
    return int(results[2])


async def run_flood_detection(ctx: PipelineContext) -> None:
    if ctx.normalized is None or ctx.short_circuit:
        return

    settings = get_settings()
    redis = await get_redis()
    user_id = ctx.user_id
    chat_id = ctx.chat_id
    now = time.time()
    prefix = settings.redis_prefix

    # ── Adaptive thresholds (per-group, cached 5 min) ─────────────────────────
    from src.intelligence.adaptive_thresholds import get_group_thresholds
    thresholds = await get_group_thresholds(chat_id)
    flood_max = thresholds.flood_max_messages or settings.flood_max_messages
    flood_window = thresholds.flood_window_seconds or settings.flood_window_seconds

    # ── 1. Sliding window flood check ────────────────────────────────────────
    flood_key = f"{prefix}flood:{chat_id}:{user_id}"
    msg_count = await _sliding_window_count(
        redis, flood_key, flood_window, now
    )
    if msg_count > flood_max:
        ctx.spam.flood_triggered = True
        ctx.spam.flood_score = min(
            100.0,
            ctx.spam.flood_score + (msg_count - flood_max) * 10,
        )
        logger.info(
            "flood_detected",
            user_id=user_id,
            chat_id=chat_id,
            msg_count=msg_count,
            window=flood_window,
            adaptive=thresholds.attack_mode,
        )

    # ── 2. Burst detection ────────────────────────────────────────────────────
    burst_key = f"{prefix}burst:{chat_id}:{user_id}"
    burst_count = await _sliding_window_count(
        redis, burst_key, settings.burst_window_seconds, now
    )
    if burst_count > settings.burst_max_messages:
        ctx.spam.burst_triggered = True
        ctx.spam.flood_score = min(100.0, ctx.spam.flood_score + 25.0)
        logger.info(
            "burst_detected",
            user_id=user_id,
            chat_id=chat_id,
            burst_count=burst_count,
        )

    # ── 3. Duplicate message detection ───────────────────────────────────────
    if ctx.normalized.fingerprint:
        # Exact repetition is a user-level signal. Cross-user coordination is
        # handled separately by the coordinated and near-duplicate paths.
        dup_key = f"{prefix}dup:{chat_id}:{user_id}:{ctx.normalized.fingerprint}"
        reserved = await redis.set(
            dup_key,
            "1",
            ex=settings.duplicate_window_seconds,
            nx=True,
        )
        if not reserved:
            ctx.spam.duplicate_detected = True
            ctx.spam.flood_score = min(100.0, ctx.spam.flood_score + 40.0)
            logger.info(
                "duplicate_detected",
                user_id=user_id,
                chat_id=chat_id,
                fingerprint=ctx.normalized.fingerprint,
            )

    # ── 4. Entropy analysis ───────────────────────────────────────────────────
    text = ctx.normalized.clean_text
    if text:
        entropy = _shannon_entropy(text)
        ctx.spam.entropy_score = entropy
        # Very low entropy = repetitive content (spam indicator)
        if entropy < 0.3 and len(text) > 20:
            ctx.spam.flood_score = min(100.0, ctx.spam.flood_score + 20.0)
        # Very high entropy in short message = gibberish / encoded payload
        elif entropy > 0.95 and len(text) < 30:
            ctx.spam.flood_score = min(100.0, ctx.spam.flood_score + 10.0)

    # ── 5. Coordinated spam detection ────────────────────────────────────────
    # Count distinct users sending the same fingerprint in this group
    if ctx.normalized.fingerprint:
        coord_key = f"{prefix}coord:{chat_id}:{ctx.normalized.fingerprint}"
        await redis.sadd(coord_key, str(user_id))
        await redis.expire(coord_key, settings.flood_window_seconds * 3)
        unique_senders = await redis.scard(coord_key)
        if unique_senders >= 3:
            ctx.spam.coordinated_score = min(100.0, unique_senders * 20.0)
            ctx.spam.flood_score = min(100.0, ctx.spam.flood_score + 30.0)
            logger.warning(
                "coordinated_spam_detected",
                chat_id=chat_id,
                fingerprint=ctx.normalized.fingerprint,
                unique_senders=unique_senders,
            )

    # ── 6. Media spam check ───────────────────────────────────────────────────
    if ctx.normalized.has_media:
        media_key = f"{prefix}media:{chat_id}:{user_id}"
        media_count = await _sliding_window_count(
            redis, media_key, settings.flood_window_seconds, now
        )
        if media_count > 3:
            ctx.spam.media_spam = True
            ctx.spam.flood_score = min(100.0, ctx.spam.flood_score + 15.0)

    logger.debug(
        "flood_detection_complete",
        user_id=user_id,
        chat_id=chat_id,
        flood_score=ctx.spam.flood_score,
        flood_triggered=ctx.spam.flood_triggered,
        burst_triggered=ctx.spam.burst_triggered,
        duplicate=ctx.spam.duplicate_detected,
        entropy=ctx.spam.entropy_score,
    )
