"""
Decision Engine
----------------
Maps risk scores and signal flags to concrete moderation actions.

Action ladder (escalating severity):
  0–19    → allow
  20–39   → silent_log
  40–54   → delete
  55–64   → delete + warn
  65–74   → delete + mute_temp (15 min)
  75–84   → delete + ban_temp (24 h)
  85–100  → delete + ban_perm  (or escalate to admin for review)

Override rules (signal-driven):
  - blacklist hit          → ban_perm immediately
  - phishing detected      → ban_temp (or ban_perm on repeat)
  - NSFW confirmed         → delete + ban_temp
  - hate speech confirmed  → delete + ban_temp
  - raid lockdown active   → ban_temp all new joiners

All decisions include a human-readable explanation for audit logs.
"""
from __future__ import annotations

from config.settings import get_settings
from src.db.models import ActionType
from src.pipeline.context import Decision, PipelineContext
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Mute durations (seconds)
_MUTE_15MIN = 900
_MUTE_1H = 3600
_MUTE_6H = 21600

# Ban durations (seconds)
_BAN_1H = 3600
_BAN_24H = 86400
_BAN_7D = 604800


def _score_to_base_action(score: float) -> str:
    if score < 20:
        return ActionType.ALLOW
    elif score < 40:
        return ActionType.SILENT_LOG
    elif score < 55:
        return ActionType.DELETE
    elif score < 65:
        return ActionType.WARN
    elif score < 75:
        return ActionType.MUTE_TEMP
    elif score < 85:
        return ActionType.BAN_TEMP
    else:
        return ActionType.BAN_PERM


async def run_decision_engine(ctx: PipelineContext) -> None:
    settings = get_settings()
    # If fast rules already decided, respect it
    if ctx.short_circuit and ctx.decision.action:
        _finalize_decision(ctx)
        return

    score = ctx.risk.total
    from src.intelligence.adaptive_thresholds import get_group_thresholds

    thresholds = await get_group_thresholds(ctx.chat_id)
    effective_score = score
    if thresholds.moderation_level == "light":
        effective_score = max(0.0, score - 10.0)
    elif thresholds.moderation_level == "strict":
        effective_score = min(100.0, score + 10.0)

    action = _score_to_base_action(effective_score)
    reason_parts: list[str] = [
        f"risk_score={score:.1f}",
        f"moderation_level={thresholds.moderation_level}",
    ]
    notify_admin = False
    mute_duration = 0
    ban_duration = 0

    # ── Override rules ────────────────────────────────────────────────────────

    # Blacklist
    if ctx.spam.blacklist_hit:
        action = ActionType.BAN_PERM
        reason_parts.append("blacklist_hit")

    # Phishing
    elif ctx.links.phishing_detected:
        if ctx.behavior.violation_count >= 2:
            action = ActionType.BAN_PERM
        else:
            action = ActionType.BAN_TEMP
            ban_duration = _BAN_24H
        reason_parts.append("phishing_detected")
        notify_admin = True

    # NSFW confirmed
    elif ctx.media.nsfw_detected and ctx.media.nsfw_score >= settings.nsfw_threshold:
        action = ActionType.BAN_TEMP
        ban_duration = _BAN_24H
        reason_parts.append(f"nsfw_score={ctx.media.nsfw_score:.2f}")
        notify_admin = True

    # Hate speech
    elif ctx.ai.hate_speech and ctx.ai.toxicity_score >= settings.toxicity_threshold:
        if ctx.behavior.violation_count >= 3:
            action = ActionType.BAN_PERM
        else:
            action = ActionType.BAN_TEMP
            ban_duration = _BAN_24H
        reason_parts.append(f"hate_speech_score={ctx.ai.toxicity_score:.2f}")
        notify_admin = True

    # Coordinated spam
    elif ctx.spam.coordinated_score > 60:
        action = ActionType.BAN_TEMP
        ban_duration = _BAN_7D
        reason_parts.append("coordinated_spam")
        notify_admin = True

    # Repeat offenders
    elif ctx.behavior.violation_count >= 5 and score >= 55:
        action = ActionType.BAN_PERM
        reason_parts.append("repeat_offender")
        notify_admin = True

    # Flood
    elif ctx.spam.flood_triggered and action == ActionType.WARN:
        action = ActionType.MUTE_TEMP
        mute_duration = _MUTE_15MIN
        reason_parts.append("flood_triggered")

    # ── Set durations for mute/ban ─────────────────────────────────────────────
    if action == ActionType.MUTE_TEMP and mute_duration == 0:
        if effective_score >= 70:
            mute_duration = _MUTE_6H
        elif effective_score >= 65:
            mute_duration = _MUTE_1H
        else:
            mute_duration = _MUTE_15MIN

    if action == ActionType.BAN_TEMP and ban_duration == 0:
        if effective_score >= 80:
            ban_duration = _BAN_7D
        else:
            ban_duration = _BAN_24H

    # Escalate very high-risk cases to admins regardless
    if effective_score >= 90:
        notify_admin = True
        if action not in (ActionType.BAN_PERM, ActionType.BAN_TEMP):
            action = ActionType.ESCALATE

    # ── Dry-run override ─────────────────────────────────────────────────────
    if settings.dry_run and action not in (ActionType.ALLOW, ActionType.SILENT_LOG):
        reason_parts.append("dry_run")
        action = ActionType.SILENT_LOG

    explanation = " | ".join(reason_parts)

    ctx.decision = Decision(
        action=action,
        reason=explanation,
        mute_duration_seconds=mute_duration,
        ban_duration_seconds=ban_duration,
        notify_admin=notify_admin,
        explanation=ctx.risk.explanation,
    )

    logger.info(
        "decision_made",
        user_id=ctx.user_id,
        chat_id=ctx.chat_id,
        action=action,
        risk_score=round(score, 2),
        reason=explanation,
        notify_admin=notify_admin,
    )


def _finalize_decision(ctx: PipelineContext) -> None:
    """Ensure mute/ban durations are set for short-circuit decisions."""
    settings = get_settings()
    action = ctx.decision.action
    if action == ActionType.MUTE_TEMP and ctx.decision.mute_duration_seconds == 0:
        ctx.decision.mute_duration_seconds = _MUTE_15MIN
    if action == ActionType.BAN_TEMP and ctx.decision.ban_duration_seconds == 0:
        ctx.decision.ban_duration_seconds = _BAN_24H
    if settings.dry_run and action not in (ActionType.ALLOW, ActionType.SILENT_LOG):
        ctx.decision.action = ActionType.SILENT_LOG
        ctx.decision.reason += " | dry_run"
