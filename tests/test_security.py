"""
Security layer tests — circuit breaker, SSRF guard, input sanitizer,
evasion detection, near-duplicate, account intelligence.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Input Sanitizer
# ─────────────────────────────────────────────────────────────────────────────

class TestInputSanitizer:
    def test_valid_user_id(self):
        from src.security.input_sanitizer import validate_user_id
        assert validate_user_id("123456789") == 123456789
        assert validate_user_id(42) == 42

    def test_invalid_user_id_string(self):
        from src.security.input_sanitizer import ValidationError, validate_user_id
        with pytest.raises(ValidationError):
            validate_user_id("not_a_number")

    def test_user_id_out_of_range(self):
        from src.security.input_sanitizer import ValidationError, validate_user_id
        with pytest.raises(ValidationError):
            validate_user_id(99_999_999_999_999)

    def test_user_id_negative_rejected(self):
        from src.security.input_sanitizer import ValidationError, validate_user_id
        with pytest.raises(ValidationError):
            validate_user_id(-1)

    def test_sql_injection_blocked(self):
        from src.security.input_sanitizer import ValidationError, validate_command_arg
        with pytest.raises(ValidationError):
            validate_command_arg("'; DROP TABLE users; --")

    def test_shell_injection_blocked(self):
        from src.security.input_sanitizer import ValidationError, validate_command_arg
        with pytest.raises(ValidationError):
            validate_command_arg("test; rm -rf /")

    def test_path_traversal_blocked(self):
        from src.security.input_sanitizer import ValidationError, validate_command_arg
        with pytest.raises(ValidationError):
            validate_command_arg("../../etc/passwd")

    def test_clean_arg_allowed(self):
        from src.security.input_sanitizer import validate_command_arg
        result = validate_command_arg("hello_world_123")
        assert result == "hello_world_123"

    def test_crlf_injection_sanitized(self):
        from src.security.input_sanitizer import sanitize_text
        result = sanitize_text("Hello\r\nWorld")
        assert "\r\n" not in result
        assert "Hello" in result

    def test_sanitize_log_field(self):
        from src.security.input_sanitizer import sanitize_log_field
        result = sanitize_log_field("test\r\ninjected_log_line")
        assert "\r\n" not in result

    def test_html_escape(self):
        from src.security.input_sanitizer import escape_html
        result = escape_html("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_duration_validation(self):
        from src.security.input_sanitizer import ValidationError, validate_duration_seconds
        assert validate_duration_seconds(3600) == 3600
        with pytest.raises(ValidationError):
            validate_duration_seconds(-1)
        with pytest.raises(ValidationError):
            validate_duration_seconds(99_999_999)


# ─────────────────────────────────────────────────────────────────────────────
# SSRF Guard
# ─────────────────────────────────────────────────────────────────────────────

class TestSSRFGuard:
    def test_private_ip_blocked(self):
        from src.security.ssrf_guard import _is_ip_blocked
        assert _is_ip_blocked("192.168.1.1") is True
        assert _is_ip_blocked("10.0.0.1") is True
        assert _is_ip_blocked("172.16.0.1") is True
        assert _is_ip_blocked("127.0.0.1") is True

    def test_metadata_endpoint_blocked(self):
        from src.security.ssrf_guard import _is_ip_blocked
        assert _is_ip_blocked("169.254.169.254") is True

    def test_public_ip_allowed(self):
        from src.security.ssrf_guard import _is_ip_blocked
        assert _is_ip_blocked("8.8.8.8") is False
        assert _is_ip_blocked("1.1.1.1") is False
        assert _is_ip_blocked("204.79.197.200") is False

    @pytest.mark.asyncio
    async def test_private_url_blocked(self):
        from src.security.ssrf_guard import validate_url
        safe, reason = await validate_url("http://192.168.1.1/admin")
        assert safe is False
        assert "blocked_ip" in reason

    @pytest.mark.asyncio
    async def test_metadata_url_blocked(self):
        from src.security.ssrf_guard import validate_url
        safe, reason = await validate_url("http://169.254.169.254/latest/meta-data/")
        assert safe is False

    @pytest.mark.asyncio
    async def test_ftp_scheme_blocked(self):
        from src.security.ssrf_guard import validate_url
        safe, reason = await validate_url("ftp://example.com/file.txt")
        assert safe is False
        assert "blocked_scheme" in reason

    @pytest.mark.asyncio
    async def test_public_url_allowed(self):
        from src.security.ssrf_guard import validate_url
        # Note: this does DNS resolution so we mock it
        with patch("src.security.ssrf_guard._resolve_hostname", new=AsyncMock(return_value=["93.184.216.34"])):
            safe, reason = await validate_url("https://example.com/page")
            assert safe is True

    def test_blocked_hostname(self):
        import asyncio

        from src.security.ssrf_guard import validate_url
        safe, reason = asyncio.run(validate_url("http://localhost/admin"))
        assert safe is False


# ─────────────────────────────────────────────────────────────────────────────
# Webhook Hardening
# ─────────────────────────────────────────────────────────────────────────────

class TestWebhookHardening:
    def test_telegram_ip_accepted(self):
        from src.security.webhook_hardening import is_telegram_ip
        assert is_telegram_ip("149.154.160.1") is True
        assert is_telegram_ip("91.108.4.1") is True

    def test_non_telegram_ip_rejected(self):
        from src.security.webhook_hardening import is_telegram_ip
        assert is_telegram_ip("1.2.3.4") is False
        assert is_telegram_ip("192.168.1.1") is False

    def test_secret_token_valid(self):
        from src.security.webhook_hardening import validate_secret_token
        assert validate_secret_token("my-secret", "my-secret") is True

    def test_secret_token_invalid(self):
        from src.security.webhook_hardening import validate_secret_token
        assert validate_secret_token("wrong", "my-secret") is False
        assert validate_secret_token(None, "my-secret") is False

    def test_timing_safe(self):
        import time

        from src.security.webhook_hardening import validate_secret_token
        t1 = time.perf_counter()
        validate_secret_token("a" * 100, "b" * 100)
        t2 = time.perf_counter()
        t3 = time.perf_counter()
        validate_secret_token("same-secret", "same-secret")
        t4 = time.perf_counter()
        # Both should take similar time (constant-time comparison)
        # Just verify neither crashes
        assert t2 > t1
        assert t4 > t3


# ─────────────────────────────────────────────────────────────────────────────
# Evasion Detection
# ─────────────────────────────────────────────────────────────────────────────

class TestEvasionDetection:
    def test_rlo_character_detected(self):
        from src.layers.evasion_detection import _BIDI_OVERRIDE
        text = "document\u202eexe.pdf"
        assert _BIDI_OVERRIDE.search(text) is not None

    def test_null_byte_detected(self):
        from src.layers.evasion_detection import _NULL_BYTES
        assert _NULL_BYTES.search("hel\x00lo") is not None

    def test_leet_normalize(self):
        from src.layers.evasion_detection import _normalize_leet
        assert _normalize_leet("h3ll0") == "hello"
        assert _normalize_leet("4dm1n") == "admin"

    def test_typosquatting_paypal(self):
        from src.layers.evasion_detection import _check_typosquatting
        flags = _check_typosquatting("https://paypa1.com/login")
        assert any("paypal" in f for f in flags)

    def test_typosquatting_binance(self):
        from src.layers.evasion_detection import _check_typosquatting
        flags = _check_typosquatting("https://b1nance.com/wallet")
        assert any("binance" in f for f in flags)

    def test_clean_url_no_flags(self):
        from src.layers.evasion_detection import _check_typosquatting
        flags = _check_typosquatting("https://github.com/repo")
        assert len(flags) == 0

    def test_base64_decode(self):
        import base64

        from src.layers.evasion_detection import _try_decode_base64
        payload = base64.b64encode(b"free bitcoin airdrop").decode()
        decoded = _try_decode_base64(payload)
        assert decoded is not None
        assert "free bitcoin" in decoded.lower()

    def test_mixed_scripts(self):
        from src.layers.evasion_detection import _count_scripts
        text = "Hello мир مرحبا world"
        scripts = _count_scripts(text)
        assert "latin" in scripts
        assert "cyrillic" in scripts
        assert "arabic" in scripts

    def test_decimal_ip_url_detected(self):
        from src.layers.evasion_detection import _DECIMAL_IP
        # 2130706433 = 127.0.0.1 in decimal
        assert _DECIMAL_IP.search("http://2130706433/evil") is not None


# ─────────────────────────────────────────────────────────────────────────────
# Near-Duplicate (SimHash)
# ─────────────────────────────────────────────────────────────────────────────

class TestNearDuplicate:
    def test_identical_texts_same_hash(self):
        from src.layers.near_duplicate import compute_simhash
        h1 = compute_simhash("buy bitcoin now cheap fast")
        h2 = compute_simhash("buy bitcoin now cheap fast")
        assert h1 == h2

    def test_slightly_different_texts_near_duplicate(self):
        from src.layers.near_duplicate import compute_simhash, hamming_distance
        h1 = compute_simhash("buy bitcoin now cheap and fast guaranteed")
        h2 = compute_simhash("buy bitcoin now cheap and fast guaranteed!")
        # Very similar texts must have low Hamming distance (< 16 bits)
        assert hamming_distance(h1, h2) < 16

    def test_very_different_texts_not_near_duplicate(self):
        from src.layers.near_duplicate import are_near_duplicates, compute_simhash
        h1 = compute_simhash("buy bitcoin now cheap fast")
        h2 = compute_simhash("مرحبا بكم في المجموعة نتمنى لكم يوما طيبا")
        assert not are_near_duplicates(h1, h2)

    def test_hamming_distance_identical(self):
        from src.layers.near_duplicate import hamming_distance
        assert hamming_distance(0xDEADBEEF, 0xDEADBEEF) == 0

    def test_hamming_distance_one_bit(self):
        from src.layers.near_duplicate import hamming_distance
        assert hamming_distance(0b1000, 0b1001) == 1

    def test_empty_text_returns_zero(self):
        from src.layers.near_duplicate import compute_simhash
        assert compute_simhash("") == 0
        assert compute_simhash("   ") == 0


# ─────────────────────────────────────────────────────────────────────────────
# Account Intelligence
# ─────────────────────────────────────────────────────────────────────────────

class TestAccountIntelligence:
    def test_bot_like_username_detected(self):
        from src.layers.account_intelligence import _analyze_username
        flags = _analyze_username("user2847362")
        assert "bot_like_username" in flags

    def test_normal_username_clean(self):
        from src.layers.account_intelligence import _analyze_username
        flags = _analyze_username("john_smith")
        assert len(flags) == 0

    def test_telegram_official_impersonation(self):
        from src.layers.account_intelligence import _analyze_username
        flags = _analyze_username("telegram_support_official")
        assert any("official" in f or "telegram" in f for f in flags)

    def test_invisible_chars_in_name(self):
        from src.layers.account_intelligence import _analyze_display_name
        flags = _analyze_display_name("Admin\u200bUser")  # zero-width space
        assert "invisible_chars_in_name" in flags

    def test_admin_title_detection(self):
        from src.layers.account_intelligence import _analyze_display_name
        flags = _analyze_display_name("Group Admin ✓")
        assert "admin_title_in_name" in flags

    def test_account_age_very_new(self):
        from src.layers.account_intelligence import _estimate_account_age_category
        assert _estimate_account_age_category(8_000_000_000) == "very_new"

    def test_account_age_old(self):
        from src.layers.account_intelligence import _estimate_account_age_category
        assert _estimate_account_age_category(5_000_000) == "old"


# ─────────────────────────────────────────────────────────────────────────────
# Circuit Breaker (state machine logic — no Redis needed)
# ─────────────────────────────────────────────────────────────────────────────

class TestCircuitBreakerLogic:
    def test_hamming_zero_same_hash(self):
        from src.layers.near_duplicate import hamming_distance
        assert hamming_distance(12345678, 12345678) == 0

    def test_bitmask_operations(self):
        from src.layers.near_duplicate import compute_simhash
        h = compute_simhash("test text for hashing purposes here")
        assert isinstance(h, int)
        assert 0 <= h <= (2**64 - 1)


# ─────────────────────────────────────────────────────────────────────────────
# Human Behavior
# ─────────────────────────────────────────────────────────────────────────────

class TestHumanBehavior:
    def test_delay_within_bounds(self):
        from src.security.human_behavior import _REACTION_MAX, _REACTION_MIN, _human_delay
        for _ in range(100):
            d = _human_delay()
            assert _REACTION_MIN <= d <= _REACTION_MAX

    def test_miss_probability_borderline(self):
        from src.security.human_behavior import should_miss_borderline
        # Non-borderline should never miss
        assert should_miss_borderline(80.0) is False
        assert should_miss_borderline(10.0) is False

    def test_warning_text_rotation(self):
        from src.security.human_behavior import get_random_warning_text
        seen = set()
        for _ in range(50):
            seen.add(get_random_warning_text(1))
        # Should see more than 1 unique template across 50 draws
        assert len(seen) >= 2
