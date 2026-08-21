"""
Coupon Engine — Advanced coupon rules, auto-apply, anti-stacking.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import db_session
from src.shop.models import Coupon, CouponUsage, ShopUser
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CouponError(Exception):
    pass


async def _validate_coupon_record(
    session: AsyncSession,
    coupon: Coupon,
    user: ShopUser,
    order_amount: float,
    service_ids: list[int] | None = None,
) -> Coupon:
    """Validate one coupon using the caller's transaction and current user state."""
    now = datetime.now(tz=UTC)
    if not coupon.is_active:
        raise CouponError("الكوبون غير صالح أو غير نشط")
    if coupon.valid_from and now < coupon.valid_from:
        raise CouponError("الكوبون لم يبدأ بعد")
    if coupon.valid_until and now > coupon.valid_until:
        raise CouponError("الكوبون منتهي الصلاحية")
    if coupon.usage_limit is not None and coupon.usage_count >= coupon.usage_limit:
        raise CouponError("تم استنفاد الكوبون")
    if order_amount < coupon.min_order_amount:
        raise CouponError(f"الحد الأدنى للطلب: {coupon.min_order_amount:.2f}$")
    if coupon.allowed_users and user.telegram_id not in coupon.allowed_users:
        raise CouponError("هذا الكوبون غير مخصص لك")
    if coupon.allowed_levels and user.level not in coupon.allowed_levels:
        raise CouponError(f"هذا الكوبون للمستوى {coupon.allowed_levels} فقط")
    if coupon.allowed_services and not service_ids:
        raise CouponError("هذا الكوبون يتطلب خدمة مؤهلة")
    if coupon.allowed_services and not any(
        sid in coupon.allowed_services for sid in service_ids or []
    ):
        raise CouponError("هذا الكوبون لا ينطبق على الخدمات المختارة")

    result = await session.execute(
        select(func.count(CouponUsage.id)).where(
            CouponUsage.coupon_id == coupon.id,
            CouponUsage.user_id == user.id,
        )
    )
    if result.scalar_one() >= coupon.per_user_limit:
        raise CouponError("لقد استخدمت هذا الكوبون مسبقاً")
    return coupon


async def validate_coupon_for_session(
    session: AsyncSession,
    code: str,
    user: ShopUser,
    order_amount: float,
    service_ids: list[int] | None = None,
) -> Coupon:
    result = await session.execute(
        select(Coupon).where(Coupon.code == code.strip().upper())
    )
    coupon = result.scalar_one_or_none()
    if not coupon:
        raise CouponError("الكوبون غير صالح أو منتهي الصلاحية")
    return await _validate_coupon_record(session, coupon, user, order_amount, service_ids)


async def validate_coupon(
    code: str,
    user: ShopUser,
    order_amount: float,
    service_ids: list[int] | None = None,
) -> Coupon:
    async with db_session() as session:
        return await validate_coupon_for_session(
            session, code, user, order_amount, service_ids
        )


def calculate_discount(coupon: Coupon, order_amount: float) -> float:
    if coupon.discount_percent:
        discount = order_amount * (coupon.discount_percent / 100)
    elif coupon.discount_fixed:
        discount = coupon.discount_fixed
    else:
        return 0.0

    if coupon.max_discount:
        discount = min(discount, coupon.max_discount)

    return round(min(discount, order_amount), 2)


async def apply_coupon(
    coupon_id: int,
    shop_user_id: int,
    order_amount: float,
    session: AsyncSession,
) -> float:
    result = await session.execute(
        select(Coupon).where(Coupon.id == coupon_id).with_for_update()
    )
    coupon = result.scalar_one_or_none()
    if not coupon:
        return 0.0

    # Applying a discount is not consuming it. Consumption is recorded only
    # after the order is paid, in the same transaction as the balance mutation.
    return calculate_discount(coupon, order_amount)


async def record_coupon_usage(
    coupon_id: int,
    shop_user_id: int,
    order_id: int,
    discount_applied: float,
) -> None:
    async with db_session() as session:
        await record_coupon_usage_in_session(
            session, coupon_id, shop_user_id, order_id, discount_applied
        )


async def record_coupon_usage_in_session(
    session: AsyncSession,
    coupon_id: int,
    shop_user_id: int,
    order_id: int,
    discount_applied: float,
) -> None:
    session.add(
        CouponUsage(
            coupon_id=coupon_id,
            user_id=shop_user_id,
            order_id=order_id,
            discount_applied=discount_applied,
        )
    )


async def auto_apply_best_coupon(
    user: ShopUser,
    order_amount: float,
    service_ids: list[int] | None = None,
) -> tuple[Coupon | None, float]:
    """Find and apply the best coupon for a user automatically."""
    async with db_session() as session:
        now = datetime.now(tz=UTC)
        result = await session.execute(
            select(Coupon)
            .where(
                Coupon.is_active == True,
                Coupon.min_order_amount <= order_amount,
                (Coupon.valid_until == None) | (Coupon.valid_until > now),
                (Coupon.valid_from == None) | (Coupon.valid_from <= now),
                (Coupon.usage_limit == None) | (Coupon.usage_count < Coupon.usage_limit),
            )
        )
        coupons = list(result.scalars().all())

    best_coupon = None
    best_discount = 0.0

    for coupon in coupons:
        if coupon.allowed_users and user.telegram_id not in coupon.allowed_users:
            continue
        if coupon.allowed_levels and user.level not in coupon.allowed_levels:
            continue

        discount = calculate_discount(coupon, order_amount)
        if discount > best_discount:
            best_discount = discount
            best_coupon = coupon

    return best_coupon, best_discount


async def create_coupon(
    code: str,
    discount_percent: float | None = None,
    discount_fixed: float | None = None,
    max_discount: float | None = None,
    min_order_amount: float = 0.0,
    usage_limit: int | None = None,
    per_user_limit: int = 1,
    valid_until: datetime | None = None,
    description: str | None = None,
) -> Coupon:
    async with db_session() as session:
        coupon = Coupon(
            code=code.upper(),
            description=description,
            discount_percent=discount_percent,
            discount_fixed=discount_fixed,
            max_discount=max_discount,
            min_order_amount=min_order_amount,
            usage_limit=usage_limit,
            per_user_limit=per_user_limit,
            valid_until=valid_until,
        )
        session.add(coupon)
        await session.flush()
        logger.info("coupon_created", code=code)
        return coupon
