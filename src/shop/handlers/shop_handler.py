"""
Shop Handler — Main store menu, browsing, service details.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.shop.ai_engine import get_recommendations, get_upsell_services
from src.shop.service_engine import (
    format_service_text,
    get_categories,
    get_featured_services,
    get_service,
    get_services_by_category,
    search_services,
)
from src.shop.user_engine import (
    format_user_profile_text,
    get_or_create_shop_user,
    get_shop_user,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _callback_id(data: list[str], index: int) -> int | None:
    if len(data) <= index:
        return None
    try:
        value = int(data[index])
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


async def cmd_shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main shop entry point — works in DM and groups."""
    user = update.effective_user
    shop_user = await get_or_create_shop_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    keyboard = [
        [
            InlineKeyboardButton("🛍 تصفح الخدمات", callback_data="shop:browse"),
            InlineKeyboardButton("⭐ المميزة", callback_data="shop:featured"),
        ],
        [
            InlineKeyboardButton("🛒 طلباتي", callback_data="shop:myorders"),
            InlineKeyboardButton("💰 محفظتي", callback_data="shop:wallet"),
        ],
        [
            InlineKeyboardButton("👤 ملفي", callback_data="shop:profile"),
            InlineKeyboardButton("🎫 الدعم", callback_data="shop:support"),
        ],
        [
            InlineKeyboardButton("🔗 الإحالات", callback_data="shop:referrals"),
            InlineKeyboardButton("🔍 بحث", callback_data="shop:search"),
        ],
        [InlineKeyboardButton("💡 مقترحة لك", callback_data="shop:recommendations")],
    ]

    vip_icon = {"basic": "🔵", "pro": "⭐", "elite": "👑"}.get(shop_user.vip_tier, "🔵")
    level_icon = {"bronze": "🥉", "silver": "🥈", "gold": "🥇", "elite": "👑"}.get(shop_user.level, "🥉")

    text = (
        f"🏪 *متجر Guardian*\n\n"
        f"أهلاً {user.first_name or 'بك'} {level_icon}\n"
        f"المستوى: *{shop_user.level.title()}* | VIP: {vip_icon}\n"
        f"💰 الرصيد: `{shop_user.balance:.2f}$`\n\n"
        f"اختر ما تريد:"
    )

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def handle_shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = (query.data or "").split(":")

    action = data[1] if len(data) > 1 else ""

    if action == "main":
        await _show_main_menu(query, context)
    elif action == "browse":
        await _show_categories(query, context)
    elif action == "featured":
        await _show_featured(query, context)
    elif action == "category":
        category_id = _callback_id(data, 2)
        if category_id is None:
            await query.answer("فئة غير صالحة", show_alert=True)
            return
        await _show_services(query, context, category_id)
    elif action == "service":
        service_id = _callback_id(data, 2)
        if service_id is None:
            await query.answer("خدمة غير صالحة", show_alert=True)
            return
        await _show_service_detail(query, context, service_id)
    elif action == "profile":
        await _show_profile(query, context)
    elif action == "search":
        await _show_search_prompt(query, context)
    elif action == "myorders":
        from src.shop.handlers.order_handler import show_my_orders
        await show_my_orders(query, context)
    elif action == "wallet":
        from src.shop.handlers.wallet_handler import show_wallet
        await show_wallet(query, context)
    elif action == "support":
        from src.shop.handlers.support_handler import show_support_menu
        await show_support_menu(query, context)
    elif action == "referrals":
        await _show_referrals(query, context)
    elif action == "recommendations":
        await _show_recommendations(query, context)
    elif action == "order":
        service_id = _callback_id(data, 2)
        if service_id is None:
            await query.answer("طلب غير صالح", show_alert=True)
            return
        from src.shop.handlers.order_handler import start_order_flow
        await start_order_flow(query, context, service_id)


async def _show_main_menu(query, context) -> None:
    user = query.from_user
    shop_user = await get_or_create_shop_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )
    keyboard = [
        [
            InlineKeyboardButton("🛍 تصفح الخدمات", callback_data="shop:browse"),
            InlineKeyboardButton("⭐ المميزة", callback_data="shop:featured"),
        ],
        [
            InlineKeyboardButton("🛒 طلباتي", callback_data="shop:myorders"),
            InlineKeyboardButton("💰 محفظتي", callback_data="shop:wallet"),
        ],
        [
            InlineKeyboardButton("👤 ملفي", callback_data="shop:profile"),
            InlineKeyboardButton("🎫 الدعم", callback_data="shop:support"),
        ],
        [
            InlineKeyboardButton("🔗 الإحالات", callback_data="shop:referrals"),
            InlineKeyboardButton("🔍 بحث", callback_data="shop:search"),
        ],
        [InlineKeyboardButton("💡 مقترحة لك", callback_data="shop:recommendations")],
    ]
    vip_icon = {"basic": "🔵", "pro": "⭐", "elite": "👑"}.get(shop_user.vip_tier, "🔵")
    level_icon = {"bronze": "🥉", "silver": "🥈", "gold": "🥇", "elite": "👑"}.get(shop_user.level, "🥉")
    text = (
        f"🏪 *متجر Guardian*\n\n"
        f"أهلاً {user.first_name or 'بك'} {level_icon}\n"
        f"المستوى: *{shop_user.level.title()}* | VIP: {vip_icon}\n"
        f"💰 الرصيد: `{shop_user.balance:.2f}$`\n\n"
        f"اختر ما تريد:"
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def _show_categories(query, context) -> None:
    categories = await get_categories()
    if not categories:
        await query.edit_message_text("❌ لا توجد فئات متاحة حالياً.")
        return

    keyboard = []
    row = []
    for i, cat in enumerate(categories):
        btn = InlineKeyboardButton(
            f"{cat.icon} {cat.name_ar}",
            callback_data=f"shop:category:{cat.id}",
        )
        row.append(btn)
        if len(row) == 2 or i == len(categories) - 1:
            keyboard.append(row)
            row = []

    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="shop:main")])

    await query.edit_message_text(
        "🛍 *تصفح الخدمات*\n\nاختر فئة:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def _show_services(query, context, category_id: int) -> None:
    user = query.from_user
    shop_user = await get_shop_user(user.id)

    service_data = await get_services_by_category(category_id, user=shop_user)

    if not service_data:
        keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="shop:browse")]]
        await query.edit_message_text(
            "❌ لا توجد خدمات في هذه الفئة حالياً.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    keyboard = []
    for data in service_data[:10]:
        svc = data["service"]
        price = data["price"]
        discount_tag = " 🔥" if data["has_discount"] else ""
        stock_tag = " ❌" if svc.stock == 0 else ""
        keyboard.append([
            InlineKeyboardButton(
                f"{svc.title_ar} — {price:.2f}${discount_tag}{stock_tag}",
                callback_data=f"shop:service:{svc.id}",
            )
        ])

    keyboard.append([InlineKeyboardButton("🔙 الفئات", callback_data="shop:browse")])

    await query.edit_message_text(
        f"📦 *الخدمات المتاحة* ({len(service_data)})\n\nاختر خدمة لعرض التفاصيل:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def _show_service_detail(query, context, service_id: int) -> None:
    user = query.from_user
    shop_user = await get_shop_user(user.id)

    data = await get_service(service_id, user=shop_user)
    if not data:
        await query.answer("❌ الخدمة غير موجودة", show_alert=True)
        return

    svc = data["service"]
    text = format_service_text(data)

    upsell = await get_upsell_services(service_id, limit=2)

    keyboard = []

    if svc.stock != 0:
        keyboard.append([
            InlineKeyboardButton("🛒 اطلب الآن", callback_data=f"shop:order:{service_id}"),
        ])

    if upsell:
        keyboard.append([InlineKeyboardButton("━━━━━━━━━━━━━━━━━━", callback_data="shop:noop")])
        keyboard.append([InlineKeyboardButton("💡 قد يعجبك أيضاً:", callback_data="shop:noop")])
        for u_svc in upsell:
            keyboard.append([
                InlineKeyboardButton(
                    f"➕ {u_svc.title_ar}",
                    callback_data=f"shop:service:{u_svc.id}",
                )
            ])

    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data=f"shop:category:{svc.category_id or 0}")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def _show_recommendations(query, context) -> None:
    user = query.from_user
    shop_user = await get_shop_user(user.id)
    if not shop_user:
        shop_user = await get_or_create_shop_user(telegram_id=user.id)

    services = await get_recommendations(shop_user, limit=5)
    if not services:
        await query.edit_message_text(
            "💡 لا توجد مقترحات كافية حالياً. تصفح الخدمات المميزة لاكتشاف المتاح.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⭐ المميزة", callback_data="shop:featured")],
                 [InlineKeyboardButton("🔙 العودة", callback_data="shop:main")]]
            ),
        )
        return

    keyboard = []
    for service in services:
        current = await get_service(service.id, user=shop_user)
        price = current["price"] if current else service.base_price
        keyboard.append([
            InlineKeyboardButton(
                f"{service.title_ar} — {price:.2f}$",
                callback_data=f"shop:service:{service.id}",
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="shop:main")])
    await query.edit_message_text(
        "💡 *مقترحة لك*\n\n"
        "تعتمد هذه المقترحات على سجل مشترياتك، أو على الخدمات المميزة عند عدم وجود سجل سابق.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def _show_featured(query, context) -> None:
    user = query.from_user
    shop_user = await get_shop_user(user.id)
    services = await get_featured_services(user=shop_user, limit=5)

    if not services:
        await query.edit_message_text("❌ لا توجد خدمات مميزة حالياً.")
        return

    keyboard = []
    for data in services:
        svc = data["service"]
        price = data["price"]
        discount_tag = " 🔥" if data["has_discount"] else ""
        keyboard.append([
            InlineKeyboardButton(
                f"⭐ {svc.title_ar} — {price:.2f}${discount_tag}",
                callback_data=f"shop:service:{svc.id}",
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="shop:main")])

    await query.edit_message_text(
        "⭐ *الخدمات المميزة*\n\nأفضل خدماتنا الأكثر طلباً:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def _show_profile(query, context) -> None:
    user = query.from_user
    shop_user = await get_shop_user(user.id)
    if not shop_user:
        shop_user = await get_or_create_shop_user(telegram_id=user.id)

    text = await format_user_profile_text(shop_user)

    keyboard = [
        [
            InlineKeyboardButton("🛒 طلباتي", callback_data="shop:myorders"),
            InlineKeyboardButton("💰 محفظتي", callback_data="shop:wallet"),
        ],
        [InlineKeyboardButton("🔙 العودة", callback_data="shop:main")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def _show_referrals(query, context) -> None:
    user = query.from_user
    shop_user = await get_shop_user(user.id)
    if not shop_user:
        shop_user = await get_or_create_shop_user(telegram_id=user.id)

    from src.shop.affiliate_engine import get_referral_stats
    stats = await get_referral_stats(user.id)

    bot_username = (await query.get_bot().get_me()).username
    referral_link = f"https://t.me/{bot_username}?start=ref_{shop_user.referral_code}"

    text = (
        f"🔗 *نظام الإحالات*\n\n"
        f"كود الإحالة: `{shop_user.referral_code}`\n"
        f"رابط الإحالة:\n`{referral_link}`\n\n"
        f"👥 من دعوتهم: *{stats.get('referred_count', 0)}*\n"
        f"💎 إجمالي العمولات: *{stats.get('total_commissions', 0):.2f}$*\n\n"
        f"📢 *كيف يعمل؟*\n"
        f"• شارك رابطك مع أصدقائك\n"
        f"• عند أول شراء لهم: تحصل على *5%* عمولة\n"
        f"• كل شراء بعد ذلك: *2%* عمولة مدى الحياة"
    )

    keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="shop:main")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def _show_search_prompt(query, context) -> None:
    context.user_data["shop_state"] = "searching"
    keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="shop:main")]]
    await query.edit_message_text(
        "🔍 *البحث في المتجر*\n\nأرسل اسم الخدمة التي تبحث عنها:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def handle_shop_search_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages when user is in search mode."""
    if context.user_data.get("shop_state") != "searching":
        return

    query_text = update.message.text.strip()
    user = update.effective_user
    shop_user = await get_shop_user(user.id)

    results = await search_services(query_text, user=shop_user)
    context.user_data.pop("shop_state", None)

    if not results:
        keyboard = [
            [InlineKeyboardButton("🛍 تصفح الكل", callback_data="shop:browse")],
            [InlineKeyboardButton("🔙 الرئيسية", callback_data="shop:main")],
        ]
        await update.message.reply_text(
            f"🔍 لم أجد نتائج لـ *{query_text}*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    keyboard = []
    for data in results:
        svc = data["service"]
        price = data["price"]
        keyboard.append([
            InlineKeyboardButton(
                f"{svc.title_ar} — {price:.2f}$",
                callback_data=f"shop:service:{svc.id}",
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 الرئيسية", callback_data="shop:main")])

    await update.message.reply_text(
        f"🔍 نتائج البحث عن *{query_text}* ({len(results)}):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
