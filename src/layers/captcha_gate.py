"""
CAPTCHA Gate — New Member Verification
=======================================
Requires new members to solve a simple inline-button challenge before
they can send messages in the group.

Flow:
  1. User joins → bot restricts all permissions + sends welcome challenge
  2. User clicks the correct button (random number / emoji / math)
  3. Bot lifts restrictions and sends welcome message
  4. If user doesn't respond within timeout → kick (not ban)

Challenge types (randomly selected per join):
  • Math: "What is 7 + 5?" with 3 button options (one correct)
  • Emoji: "Click the 🐱" with 4 emoji buttons (one correct)
  • Number: "Click the highest number" with 3 options

Security:
  • Challenge bound to (user_id, chat_id) via Redis with TTL
  • Correct answer stored server-side (button labels are not trusted)
  • Auto-kick after CAPTCHA_TIMEOUT_S if not solved
  • Bot accounts are excluded from CAPTCHA
  • Admins and whitelisted users bypass CAPTCHA

Per-group configuration (via /setcaptcha on|off):
  • Enabled/disabled per group
  • Timeout configurable (30s-300s, default 60s)
"""
from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass
from secrets import SystemRandom

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from config.settings import get_settings
from src.utils.background_tasks import create_background_task
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

CAPTCHA_TIMEOUT_S = 60        # Default seconds to solve
_KEY_PREFIX = "captcha:"
_captcha_tasks: dict[tuple[int, int], asyncio.Task] = {}
_rng = SystemRandom()


@dataclass
class CaptchaChallenge:
    question: str
    correct_answer: str
    options: list[str]       # All button options (shuffled)
    created_at: float


def _make_math_challenge() -> CaptchaChallenge:
    a = _rng.randint(2, 9)
    b = _rng.randint(2, 9)
    correct = a + b
    wrong1 = correct + _rng.randint(1, 4)
    wrong2 = correct - _rng.randint(1, 4)
    if wrong2 <= 0:
        wrong2 = correct + 5
    options = [str(correct), str(wrong1), str(wrong2)]
    _rng.shuffle(options)
    return CaptchaChallenge(
        question=f"🔐 كم يساوي {a} + {b}؟\n\n🔐 What is {a} + {b}?",
        correct_answer=str(correct),
        options=options,
        created_at=time.time(),
    )


def _make_emoji_challenge() -> CaptchaChallenge:
    emoji_pool = ["🐱", "🐶", "🌟", "🍎", "🚀", "🎵", "🌊", "🦁", "🌹", "⚡"]
    _rng.shuffle(emoji_pool)
    target = emoji_pool[0]
    options = [target, *emoji_pool[1:3]]
    _rng.shuffle(options)
    return CaptchaChallenge(
        question=f"👇 اضغط على: {target}\n\n👇 Click: {target}",
        correct_answer=target,
        options=options,
        created_at=time.time(),
    )


def _make_number_challenge() -> CaptchaChallenge:
    nums = _rng.sample(range(10, 99), 3)
    correct = str(max(nums))
    options = [str(n) for n in nums]
    _rng.shuffle(options)
    return CaptchaChallenge(
        question="🔢 اضغط على أكبر رقم\n\n🔢 Click the largest number",
        correct_answer=correct,
        options=options,
        created_at=time.time(),
    )


def _generate_challenge() -> CaptchaChallenge:
    generators = [_make_math_challenge, _make_emoji_challenge, _make_number_challenge]
    return _rng.choice(generators)()


async def is_captcha_enabled(chat_id: int) -> bool:
    """Check CAPTCHA through the canonical per-group settings hash."""
    from src.management.group_settings import get_setting

    return (await get_setting(chat_id, "captcha")) == "on"


async def set_captcha_enabled(chat_id: int, enabled: bool) -> None:
    """Persist CAPTCHA through the canonical per-group settings manager."""
    from src.management.group_settings import set_setting

    await set_setting(chat_id, "captcha", "on" if enabled else "off")


async def _store_challenge(chat_id: int, user_id: int, challenge: CaptchaChallenge) -> None:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}{_KEY_PREFIX}{chat_id}:{user_id}"
    await redis.hset(key, mapping={
        "answer": challenge.correct_answer,
        "created_at": challenge.created_at,
    })
    await redis.expire(key, CAPTCHA_TIMEOUT_S + 10)


async def _get_stored_answer(chat_id: int, user_id: int) -> str | None:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}{_KEY_PREFIX}{chat_id}:{user_id}"
    return await redis.hget(key, "answer")


async def _clear_challenge(chat_id: int, user_id: int) -> None:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}{_KEY_PREFIX}{chat_id}:{user_id}"
    await redis.delete(key)


async def _store_captcha_message_id(chat_id: int, user_id: int, message_id: int) -> None:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}{_KEY_PREFIX}msg:{chat_id}:{user_id}"
    await redis.setex(key, CAPTCHA_TIMEOUT_S + 30, str(message_id))


async def _get_captcha_message_id(chat_id: int, user_id: int) -> int | None:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}{_KEY_PREFIX}msg:{chat_id}:{user_id}"
    val = await redis.get(key)
    return int(val) if val else None


async def send_captcha_challenge(
    bot: Bot,
    chat_id: int,
    user_id: int,
    username: str | None,
) -> None:
    """
    Restrict new member and send CAPTCHA challenge.
    Called on member join events.
    """
    from telegram import ChatPermissions

    # Restrict member first (no sending)
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
        )
    except TelegramError as exc:
        logger.warning("captcha_restrict_failed", user_id=user_id, error=str(exc))
        return

    challenge = _generate_challenge()
    try:
        await _store_challenge(chat_id, user_id, challenge)
    except Exception as exc:
        logger.warning(
            "captcha_store_failed",
            chat_id=chat_id,
            user_id=user_id,
            error=type(exc).__name__,
        )
        try:
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=True),
            )
        except TelegramError as restore_exc:
            logger.warning(
                "captcha_restore_after_store_failure",
                user_id=user_id,
                error=type(restore_exc).__name__,
            )
        return

    name = f"@{username}" if username else f"#{user_id}"
    text = (
        f"👋 مرحباً {name}!\n\n"
        f"لإثبات أنك لست بوتاً، يرجى حل هذا السؤال خلال "
        f"{CAPTCHA_TIMEOUT_S} ثانية:\n\n"
        f"Welcome {name}! Prove you're human — answer within "
        f"{CAPTCHA_TIMEOUT_S}s:\n\n"
        f"{challenge.question}"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(opt, callback_data=f"captcha:{chat_id}:{user_id}:{opt}")]
        for opt in challenge.options
    ])

    try:
        msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        await _store_captcha_message_id(chat_id, user_id, msg.message_id)
        logger.info("captcha_sent", chat_id=chat_id, user_id=user_id)
    except TelegramError as exc:
        logger.warning("captcha_send_failed", error=str(exc))
        await _clear_challenge(chat_id, user_id)
        return

    # Schedule auto-kick after timeout and retain the task for cancellation on solve.
    _schedule_auto_kick(bot, chat_id, user_id)


def _schedule_auto_kick(bot: Bot, chat_id: int, user_id: int) -> None:
    key = (chat_id, user_id)
    previous = _captcha_tasks.pop(key, None)
    if previous and not previous.done():
        previous.cancel()
    _captcha_tasks[key] = create_background_task(
        _auto_kick_if_unsolved(bot, chat_id, user_id),
        name=f"captcha-timeout:{chat_id}:{user_id}",
    )


def _cancel_auto_kick(chat_id: int, user_id: int) -> None:
    task = _captcha_tasks.pop((chat_id, user_id), None)
    if task and not task.done():
        task.cancel()


async def handle_captcha_callback(bot: Bot, chat_id: int, user_id: int, answer: str) -> bool:
    """
    Validate CAPTCHA answer from callback query.
    Returns True if correct.
    """
    stored = await _get_stored_answer(chat_id, user_id)
    if stored is None:
        return False

    stored_str = stored.decode() if isinstance(stored, bytes) else stored

    if answer == stored_str:
        # Restore permissions before consuming the challenge. If Telegram rejects
        # the operation, the user can retry instead of being left locked out.
        from telegram import ChatPermissions
        try:
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_video_notes=True,
                    can_send_voice_notes=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                ),
            )
        except TelegramError as exc:
            logger.warning(
                "captcha_restore_failed",
                chat_id=chat_id,
                user_id=user_id,
                error=type(exc).__name__,
            )
            return False

        await _clear_challenge(chat_id, user_id)
        _cancel_auto_kick(chat_id, user_id)

        # Delete challenge message
        msg_id = await _get_captcha_message_id(chat_id, user_id)
        if msg_id:
            with suppress(TelegramError):
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)

        logger.info("captcha_passed", chat_id=chat_id, user_id=user_id)
        return True

    return False


async def _auto_kick_if_unsolved(bot: Bot, chat_id: int, user_id: int) -> None:
    key = (chat_id, user_id)
    try:
        await asyncio.sleep(CAPTCHA_TIMEOUT_S)
        stored = await _get_stored_answer(chat_id, user_id)
        if stored is None:
            return  # Already solved

        # Not solved — kick (not ban, so they can rejoin and try again)
        await _clear_challenge(chat_id, user_id)
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await asyncio.sleep(1)
            await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
            logger.info("captcha_timeout_kick", chat_id=chat_id, user_id=user_id)
        except TelegramError as exc:
            logger.warning("captcha_kick_failed", user_id=user_id, error=str(exc))

        # Delete challenge message
        msg_id = await _get_captcha_message_id(chat_id, user_id)
        if msg_id:
            with suppress(TelegramError):
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    finally:
        current = asyncio.current_task()
        if _captcha_tasks.get(key) is current:
            _captcha_tasks.pop(key, None)
