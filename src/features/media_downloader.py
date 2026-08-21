"""
Media Downloader  —  YouTube / TikTok / General Video
======================================================
Commands
  /yt  <url>   — download best video (≤ 50 MB)
  /yta <url>   — download audio only (mp3, ≤ 50 MB)

Backend: yt-dlp (subprocess, non-blocking via asyncio)
Safety:  per-user rate limit · file-size guard · URL validation
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from src.features.rate_limiter import rate_limit_check
from src.utils.background_tasks import create_background_task
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_MAX_BYTES = 50 * 1024 * 1024          # 50 MB Telegram bot limit
_DOWNLOAD_TIMEOUT = 300                # seconds
_RATE_LIMIT = 3                        # requests per window
_RATE_WINDOW = 120                     # seconds

_SUPPORTED = re.compile(
    r"https?://(?:www\.)?"
    r"(?:youtube\.com/(?:watch|shorts|embed|v)|youtu\.be|"
    r"tiktok\.com|vm\.tiktok\.com|"
    r"twitter\.com|x\.com|"
    r"facebook\.com|fb\.watch|"
    r"instagram\.com|"
    r"twitch\.tv|"
    r"vimeo\.com|"
    r"dailymotion\.com)",
    re.IGNORECASE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_url(url: str) -> bool:
    return bool(_SUPPORTED.search(url))


async def _run_ytdlp(args: list[str]) -> tuple[int, str, str]:
    """Non-blocking yt-dlp subprocess."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_DOWNLOAD_TIMEOUT
        )
        return (
            proc.returncode or 0,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )
    except FileNotFoundError:
        return 1, "", "yt-dlp not installed"
    except TimeoutError:
        return 1, "", "Download timed out"


async def _get_title(url: str) -> str:
    """Fetch video title without downloading."""
    rc, stdout, _ = await _run_ytdlp(
        ["--get-title", "--no-playlist", "--quiet", url]
    )
    if rc == 0 and stdout.strip():
        return stdout.strip().splitlines()[0][:100]
    return "media"


async def _download_and_send(
    update: Update,
    url: str,
    audio_only: bool,
    bot=None,
) -> None:
    user = update.effective_user
    chat = update.effective_chat
    msg = update.effective_message
    bot = bot or update.get_bot()

    # URL validation
    if not _validate_url(url):
        await msg.reply_text(
            "❌ رابط غير مدعوم | Unsupported URL.\n"
            "YouTube, TikTok, Twitter/X, Instagram, Vimeo, Facebook, Twitch."
        )
        return

    # Rate limit
    allowed, err_msg = await rate_limit_check(
        user.id, "yt_audio" if audio_only else "yt_video",
        limit=_RATE_LIMIT, window=_RATE_WINDOW,
    )
    if not allowed:
        await msg.reply_text(err_msg)
        return

    status = await msg.reply_text("⏬ جاري التحميل... | Downloading...")

    tmpdir = tempfile.mkdtemp(prefix="ytdl_")
    try:
        out_template = os.path.join(tmpdir, "%(title).60s.%(ext)s")

        if audio_only:
            args = [
                "--no-playlist",
                "--max-filesize", "50M",
                "-f", "bestaudio[ext=m4a]/bestaudio/best",
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "5",
                "-o", out_template,
                "--no-mtime",
                "--quiet",
                "--no-warnings",
                url,
            ]
        else:
            args = [
                "--no-playlist",
                "--max-filesize", "50M",
                "-f", "best[filesize<50M][ext=mp4]/best[filesize<50M]/best",
                "--merge-output-format", "mp4",
                "-o", out_template,
                "--no-mtime",
                "--quiet",
                "--no-warnings",
                url,
            ]

        rc, _, stderr = await _run_ytdlp(args)

        files = list(Path(tmpdir).iterdir())
        if rc != 0 or not files:
            err = stderr.strip().splitlines()[-1] if stderr.strip() else "Unknown error"
            await status.edit_text(f"❌ فشل التحميل | Download failed: `{err[:200]}`")
            return

        file_path = files[0]
        size = file_path.stat().st_size

        if size > _MAX_BYTES:
            await status.edit_text(
                f"❌ الملف أكبر من 50MB | File exceeds 50 MB limit "
                f"({size // 1024 // 1024} MB)."
            )
            return

        await status.edit_text("📤 جاري الإرسال... | Sending...")

        ext = file_path.suffix.lower()
        audio_exts = {".mp3", ".m4a", ".ogg", ".opus", ".flac", ".wav", ".aac"}

        with open(file_path, "rb") as fh:
            if audio_only or ext in audio_exts:
                await bot.send_audio(
                    chat_id=chat.id,
                    audio=fh,
                    filename=file_path.name,
                    read_timeout=120,
                    write_timeout=120,
                )
            else:
                await bot.send_video(
                    chat_id=chat.id,
                    video=fh,
                    filename=file_path.name,
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                )

        await status.delete()
        logger.info(
            "media_downloaded",
            user_id=user.id,
            chat_id=chat.id,
            url=url[:80],
            audio_only=audio_only,
            size_mb=round(size / 1024 / 1024, 1),
        )

    except Exception as exc:
        logger.error("media_download_error", error=str(exc), url=url[:80])
        await status.edit_text(f"❌ خطأ غير متوقع | Unexpected error: {exc}")
    finally:
        # Cleanup temp files
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Command Handlers ──────────────────────────────────────────────────────────

async def cmd_yt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Download video from YouTube / TikTok / etc."""
    if not context.args:
        await update.effective_message.reply_text(
            "📥 *تحميل فيديو | Video Download*\n\n"
            "الاستخدام | Usage: `/yt <url>`\n"
            "للصوت فقط | Audio only: `/yta <url>`\n\n"
            "يدعم: YouTube، TikTok، Twitter، Instagram، Vimeo",
            parse_mode="Markdown",
        )
        return
    url = context.args[0]
    create_background_task(
        _download_and_send(update, url, audio_only=False, bot=context.bot),
        name=f"media-video:{update.effective_user.id}",
    )


async def cmd_yta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Download audio only (mp3) from YouTube / etc."""
    if not context.args:
        await update.effective_message.reply_text(
            "🎵 *تحميل صوت | Audio Download*\n\n"
            "الاستخدام | Usage: `/yta <url>`"
        )
        return
    url = context.args[0]
    create_background_task(
        _download_and_send(update, url, audio_only=True, bot=context.bot),
        name=f"media-audio:{update.effective_user.id}",
    )


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("yt", cmd_yt))
    app.add_handler(CommandHandler("yta", cmd_yta))
    logger.info("media_downloader_handlers_registered")
