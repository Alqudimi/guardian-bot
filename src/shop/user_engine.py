"""
User Engine — Shop user management, XP, levels, VIP system.
"""
from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime

from sqlalchemy import select

from src.db.session import db_session
from src.shop.models import ShopUser, UserLevel, VIPTier
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Level thresholds and rewards
# ─────────────────────────────────────────────────────────────────────────────

LEVEL_THRESHOLDS = {
    UserLevel.BRONZE: 0,
    UserLevel.SILVER: 500,
    UserLevel.GOLD: 2000,
    UserLevel.ELITE: 6000,
}

LEVEL_DISCOUNTS = {
    UserLevel.BRONZE: 0.0,
    UserLevel.SILVER: 0.03,
    UserLevel.GOLD: 0.07,
    UserLevel.ELITE: 0.12,
}

VIP_DISCOUNTS = {
    VIPTier.BASIC: 0.05,
    VIPTier.PRO: 0.10,
    VIPTier.ELITE: 0.20,
}

VIP_SPEND_THRESHOLDS = {
    VIPTier.PRO: 100.0,
    VIPTier.ELITE: 500.0,
}

XP_RATES = {
    "purchase": 10,
    "referral": 50,
    "daily_login": 5,
    "first_order": 100,
    "ticket_resolved": 20,
}

LEVEL_NAMES_AR = {
    UserLevel.BRONZE: "برونزي",
    UserLevel.SILVER: "فضي",
    UserLevel.GOLD: "ذهبي",
    UserLevel.ELITE: "إليت",
}

VIP_NAMES_AR = {
    VIPTier.BASIC: "أساسي",
    VIPTier.PRO: "برو",
    VIPTier.ELITE: "إليت",
}


def _generate_referral_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def _xp_to_level(xp: int) -> UserLevel:
    level = UserLevel.BRONZE
    for lvl, threshold in sorted(LEVEL_THRESHOLDS.items(), key=lambda x: x[1], reverse=True):
        if xp >= threshold:
            level = lvl
            break
    return level


def _spend_to_vip(total_spent: float) -> VIPTier:
    if total_spent >= VIP_SPEND_THRESHOLDS[VIPTier.ELITE]:
        return VIPTier.ELITE
    if total_spent >= VIP_SPEND_THRESHOLDS[VIPTier.PRO]:
        return VIPTier.PRO
    return VIPTier.BASIC


async def get_or_create_shop_user(
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
    referred_by_code: str | None = None,
) -> ShopUser:
    async with db_session() as session:
        result = await session.execute(
            select(ShopUser).where(ShopUser.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user:
            if username and user.username != username:
                user.username = username
            if first_name and user.first_name != first_name:
                user.first_name = first_name
            return user

        referred_by_id: int | None = None
        if referred_by_code:
            ref_result = await session.execute(
                select(ShopUser).where(ShopUser.referral_code == referred_by_code)
            )
            referrer = ref_result.scalar_one_or_none()
            if referrer and referrer.telegram_id != telegram_id:
                referred_by_id = referrer.telegram_id

        code = _generate_referral_code()
        while True:
            existing = await session.execute(
                select(ShopUser).where(ShopUser.referral_code == code)
            )
            if not existing.scalar_one_or_none():
                break
            code = _generate_referral_code()

        user = ShopUser(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            referral_code=code,
            referred_by=referred_by_id,
        )
        session.add(user)
        await session.flush()
        logger.info("shop_user_created", telegram_id=telegram_id)
        return user


async def get_shop_user(telegram_id: int) -> ShopUser | None:
    async with db_session() as session:
        result = await session.execute(
            select(ShopUser).where(ShopUser.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


async def award_xp(telegram_id: int, xp_type: str, bonus_xp: int = 0) -> tuple[int, bool, UserLevel]:
    """Award XP and return (new_xp, leveled_up, new_level)."""
    xp_amount = XP_RATES.get(xp_type, 5) + bonus_xp

    async with db_session() as session:
        result = await session.execute(
            select(ShopUser).where(ShopUser.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            return 0, False, UserLevel.BRONZE

        old_level = user.level
        user.xp += xp_amount
        new_level = _xp_to_level(user.xp)
        leveled_up = new_level != old_level
        if leveled_up:
            user.level = new_level
            logger.info("user_leveled_up", telegram_id=telegram_id, old=old_level, new=new_level)

        return user.xp, leveled_up, new_level


async def update_vip_after_purchase(telegram_id: int) -> tuple[VIPTier, bool]:
    """Recalculate VIP tier after a purchase. Returns (new_tier, upgraded)."""
    async with db_session() as session:
        result = await session.execute(
            select(ShopUser).where(ShopUser.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            return VIPTier.BASIC, False

        old_tier = user.vip_tier
        new_tier = _spend_to_vip(user.total_spent)
        upgraded = new_tier != old_tier and (
            list(VIPTier).index(new_tier) > list(VIPTier).index(old_tier)
        )
        if upgraded:
            user.vip_tier = new_tier
            logger.info("vip_upgraded", telegram_id=telegram_id, old=old_tier, new=new_tier)

        return new_tier, upgraded


def get_user_discount(user: ShopUser) -> float:
    """Get the best applicable discount for a user (level + VIP)."""
    level_discount = LEVEL_DISCOUNTS.get(user.level, 0.0)
    vip_discount = VIP_DISCOUNTS.get(user.vip_tier, 0.0)
    return max(level_discount, vip_discount)


def get_user_priority(user: ShopUser) -> str:
    if user.vip_tier == VIPTier.ELITE:
        return "high"
    if user.vip_tier == VIPTier.PRO:
        return "normal"
    return "low"


def xp_to_next_level(user: ShopUser) -> tuple[int, int]:
    """Returns (xp_needed, xp_to_next)."""
    levels = list(LEVEL_THRESHOLDS.items())
    levels.sort(key=lambda x: x[1])
    for i, (lvl, threshold) in enumerate(levels):
        if lvl == user.level:
            if i + 1 < len(levels):
                next_threshold = levels[i + 1][1]
                return next_threshold - user.xp, next_threshold
            return 0, user.xp
    return 0, user.xp


async def format_user_profile_text(user: ShopUser) -> str:
    xp_needed, next_threshold = xp_to_next_level(user)
    level_name = LEVEL_NAMES_AR.get(user.level, user.level)
    vip_name = VIP_NAMES_AR.get(user.vip_tier, user.vip_tier)
    discount = get_user_discount(user) * 100

    vip_status = f"⭐ {vip_name}"
    if user.vip_expires_at:
        days_left = (user.vip_expires_at - datetime.now(tz=UTC)).days
        vip_status += f" (تنتهي بعد {days_left} يوم)"

    next_level_text = ""
    if xp_needed > 0:
        next_level_text = f"\n📈 تحتاج {xp_needed} XP للمستوى التالي"

    return (
        f"👤 *ملف حسابك*\n\n"
        f"🏆 المستوى: *{level_name}*\n"
        f"✨ النقاط (XP): `{user.xp:,}`{next_level_text}\n"
        f"{vip_status}\n\n"
        f"💰 الرصيد: `{user.balance:.2f}$`\n"
        f"📦 إجمالي الطلبات: `{user.total_orders}`\n"
        f"💸 إجمالي الإنفاق: `{user.total_spent:.2f}$`\n"
        f"🎁 خصمك الحالي: `{discount:.0f}%`\n\n"
        f"🔗 كود الإحالة: `{user.referral_code}`"
    )
