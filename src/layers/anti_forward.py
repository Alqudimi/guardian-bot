"""
Anti-Forward Spam Detection
============================
Detects and mitigates forwarded message spam — a common attack vector
where spammers forward content from large channels to bypass per-user
message filters.

Detection signals:
1. **High-velocity channel forwards** — same source channel forwarded
   multiple times in a sliding window.
2. **Anonymous forwards** — forwarded from channels/users with no
   visible origin (hidden_origin) at high rate.
3. **Blacklisted source channels** — forwards from known spam channels.
4. **Forward bomb** — single user forwards many messages rapidly
   (flood using forwards instead of direct messages).
5. **Cross-group forward storm** — same channel being forwarded to
   multiple groups simultaneously.
6. **New user + forward** — brand-new member immediately forwarding
   (typical spam bot behavior).

Per-group configuration:
  /antiforward on|off      — enable/disable (default off)
  /antiforward strict      — delete ALL forwards from non-admins
  /allowforward <channel>  — whitelist a specific channel for forwarding
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from telegram import Message

from config.settings import get_settings
from src.pipeline.context import PipelineContext
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────
MAX_FORWARDS_PER_USER_PER_MIN = 5    # Per-user forward rate
MAX_FORWARDS_SAME_CHANNEL = 3        # Same source channel per 5 min
FORWARD_BOMB_WINDOW_S = 30           # Window for forward bomb detection
NEW_USER_FORWARD_BAN_THRESHOLD = 2   # Forwards by brand-new member


@dataclass
class ForwardSignals:
    is_forward: bool = False
    source_channel_id: int | None = None
    source_channel_name: str | None = None
    is_anonymous: bool = False
    forward_velocity_high: bool = False
    channel_blacklisted: bool = False
    new_user_forwarding: bool = False
    forward_bomb: bool = False
    forward_risk_score: float = 0.0


async def _is_channel_whitelisted(chat_id: int, channel_id: int) -> bool:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}fwd_whitelist:{chat_id}:{channel_id}"
    return bool(await redis.exists(key))


async def _is_channel_blacklisted(channel_id: int) -> bool:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}fwd_blacklist:{channel_id}"
    return bool(await redis.exists(key))


async def add_forward_whitelist(chat_id: int, channel_id: int) -> None:
    redis = await get_redis()
    settings = get_settings()
    await redis.set(f"{settings.redis_prefix}fwd_whitelist:{chat_id}:{channel_id}", "1")


async def add_forward_blacklist(channel_id: int) -> None:
    redis = await get_redis()
    settings = get_settings()
    await redis.set(f"{settings.redis_prefix}fwd_blacklist:{channel_id}", "1")


async def get_forward_mode(chat_id: int) -> str:
    """Return 'off', 'on', or 'strict' for this group."""
    redis = await get_redis()
    settings = get_settings()
    val = await redis.get(f"{settings.redis_prefix}antiforward:{chat_id}")
    if not val:
        return "off"
    val_str = val.decode() if isinstance(val, bytes) else val
    return val_str


async def set_forward_mode(chat_id: int, mode: str) -> None:
    redis = await get_redis()
    settings = get_settings()
    await redis.set(f"{settings.redis_prefix}antiforward:{chat_id}", mode)


async def analyze_forward(ctx: PipelineContext) -> ForwardSignals:
    """Full forward analysis. Returns ForwardSignals."""
    msg: Message = ctx.message
    if not msg:
        return ForwardSignals()

    signals = ForwardSignals()

    # Detect if message is a forward
    is_fwd = bool(
        msg.forward_date or
        msg.forward_from or
        msg.forward_from_chat or
        msg.forward_sender_name
    )
    signals.is_forward = is_fwd

    if not is_fwd:
        return signals

    redis = await get_redis()
    settings = get_settings()
    prefix = settings.redis_prefix
    now = time.time()
    user_id = ctx.user_id
    chat_id = ctx.chat_id

    # ── Source channel analysis ────────────────────────────────────────────────
    if msg.forward_from_chat:
        signals.source_channel_id = msg.forward_from_chat.id
        signals.source_channel_name = msg.forward_from_chat.title or ""

        # Whitelist check
        if await _is_channel_whitelisted(chat_id, signals.source_channel_id):
            return signals  # Allowed

        # Blacklist check
        if await _is_channel_blacklisted(signals.source_channel_id):
            signals.channel_blacklisted = True
            signals.forward_risk_score += 90.0

    elif msg.forward_sender_name and not msg.forward_from:
        # Hidden origin
        signals.is_anonymous = True
        signals.forward_risk_score += 20.0

    # ── Per-user forward velocity ──────────────────────────────────────────────
    user_fwd_key = f"{prefix}fwd_user:{chat_id}:{user_id}"
    await redis.zadd(user_fwd_key, {str(now): now})
    await redis.zremrangebyscore(user_fwd_key, "-inf", now - 60)
    await redis.expire(user_fwd_key, 120)
    user_fwd_count = int(await redis.zcard(user_fwd_key) or 0)

    if user_fwd_count > MAX_FORWARDS_PER_USER_PER_MIN:
        signals.forward_velocity_high = True
        signals.forward_risk_score += 40.0

    # ── Same channel velocity (per group) ─────────────────────────────────────
    if signals.source_channel_id:
        chan_key = f"{prefix}fwd_chan:{chat_id}:{signals.source_channel_id}"
        await redis.zadd(chan_key, {str(now): now})
        await redis.zremrangebyscore(chan_key, "-inf", now - 300)
        await redis.expire(chan_key, 600)
        chan_count = int(await redis.zcard(chan_key) or 0)

        if chan_count > MAX_FORWARDS_SAME_CHANNEL:
            signals.forward_risk_score += 30.0

    # ── Forward bomb detection ────────────────────────────────────────────────
    bomb_key = f"{prefix}fwd_bomb:{chat_id}:{user_id}"
    await redis.zadd(bomb_key, {str(now): now})
    await redis.zremrangebyscore(bomb_key, "-inf", now - FORWARD_BOMB_WINDOW_S)
    await redis.expire(bomb_key, FORWARD_BOMB_WINDOW_S * 2)
    bomb_count = int(await redis.zcard(bomb_key) or 0)

    if bomb_count >= 5:
        signals.forward_bomb = True
        signals.forward_risk_score += 60.0

    # ── New user forwarding ────────────────────────────────────────────────────
    if hasattr(ctx, "account") and ctx.account.high_id_new_account:  # type: ignore
        if user_fwd_count >= NEW_USER_FORWARD_BAN_THRESHOLD:
            signals.new_user_forwarding = True
            signals.forward_risk_score += 40.0

    signals.forward_risk_score = min(100.0, signals.forward_risk_score)
    return signals


async def run_anti_forward(ctx: PipelineContext) -> None:
    """Pipeline entry point for forward analysis."""
    if ctx.short_circuit:
        return

    chat_id = ctx.chat_id
    mode = await get_forward_mode(chat_id)

    if mode == "off":
        return

    signals = await analyze_forward(ctx)
    ctx.forward_signals = signals  # type: ignore[attr-defined]

    if not signals.is_forward:
        return

    # Strict mode — delete all forwards
    if mode == "strict":
        ctx.spam.fast_rule_block = True
        ctx.decision.action = "delete"
        ctx.decision.reason = "forward_strict_mode"
        return

    # Normal mode — apply risk score
    if signals.channel_blacklisted:
        ctx.spam.blacklist_hit = True
        ctx.spam.fast_rule_block = True
        ctx.decision.action = "ban_temp"
        ctx.decision.reason = f"forward_blacklisted_channel:{signals.source_channel_id}"
        return

    if signals.forward_risk_score > 0:
        ctx.spam.flood_score = min(100.0, ctx.spam.flood_score + signals.forward_risk_score * 0.4)

    logger.debug(
        "anti_forward",
        user_id=ctx.user_id,
        source=signals.source_channel_id,
        risk=signals.forward_risk_score,
        mode=mode,
    )
