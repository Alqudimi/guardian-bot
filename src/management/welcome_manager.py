"""
Welcome Manager — Custom Welcome Messages
==========================================
Manages customizable welcome messages for new group members.

Features:
  • Per-group custom welcome message with placeholders
  • Auto-deletion of welcome messages after configurable timeout (default 5 min)
  • Optional inline button ("Rules" / "Support")
  • Optional: show rules inline with welcome
  • Mention the new user in the welcome message
  • Support for images/GIFs in welcome messages (via stored file_id)

Placeholders in welcome message text:
  {name}        — User's first name
  {username}    — @username or first name if no username
  {group}       — Group title
  {count}       — Member number (approximate)
  {rules}       — Inline rules text (if /rules is set)

Commands:
  /setwelcome <text>      — Set welcome message (admin)
  /welcome off            — Disable welcome messages
  /welcome on             — Enable welcome messages
  /testwelcome            — Preview the welcome message
"""
from __future__ import annotations

import asyncio

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from src.management.group_settings import get_setting
from src.management.rules_manager import get_rules
from src.utils.background_tasks import create_background_task
from src.utils.logger import get_logger

logger = get_logger(__name__)

WELCOME_AUTO_DELETE_S = 300   # Auto-delete welcome after 5 min


def _format_welcome(
    template: str,
    *,
    name: str,
    username: str,
    group: str,
    count: str = "—",
    rules: str = "",
) -> str:
    """Fill every documented placeholder without leaving user-facing tokens."""
    return (
        template
        .replace("{name}", name)
        .replace("{username}", username)
        .replace("{group}", group)
        .replace("{count}", count)
        .replace("{rules}", rules or "لا توجد قواعد محددة حالياً")
    )


async def send_welcome_message(
    bot: Bot,
    chat_id: int,
    user_id: int,
    first_name: str,
    username: str | None,
    group_title: str,
) -> None:
    """Send a welcome message for a new member. Auto-deleted after timeout."""
    try:
        enabled = await get_setting(chat_id, "welcome_enabled")
        if enabled != "on":
            return
        template = await get_setting(chat_id, "welcome_msg")
        if not template:
            return
    except Exception as exc:
        logger.warning("welcome_settings_unavailable", chat_id=chat_id, error=type(exc).__name__)
        return

    display_name = first_name or f"User {user_id}"
    mention = f"@{username}" if username else display_name

    rules = None
    try:
        rules = await get_rules(chat_id)
    except Exception as exc:
        logger.warning("welcome_rules_unavailable", chat_id=chat_id, error=type(exc).__name__)

    count = "—"
    if "{count}" in template:
        try:
            count = str(await bot.get_chat_member_count(chat_id))
        except TelegramError as exc:
            logger.info("welcome_member_count_unavailable", chat_id=chat_id, error=type(exc).__name__)

    text = _format_welcome(
        template,
        name=display_name,
        username=mention,
        group=group_title,
        count=count,
        rules=rules or "",
    )

    # Show rules link if rules are set
    buttons = []
    if rules:
        buttons.append(
            InlineKeyboardButton("📋 القواعد | Rules", callback_data=f"show_rules:{chat_id}")
        )
    keyboard = InlineKeyboardMarkup([buttons]) if buttons else None

    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        logger.info("welcome_sent", chat_id=chat_id, user_id=user_id)

        # Schedule auto-deletion
        create_background_task(
            _auto_delete(bot, chat_id, msg.message_id),
            name=f"welcome-delete:{chat_id}:{msg.message_id}",
        )
    except TelegramError as exc:
        logger.warning("welcome_send_failed", chat_id=chat_id, error=str(exc))


async def send_leave_message(
    bot: Bot,
    chat_id: int,
    user_id: int,
    first_name: str,
    username: str | None,
    group_title: str,
) -> None:
    """Send the configured per-group leave message after a member exits."""
    try:
        enabled = await get_setting(chat_id, "leave_enabled")
        if enabled != "on":
            return
        template = await get_setting(chat_id, "leave_msg")
        if not template:
            return
    except Exception as exc:
        logger.warning("leave_settings_unavailable", chat_id=chat_id, error=type(exc).__name__)
        return

    display_name = first_name or f"User {user_id}"
    mention = f"@{username}" if username else display_name
    text = _format_welcome(
        template,
        name=display_name,
        username=mention,
        group=group_title,
        count="—",
        rules="",
    )

    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
        )
        logger.info("leave_message_sent", chat_id=chat_id, user_id=user_id)
        create_background_task(
            _auto_delete(bot, chat_id, msg.message_id),
            name=f"leave-delete:{chat_id}:{msg.message_id}",
        )
    except TelegramError as exc:
        logger.warning("leave_message_send_failed", chat_id=chat_id, error=str(exc))


async def _auto_delete(bot: Bot, chat_id: int, message_id: int) -> None:
    await asyncio.sleep(WELCOME_AUTO_DELETE_S)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramError:
        pass
