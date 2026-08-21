"""
Telegram Group Protection Bot — Entry Point
============================================
Starts the bot in either polling (development) or webhook (production) mode.

Usage:
    python main.py

Environment variables (see config/settings.py for full list):
    TELEGRAM_BOT_TOKEN  — required
    DATABASE_URL        — PostgreSQL connection string
    REDIS_URL           — Redis connection string
    TELEGRAM_WEBHOOK_URL — Set to enable webhook mode (leave empty for polling)
"""
from __future__ import annotations

import os
import sys

# Ensure bot/ is on the path when running from project root
sys.path.insert(0, os.path.dirname(__file__))

from telegram import Update
from telegram.ext import Application, ApplicationBuilder

from config.settings import get_settings
from src.db.session import close_db, init_db
from src.handlers.message_handler import register_handlers
from src.utils.background_tasks import cancel_background_tasks
from src.utils.logger import configure_logging, get_logger
from src.utils.redis_client import close_redis, get_redis

logger = get_logger(__name__)


async def post_init(app: Application) -> None:
    """Called after Application is initialized but before polling/webhook starts."""
    settings = get_settings()

    # Initialize database tables (idempotent)
    try:
        await init_db()
    except Exception as exc:
        logger.exception("db_init_failed", error=type(exc).__name__)
        if settings.environment.strip().lower() in {"production", "staging"}:
            raise

    # Warm Redis connection
    try:
        await get_redis()
    except Exception as exc:
        logger.exception("redis_init_failed", error=type(exc).__name__)
        if settings.environment.strip().lower() in {"production", "staging"}:
            raise

    # Start optional voice backend when its credentials and dependencies are configured.
    # A voice failure must not prevent moderation and group protection from starting.
    try:
        from src.features.voice_chat import start_voice_backend

        await start_voice_backend()
    except Exception as exc:
        logger.warning("voice_backend_init_failed", error=type(exc).__name__)

    logger.info(
        "bot_initialized",
        environment=settings.environment,
        dry_run=settings.dry_run,
        webhook=bool(settings.telegram_webhook_url),
    )


async def post_shutdown(app: Application) -> None:
    """Graceful shutdown: stop optional backends and close DB/Redis connections."""
    try:
        from src.features.voice_chat import stop_voice_backend

        await stop_voice_backend()
    except Exception as exc:
        logger.warning("voice_backend_shutdown_failed", error=type(exc).__name__)

    await cancel_background_tasks()
    await close_db()
    await close_redis()
    logger.info("bot_shutdown_complete")


def build_application() -> Application:
    settings = get_settings()

    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    register_handlers(app)
    return app


def main() -> None:
    settings = get_settings()

    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    logger.info("bot_starting", environment=settings.environment)

    app = build_application()

    if settings.telegram_webhook_url:
        # ── Webhook mode (production) ─────────────────────────────────────────
        logger.info(
            "starting_webhook",
            url=settings.telegram_webhook_url,
            port=settings.telegram_webhook_port,
        )
        app.run_webhook(
            listen="0.0.0.0",
            port=settings.telegram_webhook_port,
            url_path="telegram-webhook",
            webhook_url=f"{settings.telegram_webhook_url.rstrip('/')}/telegram-webhook",
            secret_token=settings.telegram_webhook_secret or None,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    else:
        # ── Long polling mode (development) ───────────────────────────────────
        logger.info("starting_polling")
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


if __name__ == "__main__":
    main()
