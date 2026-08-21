"""
Quotes System
=============
Commands:
  /quote          — random English/Arabic quote
  /quote ar       — Arabic quote (forismatic)
  /savequote      — save last quote to favourites (Redis)
  /myquotes       — list saved quotes
  /dailyquote on  — schedule a daily quote (via PTB JobQueue)
  /dailyquote off — disable daily quote

API waterfall:
  1. https://api.quotable.io/random          (English)
  2. https://forismatic.com/en/api/          (English / Arabic)
  3. https://type.fit/api/quotes             (English, local pick)
"""
from __future__ import annotations

import json
import random

import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config.settings import get_settings
from src.features.rate_limiter import rate_limit_check
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=8)
_RATE_LIMIT = 10
_RATE_WINDOW = 60


# ── API helpers ───────────────────────────────────────────────────────────────

async def _fetch_quotable() -> dict[str, str] | None:
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
            async with s.get("https://api.quotable.io/random") as r:
                if r.status == 200:
                    data = await r.json()
                    return {"text": data["content"], "author": data["author"]}
    except Exception:
        pass
    return None


async def _fetch_forismatic(lang: str = "en") -> dict[str, str] | None:
    try:
        params = {"method": "getQuote", "format": "json", "lang": lang}
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
            async with s.post("https://forismatic.com/en/api/", data=params) as r:
                if r.status == 200:
                    raw = await r.text()
                    # forismatic sometimes returns malformed JSON
                    raw = raw.replace("\\'", "'")
                    data = json.loads(raw)
                    return {
                        "text": data.get("quoteText", "").strip(),
                        "author": data.get("quoteAuthor", "Unknown").strip() or "Unknown",
                    }
    except Exception:
        pass
    return None


_TYPEFIT_CACHE: list[dict] = []


async def _fetch_typefit() -> dict[str, str] | None:
    global _TYPEFIT_CACHE
    try:
        if not _TYPEFIT_CACHE:
            async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
                async with s.get("https://type.fit/api/quotes") as r:
                    if r.status == 200:
                        _TYPEFIT_CACHE = await r.json(content_type=None)
        if _TYPEFIT_CACHE:
            q = random.choice(_TYPEFIT_CACHE)
            return {
                "text": q.get("text", ""),
                "author": (q.get("author") or "Unknown").replace(", type.fit", ""),
            }
    except Exception:
        pass
    return None


async def get_random_quote(lang: str = "en") -> dict[str, str]:
    """Return a random quote, trying APIs in priority order."""
    if lang == "ar":
        q = await _fetch_forismatic("ru") or await _fetch_quotable() or await _fetch_typefit()
    else:
        q = await _fetch_quotable() or await _fetch_forismatic("en") or await _fetch_typefit()

    return q or {"text": "The only way to do great work is to love what you do.", "author": "Steve Jobs"}


# ── Favourites (Redis-backed) ─────────────────────────────────────────────────

async def _save_quote(user_id: int, quote: dict[str, str]) -> None:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}quotes:fav:{user_id}"
    entry = f"{quote['text']} — {quote['author']}"
    await redis.lpush(key, entry)
    await redis.ltrim(key, 0, 49)   # keep last 50
    await redis.expire(key, 86400 * 90)


async def _get_saved_quotes(user_id: int) -> list[str]:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}quotes:fav:{user_id}"
    items = await redis.lrange(key, 0, 9)  # return up to 10
    return items


# ── Last-quote store (for /savequote) ────────────────────────────────────────

async def _store_last_quote(user_id: int, quote: dict[str, str]) -> None:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}quotes:last:{user_id}"
    import json as _json
    await redis.setex(key, 3600, _json.dumps(quote))


async def _pop_last_quote(user_id: int) -> dict[str, str] | None:
    redis = await get_redis()
    settings = get_settings()
    key = f"{settings.redis_prefix}quotes:last:{user_id}"
    raw = await redis.get(key)
    if raw:
        import json as _json
        return _json.loads(raw)
    return None


# ── Format ────────────────────────────────────────────────────────────────────

def _format_quote(q: dict[str, str]) -> str:
    return f'💬 *"{q["text"]}"*\n\n— _{q["author"]}_'


def _quote_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💾 حفظ | Save", callback_data="quote:save"),
            InlineKeyboardButton("🔄 أخرى | Another", callback_data="quote:another"),
        ]
    ])


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_quote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message

    allowed, err = await rate_limit_check(user.id, "quote", limit=_RATE_LIMIT, window=_RATE_WINDOW)
    if not allowed:
        await msg.reply_text(err)
        return

    lang = context.args[0].lower() if context.args else "en"
    if lang not in ("en", "ar"):
        lang = "en"

    q = await get_random_quote(lang)
    await _store_last_quote(user.id, q)

    await msg.reply_text(
        _format_quote(q),
        parse_mode="Markdown",
        reply_markup=_quote_keyboard(),
    )


async def cmd_savequote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    q = await _pop_last_quote(user.id)
    if not q:
        await update.effective_message.reply_text(
            "لا يوجد اقتباس لحفظه. استخدم /quote أولاً | No quote to save. Use /quote first."
        )
        return
    await _save_quote(user.id, q)
    await update.effective_message.reply_text("✅ تم حفظ الاقتباس في مفضلتك | Quote saved to favourites.")


async def cmd_myquotes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    quotes = await _get_saved_quotes(user.id)
    if not quotes:
        await update.effective_message.reply_text(
            "📚 لا توجد اقتباسات محفوظة | No saved quotes yet.\n"
            "استخدم /quote ثم 💾 للحفظ | Use /quote then 💾 to save."
        )
        return
    lines = ["📚 *اقتباساتك المفضلة | Your saved quotes:*\n"]
    for i, q in enumerate(quotes, 1):
        lines.append(f"{i}. {q[:200]}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_dailyquote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    msg = update.effective_message

    if not context.args or context.args[0].lower() not in ("on", "off"):
        await msg.reply_text("Usage: /dailyquote on | /dailyquote off")
        return

    mode = context.args[0].lower()
    job_name = f"daily_quote:{chat.id}:{user.id}"

    if mode == "on":
        # Remove existing job first (idempotent)
        current = context.job_queue.get_jobs_by_name(job_name)
        for j in current:
            j.schedule_removal()

        import datetime as dt
        # Schedule at 9:00 AM UTC every day
        context.job_queue.run_daily(
            _daily_quote_job,
            time=dt.time(hour=9, minute=0, tzinfo=dt.UTC),
            chat_id=chat.id,
            user_id=user.id,
            name=job_name,
        )
        await msg.reply_text("✅ سيتم إرسال اقتباس يومياً في 9 صباحاً UTC | Daily quote scheduled at 9 AM UTC.")
    else:
        current = context.job_queue.get_jobs_by_name(job_name)
        for j in current:
            j.schedule_removal()
        await msg.reply_text("❌ تم إلغاء الاقتباس اليومي | Daily quote disabled.")


async def _daily_quote_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    q = await get_random_quote("en")
    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=f"🌅 *اقتباس اليوم | Quote of the Day*\n\n{_format_quote(q)}",
        parse_mode="Markdown",
    )


# ── Callback handler ──────────────────────────────────────────────────────────

async def handle_quote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    action = query.data.split(":")[1]
    user_id = query.from_user.id

    if action == "save":
        q = await _pop_last_quote(user_id)
        if q:
            await _save_quote(user_id, q)
            await query.answer("✅ تم الحفظ | Saved!", show_alert=True)
        else:
            await query.answer("لا يوجد اقتباس | No quote to save.", show_alert=True)

    elif action == "another":
        q = await get_random_quote("en")
        await _store_last_quote(user_id, q)
        await query.edit_message_text(
            _format_quote(q),
            parse_mode="Markdown",
            reply_markup=_quote_keyboard(),
        )


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("quote", cmd_quote))
    app.add_handler(CommandHandler("savequote", cmd_savequote))
    app.add_handler(CommandHandler("myquotes", cmd_myquotes))
    app.add_handler(CommandHandler("dailyquote", cmd_dailyquote))
    app.add_handler(
        CallbackQueryHandler(handle_quote_callback, pattern=r"^quote:")
    )
    logger.info("quotes_handlers_registered")
