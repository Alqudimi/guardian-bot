"""
Telegram Message & Event Handlers — v3
=========================================
Registers all handlers: messages, member events, callbacks, and all
admin commands from both message_handler (security) and admin_commands (management).
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.games.manager import GameManager
from src.games.session import GameSessionManager
from src.handlers.admin_commands import (
    cmd_addpattern,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


# Group member utilities
async def cmd_grouphelp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    await update.effective_message.reply_text(
        "*Guardian Group Help*\n\n"
        "أوامر مفيدة للأعضاء:\n"
        "`/rules` — عرض قواعد المجموعة\n"
        "`/games` — ألعاب Guardian الداخلية\n"
        "`/gamescores` — النتائج المحفوظة للألعاب\n"
        "`/quote` — اقتباس تفاعلي\n"
        "`/azkar` — أذكار\n"
        "`/quran` — أدوات القرآن\n"
        "`/music` — تشغيل صوتي عند تهيئة backend\n\n"
        "أوامر المشرفين: `/leave`, `/setleave`, `/undo`, `/settings`، وجميعها محمية وتتحقق من صلاحيات Telegram الفعلية.",
        parse_mode="Markdown",
    )


# Game commands
async def cmd_games(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    available_games = GameManager.list_games()
    if not available_games:
        await update.message.reply_text("لا توجد ألعاب متاحة حاليًا.")
        return

    text = (
        "🎮 *مركز ألعاب Guardian*\n\n"
        "مرحباً بك في قسم الألعاب! اختر فئة الألعاب التي ترغب في استكشافها:"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("📝 ألعاب Guardian الداخلية", callback_data="game:menu:local"),
        ],
        [InlineKeyboardButton("📜 عرض الكل", callback_data="game:menu:all")]
    ]
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_game_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    data = (query.data or "").split(":")
    if len(data) < 3:
        await query.answer("Invalid game menu", show_alert=True)
        return
    category = data[2]

    available_games = GameManager.list_games()

    if category == "main":
        keyboard = [
            [InlineKeyboardButton("📝 ألعاب Guardian الداخلية", callback_data="game:menu:local")],
            [InlineKeyboardButton("❌ إغلاق", callback_data="game:menu:close")],
        ]
        await query.edit_message_text(
            "🎮 *مركز ألعاب Guardian*\n\nاختر فئة الألعاب المتاحة داخل البوت.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    if category == "close":
        await query.edit_message_text("تم إغلاق قائمة الألعاب.")
        return

    if category in {"all", "local", "text"}:
        game_list = list(available_games.keys())
        title = "ألعاب Guardian الداخلية"
    else:
        await query.edit_message_text("فئة ألعاب غير معروفة.")
        return
    
    text = f"🎮 *{title}*\n\nاختر لعبة لبدئها:"
    keyboard = []
    for game in game_list:
        keyboard.append([InlineKeyboardButton(game.replace('_', ' ').title(), callback_data=f"game:select:{game}")])
    
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="game:menu:main")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_game_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    parts = (query.data or "").split(":")
    if len(parts) < 3:
        await query.answer("Invalid game selection", show_alert=True)
        return
    game_name = parts[2]
    if game_name not in GameManager.list_games():
        await query.answer("This game is not available", show_alert=True)
        return
    chat_id = update.effective_chat.id
    
    # Check if a game is already running
    active_game = await GameSessionManager.get_active_game_for_chat(chat_id)
    if active_game:
        await query.message.reply_text(f"هناك لعبة `{active_game.game_id}` قيد التشغيل بالفعل. استخدم `/stopgame` أولاً.")
        return

    try:
        game_instance = await GameSessionManager.create_session(chat_id, game_name)
        # We need to simulate an update object for the game's start method
        # or refactor start to take chat_id/user_id
        await game_instance.start(update, context)
        await GameSessionManager.update_session(game_instance)
    except Exception as exc:
        logger.error("Error starting game from menu", game=game_name, error=str(exc))
        await query.message.reply_text("حدث خطأ أثناء بدء اللعبة.")


async def _start_game(update: Update, context: ContextTypes.DEFAULT_TYPE, game_name: str) -> None:
    chat_id = update.effective_chat.id

    try:
        active_game = await GameSessionManager.get_active_game_for_chat(chat_id)
        if active_game:
            await update.message.reply_text(
                f"هناك لعبة `{active_game.game_id}` قيد التشغيل بالفعل في هذه المحادثة. "
                "الرجاء إنهائها أولاً باستخدام `/stopgame`.",
                parse_mode="Markdown",
            )
            return

        game_instance = await GameSessionManager.create_session(chat_id, game_name)
        await game_instance.start(update, context)
        await GameSessionManager.update_session(game_instance)
    except ValueError as exc:
        await update.message.reply_text(f"خطأ: {exc}")
    except Exception as exc:
        logger.error("Error starting game", game_name=game_name, chat_id=chat_id, error=str(exc))
        await update.message.reply_text("حدث خطأ أثناء بدء اللعبة. الرجاء المحاولة مرة أخرى.")


async def _delegate_music_play(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.features.voice_chat import cmd_play as music_cmd_play

    await music_cmd_play(update, context)


async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "الاستخدام:\n"
            "`/play mafia` أو `/play chameleon` لبدء لعبة Guardian،\n"
            "`/play <url أو بحث>` لتشغيل الموسيقى، أو استخدم `/music` للموسيقى مباشرة.",
            parse_mode="Markdown",
        )
        return

    requested_name = context.args[0].lower()
    if len(context.args) == 1 and requested_name in GameManager.list_games():
        await _start_game(update, context, requested_name)
        return

    await _delegate_music_play(update, context)


async def cmd_mafia_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _start_game(update, context, "mafia")


async def cmd_cham_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _start_game(update, context, "chameleon")


async def cmd_stopgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    active_game = await GameSessionManager.get_active_game_for_chat(chat_id)

    if not active_game:
        await update.message.reply_text("لا توجد لعبة نشطة في هذه المحادثة.")
        return

    try:
        await active_game.stop()
        await GameSessionManager.persist_scores(active_game)
        await GameSessionManager.delete_session(chat_id, active_game.game_id)
        await update.message.reply_text(f"تم إنهاء لعبة `{active_game.game_id}`.", parse_mode="Markdown")
    except Exception as exc:
        logger.error("Error stopping game", game_id=active_game.game_id, chat_id=chat_id, error=str(exc))
        await update.message.reply_text("حدث خطأ أثناء إنهاء اللعبة. الرجاء المحاولة مرة أخرى.")

async def cmd_gamescores(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    game_name = (context.args[0].lower() if context.args else "chameleon")
    if game_name not in GameManager.list_games():
        await update.effective_message.reply_text("لعبة غير معروفة. استخدم /games لرؤية الألعاب المتاحة.")
        return

    rows = await GameSessionManager.get_scoreboard(chat_id, game_name)
    if not rows:
        await update.effective_message.reply_text("لا توجد نتائج محفوظة لهذه اللعبة في المجموعة بعد.")
        return

    lines = [f"🏆 نتائج {game_name} المحفوظة:"]
    for rank, (user_id, score) in enumerate(rows, start=1):
        formatted_score = int(score) if score.is_integer() else f"{score:.2f}"
        lines.append(f"{rank}. المستخدم `{user_id}` — {formatted_score} نقطة")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_game_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    active_game = await GameSessionManager.get_active_game_for_chat(chat_id)

    if active_game and active_game.status == "running":
        # Check if the message is a command for the active game
        # This needs to be more sophisticated for actual game commands vs general chat
        # For now, we'll pass all messages to the active game's handler
        await active_game.handle_message(update, context)
        await GameSessionManager.update_session(active_game) # Persist state after handling message

async def handle_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    data = (query.data or "").split(":")
    if len(data) < 2 or data[0] != "game":
        await query.answer("Invalid game callback", show_alert=True)
        return
    
    if data[1] == "menu":
        await handle_game_menu(update, context)
        return
    elif data[1] == "select":
        await handle_game_selection(update, context)
        return

    if len(data) < 3:
        await query.answer("Invalid game callback", show_alert=True)
        return

    current_chat = update.effective_chat
    if current_chat is None:
        await query.answer("Invalid game chat", show_alert=True)
        return

    game_name = data[1]
    session_chat_id = current_chat.id
    if data[2] != "join":
        payload_chat = data[-1] if data[-1].lstrip("-").isdigit() else None
        if payload_chat is None:
            await query.answer("Invalid game chat", show_alert=True)
            return
        payload_chat_id = int(payload_chat)
        is_private_topic_selection = (
            game_name == "chameleon"
            and data[2] == "select_topic"
            and getattr(current_chat, "type", None) == "private"
        )
        if payload_chat_id != current_chat.id and not is_private_topic_selection:
            await query.answer("This game action belongs to another chat", show_alert=True)
            return
        session_chat_id = payload_chat_id

    active_game = await GameSessionManager.get_session(session_chat_id, game_name)
    if not active_game or active_game.status != "running":
        await query.answer("This game is no longer active", show_alert=True)
        return

    await active_game.handle_callback(update, context)
    await GameSessionManager.update_session(active_game)


from config.settings import get_settings
from src.handlers.admin_commands import (
    cmd_antiforward,
    cmd_ban,
    cmd_clearrules,
    cmd_groupaddpattern,
    cmd_grouppatterns,
    cmd_groupremovepattern,
    cmd_kick,
    cmd_leave,
    cmd_listpatterns,
    cmd_mute,
    cmd_removepattern,
    cmd_report,
    cmd_resetsettings,
    cmd_resetwarns,
    cmd_rules,
    cmd_setcaptcha,
    cmd_setlang,
    cmd_setleave,
    cmd_setlimits,
    cmd_setmoderation,
    cmd_setmodlog,
    cmd_setraid,
    cmd_setrules,
    cmd_setsilent,
    cmd_setsmart,
    cmd_settings,
    cmd_setwarnlimit,
    cmd_setwelcome,
    cmd_tempbans,
    cmd_testleave,
    cmd_testwelcome,
    cmd_unban,
    cmd_undo,
    cmd_unmute,
    cmd_userinfo,
    cmd_warns,
    cmd_welcome,
)
from src.handlers.callback_handler import handle_callback_query
from src.management.modlog import log_admin_command
from src.pipeline.orchestrator import run_pipeline
from src.pipeline.raid_detector import check_raid, release_lockdown, schedule_lockdown_release
from src.security.admin_authorization import is_authorized_admin
from src.security.input_sanitizer import ValidationError, validate_user_id
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def _audit_direct_admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    command_name: str,
) -> None:
    """Record a direct security command without storing command arguments."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return
    try:
        await log_admin_command(context.bot, chat.id, user.id, command_name)
    except Exception as exc:
        logger.warning(
            "direct_admin_audit_failed",
            command=command_name,
            error=type(exc).__name__,
        )


async def _require_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Require an allowlisted Telegram administrator in a group chat."""
    chat = update.effective_chat
    if not chat or getattr(chat, "type", None) not in ("group", "supergroup"):
        if update.effective_message:
            await update.effective_message.reply_text(
                "هذا الأمر متاح داخل المجموعات فقط | Group-only command."
            )
        return False
    return await is_authorized_admin(update, context.bot)


# ── Primary message handler ────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg:
        return
    if update.effective_user and update.effective_user.is_bot:
        return
    if msg.chat.type not in ("group", "supergroup"):
        return
    await run_pipeline(update, context.bot)


# ── New member / join handler ─────────────────────────────────────────────────

async def _safe_join_effect(label: str, operation, *args, **kwargs):
    try:
        return await operation(*args, **kwargs)
    except Exception as exc:
        logger.warning("join_effect_failed", effect=label, error=type(exc).__name__)
        return None


async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = update.chat_member
    if not result:
        return
    new_status = result.new_chat_member
    old_status = result.old_chat_member
    if not (
        old_status.status in ("left", "kicked", "restricted")
        and new_status.status == "member"
        and not new_status.user.is_bot
    ):
        return

    chat_id = result.chat.id
    user = new_status.user
    user_id = user.id

    # Record join for velocity tracking; a telemetry failure must not block security steps.
    from src.layers.account_intelligence import _record_join
    await _safe_join_effect("record_join", _record_join, user_id, chat_id)

    # Raid detection and scheduled Telegram-side cleanup.
    raid_activated = bool(
        await _safe_join_effect("check_raid", check_raid, context.bot, chat_id, user_id)
    )
    if raid_activated:
        await _safe_join_effect("schedule_lockdown_release", schedule_lockdown_release, context, chat_id)
        from src.management.reports import record_raid_stat
        await _safe_join_effect("record_raid_stat", record_raid_stat, chat_id)

    # CAPTCHA lookup fails closed: do not send a welcome if protection state is unknown.
    from src.layers.captcha_gate import is_captcha_enabled, send_captcha_challenge
    try:
        captcha_enabled = await is_captcha_enabled(chat_id)
    except Exception as exc:
        logger.error("captcha_state_lookup_failed", chat_id=chat_id, error=type(exc).__name__)
        return

    if captcha_enabled:
        await _safe_join_effect(
            "send_captcha_challenge",
            send_captcha_challenge,
            context.bot,
            chat_id,
            user_id,
            user.username,
        )
        return  # Skip welcome if CAPTCHA is active — CAPTCHA IS the welcome

    # Welcome delivery is best-effort after security checks have completed.
    from src.management.welcome_manager import send_welcome_message
    await _safe_join_effect(
        "send_welcome_message",
        send_welcome_message,
        context.bot,
        chat_id,
        user_id,
        user.first_name or "",
        user.username,
        result.chat.title or "Group",
    )


async def handle_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle both joins and real member departures from one ChatMember stream."""
    await handle_new_member(update, context)

    result = update.chat_member
    if not result:
        return
    old_status = result.old_chat_member
    new_status = result.new_chat_member
    if old_status.status not in ("member", "administrator", "creator", "restricted"):
        return
    if old_status.status == "restricted" and not getattr(old_status, "is_member", True):
        return
    if new_status.status not in ("left", "kicked") or new_status.user.is_bot:
        return

    from src.management.welcome_manager import send_leave_message

    await _safe_join_effect(
        "send_leave_message",
        send_leave_message,
        context.bot,
        result.chat.id,
        new_status.user.id,
        new_status.user.first_name or "",
        new_status.user.username,
        result.chat.title or "Group",
    )


# ── Security admin commands ─────────────────────────────────────────────────

async def _probe_runtime_dependencies() -> dict[str, str]:
    """Probe only local runtime dependencies; never label configuration as readiness."""
    import asyncio

    result = {"database": "unknown", "redis": "unknown"}
    try:
        from sqlalchemy import text

        from src.db.session import db_session

        async with db_session() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2.0)
        result["database"] = "ready"
    except Exception as exc:
        logger.warning("status_database_probe_failed", error=type(exc).__name__)
        result["database"] = "unavailable"

    try:
        from src.utils.redis_client import get_redis

        redis = await asyncio.wait_for(get_redis(), timeout=2.0)
        await asyncio.wait_for(redis.ping(), timeout=2.0)
        result["redis"] = "ready"
    except Exception as exc:
        logger.warning("status_redis_probe_failed", error=type(exc).__name__)
        result["redis"] = "unavailable"
    return result


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized_admin(update, context.bot):
        return

    import psutil

    from src.security.api_sentinel import get_status
    from src.security.circuit_breaker import get_state
    from src.security.dos_protection import get_dos_status
    from src.security.human_behavior import get_action_budget_status

    sentinel = await get_status()
    cb_state = await get_state()
    budget = await get_action_budget_status()
    dos = await get_dos_status()
    settings = get_settings()

    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    status_emoji = {0: "🟢", 1: "🟡", 2: "🟡", 3: "🟠", 4: "🔴", 5: "⛔"}

    runtime = await _probe_runtime_dependencies()
    from src.features.voice_chat import _VOICE_READY

    voice_state = "ready" if _VOICE_READY else "unavailable"
    payment_state = "configured" if settings.payment_provider_token else "disabled"
    games = ", ".join(GameManager.list_games()) or "none"

    text = (
        f"🤖 *Bot Status — v3*\n\n"
        f"*Env:* {settings.environment}  |  *Dry-run:* {'⚠️ON' if settings.dry_run else '✅OFF'}\n\n"
        f"*⚙️ Runtime*\n"
        f"DB: `{runtime['database']}`  |  Redis: `{runtime['redis']}`\n"
        f"Voice backend: `{voice_state}`  |  Payments: `{payment_state}`\n"
        f"Games: `{games}`\n\n"
        f"*🖥 System*\n"
        f"CPU: {cpu:.1f}%  |  RAM: {mem.percent:.1f}%  |  RSS: {dos['rss_mb']:.0f}MB\n"
        f"AI Shed: {'⚠️YES' if dos['ai_shed'] else 'No'}  |  "
        f"Crit Drop: {'⛔YES' if dos['critical'] else 'No'}\n\n"
        f"*🛡 Security*\n"
        f"Threat: {status_emoji.get(sentinel.threat_level, '❓')} {sentinel.threat_level}/5  |  "
        f"Safe-Mode: {'⛔ACTIVE' if sentinel.safe_mode_active else '✅Off'}\n"
        f"Circuit Breaker: `{cb_state.value.upper()}`\n"
        f"FloodWaits (1h): {sentinel.total_flood_waits}  |  "
        f"Forbidden: {sentinel.total_forbidden}\n"
        f"Action Success: {sentinel.action_success_rate:.0%}\n\n"
        f"*⚡ Pacing*\n"
        f"Actions (60s): {budget['recent_actions_60s']}  |  "
        f"Fatigue: {'YES' if budget['fatigue_active'] else 'No'}\n"
    )

    if sentinel.recommendations:
        text += "\n*⚠️ Recommendations*\n"
        for rec in sentinel.recommendations:
            text += f"• {rec}\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_safemode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized_admin(update, context.bot):
        return
    from src.security.api_sentinel import is_safe_mode, reset_safe_mode
    from src.security.circuit_breaker import manual_reset, manual_trip
    if not context.args:
        active = await is_safe_mode()
        await update.message.reply_text(f"Safe-mode: {'ON ⛔' if active else 'OFF ✅'}")
        return
    if context.args[0].lower() == "on":
        await manual_trip(reason="admin")
        await update.message.reply_text("⛔ *Safe-mode ON* — logging only.", parse_mode="Markdown")
    elif context.args[0].lower() == "off":
        await reset_safe_mode()
        await manual_reset()
        await update.message.reply_text("✅ *Safe-mode OFF*", parse_mode="Markdown")


async def cmd_resetbreaker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized_admin(update, context.bot):
        return
    from src.security.circuit_breaker import manual_reset
    await manual_reset()
    await update.message.reply_text("✅ Circuit breaker reset.")


async def cmd_threatinfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized_admin(update, context.bot):
        return
    if not context.args:
        await update.message.reply_text("Usage: /threatinfo <user_id>")
        return
    try:
        target_id = validate_user_id(context.args[0])
    except ValidationError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    from src.intelligence.cross_group_intel import get_user_threat
    profile = await get_user_threat(target_id)
    level_names = {0: "NONE", 1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}
    level_emoji = {0: "✅", 1: "🟡", 2: "🟠", 3: "🔴", 4: "⛔"}
    text = (
        f"🔍 *Threat: `{target_id}`*\n"
        f"Level: {level_emoji.get(int(profile.threat_level), '❓')} "
        f"*{level_names.get(int(profile.threat_level), 'UNKNOWN')}*\n"
        f"Bans: {profile.ban_count}  |  Groups: {len(profile.source_groups)}\n"
        f"Violations: {', '.join(profile.violation_types) or 'none'}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_falsepositive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_group_admin(update, context):
        return
    from src.intelligence.adaptive_thresholds import record_false_positive
    await record_false_positive(update.effective_chat.id)
    await _audit_direct_admin_command(update, context, "cmd_falsepositive")
    await update.message.reply_text("📝 False positive recorded.")


async def cmd_groupstats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_group_admin(update, context):
        return
    from src.management.reports import format_report, generate_report
    report = await generate_report(update.effective_chat.id, days=7)
    await _audit_direct_admin_command(update, context, "cmd_groupstats")
    await update.message.reply_text(format_report(report), parse_mode="Markdown")


async def cmd_unlock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_group_admin(update, context):
        return
    await release_lockdown(context.bot, update.effective_chat.id)
    await _audit_direct_admin_command(update, context, "cmd_unlock")
    await update.message.reply_text("✅ Lockdown released.")


async def cmd_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_group_admin(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /whitelist <user_id>")
        return
    try:
        target_id = validate_user_id(context.args[0])
    except ValidationError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    from src.utils.redis_client import get_redis
    redis = await get_redis()
    settings = get_settings()
    await redis.set(f"{settings.redis_prefix}wl:{update.effective_chat.id}:{target_id}", "1")
    await _audit_direct_admin_command(update, context, "cmd_whitelist")
    await update.message.reply_text(f"✅ User `{target_id}` whitelisted.", parse_mode="Markdown")


async def cmd_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_group_admin(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /blacklist <user_id>")
        return
    try:
        target_id = validate_user_id(context.args[0])
    except ValidationError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    from src.utils.redis_client import get_redis
    redis = await get_redis()
    settings = get_settings()
    await redis.set(f"{settings.redis_prefix}gbl:{target_id}", "1")
    await _audit_direct_admin_command(update, context, "cmd_blacklist")
    await update.message.reply_text(f"🚫 User `{target_id}` globally blacklisted.", parse_mode="Markdown")


async def cmd_dryrun(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized_admin(update, context.bot):
        return
    settings = get_settings()
    if not context.args:
        await update.message.reply_text(f"Dry-run: {'ON' if settings.dry_run else 'OFF'}")
        return
    if context.args[0].lower() == "on":
        settings.dry_run = True
        await update.message.reply_text("🟡 Dry-run *ON*", parse_mode="Markdown")
    elif context.args[0].lower() == "off":
        settings.dry_run = False
        await update.message.reply_text("🟢 Dry-run *OFF*", parse_mode="Markdown")


# ── /start command — supports shop referral links ────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    args = context.args or []
    ref_code: str | None = None

    if args and args[0].startswith("ref_"):
        ref_code = args[0][4:]

    from src.shop.notification_engine import send_notification
    from src.shop.user_engine import get_or_create_shop_user

    shop_user = await get_or_create_shop_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
        referred_by_code=ref_code,
    )

    if ref_code and shop_user.referred_by:
        from sqlalchemy import select

        from src.db.session import db_session
        from src.shop.models import ShopUser
        async with db_session() as session:
            result = await session.execute(
                select(ShopUser).where(ShopUser.telegram_id == shop_user.referred_by)
            )
            referrer = result.scalar_one_or_none()
            if referrer:
                await send_notification(
                    referrer.telegram_id,
                    "🔗 إحالة جديدة!",
                    "انضم مستخدم جديد عبر رابط إحالتك! ستحصل على عمولة عند أول شراء له.",
                    bot=context.bot,
                )

    keyboard = [
        [
            InlineKeyboardButton("🏪 فتح المتجر", callback_data="shop:main"),
            InlineKeyboardButton("👤 ملفي", callback_data="shop:profile"),
        ],
    ]

    welcome = (
        f"👋 مرحباً {user.first_name or 'بك'}!\n\n"
        f"أنا *Guardian Bot* — بوت حماية المجموعات والمتجر الذكي.\n\n"
        f"🏪 *المتجر:* `/shop`\n"
        f"🎮 *الألعاب:* `/games`\n"
        f"📖 *القرآن:* `/quran`\n\n"
    )

    if ref_code and shop_user.referred_by:
        welcome += "🎁 تم تسجيل كود الإحالة! ستحصل مُحيلك على عمولة عند أول شراء.\n\n"

    welcome += "استخدم /shop لفتح المتجر 👇"

    await update.message.reply_text(
        welcome,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


# ── Handler registration ─────────────────────────────────────────────────────

def register_handlers(app: Application) -> None:
    # Message handler
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & (
                filters.TEXT | filters.PHOTO | filters.VIDEO |
                filters.Document.ALL | filters.ANIMATION |
                filters.Sticker.ALL | filters.AUDIO | filters.VOICE
            ),
            handle_message,
        )
    )

    # Member join/leave
    app.add_handler(ChatMemberHandler(handle_member_update, ChatMemberHandler.CHAT_MEMBER))

    # Callback queries (CAPTCHA, rules)
    app.add_handler(
        CallbackQueryHandler(
            handle_callback_query,
            pattern=r"^(captcha:|rules_ack:|show_rules:)",
        )
    )

    # Game utility commands
    app.add_handler(CommandHandler("gamescores", cmd_gamescores, filters=filters.ChatType.GROUPS))

    # Security commands
    security_commands = [
        ("status", cmd_status),
        ("safemode", cmd_safemode),
        ("resetbreaker", cmd_resetbreaker),
        ("threatinfo", cmd_threatinfo),
        ("falsepositive", cmd_falsepositive),
        ("groupstats", cmd_groupstats),
        ("groupaddpattern", cmd_groupaddpattern),
        ("groupremovepattern", cmd_groupremovepattern),
        ("grouppatterns", cmd_grouppatterns),
        ("unlock", cmd_unlock),
        ("whitelist", cmd_whitelist),
        ("blacklist", cmd_blacklist),
        ("dryrun", cmd_dryrun),
    ]

    # Management commands
    management_commands = [
        ("setrules", cmd_setrules),
        ("setraid", cmd_setraid),
        ("setleave", cmd_setleave),
        ("leave", cmd_leave),
        ("testleave", cmd_testleave),
        ("rules", cmd_rules),
        ("clearrules", cmd_clearrules),
        ("setwelcome", cmd_setwelcome),
        ("welcome", cmd_welcome),
        ("testwelcome", cmd_testwelcome),
        ("setmodlog", cmd_setmodlog),
        ("setmoderation", cmd_setmoderation),
        ("setlimits", cmd_setlimits),
        ("setlang", cmd_setlang),
        ("setcaptcha", cmd_setcaptcha),
        ("antiforward", cmd_antiforward),
        ("settings", cmd_settings),
        ("resetsettings", cmd_resetsettings),
        ("setsilent", cmd_setsilent),
        ("setsmart", cmd_setsmart),
        ("userinfo", cmd_userinfo),
        ("warns", cmd_warns),
        ("resetwarns", cmd_resetwarns),
        ("setwarnlimit", cmd_setwarnlimit),
        ("mute", cmd_mute),
        ("unmute", cmd_unmute),
        ("ban", cmd_ban),
        ("unban", cmd_unban),
        ("undo", cmd_undo),
        ("kick", cmd_kick),
        ("tempbans", cmd_tempbans),
        ("report", cmd_report),
        ("addpattern", cmd_addpattern),
        ("removepattern", cmd_removepattern),
        ("listpatterns", cmd_listpatterns),
    ]

    for cmd, handler in security_commands + management_commands:
        app.add_handler(CommandHandler(cmd, handler))

    logger.info("handlers_registered_v3", total_commands=len(security_commands) + len(management_commands))

    # ── Feature modules (Phase 2 additive extensions) ─────────────────────────
    from src.features.register import register_all_features
    register_all_features(app)

    # ── Shop (Commerce System) ────────────────────────────────────────────────
    from src.shop.handlers.register import register_shop_handlers
    register_shop_handlers(app)

    # /start handler — supports referral links (?start=ref_XXXX)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("grouphelp", cmd_grouphelp))

    # ── Game handlers ────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("games", cmd_games))
    app.add_handler(CommandHandler("play", cmd_play))
    app.add_handler(CommandHandler("mafia_start", cmd_mafia_start))
    app.add_handler(CommandHandler("cham_start", cmd_cham_start))
    app.add_handler(CommandHandler("stopgame", cmd_stopgame))

    # Message and Callback handlers for active games
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & (
                filters.TEXT | filters.PHOTO | filters.VIDEO |
                filters.Document.ALL | filters.ANIMATION |
                filters.Sticker.ALL | filters.AUDIO | filters.VOICE
            ),
            handle_game_message,
            block=False,
        ),
        group=1,  # Run after moderation; each group can process one matching handler.
    )
    app.add_handler(CallbackQueryHandler(handle_game_callback, pattern=r"^game:"), group=1)

