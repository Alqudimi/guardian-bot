"""
Azkar Module
============
Commands:
  /azkar                — random dhikr from any category
  /azkar morning        — أذكار الصباح (Morning Azkar)
  /azkar evening        — أذكار المساء (Evening Azkar)
  /azkar sleep          — أذكار النوم  (Sleep Azkar)
  /azkar_schedule on    — auto-send morning/evening azkar at correct times
  /azkar_schedule off   — disable auto-schedule

API: https://api.aladhan.com/azkar (community)
     fallback → embedded local JSON data (always available)
"""
from __future__ import annotations

import datetime
import random

import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from src.features.rate_limiter import rate_limit_check
from src.utils.logger import get_logger

logger = get_logger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=8)
_RATE_LIMIT = 20
_RATE_WINDOW = 60

# ── Local fallback Azkar data ─────────────────────────────────────────────────
# A curated subset — the bot uses the API first and falls back to this.

_LOCAL_AZKAR: dict[str, list[dict]] = {
    "morning": [
        {
            "zikr": "أَصْبَحْنَا وَأَصْبَحَ الْمُلْكُ لِلَّهِ، وَالْحَمْدُ لِلَّهِ، لاَ إِلَـهَ إِلاَّ اللهُ وَحْدَهُ لاَ شَرِيكَ لَهُ، لَهُ الْمُلْكُ وَلَهُ الْحَمْدُ وَهُوَ عَلَى كُلِّ شَيْءٍ قَدِيرٌ",
            "count": "مرة واحدة",
            "description": "أذكار الصباح",
        },
        {
            "zikr": "اللَّهُمَّ بِكَ أَصْبَحْنَا، وَبِكَ أَمْسَيْنَا، وَبِكَ نَحْيَا، وَبِكَ نَمُوتُ وَإِلَيْكَ النُّشُورُ",
            "count": "مرة واحدة",
            "description": "أذكار الصباح",
        },
        {
            "zikr": "اللَّهُمَّ أَنْتَ رَبِّي لاَ إِلَهَ إِلاَّ أَنْتَ، خَلَقْتَنِي وَأَنَا عَبْدُكَ، وَأَنَا عَلَى عَهْدِكَ وَوَعْدِكَ مَا اسْتَطَعْتُ، أَعُوذُ بِكَ مِنْ شَرِّ مَا صَنَعْتُ، أَبُوءُ لَكَ بِنِعْمَتِكَ عَلَيَّ، وَأَبُوءُ لَكَ بِذَنْبِي فَاغْفِرْ لِي فَإِنَّهُ لاَ يَغْفِرُ الذُّنُوبَ إِلاَّ أَنْتَ",
            "count": "مرة واحدة",
            "description": "سيد الاستغفار",
        },
        {
            "zikr": "بِسْمِ اللَّهِ الَّذِي لاَ يَضُرُّ مَعَ اسْمِهِ شَيْءٌ فِي الأَرْضِ وَلاَ فِي السَّمَاءِ وَهُوَ السَّمِيعُ الْعَلِيمُ",
            "count": "3 مرات",
            "description": "حصن من كل شيء",
        },
        {
            "zikr": "رَضِيتُ بِاللَّهِ رَبًّا، وَبِالإِسْلامِ دِيناً، وَبِمُحَمَّدٍ صَلَّى اللهُ عَلَيْهِ وَسَلَّمَ نَبِيًّا وَرَسُولاً",
            "count": "3 مرات",
            "description": "أذكار الصباح",
        },
        {
            "zikr": "سُبْحَانَ اللَّهِ وَبِحَمْدِهِ",
            "count": "100 مرة",
            "description": "تُحَطُّ بها الخطايا",
        },
        {
            "zikr": "لاَ إِلَهَ إِلاَّ اللَّهُ وَحْدَهُ لاَ شَرِيكَ لَهُ، لَهُ الْمُلْكُ وَلَهُ الْحَمْدُ وَهُوَ عَلَى كُلِّ شَيْءٍ قَدِيرٌ",
            "count": "100 مرة",
            "description": "عِدلُ عشرة رقاب",
        },
    ],
    "evening": [
        {
            "zikr": "أَمْسَيْنَا وَأَمْسَى الْمُلْكُ لِلَّهِ، وَالْحَمْدُ لِلَّهِ، لاَ إِلَـهَ إِلاَّ اللهُ وَحْدَهُ لاَ شَرِيكَ لَهُ، لَهُ الْمُلْكُ وَلَهُ الْحَمْدُ وَهُوَ عَلَى كُلِّ شَيْءٍ قَدِيرٌ",
            "count": "مرة واحدة",
            "description": "أذكار المساء",
        },
        {
            "zikr": "اللَّهُمَّ بِكَ أَمْسَيْنَا، وَبِكَ أَصْبَحْنَا، وَبِكَ نَحْيَا، وَبِكَ نَمُوتُ، وَإِلَيْكَ الْمَصِيرُ",
            "count": "مرة واحدة",
            "description": "أذكار المساء",
        },
        {
            "zikr": "اللَّهُمَّ أَنْتَ رَبِّي لاَ إِلَهَ إِلاَّ أَنْتَ خَلَقْتَنِي وَأَنَا عَبْدُكَ",
            "count": "مرة واحدة",
            "description": "سيد الاستغفار - المساء",
        },
        {
            "zikr": "بِسْمِ اللَّهِ الَّذِي لاَ يَضُرُّ مَعَ اسْمِهِ شَيْءٌ فِي الأَرْضِ وَلاَ فِي السَّمَاءِ وَهُوَ السَّمِيعُ الْعَلِيمُ",
            "count": "3 مرات",
            "description": "حصن من كل شيء",
        },
        {
            "zikr": "أَعُوذُ بِكَلِمَاتِ اللَّهِ التَّامَّاتِ مِنْ شَرِّ مَا خَلَقَ",
            "count": "3 مرات",
            "description": "أذكار المساء",
        },
        {
            "zikr": "اللَّهُمَّ عَافِنِي فِي بَدَنِي، اللَّهُمَّ عَافِنِي فِي سَمْعِي، اللَّهُمَّ عَافِنِي فِي بَصَرِي، لاَ إِلَهَ إِلاَّ أَنْتَ",
            "count": "3 مرات",
            "description": "أذكار المساء",
        },
    ],
    "sleep": [
        {
            "zikr": "بِاسْمِكَ اللَّهُمَّ أَمُوتُ وَأَحْيَا",
            "count": "مرة واحدة",
            "description": "عند النوم",
        },
        {
            "zikr": "اللَّهُمَّ إِنَّكَ خَلَقْتَ نَفْسِي وَأَنْتَ تَتَوَفَّاهَا، لَكَ مَمَاتُهَا وَمَحْيَاهَا، إِنْ أَحْيَيْتَهَا فَاحْفَظْهَا، وَإِنْ أَمَتَّهَا فَاغْفِرْ لَهَا. اللَّهُمَّ إِنِّي أَسْأَلُكَ الْعَافِيَةَ",
            "count": "مرة واحدة",
            "description": "عند النوم",
        },
        {
            "zikr": "سُبْحَانَ اللَّهِ",
            "count": "33 مرة",
            "description": "تسبيح النوم",
        },
        {
            "zikr": "الْحَمْدُ لِلَّهِ",
            "count": "33 مرة",
            "description": "تسبيح النوم",
        },
        {
            "zikr": "اللَّهُ أَكْبَرُ",
            "count": "34 مرة",
            "description": "تسبيح النوم",
        },
        {
            "zikr": "آيَةُ الْكُرْسِيِّ: اللَّهُ لَا إِلَهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ لَا تَأْخُذُهُ سِنَةٌ وَلَا نَوْمٌ…",
            "count": "مرة واحدة",
            "description": "حفظ طوال الليل",
        },
        {
            "zikr": "قُلْ هُوَ اللَّهُ أَحَدٌ — قُلْ أَعُوذُ بِرَبِّ الْفَلَقِ — قُلْ أَعُوذُ بِرَبِّ النَّاسِ",
            "count": "3 مرات",
            "description": "المعوذات",
        },
    ],
}

_CATEGORIES_AR = {
    "morning": "الصباح ☀️",
    "evening": "المساء 🌙",
    "sleep":   "النوم 😴",
}


# ── API fetch ─────────────────────────────────────────────────────────────────

async def _fetch_api_azkar(category: str) -> list[dict] | None:
    """Try nawafalqari azkar-api."""
    # Map category to API parameter
    cat_map = {"morning": "اذكار الصباح", "evening": "اذكار المساء", "sleep": "أذكار النوم"}
    cat_ar = cat_map.get(category)
    if not cat_ar:
        return None
    try:
        url = "https://raw.githubusercontent.com/nawafalqari/azkar-api/main/azkar.json"
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as s, s.get(url) as r:
            if r.status != 200:
                return None
            data = await r.json(content_type=None)
            for section in data:
                if isinstance(section, dict) and section.get("category") == cat_ar:
                    return section.get("array", [])
    except Exception as exc:
        logger.debug("azkar_api_failed", error=str(exc))
    return None


async def _get_azkar(category: str) -> list[dict]:
    """Fetch azkar with API-first, local fallback."""
    api_data = await _fetch_api_azkar(category)
    if api_data:
        # Normalize API response
        normalized = []
        for item in api_data:
            if isinstance(item, dict):
                normalized.append({
                    "zikr": item.get("zikr", item.get("text", "")),
                    "count": item.get("repeat", item.get("count", "مرة واحدة")),
                    "description": item.get("description", _CATEGORIES_AR.get(category, "")),
                })
        if normalized:
            return normalized

    return _LOCAL_AZKAR.get(category, [])


def _format_zikr(zikr: dict, index: int = 1, total: int = 1) -> str:
    lines = [f"🤲 *ذكر {index}/{total}*\n"]
    text = zikr.get("zikr", "")
    count = zikr.get("count", "")
    desc = zikr.get("description", "")

    if text:
        lines.append(f"```\n{text}\n```")
    if count:
        lines.append(f"📿 *التكرار | Repeat:* {count}")
    if desc:
        lines.append(f"ℹ️ _{desc}_")

    return "\n\n".join(lines)


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_azkar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message

    allowed, err = await rate_limit_check(user.id, "azkar", limit=_RATE_LIMIT, window=_RATE_WINDOW)
    if not allowed:
        await msg.reply_text(err)
        return

    category_input = context.args[0].lower() if context.args else ""
    cat_map = {
        "morning": "morning", "صباح": "morning", "الصباح": "morning",
        "evening": "evening", "مساء": "evening", "المساء": "evening",
        "sleep":   "sleep",   "نوم":  "sleep",   "النوم":  "sleep",
    }
    category = cat_map.get(category_input, "")

    if not category:
        # Show category picker
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("☀️ الصباح | Morning", callback_data="azkar:cat:morning:0"),
                InlineKeyboardButton("🌙 المساء | Evening", callback_data="azkar:cat:evening:0"),
            ],
            [
                InlineKeyboardButton("😴 النوم | Sleep", callback_data="azkar:cat:sleep:0"),
            ],
        ])
        await msg.reply_text(
            "🤲 *الأذكار | Islamic Remembrance*\n\n"
            "اختر نوع الأذكار | Choose category:",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return

    status = await msg.reply_text(f"⏳ جاري تحميل أذكار {_CATEGORIES_AR.get(category, category)}...")
    azkar = await _get_azkar(category)

    if not azkar:
        await status.edit_text("❌ لم يتم العثور على أذكار | No azkar found.")
        return

    zikr = azkar[0]
    total = len(azkar)

    keyboard = _build_azkar_keyboard(category, 0, total)
    await status.edit_text(
        _format_zikr(zikr, 1, total),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


def _build_azkar_keyboard(category: str, index: int, total: int) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    if index > 0:
        row.append(InlineKeyboardButton("◀️ السابق", callback_data=f"azkar:cat:{category}:{index - 1}"))
    if index < total - 1:
        row.append(InlineKeyboardButton("التالي ▶️", callback_data=f"azkar:cat:{category}:{index + 1}"))
    if row:
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton("🔀 أذكار عشوائية | Random", callback_data=f"azkar:random:{category}"),
    ])
    return InlineKeyboardMarkup(buttons)


async def cmd_azkar_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Schedule automatic morning and evening azkar delivery."""
    msg = update.effective_message
    chat = update.effective_chat

    if not context.args or context.args[0].lower() not in ("on", "off"):
        await msg.reply_text("Usage: /azkar_schedule on | /azkar_schedule off")
        return

    mode = context.args[0].lower()

    for cat in ("morning", "evening"):
        job_name = f"azkar_schedule:{cat}:{chat.id}"
        for j in context.job_queue.get_jobs_by_name(job_name):
            j.schedule_removal()

    if mode == "on":
        # Morning: 6:00 AM UTC  |  Evening: 4:00 PM UTC
        for cat, hour in (("morning", 6), ("evening", 16)):
            job_name = f"azkar_schedule:{cat}:{chat.id}"
            context.job_queue.run_daily(
                _azkar_job,
                time=datetime.time(hour=hour, minute=0, tzinfo=datetime.UTC),
                chat_id=chat.id,
                data=cat,
                name=job_name,
            )
        await msg.reply_text(
            "✅ سيتم إرسال الأذكار تلقائياً:\n"
            "• أذكار الصباح — 6:00 صباحاً UTC\n"
            "• أذكار المساء — 4:00 مساءً UTC"
        )
    else:
        await msg.reply_text("❌ تم إلغاء جدول الأذكار | Azkar schedule disabled.")


async def _azkar_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    category = context.job.data
    azkar = await _get_azkar(category)
    if not azkar:
        return

    # Send first 3 azkar of the category
    header = f"🤲 *أذكار {_CATEGORIES_AR.get(category, category)}*\n\n"
    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=header + _format_zikr(azkar[0], 1, len(azkar)),
        parse_mode="Markdown",
        reply_markup=_build_azkar_keyboard(category, 0, len(azkar)),
    )


# ── Callback handler ──────────────────────────────────────────────────────────

# Cache azkar per-category for callbacks (avoid re-fetching repeatedly)
_azkar_cache: dict[str, list[dict]] = {}


async def handle_azkar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()

    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "cat":
        category = parts[2] if len(parts) > 2 else "morning"
        try:
            index = int(parts[3]) if len(parts) > 3 else 0
        except ValueError:
            index = 0

        if category not in _azkar_cache:
            _azkar_cache[category] = await _get_azkar(category)

        azkar = _azkar_cache.get(category, [])
        if not azkar:
            await query.edit_message_text("❌ لا توجد أذكار | No azkar found.")
            return

        index = max(0, min(index, len(azkar) - 1))
        await query.edit_message_text(
            _format_zikr(azkar[index], index + 1, len(azkar)),
            parse_mode="Markdown",
            reply_markup=_build_azkar_keyboard(category, index, len(azkar)),
        )

    elif action == "random":
        category = parts[2] if len(parts) > 2 else "morning"
        if category not in _azkar_cache:
            _azkar_cache[category] = await _get_azkar(category)

        azkar = _azkar_cache.get(category, [])
        if not azkar:
            return

        index = random.randint(0, len(azkar) - 1)
        await query.edit_message_text(
            _format_zikr(azkar[index], index + 1, len(azkar)),
            parse_mode="Markdown",
            reply_markup=_build_azkar_keyboard(category, index, len(azkar)),
        )


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("azkar", cmd_azkar))
    app.add_handler(CommandHandler("azkar_schedule", cmd_azkar_schedule))
    app.add_handler(CallbackQueryHandler(handle_azkar_callback, pattern=r"^azkar:"))
    logger.info("azkar_handlers_registered")
