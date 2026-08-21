"""
Order Engine — Full lifecycle management, queue, retries, SLA.
"""
from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.db.session import db_session
from src.shop.models import (
    Coupon,
    Order,
    OrderItem,
    OrderPriority,
    OrderStatus,
    Service,
    ServiceType,
    ShopUser,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _generate_order_ref() -> str:
    ts = datetime.now(tz=UTC).strftime("%y%m%d")
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(chars) for _ in range(6))
    return f"ORD-{ts}-{suffix}"


def _generate_tx_ref() -> str:
    return "TX-" + secrets.token_hex(10).upper()


# ─────────────────────────────────────────────────────────────────────────────
# Order Creation
# ─────────────────────────────────────────────────────────────────────────────

class InsufficientBalanceError(Exception):
    pass


class ServiceUnavailableError(Exception):
    pass


class OrderValidationError(Exception):
    pass


async def create_order(
    user: ShopUser,
    items: list[dict],
    coupon_id: int | None = None,
    notes: str | None = None,
    delivery_data: dict | None = None,
) -> Order:
    """Create a validated order using authoritative database prices.

    ``items`` may originate from Telegram state, so its prices are treated as
    display hints only. The database service row is the sole pricing source.
    """
    if not items:
        raise OrderValidationError("يجب أن يحتوي الطلب على خدمة واحدة على الأقل")

    async with db_session() as session:
        result = await session.execute(
            select(ShopUser).where(ShopUser.id == user.id).with_for_update()
        )
        db_user = result.scalar_one_or_none()
        if not db_user or db_user.is_banned:
            raise OrderValidationError("حساب المتجر غير صالح")

        service_ids = []
        normalized_items: list[dict] = []
        for raw_item in items:
            try:
                service_id = int(raw_item["service_id"])
                quantity = int(raw_item.get("quantity", 1))
            except (KeyError, TypeError, ValueError) as exc:
                raise OrderValidationError("بيانات الخدمة غير صالحة") from exc
            if quantity < 1:
                raise OrderValidationError("كمية الخدمة يجب أن تكون موجبة")
            if service_id in service_ids:
                raise OrderValidationError("لا يمكن تكرار الخدمة داخل الطلب")
            service_ids.append(service_id)

        service_result = await session.execute(
            select(Service).where(Service.id.in_(service_ids), Service.is_active.is_(True))
        )
        services = {service.id: service for service in service_result.scalars().all()}
        if len(services) != len(service_ids):
            raise ServiceUnavailableError("إحدى الخدمات غير متاحة حالياً")

        from src.shop.service_engine import calculate_service_price
        from src.shop.user_engine import get_user_priority

        subtotal = 0.0
        for raw_item in items:
            service = services[int(raw_item["service_id"])]
            quantity = int(raw_item.get("quantity", 1))
            if service.stock is not None and quantity > service.stock:
                raise ServiceUnavailableError("الكمية المطلوبة أكبر من المخزون المتاح")
            if quantity < service.min_order:
                raise OrderValidationError(f"الحد الأدنى لهذه الخدمة: {service.min_order}")
            if service.max_order is not None and quantity > service.max_order:
                raise OrderValidationError(f"الحد الأقصى لهذه الخدمة: {service.max_order}")
            if service.required_level:
                levels = ["bronze", "silver", "gold", "elite"]
                user_level = levels.index(str(db_user.level.value))
                required_level = levels.index(str(service.required_level.value))
                if user_level < required_level:
                    raise ServiceUnavailableError("مستوى حسابك لا يسمح بهذه الخدمة")
            price = calculate_service_price(service, db_user)
            normalized_items.append({
                "service_id": service.id,
                "quantity": quantity,
                "unit_price": price,
                "total_price": round(price * quantity, 2),
            })
            subtotal += price * quantity
        subtotal = round(subtotal, 2)

        coupon_discount = 0.0
        if coupon_id:
            from src.shop.coupon_engine import (
                CouponError,
                calculate_discount,
                validate_coupon_for_session,
            )
            coupon_result = await session.execute(
                select(Coupon).where(Coupon.id == coupon_id).with_for_update()
            )
            coupon = coupon_result.scalar_one_or_none()
            if not coupon:
                raise OrderValidationError("الكوبون غير موجود")
            try:
                await validate_coupon_for_session(
                    session, coupon.code, db_user, subtotal, service_ids
                )
            except CouponError as exc:
                raise OrderValidationError(str(exc)) from exc
            coupon_discount = calculate_discount(coupon, subtotal)

        total_amount = max(0.0, round(subtotal - coupon_discount, 2))
        available = db_user.balance - db_user.locked_balance
        if available < total_amount:
            raise InsufficientBalanceError(
                f"رصيد غير كافٍ. المتاح: {available:.2f}$ | المطلوب: {total_amount:.2f}$"
            )

        priority_str = get_user_priority(db_user)
        priority = {
            "high": OrderPriority.HIGH,
            "normal": OrderPriority.NORMAL,
            "low": OrderPriority.LOW,
        }.get(priority_str, OrderPriority.NORMAL)
        sla_minutes = {"high": 60, "normal": 120, "low": 240}.get(priority_str, 120)

        order = Order(
            order_ref=_generate_order_ref(),
            user_id=db_user.id,
            status=OrderStatus.VALIDATED,
            priority=priority,
            subtotal=subtotal,
            coupon_id=coupon_id,
            coupon_discount=coupon_discount,
            total_amount=total_amount,
            notes=notes,
            delivery_data=delivery_data or {},
            sla_deadline=datetime.now(tz=UTC) + timedelta(minutes=sla_minutes),
        )
        session.add(order)
        await session.flush()
        for item_data in normalized_items:
            session.add(OrderItem(order_id=order.id, **item_data))
        db_user.locked_balance += total_amount

        logger.info(
            "order_created",
            order_ref=order.order_ref,
            user_id=db_user.id,
            total=total_amount,
        )
        return order


async def pay_order(order_id: int, telegram_id: int) -> Order:
    """Pay a validated order exactly once after revalidating its live state."""
    failure: str | None = None
    paid_order: Order | None = None
    async with db_session() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id)
            .with_for_update()
        )
        order = result.scalar_one_or_none()
        if not order:
            raise OrderValidationError("الطلب غير موجود")
        if order.status not in (OrderStatus.VALIDATED, OrderStatus.CREATED):
            raise OrderValidationError(f"لا يمكن دفع طلب بحالة {order.status}")

        user_result = await session.execute(
            select(ShopUser).where(ShopUser.id == order.user_id).with_for_update()
        )
        user = user_result.scalar_one_or_none()
        if not user or user.telegram_id != telegram_id:
            raise OrderValidationError("المستخدم لا يملك هذا الطلب")

        service_ids = [item.service_id for item in order.items]
        service_result = await session.execute(
            select(Service).where(Service.id.in_(service_ids))
        )
        services = {service.id: service for service in service_result.scalars().all()}
        from src.shop.coupon_engine import (
            CouponError,
            calculate_discount,
            record_coupon_usage_in_session,
            validate_coupon_for_session,
        )
        from src.shop.service_engine import calculate_service_price

        if len(services) != len(service_ids):
            failure = "إحدى الخدمات لم تعد موجودة"
        elif any(not service.is_active for service in services.values()):
            failure = "إحدى الخدمات لم تعد متاحة"
        elif any(service.service_type == ServiceType.INSTANT for service in services.values()):
            failure = "الخدمة الآلية غير متاحة: لم يتم إعداد منفذ تنفيذ فعلي لهذا النوع"

        live_subtotal = 0.0
        if not failure:
            for item in order.items:
                service = services[item.service_id]
                if service.stock is not None and item.quantity > service.stock:
                    failure = "المخزون الحالي لا يكفي للطلب"
                    break
                live_price = calculate_service_price(service, user)
                if round(live_price, 2) != round(item.unit_price, 2):
                    failure = "تغير سعر الخدمة؛ يرجى إعادة إنشاء الطلب"
                    break
                live_subtotal += live_price * item.quantity

        coupon = None
        live_discount = 0.0
        if not failure and order.coupon_id:
            coupon_result = await session.execute(
                select(Coupon).where(Coupon.id == order.coupon_id).with_for_update()
            )
            coupon = coupon_result.scalar_one_or_none()
            if not coupon:
                failure = "الكوبون المرتبط بالطلب غير موجود"
            else:
                try:
                    await validate_coupon_for_session(
                        session, coupon.code, user, round(live_subtotal, 2), service_ids
                    )
                    live_discount = calculate_discount(coupon, round(live_subtotal, 2))
                except CouponError as exc:
                    failure = str(exc)

        live_total = max(0.0, round(live_subtotal - live_discount, 2))
        if not failure and (
            round(live_subtotal, 2) != round(order.subtotal, 2)
            or round(live_discount, 2) != round(order.coupon_discount, 2)
            or live_total != round(order.total_amount, 2)
        ):
            failure = "تغير سعر الطلب أو خصمه؛ يرجى إعادة إنشاء الطلب"

        available = user.balance - user.locked_balance + order.total_amount
        if not failure and available < live_total:
            failure = "رصيدك المتاح لم يعد كافياً لهذا الطلب"

        if failure:
            user.locked_balance = max(0.0, user.locked_balance - order.total_amount)
            order.status = OrderStatus.CANCELLED
            order.failed_reason = failure
        else:
            user.balance -= live_total
            user.locked_balance = max(0.0, user.locked_balance - order.total_amount)
            user.total_spent += live_total
            user.total_orders += 1
            order.xp_awarded = max(10, int(live_total * 2))
            order.status = OrderStatus.PROCESSING
            order.total_amount = live_total
            order.subtotal = round(live_subtotal, 2)
            order.coupon_discount = live_discount
            session.add(Transaction(
                ref=_generate_tx_ref(),
                user_id=user.id,
                tx_type=TransactionType.PURCHASE,
                amount=-live_total,
                balance_before=user.balance + live_total,
                balance_after=user.balance,
                status=TransactionStatus.COMPLETED,
                order_id=order.id,
                description=f"شراء - {order.order_ref}",
            ))
            for service in services.values():
                service.total_orders += 1
            if coupon:
                coupon.usage_count += 1
                await record_coupon_usage_in_session(
                    session, coupon.id, user.id, order.id, live_discount
                )
            paid_order = order
            logger.info("order_paid", order_ref=order.order_ref, total=live_total)

    if failure:
        raise OrderValidationError(failure)
    assert paid_order is not None
    return paid_order


async def complete_order(order_id: int) -> Order:
    async with db_session() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.user))
            .where(Order.id == order_id)
            .with_for_update()
        )
        order = result.scalar_one_or_none()
        if not order:
            raise OrderValidationError("الطلب غير موجود")
        if order.status not in (OrderStatus.PAID, OrderStatus.PROCESSING):
            raise OrderValidationError("لا يمكن إكمال طلب غير مدفوع أو غير قيد المعالجة")

        order.status = OrderStatus.COMPLETED
        order.completed_at = datetime.now(tz=UTC)

        logger.info("order_completed", order_ref=order.order_ref)
        return order


async def fail_order(order_id: int, reason: str = "فشل التنفيذ") -> Order:
    async with db_session() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.user))
            .where(Order.id == order_id)
            .with_for_update()
        )
        order = result.scalar_one_or_none()
        if not order:
            raise OrderValidationError("الطلب غير موجود")
        if order.status in (OrderStatus.FAILED, OrderStatus.REFUNDED, OrderStatus.CANCELLED):
            raise OrderValidationError("تمت معالجة فشل هذا الطلب مسبقاً")
        if order.status not in (OrderStatus.PAID, OrderStatus.PROCESSING):
            raise OrderValidationError("لا يمكن فشل طلب غير مدفوع أو غير قيد المعالجة")

        if order.retry_count < order.max_retries:
            order.retry_count += 1
            order.status = OrderStatus.PROCESSING
            logger.info("order_retry", order_ref=order.order_ref, attempt=order.retry_count)
            return order

        order.status = OrderStatus.FAILED
        order.failed_reason = reason
        if order.user:
            user = order.user
            user.locked_balance = max(0.0, user.locked_balance - order.total_amount)
            user.balance += order.total_amount
            user.total_spent = max(0.0, user.total_spent - order.total_amount)
            user.total_orders = max(0, user.total_orders - 1)
            session.add(Transaction(
                ref=_generate_tx_ref(),
                user_id=user.id,
                tx_type=TransactionType.REFUND,
                amount=order.total_amount,
                balance_before=user.balance - order.total_amount,
                balance_after=user.balance,
                status=TransactionStatus.COMPLETED,
                order_id=order.id,
                description=f"رد تلقائي لفشل الطلب - {order.order_ref}",
            ))

        logger.warning("order_failed", order_ref=order.order_ref, reason=reason)
        return order


async def refund_order(order_id: int, telegram_id: int | None = None) -> Order:
    """Refund one paid order, optionally enforcing the requesting user owner."""
    async with db_session() as session:
        result = await session.execute(
            select(Order).where(Order.id == order_id).with_for_update()
        )
        order = result.scalar_one_or_none()
        if not order:
            raise OrderValidationError("الطلب غير موجود")
        if order.status == OrderStatus.REFUNDED:
            raise OrderValidationError("تم استرداد هذا الطلب مسبقاً")
        if order.status not in (OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.COMPLETED):
            raise OrderValidationError("لا يمكن استرداد طلب غير مدفوع")

        user_result = await session.execute(
            select(ShopUser).where(ShopUser.id == order.user_id).with_for_update()
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise OrderValidationError("مالك الطلب غير موجود")
        if telegram_id is not None and user.telegram_id != telegram_id:
            raise OrderValidationError("المستخدم لا يملك هذا الطلب")

        user.balance += order.total_amount
        user.total_spent = max(0.0, user.total_spent - order.total_amount)
        user.total_orders = max(0, user.total_orders - 1)
        session.add(Transaction(
            ref=_generate_tx_ref(),
            user_id=user.id,
            tx_type=TransactionType.REFUND,
            amount=order.total_amount,
            balance_before=user.balance - order.total_amount,
            balance_after=user.balance,
            status=TransactionStatus.COMPLETED,
            order_id=order.id,
            description=f"استرداد - {order.order_ref}",
        ))
        order.status = OrderStatus.REFUNDED
        logger.info("order_refunded", order_ref=order.order_ref, amount=order.total_amount)
        return order


async def get_user_orders(
    user_id: int,
    status: OrderStatus | None = None,
    limit: int = 10,
    offset: int = 0,
) -> list[Order]:
    async with db_session() as session:
        q = (
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.service))
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status:
            q = q.where(Order.status == status)
        result = await session.execute(q)
        return list(result.scalars().all())


async def get_order_by_ref(
    order_ref: str,
    telegram_id: int | None = None,
) -> Order | None:
    async with db_session() as session:
        q = (
            select(Order)
            .join(ShopUser, ShopUser.id == Order.user_id)
            .options(
                selectinload(Order.user),
                selectinload(Order.items).selectinload(OrderItem.service),
            )
            .where(Order.order_ref == order_ref)
        )
        if telegram_id is not None:
            q = q.where(ShopUser.telegram_id == telegram_id)
        result = await session.execute(q)
        return result.scalar_one_or_none()


def format_order_text(order: Order) -> str:
    status_emoji = {
        OrderStatus.CREATED: "🆕",
        OrderStatus.VALIDATED: "✅",
        OrderStatus.PAID: "💳",
        OrderStatus.PROCESSING: "⚙️",
        OrderStatus.COMPLETED: "✅",
        OrderStatus.FAILED: "❌",
        OrderStatus.REFUNDED: "↩️",
        OrderStatus.CANCELLED: "🚫",
    }

    status_ar = {
        OrderStatus.CREATED: "تم الإنشاء",
        OrderStatus.VALIDATED: "تم التحقق",
        OrderStatus.PAID: "مدفوع",
        OrderStatus.PROCESSING: "قيد المعالجة",
        OrderStatus.COMPLETED: "مكتمل",
        OrderStatus.FAILED: "فشل",
        OrderStatus.REFUNDED: "مسترد",
        OrderStatus.CANCELLED: "ملغي",
    }

    emoji = status_emoji.get(order.status, "❓")
    status_text = status_ar.get(order.status, order.status)

    items_text = ""
    if order.items:
        for item in order.items:
            svc_name = item.service.title_ar if item.service else f"#{item.service_id}"
            items_text += f"\n  • {svc_name} × {item.quantity} = {item.total_price:.2f}$"

    sla_text = ""
    if order.sla_deadline and order.status in (OrderStatus.PAID, OrderStatus.PROCESSING):
        remaining = order.sla_deadline - datetime.now(tz=UTC)
        if remaining.total_seconds() > 0:
            mins = int(remaining.total_seconds() / 60)
            sla_text = f"\n⏳ SLA: متبقي {mins} دقيقة"
        else:
            sla_text = "\n⚠️ SLA: تجاوز الوقت!"

    return (
        f"{emoji} *طلب #{order.order_ref}*\n"
        f"الحالة: *{status_text}*\n"
        f"📦 الخدمات:{items_text}\n\n"
        f"💰 الإجمالي: `{order.total_amount:.2f}$`"
        f"{sla_text}"
    )
