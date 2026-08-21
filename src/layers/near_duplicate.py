"""
Near-Duplicate Detection — SimHash-Based Content Similarity
============================================================
Detects messages that are slightly modified versions of previously
flagged or banned content. Uses a SimHash approach built with mmh3
(MurmurHash3) to compute content fingerprints without the simhash
package dependency.

Features:
1. **SimHash fingerprinting** — generates a 64-bit hash that allows
   Hamming-distance comparison. Two messages with <8 bits differing
   are considered near-duplicates (>87.5% similar).
2. **Sliding window history** — maintains a rolling Redis-backed
   window of recent message hashes per group.
3. **Flagged content database** — stores hashes of known bad content.
   Any near-match triggers an alert.
4. **Spam wave detection** — if N near-duplicate messages arrive from
   different users, flag as coordinated spam wave.
5. **Cross-group pattern sharing** — flagged content hashes are shared
   across groups for bot-wide protection.

Why SimHash over exact matching?
  Spammers regularly make small edits (add character, change word, use
  homoglyphs) to bypass exact-duplicate filters. SimHash is resilient
  to these small perturbations.
"""
from __future__ import annotations

import time

import mmh3

from config.settings import get_settings
from src.pipeline.context import PipelineContext
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

_HASH_BITS = 64
_SIMILARITY_THRESHOLD = 8       # Max Hamming distance for near-duplicate
_HISTORY_WINDOW_S = 300         # 5-min sliding window of message hashes
_SPAM_WAVE_THRESHOLD = 4        # N near-dupes from different users = wave
_FLAGGED_CONTENT_TTL_S = 86400  # 24h for flagged content hashes


def _tokenize(text: str) -> list[str]:
    """
    Tokenize text into weighted shingles (word n-grams of size 2).
    Handles both Arabic and Latin text.
    """
    # Simple word tokenization
    words = text.lower().split()
    if len(words) < 2:
        return words

    # Bi-grams
    tokens = []
    for i in range(len(words) - 1):
        tokens.append(f"{words[i]} {words[i+1]}")
    tokens.extend(words)
    return tokens


def compute_simhash(text: str) -> int:
    """
    Compute a 64-bit SimHash fingerprint for the given text.

    Algorithm:
    1. Tokenize text into weighted features
    2. For each feature, compute MurmurHash3
    3. For each bit position, sum +weight if bit=1, -weight if bit=0
    4. Final hash: bit=1 if sum > 0, else 0
    """
    if not text or len(text.strip()) < 3:
        return 0

    tokens = _tokenize(text)
    if not tokens:
        return 0

    # V[i] = running sum for bit position i
    v = [0] * _HASH_BITS

    for token in tokens:
        # Use mmh3 to get a 64-bit hash (returns 128-bit, take lower 64)
        h = mmh3.hash64(token, signed=False)[0]

        for i in range(_HASH_BITS):
            bit = (h >> i) & 1
            v[i] += 1 if bit else -1

    # Convert back to integer
    fingerprint = 0
    for i in range(_HASH_BITS):
        if v[i] > 0:
            fingerprint |= (1 << i)

    return fingerprint


def hamming_distance(h1: int, h2: int) -> int:
    """Count differing bits between two 64-bit hashes."""
    xor = h1 ^ h2
    # Brian Kernighan's bit count
    count = 0
    while xor:
        count += 1
        xor &= xor - 1
    return count


def are_near_duplicates(h1: int, h2: int, threshold: int = _SIMILARITY_THRESHOLD) -> bool:
    """Return True if two SimHashes are within the similarity threshold."""
    if h1 == 0 or h2 == 0:
        return False
    return hamming_distance(h1, h2) <= threshold


async def _get_recent_hashes(redis, chat_id: int) -> list[tuple[int, str, float]]:
    """
    Retrieve recent message hashes for a group.
    Returns list of (simhash, user_id, timestamp).
    """
    settings = get_settings()
    key = f"{settings.redis_prefix}simhash:{chat_id}"
    now = time.time()

    # Remove old entries
    await redis.zremrangebyscore(key, "-inf", now - _HISTORY_WINDOW_S)
    raw = await redis.zrangebyscore(key, now - _HISTORY_WINDOW_S, "+inf", withscores=True)

    result = []
    for member, score in raw:
        try:
            parts = member.split(":")
            if len(parts) >= 2:
                simhash_val = int(parts[0])
                user_id = parts[1]
                result.append((simhash_val, user_id, score))
        except Exception:
            pass

    return result


async def _store_hash(redis, chat_id: int, simhash: int, user_id: int, score: float) -> None:
    settings = get_settings()
    key = f"{settings.redis_prefix}simhash:{chat_id}"
    member = f"{simhash}:{user_id}"
    await redis.zadd(key, {member: score})
    await redis.expire(key, _HISTORY_WINDOW_S * 2)


async def _is_flagged_content(redis, simhash: int) -> bool:
    """Check if this hash matches known flagged content."""
    settings = get_settings()
    key = f"{settings.redis_prefix}flagged_hashes"
    members = await redis.smembers(key)
    for m in members:
        try:
            stored_hash = int(m)
            if are_near_duplicates(simhash, stored_hash):
                return True
        except Exception:
            pass
    return False


async def flag_content_hash(simhash: int) -> None:
    """Mark a SimHash as flagged bad content for future matching."""
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}flagged_hashes"
    await redis.sadd(key, str(simhash))
    await redis.expire(key, _FLAGGED_CONTENT_TTL_S)


async def run_near_duplicate_detection(ctx: PipelineContext) -> None:
    """
    Near-duplicate detection pipeline layer.
    Checks current message against recent group messages and flagged content.
    """
    if ctx.normalized is None or ctx.short_circuit:
        return

    text = ctx.normalized.clean_text.strip()
    if len(text) < 10:
        return

    redis = await get_redis()
    chat_id = ctx.chat_id
    user_id = ctx.user_id
    now = time.time()

    # Compute SimHash for this message
    current_hash = compute_simhash(text)
    if current_hash == 0:
        return

    # ── 1. Check against flagged content database ──────────────────────────────
    if await _is_flagged_content(redis, current_hash):
        ctx.spam.flood_score = min(100.0, ctx.spam.flood_score + 50.0)
        ctx.spam.duplicate_detected = True
        logger.warning(
            "near_dup_flagged_content",
            user_id=user_id,
            chat_id=chat_id,
        )

    # ── 2. Check against recent messages in group ──────────────────────────────
    recent = await _get_recent_hashes(redis, chat_id)
    near_dup_users: set[str] = set()
    own_near_dups = 0

    for stored_hash, stored_uid, stored_ts in recent:
        if are_near_duplicates(current_hash, stored_hash):
            if stored_uid == str(user_id):
                own_near_dups += 1
            else:
                near_dup_users.add(stored_uid)

    # User sending near-duplicates of their own messages
    if own_near_dups >= 2:
        ctx.spam.duplicate_detected = True
        ctx.spam.flood_score = min(100.0, ctx.spam.flood_score + 30.0)
        logger.info(
            "near_dup_own_messages",
            user_id=user_id,
            count=own_near_dups,
        )

    # Coordinated near-duplicate spam wave (multiple users, same content)
    if len(near_dup_users) >= _SPAM_WAVE_THRESHOLD:
        ctx.spam.coordinated_score = min(
            100.0,
            ctx.spam.coordinated_score + len(near_dup_users) * 15.0,
        )
        ctx.spam.flood_score = min(100.0, ctx.spam.flood_score + 40.0)
        logger.warning(
            "near_dup_spam_wave",
            chat_id=chat_id,
            user_count=len(near_dup_users),
            current_user=user_id,
        )

    # ── 3. Store this message's hash ───────────────────────────────────────────
    await _store_hash(redis, chat_id, current_hash, user_id, now)

    logger.debug(
        "near_dup_complete",
        user_id=user_id,
        simhash=current_hash,
        near_dup_users=len(near_dup_users),
        own_near_dups=own_near_dups,
    )
