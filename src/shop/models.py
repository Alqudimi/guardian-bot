"""
Commerce System — SQLAlchemy ORM Models
=========================================
All shop-related database tables.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models import JSON_TYPE, Base

# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class VIPTier(str, enum.Enum):
    BASIC = "basic"
    PRO = "pro"
    ELITE = "elite"


class UserLevel(str, enum.Enum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    ELITE = "elite"


class ServiceType(str, enum.Enum):
    INSTANT = "instant"
    MANUAL = "manual"
    HYBRID = "hybrid"


class OrderStatus(str, enum.Enum):
    CREATED = "created"
    VALIDATED = "validated"
    PAID = "paid"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class OrderPriority(str, enum.Enum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class TransactionType(str, enum.Enum):
    DEPOSIT = "deposit"
    PURCHASE = "purchase"
    REFUND = "refund"
    COMMISSION = "commission"
    BONUS = "bonus"
    ADJUSTMENT = "adjustment"


class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    LOCKED = "locked"


class TicketStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    RESOLVED = "resolved"
    CLOSED = "closed"
    ESCALATED = "escalated"


class TicketPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationType(str, enum.Enum):
    TRANSACTIONAL = "transactional"
    MARKETING = "marketing"
    SYSTEM = "system"


# ─────────────────────────────────────────────────────────────────────────────
# Shop User (Commerce Profile)
# ─────────────────────────────────────────────────────────────────────────────

class ShopUser(Base):
    __tablename__ = "shop_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(128))
    first_name: Mapped[str | None] = mapped_column(String(255))

    balance: Mapped[float] = mapped_column(Float, default=0.0)
    locked_balance: Mapped[float] = mapped_column(Float, default=0.0)

    level: Mapped[str] = mapped_column(Enum(UserLevel), default=UserLevel.BRONZE)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    vip_tier: Mapped[str] = mapped_column(Enum(VIPTier), default=VIPTier.BASIC)
    vip_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    total_spent: Mapped[float] = mapped_column(Float, default=0.0)
    total_orders: Mapped[int] = mapped_column(Integer, default=0)

    referral_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    referred_by: Mapped[int | None] = mapped_column(BigInteger, index=True)

    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    ban_reason: Mapped[str | None] = mapped_column(Text)

    preferences: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    orders: Mapped[list[Order]] = relationship(back_populates="user", lazy="select")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="user", lazy="select")
    tickets: Mapped[list[SupportTicket]] = relationship(back_populates="user", lazy="select")

    __table_args__ = (
        Index("ix_shop_users_telegram", "telegram_id"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Service Catalog
# ─────────────────────────────────────────────────────────────────────────────

class ServiceCategory(Base):
    __tablename__ = "service_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    name_ar: Mapped[str] = mapped_column(String(128))
    icon: Mapped[str] = mapped_column(String(8), default="📦")
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    services: Mapped[list[Service]] = relationship(back_populates="category", lazy="select")


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    title_ar: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("service_categories.id"), index=True)

    base_price: Mapped[float] = mapped_column(Float)
    dynamic_price: Mapped[float | None] = mapped_column(Float)
    min_price: Mapped[float] = mapped_column(Float, default=0.0)
    max_price: Mapped[float | None] = mapped_column(Float)

    service_type: Mapped[str] = mapped_column(Enum(ServiceType), default=ServiceType.MANUAL)
    api_endpoint: Mapped[str | None] = mapped_column(String(512))
    api_params: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)

    stock: Mapped[int | None] = mapped_column(Integer)
    min_order: Mapped[int] = mapped_column(Integer, default=1)
    max_order: Mapped[int | None] = mapped_column(Integer)

    delivery_time_minutes: Mapped[int] = mapped_column(Integer, default=60)

    rating: Mapped[float] = mapped_column(Float, default=5.0)
    total_orders: Mapped[int] = mapped_column(Integer, default=0)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    is_vip_only: Mapped[bool] = mapped_column(Boolean, default=False)
    required_level: Mapped[str | None] = mapped_column(Enum(UserLevel))

    tags: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    extra_data: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    category: Mapped[ServiceCategory | None] = relationship(back_populates="services")
    order_items: Mapped[list[OrderItem]] = relationship(back_populates="service", lazy="select")


# ─────────────────────────────────────────────────────────────────────────────
# Orders
# ─────────────────────────────────────────────────────────────────────────────

class Order(Base):
    __tablename__ = "shop_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_users.id"), index=True)

    status: Mapped[str] = mapped_column(Enum(OrderStatus), default=OrderStatus.CREATED)
    priority: Mapped[str] = mapped_column(Enum(OrderPriority), default=OrderPriority.NORMAL)

    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    discount_amount: Mapped[float] = mapped_column(Float, default=0.0)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)

    coupon_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("coupons.id"))
    coupon_discount: Mapped[float] = mapped_column(Float, default=0.0)

    notes: Mapped[str | None] = mapped_column(Text)
    delivery_data: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)

    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)

    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_reason: Mapped[str | None] = mapped_column(Text)

    xp_awarded: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[ShopUser] = relationship(back_populates="orders")
    items: Mapped[list[OrderItem]] = relationship(back_populates="order", cascade="all, delete-orphan")
    coupon: Mapped[Coupon | None] = relationship("Coupon", lazy="select")

    __table_args__ = (
        Index("ix_orders_user_status", "user_id", "status"),
        Index("ix_orders_created", "created_at"),
    )


class OrderItem(Base):
    __tablename__ = "shop_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_orders.id"), index=True)
    service_id: Mapped[int] = mapped_column(Integer, ForeignKey("services.id"), index=True)

    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float)
    total_price: Mapped[float] = mapped_column(Float)
    delivery_value: Mapped[str | None] = mapped_column(Text)

    order: Mapped[Order] = relationship(back_populates="items")
    service: Mapped[Service] = relationship(back_populates="order_items")


# ─────────────────────────────────────────────────────────────────────────────
# Wallet & Transactions
# ─────────────────────────────────────────────────────────────────────────────

class Transaction(Base):
    __tablename__ = "shop_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ref: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_users.id"), index=True)

    tx_type: Mapped[str] = mapped_column(Enum(TransactionType))
    amount: Mapped[float] = mapped_column(Float)
    balance_before: Mapped[float] = mapped_column(Float)
    balance_after: Mapped[float] = mapped_column(Float)

    status: Mapped[str] = mapped_column(Enum(TransactionStatus), default=TransactionStatus.PENDING)

    order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("shop_orders.id"))
    description: Mapped[str | None] = mapped_column(Text)
    extra_data: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    user: Mapped[ShopUser] = relationship(back_populates="transactions")

    __table_args__ = (
        Index("ix_transactions_user_created", "user_id", "created_at"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Coupons
# ─────────────────────────────────────────────────────────────────────────────

class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)

    discount_percent: Mapped[float | None] = mapped_column(Float)
    discount_fixed: Mapped[float | None] = mapped_column(Float)
    max_discount: Mapped[float | None] = mapped_column(Float)
    min_order_amount: Mapped[float] = mapped_column(Float, default=0.0)

    usage_limit: Mapped[int | None] = mapped_column(Integer)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)

    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    allowed_services: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    allowed_users: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    allowed_levels: Mapped[list] = mapped_column(JSON_TYPE, default=list)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    stackable: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    usages: Mapped[list[CouponUsage]] = relationship(back_populates="coupon", lazy="select")


class CouponUsage(Base):
    __tablename__ = "coupon_usages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coupon_id: Mapped[int] = mapped_column(Integer, ForeignKey("coupons.id"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_users.id"), index=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_orders.id"))
    discount_applied: Mapped[float] = mapped_column(Float)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    coupon: Mapped[Coupon] = relationship(back_populates="usages")

    __table_args__ = (
        Index("ix_coupon_usage_user_coupon", "user_id", "coupon_id"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Affiliate System
# ─────────────────────────────────────────────────────────────────────────────

class AffiliateLink(Base):
    __tablename__ = "affiliate_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_users.id"), index=True)
    referred_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_users.id"), unique=True)

    first_purchase_commission_pct: Mapped[float] = mapped_column(Float, default=5.0)
    lifetime_commission_pct: Mapped[float] = mapped_column(Float, default=2.0)

    total_commission_earned: Mapped[float] = mapped_column(Float, default=0.0)
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AffiliateCommission(Base):
    __tablename__ = "affiliate_commissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_users.id"), index=True)
    referred_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_users.id"), index=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_orders.id"))

    commission_amount: Mapped[float] = mapped_column(Float)
    commission_pct: Mapped[float] = mapped_column(Float)
    is_first_purchase: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────────────────────────────────────
# Support Tickets
# ─────────────────────────────────────────────────────────────────────────────

class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_ref: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_users.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("shop_orders.id"))

    category: Mapped[str] = mapped_column(String(64), default="general")
    subject: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(Enum(TicketStatus), default=TicketStatus.OPEN)
    priority: Mapped[str] = mapped_column(Enum(TicketPriority), default=TicketPriority.NORMAL)

    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    admin_notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[ShopUser] = relationship(back_populates="tickets")
    messages: Mapped[list[TicketMessage]] = relationship(back_populates="ticket", cascade="all, delete-orphan")


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("support_tickets.id"), index=True)
    sender_id: Mapped[int | None] = mapped_column(BigInteger)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str] = mapped_column(Text)
    attachments: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[SupportTicket] = relationship(back_populates="messages")


# ─────────────────────────────────────────────────────────────────────────────
# Bundles
# ─────────────────────────────────────────────────────────────────────────────

class Bundle(Base):
    __tablename__ = "bundles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    title_ar: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    bundle_price: Mapped[float] = mapped_column(Float)
    original_price: Mapped[float] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list[BundleItem]] = relationship(back_populates="bundle", cascade="all, delete-orphan")


class BundleItem(Base):
    __tablename__ = "bundle_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bundle_id: Mapped[int] = mapped_column(Integer, ForeignKey("bundles.id"), index=True)
    service_id: Mapped[int] = mapped_column(Integer, ForeignKey("services.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    bundle: Mapped[Bundle] = relationship(back_populates="items")


# ─────────────────────────────────────────────────────────────────────────────
# Notifications
# ─────────────────────────────────────────────────────────────────────────────

class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_users.id"), index=True)
    notification_type: Mapped[str] = mapped_column(Enum(NotificationType), default=NotificationType.TRANSACTIONAL)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    extra_data: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ─────────────────────────────────────────────────────────────────────────────
# Daily Missions / Gamification
# ─────────────────────────────────────────────────────────────────────────────

class UserMission(Base):
    __tablename__ = "user_missions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_users.id"), index=True)
    mission_type: Mapped[str] = mapped_column(String(64))
    mission_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    reward_xp: Mapped[int] = mapped_column(Integer, default=0)
    reward_balance: Mapped[float] = mapped_column(Float, default=0.0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_missions_user_date", "user_id", "mission_date"),
    )
