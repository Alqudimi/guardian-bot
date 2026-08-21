"""
Central configuration using pydantic-settings.
All values are loaded from environment variables or .env file.
"""
from __future__ import annotations

import json
import re

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token: str = Field(default="", description="Bot token from @BotFather")
    telegram_admin_ids: list[int] = Field(default_factory=list)
    telegram_webhook_url: str = Field(default="", description="HTTPS webhook URL (empty = polling)")
    telegram_webhook_port: int = Field(default=8443)
    telegram_webhook_secret: str = Field(default="")

    # ── Telegram Payments ──────────────────────────────────────────────────────
    payment_provider_token: str = Field(
        default="",
        description="Provider token from BotFather Payments; empty disables deposits",
    )
    payment_currency: str = Field(default="USD")

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_prefix: str = Field(default="tgbot:")

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/tgbot"
    )
    auto_create_tables: bool | None = Field(
        default=None,
        description="Development-only convenience; production requires Alembic migrations",
    )

    # ── AI Model paths / IDs ──────────────────────────────────────────────────
    arabic_toxicity_model: str = Field(default="hossam87/bert-base-arabic-hate-speech")
    nsfw_model: str = Field(default="Marqo/nsfw-image-detection-384")
    model_cache_dir: str = Field(default="./model_cache")
    model_device: str = Field(default="cpu")  # "cpu" | "cuda" | "mps"

    # ── Thresholds ────────────────────────────────────────────────────────────
    toxicity_threshold: float = Field(default=0.65)
    nsfw_threshold: float = Field(default=0.75)
    spam_score_threshold: float = Field(default=60.0)
    phishing_threshold: float = Field(default=0.70)

    # ── Flood / Rate-limit windows ────────────────────────────────────────────
    flood_window_seconds: int = Field(default=10)
    flood_max_messages: int = Field(default=8)
    burst_window_seconds: int = Field(default=3)
    burst_max_messages: int = Field(default=4)
    duplicate_window_seconds: int = Field(default=30)

    # ── Trust scoring ─────────────────────────────────────────────────────────
    trust_score_initial: float = Field(default=50.0)
    trust_score_max: float = Field(default=100.0)
    trust_score_min: float = Field(default=0.0)
    trust_new_account_days: int = Field(default=30)

    # ── Action execution safety ───────────────────────────────────────────────
    # Max moderation actions the bot performs per minute globally
    action_rate_limit_per_minute: int = Field(default=20)
    # Min seconds between successive actions on the same user
    action_cooldown_per_user_seconds: int = Field(default=5)
    # Max bans triggered per hour before entering safe-mode
    ban_hourly_limit: int = Field(default=10)
    # Max deletes per minute
    delete_rate_per_minute: int = Field(default=30)

    # ── Raid lockdown ─────────────────────────────────────────────────────────
    raid_join_window_seconds: int = Field(default=30)
    raid_join_threshold: int = Field(default=10)

    # ── Anti-ban Telegram safety ──────────────────────────────────────────────
    # Introduce jitter delay (seconds) between successive Telegram API calls
    action_jitter_min: float = Field(default=0.3)
    action_jitter_max: float = Field(default=1.2)

    # ── Celery ────────────────────────────────────────────────────────────────
    celery_broker_url: str = Field(default="redis://localhost:6379/1")
    celery_result_backend: str = Field(default="redis://localhost:6379/2")

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=True)

    # ── Misc ──────────────────────────────────────────────────────────────────
    environment: str = Field(default="development")
    dry_run: bool = Field(default=False, description="Log decisions but do not execute actions")

    @field_validator("telegram_webhook_port")
    @classmethod
    def validate_webhook_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("TELEGRAM_WEBHOOK_PORT must be between 1 and 65535")
        return value

    @field_validator(
        "flood_window_seconds",
        "flood_max_messages",
        "burst_window_seconds",
        "burst_max_messages",
        "duplicate_window_seconds",
        "action_rate_limit_per_minute",
        "action_cooldown_per_user_seconds",
        "ban_hourly_limit",
        "delete_rate_per_minute",
        "raid_join_window_seconds",
        "raid_join_threshold",
        "trust_new_account_days",
    )
    @classmethod
    def validate_positive_limits(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("security and rate-limit settings must be positive")
        return value

    @field_validator("telegram_admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: object) -> list[int]:
        """Accept comma-separated, JSON, scalar, or list values safely."""
        if v is None or v == "":
            return []

        if isinstance(v, int):
            values = [v]
        elif isinstance(v, str):
            raw = v.strip()
            if not raw:
                return []
            if raw.startswith("["):
                try:
                    decoded = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError("TELEGRAM_ADMIN_IDS must be comma-separated IDs or a JSON list") from exc
                values = decoded if isinstance(decoded, list) else [decoded]
            else:
                values = raw.split(",")
        elif isinstance(v, (list, tuple, set)):
            values = list(v)
        else:
            raise TypeError("TELEGRAM_ADMIN_IDS has an unsupported type")

        result: list[int] = []
        for value in values:
            try:
                admin_id = int(str(value).strip())
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid Telegram admin ID: {value!r}") from exc
            if admin_id <= 0:
                raise ValueError("Telegram admin IDs must be positive integers")
            if admin_id not in result:
                result.append(admin_id)
        return result

    @field_validator("telegram_bot_token")
    @classmethod
    def validate_bot_token_format(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return value
        if not re.fullmatch(r"\d{8,12}:[A-Za-z0-9_-]{35}", value):
            raise ValueError("TELEGRAM_BOT_TOKEN has an invalid format")
        return value

    @model_validator(mode="after")
    def validate_runtime_configuration(self) -> Settings:
        environment = self.environment.strip().lower()
        if self.auto_create_tables is None:
            self.auto_create_tables = environment not in {"production", "staging"}
        if environment in {"production", "staging"} and self.auto_create_tables:
            raise ValueError("AUTO_CREATE_TABLES must be false in production and staging")
        if environment in {"production", "staging"} and not self.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required in production and staging")

        if self.telegram_webhook_url:
            if not self.telegram_webhook_url.startswith("https://"):
                raise ValueError("TELEGRAM_WEBHOOK_URL must use HTTPS")
            if not self.telegram_webhook_secret:
                raise ValueError("TELEGRAM_WEBHOOK_SECRET is required when webhook mode is enabled")
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", self.telegram_webhook_secret):
                raise ValueError("TELEGRAM_WEBHOOK_SECRET must be 16-256 URL-safe characters")

        self.payment_currency = self.payment_currency.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", self.payment_currency):
            raise ValueError("PAYMENT_CURRENCY must be a three-letter ISO currency code")

        for field_name in ("toxicity_threshold", "nsfw_threshold", "phishing_threshold"):
            value = getattr(self, field_name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0 and 1")

        if self.action_jitter_min < 0 or self.action_jitter_max < self.action_jitter_min:
            raise ValueError("Action jitter bounds are invalid")
        return self


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
