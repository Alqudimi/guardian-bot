"""
Voice Chat Music Player
=======================
Commands:
  /play  <url or search>  — add to queue and play when routed by the main dispatcher
  /music <url or search>  — direct music entrypoint
  /pause                  — pause current playback
  /resume                 — resume paused playback
  /skip                   — skip to next track
  /stop                   — stop and clear queue
  /queue  (/q)            — show current queue
  /np                     — now playing info

Architecture:
  • Per-chat asyncio Queue for track management
  • yt-dlp fetches audio stream URL (no full file download needed)
  • PyTgCalls + Pyrogram for actual voice chat streaming
  • If PyTgCalls/Pyrogram are not configured, playback commands fail closed
    and never claim that audio is playing or queued for playback

Environment variables required for actual playback:
  TELEGRAM_API_ID    — Pyrogram API ID
  TELEGRAM_API_HASH  — Pyrogram API hash
  (bot token is reused from settings)
"""
from __future__ import annotations

import asyncio
import inspect
import os
from dataclasses import dataclass, field

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from config.settings import get_settings
from src.features.rate_limiter import rate_limit_check
from src.utils.background_tasks import create_background_task
from src.utils.logger import get_logger

logger = get_logger(__name__)

_TIMEOUT = 60
_RATE_LIMIT = 10
_RATE_WINDOW = 60
_MAX_QUEUE = 20


# ── Track dataclass ───────────────────────────────────────────────────────────

@dataclass
class Track:
    title: str
    url: str
    stream_url: str = ""
    requested_by: str = "Unknown"
    duration: int = 0   # seconds


# ── Per-chat state ────────────────────────────────────────────────────────────

@dataclass
class ChatPlayer:
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=_MAX_QUEUE))
    current: Track | None = None
    paused: bool = False
    playing: bool = False
    skip_requested: bool = False


_players: dict[int, ChatPlayer] = {}


def _get_player(chat_id: int) -> ChatPlayer:
    if chat_id not in _players:
        _players[chat_id] = ChatPlayer()
    return _players[chat_id]


# ── PyTgCalls integration (optional) ─────────────────────────────────────────

_pytgcalls = None
_pyrogram_client = None


def _init_voice_backend() -> bool:
    """Attempt to initialize PyTgCalls + Pyrogram. Returns True on success."""
    global _pytgcalls, _pyrogram_client

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    settings = get_settings()

    if not api_id or not api_hash:
        logger.info("voice_backend_disabled", reason="TELEGRAM_API_ID / TELEGRAM_API_HASH not set")
        return False

    try:
        from pyrogram import Client
        from pytgcalls import PyTgCalls

        _pyrogram_client = Client(
            "voice_bot",
            api_id=int(api_id),
            api_hash=api_hash,
            bot_token=settings.telegram_bot_token,
        )
        _pytgcalls = PyTgCalls(_pyrogram_client)
        logger.info("voice_backend_initialized")
        return True
    except ImportError as exc:
        logger.info("voice_backend_unavailable", reason=str(exc))
        return False
    except Exception as exc:
        logger.warning("voice_backend_init_error", error=str(exc))
        return False


_VOICE_READY = False


async def start_voice_backend() -> None:
    """Call this once during bot startup."""
    global _VOICE_READY
    if _VOICE_READY:
        return
    if _init_voice_backend() and _pyrogram_client and _pytgcalls:
        try:
            await _pyrogram_client.start()
            await _pytgcalls.start()
            _VOICE_READY = True
            logger.info("voice_backend_started")
        except Exception as exc:
            logger.warning("voice_backend_start_error", error=type(exc).__name__)


async def stop_voice_backend() -> None:
    """Stop voice clients and cancel active per-chat player loops."""
    global _VOICE_READY, _pytgcalls, _pyrogram_client

    for task in list(_player_tasks.values()):
        if not task.done():
            task.cancel()
    if _player_tasks:
        await asyncio.gather(*_player_tasks.values(), return_exceptions=True)
    _player_tasks.clear()

    for client in (_pytgcalls, _pyrogram_client):
        stop = getattr(client, "stop", None)
        if stop is None:
            continue
        try:
            result = stop()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning("voice_client_stop_error", error=type(exc).__name__)

    _VOICE_READY = False
    _pytgcalls = None
    _pyrogram_client = None


# ── yt-dlp helpers ────────────────────────────────────────────────────────────

async def _get_stream_url(query: str) -> tuple[str, str, int]:
    """
    Resolve a query/URL to a direct audio stream URL via yt-dlp.
    Returns (stream_url, title, duration_seconds).
    """
    # If not a URL, treat as YouTube search
    if not query.startswith("http"):
        query = f"ytsearch1:{query}"

    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--get-url", "--get-title", "--get-duration",
            "--no-playlist",
            "-f", "bestaudio[ext=m4a]/bestaudio/best",
            "--quiet",
            "--no-warnings",
            query,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        lines = stdout.decode(errors="replace").strip().splitlines()

        if len(lines) >= 2:
            title = lines[0]
            stream_url = lines[1]
            duration_str = lines[2] if len(lines) > 2 else "0"
            # duration may be "3:45" or "225"
            try:
                if ":" in duration_str:
                    parts = duration_str.split(":")
                    if len(parts) == 2:
                        duration = int(parts[0]) * 60 + int(parts[1])
                    else:
                        duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                else:
                    duration = int(duration_str)
            except ValueError:
                duration = 0
            return stream_url, title, duration

    except FileNotFoundError:
        return "", "Unknown", 0
    except TimeoutError:
        return "", "Unknown", 0
    except Exception as exc:
        logger.warning("ytdlp_stream_error", error=str(exc))
    return "", "Unknown", 0


async def _play_stream(chat_id: int, stream_url: str) -> bool:
    """Send audio stream to voice chat via PyTgCalls."""
    if not _VOICE_READY or _pytgcalls is None:
        return False
    try:
        from pytgcalls.types import MediaStream
        from pytgcalls.types.input_stream import AudioPiped
        from pytgcalls.types.input_stream.quality import HighQualityAudio

        # pytgcalls API varies by version — try both
        try:
            await _pytgcalls.play(chat_id, MediaStream(stream_url))
        except (TypeError, AttributeError):
            await _pytgcalls.join_group_call(
                chat_id,
                AudioPiped(stream_url, HighQualityAudio()),
            )
        return True
    except Exception as exc:
        logger.warning("pytgcalls_play_error", chat_id=chat_id, error=str(exc))
        return False


async def _pause_stream(chat_id: int) -> bool:
    if not _VOICE_READY or _pytgcalls is None:
        return False
    try:
        await _pytgcalls.pause_stream(chat_id)
        return True
    except Exception:
        return False


async def _resume_stream(chat_id: int) -> bool:
    if not _VOICE_READY or _pytgcalls is None:
        return False
    try:
        await _pytgcalls.resume_stream(chat_id)
        return True
    except Exception:
        return False


async def _leave_voice(chat_id: int) -> bool:
    if not _VOICE_READY or _pytgcalls is None:
        return False
    try:
        await _pytgcalls.leave_group_call(chat_id)
        return True
    except Exception:
        return False


def _fmt_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ── Queue player loop ─────────────────────────────────────────────────────────

_player_tasks: dict[int, asyncio.Task] = {}


async def _player_loop(chat_id: int, bot) -> None:
    """Continuously dequeues and plays tracks for a chat."""
    if not _VOICE_READY:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "❌ التشغيل الصوتي غير متاح: لم يتم تشغيل PyTgCalls/Pyrogram. "
                "لم تتم إزالة أي طلب من قائمة تشغيل فعلية."
            ),
        )
        return

    player = _get_player(chat_id)
    player.playing = True

    try:
        while True:
            try:
                track: Track = player.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            player.current = track

            if not track.stream_url:
                stream_url, _, _ = await _get_stream_url(track.url)
                track.stream_url = stream_url

            if track.stream_url:
                played = await _play_stream(chat_id, track.stream_url)
                if played:
                    # Wait for track to finish (poll pytgcalls status)
                    try:
                        while _VOICE_READY and not player.paused and not player.skip_requested:
                            await asyncio.sleep(2)
                            # If queue has more items or explicitly stopped, break
                            if not player.playing:
                                break
                    except asyncio.CancelledError:
                        break
                else:
                    try:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=(
                                f"❌ تعذر تشغيل *{track.title}*: لم يبدأ backend الصوت الفعلي. "
                                "لم يتم اعتبار المسار مشغلاً."
                            ),
                            parse_mode="Markdown",
                        )
                    except Exception:
                        pass
            else:
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ فشل تحميل | Failed to load: *{track.title}*",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

            player.queue.task_done()
            if player.skip_requested:
                player.skip_requested = False

    finally:
        player.playing = False
        player.paused = False
        player.skip_requested = False
        player.current = None
        _player_tasks.pop(chat_id, None)


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    msg = update.effective_message

    allowed, err = await rate_limit_check(user.id, "play", limit=_RATE_LIMIT, window=_RATE_WINDOW)
    if not allowed:
        await msg.reply_text(err)
        return

    if not _VOICE_READY:
        await msg.reply_text(
            "❌ التشغيل الصوتي غير متاح حالياً. اضبط TELEGRAM_API_ID وTELEGRAM_API_HASH "
            "وشغّل Pyrogram/PyTgCalls أولاً؛ لم تتم إضافة المسار إلى قائمة وهمية."
        )
        return

    if not context.args:
        await msg.reply_text(
            "🎵 *Music Player*\n\n"
            "الاستخدام | Usage:\n"
            "• `/music <url>` — رابط مباشر\n"
            "• `/music <search query>` — بحث في يوتيوب\n"
            "• `/play <url أو بحث>` — متوافق مع dispatcher الرئيسي\n\n"
            "أوامر أخرى | Other commands:\n"
            "/pause • /resume • /skip • /stop • /queue • /np",
            parse_mode="Markdown",
        )
        return

    query = " ".join(context.args)
    player = _get_player(chat.id)

    if player.queue.qsize() >= _MAX_QUEUE:
        await msg.reply_text(f"⚠️ قائمة التشغيل ممتلئة ({_MAX_QUEUE} مقاطع) | Queue is full.")
        return

    status = await msg.reply_text("🔍 جاري البحث / جلب الرابط...")

    stream_url, title, duration = await _get_stream_url(query)

    if not stream_url and not query.startswith("http"):
        await status.edit_text("❌ لم يتم العثور على نتائج | No results found.")
        return

    track = Track(
        title=title or query[:60],
        url=query,
        stream_url=stream_url,
        requested_by=user.full_name,
        duration=duration,
    )

    try:
        player.queue.put_nowait(track)
    except asyncio.QueueFull:
        await status.edit_text("⚠️ القائمة ممتلئة | Queue full.")
        return

    pos = player.queue.qsize()
    dur = f" • {_fmt_duration(duration)}" if duration else ""

    if player.playing:
        await status.edit_text(
            f"✅ تمت الإضافة | Added to queue (#{pos}):\n"
            f"🎵 *{track.title}*{dur}\n"
            f"طلب: {user.full_name}",
            parse_mode="Markdown",
        )
    else:
        await status.edit_text(
            f"▶️ جاري التشغيل | Now playing:\n"
            f"🎵 *{track.title}*{dur}\n"
            f"طلب: {user.full_name}",
            parse_mode="Markdown",
        )
        # Start player loop
        if chat.id in _player_tasks and not _player_tasks[chat.id].done():
            pass  # Already running
        else:
            task = create_background_task(
                _player_loop(chat.id, context.bot),
                name=f"voice-player:{chat.id}",
            )
            _player_tasks[chat.id] = task


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    player = _get_player(chat.id)

    if not _VOICE_READY or not player.playing or not player.current:
        await update.effective_message.reply_text("❌ لا يوجد تشغيل صوتي فعلي متاح | Nothing is actually playing.")
        return

    player.paused = True
    ok = await _pause_stream(chat.id)
    status = "✅ تم الإيقاف المؤقت | Paused." if ok else (
        "❌ تعذر إيقاف التشغيل مؤقتاً لأن backend الصوت لم يؤكد العملية."
    )
    await update.effective_message.reply_text(status)


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    player = _get_player(chat.id)

    if not _VOICE_READY or not player.paused:
        await update.effective_message.reply_text("❌ لا يوجد تشغيل صوتي متوقف مؤقتاً | Nothing is actually paused.")
        return

    player.paused = False
    ok = await _resume_stream(chat.id)
    status = "▶️ تم الاستئناف | Resumed." if ok else (
        "❌ تعذر استئناف التشغيل لأن backend الصوت لم يؤكد العملية."
    )
    await update.effective_message.reply_text(status)


async def cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    player = _get_player(chat.id)

    if not _VOICE_READY or not player.playing or not player.current:
        await update.effective_message.reply_text("❌ لا يوجد تشغيل صوتي فعلي للتخطي | Nothing is actually playing.")
        return

    track_name = player.current.title
    player.skip_requested = True
    stopped = await _leave_voice(chat.id)
    if not stopped:
        player.skip_requested = False
        await update.effective_message.reply_text("❌ لم يؤكد backend الصوت تخطي المسار.")
        return
    player.paused = False

    await update.effective_message.reply_text(
        f"⏭️ تخطي | Skipped: *{track_name}*", parse_mode="Markdown"
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    player = _get_player(chat.id)

    player.playing = False
    player.paused = False
    player.skip_requested = False
    player.current = None

    # Drain queue
    while not player.queue.empty():
        try:
            player.queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    # Cancel background task
    task = _player_tasks.pop(chat.id, None)
    if task and not task.done():
        task.cancel()

    await _leave_voice(chat.id)
    await update.effective_message.reply_text("⏹️ تم الإيقاف ومسح القائمة | Stopped and queue cleared.")


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    player = _get_player(chat.id)

    lines = ["🎵 *قائمة التشغيل | Queue*\n"]

    if player.current:
        dur = f" ({_fmt_duration(player.current.duration)})" if player.current.duration else ""
        paused_marker = " ⏸️" if player.paused else " ▶️"
        lines.append(f"{paused_marker} **الآن | Now:** {player.current.title}{dur}")
        lines.append(f"   طلب: {player.current.requested_by}\n")

    if player.queue.empty():
        if not player.current:
            lines.append("_(القائمة فارغة | Queue is empty)_")
    else:
        # Peek queue (non-destructive)
        items: list[Track] = []
        temp_q: asyncio.Queue = asyncio.Queue()
        while not player.queue.empty():
            try:
                t = player.queue.get_nowait()
                items.append(t)
                temp_q.put_nowait(t)
            except asyncio.QueueEmpty:
                break

        # Restore queue
        _players[chat.id].queue = temp_q

        for i, t in enumerate(items, 1):
            dur = f" ({_fmt_duration(t.duration)})" if t.duration else ""
            lines.append(f"{i}. {t.title}{dur} — {t.requested_by}")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "…"

    await update.effective_message.reply_text(text, parse_mode="Markdown")


async def cmd_np(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    player = _get_player(chat.id)

    if not player.current:
        await update.effective_message.reply_text("❌ لا يوجد شيء قيد التشغيل | Nothing is playing.")
        return

    t = player.current
    dur = f"\n⏱️ المدة | Duration: {_fmt_duration(t.duration)}" if t.duration else ""
    paused = " (⏸️ متوقف مؤقتاً | Paused)" if player.paused else ""
    pending = player.queue.qsize()

    await update.effective_message.reply_text(
        f"{'▶️' if not player.paused else '⏸️'} *الآن | Now Playing{paused}*\n\n"
        f"🎵 {t.title}{dur}\n"
        f"👤 طلب: {t.requested_by}\n"
        f"📋 في القائمة: {pending} مقطع/مقاطع",
        parse_mode="Markdown",
    )


def register_handlers(app) -> None:
    # `/play` is owned by message_handler, which dispatches game names locally
    # and delegates music queries here. Register only the explicit music alias.
    app.add_handler(CommandHandler("music", cmd_play))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("skip", cmd_skip))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler(["queue", "q"], cmd_queue))
    app.add_handler(CommandHandler("np", cmd_np))
    logger.info("voice_chat_handlers_registered")
