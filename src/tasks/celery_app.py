"""
Celery Application
-------------------
Optional background task queue for heavy processing:
- Batch audit log writes
- Scheduled trust score recalculations
- Async domain reputation updates
- Heavy AI inference offloading
"""
from __future__ import annotations

from celery import Celery

from config.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "tgbot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["src.tasks.moderation_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "src.tasks.moderation_tasks.update_domain_reputation": {"queue": "low"},
        "src.tasks.moderation_tasks.recalculate_trust_scores": {"queue": "low"},
        "src.tasks.moderation_tasks.batch_log_events": {"queue": "default"},
    },
    beat_schedule={
        "recalculate-trust-scores-hourly": {
            "task": "src.tasks.moderation_tasks.recalculate_trust_scores",
            "schedule": 3600.0,
        },
    },
)
