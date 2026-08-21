"""
Celery Tasks — Background Moderation Jobs
------------------------------------------
Heavy or deferred work that should not block the real-time pipeline.
"""
from __future__ import annotations

import asyncio
from datetime import UTC
from typing import Any

from sqlalchemy import and_, select

from src.tasks.celery_app import celery_app
from src.utils.logger import get_logger

logger = get_logger(__name__)

_task_loop: asyncio.AbstractEventLoop | None = None


def _run_async(coro) -> Any:
    """Run a coroutine on the worker process loop shared by Celery tasks."""
    global _task_loop
    if _task_loop is None or _task_loop.is_closed():
        _task_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_task_loop)
    return _task_loop.run_until_complete(coro)


@celery_app.task(
    name="src.tasks.moderation_tasks.update_domain_reputation",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def update_domain_reputation(self, domain: str, risk_score: float, source: str) -> dict:
    """
    Persist a domain reputation update to the database.
    Called when the link analysis layer discovers a new risky domain.
    """
    async def _run():
        from sqlalchemy import select

        from src.db.models import DomainReputation
        from src.db.session import db_session

        async with db_session() as session:
            result = await session.execute(
                select(DomainReputation).where(DomainReputation.domain == domain)
            )
            rep = result.scalar_one_or_none()
            if rep:
                rep.risk_score = max(rep.risk_score, risk_score)
                rep.source = source
            else:
                rep = DomainReputation(
                    domain=domain,
                    risk_score=risk_score,
                    source=source,
                )
                session.add(rep)

        logger.info("domain_reputation_updated", domain=domain, risk_score=risk_score)
        return {"domain": domain, "risk_score": risk_score}

    try:
        return _run_async(_run())
    except Exception as exc:
        logger.error("domain_rep_task_failed", domain=domain, error=str(exc))
        raise self.retry(exc=exc)


@celery_app.task(
    name="src.tasks.moderation_tasks.recalculate_trust_scores",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def recalculate_trust_scores(self) -> dict:
    """
    Periodic task: slowly restore trust scores for users with no recent violations.
    Runs hourly via Celery Beat.
    """
    async def _run():
        from datetime import datetime, timedelta

        from sqlalchemy import func, select

        from src.db.models import GroupMember, ModerationEvent
        from src.db.session import db_session

        cutoff = datetime.now(tz=UTC) - timedelta(hours=24)
        updated = 0

        async with db_session() as session:
            # Find members with no violations in the last 24 hours
            result = await session.execute(
                select(GroupMember)
                .where(GroupMember.trust_score < 90.0)
                .limit(500)
            )
            members = result.scalars().all()

            for member in members:
                # Check for recent violations
                viol_result = await session.execute(
                    select(func.count(ModerationEvent.id)).where(
                        ModerationEvent.user_id == member.user_id,
                        ModerationEvent.group_id == member.group_id,
                        ModerationEvent.created_at >= cutoff,
                    )
                )
                recent_violations = viol_result.scalar_one()

                if recent_violations == 0:
                    # Slowly restore trust: +1 per hour, cap at 90
                    member.trust_score = min(90.0, member.trust_score + 1.0)
                    updated += 1

        logger.info("trust_scores_recalculated", updated=updated)
        return {"updated": updated}

    try:
        return _run_async(_run())
    except Exception as exc:
        logger.error("trust_recalculation_failed", error=type(exc).__name__)
        raise self.retry(exc=exc, countdown=min(3600, 300 * (2 ** self.request.retries)))


@celery_app.task(
    name="src.tasks.moderation_tasks.batch_log_events",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
)
def batch_log_events(self, events: list[dict]) -> dict:
    """
    Batch-write moderation events to the database.
    Used when the real-time pipeline defers logging under high load.
    """
    async def _run():
        from src.db.models import ModerationEvent
        from src.db.session import db_session

        async with db_session() as session:
            written = 0
            for evt in events:
                message_id = evt.get("message_id")
                if message_id is not None:
                    existing = await session.execute(
                        select(ModerationEvent.id).where(
                            and_(
                                ModerationEvent.group_id == evt["group_id"],
                                ModerationEvent.user_id == evt["user_id"],
                                ModerationEvent.message_id == message_id,
                            )
                        ).limit(1)
                    )
                    if existing.scalar_one_or_none() is not None:
                        continue
                session.add(ModerationEvent(**evt))
                written += 1

        logger.info("batch_log_written", count=written, received=len(events))
        return {"written": written, "received": len(events)}

    try:
        return _run_async(_run())
    except Exception as exc:
        logger.error("batch_log_task_failed", error=type(exc).__name__)
        raise self.retry(exc=exc, countdown=min(1800, 120 * (2 ** self.request.retries)))
