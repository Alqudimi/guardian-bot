"""
Audit Logging Layer
--------------------
Persists all moderation events to PostgreSQL for:
- Forensic analysis
- Analytics dashboards
- Incident replay
- System improvement feedback loops

Also updates the Redis cache for user profiles after each event.
"""
from __future__ import annotations

from sqlalchemy import select

from config.settings import get_settings
from src.db.models import ActionType, Group, GroupMember, ModerationEvent, User, ViolationCategory
from src.db.session import db_session
from src.pipeline.context import PipelineContext
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)


def _infer_violation_category(ctx: PipelineContext) -> str:
    if ctx.spam.blacklist_hit:
        return ViolationCategory.SPAM
    if ctx.links.phishing_detected:
        return ViolationCategory.PHISHING
    if ctx.media.nsfw_detected:
        return ViolationCategory.NSFW
    if ctx.ai.hate_speech or ctx.ai.offensive:
        return ViolationCategory.TOXICITY
    if ctx.spam.flood_triggered or ctx.spam.burst_triggered:
        return ViolationCategory.FLOOD
    if ctx.spam.duplicate_detected:
        return ViolationCategory.DUPLICATE
    if ctx.links.invite_abuse:
        return ViolationCategory.INVITE_ABUSE
    if ctx.spam.mention_spam:
        return ViolationCategory.MENTION_SPAM
    if ctx.spam.media_spam:
        return ViolationCategory.MEDIA_SPAM
    if ctx.spam.coordinated_score > 0:
        return ViolationCategory.RAID
    return ViolationCategory.OTHER


async def _upsert_group(session, chat_id: int, title: str | None) -> None:
    result = await session.execute(select(Group).where(Group.id == chat_id))
    group = result.scalar_one_or_none()
    if not group:
        group = Group(id=chat_id, title=title)
        session.add(group)


async def _upsert_user(session, user_id: int, username: str | None, first_name: str | None) -> None:
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(id=user_id, username=username, first_name=first_name)
        session.add(user)
    else:
        if username and user.username != username:
            user.username = username


async def run_audit_logging(ctx: PipelineContext) -> None:
    settings = get_settings()
    action = ctx.decision.action

    # Always log — even ALLOWs in audit-heavy deployments
    # For ALLOW + low risk, skip DB write to reduce load
    if action == ActionType.ALLOW and ctx.risk.total < 10:
        return

    try:
        async with db_session() as session:
            # Ensure group and user exist
            chat = ctx.message.chat
            await _upsert_group(session, ctx.chat_id, getattr(chat, "title", None))
            await _upsert_user(
                session,
                ctx.user_id,
                ctx.user.username,
                ctx.user.first_name,
            )
            await session.flush()

            # Build signals dict
            signals = {
                "spam": {
                    "flood_triggered": ctx.spam.flood_triggered,
                    "burst_triggered": ctx.spam.burst_triggered,
                    "duplicate": ctx.spam.duplicate_detected,
                    "flood_score": ctx.spam.flood_score,
                    "entropy": ctx.spam.entropy_score,
                    "coordinated": ctx.spam.coordinated_score,
                },
                "toxicity": {
                    "score": ctx.ai.toxicity_score,
                    "label": ctx.ai.toxicity_label,
                    "confidence": ctx.ai.toxicity_confidence,
                },
                "nsfw": {
                    "score": ctx.media.nsfw_score,
                    "detected": ctx.media.nsfw_detected,
                },
                "links": {
                    "risk_score": ctx.links.link_risk_score,
                    "phishing": ctx.links.phishing_detected,
                    "risky_urls": ctx.links.risky_urls[:5],
                },
                "behavior": {
                    "trust_score": ctx.behavior.trust_score,
                    "violation_count": ctx.behavior.violation_count,
                    "is_new_account": ctx.behavior.is_new_account,
                },
                "pipeline": {
                    "layer_failures": ctx.layer_failures[:20],
                },
                "execution": {
                    "status": ctx.execution_status,
                    "error": ctx.execution_error,
                },
            }

            event = ModerationEvent(
                group_id=ctx.chat_id,
                user_id=ctx.user_id,
                message_id=ctx.message_id,
                message_text=(ctx.normalized.original_text[:512] if ctx.normalized else None),
                message_fingerprint=(ctx.normalized.fingerprint if ctx.normalized else None),
                violation_category=_infer_violation_category(ctx),
                action_taken=action,
                risk_score=ctx.risk.total,
                toxicity_score=ctx.ai.toxicity_score or None,
                nsfw_score=ctx.media.nsfw_score or None,
                spam_score=ctx.spam.flood_score or None,
                link_risk_score=ctx.links.link_risk_score or None,
                behavioral_risk=ctx.behavior.behavioral_risk or None,
                explanation=ctx.risk.explanation,
                signals=signals,
                dry_run=settings.dry_run,
            )
            session.add(event)

            # Update group member stats if a punitive action was taken
            if action not in (ActionType.ALLOW, ActionType.SILENT_LOG):
                result = await session.execute(
                    select(GroupMember).where(
                        GroupMember.user_id == ctx.user_id,
                        GroupMember.group_id == ctx.chat_id,
                    )
                )
                member = result.scalar_one_or_none()
                if member:
                    member.violation_count += 1
                    if action == ActionType.WARN:
                        member.warn_count += 1
                    # Decrease trust score on violation
                    trust_delta = {
                        ActionType.DELETE: -3.0,
                        ActionType.WARN: -5.0,
                        ActionType.MUTE_TEMP: -10.0,
                        ActionType.BAN_TEMP: -20.0,
                        ActionType.BAN_PERM: -50.0,
                        ActionType.ESCALATE: -8.0,
                    }.get(action, -2.0)

                    member.trust_score = max(
                        settings.trust_score_min,
                        member.trust_score + trust_delta,
                    )
                    member.risk_index = ctx.risk.total / 100.0

        # Invalidate Redis profile cache so next message loads fresh values
        redis = await get_redis()
        cache_key = f"{settings.redis_prefix}profile:{ctx.chat_id}:{ctx.user_id}"
        await redis.delete(cache_key)

        logger.debug(
            "audit_logged",
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            action=action,
            risk_score=ctx.risk.total,
        )

    except Exception as exc:
        # Audit logging must never crash the pipeline
        logger.error("audit_logging_error", error=str(exc), user_id=ctx.user_id)
