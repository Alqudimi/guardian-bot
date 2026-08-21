"""Wallet UI and verified Telegram Payments flow."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.ext import ContextTypes

from config.settings import get_settings
from src.shop.user_engine import get_shop_user
from src.shop.wallet_engine import (
    WalletError,
    cancel_deposit_intent,
    confirm_deposit_payment,
    create_deposit_intent,
    currency_minor_units,
    format_transactions_text,
    get_balance,
    get_transactions,
    validate_deposit_payment,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEPOSIT_AMOUNTS = [5, 10, 25, 50, 100]


async def show_wallet(query, context) -> None:
    user = query.from_user
    balance, locked = await get_balance(user.id)

    keyboard = [
        [
            InlineKeyboardButton("📥 إيداع رصيد", callback_data="wallet:deposit"),
            InlineKeyboardButton("📜 السجل", callback_data="wallet:history"),
        ],
        [InlineKeyboardButton("🔙 العودة", callback_data="shop:main")],
    ]

    text = (
        f"💰 *محفظتي*\n\n"
        f"الرصيد المتاح: `{balance:.2f}$`\n"
        f"الرصيد المحجوز: `{locked:.2f}$`\n"
        f"الإجمالي: `{(balance + locked):.2f}$`"
    )

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


def _payment_configured() -> bool:
    return bool(get_settings().payment_provider_token.strip())


async def handle_wallet_callback(query, context) -> None:
    data = query.data.split(":")
    action = data[1] if len(data) > 1 else ""

    if action == "deposit":
        await _show_deposit_menu(query, context)
    elif action == "amount":
        try:
            amount = float(data[2]) if len(data) > 2 else 0
        except ValueError:
            await query.answer("❌ مبلغ غير صالح", show_alert=True)
            return
        await _process_deposit(query, context, amount)
    elif action == "custom":
        if not _payment_configured():
            await query.answer("⚠️ الدفع غير مهيأ حالياً", show_alert=True)
            return
        context.user_data["shop_state"] = "custom_deposit"
        keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="wallet:deposit")]]
        await query.edit_message_text(
            "💰 أدخل المبلغ المراد دفعه (بالدولار):",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    elif action == "history":
        await _show_history(query, context)


async def _show_deposit_menu(query, context) -> None:
    if not _payment_configured():
        await query.edit_message_text(
            "⚠️ *الإيداع غير متاح حالياً*\n\n"
            "لم يتم إعداد مزود دفع Telegram. لم يتم إضافة أي رصيد تلقائياً، "
            "ولا يمكن متابعة عملية وهمية.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 العودة", callback_data="shop:wallet")]]
            ),
            parse_mode="Markdown",
        )
        return

    keyboard = []
    row = []
    for i, amount in enumerate(DEPOSIT_AMOUNTS):
        row.append(InlineKeyboardButton(f"${amount}", callback_data=f"wallet:amount:{amount}"))
        if len(row) == 3 or i == len(DEPOSIT_AMOUNTS) - 1:
            keyboard.append(row)
            row = []

    keyboard.append([InlineKeyboardButton("✏️ مبلغ مخصص", callback_data="wallet:custom")])
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="shop:wallet")])

    await query.edit_message_text(
        "📥 *إيداع رصيد عبر Telegram Payments*\n\n"
        "اختر المبلغ أو أدخل مبلغاً مخصصاً. لن يُضاف الرصيد إلا بعد تأكيد الدفع الناجح من Telegram.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def _send_deposit_invoice(bot, chat_id: int, telegram_id: int, amount: float):
    settings = get_settings()
    provider_token = settings.payment_provider_token.strip()
    if not provider_token:
        raise WalletError("مزود الدفع غير مهيأ")

    tx = await create_deposit_intent(
        telegram_id=telegram_id,
        amount=amount,
        currency=settings.payment_currency,
        description=f"إيداع رصيد عبر Telegram Payments — {amount:.2f} {settings.payment_currency}",
    )
    payload = f"wallet:{tx.ref}"
    try:
        await bot.send_invoice(
            chat_id=chat_id,
            title="إيداع رصيد Guardian Shop",
            description=(
                f"إضافة {amount:.2f} {settings.payment_currency} إلى رصيدك. "
                "يتم الاعتماد بعد successful_payment فقط."
            ),
            payload=payload,
            provider_token=provider_token,
            currency=settings.payment_currency,
            prices=[
                LabeledPrice(
                    label="Guardian Shop balance",
                    amount=currency_minor_units(amount, settings.payment_currency),
                )
            ],
            start_parameter=f"deposit-{tx.ref}",
        )
    except Exception as exc:
        await cancel_deposit_intent(tx.ref, "فشل إرسال فاتورة Telegram")
        logger.error("deposit_invoice_send_failed", error=type(exc).__name__)
        raise WalletError("تعذر إنشاء فاتورة الدفع") from exc
    return tx


async def _process_deposit(query, context, amount: float) -> None:
    if not _payment_configured():
        await query.answer("⚠️ الدفع غير مهيأ حالياً؛ لم يتغير رصيدك", show_alert=True)
        return
    try:
        tx = await _send_deposit_invoice(
            context.bot,
            query.message.chat_id,
            query.from_user.id,
            amount,
        )
        await query.answer("✅ تم إرسال فاتورة الدفع. لن يتغير الرصيد قبل نجاح الدفع.", show_alert=True)
        logger.info("deposit_invoice_created", transaction_ref=tx.ref, user_id=query.from_user.id)
    except WalletError as exc:
        await query.answer(str(exc), show_alert=True)


async def _show_history(query, context) -> None:
    user = query.from_user
    shop_user = await get_shop_user(user.id)
    if not shop_user:
        await query.answer("❌ لا يوجد حساب", show_alert=True)
        return

    transactions = await get_transactions(shop_user.id, limit=10)
    text = format_transactions_text(transactions)

    keyboard = [[InlineKeyboardButton("🔙 المحفظة", callback_data="shop:wallet")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def handle_custom_deposit_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create a real Telegram invoice for a custom deposit amount."""
    if context.user_data.get("shop_state") != "custom_deposit":
        return

    context.user_data.pop("shop_state", None)
    if not _payment_configured():
        await update.message.reply_text("⚠️ الدفع غير مهيأ حالياً؛ لم يتغير رصيدك.")
        return

    user = update.effective_user
    try:
        amount = float(update.message.text.strip().replace("$", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ مبلغ غير صالح. أدخل رقماً مثل: 25")
        return

    try:
        tx = await _send_deposit_invoice(
            context.bot,
            update.effective_chat.id,
            user.id,
            amount,
        )
        await update.message.reply_text(
            f"✅ تم إنشاء فاتورة الدفع للمعاملة `{tx.ref}`.\n"
            "لن يُضاف الرصيد إلا بعد تأكيد Telegram للدفع.",
            parse_mode="Markdown",
        )
    except WalletError as exc:
        await update.message.reply_text(f"❌ {exc}")


async def handle_pre_checkout_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve a pre-checkout query only when it matches a pending intent."""
    query = update.pre_checkout_query
    if not query:
        return
    try:
        await validate_deposit_payment(
            payload=query.invoice_payload,
            telegram_id=query.from_user.id,
            currency=query.currency,
            total_amount_minor=query.total_amount,
        )
    except WalletError as exc:
        await query.answer(ok=False, error_message=str(exc)[:200])
    else:
        await query.answer(ok=True)


async def handle_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Credit balance exactly once after Telegram sends successful_payment."""
    message = update.effective_message
    payment = message.successful_payment if message else None
    user = update.effective_user
    if not payment or not user:
        return

    try:
        tx = await confirm_deposit_payment(
            payload=payment.invoice_payload,
            telegram_id=user.id,
            currency=payment.currency,
            total_amount_minor=payment.total_amount,
            payment_charge_id=payment.telegram_payment_charge_id,
            provider_payment_charge_id=payment.provider_payment_charge_id,
        )
        balance, _ = await get_balance(user.id)
    except WalletError as exc:
        logger.error("successful_payment_credit_failed", user_id=user.id, error=str(exc))
        await message.reply_text(
            "⚠️ تم استلام إشعار الدفع لكن تعذر اعتماد الرصيد آلياً. "
            "احتفظ بإيصال Telegram وتواصل مع الدعم.",
        )
        return

    await message.reply_text(
        f"✅ تم اعتماد الدفع وإضافة `{tx.amount:.2f} {payment.currency}` إلى رصيدك.\n"
        f"الرصيد الجديد: `{balance:.2f}`",
        parse_mode="Markdown",
    )
