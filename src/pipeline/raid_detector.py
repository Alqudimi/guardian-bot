"""
Raid Detection & Lockdown Manager
-----------------------------------
Detects coordinated join floods (raids) and activates group lockdown.

Strategy:
- Sliding window counting of new member joins per group
- When threshold is exceeded, trigger lockdown mode
- Lockdown: enable slow mode, alert admins, optionally restrict new members
- Auto-unlock after a configurable cooldown period
"""
from __future__ import annotations

import time
from uuid import uuid4

from sqlalchemy import select
from telegram import Bot, ChatPermissions
from telegram.error import TelegramError

from config.settings import get_settings
from src.db.models import Group
from src.db.session import db_session
from src.management.group_settings import get_setting
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

_LOCKDOWN_DURATION_SECONDS = 300
_RAID_RESERVATION_KEY = "raid_activation"


def _standard_group_permissions() -> ChatPermissions:
    """Return the bot's documented baseline permissions for a group."""
    return ChatPermissions(
        can_send_messages=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_send_polls=True,
    )


async def _compensate_partial_lockdown(
    bot: Bot,
    chat_id: int,
    *,
    slow_mode_applied: bool,
    permissions_applied: bool,
) -> None:
    """Best-effort compensation for mutations completed before a later failure."""
    if permissions_applied:
        try:
            await bot.set_chat_permissions(
                chat_id=chat_id,
                permissions=_standard_group_permissions(),
            )
        except TelegramError as exc:
            logger.error(
                "raid_permissions_compensation_failed",
                chat_id=chat_id,
                error=type(exc).__name__,
            )
    if slow_mode_applied:
        try:
            await bot.set_chat_slow_mode_delay(chat_id=chat_id, slow_mode_delay=0)
        except TelegramError as exc:
            logger.error(
                "raid_slow_mode_compensation_failed",
                chat_id=chat_id,
                error=type(exc).__name__,
            )


async def check_raid(bot: Bot, chat_id: int, new_user_id: int) -> bool:
    """
    Called when a new member joins. Returns True only when a new lockdown is activated.

    The per-group setting is read before recording/enforcing the raid threshold. If
    the setting cannot be read, enforcement is skipped rather than overriding an
    administrator's last known choice with an unverified lockdown.
    """
    try:
        anti_raid = await get_setting(chat_id, "anti_raid")
    except Exception as exc:
        logger.warning(
            "anti_raid_setting_unavailable",
            chat_id=chat_id,
            error=type(exc).__name__,
        )
        return False
    if anti_raid != "on":
        logger.info("anti_raid_disabled", chat_id=chat_id)
        return False

    settings = get_settings()
    redis = await get_redis()
    prefix = settings.redis_prefix
    now = time.time()

    # Sliding window join counter
    join_key = f"{prefix}joins:{chat_id}"
    pipe = redis.pipeline()
    pipe.zremrangebyscore(join_key, "-inf", now - settings.raid_join_window_seconds)
    pipe.zadd(join_key, {f"{new_user_id}:{now:.6f}:{uuid4().hex}": now})
    pipe.zcard(join_key)
    pipe.expire(join_key, settings.raid_join_window_seconds * 2)
    results = await pipe.execute()
    join_count = int(results[2])

    if join_count < settings.raid_join_threshold:
        return False

    # Reserve activation atomically. The reservation is not the active marker;
    # it only prevents concurrent join updates from issuing duplicate Telegram
    # mutations while the first activation is in progress.
    lockdown_key = f"{prefix}lockdown:{chat_id}"
    reservation_key = f"{prefix}{_RAID_RESERVATION_KEY}:{chat_id}"
    if await redis.exists(lockdown_key) or await redis.exists(reservation_key):
        return False
    reserved = await redis.set(
        reservation_key,
        str(uuid4()),
        ex=_LOCKDOWN_DURATION_SECONDS,
        nx=True,
    )
    if not reserved:
        return False

    activated = await _activate_lockdown(bot, chat_id, join_count)
    if not activated:
        await redis.delete(reservation_key)
        return False

    # Publish the active marker only after the primary Telegram operations
    # have succeeded. Keep the reservation if this state commit fails so its
    # TTL continues to suppress duplicate mutations during degradation.
    try:
        state_pipe = redis.pipeline(transaction=True)
        state_pipe.setex(lockdown_key, _LOCKDOWN_DURATION_SECONDS, "1")
        state_pipe.delete(reservation_key)
        await state_pipe.execute()
    except Exception as exc:
        logger.error(
            "raid_lockdown_state_commit_failed",
            chat_id=chat_id,
            error=type(exc).__name__,
        )
        return False

    await _persist_raid_db_state(chat_id, active=True)
    return True


async def _persist_raid_db_state(chat_id: int, *, active: bool) -> bool:
    """Mirror Telegram's confirmed raid state into the optional DB record."""
    try:
        async with db_session() as session:
            result = await session.execute(select(Group).where(Group.id == chat_id))
            group = result.scalar_one_or_none()
            if group is None:
                logger.warning("raid_db_group_missing", chat_id=chat_id, active=active)
                return False
            group.raid_lockdown = active
            group.slow_mode_active = active
            return True
    except Exception as exc:
        logger.error(
            "raid_db_state_sync_failed",
            chat_id=chat_id,
            active=active,
            error=type(exc).__name__,
        )
        return False


async def _activate_lockdown(bot: Bot, chat_id: int, join_count: int) -> bool:
    settings = get_settings()
    logger.warning(
        "raid_detected",
        chat_id=chat_id,
        join_count=join_count,
        window=settings.raid_join_window_seconds,
    )
    slow_mode_applied = False
    permissions_applied = False

    try:
        # Enable slow mode
        await bot.set_chat_slow_mode_delay(chat_id=chat_id, slow_mode_delay=30)
        slow_mode_applied = True

        # Restrict new member permissions
        await bot.set_chat_permissions(
            chat_id=chat_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_send_polls=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False,
            ),
        )
        permissions_applied = True

        # Notify group
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🚨 *Raid Alert* — {join_count} new members joined in a short window.\n"
                "Group is now in *lockdown mode*. Some features are temporarily restricted.\n"
                "Admins have been notified."
            ),
            parse_mode="Markdown",
        )

        # Notify admins
        for admin_id in settings.telegram_admin_ids:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"🚨 *Raid detected* in group `{chat_id}`\n"
                        f"{join_count} joins in {settings.raid_join_window_seconds}s window.\n"
                        "Lockdown activated automatically."
                    ),
                    parse_mode="Markdown",
                )
            except TelegramError:
                pass

    except TelegramError as exc:
        logger.error("raid_lockdown_failed", chat_id=chat_id, error=type(exc).__name__)
        await _compensate_partial_lockdown(
            bot,
            chat_id,
            slow_mode_applied=slow_mode_applied,
            permissions_applied=permissions_applied,
        )
        return False

    return True


def schedule_lockdown_release(context, chat_id: int) -> bool:
    """Schedule Telegram-side lockdown cleanup after the Redis TTL expires."""
    job_queue = getattr(context, "job_queue", None)
    if job_queue is None:
        logger.warning("raid_auto_release_unavailable", chat_id=chat_id)
        return False

    job_name = f"raid-lockdown:{chat_id}"
    for job in job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()
    job_queue.run_once(
        auto_release_lockdown,
        when=_LOCKDOWN_DURATION_SECONDS,
        data=chat_id,
        name=job_name,
    )
    return True


async def auto_release_lockdown(context) -> None:
    """JobQueue callback that restores group permissions after lockdown."""
    chat_id = getattr(getattr(context, "job", None), "data", None)
    if not isinstance(chat_id, int):
        logger.error("raid_auto_release_invalid_data")
        return
    await release_lockdown(context.bot, chat_id)


async def release_lockdown(bot: Bot, chat_id: int) -> None:
    """Release Telegram lockdown before clearing Redis state."""
    settings = get_settings()
    redis = await get_redis()
    lockdown_key = f"{settings.redis_prefix}lockdown:{chat_id}"
    slow_mode_released = False
    permissions_released = False

    try:
        await bot.set_chat_slow_mode_delay(chat_id=chat_id, slow_mode_delay=0)
        slow_mode_released = True

        await bot.set_chat_permissions(
            chat_id=chat_id,
            permissions=_standard_group_permissions(),
        )
        permissions_released = True
    except TelegramError as exc:
        if slow_mode_released and not permissions_released:
            try:
                await bot.set_chat_slow_mode_delay(chat_id=chat_id, slow_mode_delay=30)
            except TelegramError as compensation_exc:
                logger.error(
                    "lockdown_release_compensation_failed",
                    chat_id=chat_id,
                    error=type(compensation_exc).__name__,
                )
        logger.error("lockdown_release_failed", chat_id=chat_id, error=type(exc).__name__)
        return

    try:
        await bot.send_message(
            chat_id=chat_id,
            text="✅ Lockdown lifted. The group is back to normal.",
        )
    except TelegramError as exc:
        logger.warning(
            "lockdown_release_notification_failed",
            chat_id=chat_id,
            error=type(exc).__name__,
        )

    await _persist_raid_db_state(chat_id, active=False)
    try:
        await redis.delete(lockdown_key)
    except Exception as exc:
        logger.error(
            "lockdown_redis_state_clear_failed",
            chat_id=chat_id,
            error=type(exc).__name__,
        )
        return

    logger.info("lockdown_released", chat_id=chat_id)
