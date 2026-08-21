"""
SoundCloud Downloader
=====================
Command: /sc <url>

Uses yt-dlp (which supports SoundCloud natively) so no extra dependency
is needed beyond what the media_downloader already requires.

Handles:
  • Single tracks
  • Playlists (capped at first 5 tracks to avoid flooding)
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from src.features.rate_limiter import rate_limit_check
from src.utils.background_tasks import create_background_task
from src.utils.logger import get_logger

logger = get_logger(__name__)

_MAX_BYTES = 50 * 1024 * 1024
_RATE_LIMIT = 3
_RATE_WINDOW = 120
_PLAYLIST_CAP = 5
_TIMEOUT = 300

_SC_PATTERN = re.compile(
    r"https?://(?:www\.)?soundcloud\.com/[\w\-/]+",
    re.IGNORECASE,
)


def _is_sc_url(url: str) -> bool:
    return bool(_SC_PATTERN.search(url))


async def _run_ytdlp(args: list[str]) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_TIMEOUT
        )
        return (
            proc.returncode or 0,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )
    except FileNotFoundError:
        return 1, "", "yt-dlp not installed"
    except TimeoutError:
        return 1, "", "Timed out"


async def _download_sc(update: Update, url: str, bot=None) -> None:
    user = update.effective_user
    chat = update.effective_chat
    msg = update.effective_message
    bot = bot or update.get_bot()

    if not _is_sc_url(url):
        await msg.reply_text(
            "❌ يرجى تقديم رابط SoundCloud صحيح | Please provide a valid SoundCloud URL.\n"
            "مثال | Example: `https://soundcloud.com/artist/track`",
            parse_mode="Markdown",
        )
        return

    allowed, err_msg = await rate_limit_check(
        user.id, "soundcloud", limit=_RATE_LIMIT, window=_RATE_WINDOW
    )
    if not allowed:
        await msg.reply_text(err_msg)
        return

    status = await msg.reply_text("🎵 جاري التحميل من SoundCloud...")

    tmpdir = tempfile.mkdtemp(prefix="sc_")
    try:
        out_template = os.path.join(tmpdir, "%(playlist_index)02d-%(title).60s.%(ext)s")

        args = [
            "--playlist-items", f"1:{_PLAYLIST_CAP}",
            "--max-filesize", "50M",
            "-f", "bestaudio[ext=mp3]/bestaudio",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "5",
            "-o", out_template,
            "--no-mtime",
            "--quiet",
            "--no-warnings",
            url,
        ]

        rc, _, stderr = await _run_ytdlp(args)

        files = sorted(Path(tmpdir).iterdir())
        if not files:
            err_line = (stderr.strip().splitlines() or ["Unknown"])[-1]
            await status.edit_text(f"❌ فشل التحميل | Download failed: `{err_line[:200]}`")
            return

        await status.edit_text(f"📤 جاري إرسال {len(files)} مقطع... | Sending {len(files)} track(s)...")

        for fp in files:
            size = fp.stat().st_size
            if size > _MAX_BYTES:
                await bot.send_message(
                    chat_id=chat.id,
                    text=f"⚠️ المقطع '{fp.stem}' أكبر من 50MB — تخطي | Skipping.",
                )
                continue
            with open(fp, "rb") as fh:
                await bot.send_audio(
                    chat_id=chat.id,
                    audio=fh,
                    filename=fp.name,
                    read_timeout=120,
                    write_timeout=120,
                )

        await status.delete()
        logger.info(
            "soundcloud_downloaded",
            user_id=user.id,
            chat_id=chat.id,
            url=url[:80],
            tracks=len(files),
        )

    except Exception as exc:
        logger.error("soundcloud_error", error=str(exc))
        await status.edit_text(f"❌ خطأ | Error: {exc}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def cmd_sc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text(
            "🎵 *SoundCloud Downloader*\n\n"
            "الاستخدام | Usage: `/sc <soundcloud_url>`\n"
            "يدعم المقاطع والقوائم (أول 5 مقاطع) | Supports tracks & playlists (first 5).",
            parse_mode="Markdown",
        )
        return
    url = context.args[0]
    create_background_task(
        _download_sc(update, url),
        name=f"soundcloud-download:{update.effective_user.id}",
    )


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("sc", cmd_sc))
    logger.info("soundcloud_handlers_registered")
