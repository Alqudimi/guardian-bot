"""
Order Handler — Complete order flow with coupon support.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.shop.coupon_engine import CouponError, auto_apply_best_coupon, validate_coupon
from src.shop.models import OrderStatus
from src.shop.notification_engine import notify_level_up, notify_order_update, notify_vip_upgrade
from src.shop.order_engine import (
    InsufficientBalanceError,
    OrderValidationError,
    ServiceUnavailableError,
    create_order,
    format_order_text,
    get_order_by_ref,
    get_user_orders,
    pay_order,
    refund_order,
)
from src.shop.service_engine import get_service
from src.shop.user_engine import (
    award_xp,
    get_or_create_shop_user,
    get_shop_user,
    update_vip_after_purchase,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def start_order_flow(query, context, service_id: int) -> None:
    """Begin order creation for a service."""
    user = query.from_user
    shop_user = await get_shop_user(user.id)
    if not shop_user:
        shop_user = await get_or_create_shop_user(telegram_id=user.id)

    data = await get_service(service_id, user=shop_user)
    if not data:
        await query.answer("❌ الخدمة غير موجودة", show_alert=True)
        return

    svc = data["service"]
    if svc.stock == 0:
        await query.answer("❌ هذه الخدمة غير متوفرة حالياً", show_alert=True)
        return

    price = data["price"]
    available = shop_user.balance - shop_user.locked_balance

    best_coupon, auto_discount = await auto_apply_best_coupon(
        shop_user, price, [service_id]
    )

    final_price = round(price - auto_discount, 2)
    coupon_text = ""
    if best_coupon and auto_discount > 0:
        coupon_text = f"\n🎟 كوبون مُطبَّق: `{best_coupon.code}` (-{auto_discount:.2f}$)"

    context.user_data["pending_order"] = {
        "service_id": service_id,
        "unit_price": price,
        "quantity": 1,
        "coupon_id": best_coupon.id if best_coupon else None,
        "final_price": final_price,
    }

    balance_ok = available >= final_price

    text = (
        f"🛒 *تأكيد الطلب*\n\n"
        f"📦 الخدمة: *{svc.title_ar}*\n"
        f"💰 السعر: `{price:.2f}$`"
        f"{coupon_text}\n"
        f"💳 الإجمالي: `{final_price:.2f}$`\n\n"
        f"رصيدك المتاح: `{available:.2f}$`\n"
    )

    if not balance_ok:
        shortage = final_price - available
        text += f"\n⚠️ رصيدك غير كافٍ، تحتاج {shortage:.2f}$ إضافية."
        keyboard = [
            [InlineKeyboardButton("💰 شحن الرصيد", callback_data="shop:wallet")],
            [InlineKeyboardButton("🔙 العودة", callback_data=f"shop:service:{service_id}")],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("✅ تأكيد الدفع", callback_data=f"order:confirm:{service_id}"),
                InlineKeyboardButton("❌ إلغاء", callback_data=f"shop:service:{service_id}"),
            ],
        ]
        if not best_coupon:
            keyboard.insert(0, [
                InlineKeyboardButton("🎟 لدي كوبون", callback_data=f"order:coupon:{service_id}"),
            ])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def handle_order_callback(query, context) -> None:
    data = (query.data or "").split(":")
    action = data[1] if len(data) > 1 else ""
    try:
        if action in {"confirm", "coupon"}:
            service_id = int(data[2])
            if service_id < 1:
                raise ValueError
            if action == "confirm":
                await _process_order(query, context, service_id)
            else:
                context.user_data["shop_state"] = f"coupon_for_{service_id}"
                keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data=f"shop:order:{service_id}")]]
                await query.edit_message_text(
                    "🎟 أدخل كود الكوبون:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
        elif action == "detail":
            order_ref = data[2]
            if not order_ref or len(order_ref) > 32:
                raise ValueError
            await _show_order_detail(query, context, order_ref)
        elif action == "refund":
            order_id = int(data[2])
            if order_id < 1:
                raise ValueError
            await _request_refund(query, context, order_id)
    except (IndexError, TypeError, ValueError):
        await query.answer("❌ رابط الطلب غير صالح أو منتهي", show_alert=True)


async def _process_order(query, context, service_id: int) -> None:
    user = query.from_user
    shop_user = await get_shop_user(user.id)
    if not shop_user:
        await query.answer("❌ يرجى بدء المتجر أولاً بـ /shop", show_alert=True)
        return

    pending = context.user_data.get("pending_order", {})
    if not pending or pending.get("service_id") != service_id:
        await query.answer("❌ انتهت صلاحية الطلب، ابدأ من جديد", show_alert=True)
        return

    try:
        items = [{
            "service_id": pending["service_id"],
            "quantity": pending["quantity"],
            "unit_price": pending["unit_price"],
        }]
        order = await create_order(
            user=shop_user,
            items=items,
            coupon_id=pending.get("coupon_id"),
        )
        paid_order = await pay_order(order.id, user.id)

        context.user_data.pop("pending_order", None)

        xp_amount = max(10, int(paid_order.total_amount * 2))
        new_xp, leveled_up, new_level = await award_xp(user.id, "purchase", bonus_xp=xp_amount - 10)
        new_vip, vip_upgraded = await update_vip_after_purchase(user.id)

        if leveled_up:
            await notify_level_up(user.id, new_level, bot=context.bot)
        if vip_upgraded:
            await notify_vip_upgrade(user.id, new_vip, bot=context.bot)

        await notify_order_update(user.id, paid_order.order_ref, "paid", bot=context.bot)

        keyboard = [
            [InlineKeyboardButton("📋 تفاصيل الطلب", callback_data=f"order:detail:{paid_order.order_ref}")],
            [InlineKeyboardButton("🏪 متابعة التسوق", callback_data="shop:main")],
        ]

        xp_text = f"\n✨ حصلت على {xp_amount} XP!"
        level_text = f"\n🆙 ترقيت إلى *{new_level.title()}*!" if leveled_up else ""

        await query.edit_message_text(
            f"✅ *تم تأكيد طلبك!*\n\n"
            f"رقم الطلب: `{paid_order.order_ref}`\n"
            f"المبلغ: `{paid_order.total_amount:.2f}$`\n"
            f"الحالة: ⚙️ قيد المعالجة"
            f"{xp_text}{level_text}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    except InsufficientBalanceError as e:
        await query.answer(str(e), show_alert=True)
    except (OrderValidationError, ServiceUnavailableError) as e:
        await query.answer(str(e), show_alert=True)
    except Exception as e:
        logger.error("order_processing_error", error=str(e))
        await query.answer("❌ حدث خطأ أثناء معالجة الطلب", show_alert=True)


async def show_my_orders(query, context) -> None:
    user = query.from_user
    shop_user = await get_shop_user(user.id)
    if not shop_user:
        await query.edit_message_text("❌ لا يوجد حساب. ابدأ بـ /shop")
        return

    orders = await get_user_orders(shop_user.id, limit=8)

    if not orders:
        keyboard = [
            [InlineKeyboardButton("🛍 تصفح الخدمات", callback_data="shop:browse")],
            [InlineKeyboardButton("🔙 العودة", callback_data="shop:main")],
        ]
        await query.edit_message_text(
            "📦 *طلباتي*\n\nلا توجد طلبات بعد.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    status_emoji = {
        "created": "🆕", "validated": "✅", "paid": "💳",
        "processing": "⚙️", "completed": "✅", "failed": "❌",
        "refunded": "↩️", "cancelled": "🚫",
    }

    keyboard = []
    for order in orders:
        emoji = status_emoji.get(order.status, "❓")
        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} {order.order_ref} — {order.total_amount:.2f}$",
                callback_data=f"order:detail:{order.order_ref}",
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="shop:main")])

    await query.edit_message_text(
        f"🛒 *طلباتي* ({len(orders)})",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def _show_order_detail(query, context, order_ref: str) -> None:
    order = await get_order_by_ref(order_ref, telegram_id=query.from_user.id)
    if not order:
        await query.answer("❌ الطلب غير موجود", show_alert=True)
        return

    text = format_order_text(order)
    keyboard = []

    if order.status == OrderStatus.PAID or order.status == OrderStatus.PROCESSING:
        keyboard.append([
            InlineKeyboardButton("↩️ طلب استرداد", callback_data=f"order:refund:{order.id}"),
        ])

    keyboard.append([InlineKeyboardButton("🔙 طلباتي", callback_data="shop:myorders")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def _request_refund(query, context, order_id: int) -> None:
    try:
        order = await refund_order(order_id, telegram_id=query.from_user.id)
        await notify_order_update(query.from_user.id, order.order_ref, "refunded", bot=context.bot)
        keyboard = [[InlineKeyboardButton("🔙 طلباتي", callback_data="shop:myorders")]]
        await query.edit_message_text(
            f"↩️ *تم طلب الاسترداد*\n\nسيتم رد `{order.total_amount:.2f}$` إلى رصيدك خلال لحظات.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
    except OrderValidationError as e:
        await query.answer(str(e), show_alert=True)


async def handle_coupon_message(update, context) -> None:
    """Handle coupon code input from user."""
    state = context.user_data.get("shop_state", "")
    if not state.startswith("coupon_for_"):
        return

    try:
        service_id = int(state.replace("coupon_for_", ""))
        if service_id < 1:
            raise ValueError
    except ValueError:
        context.user_data.pop("shop_state", None)
        return
    code = update.message.text.strip().upper()
    user = update.effective_user
    shop_user = await get_shop_user(user.id)
    if not shop_user:
        return

    pending = context.user_data.get("pending_order", {})
    order_amount = pending.get("unit_price", 0)

    try:
        coupon = await validate_coupon(code, shop_user, order_amount, [service_id])
        from src.shop.coupon_engine import calculate_discount
        discount = calculate_discount(coupon, order_amount)
        final_price = round(order_amount - discount, 2)

        context.user_data["pending_order"]["coupon_id"] = coupon.id
        context.user_data["pending_order"]["final_price"] = final_price
        context.user_data.pop("shop_state", None)

        keyboard = [
            [
                InlineKeyboardButton("✅ تأكيد الدفع", callback_data=f"order:confirm:{service_id}"),
                InlineKeyboardButton("❌ إلغاء", callback_data=f"shop:service:{service_id}"),
            ]
        ]
        await update.message.reply_text(
            f"✅ *كوبون صالح!*\n\n"
            f"الكوبون: `{code}`\n"
            f"الخصم: `{discount:.2f}$`\n"
            f"السعر النهائي: `{final_price:.2f}$`",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
    except CouponError as e:
        keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data=f"shop:order:{service_id}")]]
        context.user_data.pop("shop_state", None)
        await update.message.reply_text(
            f"❌ {e}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
