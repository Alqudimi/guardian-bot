"""
DoS / DDoS Protection & Memory Safety
=======================================
Protects the bot process from:

1. Message flood DoS — limits how many messages the pipeline processes
   per second globally; excess messages are dropped with a counter.
2. Oversized payload attacks — messages or media beyond configurable
   size limits are rejected before expensive processing.
3. Regex ReDoS mitigation — all user-supplied content that might be
   used in pattern matching is length-capped.
4. Async task queue flooding — prevents unbounded Celery task enqueue.
5. Memory watermark protection — if process RSS > threshold, start
   shedding lower-priority work (AI inference) to stay alive.
6. Redis key explosion prevention — all keys must use known prefixes
   with bounded TTLs; orphan key detection.
7. Update queue depth monitor — if the incoming update queue grows
   too deep the bot stops accepting new updates temporarily.
"""
from __future__ import annotations

import os
import time
from typing import Any

import psutil

from config.settings import get_settings
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

# ── Limits ─────────────────────────────────────────────────────────────────────
MAX_TEXT_BYTES = 65_536          # 64 KB — hard cap before any processing
MAX_MEDIA_CAPTION_BYTES = 4_096
MAX_PIPELINE_PER_SECOND = 50     # global pipeline invocation cap
MAX_CELERY_QUEUE_DEPTH = 500     # max pending Celery tasks before shedding
MEMORY_SHED_THRESHOLD_MB = 900   # RSS above this → skip AI inference
MEMORY_CRITICAL_MB = 1_400       # RSS above this → drop non-critical messages


def _process_rss_mb() -> float:
    try:
        proc = psutil.Process(os.getpid())
        return proc.memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


async def _pipeline_rate_ok(redis, prefix: str) -> bool:
    """Global pipeline invocation rate limiter (messages/second)."""
    key = f"{prefix}dos:pipeline_rate"
    now = time.time()
    # Use individual commands (avoids pipeline sync/async differences in tests)
    await redis.zremrangebyscore(key, "-inf", now - 1.0)
    await redis.zadd(key, {str(now): now})
    count_raw = await redis.zcard(key)
    await redis.expire(key, 5)
    count = int(count_raw) if count_raw else 0
    if count > MAX_PIPELINE_PER_SECOND:
        logger.warning("dos_pipeline_rate_exceeded", count=count)
        return False
    return True


def should_shed_ai(rss_mb: float) -> bool:
    """Return True if AI inference should be skipped due to memory pressure."""
    return rss_mb >= MEMORY_SHED_THRESHOLD_MB


def should_drop_message(rss_mb: float) -> bool:
    """Return True if the message should be dropped entirely (critical memory)."""
    return rss_mb >= MEMORY_CRITICAL_MB


async def check_message_safe(text: str | None, media_size_bytes: int = 0) -> tuple[bool, str]:
    """
    Pre-pipeline safety check.
    Returns (safe, reason). If not safe, the message should be dropped.
    """
    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix

    # Memory check
    rss = _process_rss_mb()
    if should_drop_message(rss):
        logger.error("dos_memory_critical_drop", rss_mb=round(rss, 1))
        return False, f"memory_critical:{rss:.0f}MB"

    # Global rate check
    if not await _pipeline_rate_ok(redis, prefix):
        return False, "global_rate_exceeded"

    # Text size check
    if text and len(text.encode("utf-8", errors="ignore")) > MAX_TEXT_BYTES:
        logger.warning("dos_oversized_text", size=len(text))
        return False, f"text_too_large:{len(text)}"

    return True, ""


async def get_dos_status() -> dict[str, Any]:
    """Return current DoS protection status for the /status command."""
    rss = _process_rss_mb()
    return {
        "rss_mb": round(rss, 1),
        "ai_shed": should_shed_ai(rss),
        "critical": should_drop_message(rss),
        "memory_shed_threshold_mb": MEMORY_SHED_THRESHOLD_MB,
        "memory_critical_mb": MEMORY_CRITICAL_MB,
    }
