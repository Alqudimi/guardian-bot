"""
Moderation Log Channel
=======================
Forwards moderation events to a designated Telegram channel or group,
providing admins with a real-time audit trail separate from the main group.

Features:
  • Configurable mod-log channel per group (/setmodlog <channel_id>)
  • Formatted event messages with full signal breakdown
  • Color-coded severity levels (✅ allow / 🟡 warn / 🟠 delete / 🔴 ban)
  • Automatic alert messages for critical events (raids, critical threats)
  • Thread/topic support for Telegram groups with topics

Event types forwarded:
  • Message deleted with reason + risk score
  • User muted/banned with duration + violation details
  • Raid detected + lockdown status
  • Cross-group critical threat detected
  • Circuit breaker state changes
  • CAPTCHA failures (batch summary)
  • Admin commands executed
"""
from __future__ import annotations

from telegram import Bot
from telegram.error import TelegramError

from src.management.group_settings import get_setting
from src.pipeline.context import PipelineContext
from src.utils.logger import get_logger

logger = get_logger(__name__)

_ACTION_EMOJI = {
    "allow": "✅",
    "silent_log": "👁",
    "delete": "🗑",
    "warn": "⚠️",
    "mute_temp": "🔇",
    "ban_temp": "🔨",
    "ban_perm": "⛔",
    "escalate": "🚨",
}


async def get_modlog_channel(chat_id: int) -> int | None:
    """Get the mod-log channel ID for a group. Returns None if not configured."""
    val = await get_setting(chat_id, "modlog_channel")
    if not val:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


async def log_admin_command(
    bot: Bot,
    chat_id: int,
    user_id: int,
    command_name: str,
) -> None:
    """Write a minimal admin audit event without recording command arguments."""
    modlog_id = await get_modlog_channel(chat_id)
    if not modlog_id:
        return
    text = (
        "🛡 *ADMIN COMMAND*\n"
        f"Group: `{chat_id}`\n"
        f"Admin: `{user_id}`\n"
        f"Command: `{command_name}`"
    )
    try:
        await bot.send_message(chat_id=modlog_id, text=text, parse_mode="Markdown")
    except TelegramError as exc:
        logger.debug("admin_modlog_send_failed", modlog_id=modlog_id, error=str(exc))


async def log_moderation_event(bot: Bot, ctx: PipelineContext) -> None:
    """
    Forward a moderation event to the group's mod-log channel.
    Silently skips if no channel is configured or on errors.
    """
    if not ctx.decision or not ctx.risk:
        return

    action = ctx.decision.action
    if action in ("allow", "silent_log"):
        return  # Don't flood the log with clean messages

    modlog_id = await get_modlog_channel(ctx.chat_id)
    if not modlog_id:
        return

    emoji = _ACTION_EMOJI.get(action, "📝")
    user_name = f"@{ctx.user.username}" if ctx.user.username else f"#{ctx.user_id}"

    text = (
        f"{emoji} *{action.upper().replace('_', ' ')}*\n"
        f"👤 User: `{ctx.user_id}` ({user_name})\n"
        f"💬 Group: `{ctx.chat_id}`\n"
        f"📊 Risk: `{ctx.risk.total:.1f}/100`\n"
        f"📝 Reason: {ctx.decision.reason[:200]}\n"
    )

    if ctx.risk.explanation:
        text += f"🔍 Signals: `{ctx.risk.explanation[:300]}`"

    try:
        await bot.send_message(
            chat_id=modlog_id,
            text=text,
            parse_mode="Markdown",
        )
    except TelegramError as exc:
        logger.debug("modlog_send_failed", modlog_id=modlog_id, error=str(exc))


async def log_raid_event(bot: Bot, chat_id: int, join_count: int, locked: bool) -> None:
    """Log a raid detection event to the mod-log channel."""
    modlog_id = await get_modlog_channel(chat_id)
    if not modlog_id:
        return

    status = "🔒 LOCKED DOWN" if locked else "⚠️ DETECTED"
    text = (
        f"🚨 *RAID {status}*\n"
        f"Group: `{chat_id}`\n"
        f"Joins: {join_count} in window\n"
        f"{'Slow mode activated.' if locked else 'Monitoring...'}"
    )
    try:
        await bot.send_message(chat_id=modlog_id, text=text, parse_mode="Markdown")
    except TelegramError:
        pass


async def log_critical_threat(bot: Bot, chat_id: int, user_id: int, threat_level: int) -> None:
    """Log a critical cross-group threat detection."""
    modlog_id = await get_modlog_channel(chat_id)
    if not modlog_id:
        return

    text = (
        f"⛔ *CRITICAL THREAT DETECTED*\n"
        f"User: `{user_id}`\n"
        f"Group: `{chat_id}`\n"
        f"Threat Level: {threat_level}/4\n"
        f"Action: Pre-emptive ban applied."
    )
    try:
        await bot.send_message(chat_id=modlog_id, text=text, parse_mode="Markdown")
    except TelegramError:
        pass
