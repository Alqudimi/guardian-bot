"""
Smart Detection Handler
=======================
Runs in handler group 1 (after the moderation pipeline) with block=False.

Auto-detects:
  1. YouTube / TikTok / SoundCloud / Instagram URLs
     → Offers inline keyboard to download
  2. Arabic Quran verse patterns
     → Shows the verse automatically
  3. Islamic greeting patterns (صباح/مساء الخير)
     → Responds with relevant azkar in private chats
  4. Direct download intent keywords (e.g. "حمل" / "download" near a URL)
     → Immediately triggers download without extra button press

All detections are lightweight (compiled regex, no I/O) before any action.
Heavy operations (download, API call) are dispatched as background tasks.
"""
from __future__ import annotations

import re
import secrets

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from config.settings import get_settings
from src.management.group_settings import get_setting
from src.utils.background_tasks import create_background_task
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)


# ── URL patterns ──────────────────────────────────────────────────────────────

_YT_RE = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)"
    r"[\w\-?=&%+#]{5,}",
    re.IGNORECASE,
)
_TT_RE = re.compile(
    r"https?://(?:www\.)?(?:tiktok\.com/@[\w.]+/video/|vm\.tiktok\.com/|tiktok\.com/t/)"
    r"[\w\-]+",
    re.IGNORECASE,
)
_SC_RE = re.compile(
    r"https?://(?:www\.)?soundcloud\.com/[\w\-/]+",
    re.IGNORECASE,
)
_IG_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[\w\-]+",
    re.IGNORECASE,
)

# Patterns that suggest the user wants to download now
_DOWNLOAD_INTENT_RE = re.compile(
    r"\b(?:حمل|حمله|تحميل|download|dl|تنزيل|save)\b",
    re.IGNORECASE,
)

# ── Quran patterns ────────────────────────────────────────────────────────────
# Matches: "2:255", "البقرة:255", "quran 2 255", "آية الكرسي"

_QURAN_NUM_RE = re.compile(
    r"(?:quran|قرآن|آية|ayah|verse)[\s:]+(\d{1,3})[:\s]+(\d{1,3})",
    re.IGNORECASE,
)

_QURAN_NAMED_VERSES: dict[str, tuple[int, int]] = {
    "آية الكرسي":         (2, 255),
    "الفاتحة":            (1, 1),
    "قل هو الله أحد":    (112, 1),
    "المعوذتين":         (113, 1),
    "آية النور":         (24, 35),
    "آية السيف":         (9, 5),
    "surah fatiha":      (1, 1),
    "ayat al kursi":     (2, 255),
    "throne verse":      (2, 255),
}

# ── Islamic greetings ─────────────────────────────────────────────────────────

_MORNING_RE = re.compile(r"صباح\s*الخير|good\s*morning|صباح\s*النور", re.IGNORECASE)
_EVENING_RE = re.compile(r"مساء\s*الخير|good\s*evening|مساء\s*النور", re.IGNORECASE)
_AUTO_RESPONSE_TTL_SECONDS = 30


async def _group_smart_enabled(chat_id: int) -> bool:
    try:
        return await get_setting(chat_id, "smart_responses") == "on"
    except Exception as exc:
        logger.warning("smart_setting_unavailable", chat_id=chat_id, error=type(exc).__name__)
        return False


async def _reserve_auto_response(chat_id: int, response_type: str) -> bool:
    try:
        redis = await get_redis()
        key = f"{get_settings().redis_prefix}smart_auto:{chat_id}:{response_type}"
        return bool(
            await redis.set(
                key,
                "1",
                ex=_AUTO_RESPONSE_TTL_SECONDS,
                nx=True,
            )
        )
    except Exception as exc:
        logger.warning("smart_response_rate_limit_unavailable", error=type(exc).__name__)
        return False


# ── Smart message handler ─────────────────────────────────────────────────────

async def handle_smart_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not msg or not msg.text or not chat:
        return

    text = msg.text
    is_private = chat.type == "private"

    # ── 1. URL detection ──────────────────────────────────────────────────────
    has_download_intent = bool(_DOWNLOAD_INTENT_RE.search(text))

    yt_match = _YT_RE.search(text)
    tt_match = _TT_RE.search(text)
    sc_match = _SC_RE.search(text)
    ig_match = _IG_RE.search(text)

    media_url = None
    media_type = None

    if yt_match or tt_match:
        media_url = (yt_match or tt_match).group(0)
        media_type = "yt"
    elif sc_match:
        media_url = sc_match.group(0)
        media_type = "sc"
    elif ig_match:
        media_url = ig_match.group(0)
        media_type = "ig"

    if media_url and media_type:
        if has_download_intent:
            # User clearly wants to download — start immediately
            await _auto_download(update, context, media_url, media_type)
        elif is_private or await _group_smart_enabled(chat.id):
            # Offer inline keyboard only when automatic group responses are enabled.
            await _offer_download(msg, media_url, media_type)
        return

    # ── 2. Named Quran verse ──────────────────────────────────────────────────
    for phrase, (surah, ayah) in _QURAN_NAMED_VERSES.items():
        if phrase.lower() in text.lower():
            if is_private or (
                await _group_smart_enabled(chat.id)
                and await _reserve_auto_response(chat.id, "quran")
            ):
                create_background_task(
                    _send_quran_verse(chat.id, surah, ayah, context.bot),
                    name=f"smart-quran:{chat.id}:{surah}:{ayah}",
                )
            return

    # ── 3. Numeric Quran reference ────────────────────────────────────────────
    q_match = _QURAN_NUM_RE.search(text)
    if q_match:
        try:
            surah = int(q_match.group(1))
            ayah = int(q_match.group(2))
            if 1 <= surah <= 114 and 1 <= ayah <= 300:
                if is_private or (
                    await _group_smart_enabled(chat.id)
                    and await _reserve_auto_response(chat.id, "quran")
                ):
                    create_background_task(
                        _send_quran_verse(chat.id, surah, ayah, context.bot),
                        name=f"smart-quran:{chat.id}:{surah}:{ayah}",
                    )
        except (ValueError, IndexError):
            pass
        return

    # ── 4. Islamic greetings (private chat only) ──────────────────────────────
    if is_private:
        if _MORNING_RE.search(text):
            create_background_task(
                _send_azkar_auto(chat.id, "morning", context.bot),
                name=f"smart-azkar:{chat.id}:morning",
            )
        elif _EVENING_RE.search(text):
            create_background_task(
                _send_azkar_auto(chat.id, "evening", context.bot),
                name=f"smart-azkar:{chat.id}:evening",
            )


# ── Background helpers ────────────────────────────────────────────────────────

async def _create_download_token(chat_id: int, user_id: int, url: str) -> str | None:
    """Store a short-lived target because Telegram callback data is size-limited."""
    try:
        token = secrets.token_urlsafe(8)
        redis = await get_redis()
        key = f"{get_settings().redis_prefix}smart_dl:{chat_id}:{user_id}:{token}"
        await redis.setex(key, 600, url)
        return token
    except Exception as exc:
        logger.warning("smart_download_token_store_failed", error=type(exc).__name__)
        return None


async def _consume_download_token(chat_id: int, user_id: int, token: str) -> str | None:
    try:
        redis = await get_redis()
        key = f"{get_settings().redis_prefix}smart_dl:{chat_id}:{user_id}:{token}"
        return await redis.getdel(key)
    except Exception as exc:
        logger.warning("smart_download_token_read_failed", error=type(exc).__name__)
        return None


async def _offer_download(msg, url: str, media_type: str) -> None:
    """Send a non-intrusive inline keyboard offering to download."""
    chat = getattr(msg, "chat", None)
    author = getattr(msg, "from_user", None)
    if not chat or not author:
        return
    token = await _create_download_token(chat.id, author.id, url)
    if not token:
        await msg.reply_text("❌ تعذر تجهيز رابط التنزيل الآمن، يرجى المحاولة لاحقاً.")
        return

    type_labels = {
        "yt": "🎬 يوتيوب/تيك توك",
        "sc": "🎵 SoundCloud",
        "ig": "📷 Instagram",
    }
    label = type_labels.get(media_type, "🔗 Media")

    rows = [[
        InlineKeyboardButton(
            "⬇️ تحميل فيديو | Download Video",
            callback_data=f"smart_dl:{media_type}:video:{token}",
        ),
    ]]
    if media_type == "yt":
        rows.append([
            InlineKeyboardButton(
                "🎵 تحميل صوت | Download Audio",
                callback_data=f"smart_dl:{media_type}:audio:{token}",
            ),
        ])
    keyboard = InlineKeyboardMarkup(rows)

    try:
        await msg.reply_text(
            f"🔗 تم اكتشاف رابط {label}\n"
            f"`{url[:60]}{'…' if len(url) > 60 else ''}`\n\n"
            "هل تريد تحميله؟ | Want to download it?",
            reply_markup=keyboard,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
    except Exception as exc:
        logger.debug("smart_detect_offer_error", error=str(exc))


async def _auto_download(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    media_type: str,
) -> None:
    """Start download immediately (user expressed download intent)."""
    if media_type == "yt":
        from src.features.media_downloader import _download_and_send
        create_background_task(
            _download_and_send(update, url, audio_only=False, bot=context.bot),
            name=f"smart-video:{update.effective_user.id}",
        )
    elif media_type == "sc":
        from src.features.soundcloud import _download_sc
        create_background_task(
            _download_sc(update, url, bot=context.bot),
            name=f"smart-soundcloud:{update.effective_user.id}",
        )
    elif media_type == "ig":
        from src.features.instagram import _download_ig
        create_background_task(
            _download_ig(update, url, bot=context.bot),
            name=f"smart-instagram:{update.effective_user.id}",
        )


async def _send_quran_verse(chat_id: int, surah: int, ayah: int, bot) -> None:
    from src.features.quran import _fetch_ayah, _format_ayah
    result = await _fetch_ayah(surah, ayah)
    if result:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=_format_ayah(result),
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.debug("smart_quran_send_error", error=str(exc))


async def _send_azkar_auto(chat_id: int, category: str, bot) -> None:
    from src.features.azkar import _build_azkar_keyboard, _format_zikr, _get_azkar
    azkar = await _get_azkar(category)
    if not azkar:
        return
    try:
        import random
        idx = random.randint(0, min(2, len(azkar) - 1))
        await bot.send_message(
            chat_id=chat_id,
            text=_format_zikr(azkar[idx], idx + 1, len(azkar)),
            parse_mode="Markdown",
            reply_markup=_build_azkar_keyboard(category, idx, len(azkar)),
        )
    except Exception as exc:
        logger.debug("smart_azkar_send_error", error=str(exc))


# ── Callback for inline download buttons ──────────────────────────────────────

async def handle_smart_dl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer("⏬ جاري البدء... | Starting download...")

    parts = (query.data or "").split(":", 3)
    if len(parts) < 4 or not query.message or not query.message.chat:
        return

    _, media_type, mode, token = parts
    if media_type not in {"yt", "sc", "ig"} or mode not in {"video", "audio"}:
        await query.answer("❌ رابط التنزيل غير صالح", show_alert=True)
        return
    url = await _consume_download_token(
        query.message.chat.id, query.from_user.id, token
    )
    if not url:
        await query.answer("❌ انتهت صلاحية رابط التنزيل أو لا يخصك", show_alert=True)
        return
    audio_only = mode == "audio"

    # Delete the offer message
    try:
        await query.message.delete()
    except Exception:
        pass

    # Adapt the callback's existing Telegram objects to the downloader contract.
    # The downloader still sends through context.bot and the real Bot API.
    class _CallbackUpdateAdapter:
        """Minimal update adapter for a callback-originated download request."""
        effective_user = query.from_user
        effective_chat = query.message.chat
        effective_message = query.message

    callback_update = _CallbackUpdateAdapter()

    if media_type == "yt":
        from src.features.media_downloader import _download_and_send
        create_background_task(
            _download_and_send(callback_update, url, audio_only=audio_only, bot=context.bot),
            name=f"smart-callback-video:{query.from_user.id}",
        )
    elif media_type == "sc":
        from src.features.soundcloud import _download_sc
        create_background_task(
            _download_sc(callback_update, url, bot=context.bot),
            name=f"smart-callback-soundcloud:{query.from_user.id}",
        )
    elif media_type == "ig":
        from src.features.instagram import _download_ig
        create_background_task(
            _download_ig(callback_update, url, bot=context.bot),
            name=f"smart-callback-instagram:{query.from_user.id}",
        )


def register_handlers(app) -> None:
    # Smart message handler in group 1 (runs after moderation pipeline)
    app.add_handler(
        MessageHandler(
            filters.TEXT & (~filters.COMMAND),
            handle_smart_message,
            block=False,
        ),
        group=1,
    )
    # Callback handler for the inline download keyboard
    app.add_handler(
        CallbackQueryHandler(handle_smart_dl_callback, pattern=r"^smart_dl:"),
        group=1,
    )
    logger.info("smart_detect_handlers_registered")
