"""
Support Handler — Ticket creation, replies, status tracking.
"""
from __future__ import annotations

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.shop.support_engine import (
    TICKET_CATEGORIES,
    create_ticket,
    format_ticket_text,
    get_user_tickets,
    reply_to_ticket,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)
_TICKET_REF_PATTERN = re.compile(r"^TKT-\d{6}-[A-F0-9]{6}$")


def _valid_ticket_ref(ticket_ref: str) -> bool:
    return bool(_TICKET_REF_PATTERN.fullmatch(ticket_ref))


async def show_support_menu(query, context) -> None:
    keyboard = [
        [
            InlineKeyboardButton("🎫 تذاكري", callback_data="support:my_tickets"),
            InlineKeyboardButton("➕ فتح تذكرة", callback_data="support:new"),
        ],
        [InlineKeyboardButton("🔙 العودة", callback_data="shop:main")],
    ]
    await query.edit_message_text(
        "🎧 *مركز الدعم*\n\n"
        "نحن هنا لمساعدتك في أي استفسار أو مشكلة.\n"
        "تُرتب التذاكر حسب الأولوية وموعد SLA المسجل.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def handle_support_callback(query, context) -> None:
    data = (query.data or "").split(":")
    action = data[1] if len(data) > 1 else ""
    if not action:
        await query.answer("⛔ طلب دعم غير صالح.", show_alert=True)
        return

    if action == "my_tickets":
        await _show_my_tickets(query, context)
    elif action == "new":
        await _show_category_selection(query, context)
    elif action == "category":
        category = data[2] if len(data) > 2 else ""
        if category not in TICKET_CATEGORIES:
            await query.answer("⛔ تصنيف غير صالح.", show_alert=True)
            return
        context.user_data["ticket_category"] = category
        context.user_data["shop_state"] = "ticket_subject"
        keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="shop:support")]]
        cat_name = TICKET_CATEGORIES.get(category, category)
        await query.edit_message_text(
            f"📝 *{cat_name}*\n\nأدخل موضوع التذكرة (عنوان مختصر):",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
    elif action == "view":
        ticket_ref = data[2] if len(data) > 2 else ""
        if not _valid_ticket_ref(ticket_ref):
            await query.answer("⛔ رقم تذكرة غير صالح.", show_alert=True)
            return
        await _show_ticket_detail(query, context, ticket_ref)
    elif action == "reply":
        ticket_ref = data[2] if len(data) > 2 else ""
        if not _valid_ticket_ref(ticket_ref):
            await query.answer("⛔ رقم تذكرة غير صالح.", show_alert=True)
            return
        context.user_data["replying_to_ticket"] = ticket_ref
        context.user_data["shop_state"] = "ticket_reply"
        keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data=f"support:view:{ticket_ref}")]]
        await query.edit_message_text(
            "💬 اكتب ردك على التذكرة:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await query.answer("⛔ إجراء دعم غير معروف.", show_alert=True)


async def _show_my_tickets(query, context) -> None:
    user = query.from_user
    tickets = await get_user_tickets(user.id, limit=5)

    if not tickets:
        keyboard = [
            [InlineKeyboardButton("➕ فتح تذكرة", callback_data="support:new")],
            [InlineKeyboardButton("🔙 العودة", callback_data="shop:support")],
        ]
        await query.edit_message_text(
            "📭 لا توجد تذاكر بعد.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    status_emoji = {
        "open": "🟢", "in_progress": "🔵", "waiting": "🟡",
        "resolved": "✅", "closed": "⚫", "escalated": "🔴",
    }

    keyboard = []
    for ticket in tickets:
        emoji = status_emoji.get(ticket.status, "❓")
        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} #{ticket.ticket_ref} — {ticket.subject[:25]}",
                callback_data=f"support:view:{ticket.ticket_ref}",
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="shop:support")])

    await query.edit_message_text(
        f"🎫 *تذاكري* ({len(tickets)})",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def _show_category_selection(query, context) -> None:
    keyboard = []
    for key, name in TICKET_CATEGORIES.items():
        keyboard.append([InlineKeyboardButton(name, callback_data=f"support:category:{key}")])
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="shop:support")])

    await query.edit_message_text(
        "📂 *نوع المشكلة*\n\nاختر تصنيف تذكرتك:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def _show_ticket_detail(query, context, ticket_ref: str) -> None:
    user = query.from_user
    tickets = await get_user_tickets(user.id, limit=20)
    ticket = next((t for t in tickets if t.ticket_ref == ticket_ref), None)

    if not ticket:
        await query.answer("❌ التذكرة غير موجودة", show_alert=True)
        return

    text = format_ticket_text(ticket)
    keyboard = []

    if ticket.status not in ("resolved", "closed"):
        keyboard.append([
            InlineKeyboardButton("💬 إضافة رد", callback_data=f"support:reply:{ticket_ref}"),
        ])
    keyboard.append([InlineKeyboardButton("🔙 تذاكري", callback_data="support:my_tickets")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages for ticket creation flow."""
    state = context.user_data.get("shop_state", "")
    user = update.effective_user

    if state == "ticket_subject":
        context.user_data["ticket_subject"] = update.message.text.strip()
        context.user_data["shop_state"] = "ticket_message"
        keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="shop:support")]]
        await update.message.reply_text(
            "📝 اكتب رسالتك أو وصف المشكلة بالتفصيل:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if state == "ticket_message":
        subject = context.user_data.pop("ticket_subject", "استفسار")
        category = context.user_data.pop("ticket_category", "general")
        context.user_data.pop("shop_state", None)

        try:
            ticket = await create_ticket(
                telegram_id=user.id,
                subject=subject,
                message=update.message.text.strip(),
                category=category,
            )
            keyboard = [
                [
                    InlineKeyboardButton(
                        "📋 عرض التذكرة",
                        callback_data=f"support:view:{ticket.ticket_ref}",
                    )
                ],
                [InlineKeyboardButton("🔙 الرئيسية", callback_data="shop:main")],
            ]
            await update.message.reply_text(
                f"✅ *تم فتح التذكرة*\n\n"
                f"رقم التذكرة: `{ticket.ticket_ref}`\n"
                f"سيتم الرد عليك قريباً.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.exception("ticket_creation_failed", error=type(exc).__name__)
            await update.message.reply_text("❌ تعذر فتح التذكرة حالياً. حاول مرة أخرى لاحقاً.")
        return

    if state == "ticket_reply":
        ticket_ref = context.user_data.pop("replying_to_ticket", "")
        context.user_data.pop("shop_state", None)

        if not ticket_ref:
            return

        try:
            await reply_to_ticket(ticket_ref, update.message.text.strip(), user.id, is_admin=False)
            keyboard = [
                [
                    InlineKeyboardButton(
                        "📋 عرض التذكرة",
                        callback_data=f"support:view:{ticket_ref}",
                    )
                ]
            ]
            await update.message.reply_text(
                "✅ تم إرسال ردك بنجاح.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as exc:
            logger.exception("ticket_reply_failed", error=type(exc).__name__)
            await update.message.reply_text("❌ تعذر إرسال الرد حالياً. حاول مرة أخرى لاحقاً.")
