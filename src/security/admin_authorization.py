"""Authorization policy for administrative Telegram commands."""
from __future__ import annotations

from telegram import Bot, Update
from telegram.error import TelegramError

from config.settings import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_ADMIN_STATUSES = {"administrator", "creator"}
_GROUP_CHAT_TYPES = {"group", "supergroup"}


async def is_authorized_admin(update: Update, bot: Bot) -> bool:
    """Return whether the sender is an allowlisted and chat-authorized admin."""
    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None:
        return False

    if user.id not in get_settings().telegram_admin_ids:
        return False

    if chat.type not in _GROUP_CHAT_TYPES:
        return True

    try:
        member = await bot.get_chat_member(chat_id=chat.id, user_id=user.id)
    except TelegramError as exc:
        logger.warning(
            "admin_authorization_lookup_failed",
            chat_id=chat.id,
            user_id=user.id,
            error=type(exc).__name__,
        )
        return False

    authorized = getattr(member, "status", None) in _ADMIN_STATUSES
    if not authorized:
        logger.warning(
            "admin_authorization_denied",
            chat_id=chat.id,
            user_id=user.id,
            member_status=getattr(member, "status", None),
        )
    return authorized
