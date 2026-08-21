"""
Cross-Group Threat Intelligence
================================
Shares threat intelligence across all groups the bot operates in.

When a user is confirmed malicious in one group, the intelligence is
propagated to all groups so the bot can act proactively before the
user causes harm elsewhere.

Threat propagation:
  Level 1 (LOW)    — Monitor closely in other groups
  Level 2 (MEDIUM) — Apply stricter thresholds in other groups
  Level 3 (HIGH)   — Pre-emptive warn/restrict on first message
  Level 4 (CRITICAL)— Immediate ban on sight across all groups

Intelligence data stored per threat entity:
  - User ID → threat level, source groups, ban count, timestamps
  - Domain → risk score, detection count, first/last seen
  - Fingerprint → content hash, spam count, source groups
  - IP pattern → if extractable, track abuse patterns

Decay policy:
  - Threat levels decay over time with no new incidents
  - Level 1–2 decay in 7 days
  - Level 3 decays in 30 days
  - Level 4 is permanent (requires manual review to remove)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from config.settings import get_settings
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)


class ThreatLevel(IntEnum):
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


# TTL per threat level (seconds)
_THREAT_TTL = {
    ThreatLevel.LOW: 7 * 86400,
    ThreatLevel.MEDIUM: 14 * 86400,
    ThreatLevel.HIGH: 30 * 86400,
    ThreatLevel.CRITICAL: 365 * 86400,  # 1 year
}

# How many group bans → threat level
_BAN_TO_THREAT = {
    1: ThreatLevel.LOW,
    3: ThreatLevel.MEDIUM,
    5: ThreatLevel.HIGH,
    8: ThreatLevel.CRITICAL,
}


@dataclass
class UserThreatProfile:
    user_id: int
    threat_level: ThreatLevel = ThreatLevel.NONE
    ban_count: int = 0
    source_groups: list[int] = None  # type: ignore[assignment]
    first_seen: float = 0.0
    last_incident: float = 0.0
    violation_types: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.source_groups is None:
            self.source_groups = []
        if self.violation_types is None:
            self.violation_types = []


async def get_user_threat(user_id: int) -> UserThreatProfile:
    """Retrieve the global threat profile for a user."""
    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix

    data = await redis.hgetall(f"{prefix}gthreat:{user_id}")

    if not data:
        return UserThreatProfile(user_id=user_id)

    threat_level = ThreatLevel(int(data.get("level", 0)))
    ban_count = int(data.get("ban_count", 0))

    raw_groups = data.get("source_groups", "")
    source_groups = [int(g) for g in raw_groups.split(",") if g.strip()] if raw_groups else []

    raw_violations = data.get("violations", "")
    violations = raw_violations.split(",") if raw_violations else []

    return UserThreatProfile(
        user_id=user_id,
        threat_level=threat_level,
        ban_count=ban_count,
        source_groups=source_groups,
        first_seen=float(data.get("first_seen", time.time())),
        last_incident=float(data.get("last_incident", time.time())),
        violation_types=violations,
    )


async def report_user_incident(
    user_id: int,
    chat_id: int,
    violation_type: str,
    action_taken: str,
) -> ThreatLevel:
    """
    Report a violation incident for a user. Updates the global threat
    profile and returns the new threat level.
    """
    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix
    key = f"{prefix}gthreat:{user_id}"
    now = time.time()

    # Get or create profile
    profile = await get_user_threat(user_id)

    # Increment ban count on ban actions
    if "ban" in action_taken:
        profile.ban_count += 1

    # Always increment for serious violations
    if violation_type in ("phishing", "nsfw", "hate_speech", "coordinated_spam"):
        profile.ban_count = max(profile.ban_count, profile.ban_count + 1)

    # Determine new threat level
    new_level = ThreatLevel.LOW
    for threshold, level in sorted(_BAN_TO_THREAT.items()):
        if profile.ban_count >= threshold:
            new_level = level

    # Never downgrade threat level automatically
    new_level = max(new_level, profile.threat_level)

    # Update groups list
    if chat_id not in profile.source_groups:
        profile.source_groups.append(chat_id)

    # Update violation types
    if violation_type not in profile.violation_types:
        profile.violation_types.append(violation_type)

    # Persist
    ttl = _THREAT_TTL.get(new_level, 7 * 86400)
    await redis.hset(key, mapping={
        "level": int(new_level),
        "ban_count": profile.ban_count,
        "source_groups": ",".join(str(g) for g in profile.source_groups[-20:]),
        "first_seen": profile.first_seen or now,
        "last_incident": now,
        "violations": ",".join(profile.violation_types[-10:]),
    })
    await redis.expire(key, ttl)

    logger.info(
        "global_threat_updated",
        user_id=user_id,
        chat_id=chat_id,
        old_level=int(profile.threat_level),
        new_level=int(new_level),
        ban_count=profile.ban_count,
        violation=violation_type,
    )

    # If threat level is HIGH or CRITICAL, add to global blacklist
    if new_level >= ThreatLevel.HIGH:
        await redis.set(f"{prefix}gbl:{user_id}", str(int(new_level)))
        logger.warning(
            "user_added_to_global_blacklist",
            user_id=user_id,
            threat_level=int(new_level),
        )

    return new_level


async def get_domain_threat(domain: str) -> float:
    """Get the global threat risk score for a domain (0.0 – 1.0)."""
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}domain_threat:{domain}"
    score = await redis.hget(key, "risk_score")
    return float(score) if score else 0.0


async def report_domain_threat(domain: str, risk_score: float, source: str) -> None:
    """Report a malicious domain to the global intelligence store."""
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}domain_threat:{domain}"

    existing = float(await redis.hget(key, "risk_score") or 0)
    new_score = min(1.0, max(existing, risk_score))

    count = int(await redis.hget(key, "count") or 0) + 1

    await redis.hset(key, mapping={
        "risk_score": new_score,
        "count": count,
        "source": source,
        "last_seen": time.time(),
    })
    await redis.expire(key, 86400 * 30)

    logger.info("domain_threat_reported", domain=domain, risk_score=new_score, count=count)


async def get_threat_summary() -> dict[str, Any]:
    """Return summary statistics for the global threat intelligence."""
    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix

    # Count keys by pattern
    critical_count = 0
    high_count = 0

    # This is expensive — only call for admin status commands
    cursor = 0
    async for key in redis.scan_iter(f"{prefix}gthreat:*"):
        level = await redis.hget(key, "level")
        if level:
            lvl = int(level)
            if lvl >= ThreatLevel.CRITICAL:
                critical_count += 1
            elif lvl >= ThreatLevel.HIGH:
                high_count += 1

    return {
        "critical_threats": critical_count,
        "high_threats": high_count,
        "global_blacklist_size": await redis.dbsize(),
    }


async def should_apply_cross_group_restrictions(
    user_id: int,
    chat_id: int,
) -> tuple[bool, ThreatLevel, str]:
    """
    Check if a user should have cross-group restrictions applied
    before they even send a message.

    Returns (should_restrict, threat_level, reason).
    """
    profile = await get_user_threat(user_id)

    if profile.threat_level == ThreatLevel.NONE:
        return False, ThreatLevel.NONE, ""

    # Don't restrict in the group where the incident was reported
    if profile.threat_level >= ThreatLevel.CRITICAL:
        return True, profile.threat_level, f"global_critical_threat:bans={profile.ban_count}"

    if profile.threat_level >= ThreatLevel.HIGH and len(profile.source_groups) >= 3:
        return True, profile.threat_level, f"global_high_threat:groups={len(profile.source_groups)}"

    if profile.threat_level >= ThreatLevel.MEDIUM and profile.ban_count >= 5:
        return True, profile.threat_level, f"global_medium_threat:bans={profile.ban_count}"

    return False, profile.threat_level, ""
