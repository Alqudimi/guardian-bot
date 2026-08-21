"""
Unit tests for the Message Normalization Layer.
Run with: python -m pytest tests/test_normalization.py -v
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


from src.layers.normalization import (
    _INVISIBLE_CHARS,
    _clean_zalgo,
    _compute_fingerprint,
    _extract_urls,
    _normalize_homoglyphs,
)


class TestZalgoClean:
    def test_zalgo_cleaned(self):
        zalgo_text = "H\u0300\u0301\u0302ello"
        cleaned, detected = _clean_zalgo(zalgo_text)
        assert detected is True
        assert cleaned == "Hello"

    def test_clean_text_unchanged(self):
        text = "Hello World"
        cleaned, detected = _clean_zalgo(text)
        assert detected is False
        assert cleaned == text

    def test_arabic_not_affected(self):
        arabic = "مرحبا بالعالم"
        cleaned, detected = _clean_zalgo(arabic)
        assert detected is False
        assert cleaned == arabic


class TestHomoglyphNormalization:
    def test_cyrillic_to_ascii(self):
        # Cyrillic 'а' (U+0430) should map to 'a'
        text = "\u0430pple"
        normalized, changed = _normalize_homoglyphs(text)
        assert changed is True
        assert normalized == "apple"

    def test_arabic_variant_normalized(self):
        # ک (U+06A9) → ك (U+0643)
        text = "بن\u06a9"
        normalized, changed = _normalize_homoglyphs(text)
        assert changed is True

    def test_clean_text_unchanged(self):
        text = "normal text"
        normalized, changed = _normalize_homoglyphs(text)
        assert changed is False
        assert normalized == text


class TestURLExtraction:
    def test_http_url(self):
        text = "Check this out https://example.com/path?q=1"
        urls = _extract_urls(text)
        assert len(urls) == 1
        assert "https://example.com" in urls[0]

    def test_telegram_invite(self):
        text = "Join us at t.me/joinchat/ABCDEF123456"
        urls = _extract_urls(text)
        assert len(urls) == 1

    def test_multiple_urls(self):
        text = "Visit http://a.com and https://b.com"
        urls = _extract_urls(text)
        assert len(urls) == 2

    def test_no_urls(self):
        text = "No links here at all"
        urls = _extract_urls(text)
        assert len(urls) == 0


class TestFingerprint:
    def test_same_text_same_fingerprint(self):
        text = "Hello world"
        assert _compute_fingerprint(text) == _compute_fingerprint(text)

    def test_different_texts(self):
        assert _compute_fingerprint("text1") != _compute_fingerprint("text2")

    def test_whitespace_normalized(self):
        # Extra spaces should produce same fingerprint
        assert _compute_fingerprint("hello   world") == _compute_fingerprint("hello world")

    def test_case_normalized(self):
        assert _compute_fingerprint("Hello") == _compute_fingerprint("hello")


class TestInvisibleCharRemoval:
    def test_zero_width_removed(self):
        text = "hel\u200blo"
        cleaned = _INVISIBLE_CHARS.sub("", text)
        assert cleaned == "hello"

    def test_bidi_marks_removed(self):
        text = "text\u202amore"
        cleaned = _INVISIBLE_CHARS.sub("", text)
        assert cleaned == "textmore"
