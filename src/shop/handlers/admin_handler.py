"""
Admin Shop Handler — Full control panel for the store.
Commands (admin only):
  /shop_dashboard     — Revenue & stats overview
  /shop_services      — Manage services
  /shop_addservice    — Add a new service
  /shop_orders        — View recent orders
  /shop_order <ref>   — Order details + actions
  /shop_users         — User list
  /shop_user <tid>    — User details + actions
  /shop_addbalance    — Add balance to a user
  /shop_coupons       — Coupon list
  /shop_addcoupon     — Create coupon
  /shop_tickets       — Open support tickets
  /shop_broadcast     — Send flash sale message
  /shop_addcat        — Add service category
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config.settings import get_settings
from src.shop.ai_engine import calculate_fraud_score, get_revenue_insights
from src.shop.coupon_engine import create_coupon
from src.shop.models import OrderStatus
from src.shop.notification_engine import send_flash_sale_notification
from src.shop.order_engine import (
    OrderValidationError,
    complete_order,
    fail_order,
    format_order_text,
    get_order_by_ref,
    refund_order,
)
from src.shop.service_engine import create_category, create_service, get_categories
from src.shop.support_engine import (
    close_ticket,
    escalate_ticket,
    get_all_open_tickets,
    reply_to_ticket,
)
from src.shop.user_engine import get_shop_user
from src.shop.wallet_engine import admin_adjust_balance
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _is_admin(user_id: int) -> bool:
    return user_id in get_settings().telegram_admin_ids


def _admin_only(fn):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ للمشرفين فقط.")
            return
        return await fn(update, context)
    wrapper.__name__ = fn.__name__
    return wrapper


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_shop_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    insights_7 = await get_revenue_insights(days=7)
    insights_30 = await get_revenue_insights(days=30)

    text = (
        f"📊 *لوحة تحكم المتجر*\n\n"
        f"━━━━━━━━━━━ آخر 7 أيام ━━━━━━━━━━━\n"
        f"💰 الإيرادات: `{insights_7['revenue']:.2f}$`\n"
        f"📦 الطلبات: `{insights_7['total_orders']}`\n"
        f"✅ المكتملة: `{insights_7['completed_orders']}`\n"
        f"👥 مستخدمون جدد: `{insights_7['new_users']}`\n"
        f"📈 معدل التحويل: `{insights_7['conversion_rate']}%`\n\n"
        f"━━━━━━━━━━━ آخر 30 يوم ━━━━━━━━━━━\n"
        f"💰 الإيرادات: `{insights_30['revenue']:.2f}$`\n"
        f"📦 الطلبات: `{insights_30['total_orders']}`\n"
        f"✅ المكتملة: `{insights_30['completed_orders']}`\n"
        f"👥 مستخدمون جدد: `{insights_30['new_users']}`\n"
        f"📈 معدل التحويل: `{insights_30['conversion_rate']}%`\n\n"
        f"━━━━━━━━━━━ أوامر الإدارة ━━━━━━━━━━━\n"
        f"/shop_orders — الطلبات الأخيرة\n"
        f"/shop_tickets — تذاكر الدعم\n"
        f"/shop_services — الخدمات\n"
        f"/shop_coupons — الكوبونات\n"
        f"/shop_addservice — إضافة خدمة\n"
        f"/shop_addcoupon — إضافة كوبون\n"
        f"/shop_broadcast — بث رسالة\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
# Order Management
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_shop_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from src.db.session import db_session
    from src.shop.models import Order

    async with db_session() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.user))
            .order_by(Order.created_at.desc())
            .limit(15)
        )
        orders = list(result.scalars().all())

    if not orders:
        await update.message.reply_text("📭 لا توجد طلبات.")
        return

    status_emoji = {
        "created": "🆕", "validated": "✅", "paid": "💳",
        "processing": "⚙️", "completed": "✅", "failed": "❌",
        "refunded": "↩️", "cancelled": "🚫",
    }
    lines = ["📦 *آخر الطلبات*\n"]
    for order in orders:
        emoji = status_emoji.get(order.status, "❓")
        user_str = f"@{order.user.username}" if order.user and order.user.username else f"id:{order.user.telegram_id if order.user else '?'}"
        lines.append(
            f"{emoji} `{order.order_ref}` — {order.total_amount:.2f}$ — {user_str}\n"
            f"   `/shop_order {order.order_ref}`"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@_admin_only
async def cmd_shop_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /shop_order <order_ref>")
        return

    order_ref = context.args[0].upper()
    order = await get_order_by_ref(order_ref)
    if not order:
        await update.message.reply_text(f"❌ الطلب {order_ref} غير موجود.")
        return

    text = format_order_text(order)
    if order.user:
        text += f"\n\n👤 المستخدم: `{order.user.telegram_id}`"
        if order.user.username:
            text += f" (@{order.user.username})"

    keyboard = []
    if order.status in (OrderStatus.PAID, OrderStatus.PROCESSING):
        keyboard.append([
            InlineKeyboardButton("✅ أكمل الطلب", callback_data=f"admin_order:complete:{order.id}"),
            InlineKeyboardButton("❌ فشل الطلب", callback_data=f"admin_order:fail:{order.id}"),
        ])
    if order.status not in (OrderStatus.REFUNDED, OrderStatus.CANCELLED):
        keyboard.append([
            InlineKeyboardButton("↩️ استرداد", callback_data=f"admin_order:refund:{order.id}"),
        ])

    markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")


async def handle_admin_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _is_admin(query.from_user.id):
        await query.answer("⛔ للمشرفين فقط", show_alert=True)
        return

    await query.answer()
    try:
        data = (query.data or "").split(":")
        action = data[1]
        order_id = int(data[2])
        if action not in {"complete", "fail", "refund"} or order_id < 1:
            raise ValueError
    except (IndexError, TypeError, ValueError):
        await query.answer("❌ رابط إداري غير صالح", show_alert=True)
        return

    try:
        if action == "complete":
            order = await complete_order(order_id)
            from src.shop.notification_engine import notify_order_update
            if order.user:
                await notify_order_update(order.user.telegram_id, order.order_ref, "completed", bot=context.bot)
            await query.edit_message_text(f"✅ تم إكمال الطلب `{order.order_ref}`", parse_mode="Markdown")
        elif action == "fail":
            order = await fail_order(order_id, reason="فشل يدوي من الإدارة")
            if order.user:
                from src.shop.notification_engine import notify_order_update
                await notify_order_update(
                    order.user.telegram_id, order.order_ref, "failed", bot=context.bot
                )
            await query.edit_message_text(f"❌ تم تحديد الطلب `{order.order_ref}` كفاشل", parse_mode="Markdown")
        elif action == "refund":
            order = await refund_order(order_id)
            from src.shop.notification_engine import notify_order_update
            if order.user:
                await notify_order_update(order.user.telegram_id, order.order_ref, "refunded", bot=context.bot)
            await query.edit_message_text(f"↩️ تم استرداد الطلب `{order.order_ref}`", parse_mode="Markdown")
    except OrderValidationError as exc:
        await query.edit_message_text(f"❌ تعذر تنفيذ العملية: {exc}")
    except Exception:
        logger.exception("admin_order_callback_failed", action=action, order_id=order_id)
        await query.edit_message_text("❌ تعذر تنفيذ العملية حالياً")


# ─────────────────────────────────────────────────────────────────────────────
# User Management
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_shop_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /shop_user <telegram_id>")
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ معرف غير صالح")
        return

    user = await get_shop_user(tid)
    if not user:
        await update.message.reply_text(f"❌ لا يوجد حساب للمستخدم {tid}")
        return

    fraud_score, flags = await calculate_fraud_score(tid)
    fraud_text = f"\n⚠️ درجة الاحتيال: `{fraud_score:.0f}/100` — {', '.join(flags) or 'نظيف'}"

    from src.shop.user_engine import format_user_profile_text
    profile = await format_user_profile_text(user)

    text = profile + fraud_text + f"\n\nالحالة: {'🔴 موقوف' if user.is_banned else '🟢 نشط'}"
    await update.message.reply_text(text, parse_mode="Markdown")


@_admin_only
async def cmd_shop_addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args or []) < 2:
        await update.message.reply_text("Usage: /shop_addbalance <telegram_id> <amount> [note]")
        return
    try:
        tid = int(context.args[0])
        amount = float(context.args[1])
        note = " ".join(context.args[2:]) if len(context.args) > 2 else "إضافة رصيد من الإدارة"
    except (ValueError, IndexError):
        await update.message.reply_text("❌ بيانات غير صالحة")
        return

    try:
        await admin_adjust_balance(telegram_id=tid, amount=amount, description=note)
        await update.message.reply_text(f"✅ تم إضافة `{amount:.2f}$` للمستخدم `{tid}`", parse_mode="Markdown")
    except Exception:
        logger.exception("admin_balance_adjustment_failed", telegram_id=tid)
        await update.message.reply_text("❌ تعذر تعديل الرصيد حالياً.")


# ─────────────────────────────────────────────────────────────────────────────
# Service Management
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_shop_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from sqlalchemy import select

    from src.db.session import db_session
    from src.shop.models import Service

    async with db_session() as session:
        result = await session.execute(
            select(Service).order_by(Service.category_id, Service.id).limit(20)
        )
        services = list(result.scalars().all())

    if not services:
        await update.message.reply_text("📭 لا توجد خدمات. استخدم /shop_addservice")
        return

    lines = ["📦 *الخدمات* (أول 20)\n"]
    for svc in services:
        status = "✅" if svc.is_active else "❌"
        lines.append(f"{status} `#{svc.id}` {svc.title_ar} — {svc.base_price:.2f}$")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@_admin_only
async def cmd_shop_addservice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Usage: /shop_addservice <category_id> <price> <type> <title_en> | <title_ar>
    Example: /shop_addservice 1 9.99 instant Social Media Boost | تعزيز السوشيال ميديا
    """
    if not context.args or len(context.args) < 4:
        cats = await get_categories()
        cats_text = "\n".join([f"`{c.id}` — {c.name_ar}" for c in cats]) or "لا توجد فئات، استخدم /shop_addcat أولاً"
        await update.message.reply_text(
            "Usage: `/shop_addservice <cat_id> <price> <type(instant/manual/hybrid)> <name_en> | <name_ar>`\n\n"
            f"الفئات المتاحة:\n{cats_text}",
            parse_mode="Markdown",
        )
        return

    try:
        cat_id = int(context.args[0])
        price = float(context.args[1])
        stype = context.args[2].lower()
        rest = " ".join(context.args[3:])
        if "|" in rest:
            title_en, title_ar = [p.strip() for p in rest.split("|", 1)]
        else:
            title_en = rest
            title_ar = rest
    except (ValueError, IndexError):
        await update.message.reply_text("❌ بيانات غير صالحة.")
        return

    svc = await create_service(
        title=title_en,
        title_ar=title_ar,
        base_price=price,
        category_id=cat_id,
        service_type=stype,
    )
    await update.message.reply_text(
        f"✅ تم إضافة الخدمة:\n`#{svc.id}` {svc.title_ar} — {svc.base_price:.2f}$",
        parse_mode="Markdown",
    )


@_admin_only
async def cmd_shop_addcat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /shop_addcat <icon> <name_en> | <name_ar>"""
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/shop_addcat <icon> <name_en> | <name_ar>`\n"
            "Example: `/shop_addcat 📱 Social Media | سوشيال ميديا`",
            parse_mode="Markdown",
        )
        return

    icon = context.args[0]
    rest = " ".join(context.args[1:])
    if "|" in rest:
        name_en, name_ar = [p.strip() for p in rest.split("|", 1)]
    else:
        name_en = rest
        name_ar = rest

    cat = await create_category(name=name_en, name_ar=name_ar, icon=icon)
    await update.message.reply_text(
        f"✅ تم إضافة الفئة: {icon} {cat.name_ar} (ID: {cat.id})",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Coupon Management
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_shop_coupons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from sqlalchemy import select

    from src.db.session import db_session
    from src.shop.models import Coupon

    async with db_session() as session:
        result = await session.execute(
            select(Coupon).order_by(Coupon.created_at.desc()).limit(15)
        )
        coupons = list(result.scalars().all())

    if not coupons:
        await update.message.reply_text("📭 لا توجد كوبونات.")
        return

    lines = ["🎟 *الكوبونات*\n"]
    for c in coupons:
        status = "✅" if c.is_active else "❌"
        discount = f"{c.discount_percent}%" if c.discount_percent else f"{c.discount_fixed}$"
        usage = f"{c.usage_count}/{c.usage_limit or '∞'}"
        lines.append(f"{status} `{c.code}` — {discount} — {usage} استخدام")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@_admin_only
async def cmd_shop_addcoupon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Usage: /shop_addcoupon <code> <discount%> [usage_limit] [min_order]
    Example: /shop_addcoupon SAVE20 20 100 10
    """
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/shop_addcoupon <code> <discount%> [usage_limit] [min_order]`\n"
            "Example: `/shop_addcoupon SAVE20 20 100 10`",
            parse_mode="Markdown",
        )
        return

    try:
        code = context.args[0].upper()
        discount_pct = float(context.args[1])
        usage_limit = int(context.args[2]) if len(context.args) > 2 else None
        min_order = float(context.args[3]) if len(context.args) > 3 else 0.0
    except (ValueError, IndexError):
        await update.message.reply_text("❌ بيانات الكوبون غير صالحة.")
        return

    try:
        coupon = await create_coupon(
            code=code,
            discount_percent=discount_pct,
            usage_limit=usage_limit,
            min_order_amount=min_order,
        )
        await update.message.reply_text(
            f"✅ تم إنشاء الكوبون:\n`{coupon.code}` — {discount_pct}% خصم",
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("admin_coupon_creation_failed", code=code)
        await update.message.reply_text("❌ تعذر إنشاء الكوبون حالياً.")


# ─────────────────────────────────────────────────────────────────────────────
# Support Management
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_shop_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tickets = await get_all_open_tickets(limit=15)

    if not tickets:
        await update.message.reply_text("✅ لا توجد تذاكر مفتوحة.")
        return

    priority_emoji = {"low": "🟢", "normal": "🔵", "high": "🟠", "urgent": "🔴"}
    lines = [f"🎫 *تذاكر مفتوحة* ({len(tickets)})\n"]
    for t in tickets:
        emoji = priority_emoji.get(t.priority, "❓")
        user_str = f"@{t.user.username}" if t.user and t.user.username else f"tid:{t.user.telegram_id if t.user else '?'}"
        lines.append(
            f"{emoji} `{t.ticket_ref}` — {t.subject[:30]}\n"
            f"   👤 {user_str} | `/shop_ticket {t.ticket_ref}`"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@_admin_only
async def cmd_shop_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /shop_ticket <ticket_ref> [reply message...]")
        return

    ticket_ref = context.args[0].upper()
    reply_msg = " ".join(context.args[1:]) if len(context.args) > 1 else None

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from src.db.session import db_session
    from src.shop.models import SupportTicket

    async with db_session() as session:
        result = await session.execute(
            select(SupportTicket)
            .options(selectinload(SupportTicket.user), selectinload(SupportTicket.messages))
            .where(SupportTicket.ticket_ref == ticket_ref)
        )
        ticket = result.scalar_one_or_none()

    if not ticket:
        await update.message.reply_text(f"❌ التذكرة {ticket_ref} غير موجودة")
        return

    from src.shop.support_engine import format_ticket_text
    text = format_ticket_text(ticket)

    if ticket.user:
        text += f"\n\n👤 `{ticket.user.telegram_id}`"
        if ticket.user.username:
            text += f" (@{ticket.user.username})"

    if reply_msg:
        try:
            await reply_to_ticket(ticket_ref, reply_msg, update.effective_user.id, is_admin=True)
            text += f"\n\n✅ *تم إرسال الرد:*\n_{reply_msg}_"
            if ticket.user:
                try:
                    await context.bot.send_message(
                        chat_id=ticket.user.telegram_id,
                        text=f"🎫 *رد على تذكرتك #{ticket_ref}*\n\n{reply_msg}",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
        except Exception:
            logger.exception("admin_ticket_reply_failed", ticket_ref=ticket_ref)
            text += "\n\n❌ تعذر إرسال الرد حالياً."

    keyboard = [
        [
            InlineKeyboardButton("✅ إغلاق", callback_data=f"admin_ticket:close:{ticket_ref}"),
            InlineKeyboardButton("🔴 تصعيد", callback_data=f"admin_ticket:escalate:{ticket_ref}"),
        ]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def handle_admin_ticket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _is_admin(query.from_user.id):
        await query.answer("⛔ للمشرفين فقط", show_alert=True)
        return
    await query.answer()

    try:
        data = (query.data or "").split(":", 2)
        action = data[1]
        ticket_ref = data[2]
        if action not in {"close", "escalate"} or not ticket_ref or len(ticket_ref) > 64:
            raise ValueError
    except (IndexError, TypeError, ValueError):
        await query.answer("❌ رابط تذكرة غير صالح", show_alert=True)
        return

    try:
        if action == "close":
            await close_ticket(ticket_ref, admin_notes="مغلقة من الإدارة")
            await query.edit_message_text(f"✅ تم إغلاق التذكرة `{ticket_ref}`", parse_mode="Markdown")
        elif action == "escalate":
            await escalate_ticket(ticket_ref)
            await query.edit_message_text(f"🔴 تم تصعيد التذكرة `{ticket_ref}`", parse_mode="Markdown")
    except Exception:
        logger.exception("admin_ticket_callback_failed", action=action, ticket_ref=ticket_ref)
        await query.edit_message_text("❌ تعذر تنفيذ العملية حالياً")


# ─────────────────────────────────────────────────────────────────────────────
# Broadcast
# ─────────────────────────────────────────────────────────────────────────────

@_admin_only
async def cmd_shop_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /shop_broadcast <message>")
        return

    message = " ".join(context.args)

    from sqlalchemy import select

    from src.db.session import db_session
    from src.shop.models import ShopUser

    async with db_session() as session:
        result = await session.execute(
            select(ShopUser.telegram_id).where(ShopUser.is_banned == False).limit(1000)
        )
        user_ids = [row[0] for row in result.all()]

    if not user_ids:
        await update.message.reply_text("❌ لا يوجد مستخدمون.")
        return

    await update.message.reply_text(f"📤 جاري الإرسال إلى {len(user_ids)} مستخدم...")
    sent = await send_flash_sale_notification(context.bot, user_ids, message)
    await update.message.reply_text(f"✅ تم الإرسال بنجاح إلى {sent}/{len(user_ids)} مستخدم.")
