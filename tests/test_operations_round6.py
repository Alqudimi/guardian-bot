from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_post_init_starts_optional_voice_backend_without_blocking_core_startup() -> None:
    import main

    settings = SimpleNamespace(
        environment="development",
        dry_run=True,
        telegram_webhook_url="",
    )
    with (
        patch.object(main, "get_settings", return_value=settings),
        patch.object(main, "init_db", new_callable=AsyncMock),
        patch.object(main, "get_redis", new_callable=AsyncMock),
        patch(
            "src.features.voice_chat.start_voice_backend",
            new_callable=AsyncMock,
        ) as start_voice,
    ):
        await main.post_init(object())

    start_voice.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_init_keeps_moderation_startup_alive_when_voice_backend_fails() -> None:
    import main

    settings = SimpleNamespace(
        environment="development",
        dry_run=False,
        telegram_webhook_url="",
    )
    with (
        patch.object(main, "get_settings", return_value=settings),
        patch.object(main, "init_db", new_callable=AsyncMock),
        patch.object(main, "get_redis", new_callable=AsyncMock),
        patch(
            "src.features.voice_chat.start_voice_backend",
            new_callable=AsyncMock,
            side_effect=RuntimeError("voice unavailable"),
        ),
    ):
        await main.post_init(object())


@pytest.mark.asyncio
async def test_post_shutdown_stops_voice_backend_before_shared_resources() -> None:
    import main

    with (
        patch(
            "src.features.voice_chat.stop_voice_backend",
            new_callable=AsyncMock,
        ) as stop_voice,
        patch.object(main, "close_db", new_callable=AsyncMock) as close_db,
        patch.object(main, "close_redis", new_callable=AsyncMock) as close_redis,
    ):
        await main.post_shutdown(object())

    stop_voice.assert_awaited_once()
    close_db.assert_awaited_once()
    close_redis.assert_awaited_once()
    assert stop_voice.await_args_list[0]


class _FakeJob:
    def __init__(self) -> None:
        self.removed = False

    def schedule_removal(self) -> None:
        self.removed = True


class _FakeJobQueue:
    def __init__(self) -> None:
        self.jobs = [_FakeJob()]
        self.scheduled: dict[str, object] = {}

    def get_jobs_by_name(self, name: str) -> list[_FakeJob]:
        return self.jobs

    def run_once(self, callback, *, when: int, data: int, name: str) -> None:
        self.scheduled[name] = {
            "callback": callback,
            "when": when,
            "data": data,
        }


def test_schedule_lockdown_release_replaces_existing_job() -> None:
    from src.pipeline.raid_detector import schedule_lockdown_release

    queue = _FakeJobQueue()
    context = SimpleNamespace(job_queue=queue)
    assert schedule_lockdown_release(context, -100001) is True
    assert queue.jobs[0].removed is True
    scheduled = queue.scheduled["raid-lockdown:-100001"]
    assert scheduled["when"] == 300
    assert scheduled["data"] == -100001


@pytest.mark.asyncio
async def test_auto_release_lockdown_calls_real_release_path() -> None:
    from src.pipeline.raid_detector import auto_release_lockdown

    context = SimpleNamespace(
        bot=object(),
        job=SimpleNamespace(data=-100001),
    )
    with patch(
        "src.pipeline.raid_detector.release_lockdown",
        new_callable=AsyncMock,
    ) as release:
        await auto_release_lockdown(context)

    release.assert_awaited_once_with(context.bot, -100001)


@pytest.mark.asyncio
async def test_report_metrics_roundtrip_through_real_redis() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from config import settings as settings_module
    from config.settings import Settings
    from src.management.reports import (
        generate_report,
        record_action_stat,
        record_circuit_suppression,
        record_layer_failure,
        record_raid_stat,
    )
    from src.utils.redis_client import get_redis

    chat_id = -100002
    prefix = f"pytest:round6-report:{uuid4().hex}:"
    previous = settings_module._settings
    settings_module._settings = Settings(
        _env_file=None,
        telegram_admin_ids=[],
        redis_prefix=prefix,
    )
    today = datetime.now(tz=UTC).strftime("%Y%m%d")
    keys = [
        f"{prefix}stats:{chat_id}:{today}:actions",
        f"{prefix}stats:{chat_id}:{today}:violations",
        f"{prefix}stats:{chat_id}:{today}:offenders",
        f"{prefix}stats:{chat_id}:{today}:events",
        f"{prefix}stats:{chat_id}:{today}:layer_failures",
    ]
    try:
        await record_action_stat(chat_id, "delete", "spam", user_id=42)
        await record_raid_stat(chat_id)
        await record_circuit_suppression(chat_id)
        await record_layer_failure(chat_id, "link_analysis")
        report = await generate_report(chat_id, days=1)

        assert report.actions == {"delete": 1}
        assert report.violations == {"spam": 1}
        assert report.top_offenders == [(42, 1)]
        assert report.raids == 1
        assert report.circuit_trips == 1
        assert report.layer_failures == {"link_analysis": 1}
    finally:
        redis = await get_redis()
        await redis.delete(*keys)
        settings_module._settings = previous
