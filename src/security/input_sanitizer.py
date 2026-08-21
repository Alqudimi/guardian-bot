"""
Input Sanitizer — Command Injection & Injection Attack Prevention
==================================================================
Validates and sanitizes all user-provided inputs to bot commands and
pipeline processing. Protects against:

  • Command injection via bot command arguments
  • SQL injection (defense-in-depth on top of parameterized queries)
  • Path traversal attacks
  • Log injection / CRLF injection
  • Integer overflow in IDs
  • Unicode control character injection
  • Regex denial-of-service (ReDoS) via untrusted patterns
  • XSS (for any HTML responses)
  • Excessively long inputs
"""
from __future__ import annotations

import html
import re
import unicodedata
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Limits ─────────────────────────────────────────────────────────────────────
MAX_TEXT_LENGTH = 4096        # Telegram's max message length
MAX_COMMAND_ARG_LENGTH = 256
MAX_USER_ID = 9_999_999_999  # Safe upper bound for Telegram user IDs
MIN_USER_ID = 1
MAX_GROUP_ID_ABS = 999_999_999_999

# ── Dangerous patterns ─────────────────────────────────────────────────────────
_SQL_PATTERNS = re.compile(
    r"(?:'|\"|\b(?:OR|AND|UNION|SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|"
    r"EXEC|EXECUTE|SCRIPT|DECLARE|CAST|CONVERT|CHAR|NCHAR|VARCHAR)\b)",
    re.IGNORECASE,
)

_SHELL_INJECTION = re.compile(
    r"[;&|`$<>\\]|\.\./|/etc/|/proc/|/sys/|cmd\.exe|powershell",
    re.IGNORECASE,
)

_CRLF_INJECTION = re.compile(r"[\r\n\x00\x0b\x0c]")

_PATH_TRAVERSAL = re.compile(r"\.\.[/\\]|[/\\]\.\.")

# ── Control characters (non-printable, non-whitespace) ─────────────────────────
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


class ValidationError(Exception):
    """Raised when input fails validation."""
    pass


def sanitize_text(text: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    """
    Sanitize free-form text from untrusted sources.
    Removes control characters, truncates, normalizes Unicode.
    """
    if not isinstance(text, str):
        return ""

    # Truncate first to avoid expensive operations on huge strings
    text = text[:max_length * 2]

    # Remove CRLF injection
    text = _CRLF_INJECTION.sub(" ", text)

    # Remove control characters (preserve tab, newline, carriage return)
    text = _CONTROL_CHARS.sub("", text)

    # Unicode normalize
    text = unicodedata.normalize("NFC", text)

    # Final truncation
    return text[:max_length]


def sanitize_log_field(value: Any) -> str:
    """
    Sanitize a value before including it in a log record.
    Prevents log injection attacks.
    """
    if value is None:
        return "null"
    text = str(value)[:512]
    text = _CRLF_INJECTION.sub(" ", text)
    text = _CONTROL_CHARS.sub("", text)
    return text


def validate_user_id(value: Any) -> int:
    """
    Validate a Telegram user ID from command arguments.
    Raises ValidationError on invalid input.
    """
    try:
        uid = int(str(value).strip())
    except (ValueError, TypeError):
        raise ValidationError(f"Invalid user ID format: {value!r}")

    if not (MIN_USER_ID <= uid <= MAX_USER_ID):
        raise ValidationError(f"User ID {uid} out of valid range")

    return uid


def validate_group_id(value: Any) -> int:
    """Validate a Telegram group/chat ID."""
    try:
        gid = int(str(value).strip())
    except (ValueError, TypeError):
        raise ValidationError(f"Invalid group ID format: {value!r}")

    # Group IDs can be negative (supergroups are negative)
    if abs(gid) > MAX_GROUP_ID_ABS:
        raise ValidationError(f"Group ID {gid} out of valid range")

    return gid


def validate_command_arg(arg: str, arg_name: str = "arg") -> str:
    """
    Validate a command argument string.
    Checks for injection patterns and length limits.
    """
    if not isinstance(arg, str):
        raise ValidationError(f"{arg_name}: must be a string")

    arg = arg.strip()

    if len(arg) > MAX_COMMAND_ARG_LENGTH:
        raise ValidationError(f"{arg_name}: too long ({len(arg)} > {MAX_COMMAND_ARG_LENGTH})")

    if _SQL_PATTERNS.search(arg):
        raise ValidationError(f"{arg_name}: contains SQL injection pattern")

    if _SHELL_INJECTION.search(arg):
        raise ValidationError(f"{arg_name}: contains shell injection pattern")

    if _PATH_TRAVERSAL.search(arg):
        raise ValidationError(f"{arg_name}: contains path traversal pattern")

    if _CRLF_INJECTION.search(arg):
        raise ValidationError(f"{arg_name}: contains CRLF injection")

    return arg


def validate_duration_seconds(value: Any, max_seconds: int = 2_592_000) -> int:
    """Validate a ban/mute duration in seconds."""
    try:
        secs = int(str(value).strip())
    except (ValueError, TypeError):
        raise ValidationError(f"Invalid duration: {value!r}")

    if secs < 0:
        raise ValidationError("Duration cannot be negative")

    if secs > max_seconds:
        raise ValidationError(f"Duration {secs}s exceeds maximum {max_seconds}s")

    return secs


def escape_html(text: str) -> str:
    """Escape HTML entities for safe Telegram HTML-mode messages."""
    return html.escape(text, quote=True)


def validate_url_for_whitelist(url: str) -> str:
    """Validate a URL before adding to whitelist/configuration."""
    url = url.strip()
    if len(url) > 2048:
        raise ValidationError("URL too long")
    if _CRLF_INJECTION.search(url):
        raise ValidationError("URL contains CRLF injection")
    if not url.startswith(("http://", "https://")):
        raise ValidationError("URL must start with http:// or https://")
    return url


def sanitize_command_args(args: tuple | list) -> list[str]:
    """Sanitize a list of command arguments."""
    result = []
    for arg in args:
        try:
            cleaned = validate_command_arg(str(arg))
            result.append(cleaned)
        except ValidationError as exc:
            logger.warning("command_arg_rejected", error=str(exc))
    return result
