"""
Service Engine — Catalog management and dynamic pricing.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from src.db.session import db_session
from src.shop.models import Service, ServiceCategory, ShopUser, UserLevel, VIPTier
from src.shop.user_engine import get_user_discount
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Dynamic Pricing Factors
# ─────────────────────────────────────────────────────────────────────────────

DEMAND_SURGE_THRESHOLD = 50
DEMAND_SURGE_MULTIPLIER = 1.15
LOW_STOCK_MULTIPLIER = 1.10
LOW_STOCK_THRESHOLD = 5


def calculate_service_price(service: Service, user: ShopUser | None = None) -> float:
    base = service.base_price

    if service.dynamic_price is not None:
        base = service.dynamic_price

    if service.stock is not None and service.stock <= LOW_STOCK_THRESHOLD:
        base *= LOW_STOCK_MULTIPLIER

    if service.total_orders > DEMAND_SURGE_THRESHOLD:
        surge = 1.0 + (service.total_orders / 1000) * 0.05
        base *= min(surge, DEMAND_SURGE_MULTIPLIER)

    hour = datetime.now(tz=UTC).hour
    if 0 <= hour < 6:
        base *= 0.95

    if user:
        discount = get_user_discount(user)
        base *= (1 - discount)

    if service.min_price:
        base = max(base, service.min_price)
    if service.max_price:
        base = min(base, service.max_price)

    return round(base, 2)


async def get_categories(active_only: bool = True) -> list[ServiceCategory]:
    async with db_session() as session:
        q = select(ServiceCategory).order_by(ServiceCategory.sort_order)
        if active_only:
            q = q.where(ServiceCategory.is_active == True)
        result = await session.execute(q)
        return list(result.scalars().all())


async def get_services_by_category(
    category_id: int,
    user: ShopUser | None = None,
    active_only: bool = True,
) -> list[dict]:
    async with db_session() as session:
        q = select(Service).where(Service.category_id == category_id)
        if active_only:
            q = q.where(Service.is_active == True)
        if user and user.vip_tier == VIPTier.BASIC:
            q = q.where(Service.is_vip_only == False)

        result = await session.execute(q)
        services = list(result.scalars().all())

    enriched = []
    for svc in services:
        if svc.required_level and user:
            level_order = [UserLevel.BRONZE, UserLevel.SILVER, UserLevel.GOLD, UserLevel.ELITE]
            if level_order.index(user.level) < level_order.index(svc.required_level):
                continue

        price = calculate_service_price(svc, user)
        enriched.append({
            "service": svc,
            "price": price,
            "original_price": svc.base_price,
            "has_discount": price < svc.base_price,
        })

    return enriched


async def get_service(service_id: int, user: ShopUser | None = None) -> dict | None:
    async with db_session() as session:
        result = await session.execute(
            select(Service).where(Service.id == service_id, Service.is_active == True)
        )
        svc = result.scalar_one_or_none()
        if not svc:
            return None

    price = calculate_service_price(svc, user)
    return {
        "service": svc,
        "price": price,
        "original_price": svc.base_price,
        "has_discount": price < svc.base_price,
    }


async def get_featured_services(user: ShopUser | None = None, limit: int = 5) -> list[dict]:
    async with db_session() as session:
        q = (
            select(Service)
            .where(Service.is_active == True, Service.is_featured == True)
            .order_by(Service.total_orders.desc())
            .limit(limit)
        )
        result = await session.execute(q)
        services = list(result.scalars().all())

    enriched = []
    for svc in services:
        price = calculate_service_price(svc, user)
        enriched.append({
            "service": svc,
            "price": price,
            "original_price": svc.base_price,
            "has_discount": price < svc.base_price,
        })
    return enriched


async def search_services(query: str, user: ShopUser | None = None) -> list[dict]:
    async with db_session() as session:
        q = (
            select(Service)
            .where(
                Service.is_active == True,
                (Service.title.ilike(f"%{query}%") | Service.title_ar.ilike(f"%{query}%")),
            )
            .limit(10)
        )
        result = await session.execute(q)
        services = list(result.scalars().all())

    enriched = []
    for svc in services:
        price = calculate_service_price(svc, user)
        enriched.append({
            "service": svc,
            "price": price,
            "original_price": svc.base_price,
            "has_discount": price < svc.base_price,
        })
    return enriched


async def create_service(
    title: str,
    title_ar: str,
    base_price: float,
    category_id: int,
    service_type: str = "manual",
    description: str | None = None,
    stock: int | None = None,
    delivery_time_minutes: int = 60,
    is_featured: bool = False,
) -> Service:
    async with db_session() as session:
        svc = Service(
            title=title,
            title_ar=title_ar,
            description=description,
            category_id=category_id,
            base_price=base_price,
            service_type=service_type,
            stock=stock,
            delivery_time_minutes=delivery_time_minutes,
            is_featured=is_featured,
        )
        session.add(svc)
        await session.flush()
        logger.info("service_created", service_id=svc.id, title=title)
        return svc


async def create_category(
    name: str,
    name_ar: str,
    icon: str = "📦",
    description: str | None = None,
) -> ServiceCategory:
    async with db_session() as session:
        cat = ServiceCategory(
            name=name,
            name_ar=name_ar,
            icon=icon,
            description=description,
        )
        session.add(cat)
        await session.flush()
        return cat


def format_service_text(data: dict) -> str:
    svc: Service = data["service"]
    price = data["price"]
    original = data["original_price"]
    has_discount = data["has_discount"]

    price_text = f"`{price:.2f}$`"
    if has_discount:
        discount_pct = int((1 - price / original) * 100)
        price_text = f"~~{original:.2f}$~~ → `{price:.2f}$` 🔥 -{discount_pct}%"

    stock_text = ""
    if svc.stock is not None:
        if svc.stock == 0:
            stock_text = "\n❌ *نفد المخزون*"
        elif svc.stock <= 5:
            stock_text = f"\n⚠️ متبقي فقط {svc.stock}"

    delivery = f"{svc.delivery_time_minutes} دقيقة"
    if svc.delivery_time_minutes >= 60:
        hours = svc.delivery_time_minutes // 60
        delivery = f"{hours} ساعة"

    stars = "⭐" * int(svc.rating) + ("" if svc.rating == int(svc.rating) else "½")

    return (
        f"📦 *{svc.title_ar}*\n"
        f"_{svc.description or ''}_\n\n"
        f"💰 السعر: {price_text}\n"
        f"⏱ وقت التسليم: {delivery}\n"
        f"📊 التقييم: {stars} ({svc.rating:.1f})\n"
        f"📦 الطلبات: `{svc.total_orders:,}`"
        f"{stock_text}"
    )
