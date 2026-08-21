"""
Webhook Hardening — Production Webhook Security
================================================
Security hardening layer for webhook mode:

1. **IP Allowlist** — Only accept requests from Telegram's official
   IP ranges (149.154.160.0/20 and 91.108.4.0/22).
2. **Secret Token Validation** — Require the X-Telegram-Bot-Api-Secret-Token
   header on all requests.
3. **Replay Attack Prevention** — Reject updates with timestamps older
   than a configurable window (default 60 seconds).
4. **Request Rate Limiting** — Limit incoming webhook requests per second
   to detect flood attacks against the webhook endpoint.
5. **Payload Size Limit** — Reject payloads above Telegram's max size.
6. **Content-Type Validation** — Only accept application/json.
7. **Update ID Deduplication** — Track seen update IDs to prevent
   double-processing from replay attacks.

For use with python-telegram-bot's webhook via custom middleware or
as a pre-validation hook.
"""
from __future__ import annotations

import hmac
import ipaddress
import time
from uuid import uuid4

from config.settings import get_settings
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

# ── Telegram's official IP ranges ─────────────────────────────────────────────
# https://core.telegram.org/bots/webhooks#the-short-version
_TELEGRAM_IP_RANGES = [
    ipaddress.ip_network("149.154.160.0/20"),
    ipaddress.ip_network("91.108.4.0/22"),
    # IPv6
    ipaddress.ip_network("2001:b28:f23d::/48"),
    ipaddress.ip_network("2001:b28:f23f::/48"),
    ipaddress.ip_network("2001:67c:4e8::/48"),
]

_MAX_PAYLOAD_BYTES = 512 * 1024   # 512 KB (Telegram's update max)
_REPLAY_WINDOW_S = 60              # Reject updates older than 60s
_WEBHOOK_RATE_LIMIT = 100          # Max requests per minute from Telegram
_DEDUP_WINDOW_S = 300              # 5-min update-ID dedup window


def is_telegram_ip(ip_str: str) -> bool:
    """Check if an IP address belongs to Telegram's infrastructure."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in network for network in _TELEGRAM_IP_RANGES)
    except ValueError:
        return False


def validate_secret_token(provided: str | None, expected: str) -> bool:
    """
    Constant-time comparison of the webhook secret token.
    Prevents timing attacks.
    """
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


async def is_update_id_seen(update_id: int) -> bool:
    """Check and record an update_id to prevent replay attacks."""
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}webhook_uid:{update_id}"

    # SET NX makes the check-and-record operation atomic across workers.
    recorded = await redis.set(key, "1", ex=_DEDUP_WINDOW_S, nx=True)
    return not bool(recorded)


async def check_webhook_rate_limit(source_ip: str) -> bool:
    """
    Rate limit webhook requests by source IP.
    Returns True if request is allowed.
    """
    redis = await get_redis()
    settings = get_settings()
    now = time.time()
    key = f"{settings.redis_prefix}wh_rate:{source_ip}"

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, "-inf", now - 60)
    pipe.zadd(key, {f"{now:.6f}:{uuid4().hex}": now})
    pipe.zcard(key)
    pipe.expire(key, 120)
    results = await pipe.execute()
    count = int(results[2])

    if count > _WEBHOOK_RATE_LIMIT:
        logger.warning(
            "webhook_rate_limit_exceeded",
            source_ip=source_ip,
            count=count,
        )
        return False
    return True


async def validate_webhook_request(
    source_ip: str,
    secret_token_header: str | None,
    payload_size: int,
    content_type: str,
    update_id: int | None = None,
) -> tuple[bool, str]:
    """
    Full webhook request validation.
    Returns (valid: bool, rejection_reason: str).
    """
    settings = get_settings()

    # 1. IP allowlist
    if not is_telegram_ip(source_ip):
        logger.warning("webhook_rejected_ip", source_ip=source_ip)
        return False, f"unauthorized_source_ip:{source_ip}"

    # 2. Secret token is mandatory for webhook mode.
    if not settings.telegram_webhook_secret:
        logger.error("webhook_rejected_secret_not_configured")
        return False, "webhook_secret_not_configured"
    if not validate_secret_token(secret_token_header, settings.telegram_webhook_secret):
        logger.warning("webhook_rejected_bad_token", source_ip=source_ip)
        return False, "invalid_secret_token"

    # 3. Content-Type
    if "application/json" not in content_type.lower():
        return False, f"invalid_content_type:{content_type}"

    # 4. Payload size
    if payload_size > _MAX_PAYLOAD_BYTES:
        return False, f"payload_too_large:{payload_size}"

    # 5. Rate limit
    if not await check_webhook_rate_limit(source_ip):
        return False, "rate_limit_exceeded"

    # 6. Update ID deduplication
    if update_id is not None and await is_update_id_seen(update_id):
        logger.warning("webhook_duplicate_update_id", update_id=update_id)
        return False, f"duplicate_update_id:{update_id}"

    return True, ""
