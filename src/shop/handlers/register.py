"""
Shop Handlers Registration — Plugs all shop handlers into the bot.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

from src.shop.handlers.admin_handler import (
    cmd_shop_addbalance,
    cmd_shop_addcat,
    cmd_shop_addcoupon,
    cmd_shop_addservice,
    cmd_shop_broadcast,
    cmd_shop_coupons,
    cmd_shop_dashboard,
    cmd_shop_order,
    cmd_shop_orders,
    cmd_shop_services,
    cmd_shop_ticket,
    cmd_shop_tickets,
    cmd_shop_user,
    handle_admin_order_callback,
    handle_admin_ticket_callback,
)
from src.shop.handlers.order_handler import (
    handle_coupon_message,
    handle_order_callback,
)
from src.shop.handlers.shop_handler import (
    cmd_shop,
    handle_shop_callback,
    handle_shop_search_message,
)
from src.shop.handlers.support_handler import (
    handle_support_callback,
    handle_support_message,
)
from src.shop.handlers.wallet_handler import (
    handle_custom_deposit_message,
    handle_pre_checkout_query,
    handle_successful_payment,
    handle_wallet_callback,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def _unified_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route all shop-related callback queries to the correct handler."""
    query = update.callback_query
    data = query.data

    if data.startswith("shop:"):
        await handle_shop_callback(update, context)
    elif data.startswith("order:"):
        await handle_order_callback(query, context)
    elif data.startswith("wallet:"):
        await handle_wallet_callback(query, context)
    elif data.startswith("support:"):
        await handle_support_callback(query, context)
    elif data.startswith("admin_order:"):
        await handle_admin_order_callback(update, context)
    elif data.startswith("admin_ticket:"):
        await handle_admin_ticket_callback(update, context)
    elif data == "shop:noop":
        await query.answer()


async def _shop_message_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route private messages to the appropriate shop input handler."""
    state = context.user_data.get("shop_state", "")
    if not state:
        return

    if state == "searching":
        await handle_shop_search_message(update, context)
    elif state.startswith("coupon_for_"):
        await handle_coupon_message(update, context)
    elif state == "custom_deposit":
        await handle_custom_deposit_message(update, context)
    elif state in ("ticket_subject", "ticket_message", "ticket_reply"):
        await handle_support_message(update, context)


def register_shop_handlers(app: Application) -> None:
    """Register all shop handlers with the bot application."""

    app.add_handler(CommandHandler("shop", cmd_shop))

    app.add_handler(
        CallbackQueryHandler(
            _unified_callback_router,
            pattern="^(shop:|order:|wallet:|support:|admin_order:|admin_ticket:)",
        ),
        group=1,
    )

    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            _shop_message_router,
        ),
        group=2,
    )

    app.add_handler(PreCheckoutQueryHandler(handle_pre_checkout_query), group=1)
    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.SUCCESSFUL_PAYMENT, handle_successful_payment),
        group=1,
    )

    shop_admin_commands = [
        ("shop_dashboard", cmd_shop_dashboard),
        ("shop_orders", cmd_shop_orders),
        ("shop_order", cmd_shop_order),
        ("shop_user", cmd_shop_user),
        ("shop_addbalance", cmd_shop_addbalance),
        ("shop_services", cmd_shop_services),
        ("shop_addservice", cmd_shop_addservice),
        ("shop_addcat", cmd_shop_addcat),
        ("shop_coupons", cmd_shop_coupons),
        ("shop_addcoupon", cmd_shop_addcoupon),
        ("shop_tickets", cmd_shop_tickets),
        ("shop_ticket", cmd_shop_ticket),
        ("shop_broadcast", cmd_shop_broadcast),
    ]
    for cmd, handler in shop_admin_commands:
        app.add_handler(CommandHandler(cmd, handler))

    logger.info(
        "shop_handlers_registered",
        commands=len(shop_admin_commands) + 1,
    )
