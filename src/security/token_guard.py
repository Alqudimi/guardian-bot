"""
Token Guard — Secret & Credential Leakage Prevention
======================================================
Prevents accidental leakage of bot tokens, API keys, and secrets
through messages, logs, or error outputs.

1. **Outbound message scanning** — before the bot sends any message,
   scan it for patterns matching known secret formats and redact them.
2. **Log sanitization** — ensure structured log records never contain
   raw token values.
3. **Error message sanitization** — strip exception messages that may
   contain connection strings or tokens before forwarding to admins.
4. **Pattern library** — covers Telegram bot tokens, Redis URLs with
   passwords, PostgreSQL DSNs, AWS keys, generic API key patterns,
   JWT tokens, private key blocks.

Used as a pre-send filter on all bot-generated messages.
"""
from __future__ import annotations

import re

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Secret patterns ────────────────────────────────────────────────────────────
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Telegram bot token: 123456789:ABCdefGHI...
    ("telegram_token", re.compile(r"\d{8,12}:[A-Za-z0-9_-]{35}", re.ASCII)),
    # Redis URL with password: redis://:password@host
    ("redis_url", re.compile(r"redis://[^:@\s]+:[^@\s]+@", re.IGNORECASE)),
    # PostgreSQL DSN
    ("pg_dsn", re.compile(r"postgresql(?:\+asyncpg)?://[^:@\s]+:[^@\s]+@", re.IGNORECASE)),
    # AWS Access Key
    ("aws_key", re.compile(r"(?:AKIA|AIPA|AROA|ASIA)[A-Z0-9]{16}", re.ASCII)),
    # AWS Secret Key (40 chars base64-ish after known marker)
    ("aws_secret", re.compile(r"(?:aws_secret|AWS_SECRET)[_A-Z]*\s*[=:]\s*[A-Za-z0-9+/]{40}", re.IGNORECASE)),
    # Generic API key patterns
    ("api_key", re.compile(r"(?:api[_-]?key|apikey|access[_-]?token|secret[_-]?key)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{20,}", re.IGNORECASE)),
    # JWT tokens (three base64url segments)
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")),
    # Private key blocks
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE)),
    # Generic 40-char hex secrets (git tokens, etc.)
    ("hex_secret", re.compile(r"\b[0-9a-f]{40}\b", re.ASCII)),
]

_REDACTED = "[REDACTED]"


def sanitize_message(text: str) -> str:
    """
    Scan outbound message text for secret patterns and redact them.
    Returns sanitized text safe to send to users/admins.
    """
    for name, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            text = pattern.sub(_REDACTED, text)
            logger.warning("token_guard_redacted", pattern_name=name)
    return text


def sanitize_error(exc: Exception) -> str:
    """
    Convert an exception to a safe string, stripping credential patterns.
    Use this before including error details in messages to admins.
    """
    raw = str(exc)
    return sanitize_message(raw)[:500]


def sanitize_dict(data: dict) -> dict:
    """
    Recursively sanitize a dictionary (e.g., log record fields).
    """
    result = {}
    for k, v in data.items():
        if isinstance(v, str):
            result[k] = sanitize_message(v)
        elif isinstance(v, dict):
            result[k] = sanitize_dict(v)
        else:
            result[k] = v
    return result


def scan_for_leaks(text: str) -> list[str]:
    """
    Return a list of pattern names found in text.
    Used for alerting without modifying the original text.
    """
    found = []
    for name, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            found.append(name)
    return found
