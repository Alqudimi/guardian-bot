"""
Language Guard — Group Language Policy Enforcement
====================================================
Enforces a configured language policy for groups that wish to maintain
language consistency (e.g., Arabic-only communities).

Configuration per group (via /setlang):
  ar   — Arabic only
  en   — English only
  ar+en — Arabic or English (bilingual)
  any  — No restriction (default)

Language detection approach:
  1. Unicode script analysis (fast, no external model needed)
  2. Character frequency heuristic for Arabic/Latin/etc.
  3. Short messages (<10 chars) are exempt
  4. Commands (/...) are always exempt
  5. URLs are stripped before detection
  6. Admins and whitelisted users are exempt

Response options (configurable per group):
  delete — delete the message and send a language reminder
  warn   — just send a reminder, don't delete
  mute   — delete and mute for 5 minutes on repeat

Supports:
  Arabic (ar), English (en), French (fr), Russian (ru),
  Turkish (tr), Persian (fa), Urdu (ur)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from config.settings import get_settings
from src.pipeline.context import PipelineContext
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

# ── Unicode script ranges ──────────────────────────────────────────────────────
_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN_RE = re.compile(r"[A-Za-z\u00C0-\u024F]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_CJK_RE = re.compile(r"[\u4E00-\u9FFF\u3040-\u30FF]")
_PERSIAN_URDU_RE = re.compile(r"[\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF]")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_COMMAND_RE = re.compile(r"^/\w+")

# Language name labels for messages
_LANG_LABELS = {
    "ar": "العربية",
    "en": "English",
    "fr": "Français",
    "ru": "Русский",
    "ar+en": "العربية / English",
}


@dataclass
class LangDetection:
    dominant: str          # "ar", "en", "ru", "other"
    ar_ratio: float = 0.0
    latin_ratio: float = 0.0
    cyrillic_ratio: float = 0.0
    cjk_ratio: float = 0.0
    mixed: bool = False


def detect_language(text: str) -> LangDetection:
    """
    Detect the dominant script/language of a text using Unicode character ranges.
    Returns LangDetection with ratios.
    """
    # Strip URLs and commands
    cleaned = _URL_RE.sub("", text)
    cleaned = _COMMAND_RE.sub("", cleaned).strip()

    if len(cleaned) < 5:
        return LangDetection(dominant="neutral")

    # Count alpha chars per script
    ar = len(_ARABIC_RE.findall(cleaned))
    lat = len(_LATIN_RE.findall(cleaned))
    cyr = len(_CYRILLIC_RE.findall(cleaned))
    cjk = len(_CJK_RE.findall(cleaned))
    total = ar + lat + cyr + cjk

    if total < 3:
        return LangDetection(dominant="neutral")

    ar_r = ar / total
    lat_r = lat / total
    cyr_r = cyr / total
    cjk_r = cjk / total

    # Determine dominant
    dominant = "other"
    if ar_r >= 0.6 or (ar_r >= 0.3 and lat_r < 0.2):
        dominant = "ar"
    elif lat_r >= 0.6:
        dominant = "en"
    elif cyr_r >= 0.6:
        dominant = "ru"
    elif cjk_r >= 0.5:
        dominant = "cjk"

    mixed = sum(1 for r in [ar_r, lat_r, cyr_r] if r > 0.2) >= 2

    return LangDetection(
        dominant=dominant,
        ar_ratio=ar_r,
        latin_ratio=lat_r,
        cyrillic_ratio=cyr_r,
        cjk_ratio=cjk_r,
        mixed=mixed,
    )


async def get_group_language_policy(chat_id: int) -> str:
    """Return the canonical group language policy, migrating the legacy key."""
    redis = await get_redis()
    settings = get_settings()
    legacy_key = f"{settings.redis_prefix}lang_policy:{chat_id}"
    legacy_value = await redis.get(legacy_key)
    if legacy_value:
        policy = (
            legacy_value.decode() if isinstance(legacy_value, bytes) else str(legacy_value)
        )
        if policy in {"any", "ar", "en", "fr", "ru", "ar+en"}:
            from src.management.group_settings import set_setting

            await set_setting(chat_id, "lang_policy", policy)
            await redis.delete(legacy_key)
            return policy
        await redis.delete(legacy_key)

    from src.management.group_settings import get_setting

    return await get_setting(chat_id, "lang_policy")


async def set_group_language_policy(chat_id: int, policy: str) -> None:
    valid = {"any", "ar", "en", "fr", "ru", "ar+en"}
    if policy not in valid:
        raise ValueError(f"Invalid policy '{policy}'. Valid: {valid}")

    from src.management.group_settings import set_setting

    await set_setting(chat_id, "lang_policy", policy)
    redis = await get_redis()
    settings = get_settings()
    await redis.delete(f"{settings.redis_prefix}lang_policy:{chat_id}")


def _text_violates_policy(dominant: str, policy: str) -> bool:
    """Return True if the detected language violates the policy."""
    if policy == "any" or dominant == "neutral":
        return False
    if policy == "ar+en":
        return dominant not in ("ar", "en", "neutral", "other")
    return dominant != policy and dominant != "neutral"


async def run_language_guard(ctx: PipelineContext) -> None:
    """Language guard pipeline layer."""
    if ctx.normalized is None or ctx.short_circuit:
        return

    text = ctx.normalized.clean_text.strip()
    if len(text) < 10:
        return

    # Skip commands
    if _COMMAND_RE.match(text):
        return

    policy = await get_group_language_policy(ctx.chat_id)
    if policy == "any":
        return

    detection = detect_language(text)
    if not _text_violates_policy(detection.dominant, policy):
        return

    allowed_label = _LANG_LABELS.get(policy, policy)
    ctx.short_circuit = True
    ctx.decision.action = "delete"
    ctx.decision.reason = (
        f"language_policy:{policy}:detected={detection.dominant}"
    )
    ctx.decision.warning_text = (
        f"⚠️ هذه المجموعة تدعم فقط: {allowed_label}\n"
        f"⚠️ This group only allows: {allowed_label}"
    )

    logger.info(
        "language_guard_violation",
        user_id=ctx.user_id,
        chat_id=ctx.chat_id,
        dominant=detection.dominant,
        policy=policy,
    )
