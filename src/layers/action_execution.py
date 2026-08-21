"""
Action Execution Layer  (v2 — with Circuit Breaker + Human Behavior)
=====================================================================
Enforces moderation decisions against Telegram's API.

Anti-ban safety stack (layered, in order):
  1. API Sentinel safe-mode check  — full stop if Telegram is fighting back
  2. Circuit Breaker               — stop on repeated API errors
  3. Global action rate limiter    — token bucket (Redis)
  4. Per-user cooldown             — min gap between actions on same user
  5. Hourly ban cap                — max N bans / hour
  6. Human behavior delay          — log-normal distribution, reaction time
  7. Random jitter                 — additional micro-delay
  8. Delete budget                  — atomic per-minute delete cap
"""
from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from telegram import Bot, ChatPermissions
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

from config.settings import get_settings
from src.db.models import ActionType
from src.pipeline.context import PipelineContext
from src.security.api_sentinel import (
    is_safe_mode,
    record_action_result,
    record_flood_wait,
    record_forbidden,
)
from src.security.circuit_breaker import can_act, record_failure, record_success
from src.security.human_behavior import (
    compute_action_delay,
    get_random_warning_text,
    simulate_typing,
)
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

_DELETE_ACTIONS = frozenset(
    {
        ActionType.DELETE,
        ActionType.WARN,
        ActionType.MUTE_TEMP,
        ActionType.BAN_TEMP,
        ActionType.BAN_PERM,
    }
)

_DELETE_SLOT_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
if tonumber(redis.call('ZCARD', key)) >= limit then
    return 0
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window * 2)
return 1
"""


async def _check_rate_limit(redis, key: str, limit: int, window: int) -> bool:
    now = time.time()
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, "-inf", now - window)
    pipe.zadd(key, {f"{now:.6f}:{uuid4().hex}": now})
    pipe.zcard(key)
    pipe.expire(key, window * 2)
    results = await pipe.execute()
    return int(results[2]) <= limit


async def _reserve_delete_slot(redis, chat_id: int, message_id: int) -> bool:
    """Atomically reserve one delete budget slot for the current minute."""
    settings = get_settings()
    limit = settings.delete_rate_per_minute
    if limit <= 0:
        return False

    key = f"{settings.redis_prefix}deletes_minute"
    now = time.time()
    member = f"{chat_id}:{message_id}:{now:.6f}:{uuid4().hex}"
    result = await redis.eval(
        _DELETE_SLOT_SCRIPT,
        1,
        key,
        now,
        60,
        limit,
        member,
    )
    return int(result) == 1


async def _can_execute_action(redis, user_id: int, chat_id: int) -> tuple[bool, str]:
    settings = get_settings()
    prefix = settings.redis_prefix
    now = time.time()

    # 1. Global action rate limit
    global_key = f"{prefix}act_global"
    if not await _check_rate_limit(redis, global_key, settings.action_rate_limit_per_minute, 60):
        return False, "global_rate_limit"

    # 2. Atomic per-user cooldown reservation.
    # Reserving before the API call closes the concurrent-update race; failed
    # calls still retain a short cooldown to avoid immediate retry storms.
    user_key = f"{prefix}act_user:{chat_id}:{user_id}"
    reserved = await redis.set(
        user_key,
        str(now),
        ex=settings.action_cooldown_per_user_seconds,
        nx=True,
    )
    if not reserved:
        return False, "per_user_cooldown"

    return True, ""


async def _record_action_taken(redis, user_id: int, chat_id: int, action: str) -> None:
    settings = get_settings()
    prefix = settings.redis_prefix
    now = time.time()

    user_key = f"{prefix}act_user:{chat_id}:{user_id}"
    await redis.setex(user_key, settings.action_cooldown_per_user_seconds * 2, str(now))

    if action in (ActionType.BAN_TEMP, ActionType.BAN_PERM):
        bans_key = f"{prefix}bans_hourly"
        await redis.zadd(bans_key, {f"{chat_id}:{user_id}:{now}": now})
        await redis.expire(bans_key, 3600)


async def _hourly_ban_limit_reached(redis) -> bool:
    settings = get_settings()
    prefix = settings.redis_prefix
    bans_key = f"{prefix}bans_hourly"
    now = time.time()
    await redis.zremrangebyscore(bans_key, "-inf", now - 3600)
    count = await redis.zcard(bans_key)
    return int(count) >= settings.ban_hourly_limit


async def execute_action(ctx: PipelineContext, bot: Bot) -> None:
    action = ctx.decision.action
    user_id = ctx.user_id
    chat_id = ctx.chat_id
    message_id = ctx.message_id
    redis = await get_redis()

    if action == ActionType.ALLOW:
        ctx.execution_status = "not_required"
        return

    if action == ActionType.SILENT_LOG:
        ctx.execution_status = "logged_only"
        logger.info(
            "silent_log",
            user_id=user_id,
            chat_id=chat_id,
            risk=ctx.risk.total,
            explanation=ctx.risk.explanation,
        )
        return

    ctx.execution_status = "in_progress"

    # ── Layer 1: API Sentinel safe-mode ───────────────────────────────────────
    if await is_safe_mode():
        logger.warning(
            "action_suppressed_safe_mode",
            user_id=user_id,
            chat_id=chat_id,
            action=action,
        )
        ctx.execution_status = "suppressed_safe_mode"
        return

    # ── Layer 2: Circuit Breaker ──────────────────────────────────────────────
    cb_allowed, cb_reason = await can_act()
    if not cb_allowed:
        logger.warning(
            "action_suppressed_circuit_breaker",
            user_id=user_id,
            chat_id=chat_id,
            action=action,
            reason=cb_reason,
        )
        try:
            from src.management.reports import record_circuit_suppression

            await record_circuit_suppression(chat_id)
        except Exception as exc:
            logger.warning(
                "circuit_suppression_stat_failed",
                chat_id=chat_id,
                error=type(exc).__name__,
            )
        ctx.execution_status = "suppressed_circuit_breaker"
        return

    # ── Layer 3 & 4: Global rate + per-user cooldown ──────────────────────────
    allowed, reason = await _can_execute_action(redis, user_id, chat_id)
    if not allowed:
        logger.debug(
            "action_rate_limited",
            user_id=user_id,
            chat_id=chat_id,
            reason=reason,
        )
        ctx.execution_status = f"suppressed_{reason}"
        return

    # ── Layer 5: Hourly ban cap ────────────────────────────────────────────────
    if action in (ActionType.BAN_TEMP, ActionType.BAN_PERM) and await _hourly_ban_limit_reached(redis):
        logger.error("hourly_ban_cap_reached", chat_id=chat_id)
        action = ActionType.MUTE_TEMP
        ctx.decision.action = action
        ctx.decision.mute_duration_seconds = ctx.decision.mute_duration_seconds or 3600

    # ── Delete budget ─────────────────────────────────────────────────────────
    if action in _DELETE_ACTIONS and not await _reserve_delete_slot(redis, chat_id, message_id):
        logger.warning(
            "delete_rate_limited",
            user_id=user_id,
            chat_id=chat_id,
            action=action,
        )
        ctx.execution_status = "suppressed_delete_budget"
        return

    # ── Pacing delay (never changes the selected security action) ─────────────
    delay = await compute_action_delay(action, ctx.risk.total)
    await asyncio.sleep(delay)

    # ── Execute ────────────────────────────────────────────────────────────────
    try:
        match action:
            case ActionType.DELETE:
                await _delete_message(bot, chat_id, message_id)

            case ActionType.WARN:
                await _delete_message(bot, chat_id, message_id)
                await _send_warning(bot, chat_id, user_id, ctx.behavior.warn_count + 1)

            case ActionType.MUTE_TEMP:
                await _delete_message(bot, chat_id, message_id)
                await _mute_user(bot, chat_id, user_id, ctx.decision.mute_duration_seconds)

            case ActionType.BAN_TEMP:
                await _delete_message(bot, chat_id, message_id)
                await _ban_user(bot, chat_id, user_id, ctx.decision.ban_duration_seconds)

            case ActionType.BAN_PERM:
                await _delete_message(bot, chat_id, message_id)
                await _ban_user(bot, chat_id, user_id, 0)

            case ActionType.SLOW_MODE:
                await _apply_slow_mode(bot, chat_id, ctx.decision.mute_duration_seconds or 30)

            case ActionType.MEDIA_RESTRICT:
                await _restrict_media(bot, chat_id, user_id, ctx.decision.mute_duration_seconds)

            case ActionType.LINK_RESTRICT:
                await _restrict_links(bot, chat_id, user_id, ctx.decision.mute_duration_seconds)

            case ActionType.ESCALATE:
                delivered = await _escalate_to_admins(bot, ctx)
                if not delivered:
                    raise TelegramError("escalation_delivery_failed")

            case ActionType.RAID_LOCKDOWN:
                await _activate_raid_lockdown(bot, chat_id)

            case _:
                raise TelegramError(f"unsupported_action:{action}")

        await _record_action_taken(redis, user_id, chat_id, action)
        ctx.execution_status = "succeeded"
        from src.security.human_behavior import record_action_completed
        await record_action_completed()
        await record_success()
        await record_action_result(True, action)

        # Report to cross-group intelligence after successful ban
        if action in (ActionType.BAN_TEMP, ActionType.BAN_PERM):
            from src.intelligence.cross_group_intel import report_user_incident
            from src.layers.audit_logging import _infer_violation_category
            violation = _infer_violation_category(ctx)
            await report_user_incident(user_id, chat_id, violation, action)

        if ctx.decision.notify_admin:
            await _notify_admins(bot, ctx, action)

    except RetryAfter as exc:
        ctx.execution_status = "failed"
        ctx.execution_error = type(exc).__name__
        await record_flood_wait(int(exc.retry_after), action)
        await record_failure(f"retry_after_{action}")
        await record_action_result(False, action)
        logger.warning(
            "telegram_retry_after",
            user_id=user_id,
            retry_after=exc.retry_after,
            action=action,
        )

    except Forbidden:
        ctx.execution_status = "failed"
        ctx.execution_error = "Forbidden"
        await record_forbidden(chat_id, user_id)
        await record_failure(f"forbidden_{action}")
        await record_action_result(False, action)
        logger.warning(
            "action_forbidden",
            user_id=user_id,
            chat_id=chat_id,
            action=action,
        )

    except BadRequest as exc:
        ctx.execution_status = "failed"
        ctx.execution_error = type(exc).__name__
        err = str(exc).lower()
        if "message to delete not found" in err or "chat not found" in err:
            pass  # Idempotent — already gone
        else:
            await record_failure(f"bad_request_{action}")
            await record_action_result(False, action)
        logger.warning(
            "action_bad_request",
            user_id=user_id,
            chat_id=chat_id,
            action=action,
            error=str(exc),
        )

    except TelegramError as exc:
        ctx.execution_status = "failed"
        ctx.execution_error = type(exc).__name__
        await record_failure(f"telegram_error_{action}")
        await record_action_result(False, action)
        logger.error(
            "action_telegram_error",
            user_id=user_id,
            chat_id=chat_id,
            action=action,
            error=str(exc),
        )


async def _delete_message(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info("message_deleted", chat_id=chat_id, message_id=message_id)
    except BadRequest as exc:
        if "message to delete not found" not in str(exc).lower():
            raise


async def _mute_user(bot: Bot, chat_id: int, user_id: int, duration_seconds: int) -> None:
    until = datetime.now(tz=UTC) + timedelta(seconds=duration_seconds)
    await bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
        ),
        until_date=until,
    )
    logger.info("user_muted", user_id=user_id, chat_id=chat_id, duration=duration_seconds)


async def _ban_user(bot: Bot, chat_id: int, user_id: int, duration_seconds: int) -> None:
    until: datetime | None = None
    if duration_seconds > 0:
        until = datetime.now(tz=UTC) + timedelta(seconds=duration_seconds)
    await bot.ban_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        until_date=until,
        revoke_messages=True,
    )
    logger.info(
        "user_banned",
        user_id=user_id,
        chat_id=chat_id,
        permanent=(duration_seconds == 0),
        duration=duration_seconds,
    )


async def _send_warning(bot: Bot, chat_id: int, user_id: int, warn_number: int) -> None:
    await simulate_typing(bot, chat_id)
    text = get_random_warning_text(warn_number)
    try:
        msg = await bot.send_message(chat_id=chat_id, text=text)
        await asyncio.sleep(30)
        await _delete_message(bot, chat_id, msg.message_id)
    except TelegramError as exc:
        logger.warning("warning_send_failed", user_id=user_id, error=str(exc))


async def _escalate_to_admins(bot: Bot, ctx: PipelineContext) -> bool:
    settings = get_settings()
    if not settings.telegram_admin_ids:
        logger.warning("escalation_skipped_no_admin_recipients", chat_id=ctx.chat_id)
        return False
    delivered = 0
    text = (
        f"🚨 *Escalation Alert*\n"
        f"Group: `{ctx.chat_id}`\n"
        f"User: `{ctx.user_id}` (@{ctx.user.username or 'N/A'})\n"
        f"Risk: `{ctx.risk.total:.1f}/100`\n"
        f"Signals: `{ctx.risk.explanation[:200]}`"
    )
    for admin_id in settings.telegram_admin_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=text, parse_mode="Markdown")
            delivered += 1
        except TelegramError as exc:
            logger.warning(
                "escalation_delivery_failed",
                admin_id=admin_id,
                error=type(exc).__name__,
            )
    return delivered > 0


async def _notify_admins(bot: Bot, ctx: PipelineContext, action: str) -> None:
    settings = get_settings()
    if not settings.telegram_admin_ids:
        return
    text = (
        f"🛡 *Moderation Action*\n"
        f"Group: `{ctx.chat_id}`\n"
        f"User: `{ctx.user_id}` (@{ctx.user.username or 'N/A'})\n"
        f"Action: `{action}`\n"
        f"Risk: `{ctx.risk.total:.1f}/100`\n"
        f"Reason: {ctx.decision.reason[:200]}"
    )
    for admin_id in settings.telegram_admin_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=text, parse_mode="Markdown")
        except TelegramError:
            pass


async def _apply_slow_mode(bot: Bot, chat_id: int, delay_seconds: int) -> None:
    """Enable Telegram slow mode for the entire group chat."""
    # Telegram accepts 0, 10, 30, 60, 300, 900, 3600 seconds.
    # Round to nearest valid value.
    _VALID_DELAYS = (0, 10, 30, 60, 300, 900, 3600)
    closest = min(_VALID_DELAYS, key=lambda x: abs(x - delay_seconds))
    await bot.set_chat_slow_mode_delay(chat_id=chat_id, slow_mode_delay=closest)
    logger.info("slow_mode_applied", chat_id=chat_id, delay=closest)


async def _restrict_media(
    bot: Bot, chat_id: int, user_id: int, duration_seconds: int
) -> None:
    """Restrict a user from sending media (photos, videos, documents, stickers)."""
    until: datetime | None = None
    if duration_seconds and duration_seconds > 0:
        until = datetime.now(tz=UTC) + timedelta(seconds=duration_seconds)
    await bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=ChatPermissions(
            can_send_messages=True,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,   # disables stickers/gifs/inline
            can_add_web_page_previews=False,
        ),
        until_date=until,
    )
    logger.info(
        "media_restricted",
        user_id=user_id,
        chat_id=chat_id,
        duration=duration_seconds,
    )


async def _restrict_links(
    bot: Bot, chat_id: int, user_id: int, duration_seconds: int
) -> None:
    """Restrict a user from sending links (web page previews and inline bots)."""
    until: datetime | None = None
    if duration_seconds and duration_seconds > 0:
        until = datetime.now(tz=UTC) + timedelta(seconds=duration_seconds)
    await bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=False,  # disables link previews
        ),
        until_date=until,
    )
    logger.info(
        "link_restricted",
        user_id=user_id,
        chat_id=chat_id,
        duration=duration_seconds,
    )


async def _activate_raid_lockdown(bot: Bot, chat_id: int) -> None:
    # The Telegram mutation is the primary operation and must propagate errors;
    # execute_action must not record a failed lockdown as a successful action.
    await bot.set_chat_slow_mode_delay(chat_id=chat_id, slow_mode_delay=30)
    try:
        from src.intelligence.adaptive_thresholds import record_raid

        await record_raid(chat_id)
    except Exception as exc:
        logger.warning("raid_lockdown_metric_failed", chat_id=chat_id, error=type(exc).__name__)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text="🔒 *Raid protection activated.* Group is in slow mode.",
            parse_mode="Markdown",
        )
    except TelegramError as exc:
        logger.warning("raid_lockdown_notice_failed", chat_id=chat_id, error=type(exc).__name__)
    logger.warning("raid_lockdown_activated", chat_id=chat_id)
