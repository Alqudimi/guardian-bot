"""
Callback Query Handler
=======================
Handles all inline button callback queries:
  - CAPTCHA challenge responses
  - Rules acknowledgment
  - Group settings quick-toggles
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from src.utils.logger import get_logger

logger = get_logger(__name__)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data

    # ── CAPTCHA callback ───────────────────────────────────────────────────────
    if data.startswith("captcha:"):
        parts = data.split(":", 3)
        if len(parts) != 4:
            return
        _, chat_id_str, user_id_str, answer = parts
        try:
            chat_id = int(chat_id_str)
            user_id = int(user_id_str)
        except ValueError:
            await query.answer("⛔ تحقق غير صالح.", show_alert=True)
            return
        if user_id <= 0 or (query.message and query.message.chat_id != chat_id):
            await query.answer("⛔ تحقق غير صالح لهذه المحادثة.", show_alert=True)
            return

        # Only the challenged user can answer
        if query.from_user.id != user_id:
            await query.answer("⛔ هذا التحقق ليس لك | This CAPTCHA is not for you.", show_alert=True)
            return

        from src.layers.captcha_gate import handle_captcha_callback
        from src.management.reports import record_captcha_result

        correct = await handle_captcha_callback(context.bot, chat_id, user_id, answer)
        try:
            await record_captcha_result(chat_id, correct)
        except Exception as exc:
            logger.warning("captcha_metric_failed", chat_id=chat_id, error=type(exc).__name__)
        if correct:
            await query.answer("✅ تم التحقق! | Verified! You can now chat.", show_alert=True)
            logger.info("captcha_callback_passed", user_id=user_id, chat_id=chat_id)
        else:
            await query.answer("❌ إجابة خاطئة | Wrong answer. Try again.", show_alert=True)
        return

    # ── Rules acknowledgment ───────────────────────────────────────────────────
    if data.startswith("rules_ack:"):
        try:
            chat_id = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            await query.answer("⛔ طلب غير صالح.", show_alert=True)
            return
        if not query.message or query.message.chat_id != chat_id:
            await query.answer("⛔ هذا الزر غير صالح لهذه المحادثة.", show_alert=True)
            return
        await query.answer("✅ شكراً! | Thank you for reading the rules!", show_alert=False)
        return

    # ── Show rules button (from welcome message) ───────────────────────────────
    if data.startswith("show_rules:"):
        try:
            chat_id = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            await query.answer("⛔ طلب غير صالح.", show_alert=True)
            return
        if not query.message or query.message.chat_id != chat_id:
            await query.answer("⛔ هذا الزر غير صالح لهذه المحادثة.", show_alert=True)
            return
        from src.management.rules_manager import get_rules
        rules = await get_rules(chat_id)
        if rules:
            try:
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=f"📋 *Group Rules*\n\n{rules}",
                    parse_mode="Markdown",
                )
                await query.answer()
            except Exception as exc:
                logger.warning("rules_dm_failed", user_id=query.from_user.id, error=type(exc).__name__)
                await query.answer("تعذر إرسال القواعد في الخاص.", show_alert=True)
        else:
            await query.answer("No rules set yet.", show_alert=True)
        return
