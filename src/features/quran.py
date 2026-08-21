"""
Quran Module
============
Commands:
  /quran <surah:ayah>   — fetch a specific verse  (e.g. /quran 2:255)
  /surah <number>       — fetch first 10 ayahs of a surah
  /random_ayah          — a random ayah with translation

API: https://api.alquran.cloud/v1/  (free, no auth required)
Editions used:
  • quran-uthmani        — Arabic text
  • en.asad              — English translation (Muhammad Asad)
"""
from __future__ import annotations

import asyncio
import random

import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from src.features.rate_limiter import rate_limit_check
from src.utils.logger import get_logger

logger = get_logger(__name__)

_BASE = "https://api.alquran.cloud/v1"
_TIMEOUT = aiohttp.ClientTimeout(total=10)
_RATE_LIMIT = 15
_RATE_WINDOW = 60

# Total ayahs in each surah (1–114)
_SURAH_LENGTHS = [
    7, 286, 200, 176, 120, 165, 206, 75, 129, 109,
    123, 111, 43, 52, 99, 128, 111, 110, 98, 135,
    112, 78, 118, 64, 77, 227, 93, 88, 69, 60,
    34, 30, 73, 54, 45, 83, 182, 88, 75, 85,
    54, 53, 89, 59, 37, 35, 38, 29, 18, 45,
    60, 49, 62, 55, 78, 96, 29, 22, 24, 13,
    14, 11, 11, 18, 12, 12, 30, 52, 52, 44,
    28, 28, 20, 56, 40, 31, 50, 40, 46, 42,
    29, 19, 36, 25, 22, 17, 19, 26, 30, 20,
    15, 21, 11, 8, 8, 19, 5, 8, 8, 11,
    11, 8, 3, 9, 5, 4, 7, 3, 6, 3,
    5, 4, 5, 6,
]

_SURAH_NAMES: dict[int, str] = {
    1: "الفاتحة", 2: "البقرة", 3: "آل عمران", 4: "النساء",
    5: "المائدة", 6: "الأنعام", 7: "الأعراف", 8: "الأنفال",
    9: "التوبة", 10: "يونس", 36: "يس", 55: "الرحمن",
    56: "الواقعة", 67: "الملك", 112: "الإخلاص",
    113: "الفلق", 114: "الناس",
}


# ── API helpers ───────────────────────────────────────────────────────────────

async def _fetch_ayah(surah: int, ayah: int) -> dict | None:
    """Fetch a single ayah in both Arabic and English."""
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
            ar_url = f"{_BASE}/ayah/{surah}:{ayah}/quran-uthmani"
            en_url = f"{_BASE}/ayah/{surah}:{ayah}/en.asad"

            ar_r, en_r = await asyncio.gather(
                s.get(ar_url), s.get(en_url), return_exceptions=True
            )

            ar_text = en_text = ""
            if not isinstance(ar_r, Exception) and ar_r.status == 200:
                d = await ar_r.json()
                ar_text = d.get("data", {}).get("text", "")
            if not isinstance(en_r, Exception) and en_r.status == 200:
                d = await en_r.json()
                en_text = d.get("data", {}).get("text", "")

            return {
                "surah": surah,
                "ayah": ayah,
                "arabic": ar_text,
                "english": en_text,
                "surah_name": _SURAH_NAMES.get(surah, f"Surah {surah}"),
            }
    except Exception as exc:
        logger.warning("quran_api_error", error=str(exc))
        return None


async def _fetch_surah_meta(surah: int) -> str:
    """Fetch the English name of a surah."""
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
            async with s.get(f"{_BASE}/surah/{surah}") as r:
                if r.status == 200:
                    d = await r.json()
                    data = d.get("data", {})
                    return data.get("englishName", f"Surah {surah}")
    except Exception:
        pass
    return f"Surah {surah}"


def _format_ayah(result: dict) -> str:
    surah_name = result.get("surah_name", f"Surah {result['surah']}")
    ref = f"({result['surah']}:{result['ayah']}) — {surah_name}"
    arabic = result.get("arabic", "")
    english = result.get("english", "")

    parts = [f"📖 *{ref}*\n"]
    if arabic:
        parts.append(f"```\n{arabic}\n```")
    if english:
        parts.append(f"_{english}_")
    return "\n\n".join(parts)


# ── Commands ──────────────────────────────────────────────────────────────────


async def cmd_quran(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetch a specific ayah: /quran <surah:ayah>"""
    user = update.effective_user
    msg = update.effective_message

    allowed, err = await rate_limit_check(user.id, "quran", limit=_RATE_LIMIT, window=_RATE_WINDOW)
    if not allowed:
        await msg.reply_text(err)
        return

    if not context.args:
        await msg.reply_text(
            "📖 *القرآن الكريم | Holy Quran*\n\n"
            "الاستخدام | Usage:\n"
            "• `/quran 2:255` — آية الكرسي\n"
            "• `/quran 1:1`   — الفاتحة\n"
            "• `/surah 36`    — سورة يس\n"
            "• `/random_ayah` — آية عشوائية",
            parse_mode="Markdown",
        )
        return

    ref = context.args[0]
    if ":" not in ref:
        await msg.reply_text("❌ الصيغة الصحيحة | Format: `/quran <surah>:<ayah>` — مثال: `/quran 2:255`", parse_mode="Markdown")
        return

    try:
        surah_s, ayah_s = ref.split(":", 1)
        surah = int(surah_s)
        ayah = int(ayah_s)
    except ValueError:
        await msg.reply_text("❌ أرقام غير صحيحة | Invalid numbers.")
        return

    if not (1 <= surah <= 114):
        await msg.reply_text("❌ رقم السورة بين 1 و 114 | Surah must be between 1 and 114.")
        return

    max_ayah = _SURAH_LENGTHS[surah - 1]
    if not (1 <= ayah <= max_ayah):
        await msg.reply_text(f"❌ السورة {surah} تحتوي على {max_ayah} آية | Surah {surah} has {max_ayah} ayahs.")
        return

    status = await msg.reply_text("⏳ جاري الجلب...")
    result = await _fetch_ayah(surah, ayah)

    if not result:
        await status.edit_text("❌ فشل الاتصال بالخادم | Could not reach Quran API.")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◀️ السابقة", callback_data=f"quran:prev:{surah}:{ayah}"),
            InlineKeyboardButton("التالية ▶️", callback_data=f"quran:next:{surah}:{ayah}"),
        ]
    ])
    await status.edit_text(_format_ayah(result), parse_mode="Markdown", reply_markup=keyboard)


async def cmd_surah(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetch first 10 ayahs of a surah: /surah <number>"""
    user = update.effective_user
    msg = update.effective_message

    allowed, err = await rate_limit_check(user.id, "surah", limit=5, window=60)
    if not allowed:
        await msg.reply_text(err)
        return

    if not context.args:
        await msg.reply_text("الاستخدام | Usage: `/surah <1-114>` — مثال: `/surah 36`", parse_mode="Markdown")
        return

    try:
        surah = int(context.args[0])
    except ValueError:
        await msg.reply_text("❌ أدخل رقماً صحيحاً | Enter a valid number.")
        return

    if not (1 <= surah <= 114):
        await msg.reply_text("❌ رقم السورة بين 1 و 114.")
        return

    status = await msg.reply_text(f"⏳ جاري تحميل سورة رقم {surah}...")

    max_ayah = _SURAH_LENGTHS[surah - 1]
    limit = min(10, max_ayah)

    results = await asyncio.gather(
        *[_fetch_ayah(surah, a) for a in range(1, limit + 1)]
    )

    valid = [r for r in results if r]
    if not valid:
        await status.edit_text("❌ فشل الجلب | Fetch failed.")
        return

    en_name = await _fetch_surah_meta(surah)
    ar_name = _SURAH_NAMES.get(surah, "")
    header = f"📖 *سورة {ar_name} | {en_name}* (Surah {surah})\n\n"

    lines = [header]
    for r in valid:
        lines.append(f"({r['ayah']}) {r['arabic']}")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "…"

    keyboard = None
    if max_ayah > 10:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"المزيد ({limit + 1}–{min(limit + 10, max_ayah)}) ▶️",
                                  callback_data=f"quran:surah:{surah}:{limit + 1}")]
        ])

    await status.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def cmd_random_ayah(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a random ayah."""
    user = update.effective_user
    msg = update.effective_message

    allowed, err = await rate_limit_check(user.id, "random_ayah", limit=_RATE_LIMIT, window=_RATE_WINDOW)
    if not allowed:
        await msg.reply_text(err)
        return

    surah = random.randint(1, 114)
    ayah = random.randint(1, _SURAH_LENGTHS[surah - 1])

    status = await msg.reply_text("🎲 اختيار آية عشوائية...")
    result = await _fetch_ayah(surah, ayah)

    if not result:
        await status.edit_text("❌ فشل الجلب | Fetch failed.")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎲 أخرى | Another", callback_data="quran:random"),
            InlineKeyboardButton("◀️▶️ التنقل", callback_data=f"quran:next:{surah}:{ayah}"),
        ]
    ])
    await status.edit_text(_format_ayah(result), parse_mode="Markdown", reply_markup=keyboard)


# ── Callback handler ──────────────────────────────────────────────────────────

async def handle_quran_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()

    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "random":
        surah = random.randint(1, 114)
        ayah = random.randint(1, _SURAH_LENGTHS[surah - 1])
        result = await _fetch_ayah(surah, ayah)
        if result:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎲 أخرى | Another", callback_data="quran:random"),
                 InlineKeyboardButton("◀️▶️ تنقل", callback_data=f"quran:next:{surah}:{ayah}")]
            ])
            await query.edit_message_text(_format_ayah(result), parse_mode="Markdown", reply_markup=keyboard)

    elif action in ("next", "prev"):
        try:
            surah, ayah = int(parts[2]), int(parts[3])
        except (IndexError, ValueError):
            return

        if action == "next":
            ayah += 1
            if ayah > _SURAH_LENGTHS[surah - 1]:
                surah = min(surah + 1, 114)
                ayah = 1
        else:
            ayah -= 1
            if ayah < 1:
                surah = max(surah - 1, 1)
                ayah = _SURAH_LENGTHS[surah - 1]

        result = await _fetch_ayah(surah, ayah)
        if result:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("◀️ السابقة", callback_data=f"quran:prev:{surah}:{ayah}"),
                    InlineKeyboardButton("التالية ▶️", callback_data=f"quran:next:{surah}:{ayah}"),
                ]
            ])
            await query.edit_message_text(_format_ayah(result), parse_mode="Markdown", reply_markup=keyboard)

    elif action == "surah":
        try:
            surah, start = int(parts[2]), int(parts[3])
        except (IndexError, ValueError):
            return
        max_ayah = _SURAH_LENGTHS[surah - 1]
        end = min(start + 9, max_ayah)

        results = await asyncio.gather(
            *[_fetch_ayah(surah, a) for a in range(start, end + 1)]
        )
        valid = [r for r in results if r]
        if not valid:
            return

        lines = [f"📖 *Surah {surah}* (آيات {start}–{end})\n"]
        for r in valid:
            lines.append(f"({r['ayah']}) {r['arabic']}")
        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:3990] + "…"

        keyboard = None
        if end < max_ayah:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"المزيد ({end + 1}–{min(end + 10, max_ayah)}) ▶️",
                                      callback_data=f"quran:surah:{surah}:{end + 1}")]
            ])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("quran", cmd_quran))
    app.add_handler(CommandHandler("surah", cmd_surah))
    app.add_handler(CommandHandler("random_ayah", cmd_random_ayah))
    app.add_handler(CallbackQueryHandler(handle_quran_callback, pattern=r"^quran:"))
    logger.info("quran_handlers_registered")
