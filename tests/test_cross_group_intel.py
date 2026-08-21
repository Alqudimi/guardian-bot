"""
Tests for cross-group threat intelligence and adaptive thresholds.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, patch

import pytest


class TestCrossGroupIntelligence:
    def test_threat_level_enum_ordering(self):
        from src.intelligence.cross_group_intel import ThreatLevel
        assert ThreatLevel.NONE < ThreatLevel.LOW
        assert ThreatLevel.LOW < ThreatLevel.MEDIUM
        assert ThreatLevel.MEDIUM < ThreatLevel.HIGH
        assert ThreatLevel.HIGH < ThreatLevel.CRITICAL

    def test_ban_count_to_threat_mapping(self):
        from src.intelligence.cross_group_intel import _BAN_TO_THREAT, ThreatLevel
        assert _BAN_TO_THREAT[1] == ThreatLevel.LOW
        assert _BAN_TO_THREAT[3] == ThreatLevel.MEDIUM
        assert _BAN_TO_THREAT[5] == ThreatLevel.HIGH
        assert _BAN_TO_THREAT[8] == ThreatLevel.CRITICAL

    def test_threat_ttl_longer_for_higher_levels(self):
        from src.intelligence.cross_group_intel import _THREAT_TTL, ThreatLevel
        assert _THREAT_TTL[ThreatLevel.LOW] < _THREAT_TTL[ThreatLevel.HIGH]
        assert _THREAT_TTL[ThreatLevel.HIGH] < _THREAT_TTL[ThreatLevel.CRITICAL]

    @pytest.mark.asyncio
    @patch("src.intelligence.cross_group_intel.get_redis")
    async def test_get_user_threat_empty(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_get_redis.return_value = mock_redis

        from src.intelligence.cross_group_intel import ThreatLevel, get_user_threat
        profile = await get_user_threat(99999)
        assert profile.threat_level == ThreatLevel.NONE
        assert profile.ban_count == 0

    @pytest.mark.asyncio
    @patch("src.intelligence.cross_group_intel.get_redis")
    async def test_should_restrict_none_threat(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_get_redis.return_value = mock_redis

        from src.intelligence.cross_group_intel import (
            ThreatLevel,
            should_apply_cross_group_restrictions,
        )
        should, level, reason = await should_apply_cross_group_restrictions(12345, -100001)
        assert should is False
        assert level == ThreatLevel.NONE


class TestAdaptiveThresholds:
    def test_safe_float_valid(self):
        from src.intelligence.adaptive_thresholds import _safe_float
        assert _safe_float("0.65") == 0.65
        assert _safe_float(None) is None
        assert _safe_float("") is None

    def test_safe_int_valid(self):
        from src.intelligence.adaptive_thresholds import _safe_int
        assert _safe_int("8") == 8
        assert _safe_int(None) is None

    @pytest.mark.asyncio
    @patch("src.intelligence.adaptive_thresholds.get_redis")
    async def test_record_group_message_no_crash(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.zadd = AsyncMock()
        mock_redis.zremrangebyscore = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_get_redis.return_value = mock_redis

        from src.intelligence.adaptive_thresholds import record_group_message
        await record_group_message(-100001)

    @pytest.mark.asyncio
    @patch("src.intelligence.adaptive_thresholds.get_redis")
    async def test_false_positive_recorded(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()
        mock_redis.delete = AsyncMock()
        mock_get_redis.return_value = mock_redis

        from src.intelligence.adaptive_thresholds import record_false_positive
        await record_false_positive(-100001)
        mock_redis.incr.assert_called_once()
