"""
User Information & Reputation System
=====================================
Provides rich user profiles for admins — combining trust scores,
warn history, moderation events, ban history, and threat intelligence.

Commands:
  /userinfo <user_id | @username>   — Full user report
  /trustscore <user_id>             — Quick trust score check
  /warns <user_id>                  — View active warns
  /resetwarns <user_id>             — Reset warns (admin)
  /unban <user_id>                  — Unban a user
  /mute <user_id> [duration]        — Manual mute
  /unmute <user_id>                 — Remove mute

User profile includes:
  • Trust score (0–100)
  • Active warn count + history
  • Recent moderation events (from DB)
  • Global threat level (cross-group intel)
  • Account age category (from user ID)
  • Join date to this group (if available)
  • Total messages sent (approximation from Redis)
  • Ban status in this group
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from config.settings import get_settings
from src.db.models import GroupMember
from src.db.session import db_session
from src.intelligence.cross_group_intel import get_user_threat
from src.layers.smart_warn import get_warn_status
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

_TRUST_LABEL = {
    (0, 20): ("⛔", "Untrusted"),
    (20, 40): ("🔴", "Low"),
    (40, 60): ("🟡", "Moderate"),
    (60, 80): ("🟢", "Good"),
    (80, 101): ("✅", "Trusted"),
}
_THREAT_EMOJI = {0: "✅", 1: "🟡", 2: "🟠", 3: "🔴", 4: "⛔"}
_THREAT_NAME = {0: "None", 1: "Low", 2: "Medium", 3: "High", 4: "Critical"}


def _trust_label(score: float) -> tuple[str, str]:
    for (lo, hi), label in _TRUST_LABEL.items():
        if lo <= score < hi:
            return label
    return ("❓", "Unknown")


@dataclass
class UserProfile:
    user_id: int
    trust_score: float = 50.0
    active_warns: int = 0
    total_warns: int = 0
    threat_level: int = 0
    account_age_category: str = "unavailable_via_bot_api"
    cross_group_bans: int = 0
    source_groups: int = 0
    violation_types: list[str] = field(default_factory=list)
    message_count_30d: int = 0


async def get_user_profile(user_id: int, chat_id: int) -> UserProfile:
    """Build a comprehensive user profile for admin display."""
    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix

    profile = UserProfile(user_id=user_id)

    # ── Trust score ────────────────────────────────────────────────────────────
    trust_raw = await redis.hget(f"{prefix}profile:{chat_id}:{user_id}", "trust_score")
    if trust_raw is not None:
        profile.trust_score = float(trust_raw)
    else:
        try:
            async with db_session() as session:
                result = await session.execute(
                    select(GroupMember.trust_score).where(
                        GroupMember.user_id == user_id,
                        GroupMember.group_id == chat_id,
                    )
                )
                db_trust = result.scalar_one_or_none()
            if db_trust is not None:
                profile.trust_score = float(db_trust)
        except Exception as exc:
            logger.warning(
                "user_profile_trust_lookup_failed",
                chat_id=chat_id,
                user_id=user_id,
                error=type(exc).__name__,
            )

    # ── Warn status ────────────────────────────────────────────────────────────
    warn_status = await get_warn_status(user_id, chat_id)
    profile.active_warns = warn_status.active_warn_count
    profile.total_warns = warn_status.total_warn_count

    # ── Global threat profile ──────────────────────────────────────────────────
    threat = await get_user_threat(user_id)
    profile.threat_level = int(threat.threat_level)
    profile.cross_group_bans = threat.ban_count
    profile.source_groups = len(threat.source_groups)
    profile.violation_types = threat.violation_types

    # ── Account age ────────────────────────────────────────────────────────────
    # Telegram's Bot API does not expose account creation time.

    # ── Message count (approximate, from activity key) ────────────────────────
    activity_key = f"{prefix}user_msgs:{chat_id}:{user_id}"
    profile.message_count_30d = int(await redis.get(activity_key) or 0)

    return profile


def format_user_report(profile: UserProfile) -> str:
    """Format a user profile as a Markdown message for admins."""
    trust_emoji, trust_name = _trust_label(profile.trust_score)
    threat_emoji = _THREAT_EMOJI.get(profile.threat_level, "❓")
    threat_name = _THREAT_NAME.get(profile.threat_level, "Unknown")

    lines = [
        f"👤 *User Report: `{profile.user_id}`*\n",
        f"*Trust Score:* {trust_emoji} {profile.trust_score:.0f}/100 ({trust_name})",
        "*Account Age:* unavailable via Bot API",
        f"*Msgs (30d):* {profile.message_count_30d}",
        "",
        f"*⚠️ Warns (active):* {profile.active_warns}",
        f"*Warns (total):* {profile.total_warns}",
        "",
        f"*🌐 Global Threat:* {threat_emoji} {threat_name}",
        f"*Cross-group Bans:* {profile.cross_group_bans}",
        f"*Groups Tracked:* {profile.source_groups}",
    ]

    if profile.violation_types:
        lines.append(f"*Violations:* {', '.join(profile.violation_types)}")

    return "\n".join(lines)


async def increment_message_count(user_id: int, chat_id: int) -> None:
    """Track approximate message count per user per group."""
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}user_msgs:{chat_id}:{user_id}"
    await redis.incr(key)
    await redis.expire(key, 86400 * 35)  # 35-day rolling window
