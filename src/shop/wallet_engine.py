"""
Wallet Engine — Double-entry ledger, deposits, anti-fraud checks.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from src.db.session import db_session
from src.shop.models import (
    ShopUser,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_DAILY_DEPOSIT = 10000.0
MIN_DEPOSIT = 1.0
MAX_SINGLE_DEPOSIT = 5000.0


def _generate_tx_ref() -> str:
    return "DEP-" + secrets.token_hex(10).upper()


_ZERO_DECIMAL_CURRENCIES = {
    "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW",
    "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
}
_THREE_DECIMAL_CURRENCIES = {"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"}


def currency_minor_units(amount: float, currency: str) -> int:
    decimals = 0 if currency in _ZERO_DECIMAL_CURRENCIES else 3 if currency in _THREE_DECIMAL_CURRENCIES else 2
    return int(round(amount * (10**decimals)))


class WalletError(Exception):
    pass


async def create_deposit_intent(
    telegram_id: int,
    amount: float,
    currency: str = "USD",
    description: str = "إيداع رصيد",
    metadata: dict | None = None,
) -> Transaction:
    currency = currency.strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise WalletError("عملة الدفع غير صالحة")
    if amount < MIN_DEPOSIT:
        raise WalletError(f"الحد الأدنى للإيداع: {MIN_DEPOSIT}$")
    if amount > MAX_SINGLE_DEPOSIT:
        raise WalletError(f"الحد الأقصى لعملية واحدة: {MAX_SINGLE_DEPOSIT}$")

    async with db_session() as session:
        result = await session.execute(
            select(ShopUser).where(ShopUser.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise WalletError("المستخدم غير موجود")
        if user.is_banned:
            raise WalletError("الحساب موقوف")

        daily_sum = await _get_daily_deposit_sum(user.id, session)
        if daily_sum + amount > MAX_DAILY_DEPOSIT:
            raise WalletError(f"تجاوزت الحد اليومي ({MAX_DAILY_DEPOSIT}$)")

        tx = Transaction(
            ref=_generate_tx_ref(),
            user_id=user.id,
            tx_type=TransactionType.DEPOSIT,
            amount=amount,
            balance_before=user.balance,
            balance_after=user.balance,
            status=TransactionStatus.PENDING,
            description=description,
            extra_data={**(metadata or {}), "payment_currency": currency},
        )
        session.add(tx)
        logger.info(
            "wallet_deposit_intent_created",
            telegram_id=telegram_id,
            amount=amount,
            transaction_ref=tx.ref,
        )
        return tx


async def cancel_deposit_intent(transaction_ref: str, reason: str) -> None:
    async with db_session() as session:
        result = await session.execute(
            select(Transaction).where(Transaction.ref == transaction_ref)
        )
        tx = result.scalar_one_or_none()
        if tx and tx.status == TransactionStatus.PENDING:
            tx.status = TransactionStatus.FAILED
            tx.description = f"{tx.description or ''} — {reason}".strip()


async def validate_deposit_payment(
    payload: str,
    telegram_id: int,
    currency: str,
    total_amount_minor: int,
) -> None:
    if not payload.startswith("wallet:"):
        raise WalletError("حمولة الدفع غير صالحة")
    transaction_ref = payload.removeprefix("wallet:")
    async with db_session() as session:
        result = await session.execute(
            select(Transaction)
            .options(selectinload(Transaction.user))
            .where(Transaction.ref == transaction_ref)
        )
        tx = result.scalar_one_or_none()
        if not tx or tx.tx_type != TransactionType.DEPOSIT:
            raise WalletError("عملية الإيداع غير موجودة")
        if not tx.user or tx.user.telegram_id != telegram_id:
            raise WalletError("المستخدم لا يطابق عملية الإيداع")
        if tx.status != TransactionStatus.PENDING:
            raise WalletError("عملية الإيداع غير قابلة للتأكيد")
        expected_currency = (tx.extra_data or {}).get("payment_currency", "USD").upper()
        if currency.upper() != expected_currency:
            raise WalletError("عملة الدفع لا تطابق الفاتورة")
        if total_amount_minor != currency_minor_units(tx.amount, expected_currency):
            raise WalletError("قيمة الدفع لا تطابق الفاتورة")


async def confirm_deposit_payment(
    payload: str,
    telegram_id: int,
    currency: str,
    total_amount_minor: int,
    payment_charge_id: str,
    provider_payment_charge_id: str | None = None,
) -> Transaction:
    if not payload.startswith("wallet:"):
        raise WalletError("حمولة الدفع غير صالحة")
    transaction_ref = payload.removeprefix("wallet:")
    async with db_session() as session:
        result = await session.execute(
            select(Transaction)
            .options(selectinload(Transaction.user))
            .where(Transaction.ref == transaction_ref)
            .with_for_update()
        )
        tx = result.scalar_one_or_none()
        if not tx or tx.tx_type != TransactionType.DEPOSIT:
            raise WalletError("عملية الإيداع غير موجودة")
        if not tx.user or tx.user.telegram_id != telegram_id:
            raise WalletError("المستخدم لا يطابق عملية الإيداع")
        if tx.status == TransactionStatus.COMPLETED:
            return tx
        if tx.status != TransactionStatus.PENDING:
            raise WalletError("عملية الإيداع غير قابلة للتأكيد")

        expected_currency = (tx.extra_data or {}).get("payment_currency", "USD")
        if currency.upper() != expected_currency.upper():
            raise WalletError("عملة الدفع لا تطابق الفاتورة")
        if total_amount_minor != currency_minor_units(tx.amount, expected_currency.upper()):
            raise WalletError("قيمة الدفع لا تطابق الفاتورة")

        balance_before = tx.user.balance
        tx.user.balance += tx.amount
        tx.balance_before = balance_before
        tx.balance_after = tx.user.balance
        tx.status = TransactionStatus.COMPLETED
        tx.extra_data = {
            **(tx.extra_data or {}),
            "telegram_payment_charge_id": payment_charge_id,
            "provider_payment_charge_id": provider_payment_charge_id,
        }
        logger.info(
            "wallet_deposit_confirmed",
            telegram_id=telegram_id,
            amount=tx.amount,
            transaction_ref=tx.ref,
        )
        return tx


# Backward-compatible internal API: direct user deposit is deliberately removed.
async def deposit(*args, **kwargs):
    raise WalletError("الإيداع المباشر معطل؛ استخدم Telegram Payments invoice")


async def admin_adjust_balance(
    telegram_id: int,
    amount: float,
    description: str = "إضافة رصيد من الإدارة",
) -> Transaction:
    """Apply an explicit positive administrative adjustment, not a user deposit."""
    if amount <= 0:
        raise WalletError("قيمة التعديل الإداري يجب أن تكون موجبة")
    async with db_session() as session:
        result = await session.execute(
            select(ShopUser).where(ShopUser.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise WalletError("المستخدم غير موجود")
        balance_before = user.balance
        user.balance += amount
        tx = Transaction(
            ref="ADJ-" + secrets.token_hex(10).upper(),
            user_id=user.id,
            tx_type=TransactionType.ADJUSTMENT,
            amount=amount,
            balance_before=balance_before,
            balance_after=user.balance,
            status=TransactionStatus.COMPLETED,
            description=description,
        )
        session.add(tx)
        return tx


async def add_bonus(
    telegram_id: int,
    amount: float,
    description: str = "مكافأة",
) -> Transaction:
    async with db_session() as session:
        result = await session.execute(
            select(ShopUser).where(ShopUser.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise WalletError("المستخدم غير موجود")

        balance_before = user.balance
        user.balance += amount

        tx = Transaction(
            ref="BON-" + secrets.token_hex(8).upper(),
            user_id=user.id,
            tx_type=TransactionType.BONUS,
            amount=amount,
            balance_before=balance_before,
            balance_after=user.balance,
            status=TransactionStatus.COMPLETED,
            description=description,
        )
        session.add(tx)
        return tx


async def get_balance(telegram_id: int) -> tuple[float, float]:
    """Returns (balance, locked_balance)."""
    async with db_session() as session:
        result = await session.execute(
            select(ShopUser.balance, ShopUser.locked_balance)
            .where(ShopUser.telegram_id == telegram_id)
        )
        row = result.one_or_none()
        if not row:
            return 0.0, 0.0
        return row[0], row[1]


async def get_transactions(
    user_id: int,
    limit: int = 10,
    tx_type: TransactionType | None = None,
) -> list[Transaction]:
    async with db_session() as session:
        q = (
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.created_at.desc())
            .limit(limit)
        )
        if tx_type:
            q = q.where(Transaction.tx_type == tx_type)
        result = await session.execute(q)
        return list(result.scalars().all())


async def _get_daily_deposit_sum(user_id: int, session) -> float:
    today_start = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0.0))
        .where(
            Transaction.user_id == user_id,
            Transaction.tx_type == TransactionType.DEPOSIT,
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.created_at >= today_start,
        )
    )
    return float(result.scalar_one())


def format_transactions_text(transactions: list[Transaction]) -> str:
    if not transactions:
        return "📭 لا توجد معاملات بعد."

    type_emoji = {
        TransactionType.DEPOSIT: "📥",
        TransactionType.PURCHASE: "🛒",
        TransactionType.REFUND: "↩️",
        TransactionType.COMMISSION: "💎",
        TransactionType.BONUS: "🎁",
        TransactionType.ADJUSTMENT: "⚙️",
    }
    type_ar = {
        TransactionType.DEPOSIT: "إيداع",
        TransactionType.PURCHASE: "شراء",
        TransactionType.REFUND: "استرداد",
        TransactionType.COMMISSION: "عمولة",
        TransactionType.BONUS: "مكافأة",
        TransactionType.ADJUSTMENT: "تعديل",
    }

    lines = ["💳 *آخر المعاملات*\n"]
    for tx in transactions:
        emoji = type_emoji.get(tx.tx_type, "💰")
        type_text = type_ar.get(tx.tx_type, tx.tx_type)
        sign = "+" if tx.amount > 0 else ""
        ts = tx.created_at.strftime("%d/%m %H:%M") if tx.created_at else ""
        lines.append(f"{emoji} {type_text}: {sign}{tx.amount:.2f}$ | `{ts}`")

    return "\n".join(lines)
