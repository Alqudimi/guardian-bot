"""
Support Engine — Ticket lifecycle, SLA, auto-escalation.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.db.session import db_session
from src.shop.models import (
    ShopUser,
    SupportTicket,
    TicketMessage,
    TicketPriority,
    TicketStatus,
    VIPTier,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

SLA_HOURS = {
    TicketPriority.LOW: 48,
    TicketPriority.NORMAL: 24,
    TicketPriority.HIGH: 8,
    TicketPriority.URGENT: 2,
}

TICKET_CATEGORIES = {
    "order": "مشكلة في طلب",
    "payment": "مشكلة في الدفع",
    "account": "مشكلة في الحساب",
    "refund": "طلب استرداد",
    "technical": "مشكلة تقنية",
    "general": "استفسار عام",
}


def _generate_ticket_ref() -> str:
    ts = datetime.now(tz=UTC).strftime("%y%m%d")
    suffix = secrets.token_hex(3).upper()
    return f"TKT-{ts}-{suffix}"


async def create_ticket(
    telegram_id: int,
    subject: str,
    message: str,
    category: str = "general",
    order_id: int | None = None,
) -> SupportTicket:
    async with db_session() as session:
        user_result = await session.execute(
            select(ShopUser).where(ShopUser.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise ValueError("المستخدم غير موجود")

        priority = TicketPriority.HIGH if user.vip_tier == VIPTier.ELITE else TicketPriority.NORMAL
        if user.vip_tier == VIPTier.PRO:
            priority = TicketPriority.HIGH

        sla_hours = SLA_HOURS[priority]
        sla_deadline = datetime.now(tz=UTC) + timedelta(hours=sla_hours)

        ticket = SupportTicket(
            ticket_ref=_generate_ticket_ref(),
            user_id=user.id,
            order_id=order_id,
            category=category,
            subject=subject,
            status=TicketStatus.OPEN,
            priority=priority,
            sla_deadline=sla_deadline,
        )
        session.add(ticket)
        await session.flush()

        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_id=telegram_id,
            is_admin=False,
            message=message,
        )
        session.add(msg)
        logger.info("ticket_created", ref=ticket.ticket_ref, user=telegram_id)
        return ticket


async def reply_to_ticket(
    ticket_ref: str,
    message: str,
    sender_id: int,
    is_admin: bool = False,
) -> TicketMessage:
    async with db_session() as session:
        result = await session.execute(
            select(SupportTicket).where(SupportTicket.ticket_ref == ticket_ref)
        )
        ticket = result.scalar_one_or_none()
        if not ticket:
            raise ValueError("التذكرة غير موجودة")

        if ticket.status == TicketStatus.CLOSED:
            raise ValueError("التذكرة مغلقة")

        if not is_admin:
            sender_result = await session.execute(
                select(ShopUser).where(ShopUser.telegram_id == sender_id)
            )
            sender = sender_result.scalar_one_or_none()
            if not sender or sender.id != ticket.user_id:
                raise PermissionError("لا تملك صلاحية الرد على هذه التذكرة")

        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_id=sender_id,
            is_admin=is_admin,
            message=message,
        )
        session.add(msg)

        if is_admin and ticket.status == TicketStatus.OPEN:
            ticket.status = TicketStatus.IN_PROGRESS
        elif not is_admin:
            ticket.status = TicketStatus.WAITING

        return msg


async def close_ticket(ticket_ref: str, admin_notes: str | None = None) -> SupportTicket:
    async with db_session() as session:
        result = await session.execute(
            select(SupportTicket).where(SupportTicket.ticket_ref == ticket_ref)
        )
        ticket = result.scalar_one_or_none()
        if not ticket:
            raise ValueError("التذكرة غير موجودة")
        ticket.status = TicketStatus.RESOLVED
        ticket.resolved_at = datetime.now(tz=UTC)
        if admin_notes:
            ticket.admin_notes = admin_notes
        return ticket


async def escalate_ticket(ticket_ref: str) -> SupportTicket:
    async with db_session() as session:
        result = await session.execute(
            select(SupportTicket).where(SupportTicket.ticket_ref == ticket_ref)
        )
        ticket = result.scalar_one_or_none()
        if not ticket:
            raise ValueError("التذكرة غير موجودة")
        ticket.status = TicketStatus.ESCALATED
        ticket.priority = TicketPriority.URGENT
        ticket.escalated_at = datetime.now(tz=UTC)
        logger.warning("ticket_escalated", ref=ticket_ref)
        return ticket


async def get_user_tickets(
    telegram_id: int, limit: int = 5, open_only: bool = False
) -> list[SupportTicket]:
    async with db_session() as session:
        user_result = await session.execute(
            select(ShopUser).where(ShopUser.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return []

        q = (
            select(SupportTicket)
            .options(selectinload(SupportTicket.messages))
            .where(SupportTicket.user_id == user.id)
            .order_by(SupportTicket.created_at.desc())
            .limit(limit)
        )
        if open_only:
            q = q.where(SupportTicket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS]))
        result = await session.execute(q)
        return list(result.scalars().all())


async def get_all_open_tickets(limit: int = 20) -> list[SupportTicket]:
    async with db_session() as session:
        q = (
            select(SupportTicket)
            .options(selectinload(SupportTicket.user), selectinload(SupportTicket.messages))
            .where(SupportTicket.status.in_([
                TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.ESCALATED
            ]))
            .order_by(SupportTicket.priority.desc(), SupportTicket.created_at.asc())
            .limit(limit)
        )
        result = await session.execute(q)
        return list(result.scalars().all())


async def auto_escalate_overdue_tickets() -> int:
    """Escalate tickets that breached SLA. Returns count of escalated tickets."""
    async with db_session() as session:
        now = datetime.now(tz=UTC)
        result = await session.execute(
            select(SupportTicket).where(
                SupportTicket.sla_deadline < now,
                SupportTicket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS]),
            )
        )
        tickets = list(result.scalars().all())
        for ticket in tickets:
            ticket.status = TicketStatus.ESCALATED
            ticket.escalated_at = now
        if tickets:
            logger.warning("tickets_auto_escalated", count=len(tickets))
        return len(tickets)


def format_ticket_text(ticket: SupportTicket) -> str:
    status_ar = {
        TicketStatus.OPEN: "🟢 مفتوحة",
        TicketStatus.IN_PROGRESS: "🔵 قيد المعالجة",
        TicketStatus.WAITING: "🟡 بانتظار ردك",
        TicketStatus.RESOLVED: "✅ محلولة",
        TicketStatus.CLOSED: "⚫ مغلقة",
        TicketStatus.ESCALATED: "🔴 مُصعَّدة",
    }
    priority_ar = {
        TicketPriority.LOW: "منخفضة",
        TicketPriority.NORMAL: "عادية",
        TicketPriority.HIGH: "عالية",
        TicketPriority.URGENT: "عاجلة",
    }

    status_text = status_ar.get(ticket.status, ticket.status)
    priority_text = priority_ar.get(ticket.priority, ticket.priority)

    sla_text = ""
    if ticket.sla_deadline and ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        remaining = ticket.sla_deadline - datetime.now(tz=UTC)
        if remaining.total_seconds() > 0:
            hours = int(remaining.total_seconds() / 3600)
            sla_text = f"\n⏳ SLA: متبقي {hours} ساعة"
        else:
            sla_text = "\n⚠️ SLA: تجاوز الوقت!"

    last_msg = ""
    if ticket.messages:
        last = ticket.messages[-1]
        sender = "الدعم 👨‍💻" if last.is_admin else "أنت"
        last_msg = f"\n\n💬 آخر رد ({sender}):\n_{last.message[:100]}..._" if len(last.message) > 100 else f"\n\n💬 آخر رد ({sender}):\n_{last.message}_"

    return (
        f"🎫 *تذكرة #{ticket.ticket_ref}*\n"
        f"الموضوع: {ticket.subject}\n"
        f"الحالة: {status_text}\n"
        f"الأولوية: {priority_text}"
        f"{sla_text}"
        f"{last_msg}"
    )
