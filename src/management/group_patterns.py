"""Per-group content pattern storage and bounded compilation."""
from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

import regex as re2

from config.settings import get_settings
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

_PATTERN_TYPES = {"regex", "literal"}
_CATEGORIES = {"spam", "scam", "adult", "phishing", "abuse", "other"}
_MAX_PATTERN_LENGTH = 512
_MAX_PATTERNS_PER_GROUP = 100
_CACHE_TTL = 600


@dataclass(frozen=True)
class GroupPattern:
    pattern_id: str
    pattern_type: str
    category: str
    pattern: str


def _key(chat_id: int) -> str:
    return f"{get_settings().redis_prefix}group_patterns:{chat_id}"


def _cache_key(chat_id: int) -> str:
    return f"{_key(chat_id)}:compiled"


def _decode(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _serialize(item: GroupPattern) -> str:
    return json.dumps(
        {
            "id": item.pattern_id,
            "type": item.pattern_type,
            "category": item.category,
            "pattern": item.pattern,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _deserialize(raw: bytes | str) -> GroupPattern | None:
    try:
        data = json.loads(_decode(raw))
        item = GroupPattern(
            pattern_id=str(data["id"]),
            pattern_type=str(data["type"]),
            category=str(data["category"]),
            pattern=str(data["pattern"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if item.pattern_type not in _PATTERN_TYPES or item.category not in _CATEGORIES:
        return None
    if not item.pattern or len(item.pattern) > _MAX_PATTERN_LENGTH:
        return None
    return item


async def add_group_pattern(
    chat_id: int,
    pattern_type: str,
    category: str,
    pattern: str,
) -> GroupPattern:
    if pattern_type not in _PATTERN_TYPES:
        raise ValueError("pattern_type must be regex or literal")
    if category not in _CATEGORIES:
        raise ValueError("unsupported pattern category")
    if not pattern or len(pattern) > _MAX_PATTERN_LENGTH:
        raise ValueError("pattern length is invalid")
    if pattern_type == "regex":
        try:
            re2.compile(pattern, re2.IGNORECASE | re2.UNICODE)
        except re2.error as exc:
            raise ValueError("invalid regular expression") from exc

    item = GroupPattern(uuid4().hex[:12], pattern_type, category, pattern)
    redis = await get_redis()
    key = _key(chat_id)
    if int(await redis.hlen(key) or 0) >= _MAX_PATTERNS_PER_GROUP:
        raise ValueError("group pattern limit reached")
    await redis.hset(key, item.pattern_id, _serialize(item))
    await invalidate_group_pattern_cache(chat_id)
    logger.info("group_pattern_added", chat_id=chat_id, pattern_id=item.pattern_id)
    return item


async def list_group_patterns(chat_id: int) -> list[GroupPattern]:
    redis = await get_redis()
    raw = await redis.hgetall(_key(chat_id))
    patterns: list[GroupPattern] = []
    for value in raw.values():
        item = _deserialize(value)
        if item is not None:
            patterns.append(item)
    return sorted(patterns, key=lambda item: item.pattern_id)


async def remove_group_pattern(chat_id: int, pattern_id: str) -> bool:
    if not pattern_id or len(pattern_id) > 32:
        return False
    redis = await get_redis()
    removed = int(await redis.hdel(_key(chat_id), pattern_id) or 0)
    if removed:
        await invalidate_group_pattern_cache(chat_id)
        logger.info("group_pattern_removed", chat_id=chat_id, pattern_id=pattern_id)
    return bool(removed)


async def invalidate_group_pattern_cache(chat_id: int) -> None:
    redis = await get_redis()
    key = _cache_key(chat_id)
    await redis.delete(key, f"{key}:empty")


async def load_compiled_group_patterns(chat_id: int) -> list[tuple[str, re2.Pattern]]:
    redis = await get_redis()
    key = _cache_key(chat_id)
    if await redis.exists(f"{key}:empty"):
        return []
    cached = await redis.lrange(key, 0, -1)
    if not cached:
        patterns = await list_group_patterns(chat_id)
        values: list[str] = []
        for item in patterns:
            values.append(_serialize(item))
        if not values:
            await redis.setex(f"{key}:empty", _CACHE_TTL, "1")
            return []
        pipe = redis.pipeline()
        pipe.rpush(key, *values)
        pipe.expire(key, _CACHE_TTL)
        await pipe.execute()
        cached = values

    compiled: list[tuple[str, re2.Pattern]] = []
    for raw in cached:
        item = _deserialize(raw)
        if item is None:
            continue
        source = re2.escape(item.pattern) if item.pattern_type == "literal" else item.pattern
        try:
            compiled.append((item.category, re2.compile(source, re2.IGNORECASE | re2.UNICODE)))
        except re2.error:
            logger.warning("group_pattern_compile_skipped", chat_id=chat_id)
    return compiled
