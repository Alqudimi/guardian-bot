"""
Unit tests for the Risk Scoring Engine.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock

import pytest

from src.pipeline.context import (
    AISignals,
    LinkSignals,
    MediaSignals,
    SpamSignals,
    UserBehaviorSignals,
)


def _make_ctx(**kwargs) -> MagicMock:
    ctx = MagicMock()
    ctx.user_id = 12345
    ctx.chat_id = -100001
    ctx.spam = SpamSignals()
    ctx.behavior = UserBehaviorSignals()
    ctx.links = LinkSignals()
    ctx.media = MediaSignals()
    ctx.ai = AISignals()
    ctx.short_circuit = False
    for k, v in kwargs.items():
        setattr(ctx, k, v)
    return ctx


@pytest.mark.asyncio
async def test_clean_message_low_risk():
    from src.layers.risk_scoring import run_risk_scoring
    ctx = _make_ctx()
    await run_risk_scoring(ctx)
    assert ctx.risk.total < 20


@pytest.mark.asyncio
async def test_flood_raises_risk():
    from src.layers.risk_scoring import run_risk_scoring
    ctx = _make_ctx()
    ctx.spam.flood_triggered = True
    ctx.spam.flood_score = 80.0
    await run_risk_scoring(ctx)
    assert ctx.risk.total >= 20


@pytest.mark.asyncio
async def test_toxicity_raises_risk():
    from src.layers.risk_scoring import run_risk_scoring
    ctx = _make_ctx()
    ctx.ai.toxicity_score = 0.9
    ctx.ai.toxicity_label = "HATE"
    ctx.ai.hate_speech = True
    await run_risk_scoring(ctx)
    assert ctx.risk.total >= 60


@pytest.mark.asyncio
async def test_nsfw_raises_risk():
    from src.layers.risk_scoring import run_risk_scoring
    ctx = _make_ctx()
    ctx.media.nsfw_score = 0.95
    ctx.media.nsfw_detected = True
    await run_risk_scoring(ctx)
    assert ctx.risk.total >= 80


@pytest.mark.asyncio
async def test_phishing_boosts_risk():
    from src.layers.risk_scoring import run_risk_scoring
    ctx = _make_ctx()
    ctx.links.phishing_detected = True
    ctx.links.link_risk_score = 80.0
    await run_risk_scoring(ctx)
    assert ctx.risk.total >= 75


@pytest.mark.asyncio
async def test_blacklist_max_risk():
    from src.layers.risk_scoring import run_risk_scoring
    ctx = _make_ctx()
    ctx.short_circuit = True
    ctx.spam.blacklist_hit = True
    ctx.spam.whitelist_hit = False
    await run_risk_scoring(ctx)
    assert ctx.risk.total == 100.0


@pytest.mark.asyncio
async def test_whitelist_zero_risk():
    from src.layers.risk_scoring import run_risk_scoring
    ctx = _make_ctx()
    ctx.short_circuit = True
    ctx.spam.whitelist_hit = True
    await run_risk_scoring(ctx)
    assert ctx.risk.total == 0.0


@pytest.mark.asyncio
async def test_explanation_populated():
    from src.layers.risk_scoring import run_risk_scoring
    ctx = _make_ctx()
    ctx.spam.flood_triggered = True
    ctx.spam.flood_score = 60.0
    await run_risk_scoring(ctx)
    assert ctx.risk.explanation
    assert "risk_score" in ctx.risk.explanation
