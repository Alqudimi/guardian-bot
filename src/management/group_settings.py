"""
Group Settings Manager
=======================
Centralized per-group configuration storage backed by Redis.
All bot behaviours that are configurable per-group are stored here.

Settings schema (stored as Redis hash at key: group_settings:{chat_id}):
  captcha          — "on" | "off"          (CAPTCHA for new members)
  antiforward      — "off" | "on" | "strict"
  lang_policy      — "any" | "ar" | "en" | "ar+en" | "ru"
  warn_limit       — integer (1-10)
  modlog_channel   — integer (channel ID for forwarding moderation events)
  welcome_msg      — string (custom welcome message, {name} placeholder)
  welcome_enabled  — "on" | "off"
  leave_msg        — string (custom leave message, {name} placeholder)
  leave_enabled    — "on" | "off"
  rules_text       — string (group rules)
  moderation_level — "light" | "moderate" | "strict"
  anti_raid        — "on" | "off"
  max_links        — integer (max URLs per message)
  max_mentions     — integer (max @mentions per message)
  silent_mode      — "on" | "off" (delete without sending any messages)
  smart_responses  — "on" | "off" (automatic contextual replies)
"""
from __future__ import annotations

from typing import Any

from config.settings import get_settings
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

_DEFAULTS: dict[str, Any] = {
    "captcha": "off",
    "antiforward": "off",
    "lang_policy": "any",
    "warn_limit": "5",
    "modlog_channel": "",
    "welcome_msg": "👋 مرحباً {name}! Welcome {name}!",
    "welcome_enabled": "off",
    "leave_msg": "👋 غادر {name} المجموعة.",
    "leave_enabled": "off",
    "rules_text": "",
    "moderation_level": "moderate",
    "anti_raid": "on",
    "max_links": "5",
    "max_mentions": "10",
    "silent_mode": "off",
    "smart_responses": "on",
}

_VALID_VALUES: dict[str, set[str]] = {
    "captcha": {"on", "off"},
    "antiforward": {"off", "on", "strict"},
    "lang_policy": {"any", "ar", "en", "ar+en", "fr", "ru"},
    "moderation_level": {"light", "moderate", "strict"},
    "anti_raid": {"on", "off"},
    "welcome_enabled": {"on", "off"},
    "leave_enabled": {"on", "off"},
    "silent_mode": {"on", "off"},
    "smart_responses": {"on", "off"},
}

_WARN_LIMIT_MIN = 1
_WARN_LIMIT_MAX = 10
_NUMERIC_LIMITS: dict[str, tuple[int, int]] = {
    "max_links": (0, 50),
    "max_mentions": (0, 50),
}
_TEXT_LIMITS: dict[str, int] = {
    "welcome_msg": 4096,
    "leave_msg": 4096,
    "rules_text": 4096,
}


def _key(chat_id: int) -> str:
    return f"{get_settings().redis_prefix}group_settings:{chat_id}"


def _legacy_warn_key(chat_id: int) -> str:
    return f"{get_settings().redis_prefix}warnlimit:{chat_id}"


def _legacy_captcha_key(chat_id: int) -> str:
    return f"{get_settings().redis_prefix}captcha_enabled:{chat_id}"


def _decode(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _parse_warn_limit(value: Any) -> int | None:
    try:
        parsed = int(_decode(value))
    except (TypeError, ValueError):
        return None
    if not (_WARN_LIMIT_MIN <= parsed <= _WARN_LIMIT_MAX):
        return None
    return parsed


async def _migrate_legacy_captcha(redis, chat_id: int) -> str | None:
    """Read the old boolean CAPTCHA key once, migrate it, then remove it."""
    legacy_value = await redis.get(_legacy_captcha_key(chat_id))
    if legacy_value is None:
        return None
    normalized = _decode(legacy_value).strip().lower()
    migrated = {
        "1": "on",
        "on": "on",
        "true": "on",
        "0": "off",
        "off": "off",
        "false": "off",
    }.get(normalized)
    await redis.delete(_legacy_captcha_key(chat_id))
    if migrated is None:
        logger.warning("legacy_captcha_discarded", chat_id=chat_id)
        return None
    return migrated


async def _migrate_legacy_warn_limit(redis, chat_id: int) -> str | None:
    """Read the old warnlimit key once, migrate valid data, then remove it."""
    legacy_value = await redis.get(_legacy_warn_key(chat_id))
    if legacy_value is None:
        return None

    parsed = _parse_warn_limit(legacy_value)
    await redis.delete(_legacy_warn_key(chat_id))
    if parsed is None:
        logger.warning("legacy_warn_limit_discarded", chat_id=chat_id)
        return None
    return str(parsed)


async def get_setting(chat_id: int, field: str) -> str:
    """Get one setting, lazily migrating legacy CAPTCHA and warn-limit keys."""
    redis = await get_redis()
    val = await redis.hget(_key(chat_id), field)
    if val is None and field == "captcha":
        migrated = await _migrate_legacy_captcha(redis, chat_id)
        if migrated is not None:
            await redis.hset(_key(chat_id), field, migrated)
            return migrated
        return str(_DEFAULTS.get(field, ""))
    if val is None and field == "warn_limit":
        migrated = await _migrate_legacy_warn_limit(redis, chat_id)
        if migrated is not None:
            await redis.hset(_key(chat_id), field, migrated)
            return migrated
        return str(_DEFAULTS.get(field, ""))
    if val is None:
        return str(_DEFAULTS.get(field, ""))

    decoded = _decode(val)
    if field == "warn_limit":
        parsed = _parse_warn_limit(decoded)
        if parsed is None:
            logger.warning("invalid_warn_limit_ignored", chat_id=chat_id)
            return str(_DEFAULTS[field])
        return str(parsed)
    return decoded


def validate_setting(field: str, value: str) -> str:
    """Validate the public canonical settings schema without writing to Redis."""
    if field not in _DEFAULTS:
        raise ValueError(f"Unsupported group setting: {field}")
    normalized = str(value)
    if field in _VALID_VALUES and normalized not in _VALID_VALUES[field]:
        raise ValueError(f"Invalid value for {field}")
    if field == "warn_limit" and _parse_warn_limit(normalized) is None:
        raise ValueError("warn_limit must be an integer from 1 to 10")
    if field in _NUMERIC_LIMITS:
        minimum, maximum = _NUMERIC_LIMITS[field]
        try:
            parsed = int(normalized)
        except ValueError as exc:
            raise ValueError(f"{field} must be an integer") from exc
        if not minimum <= parsed <= maximum:
            raise ValueError(f"{field} must be between {minimum} and {maximum}")
        normalized = str(parsed)
    if field == "modlog_channel" and normalized:
        try:
            int(normalized)
        except ValueError as exc:
            raise ValueError("modlog_channel must be a Telegram chat ID") from exc
    if field in _TEXT_LIMITS and len(normalized) > _TEXT_LIMITS[field]:
        raise ValueError(f"{field} exceeds the allowed length")
    return normalized


async def set_setting(chat_id: int, field: str, value: str) -> None:
    """Set a group setting with validation and remove superseded legacy state."""
    value = validate_setting(field, value)

    redis = await get_redis()
    await redis.hset(_key(chat_id), field, value)
    if field == "warn_limit":
        await redis.delete(_legacy_warn_key(chat_id))
    elif field == "captcha":
        await redis.delete(_legacy_captcha_key(chat_id))
    logger.info("group_setting_changed", chat_id=chat_id, field=field, value=value)


async def get_all_settings(chat_id: int) -> dict[str, str]:
    """Get all settings, merging defaults and migrating legacy values."""
    redis = await get_redis()
    raw = await redis.hgetall(_key(chat_id))
    result = {key: str(value) for key, value in _DEFAULTS.items()}
    decoded_raw = {_decode(key): _decode(value) for key, value in raw.items()}
    result.update(decoded_raw)

    if "captcha" not in decoded_raw:
        migrated_captcha = await _migrate_legacy_captcha(redis, chat_id)
        if migrated_captcha is not None:
            await redis.hset(_key(chat_id), "captcha", migrated_captcha)
            result["captcha"] = migrated_captcha

    if "warn_limit" not in decoded_raw:
        migrated = await _migrate_legacy_warn_limit(redis, chat_id)
        if migrated is not None:
            await redis.hset(_key(chat_id), "warn_limit", migrated)
            result["warn_limit"] = migrated
    else:
        if result["captcha"] not in _VALID_VALUES["captcha"]:
            result["captcha"] = str(_DEFAULTS["captcha"])
        parsed = _parse_warn_limit(result["warn_limit"])
        if parsed is None:
            result["warn_limit"] = str(_DEFAULTS["warn_limit"])
        else:
            result["warn_limit"] = str(parsed)
    return result


async def reset_settings(chat_id: int) -> None:
    """Reset all settings and remove superseded legacy keys."""
    redis = await get_redis()
    await redis.delete(
        _key(chat_id),
        _legacy_warn_key(chat_id),
        _legacy_captcha_key(chat_id),
    )
    logger.info("group_settings_reset", chat_id=chat_id)
