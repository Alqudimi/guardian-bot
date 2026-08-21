"""
Unit tests for the Decision Engine.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock

import pytest

from src.db.models import ActionType
from src.pipeline.context import (
    AISignals,
    Decision,
    LinkSignals,
    MediaSignals,
    RiskScore,
    SpamSignals,
    UserBehaviorSignals,
)


def _make_ctx(risk_total: float = 0.0, **kwargs) -> MagicMock:
    ctx = MagicMock()
    ctx.user_id = 12345
    ctx.chat_id = -100001
    ctx.spam = SpamSignals()
    ctx.behavior = UserBehaviorSignals()
    ctx.links = LinkSignals()
    ctx.media = MediaSignals()
    ctx.ai = AISignals()
    ctx.risk = RiskScore(total=risk_total)
    ctx.decision = Decision()
    ctx.short_circuit = False
    for k, v in kwargs.items():
        setattr(ctx, k, v)
    return ctx


@pytest.mark.asyncio
async def test_low_risk_allow():
    from src.layers.decision_engine import run_decision_engine
    ctx = _make_ctx(risk_total=5.0)
    await run_decision_engine(ctx)
    assert ctx.decision.action == ActionType.ALLOW


@pytest.mark.asyncio
async def test_medium_risk_silent_log():
    from src.layers.decision_engine import run_decision_engine
    ctx = _make_ctx(risk_total=30.0)
    await run_decision_engine(ctx)
    assert ctx.decision.action == ActionType.SILENT_LOG


@pytest.mark.asyncio
async def test_moderate_risk_delete():
    from src.layers.decision_engine import run_decision_engine
    ctx = _make_ctx(risk_total=47.0)
    await run_decision_engine(ctx)
    assert ctx.decision.action == ActionType.DELETE


@pytest.mark.asyncio
async def test_high_risk_mute():
    from src.layers.decision_engine import run_decision_engine
    ctx = _make_ctx(risk_total=68.0)
    await run_decision_engine(ctx)
    assert ctx.decision.action == ActionType.MUTE_TEMP
    assert ctx.decision.mute_duration_seconds > 0


@pytest.mark.asyncio
async def test_very_high_risk_ban():
    from src.layers.decision_engine import run_decision_engine
    ctx = _make_ctx(risk_total=80.0)
    await run_decision_engine(ctx)
    assert ctx.decision.action == ActionType.BAN_TEMP
    assert ctx.decision.ban_duration_seconds > 0


@pytest.mark.asyncio
async def test_phishing_escalates_to_ban():
    from src.layers.decision_engine import run_decision_engine
    ctx = _make_ctx(risk_total=55.0)
    ctx.links.phishing_detected = True
    await run_decision_engine(ctx)
    assert ctx.decision.action in (ActionType.BAN_TEMP, ActionType.BAN_PERM)
    assert ctx.decision.notify_admin is True


@pytest.mark.asyncio
async def test_repeat_offender_perm_ban():
    from src.layers.decision_engine import run_decision_engine
    ctx = _make_ctx(risk_total=60.0)
    ctx.behavior.violation_count = 6
    await run_decision_engine(ctx)
    assert ctx.decision.action == ActionType.BAN_PERM


@pytest.mark.asyncio
async def test_dry_run_downgrades_action():
    from config.settings import get_settings
    from src.layers.decision_engine import run_decision_engine
    settings = get_settings()
    original = settings.dry_run
    settings.dry_run = True
    try:
        ctx = _make_ctx(risk_total=90.0)
        await run_decision_engine(ctx)
        assert ctx.decision.action == ActionType.SILENT_LOG
    finally:
        settings.dry_run = original
