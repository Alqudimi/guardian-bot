"""
Extended Admin Commands — v3
==============================
All management and security admin commands in one module.

Group Management:
  /setrules <text>           — Set group rules
  /rules                     — Show group rules
  /clearrules                — Clear rules
  /setwelcome <text>         — Set welcome message
  /welcome on|off            — Toggle welcome messages
  /testwelcome               — Preview welcome message
  /setmodlog <channel_id>    — Set mod-log channel
  /setlang <code>            — Set language policy
  /setcaptcha on|off         — Toggle CAPTCHA
  /setraid on|off            — Toggle per-group raid protection
  /antiforward off|on|strict — Set forward policy
  /settings                  — Show all group settings
  /resetsettings             — Reset settings to defaults
  /setmoderation level       — Set light/moderate/strict profile
  /setlimits <links> <mentions> — Set per-message limits
  /setsmart on|off           — Toggle automatic group replies
  /setsilent on|off          — Toggle silent mode
  /groupaddpattern ...       — Add per-group content rule
  /groupremovepattern <id>   — Remove per-group content rule
  /grouppatterns             — List per-group content rules

User Management:
  /userinfo <user_id>        — Full user profile
  /warns <user_id>           — View warns
  /resetwarns <user_id>      — Reset warns
  /setwarnlimit <n>          — Set max warns before ban
  /mute <user_id> [minutes]  — Manually mute a user
  /unmute <user_id>          — Unmute a user
  /ban <user_id> [days]      — Manually ban a user
  /unban <user_id>           — Unban a user
  /undo <user_id>            — Reverse the latest reversible action
  /kick <user_id>            — Kick (remove without ban)
  /tempbans                  — List active temporary bans

Reporting:
  /report [days]             — Generate moderation report (default 7 days)
  /report daily              — Today's report

Security:
  /safemode on|off           — Toggle safe mode
  /resetbreaker              — Reset circuit breaker
  /threatinfo <user_id>      — Threat intelligence profile
  /falsepositive             — Report false positive
  /status                    — Full bot status
  /groupstats                — Group statistics
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from telegram import ChatPermissions, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from src.layers.smart_warn import (
    get_warn_status,
    reset_warns,
    set_max_warns,
)
from src.management.group_settings import (
    get_all_settings,
    get_setting,
    reset_settings,
    set_setting,
)
from src.management.modlog import get_modlog_channel, log_admin_command
from src.management.reports import format_report, generate_report
from src.management.rules_manager import (
    clear_rules,
    send_rules_message,
    set_rules,
)
from src.management.user_info import format_user_report, get_user_profile
from src.management.welcome_manager import send_leave_message, send_welcome_message
from src.security.admin_authorization import is_authorized_admin
from src.security.input_sanitizer import (
    ValidationError,
    validate_duration_seconds,
    validate_user_id,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _admin_only(fn):
    """Allow only configured Telegram admins who are admins in the current group."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat or getattr(chat, "type", None) not in ("group", "supergroup"):
            if update.effective_message:
                await update.effective_message.reply_text(
                    "هذا الأمر متاح داخل المجموعات فقط | Group-only command."
                )
            return
        if not await is_authorized_admin(update, context.bot):
            if update.effective_message:
                await update.effective_message.reply_text("⛔ هذا الأمر للمشرفين فقط | Admin only.")
            return
        try:
            return await fn(update, context)
        finally:
            chat = update.effective_chat
            user = update.effective_user
            if chat and user and getattr(chat, "type", None) in ("group", "supergroup"):
                try:
                    await log_admin_command(context.bot, chat.id, user.id, fn.__name__)
                except Exception as exc:
                    logger.warning(
                        "admin_audit_failed",
                        command=fn.__name__,
                        error=type(exc).__name__,
                    )

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# ─────────────────────────────────────────────────────────────────────────────
# GROUP RULES
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_setrules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("الاستخدام | Usage: /setrules <text>")
        return
    text = " ".join(context.args)
    try:
        await set_rules(update.effective_chat.id, text)
        await update.message.reply_text("✅ تم حفظ قواعد المجموعة | Rules saved.")
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}")


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_rules_message(context.bot, update.effective_chat.id)


@_admin_only
async def cmd_clearrules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await clear_rules(update.effective_chat.id)
    await update.message.reply_text("✅ تم حذف القواعد | Rules cleared.")


# ─────────────────────────────────────────────────────────────────────────────
# WELCOME MESSAGES
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_setwelcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "الاستخدام | Usage: /setwelcome <text>\n"
            "المتغيرات | Placeholders: {name} {username} {group} {count} {rules}"
        )
        return
    text = " ".join(context.args)
    await set_setting(update.effective_chat.id, "welcome_msg", text)
    await set_setting(update.effective_chat.id, "welcome_enabled", "on")
    await update.message.reply_text("✅ تم حفظ رسالة الترحيب | Welcome message saved and enabled.")


@_admin_only
async def cmd_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if context.args:
        mode = context.args[0].lower()
        if mode in ("on", "off"):
            await set_setting(chat_id, "welcome_enabled", mode)
            state = "✅ مفعّل | Enabled" if mode == "on" else "❌ معطّل | Disabled"
            await update.message.reply_text(f"رسالة الترحيب: {state}")
            return
    enabled = await get_setting(chat_id, "welcome_enabled")
    await update.message.reply_text(f"رسالة الترحيب: {'✅ On' if enabled == 'on' else '❌ Off'}")


@_admin_only
async def cmd_setleave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "الاستخدام | Usage: /setleave <text>\n"
            "المتغيرات | Placeholders: {name} {username} {group}"
        )
        return
    text = " ".join(context.args)
    await set_setting(update.effective_chat.id, "leave_msg", text)
    await set_setting(update.effective_chat.id, "leave_enabled", "on")
    await update.message.reply_text("✅ تم حفظ رسالة المغادرة | Leave message saved and enabled.")


@_admin_only
async def cmd_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if context.args:
        mode = context.args[0].lower()
        if mode in ("on", "off"):
            await set_setting(chat_id, "leave_enabled", mode)
            state = "✅ مفعّل | Enabled" if mode == "on" else "❌ معطّل | Disabled"
            await update.message.reply_text(f"رسالة المغادرة: {state}")
            return
    enabled = await get_setting(chat_id, "leave_enabled")
    await update.message.reply_text(f"رسالة المغادرة: {'✅ On' if enabled == 'on' else '❌ Off'}")


@_admin_only
async def cmd_testleave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    await send_leave_message(
        context.bot,
        chat.id,
        user.id,
        user.first_name or "Test",
        user.username,
        chat.title or "Test Group",
    )


@_admin_only
async def cmd_testwelcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    await send_welcome_message(
        context.bot,
        chat.id,
        user.id,
        user.first_name or "Test",
        user.username,
        chat.title or "Test Group",
    )


# ─────────────────────────────────────────────────────────────────────────────
# MOD-LOG CHANNEL
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_setmodlog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        current = await get_modlog_channel(update.effective_chat.id)
        await update.message.reply_text(
            f"قناة السجلات الحالية | Current mod-log: `{current or 'None'}`\n"
            f"Usage: /setmodlog <channel_id> or /setmodlog off",
            parse_mode="Markdown",
        )
        return
    arg = context.args[0]
    if arg.lower() == "off":
        await set_setting(update.effective_chat.id, "modlog_channel", "")
        await update.message.reply_text("✅ تم إيقاف قناة السجلات | Mod-log disabled.")
        return
    try:
        channel_id = int(arg)
        await set_setting(update.effective_chat.id, "modlog_channel", str(channel_id))
        await update.message.reply_text(f"✅ تم تعيين قناة السجلات: `{channel_id}`", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ معرّف القناة غير صالح | Invalid channel ID.")


# ─────────────────────────────────────────────────────────────────────────────
# LANGUAGE POLICY
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_setlang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        policy = await get_setting(update.effective_chat.id, "lang_policy")
        await update.message.reply_text(
            f"السياسة الحالية | Current policy: `{policy}`\n"
            f"الخيارات | Options: any, ar, en, ar+en, fr, ru",
            parse_mode="Markdown",
        )
        return
    policy = context.args[0].lower()
    try:
        from src.layers.language_guard import set_group_language_policy
        await set_group_language_policy(update.effective_chat.id, policy)
        await update.message.reply_text(f"✅ سياسة اللغة | Language policy: `{policy}`", parse_mode="Markdown")
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# CAPTCHA
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_setcaptcha(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        from src.layers.captcha_gate import is_captcha_enabled
        enabled = await is_captcha_enabled(update.effective_chat.id)
        await update.message.reply_text(f"CAPTCHA: {'✅ On' if enabled else '❌ Off'}")
        return
    mode = context.args[0].lower()
    from src.layers.captcha_gate import set_captcha_enabled
    if mode == "on":
        await set_captcha_enabled(update.effective_chat.id, True)
        await update.message.reply_text("✅ تم تفعيل CAPTCHA للأعضاء الجدد.")
    elif mode == "off":
        await set_captcha_enabled(update.effective_chat.id, False)
        await update.message.reply_text("❌ تم إيقاف CAPTCHA.")


# ─────────────────────────────────────────────────────────────────────────────
# RAID PROTECTION
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_setraid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle join-flood lockdown for the current group."""
    chat_id = update.effective_chat.id
    if not context.args:
        value = await get_setting(chat_id, "anti_raid")
        await update.message.reply_text(
            f"Anti-raid protection: `{value}`\nUse: /setraid on|off",
            parse_mode="Markdown",
        )
        return

    value = context.args[0].lower()
    if value not in {"on", "off"}:
        await update.message.reply_text("❌ Use: /setraid on|off")
        return

    await set_setting(chat_id, "anti_raid", value)
    await update.message.reply_text(
        f"✅ Anti-raid protection: `{value}`",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-FORWARD
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_antiforward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.layers.anti_forward import get_forward_mode, set_forward_mode
    if not context.args:
        mode = await get_forward_mode(update.effective_chat.id)
        await update.message.reply_text(
            f"Anti-forward: `{mode}`\nOptions: off / on / strict",
            parse_mode="Markdown",
        )
        return
    mode = context.args[0].lower()
    if mode not in ("off", "on", "strict"):
        await update.message.reply_text("❌ Options: off / on / strict")
        return
    await set_forward_mode(update.effective_chat.id, mode)
    await update.message.reply_text(f"✅ Anti-forward: `{mode}`", parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
# GROUP SETTINGS OVERVIEW
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    s = await get_all_settings(chat_id)
    text = (
        f"⚙️ *إعدادات المجموعة | Group Settings*\n\n"
        f"`captcha         ` {s['captcha']}\n"
        f"`antiforward     ` {s['antiforward']}\n"
        f"`lang_policy     ` {s['lang_policy']}\n"
        f"`warn_limit      ` {s['warn_limit']}\n"
        f"`welcome         ` {s['welcome_enabled']}\n"
        f"`leave          ` {s['leave_enabled']}\n"
        f"`moderation_level` {s['moderation_level']}\n"
        f"`anti_raid       ` {s['anti_raid']}\n"
        f"`max_links       ` {s['max_links']}\n"
        f"`max_mentions    ` {s['max_mentions']}\n"
        f"`silent_mode     ` {s['silent_mode']}\n"
        f"`smart_responses ` {s['smart_responses']}\n"
        f"`modlog_channel  ` {s['modlog_channel'] or 'not set'}\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


@_admin_only
async def cmd_setmoderation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set the per-group moderation profile: light, moderate, or strict."""
    chat_id = update.effective_chat.id
    if not context.args:
        current = await get_setting(chat_id, "moderation_level")
        await update.message.reply_text(
            f"Moderation level: `{current}`\n"
            "Use: /setmoderation light|moderate|strict",
            parse_mode="Markdown",
        )
        return

    level = context.args[0].lower()
    if level not in {"light", "moderate", "strict"}:
        await update.message.reply_text("❌ Use: /setmoderation light|moderate|strict")
        return

    await set_setting(chat_id, "moderation_level", level)
    from src.intelligence.adaptive_thresholds import invalidate_group_thresholds

    await invalidate_group_thresholds(chat_id)
    await update.message.reply_text(
        f"✅ Moderation level: `{level}`", parse_mode="Markdown"
    )


@_admin_only
async def cmd_resetsettings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reset_settings(update.effective_chat.id)
    await update.message.reply_text("✅ تم إعادة ضبط الإعدادات | Settings reset to defaults.")


@_admin_only
async def cmd_setsmart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle automatic contextual replies in this group."""
    chat_id = update.effective_chat.id
    if not context.args:
        value = await get_setting(chat_id, "smart_responses")
        await update.message.reply_text(f"Smart responses: `{value}`", parse_mode="Markdown")
        return
    value = context.args[0].lower()
    if value not in {"on", "off"}:
        await update.message.reply_text("❌ Use: /setsmart on|off")
        return
    await set_setting(chat_id, "smart_responses", value)
    await update.message.reply_text(
        f"✅ Smart group responses: `{value}`", parse_mode="Markdown"
    )


@_admin_only
async def cmd_setlimits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set safe per-group link and mention limits."""
    chat_id = update.effective_chat.id
    if len(context.args or []) < 2:
        links = await get_setting(chat_id, "max_links")
        mentions = await get_setting(chat_id, "max_mentions")
        await update.message.reply_text(
            f"Limits: links=`{links}`, mentions=`{mentions}`\n"
            "Use: /setlimits <links 1-50> <mentions 1-50>",
            parse_mode="Markdown",
        )
        return

    try:
        links = int(context.args[0])
        mentions = int(context.args[1])
    except (TypeError, ValueError):
        await update.message.reply_text("❌ Limits must be integers from 1 to 50.")
        return
    if not (1 <= links <= 50 and 1 <= mentions <= 50):
        await update.message.reply_text("❌ Limits must be integers from 1 to 50.")
        return

    await set_setting(chat_id, "max_links", str(links))
    await set_setting(chat_id, "max_mentions", str(mentions))
    await update.message.reply_text(
        f"✅ Limits set: links=`{links}`, mentions=`{mentions}`",
        parse_mode="Markdown",
    )


@_admin_only
async def cmd_setsilent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        val = await get_setting(update.effective_chat.id, "silent_mode")
        await update.message.reply_text(f"Silent mode: {val}")
        return
    mode = context.args[0].lower()
    if mode not in ("on", "off"):
        await update.message.reply_text("❌ Use: /setsilent on|off")
        return
    await set_setting(update.effective_chat.id, "silent_mode", mode)
    await update.message.reply_text(f"✅ Silent mode: {mode}")


# ─────────────────────────────────────────────────────────────────────────────
# USER MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("الاستخدام | Usage: /userinfo <user_id>")
        return
    try:
        uid = validate_user_id(context.args[0])
    except ValidationError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    profile = await get_user_profile(uid, update.effective_chat.id)
    await update.message.reply_text(format_user_report(profile), parse_mode="Markdown")


@_admin_only
async def cmd_warns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /warns <user_id>")
        return
    try:
        uid = validate_user_id(context.args[0])
    except ValidationError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    status = await get_warn_status(uid, update.effective_chat.id)
    text = (
        f"⚠️ *Warns for `{uid}`*\n\n"
        f"Active: {status.active_warn_count}\n"
        f"Total: {status.total_warn_count}\n"
        f"Next action: `{status.next_action}`"
    )
    if status.history:
        text += "\n\n*Recent:*"
        for w in reversed(status.history[-3:]):
            ts = datetime.fromtimestamp(w.timestamp, tz=UTC).strftime("%m/%d %H:%M")
            text += f"\n• {ts} — {w.violation_type} (risk:{w.risk_score:.0f})"
    await update.message.reply_text(text, parse_mode="Markdown")


@_admin_only
async def cmd_resetwarns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /resetwarns <user_id>")
        return
    try:
        uid = validate_user_id(context.args[0])
    except ValidationError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    await reset_warns(uid, update.effective_chat.id)
    await update.message.reply_text(f"✅ Warns reset for `{uid}`.", parse_mode="Markdown")


@_admin_only
async def cmd_setwarnlimit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        from src.layers.smart_warn import get_max_warns
        limit = await get_max_warns(update.effective_chat.id)
        await update.message.reply_text(f"Current warn limit: {limit}")
        return
    try:
        limit = int(context.args[0])
        if not (1 <= limit <= 10):
            raise ValueError("Must be 1–10")
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    await set_max_warns(update.effective_chat.id, limit)
    await update.message.reply_text(f"✅ Warn limit set to {limit}.")


@_admin_only
async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /mute <user_id> [minutes=60]")
        return
    try:
        uid = validate_user_id(context.args[0])
        raw_minutes = context.args[1] if len(context.args) > 1 else "60"
        seconds = validate_duration_seconds(raw_minutes, max_seconds=31 * 24 * 60 * 60)
        if seconds < 60:
            raise ValidationError("Mute duration must be at least 1 minute")
        minutes = seconds // 60
    except (ValidationError, ValueError) as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    until = datetime.now(tz=UTC) + timedelta(minutes=minutes)
    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=uid,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        await update.message.reply_text(f"🔇 Muted `{uid}` for {minutes} minutes.", parse_mode="Markdown")
    except TelegramError as exc:
        logger.warning(
            "admin_telegram_operation_failed",
            error=type(exc).__name__,
        )
        await update.message.reply_text("❌ تعذر تنفيذ العملية عبر Telegram حالياً.")


@_admin_only
async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /unmute <user_id>")
        return
    try:
        uid = validate_user_id(context.args[0])
    except ValidationError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=uid,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_polls=True,
                can_send_other_messages=True,
            ),
        )
        await update.message.reply_text(f"✅ Unmuted `{uid}`.", parse_mode="Markdown")
    except TelegramError as exc:
        logger.warning(
            "admin_telegram_operation_failed",
            error=type(exc).__name__,
        )
        await update.message.reply_text("❌ تعذر تنفيذ العملية عبر Telegram حالياً.")


@_admin_only
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /ban <user_id> [days=0=permanent]")
        return
    try:
        uid = validate_user_id(context.args[0])
        raw_days = context.args[1] if len(context.args) > 1 else "0"
        seconds = validate_duration_seconds(raw_days, max_seconds=366 * 24 * 60 * 60)
        days = seconds // (24 * 60 * 60)
        if seconds and days == 0:
            raise ValidationError("Ban duration must be at least 1 day")
    except (ValidationError, ValueError) as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    until = None
    if days > 0:
        until = datetime.now(tz=UTC) + timedelta(days=days)
    try:
        await context.bot.ban_chat_member(
            chat_id=update.effective_chat.id,
            user_id=uid,
            until_date=until,
        )
        label = f"{days}d" if days > 0 else "permanent"
        await update.message.reply_text(f"⛔ Banned `{uid}` ({label}).", parse_mode="Markdown")
    except TelegramError as exc:
        logger.warning(
            "admin_telegram_operation_failed",
            error=type(exc).__name__,
        )
        await update.message.reply_text("❌ تعذر تنفيذ العملية عبر Telegram حالياً.")


@_admin_only
async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    try:
        uid = validate_user_id(context.args[0])
    except ValidationError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    try:
        await context.bot.unban_chat_member(
            chat_id=update.effective_chat.id,
            user_id=uid,
        )
        await update.message.reply_text(f"✅ Unbanned `{uid}`.", parse_mode="Markdown")
    except TelegramError as exc:
        logger.warning(
            "admin_telegram_operation_failed",
            error=type(exc).__name__,
        )
        await update.message.reply_text("❌ تعذر تنفيذ العملية عبر Telegram حالياً.")


@_admin_only
async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reverse the latest recorded mute/ban for a user in this group."""
    if not context.args:
        await update.message.reply_text("Usage: /undo <user_id>")
        return
    try:
        uid = validate_user_id(context.args[0])
    except ValidationError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return

    from sqlalchemy import select

    from src.db.models import ActionType, ModerationEvent
    from src.db.session import db_session

    reversible = (ActionType.MUTE_TEMP, ActionType.BAN_TEMP, ActionType.BAN_PERM)
    async with db_session() as session:
        result = await session.execute(
            select(ModerationEvent)
            .where(
                ModerationEvent.group_id == update.effective_chat.id,
                ModerationEvent.user_id == uid,
                ModerationEvent.action_taken.in_(reversible),
            )
            .order_by(ModerationEvent.created_at.desc(), ModerationEvent.id.desc())
            .limit(1)
        )
        event = result.scalar_one_or_none()

    if event is None:
        await update.message.reply_text("لا توجد عقوبة قابلة للتراجع لهذا المستخدم.")
        return

    action = event.action_taken
    action_value = action.value if hasattr(action, "value") else str(action)
    try:
        if action_value in {ActionType.BAN_TEMP.value, ActionType.BAN_PERM.value}:
            await context.bot.unban_chat_member(
                chat_id=update.effective_chat.id,
                user_id=uid,
                only_if_banned=True,
            )
        else:
            await context.bot.restrict_chat_member(
                chat_id=update.effective_chat.id,
                user_id=uid,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                ),
            )
    except TelegramError as exc:
        logger.warning("admin_undo_failed", error=type(exc).__name__)
        await update.message.reply_text("❌ تعذر التراجع عن العقوبة عبر Telegram حالياً.")
        return

    from src.intelligence.adaptive_thresholds import record_false_positive

    await record_false_positive(update.effective_chat.id)
    await update.message.reply_text(
        f"✅ تم التراجع عن آخر عقوبة للمستخدم `{uid}`.", parse_mode="Markdown"
    )


@_admin_only
async def cmd_kick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /kick <user_id>")
        return
    try:
        uid = validate_user_id(context.args[0])
    except ValidationError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    try:
        await context.bot.ban_chat_member(chat_id=update.effective_chat.id, user_id=uid)
        await asyncio.sleep(0.5)
        await context.bot.unban_chat_member(chat_id=update.effective_chat.id, user_id=uid)
        await update.message.reply_text(f"👢 Kicked `{uid}`.", parse_mode="Markdown")
    except TelegramError as exc:
        logger.warning(
            "admin_telegram_operation_failed",
            error=type(exc).__name__,
        )
        await update.message.reply_text("❌ تعذر تنفيذ العملية عبر Telegram حالياً.")


# ─────────────────────────────────────────────────────────────────────────────
# REPORTING
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_tempbans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from config.settings import get_settings as _gs
    from src.utils.redis_client import get_redis
    redis = await get_redis()
    settings = _gs()
    bans_key = f"{settings.redis_prefix}bans_hourly"
    import time as _time
    now = _time.time()
    await redis.zremrangebyscore(bans_key, "-inf", now - 3600)
    entries = await redis.zrange(bans_key, 0, -1)
    if not entries:
        await update.message.reply_text("No active temporary bans in the last hour.")
        return
    lines = ["*Active Temp Bans (last 1h):*"]
    for entry in entries[-10:]:  # Show up to 10
        parts = entry.split(":")
        if len(parts) >= 2:
            lines.append(f"  • chat `{parts[0]}` / user `{parts[1]}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
# DYNAMIC BLACKLIST PATTERNS
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_addpattern(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /addpattern <type> <category> <pattern>
    type: regex | literal
    category: spam | scam | adult | phishing | other
    Example: /addpattern regex spam free.*crypto.*airdrop
    """
    if len(context.args) < 3:
        await update.message.reply_text(
            "الاستخدام | Usage:\n"
            "`/addpattern <type> <category> <pattern>`\n\n"
            "type: `regex` | `literal`\n"
            "category: `spam` | `scam` | `adult` | `phishing` | `other`\n\n"
            "Example: `/addpattern regex spam free.*crypto`",
            parse_mode="Markdown",
        )
        return

    pattern_type = context.args[0].lower()
    category = context.args[1].lower()
    pattern = " ".join(context.args[2:])
    if len(pattern) > 512:
        await update.message.reply_text("❌ Pattern is too long; maximum length is 512 characters.")
        return

    if pattern_type not in ("regex", "literal"):
        await update.message.reply_text("❌ type must be `regex` or `literal`", parse_mode="Markdown")
        return

    if category not in ("spam", "scam", "adult", "phishing", "other"):
        await update.message.reply_text(
            "❌ category must be one of: `spam` scam adult phishing other",
            parse_mode="Markdown",
        )
        return

    # Validate regex compiles before saving. The runtime uses `regex` with a timeout.
    if pattern_type == "regex":
        import regex as _re2
        try:
            _re2.compile(pattern, _re2.IGNORECASE | _re2.UNICODE)
        except _re2.error:
            await update.message.reply_text("❌ Invalid regular expression.")
            return

    try:
        from src.db.models import BlacklistedPattern as _BP
        from src.db.session import db_session as _dbs
        async with _dbs() as session:
            row = _BP(
                pattern=pattern,
                pattern_type=pattern_type,
                category=category,
                is_active=True,
            )
            session.add(row)
        # Invalidate cache so the new pattern is picked up immediately
        from src.layers.fast_rules import invalidate_db_pattern_cache
        await invalidate_db_pattern_cache()
        await update.message.reply_text(
            f"✅ Pattern added and cache refreshed.\n"
            f"Type: `{pattern_type}` | Category: `{category}`\n"
            f"Pattern: `{pattern[:100]}`",
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.exception("blacklist_pattern_create_failed", error=type(exc).__name__)
        await update.message.reply_text("❌ Database operation failed. Check bot logs.")


@_admin_only
async def cmd_removepattern(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /removepattern <id>
    Deactivates a pattern by its DB ID (get IDs from /listpatterns).
    """
    if not context.args:
        await update.message.reply_text("Usage: /removepattern <id>")
        return
    try:
        pattern_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID must be a number.")
        return

    try:
        from sqlalchemy import select as _sel

        from src.db.models import BlacklistedPattern as _BP
        from src.db.session import db_session as _dbs
        async with _dbs() as session:
            result = await session.execute(
                _sel(_BP).where(_BP.id == pattern_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                await update.message.reply_text(f"❌ Pattern ID `{pattern_id}` not found.", parse_mode="Markdown")
                return
            row.is_active = False
        from src.layers.fast_rules import invalidate_db_pattern_cache
        await invalidate_db_pattern_cache()
        await update.message.reply_text(
            f"✅ Pattern `{pattern_id}` deactivated and cache refreshed.",
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.exception("blacklist_pattern_update_failed", error=type(exc).__name__)
        await update.message.reply_text("❌ Database operation failed. Check bot logs.")


@_admin_only
async def cmd_listpatterns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /listpatterns — List all active blacklisted patterns.
    """
    try:
        from sqlalchemy import select as _sel

        from src.db.models import BlacklistedPattern as _BP
        from src.db.session import db_session as _dbs
        async with _dbs() as session:
            result = await session.execute(
                _sel(_BP).where(_BP.is_active == True).order_by(_BP.id)
            )
            rows = result.scalars().all()
    except Exception as exc:
        logger.exception("blacklist_pattern_list_failed", error=type(exc).__name__)
        await update.message.reply_text("❌ Database operation failed. Check bot logs.")
        return

    if not rows:
        await update.message.reply_text("📋 No active blacklisted patterns.")
        return

    lines = ["📋 *Active Blacklisted Patterns:*\n"]
    for row in rows[:25]:  # Cap at 25 to avoid Telegram message limit
        pat_preview = row.pattern[:50] + ("…" if len(row.pattern) > 50 else "")
        lines.append(
            f"`[{row.id}]` `{row.pattern_type}/{row.category}` — `{pat_preview}`"
        )
    if len(rows) > 25:
        lines.append(f"\n_…and {len(rows) - 25} more_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
# REPORTING
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    days = 7
    if context.args:
        arg = context.args[0].lower()
        if arg == "daily":
            days = 1
        else:
            try:
                days = max(1, min(30, int(arg)))
            except ValueError:
                pass

    report = await generate_report(update.effective_chat.id, days)
    text = format_report(report, days)
    await update.message.reply_text(text, parse_mode="Markdown")


@_admin_only
async def cmd_groupaddpattern(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a per-group content pattern without changing global patterns."""
    if len(context.args or []) < 3:
        await update.message.reply_text(
            "Usage: /groupaddpattern <regex|literal> <category> <pattern>\n"
            "Categories: spam, scam, adult, phishing, abuse, other"
        )
        return

    from src.management.group_patterns import add_group_pattern

    try:
        item = await add_group_pattern(
            update.effective_chat.id,
            context.args[0].lower(),
            context.args[1].lower(),
            " ".join(context.args[2:]),
        )
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    except Exception:
        logger.exception("group_pattern_add_failed", chat_id=update.effective_chat.id)
        await update.message.reply_text("❌ تعذر حفظ قاعدة المجموعة حالياً.")
        return

    await update.message.reply_text(
        f"✅ Group pattern added: `{item.pattern_id}`", parse_mode="Markdown"
    )


@_admin_only
async def cmd_groupremovepattern(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /groupremovepattern <pattern_id>")
        return

    from src.management.group_patterns import remove_group_pattern

    removed = await remove_group_pattern(update.effective_chat.id, context.args[0])
    await update.message.reply_text(
        "✅ Group pattern removed." if removed else "❌ Pattern not found."
    )


@_admin_only
async def cmd_grouppatterns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.management.group_patterns import list_group_patterns

    patterns = await list_group_patterns(update.effective_chat.id)
    if not patterns:
        await update.message.reply_text("لا توجد قواعد محتوى خاصة بهذه المجموعة.")
        return

    lines = ["*Group content patterns:*"]
    for item in patterns[:50]:
        safe_pattern = item.pattern.replace("`", "'")[:80]
        lines.append(f"`{item.pattern_id}` · {item.category}/{item.pattern_type} · `{safe_pattern}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
