"""
Fast Rules Engine
-----------------
Ultra-low-latency deterministic filtering. Runs before any AI inference.
Checks:
- Whitelist / blacklist
- Regex-based spam patterns (static + DB-backed dynamic patterns)
- Repeated character spam
- Mention spam (per-group configurable threshold)
- Link spam (per-group configurable threshold)
- Forwarded spam
- Media spam
Sets ctx.short_circuit = True to bypass AI layers when appropriate.
"""
from __future__ import annotations

import re

import regex as re2

from config.settings import get_settings
from src.db.models import BlacklistedPattern
from src.db.session import db_session
from src.management.group_patterns import load_compiled_group_patterns
from src.management.group_settings import get_setting
from src.pipeline.context import PipelineContext
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

# ── Dynamic DB-pattern cache ───────────────────────────────────────────────────
# Patterns are loaded from `blacklisted_patterns` table and cached in Redis
# for 10 minutes to avoid a DB hit on every message.
_DB_PATTERN_CACHE_KEY = "db_patterns:compiled"
_DB_PATTERN_CACHE_TTL = 600  # seconds
_MAX_DYNAMIC_PATTERN_LENGTH = 512
_DYNAMIC_SEARCH_TIMEOUT_SECONDS = 0.05


def _group_limit(value: object, default: int, maximum: int = 50) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(maximum, parsed))


async def _load_db_patterns() -> list[re2.Pattern]:
    """
    Load active patterns from the BlacklistedPattern DB table.
    Returns compiled regex objects. Results are cached in Redis.
    """
    redis = await get_redis()
    settings = get_settings()
    cache_key = f"{settings.redis_prefix}{_DB_PATTERN_CACHE_KEY}"

    # Check Redis cache first (stores raw pattern strings as a list).
    # The empty marker prevents repeated DB queries when no patterns exist.
    if await redis.exists(f"{cache_key}:empty"):
        return []
    cached_raw = await redis.lrange(cache_key, 0, -1)
    if cached_raw:
        compiled: list[re2.Pattern] = []
        for raw in cached_raw:
            if len(raw) > _MAX_DYNAMIC_PATTERN_LENGTH:
                logger.warning("db_pattern_skipped", reason="pattern_too_long")
                continue
            try:
                compiled.append(re2.compile(raw, re2.IGNORECASE | re2.UNICODE))
            except re2.error:
                logger.warning("db_pattern_skipped", reason="invalid_cached_pattern")
        return compiled

    # Cache miss — load from DB
    try:
        async with db_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(BlacklistedPattern).where(BlacklistedPattern.is_active)
            )
            rows = result.scalars().all()
    except Exception as exc:
        logger.warning("db_pattern_load_failed", error=str(exc))
        return []

    compiled: list[re2.Pattern] = []
    raw_patterns: list[str] = []

    for row in rows:
        if len(row.pattern) > _MAX_DYNAMIC_PATTERN_LENGTH:
            logger.warning("db_pattern_skipped", reason="pattern_too_long")
            continue
        try:
            if row.pattern_type == "literal":
                pat = re2.compile(re2.escape(row.pattern), re2.IGNORECASE | re2.UNICODE)
                cached_pattern = re2.escape(row.pattern)
            else:
                pat = re2.compile(row.pattern, re2.IGNORECASE | re2.UNICODE)
                cached_pattern = row.pattern
            compiled.append(pat)
            raw_patterns.append(cached_pattern)
        except re2.error as exc:
            logger.warning("db_pattern_compile_error", error=type(exc).__name__)

    # Store raw patterns in Redis list
    if raw_patterns:
        pipe = redis.pipeline()
        pipe.delete(cache_key)
        pipe.rpush(cache_key, *raw_patterns)
        pipe.expire(cache_key, _DB_PATTERN_CACHE_TTL)
        await pipe.execute()
    else:
        # Cache the empty result so we don't hammer the DB
        await redis.setex(f"{cache_key}:empty", _DB_PATTERN_CACHE_TTL, "1")

    logger.info("db_patterns_loaded", count=len(compiled))
    return compiled


async def invalidate_db_pattern_cache() -> None:
    """Call this after adding or removing a DB pattern so the cache refreshes."""
    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix
    pipe = redis.pipeline()
    pipe.delete(f"{prefix}{_DB_PATTERN_CACHE_KEY}")
    pipe.delete(f"{prefix}{_DB_PATTERN_CACHE_KEY}:empty")
    await pipe.execute()
    logger.info("db_pattern_cache_invalidated")

def _safe_dynamic_search(pattern: re2.Pattern, text: str) -> bool:
    """Search an untrusted dynamic pattern with strict input and time bounds."""
    if len(text) > 4096:
        return False
    try:
        return pattern.search(text, timeout=_DYNAMIC_SEARCH_TIMEOUT_SECONDS) is not None
    except (TimeoutError, re2.error):
        logger.warning("db_pattern_search_skipped", reason="regex_timeout_or_error")
        return False


# ── Static compiled patterns ──────────────────────────────────────────────────

_PHONE_SPAM = re.compile(
    r"(?:\+?[\d\s\-.(]{7,20}[\d])",
    re.UNICODE,
)

_CRYPTO_SCAM = re.compile(
    r"(?:free\s*(?:btc|eth|usdt|crypto)|airdrop|(?:100|200|500)x|"
    r"guaranteed\s*profit|(?:investment|invest)\s*(?:now|today)|"
    r"double\s*your\s*(?:money|btc|eth))",
    re.IGNORECASE | re.UNICODE,
)

_ADULT_KEYWORDS = re.compile(
    r"(?:18\+|xxx|porn|nude|naked|onlyfans|cam\s*(?:girl|boy|live))",
    re.IGNORECASE | re.UNICODE,
)

_ARABIC_SCAM = re.compile(
    r"(?:ربح|مكسب|استثمار|تداول|عملة|دخل|مال|ثروة|مجاني|هدية|جائزة)"
    r".{0,20}(?:الآن|اليوم|سريع|فوري|ضمان)",
    re.UNICODE,
)

_MENTION_PATTERN = re.compile(r"@\w+", re.UNICODE)

# Patterns that immediately warrant block (very high confidence)
_INSTANT_BLOCK: list[re.Pattern] = [
    re.compile(r"@everyone|@here", re.IGNORECASE),
    re.compile(
        r"(?:t\.me/|telegram\.me/)(?:joinchat|\+)[A-Za-z0-9_-]{10,}",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:wa\.me|whatsapp\.com/invite)[/A-Za-z0-9_?=&]+",
        re.IGNORECASE,
    ),
]


async def _check_whitelist(user_id: int, chat_id: int) -> bool:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}wl:{chat_id}:{user_id}"
    return bool(await redis.exists(key))


async def _check_blacklist(user_id: int, chat_id: int) -> bool:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}bl:{chat_id}:{user_id}"
    return bool(await redis.exists(key))


async def _check_global_blacklist(user_id: int) -> bool:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}gbl:{user_id}"
    return bool(await redis.exists(key))


async def run_fast_rules(ctx: PipelineContext) -> None:
    """
    Evaluate deterministic rules. Sets ctx.spam flags and possibly
    ctx.short_circuit = True for whitelist hits (allow) or blacklist hits (block).
    """
    if ctx.normalized is None:
        return

    text = ctx.normalized.clean_text
    user_id = ctx.user_id
    chat_id = ctx.chat_id

    # ── 1. Whitelist check (allow fast-path) ─────────────────────────────────
    if await _check_whitelist(user_id, chat_id):
        ctx.spam.whitelist_hit = True
        ctx.short_circuit = True
        ctx.decision.action = "allow"
        ctx.decision.reason = "whitelist"
        logger.debug("whitelist_hit", user_id=user_id, chat_id=chat_id)
        return

    # ── 2. Blacklist check (block fast-path) ─────────────────────────────────
    if await _check_blacklist(user_id, chat_id) or await _check_global_blacklist(user_id):
        ctx.spam.blacklist_hit = True
        ctx.short_circuit = True
        ctx.spam.fast_rule_block = True
        ctx.decision.action = "ban_perm"
        ctx.decision.reason = "blacklist"
        logger.info("blacklist_hit", user_id=user_id, chat_id=chat_id)
        return

    # ── 3. Instant block patterns ─────────────────────────────────────────────
    for pattern in _INSTANT_BLOCK:
        if pattern.search(text):
            ctx.spam.fast_rule_block = True
            ctx.spam.blacklist_hit = True
            ctx.short_circuit = True
            ctx.decision.action = "delete"
            ctx.decision.reason = f"instant_block_pattern:{pattern.pattern[:40]}"
            logger.info(
                "instant_block_pattern",
                user_id=user_id,
                chat_id=chat_id,
                pattern=pattern.pattern[:60],
            )
            return

    # ── 4. Invite link in message ─────────────────────────────────────────────
    if ctx.normalized.has_invite_link:
        ctx.spam.link_spam = True
        ctx.spam.flood_score = max(ctx.spam.flood_score, 50.0)

    # ── 5. Mention spam (per-group configurable threshold) ────────────────────
    mention_limit_str = await get_setting(chat_id, "max_mentions")
    mention_limit = _group_limit(mention_limit_str, default=5)
    if ctx.normalized.mention_count >= mention_limit:
        ctx.spam.mention_spam = True
        ctx.spam.flood_score = max(ctx.spam.flood_score, 60.0)

    # ── 6. Link spam (per-group configurable threshold) ───────────────────────
    link_limit_str = await get_setting(chat_id, "max_links")
    link_limit = _group_limit(link_limit_str, default=3)
    if len(ctx.normalized.urls) >= link_limit:
        ctx.spam.link_spam = True
        ctx.spam.flood_score = max(ctx.spam.flood_score, 55.0)

    # ── 7. Forwarded spam heuristics ──────────────────────────────────────────
    if ctx.normalized.is_forwarded and len(ctx.normalized.urls) >= 1:
        ctx.spam.forwarded_spam = True
        ctx.spam.flood_score = max(ctx.spam.flood_score, 40.0)

    # ── 8. Media spam via rapid media sends (checked in flood layer) ──────────
    if ctx.normalized.has_media and not text:
        ctx.spam.media_spam = True

    # ── 9. Crypto / scam regex ────────────────────────────────────────────────
    if _CRYPTO_SCAM.search(text):
        ctx.spam.flood_score = max(ctx.spam.flood_score, 70.0)
        ctx.spam.fast_rule_block = True
        ctx.short_circuit = True
        ctx.decision.action = "delete"
        ctx.decision.reason = "crypto_scam_pattern"

    # ── 10. Adult keyword regex ───────────────────────────────────────────────
    if _ADULT_KEYWORDS.search(text):
        ctx.spam.flood_score = max(ctx.spam.flood_score, 60.0)

    # ── 11. Arabic scam pattern ───────────────────────────────────────────────
    if _ARABIC_SCAM.search(text):
        ctx.spam.flood_score = max(ctx.spam.flood_score, 65.0)
        ctx.spam.fast_rule_block = True
        ctx.short_circuit = True
        ctx.decision.action = "delete"
        ctx.decision.reason = "arabic_scam_pattern"

    # ── 12. Zalgo = obfuscation attempt ───────────────────────────────────────
    if ctx.normalized.zalgo_detected:
        ctx.spam.flood_score = max(ctx.spam.flood_score, 30.0)

    # ── 13. Per-group content patterns ────────────────────────────────────────
    for category, pattern in await load_compiled_group_patterns(chat_id):
        try:
            matched = pattern.search(text, timeout=_DYNAMIC_SEARCH_TIMEOUT_SECONDS) is not None
        except (TimeoutError, re2.error):
            logger.warning("group_pattern_search_skipped", chat_id=chat_id)
            continue
        if matched:
            ctx.spam.fast_rule_block = True
            ctx.spam.flood_score = max(ctx.spam.flood_score, 60.0)
            ctx.short_circuit = True
            ctx.decision.action = "delete"
            ctx.decision.reason = f"group_pattern:{category}"
            logger.info(
                "group_pattern_hit",
                user_id=user_id,
                chat_id=chat_id,
                category=category,
            )
            return

    # ── 14. Dynamic DB-backed patterns ────────────────────────────────────────
    db_patterns = await _load_db_patterns()
    for pat in db_patterns:
        if _safe_dynamic_search(pat, text):
            ctx.spam.fast_rule_block = True
            ctx.short_circuit = True
            ctx.decision.action = "delete"
            ctx.decision.reason = f"db_pattern:{pat.pattern[:60]}"
            logger.info(
                "db_pattern_hit",
                user_id=user_id,
                chat_id=chat_id,
                pattern=pat.pattern[:60],
            )
            break  # First match is enough to block

    logger.debug(
        "fast_rules_complete",
        user_id=user_id,
        chat_id=chat_id,
        flood_score=ctx.spam.flood_score,
        fast_block=ctx.spam.fast_rule_block,
        link_spam=ctx.spam.link_spam,
        mention_spam=ctx.spam.mention_spam,
    )
