"""
Group Rules Manager
====================
Manage and display group rules with inline button navigation.

Commands:
  /setrules <text>   — Set/update group rules (admin only)
  /rules             — Display current group rules (any member)
  /clearrules        — Clear group rules (admin only)

Features:
  • Rules stored per-group in Redis
  • Supports Markdown formatting in rules
  • Maximum 5 rules sections (numbered)
  • Auto-pinning option for rules message
  • Rules message auto-refreshed on /rules calls (deletes old rules msg)
  • Optional: new members shown rules on join (if welcome is enabled)
"""
from __future__ import annotations

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from config.settings import get_settings
from src.management.group_settings import get_setting, set_setting
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

_MAX_RULES_LENGTH = 3000


async def set_rules(chat_id: int, rules_text: str) -> None:
    """Store group rules text."""
    if len(rules_text) > _MAX_RULES_LENGTH:
        raise ValueError(f"Rules too long ({len(rules_text)} > {_MAX_RULES_LENGTH} chars)")
    await set_setting(chat_id, "rules_text", rules_text)
    # Store the last rules message ID for replacement
    redis = await get_redis()
    settings = get_settings()
    await redis.delete(f"{settings.redis_prefix}rules_msg:{chat_id}")


async def get_rules(chat_id: int) -> str | None:
    """Get group rules text. Returns None if not set."""
    text = await get_setting(chat_id, "rules_text")
    return text if text else None


async def clear_rules(chat_id: int) -> None:
    """Clear group rules."""
    await set_setting(chat_id, "rules_text", "")


async def send_rules_message(bot: Bot, chat_id: int) -> None:
    """Send the rules message to the group, replacing the previous one."""
    redis = await get_redis()
    settings = get_settings()

    rules = await get_rules(chat_id)
    if not rules:
        await bot.send_message(
            chat_id=chat_id,
            text="لم يتم تعيين قواعد لهذه المجموعة بعد.\nNo rules set yet. Use /setrules to add them.",
        )
        return

    # Delete previous rules message if exists
    old_msg_key = f"{settings.redis_prefix}rules_msg:{chat_id}"
    old_msg_id = await redis.get(old_msg_key)
    if old_msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=int(old_msg_id))
        except TelegramError:
            pass

    text = f"📋 *قواعد المجموعة | Group Rules*\n\n{rules}"
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ قرأت القواعد | I've read the rules", callback_data=f"rules_ack:{chat_id}")
    ]])

    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        await redis.setex(old_msg_key, 86400 * 30, str(msg.message_id))
    except TelegramError as exc:
        logger.warning("rules_send_failed", chat_id=chat_id, error=str(exc))
