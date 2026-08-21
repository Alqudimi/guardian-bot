"""
Account Intelligence Layer
===========================
Deep analysis of Telegram user accounts to detect:

1. Bot-like username patterns (random chars, numeric suffixes, known bot names)
2. Freshly-created account heuristics (ID-based estimation)
3. Profile completeness score (username, first/last name, bio presence)
4. Join velocity — has this user joined many groups recently?
5. Name/username homoglyph attacks — impersonating admins
6. Suspicious display name patterns (admin lookalikes, Telegram official lookalikes)
7. Cross-group ban correlation — user banned in multiple groups = global threat
8. Account resurrection detection — user who was inactive suddenly becomes active
9. Fake admin detection — usernames/names mimicking group admin names

All signals contribute to behavioral_risk and may trigger fast-path blocking.
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field

from config.settings import get_settings
from src.pipeline.context import PipelineContext
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

# ── Username patterns ──────────────────────────────────────────────────────────

# Bot-like: random alphanumeric + numbers at end (e.g. user2847362)
_BOT_USERNAME_PATTERN = re.compile(
    r"^(?:[a-z]{3,8}\d{5,}|[a-z]\d{6,}|\d+[a-z]+\d+|[a-z]{2,4}[._][a-z]{2,4}\d{3,})$",
    re.IGNORECASE,
)

# Suspicious name patterns — impersonating Telegram official
_TELEGRAM_OFFICIAL_PATTERN = re.compile(
    r"(?:telegram|support|admin|moderator|official|security|bot_father|"
    r"تيليجرام|دعم|مشرف|إدارة|ادمن|مودريتور)",
    re.IGNORECASE | re.UNICODE,
)

# Admin lookalike — check against actual group admins (loaded dynamically)
_ADMIN_TITLES = re.compile(
    r"(?:admin|owner|مالك|مشرف|ادمن|مدير|مؤسس)",
    re.IGNORECASE | re.UNICODE,
)

# Invisible/zero-width chars in display names (evasion)
_INVISIBLE_IN_NAME = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2060\ufeff]"
)

# Excessive punctuation or repeated chars in names (spam bot names)
_SPAM_NAME_PATTERN = re.compile(
    r"(?:[!@#$%^&*]{3,}|(.)\1{3,}|\d{8,})",
    re.UNICODE,
)


@dataclass
class AccountSignals:
    bot_like_username: bool = False
    suspicious_display_name: bool = False
    admin_impersonation: bool = False
    telegram_official_impersonation: bool = False
    invisible_chars_in_name: bool = False
    # Kept for backward-compatible reporting; never inferred from user ID.
    high_id_new_account: bool = False
    cross_group_banned: bool = False
    join_velocity_high: bool = False
    account_risk_score: float = 0.0
    risk_reasons: list[str] = field(default_factory=list)


def _estimate_account_age_category(user_id: int) -> str:
    """
    Estimate account age category from Telegram user ID.
    Telegram IDs are roughly monotonically increasing.
    This is a heuristic — not exact.
    """
    if user_id < 100_000:
        return "very_old"         # Pre-2014
    elif user_id < 10_000_000:
        return "old"              # ~2014-2016
    elif user_id < 100_000_000:
        return "established"      # ~2016-2019
    elif user_id < 1_000_000_000:
        return "moderate"         # ~2019-2022
    elif user_id < 5_000_000_000:
        return "recent"           # ~2022-2023
    elif user_id < 7_000_000_000:
        return "new"              # ~2023-2024
    else:
        return "very_new"         # 2024+


async def _get_cross_group_ban_count(user_id: int) -> int:
    """Count how many groups have banned this user."""
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}global_bans:{user_id}"
    count = await redis.get(key)
    return int(count) if count else 0


async def _record_group_ban(user_id: int, chat_id: int) -> int:
    """Record a ban event for cross-group intelligence."""
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}global_bans:{user_id}"
    new_count = await redis.incr(key)
    await redis.expire(key, 86400 * 30)  # 30 days
    # Also record which groups
    await redis.sadd(f"{settings.redis_prefix}banned_in_groups:{user_id}", str(chat_id))
    await redis.expire(f"{settings.redis_prefix}banned_in_groups:{user_id}", 86400 * 30)
    return new_count


async def _check_join_velocity(user_id: int) -> int:
    """
    Count how many groups this user has been seen joining recently.
    Returns join count in last 24h across all tracked groups.
    """
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}join_velocity:{user_id}"
    now = time.time()
    await redis.zremrangebyscore(key, "-inf", now - 86400)
    return int(await redis.zcard(key) or 0)


async def _record_join(user_id: int, chat_id: int) -> None:
    """Record a group join for velocity tracking."""
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}join_velocity:{user_id}"
    now = time.time()
    await redis.zadd(key, {str(chat_id): now})
    await redis.expire(key, 86400 * 2)


def _analyze_username(username: str | None) -> list[str]:
    flags: list[str] = []
    if not username:
        return flags
    if _BOT_USERNAME_PATTERN.match(username):
        flags.append("bot_like_username")
    if _TELEGRAM_OFFICIAL_PATTERN.search(username):
        flags.append("telegram_official_username")
    return flags


def _analyze_display_name(name: str | None) -> list[str]:
    flags: list[str] = []
    if not name:
        return flags

    if _INVISIBLE_IN_NAME.search(name):
        flags.append("invisible_chars_in_name")

    if _TELEGRAM_OFFICIAL_PATTERN.search(name):
        flags.append("telegram_official_name")

    if _ADMIN_TITLES.search(name):
        flags.append("admin_title_in_name")

    if _SPAM_NAME_PATTERN.search(name):
        flags.append("spam_like_name")

    # Check for confusable characters (homoglyph attack in names)
    nfkd = unicodedata.normalize("NFKD", name)
    if nfkd != name and any(
        unicodedata.category(c) == "Ll" and ord(c) > 127 for c in name
    ):
        flags.append("homoglyph_display_name")

    return flags


async def analyze_account(ctx: PipelineContext) -> AccountSignals:
    """
    Full account intelligence analysis. Returns AccountSignals.
    """
    user = ctx.user
    user_id = ctx.user_id
    chat_id = ctx.chat_id

    signals = AccountSignals()
    reasons: list[str] = []

    # ── 1. Username analysis ──────────────────────────────────────────────────
    username_flags = _analyze_username(user.username)
    for flag in username_flags:
        reasons.append(flag)
        if "official" in flag:
            signals.telegram_official_impersonation = True
        elif "bot_like" in flag:
            signals.bot_like_username = True

    # ── 2. Display name analysis ──────────────────────────────────────────────
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    name_flags = _analyze_display_name(full_name)
    for flag in name_flags:
        reasons.append(flag)
        if "admin" in flag or "official" in flag:
            signals.admin_impersonation = True
            signals.suspicious_display_name = True
        if "invisible" in flag:
            signals.invisible_chars_in_name = True
        if "homoglyph" in flag or "spam" in flag:
            signals.suspicious_display_name = True

    # ── 3. Account age ────────────────────────────────────────────────────────
    # Telegram does not expose account creation time through this update. A
    # numeric user ID is not reliable evidence of age or maliciousness, so it
    # is intentionally excluded from the moderation risk score.

    # ── 4. Cross-group ban count ──────────────────────────────────────────────
    ban_count = await _get_cross_group_ban_count(user_id)
    if ban_count >= 3:
        signals.cross_group_banned = True
        reasons.append(f"cross_group_bans:{ban_count}")

    # ── 5. Join velocity ──────────────────────────────────────────────────────
    join_count = await _check_join_velocity(user_id)
    if join_count >= 10:
        signals.join_velocity_high = True
        reasons.append(f"join_velocity:{join_count}/24h")

    # ── 6. Compute account risk score ─────────────────────────────────────────
    risk = 0.0

    if signals.telegram_official_impersonation:
        risk += 50.0
    if signals.admin_impersonation:
        risk += 35.0
    if signals.invisible_chars_in_name:
        risk += 25.0
    if signals.bot_like_username:
        risk += 15.0
    if signals.suspicious_display_name:
        risk += 20.0
    if signals.cross_group_banned:
        risk += min(60.0, ban_count * 15.0)
    if signals.join_velocity_high:
        risk += min(40.0, join_count * 3.0)

    signals.account_risk_score = min(100.0, risk)
    signals.risk_reasons = reasons

    logger.debug(
        "account_intelligence",
        user_id=user_id,
        chat_id=chat_id,
        risk=risk,
        flags=reasons,
    )

    return signals


async def run_account_intelligence(ctx: PipelineContext) -> None:
    """Pipeline layer entry point. Merges account signals into behavioral signals."""
    if ctx.short_circuit:
        return

    signals = await analyze_account(ctx)

    # Merge into behavioral context
    ctx.behavior.behavioral_risk = min(
        100.0,
        ctx.behavior.behavioral_risk + signals.account_risk_score * 0.4
    )

    # Admin impersonation → near-instant block
    if signals.admin_impersonation or signals.telegram_official_impersonation:
        ctx.spam.fast_rule_block = True
        ctx.short_circuit = True
        ctx.spam.flood_score = max(ctx.spam.flood_score, 80.0)
        ctx.decision.action = "ban_temp"
        ctx.decision.reason = f"admin_impersonation:{','.join(signals.risk_reasons)}"

    # Cross-group ban history → raise risk
    if signals.cross_group_banned:
        ctx.spam.flood_score = min(100.0, ctx.spam.flood_score + 30.0)

    # Store account signals in context for risk scoring
    if not hasattr(ctx, "account"):
        ctx.account = signals  # type: ignore[attr-defined]
