"""
Notification Engine — Transactional and marketing notifications.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from src.db.session import db_session
from src.shop.models import Notification, NotificationType, ShopUser
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def send_notification(
    telegram_id: int,
    title: str,
    body: str,
    notification_type: NotificationType = NotificationType.TRANSACTIONAL,
    metadata: dict | None = None,
    bot=None,
) -> None:
    """Create and optionally send a Telegram notification."""
    async with db_session() as session:
        user_result = await session.execute(
            select(ShopUser).where(ShopUser.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return

        notif = Notification(
            user_id=user.id,
            notification_type=notification_type,
            title=title,
            body=body,
            extra_data=metadata or {},
        )
        session.add(notif)
        await session.flush()

        if bot:
            try:
                await bot.send_message(
                    chat_id=telegram_id,
                    text=f"🔔 *{title}*\n\n{body}",
                    parse_mode="Markdown",
                )
                notif.is_sent = True
                notif.sent_at = datetime.now(tz=UTC)
            except Exception as exc:
                logger.warning("notification_send_failed", telegram_id=telegram_id, error=str(exc))


async def notify_order_update(telegram_id: int, order_ref: str, status: str, bot=None) -> None:
    status_messages = {
        "paid": ("✅ تم تأكيد طلبك", f"طلبك `{order_ref}` تم الدفع بنجاح وهو الآن قيد المعالجة."),
        "completed": ("🎉 طلبك مكتمل!", f"تم تنفيذ طلبك `{order_ref}` بنجاح."),
        "failed": ("❌ فشل تنفيذ الطلب", f"للأسف، فشل تنفيذ طلبك `{order_ref}`. سيتم رد المبلغ تلقائياً."),
        "refunded": ("↩️ تم الاسترداد", f"تم استرداد مبلغ طلبك `{order_ref}` إلى رصيدك."),
        "processing": ("⚙️ جاري المعالجة", f"طلبك `{order_ref}` قيد المعالجة الآن."),
    }

    if status in status_messages:
        title, body = status_messages[status]
        await send_notification(telegram_id, title, body, bot=bot)


async def notify_level_up(telegram_id: int, new_level: str, bot=None) -> None:
    level_names = {
        "bronze": "برونزي 🥉",
        "silver": "فضي 🥈",
        "gold": "ذهبي 🥇",
        "elite": "إليت 👑",
    }
    name = level_names.get(new_level, new_level)
    await send_notification(
        telegram_id,
        "🆙 ترقية المستوى!",
        f"تهانينا! وصلت إلى مستوى *{name}*\nاستمتع بخصومات وامتيازات أفضل!",
        bot=bot,
    )


async def notify_vip_upgrade(telegram_id: int, new_tier: str, bot=None) -> None:
    tier_names = {
        "pro": "برو ⭐",
        "elite": "إليت 👑",
    }
    name = tier_names.get(new_tier, new_tier)
    await send_notification(
        telegram_id,
        "⭐ ترقية VIP!",
        f"تم ترقية عضويتك إلى *VIP {name}*!\nاستمتع بخصومات أكبر وأولوية في التنفيذ!",
        bot=bot,
    )


async def notify_commission(telegram_id: int, amount: float, bot=None) -> None:
    await send_notification(
        telegram_id,
        "💎 عمولة إحالة",
        f"تلقيت عمولة إحالة بقيمة *{amount:.2f}$* تمت إضافتها لرصيدك!",
        bot=bot,
    )


async def send_flash_sale_notification(bot, user_ids: list[int], message: str) -> int:
    """Broadcast a flash sale. Returns number of successfully sent messages."""
    sent = 0
    for tid in user_ids:
        try:
            await bot.send_message(
                chat_id=tid,
                text=f"⚡ *عرض محدود!*\n\n{message}",
                parse_mode="Markdown",
            )
            sent += 1
        except Exception:
            pass
    return sent
