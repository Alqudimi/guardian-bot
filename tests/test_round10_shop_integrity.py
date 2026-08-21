from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from src.db.models import Base


class _StablePricingDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        current = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
        return current.astimezone(tz) if tz else current.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def daytime_service_pricing(monkeypatch):
    monkeypatch.setattr("src.shop.service_engine.datetime", _StablePricingDateTime)


from src.shop.models import (
    Coupon,
    CouponUsage,
    Order,
    OrderStatus,
    Service,
    ServiceType,
    ShopUser,
    UserLevel,
    VIPTier,
)


@pytest.fixture
async def shop_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def isolated_session():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    import src.db.session as db_module

    monkeypatch.setattr(db_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr("src.shop.order_engine.db_session", isolated_session)
    monkeypatch.setattr("src.shop.coupon_engine.db_session", isolated_session)
    yield factory
    await engine.dispose()


async def _seed_user_and_service(factory, *, price: float = 10.0):
    async with factory() as session:
        user = ShopUser(
            telegram_id=42,
            username="buyer",
            first_name="Buyer",
            balance=100.0,
            locked_balance=0.0,
            level=UserLevel.BRONZE,
            vip_tier=VIPTier.BASIC,
            referral_code="buyer-42",
        )
        service = Service(
            title="Manual service",
            title_ar="خدمة يدوية",
            base_price=price,
            service_type=ServiceType.MANUAL,
            min_order=1,
            stock=10,
            is_active=True,
        )
        session.add_all([user, service])
        await session.commit()
        await session.refresh(user)
        await session.refresh(service)
        return user, service


@pytest.mark.asyncio
async def test_create_order_uses_authoritative_service_price(shop_db):
    from src.shop.order_engine import create_order

    user, service = await _seed_user_and_service(shop_db, price=12.5)
    order = await create_order(
        user,
        [{"service_id": service.id, "quantity": 1, "unit_price": 0.01}],
    )

    assert order.total_amount == 11.88
    async with shop_db() as session:
        saved = await session.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == order.id)
        )
        saved_order = saved.scalar_one()
        assert saved_order.items[0].unit_price == 11.88
        assert saved_order.items[0].total_price == 11.88


@pytest.mark.asyncio
async def test_coupon_is_consumed_only_after_successful_payment(shop_db):
    from src.shop.order_engine import create_order, pay_order

    user, service = await _seed_user_and_service(shop_db, price=20.0)
    async with shop_db() as session:
        coupon = Coupon(
            code="TENOFF",
            discount_percent=10.0,
            per_user_limit=1,
            usage_limit=10,
            min_order_amount=1.0,
            is_active=True,
        )
        session.add(coupon)
        await session.commit()
        await session.refresh(coupon)
        coupon_id = coupon.id

    order = await create_order(
        user,
        [{"service_id": service.id, "quantity": 1, "unit_price": 20.0}],
        coupon_id=coupon_id,
    )
    async with shop_db() as session:
        saved_coupon = await session.get(Coupon, coupon_id)
        assert saved_coupon.usage_count == 0

    paid = await pay_order(order.id, telegram_id=42)
    assert paid.status is OrderStatus.PROCESSING
    assert paid.total_amount == 17.1
    async with shop_db() as session:
        saved_coupon = await session.get(Coupon, coupon_id)
        usages = await session.execute(
            select(CouponUsage).where(CouponUsage.coupon_id == coupon_id)
        )
        assert saved_coupon.usage_count == 1
        assert len(usages.scalars().all()) == 1


@pytest.mark.asyncio
async def test_payment_rejects_stale_price_and_releases_lock(shop_db):
    from src.shop.order_engine import OrderValidationError, create_order, pay_order

    user, service = await _seed_user_and_service(shop_db, price=10.0)
    order = await create_order(
        user,
        [{"service_id": service.id, "quantity": 1, "unit_price": 10.0}],
    )
    async with shop_db() as session:
        current = await session.get(Service, service.id)
        current.base_price = 20.0
        await session.commit()

    with pytest.raises(OrderValidationError, match="تغير سعر الخدمة"):
        await pay_order(order.id, telegram_id=42)

    async with shop_db() as session:
        saved_order = await session.get(Order, order.id)
        saved_user = await session.get(ShopUser, user.id)
        assert saved_order.status is OrderStatus.CANCELLED
        assert saved_user.locked_balance == 0.0
        assert saved_user.balance == 100.0


@pytest.mark.asyncio
async def test_refund_requires_owner_and_is_idempotent(shop_db):
    from src.shop.order_engine import OrderValidationError, create_order, pay_order, refund_order

    user, service = await _seed_user_and_service(shop_db, price=10.0)
    order = await create_order(
        user,
        [{"service_id": service.id, "quantity": 1, "unit_price": 10.0}],
    )
    await pay_order(order.id, telegram_id=42)

    with pytest.raises(OrderValidationError, match="لا يملك"):
        await refund_order(order.id, telegram_id=99)

    refunded = await refund_order(order.id, telegram_id=42)
    assert refunded.status is OrderStatus.REFUNDED
    with pytest.raises(OrderValidationError, match="مسبقاً"):
        await refund_order(order.id, telegram_id=42)

    async with shop_db() as session:
        saved_user = await session.get(ShopUser, user.id)
        assert saved_user.balance == 100.0


@pytest.mark.asyncio
async def test_terminal_failure_refunds_paid_order_once(shop_db):
    from src.shop.order_engine import OrderValidationError, create_order, fail_order, pay_order

    user, service = await _seed_user_and_service(shop_db, price=10.0)
    order = await create_order(
        user,
        [{"service_id": service.id, "quantity": 1, "unit_price": 10.0}],
    )
    await pay_order(order.id, telegram_id=42)
    async with shop_db() as session:
        saved_order = await session.get(Order, order.id)
        saved_order.max_retries = 0
        await session.commit()

    failed = await fail_order(order.id, reason="provider failed")
    assert failed.status is OrderStatus.FAILED
    with pytest.raises(OrderValidationError, match="مسبقاً"):
        await fail_order(order.id, reason="retry")

    async with shop_db() as session:
        saved_user = await session.get(ShopUser, user.id)
        assert saved_user.balance == 100.0
        assert saved_user.total_orders == 0
