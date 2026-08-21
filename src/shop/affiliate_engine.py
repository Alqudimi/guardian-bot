"""
Affiliate Engine — Referral tracking, commission calculation, anti-fraud.
"""
from __future__ import annotations

from sqlalchemy import func, select

from src.db.session import db_session
from src.shop.models import (
    AffiliateCommission,
    AffiliateLink,
    ShopUser,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

FIRST_PURCHASE_COMMISSION_PCT = 5.0
LIFETIME_COMMISSION_PCT = 2.0
VIP_REFERRER_BONUS_PCT = 1.0


async def register_referral(referred_telegram_id: int, referrer_code: str) -> bool:
    """Link a new user to their referrer. Returns True if registered."""
    async with db_session() as session:
        referrer_result = await session.execute(
            select(ShopUser).where(ShopUser.referral_code == referrer_code)
        )
        referrer = referrer_result.scalar_one_or_none()
        if not referrer:
            return False

        referred_result = await session.execute(
            select(ShopUser).where(ShopUser.telegram_id == referred_telegram_id)
        )
        referred = referred_result.scalar_one_or_none()
        if not referred:
            return False

        if referred.telegram_id == referrer.telegram_id:
            return False

        existing = await session.execute(
            select(AffiliateLink).where(AffiliateLink.referred_id == referred.id)
        )
        if existing.scalar_one_or_none():
            return False

        link = AffiliateLink(
            referrer_id=referrer.id,
            referred_id=referred.id,
        )
        session.add(link)

        referred.referred_by = referrer.telegram_id
        logger.info(
            "referral_registered",
            referrer=referrer.telegram_id,
            referred=referred_telegram_id,
        )
        return True


async def process_purchase_commission(
    order_id: int,
    buyer_telegram_id: int,
    order_amount: float,
    is_first_purchase: bool = False,
) -> float:
    """Calculate and credit affiliate commission. Returns commission amount."""
    async with db_session() as session:
        buyer_result = await session.execute(
            select(ShopUser).where(ShopUser.telegram_id == buyer_telegram_id)
        )
        buyer = buyer_result.scalar_one_or_none()
        if not buyer or not buyer.referred_by:
            return 0.0

        link_result = await session.execute(
            select(AffiliateLink).where(AffiliateLink.referred_id == buyer.id)
        )
        link = link_result.scalar_one_or_none()
        if not link or link.is_flagged:
            return 0.0

        referrer_result = await session.execute(
            select(ShopUser).where(ShopUser.id == link.referrer_id)
        )
        referrer = referrer_result.scalar_one_or_none()
        if not referrer:
            return 0.0

        pct = FIRST_PURCHASE_COMMISSION_PCT if is_first_purchase else LIFETIME_COMMISSION_PCT
        commission = round(order_amount * pct / 100, 2)

        if commission <= 0:
            return 0.0

        referrer.balance += commission
        link.total_commission_earned += commission

        tx_ref = "COM-" + __import__("secrets").token_hex(8).upper()
        tx = Transaction(
            ref=tx_ref,
            user_id=referrer.id,
            tx_type=TransactionType.COMMISSION,
            amount=commission,
            balance_before=referrer.balance - commission,
            balance_after=referrer.balance,
            status=TransactionStatus.COMPLETED,
            description=f"عمولة إحالة - طلب #{order_id}",
        )
        session.add(tx)

        commission_record = AffiliateCommission(
            referrer_id=referrer.id,
            referred_id=buyer.id,
            order_id=order_id,
            commission_amount=commission,
            commission_pct=pct,
            is_first_purchase=is_first_purchase,
            status="completed",
        )
        session.add(commission_record)

        logger.info(
            "commission_credited",
            referrer=referrer.telegram_id,
            commission=commission,
            order_id=order_id,
        )
        return commission


async def get_referral_stats(telegram_id: int) -> dict:
    async with db_session() as session:
        user_result = await session.execute(
            select(ShopUser).where(ShopUser.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return {}

        referred_count = await session.execute(
            select(func.count(AffiliateLink.id)).where(AffiliateLink.referrer_id == user.id)
        )
        total_commissions = await session.execute(
            select(func.coalesce(func.sum(AffiliateCommission.commission_amount), 0.0))
            .where(AffiliateCommission.referrer_id == user.id, AffiliateCommission.status == "completed")
        )

        return {
            "referral_code": user.referral_code,
            "referred_count": referred_count.scalar_one(),
            "total_commissions": float(total_commissions.scalar_one()),
        }


async def flag_suspicious_affiliate(link_id: int, reason: str) -> None:
    async with db_session() as session:
        result = await session.execute(select(AffiliateLink).where(AffiliateLink.id == link_id))
        link = result.scalar_one_or_none()
        if link:
            link.is_flagged = True
            link.flag_reason = reason
            logger.warning("affiliate_flagged", link_id=link_id, reason=reason)
