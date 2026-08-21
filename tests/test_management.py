"""
Tests for management system: group settings, smart warns,
language guard, reports, rules, welcome manager.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _WarnPipeline:
    def __init__(self, raw):
        self.raw = raw

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def watch(self, key):
        return None

    async def get(self, key):
        return self.raw

    def multi(self):
        return self

    def set(self, key, value):
        return self

    def expire(self, key, seconds):
        return self

    async def execute(self):
        return [True, True]


# ─────────────────────────────────────────────────────────────────────────────
# Group Settings
# ─────────────────────────────────────────────────────────────────────────────

class TestGroupSettings:
    @pytest.mark.asyncio
    @patch("src.management.group_settings.get_redis")
    async def test_get_default_setting(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.hget = AsyncMock(return_value=None)
        mock_get_redis.return_value = mock_redis

        from src.management.group_settings import get_setting
        result = await get_setting(-100001, "captcha")
        assert result == "off"

    @pytest.mark.asyncio
    @patch("src.management.group_settings.get_redis")
    async def test_set_valid_setting(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_get_redis.return_value = mock_redis

        from src.management.group_settings import set_setting
        await set_setting(-100001, "captcha", "on")
        mock_redis.hset.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_setting_value_raises(self):
        from src.management.group_settings import set_setting
        with pytest.raises(ValueError):
            with patch("src.management.group_settings.get_redis") as m:
                m.return_value = AsyncMock()
                await set_setting(-100001, "captcha", "maybe")

    def test_defaults_cover_all_fields(self):
        from src.management.group_settings import _DEFAULTS
        required = {"captcha", "antiforward", "lang_policy", "warn_limit", "welcome_enabled"}
        for field in required:
            assert field in _DEFAULTS

    @pytest.mark.asyncio
    @patch("src.management.group_settings.get_redis")
    async def test_get_all_settings_merges_defaults(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={b"captcha": b"on"})
        mock_get_redis.return_value = mock_redis

        from src.management.group_settings import get_all_settings
        s = await get_all_settings(-100001)
        assert s["captcha"] == "on"
        assert s["antiforward"] == "off"  # Default


# ─────────────────────────────────────────────────────────────────────────────
# Smart Warn System
# ─────────────────────────────────────────────────────────────────────────────

class TestSmartWarn:
    @pytest.mark.asyncio
    @patch("src.layers.smart_warn.get_redis")
    async def test_first_warn_gives_warn_delete(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=_WarnPipeline(None))
        mock_get_redis.return_value = mock_redis

        from src.layers.smart_warn import add_warn
        with patch("src.layers.smart_warn.get_setting", new=AsyncMock(return_value="5")):
            status = await add_warn(123, -456, "spam", 70.0)
        assert status.active_warn_count == 1
        assert status.next_action == "warn_delete"

    @pytest.mark.asyncio
    @patch("src.layers.smart_warn.get_redis")
    async def test_fourth_warn_escalates_to_ban(self, mock_get_redis):
        import json
        import time
        mock_redis = AsyncMock()
        existing = [
            {"timestamp": time.time() - 100, "violation_type": "spam",
             "risk_score": 70.0, "action_taken": "warn", "message_preview": ""}
            for _ in range(3)
        ]
        history_json = json.dumps(existing).encode()
        mock_redis.get = AsyncMock(return_value=history_json)
        mock_redis.set = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=_WarnPipeline(history_json))
        mock_get_redis.return_value = mock_redis

        from src.layers.smart_warn import add_warn
        with patch("src.layers.smart_warn.get_setting", new=AsyncMock(return_value="5")):
            status = await add_warn(123, -456, "spam", 70.0)
        assert status.active_warn_count == 4
        assert status.next_action == "ban_temp"

    @pytest.mark.asyncio
    @patch("src.layers.smart_warn.get_redis")
    async def test_fifth_warn_perm_ban(self, mock_get_redis):
        import json
        import time
        mock_redis = AsyncMock()
        existing = [
            {"timestamp": time.time() - 100, "violation_type": "spam",
             "risk_score": 80.0, "action_taken": "ban_temp", "message_preview": ""}
            for _ in range(4)
        ]
        history_json = json.dumps(existing).encode()
        mock_redis.get = AsyncMock(side_effect=[history_json, None])
        mock_redis.set = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=_WarnPipeline(history_json))
        mock_get_redis.return_value = mock_redis

        from src.layers.smart_warn import add_warn
        with patch("src.layers.smart_warn.get_setting", new=AsyncMock(return_value="5")):
            status = await add_warn(123, -456, "spam", 80.0)
        assert status.next_action == "ban_perm"

    def test_warn_ladder_mute_durations(self):
        from src.layers.smart_warn import _build_ladder
        ladder = _build_ladder()
        assert ladder[1]["mute"] == 600    # 10 min
        assert ladder[2]["mute"] == 3600   # 1 hour
        assert ladder[3]["ban"] == 86400   # 24 hours

    @pytest.mark.asyncio
    @patch("src.layers.smart_warn.get_redis")
    async def test_reset_warns(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()
        mock_get_redis.return_value = mock_redis

        from src.layers.smart_warn import reset_warns
        await reset_warns(123, -456)
        mock_redis.delete.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Language Guard
# ─────────────────────────────────────────────────────────────────────────────

class TestLanguageGuard:
    def test_arabic_text_detected(self):
        from src.layers.language_guard import detect_language
        result = detect_language("مرحبا كيف حالك اليوم يا صديقي")
        assert result.dominant == "ar"
        assert result.ar_ratio > 0.8

    def test_english_text_detected(self):
        from src.layers.language_guard import detect_language
        result = detect_language("hello how are you doing today")
        assert result.dominant == "en"
        assert result.latin_ratio > 0.8

    def test_russian_text_detected(self):
        from src.layers.language_guard import detect_language
        result = detect_language("привет как дела сегодня")
        assert result.dominant == "ru"

    def test_mixed_text_detected(self):
        from src.layers.language_guard import detect_language
        result = detect_language("Hello مرحبا how are you")
        assert result.mixed is True

    def test_policy_violation_arabic_only(self):
        from src.layers.language_guard import _text_violates_policy
        assert _text_violates_policy("en", "ar") is True
        assert _text_violates_policy("ar", "ar") is False

    def test_policy_bilingual_ar_en(self):
        from src.layers.language_guard import _text_violates_policy
        assert _text_violates_policy("ar", "ar+en") is False
        assert _text_violates_policy("en", "ar+en") is False
        assert _text_violates_policy("ru", "ar+en") is True

    def test_neutral_never_violates(self):
        from src.layers.language_guard import _text_violates_policy
        assert _text_violates_policy("neutral", "ar") is False
        assert _text_violates_policy("neutral", "en") is False

    def test_any_policy_never_violates(self):
        from src.layers.language_guard import _text_violates_policy
        assert _text_violates_policy("ru", "any") is False
        assert _text_violates_policy("cjk", "any") is False

    def test_short_text_neutral(self):
        from src.layers.language_guard import detect_language
        result = detect_language("ok")
        assert result.dominant == "neutral"


# ─────────────────────────────────────────────────────────────────────────────
# Reports
# ─────────────────────────────────────────────────────────────────────────────

class TestReports:
    @pytest.mark.asyncio
    @patch("src.management.reports.get_redis")
    async def test_generate_report_empty(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.get = AsyncMock(return_value=None)
        mock_get_redis.return_value = mock_redis

        from src.management.reports import generate_report
        report = await generate_report(-100001, days=7)
        assert report.chat_id == -100001
        assert report.total_processed == 0

    def test_format_report_no_crash(self):
        from datetime import datetime

        from src.management.reports import ModerationReport, format_report
        report = ModerationReport(
            chat_id=-100001,
            period_start=datetime.now(tz=UTC),
            period_end=datetime.now(tz=UTC),
            actions={"delete": 10, "ban_temp": 3},
            violations={"spam": 8, "toxic": 5},
            total_processed=13,
            captcha_pass=20,
            captcha_fail=5,
            raids=2,
            circuit_trips=1,
            top_offenders=[(42, 3)],
        )
        text = format_report(report)
        assert "delete" in text
        assert "spam" in text
        assert "20✅" in text
        assert "Raids" in text
        assert "42" in text

    @pytest.mark.asyncio
    @patch("src.management.reports.get_redis")
    async def test_record_action_stat(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.hincrby = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_get_redis.return_value = mock_redis

        from src.management.reports import record_action_stat
        await record_action_stat(-100001, "delete", "spam")
        assert mock_redis.hincrby.call_count == 2

    @pytest.mark.asyncio
    @patch("src.management.reports.get_redis")
    async def test_generate_report_includes_events_and_top_offenders(self, mock_get_redis):
        mock_redis = AsyncMock()

        async def hgetall(key: str) -> dict[str, str]:
            if key.endswith(":actions"):
                return {"delete": "3"}
            if key.endswith(":violations"):
                return {"spam": "3"}
            if key.endswith(":events"):
                return {"raids": "2", "circuit_trips": "1"}
            return {}

        mock_redis.hgetall = hgetall
        mock_redis.zrange = AsyncMock(return_value=[(b"42", 3.0), (b"99", 1.0)])
        mock_redis.get = AsyncMock(return_value=None)
        mock_get_redis.return_value = mock_redis

        from src.management.reports import generate_report

        report = await generate_report(-100001, days=1)
        assert report.raids == 2
        assert report.circuit_trips == 1
        assert report.top_offenders == [(42, 3), (99, 1)]


# ─────────────────────────────────────────────────────────────────────────────
# Token Guard
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenGuard:
    def test_telegram_token_redacted(self):
        from src.security.token_guard import sanitize_message
        # Telegram tokens are: <digits>:<35 alphanumeric chars>
        text = "Token: 123456789:ABCdefGHIjklmnopqrstuvwxyz123456789"
        result = sanitize_message(text)
        assert "ABCdef" not in result
        assert "[REDACTED]" in result

    def test_jwt_redacted(self):
        from src.security.token_guard import sanitize_message
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        result = sanitize_message(jwt)
        assert "[REDACTED]" in result

    def test_clean_text_unchanged(self):
        from src.security.token_guard import sanitize_message
        text = "مرحبا بكم في المجموعة! Hello everyone!"
        result = sanitize_message(text)
        assert result == text

    def test_scan_detects_aws_key(self):
        from src.security.token_guard import scan_for_leaks
        text = "key = AKIAIOSFODNN7EXAMPLE"
        found = scan_for_leaks(text)
        assert "aws_key" in found

    def test_pg_dsn_redacted(self):
        from src.security.token_guard import sanitize_message
        dsn = "postgresql+asyncpg://user:password123@localhost:5432/mydb"
        result = sanitize_message(dsn)
        assert "password123" not in result

    def test_sanitize_error_safe(self):
        from src.security.token_guard import sanitize_error
        exc = Exception("Connection to postgresql://user:pass@host:5432/db failed")
        result = sanitize_error(exc)
        assert "pass" not in result or "[REDACTED]" in result


# ─────────────────────────────────────────────────────────────────────────────
# DoS Protection
# ─────────────────────────────────────────────────────────────────────────────

class TestDosProtection:
    def test_shed_ai_threshold(self):
        from src.security.dos_protection import MEMORY_SHED_THRESHOLD_MB, should_shed_ai
        assert should_shed_ai(MEMORY_SHED_THRESHOLD_MB - 1) is False
        assert should_shed_ai(MEMORY_SHED_THRESHOLD_MB + 1) is True

    def test_drop_threshold(self):
        from src.security.dos_protection import MEMORY_CRITICAL_MB, should_drop_message
        assert should_drop_message(MEMORY_CRITICAL_MB - 1) is False
        assert should_drop_message(MEMORY_CRITICAL_MB + 1) is True

    @pytest.mark.asyncio
    @patch("src.security.dos_protection.get_redis")
    async def test_text_oversized(self, mock_get_redis):
        from src.security.dos_protection import check_message_safe
        mock_redis = AsyncMock()
        mock_redis.zremrangebyscore = AsyncMock()
        mock_redis.zadd = AsyncMock()
        mock_redis.zcard = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()
        mock_get_redis.return_value = mock_redis

        big_text = "a" * 100_000
        safe, reason = await check_message_safe(big_text)
        assert safe is False
        assert "text_too_large" in reason


# ─────────────────────────────────────────────────────────────────────────────
# Anti-Forward
# ─────────────────────────────────────────────────────────────────────────────

class TestAntiForward:
    @pytest.mark.asyncio
    @patch("src.layers.anti_forward.get_redis")
    async def test_forward_mode_default_off(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_get_redis.return_value = mock_redis

        from src.layers.anti_forward import get_forward_mode
        mode = await get_forward_mode(-100001)
        assert mode == "off"

    @pytest.mark.asyncio
    @patch("src.layers.anti_forward.get_redis")
    async def test_set_forward_mode(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        mock_get_redis.return_value = mock_redis

        from src.layers.anti_forward import set_forward_mode
        await set_forward_mode(-100001, "strict")
        mock_redis.set.assert_called_once()
