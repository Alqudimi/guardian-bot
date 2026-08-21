"""
AI Engine — Personalization, recommendations, upsell, fraud detection.
Uses lightweight heuristics (no external API required).
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from src.db.session import db_session
from src.shop.models import (
    Order,
    OrderItem,
    Service,
    ShopUser,
    Transaction,
    TransactionType,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Personalization — Service Recommendations
# ─────────────────────────────────────────────────────────────────────────────

async def get_recommendations(
    user: ShopUser,
    limit: int = 3,
    exclude_service_ids: list[int] | None = None,
) -> list[Service]:
    """Return recommended services based on user history."""
    async with db_session() as session:
        ordered_result = await session.execute(
            select(OrderItem.service_id, func.count(OrderItem.id).label("cnt"))
            .join(Order, OrderItem.order_id == Order.id)
            .where(Order.user_id == user.id)
            .group_by(OrderItem.service_id)
            .order_by(func.count(OrderItem.id).desc())
            .limit(10)
        )
        ordered_service_ids = [row[0] for row in ordered_result.all()]

        if ordered_service_ids:
            cat_result = await session.execute(
                select(Service.category_id)
                .where(Service.id.in_(ordered_service_ids))
            )
            preferred_cats = [row[0] for row in cat_result.all() if row[0]]
            cat_counter = Counter(preferred_cats)
            top_cats = [cat for cat, _ in cat_counter.most_common(3)]

            q = (
                select(Service)
                .where(
                    Service.is_active == True,
                    Service.category_id.in_(top_cats),
                    ~Service.id.in_(ordered_service_ids),
                )
                .order_by(Service.total_orders.desc())
                .limit(limit)
            )
        else:
            q = (
                select(Service)
                .where(Service.is_active == True, Service.is_featured == True)
                .order_by(Service.total_orders.desc())
                .limit(limit)
            )

        if exclude_service_ids:
            q = q.where(~Service.id.in_(exclude_service_ids))

        result = await session.execute(q)
        return list(result.scalars().all())


async def get_upsell_services(service_id: int, limit: int = 2) -> list[Service]:
    """Services frequently bought with the given service (co-purchase)."""
    async with db_session() as session:
        co_order_result = await session.execute(
            select(OrderItem.service_id, func.count(OrderItem.id).label("cnt"))
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                Order.id.in_(
                    select(OrderItem.order_id).where(OrderItem.service_id == service_id)
                ),
                OrderItem.service_id != service_id,
            )
            .group_by(OrderItem.service_id)
            .order_by(func.count(OrderItem.id).desc())
            .limit(limit)
        )
        co_ids = [row[0] for row in co_order_result.all()]
        if not co_ids:
            result = await session.execute(
                select(Service)
                .where(Service.is_active == True, Service.id != service_id, Service.is_featured == True)
                .order_by(Service.total_orders.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

        result = await session.execute(
            select(Service).where(Service.id.in_(co_ids), Service.is_active == True)
        )
        return list(result.scalars().all())


# ─────────────────────────────────────────────────────────────────────────────
# Fraud Detection
# ─────────────────────────────────────────────────────────────────────────────

async def calculate_fraud_score(telegram_id: int) -> tuple[float, list[str]]:
    """
    Returns (fraud_score 0-100, list of flags).
    Score > 70 = high risk.
    """
    flags: list[str] = []
    score = 0.0

    async with db_session() as session:
        user_result = await session.execute(
            select(ShopUser).where(ShopUser.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return 100.0, ["user_not_found"]

        account_age = (datetime.now(tz=UTC) - user.created_at).days
        if account_age < 1:
            score += 30
            flags.append("new_account")
        elif account_age < 7:
            score += 10
            flags.append("young_account")

        week_ago = datetime.now(tz=UTC) - timedelta(days=7)
        recent_deposits = await session.execute(
            select(func.count(Transaction.id), func.sum(Transaction.amount))
            .where(
                Transaction.user_id == user.id,
                Transaction.tx_type == TransactionType.DEPOSIT,
                Transaction.created_at >= week_ago,
            )
        )
        dep_row = recent_deposits.one()
        dep_count, dep_sum = dep_row[0] or 0, float(dep_row[1] or 0)

        if dep_count > 10:
            score += 20
            flags.append("high_deposit_frequency")
        if dep_sum > 5000:
            score += 15
            flags.append("high_deposit_volume")

        recent_orders = await session.execute(
            select(func.count(Order.id))
            .where(Order.user_id == user.id, Order.created_at >= week_ago)
        )
        order_count = recent_orders.scalar_one() or 0
        if order_count > 20:
            score += 20
            flags.append("high_order_frequency")

        failed_orders = await session.execute(
            select(func.count(Order.id))
            .where(
                Order.user_id == user.id,
                Order.status == "failed",
                Order.created_at >= week_ago,
            )
        )
        failed_count = failed_orders.scalar_one() or 0
        if failed_count > 5:
            score += 15
            flags.append("high_failure_rate")

    return min(score, 100.0), flags


async def get_revenue_insights(days: int = 30) -> dict:
    """Basic revenue analytics for admin dashboard."""
    since = datetime.now(tz=UTC) - timedelta(days=days)
    async with db_session() as session:
        revenue = await session.execute(
            select(func.coalesce(func.sum(Order.total_amount), 0.0))
            .where(Order.status == "completed", Order.created_at >= since)
        )
        order_count = await session.execute(
            select(func.count(Order.id)).where(Order.created_at >= since)
        )
        user_count = await session.execute(
            select(func.count(ShopUser.id)).where(ShopUser.created_at >= since)
        )
        completed = await session.execute(
            select(func.count(Order.id))
            .where(Order.status == "completed", Order.created_at >= since)
        )
        total_orders = order_count.scalar_one() or 1
        completed_orders = completed.scalar_one() or 0

        return {
            "revenue": float(revenue.scalar_one()),
            "total_orders": total_orders,
            "completed_orders": completed_orders,
            "new_users": user_count.scalar_one() or 0,
            "conversion_rate": round(completed_orders / total_orders * 100, 1),
        }
