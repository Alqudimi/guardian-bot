"""
Instagram Downloader
====================
Command: /ig <url>

Uses yt-dlp for reels/videos and instaloader for photo posts.
Falls back gracefully when instaloader is not installed.

Supports:
  • Reels & videos  (via yt-dlp)
  • Photo posts     (via instaloader Python API in executor)
  • Carousels       (sends all images/videos)
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
_TIMEOUT = 240

_IG_PATTERN = re.compile(
    r"https?://(?:www\.)?instagram\.com/"
    r"(?:p|reel|tv|stories|s)/[\w\-]+",
    re.IGNORECASE,
)
_REEL_PATTERN = re.compile(
    r"instagram\.com/reel/|instagram\.com/tv/",
    re.IGNORECASE,
)


def _is_ig_url(url: str) -> bool:
    return bool(_IG_PATTERN.search(url))


async def _run_ytdlp(args: list[str]) -> tuple[int, list[Path], str]:
    """Run yt-dlp and return (returncode, downloaded_files, stderr)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_TIMEOUT
        )
        return proc.returncode or 0, [], stderr.decode(errors="replace")
    except FileNotFoundError:
        return 1, [], "yt-dlp not installed"
    except TimeoutError:
        return 1, [], "Timed out"


async def _try_ytdlp(url: str, tmpdir: str) -> tuple[bool, list[Path], str]:
    """Attempt download via yt-dlp."""
    out_template = os.path.join(tmpdir, "%(autonumber)02d-%(title).60s.%(ext)s")
    args = [
        "--no-playlist",
        "--max-filesize", "50M",
        "-f", "best[ext=mp4]/best",
        "-o", out_template,
        "--no-mtime",
        "--quiet",
        "--no-warnings",
        url,
    ]
    rc, _, stderr = await _run_ytdlp(args)
    files = sorted(Path(tmpdir).iterdir())
    return (rc == 0 and bool(files)), files, stderr


async def _try_instaloader(url: str, tmpdir: str) -> tuple[bool, list[Path], str]:
    """Attempt download via instaloader (in executor to avoid blocking)."""
    try:
        import instaloader

        shortcode_match = re.search(r"/(?:p|reel|tv)/([A-Za-z0-9_\-]+)", url)
        if not shortcode_match:
            return False, [], "Could not extract shortcode"

        shortcode = shortcode_match.group(1)

        def _blocking_download():
            loader = instaloader.Instaloader(
                download_video_thumbnails=False,
                save_metadata=False,
                post_metadata_txt_pattern="",
                dirname_pattern=tmpdir,
                filename_pattern="{shortcode}_{mediaid}",
                quiet=True,
            )
            post = instaloader.Post.from_shortcode(loader.context, shortcode)
            loader.download_post(post, target=tmpdir)

        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(None, _blocking_download),
            timeout=_TIMEOUT,
        )

        files = [
            f for f in sorted(Path(tmpdir).iterdir())
            if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".mp4", ".mov"}
        ]
        return bool(files), files, ""

    except ModuleNotFoundError:
        return False, [], "instaloader not installed"
    except Exception as exc:
        return False, [], str(exc)


async def _download_ig(update: Update, url: str, bot=None) -> None:
    user = update.effective_user
    chat = update.effective_chat
    msg = update.effective_message
    bot = bot or update.get_bot()

    if not _is_ig_url(url):
        await msg.reply_text(
            "❌ يرجى تقديم رابط Instagram صحيح.\n"
            "Example: `https://www.instagram.com/p/XXXX/`",
            parse_mode="Markdown",
        )
        return

    allowed, err_msg = await rate_limit_check(
        user.id, "instagram", limit=_RATE_LIMIT, window=_RATE_WINDOW
    )
    if not allowed:
        await msg.reply_text(err_msg)
        return

    status = await msg.reply_text("📥 جاري التحميل من Instagram...")

    tmpdir = tempfile.mkdtemp(prefix="ig_")
    try:
        # Strategy 1: yt-dlp (fast, works for reels/videos)
        success, files, err = await _try_ytdlp(url, tmpdir)

        # Strategy 2: instaloader (for photos)
        if not success:
            shutil.rmtree(tmpdir, ignore_errors=True)
            tmpdir = tempfile.mkdtemp(prefix="ig_il_")
            success, files, err = await _try_instaloader(url, tmpdir)

        if not success or not files:
            await status.edit_text(
                f"❌ فشل التحميل | Download failed.\n"
                f"تأكد أن الحساب عام | Make sure the account is public.\n"
                f"`{err[:150]}`"
            )
            return

        await status.edit_text(f"📤 إرسال {len(files)} ملف... | Sending {len(files)} file(s)...")

        for fp in files:
            if fp.suffix.lower() in {".txt", ".json", ".xz"}:
                continue
            size = fp.stat().st_size
            if size > _MAX_BYTES:
                await bot.send_message(
                    chat_id=chat.id,
                    text=f"⚠️ ملف '{fp.name}' أكبر من 50MB — تخطي.",
                )
                continue
            ext = fp.suffix.lower()
            with open(fp, "rb") as fh:
                if ext in {".mp4", ".mov", ".avi"}:
                    await bot.send_video(
                        chat_id=chat.id,
                        video=fh, filename=fp.name,
                        supports_streaming=True,
                        read_timeout=120, write_timeout=120,
                    )
                else:
                    await bot.send_photo(
                        chat_id=chat.id,
                        photo=fh,
                        read_timeout=60, write_timeout=60,
                    )

        await status.delete()
        logger.info(
            "instagram_downloaded",
            user_id=user.id,
            chat_id=chat.id,
            url=url[:80],
            files=len(files),
        )

    except Exception as exc:
        logger.error("instagram_error", error=str(exc))
        await status.edit_text(f"❌ خطأ | Error: {exc}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def cmd_ig(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text(
            "📷 *Instagram Downloader*\n\n"
            "الاستخدام | Usage: `/ig <instagram_url>`\n"
            "يدعم: الصور، الريلز، الفيديوهات | Supports: photos, reels, videos.",
            parse_mode="Markdown",
        )
        return
    url = context.args[0]
    create_background_task(
        _download_ig(update, url),
        name=f"instagram-download:{update.effective_user.id}",
    )


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("ig", cmd_ig))
    logger.info("instagram_handlers_registered")
