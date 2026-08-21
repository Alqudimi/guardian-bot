from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError as PydanticValidationError

_VALID_TOKEN = "123456789:" + "A" * 35


def test_admin_ids_accept_scalar_and_comma_separated_values() -> None:
    from config.settings import Settings

    scalar = Settings(_env_file=None, telegram_admin_ids=123456789)
    csv = Settings(_env_file=None, telegram_admin_ids="123456789, 987654321, 123456789")
    json_list = Settings(_env_file=None, telegram_admin_ids="[123456789, 987654321]")

    assert scalar.telegram_admin_ids == [123456789]
    assert csv.telegram_admin_ids == [123456789, 987654321]
    assert json_list.telegram_admin_ids == [123456789, 987654321]


def test_admin_ids_reject_invalid_values() -> None:
    from config.settings import Settings

    with pytest.raises(PydanticValidationError):
        Settings(_env_file=None, telegram_admin_ids="not-an-id")
    with pytest.raises(PydanticValidationError):
        Settings(_env_file=None, telegram_admin_ids="-1")


def test_production_requires_valid_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from config.settings import Settings

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(PydanticValidationError):
        Settings(_env_file=None, environment="production")

    settings = Settings(_env_file=None, environment="production", telegram_bot_token=_VALID_TOKEN)
    assert settings.telegram_bot_token == _VALID_TOKEN


def test_webhook_requires_https_and_secret() -> None:
    from config.settings import Settings

    with pytest.raises(PydanticValidationError):
        Settings(
            _env_file=None,
            environment="production",
            telegram_bot_token=_VALID_TOKEN,
            telegram_webhook_url="http://bot.example.com",
        )

    with pytest.raises(PydanticValidationError):
        Settings(
            _env_file=None,
            environment="production",
            telegram_bot_token=_VALID_TOKEN,
            telegram_webhook_url="https://bot.example.com",
        )

    settings = Settings(
        _env_file=None,
        environment="production",
        telegram_bot_token=_VALID_TOKEN,
        telegram_webhook_url="https://bot.example.com",
        telegram_webhook_secret="S" * 32,
    )
    assert settings.telegram_webhook_secret == "S" * 32


@pytest.mark.asyncio
async def test_admin_authorization_requires_group_admin_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import settings as settings_module
    from config.settings import Settings
    from src.security.admin_authorization import is_authorized_admin

    settings_module._settings = Settings(_env_file=None, telegram_admin_ids=[42])
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
    )
    bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")))

    assert await is_authorized_admin(update, bot) is False
    bot.get_chat_member.return_value = SimpleNamespace(status="administrator")
    assert await is_authorized_admin(update, bot) is True


@pytest.mark.asyncio
async def test_admin_authorization_denies_lookup_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from telegram.error import NetworkError

    from config import settings as settings_module
    from config.settings import Settings
    from src.security.admin_authorization import is_authorized_admin

    settings_module._settings = Settings(_env_file=None, telegram_admin_ids=[42])
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=-1001, type="group"),
    )
    bot = SimpleNamespace(get_chat_member=AsyncMock(side_effect=NetworkError("offline")))

    assert await is_authorized_admin(update, bot) is False


def test_logging_event_redacts_credentials() -> None:
    from src.utils.logger import _sanitize_event

    event = _sanitize_event(
        {
            "message": "token=123456789:" + "B" * 35,
            "dsn": "postgresql+asyncpg://user:password@db:5432/app",
        }
    )

    assert "B" * 35 not in event["message"]
    assert "password" not in event["dsn"]


def test_borderline_actions_are_never_skipped() -> None:
    from src.security.human_behavior import should_miss_borderline

    assert all(should_miss_borderline(score) is False for score in (40, 50, 57, 80))


@pytest.mark.asyncio
async def test_action_cooldown_reservation_blocks_concurrent_retry() -> None:
    from config import settings as settings_module
    from config.settings import Settings
    from src.layers.action_execution import _can_execute_action
    from src.utils.redis_client import get_redis

    previous = settings_module._settings
    settings_module._settings = Settings(
        _env_file=None,
        telegram_admin_ids=[],
        redis_prefix="pytest:cooldown:",
        action_cooldown_per_user_seconds=5,
        action_rate_limit_per_minute=100,
    )
    redis = await get_redis()
    global_key = "pytest:cooldown:act_global"
    user_key = "pytest:cooldown:act_user:-100:777"
    await redis.delete(global_key, user_key)

    try:
        first = await _can_execute_action(redis, 777, -100)
        second = await _can_execute_action(redis, 777, -100)
        assert first == (True, "")
        assert second == (False, "per_user_cooldown")
    finally:
        await redis.delete(global_key, user_key)
        settings_module._settings = previous


@pytest.mark.asyncio
async def test_webhook_update_id_deduplication_uses_real_redis() -> None:
    from config import settings as settings_module
    from config.settings import Settings
    from src.security.webhook_hardening import is_update_id_seen
    from src.utils.redis_client import get_redis

    previous = settings_module._settings
    settings_module._settings = Settings(
        _env_file=None,
        telegram_admin_ids=[],
        redis_prefix="pytest:webhook:",
    )
    redis = await get_redis()
    key = "pytest:webhook:webhook_uid:987654321"
    await redis.delete(key)

    try:
        assert await is_update_id_seen(987654321) is False
        assert await is_update_id_seen(987654321) is True
    finally:
        await redis.delete(key)
        settings_module._settings = previous


def test_full_application_builds_and_registers_handler_groups() -> None:
    from config import settings as settings_module
    from config.settings import Settings
    from main import build_application

    previous = settings_module._settings
    settings_module._settings = Settings(
        _env_file=None,
        environment="development",
        telegram_bot_token=_VALID_TOKEN,
        telegram_admin_ids=[42],
        dry_run=True,
    )
    try:
        app = build_application()
        assert {0, 1, 2}.issubset(app.handlers)
        assert sum(len(group_handlers) for group_handlers in app.handlers.values()) >= 70
    finally:
        settings_module._settings = previous


def test_play_command_has_single_owner_and_explicit_music_alias() -> None:
    from telegram.ext import CommandHandler

    from config import settings as settings_module
    from config.settings import Settings
    from main import build_application

    previous = settings_module._settings
    settings_module._settings = Settings(
        _env_file=None,
        environment="development",
        telegram_bot_token=_VALID_TOKEN,
        telegram_admin_ids=[42],
        dry_run=True,
    )
    try:
        app = build_application()
        play_handlers = [
            handler
            for handlers in app.handlers.values()
            for handler in handlers
            if isinstance(handler, CommandHandler) and handler.commands == frozenset({"play"})
        ]
        music_handlers = [
            handler
            for handlers in app.handlers.values()
            for handler in handlers
            if isinstance(handler, CommandHandler) and handler.commands == frozenset({"music"})
        ]

        assert len(play_handlers) == 1
        assert play_handlers[0].callback.__module__ == "src.handlers.message_handler"
        assert len(music_handlers) == 1
        assert music_handlers[0].callback.__module__ == "src.features.voice_chat"
    finally:
        settings_module._settings = previous


@pytest.mark.asyncio
async def test_play_dispatches_registered_games_and_delegates_music() -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from src.handlers.message_handler import cmd_play

    update = object()
    with patch(
        "src.handlers.message_handler._start_game", new_callable=AsyncMock
    ) as start_game:
        await cmd_play(update, SimpleNamespace(args=["mafia"]))
        start_game.assert_awaited_once_with(update, start_game.await_args.args[1], "mafia")

    with patch(
        "src.handlers.message_handler._delegate_music_play", new_callable=AsyncMock
    ) as delegate_music:
        await cmd_play(update, SimpleNamespace(args=["lofi", "mix"]))
        await cmd_play(update, SimpleNamespace(args=["mafia", "song"]))
        assert delegate_music.await_count == 2


@pytest.mark.asyncio
async def test_delete_budget_is_enforced_by_real_redis() -> None:
    from config import settings as settings_module
    from config.settings import Settings
    from src.layers.action_execution import _reserve_delete_slot
    from src.utils.redis_client import get_redis

    previous = settings_module._settings
    settings_module._settings = Settings(
        _env_file=None,
        telegram_admin_ids=[],
        redis_prefix="pytest:delete-budget:",
        delete_rate_per_minute=1,
    )
    redis = await get_redis()
    key = "pytest:delete-budget:deletes_minute"
    await redis.delete(key)

    try:
        assert await _reserve_delete_slot(redis, -100, 1) is True
        assert await _reserve_delete_slot(redis, -100, 2) is False
    finally:
        await redis.delete(key)
        settings_module._settings = previous


@pytest.mark.asyncio
async def test_antiban_budget_uses_runtime_settings() -> None:
    from config import settings as settings_module
    from config.settings import Settings
    from src.utils.anti_ban import get_action_budget
    from src.utils.redis_client import get_redis

    previous = settings_module._settings
    settings_module._settings = Settings(
        _env_file=None,
        telegram_admin_ids=[],
        redis_prefix="pytest:runtime-budget:",
        action_rate_limit_per_minute=7,
        ban_hourly_limit=3,
        delete_rate_per_minute=2,
    )
    redis = await get_redis()
    await redis.delete(
        "pytest:runtime-budget:act_global",
        "pytest:runtime-budget:bans_hourly",
        "pytest:runtime-budget:deletes_minute",
    )

    try:
        budget = await get_action_budget()
        assert budget.global_remaining == 7
        assert budget.ban_remaining == 3
        assert budget.delete_remaining == 2
    finally:
        settings_module._settings = previous


@pytest.mark.asyncio
async def test_link_expansion_blocks_loopback_before_network() -> None:
    from src.layers.link_analysis import _expand_url

    assert await _expand_url("http://127.0.0.1:9/internal") is None


@pytest.mark.asyncio
async def test_ssrf_guard_fails_closed_on_dns_resolution_failure(monkeypatch) -> None:
    import src.security.ssrf_guard as ssrf_guard

    async def no_dns(_hostname: str) -> list[str]:
        return []

    monkeypatch.setattr(ssrf_guard, "_resolve_hostname", no_dns)
    safe, reason = await ssrf_guard.validate_url("https://example.invalid/path")
    assert safe is False
    assert reason == "dns_unresolvable"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("action_rate_limit_per_minute", 0),
        ("delete_rate_per_minute", -1),
        ("flood_window_seconds", 0),
    ],
)
def test_security_limits_must_be_positive(field_name: str, value: int) -> None:
    from config.settings import Settings

    with pytest.raises(ValueError, match="must be positive"):
        Settings(_env_file=None, **{field_name: value})


def test_webhook_port_must_be_valid_tcp_port() -> None:
    from config.settings import Settings

    with pytest.raises(ValueError, match="between 1 and 65535"):
        Settings(_env_file=None, telegram_webhook_port=70000)



def test_dynamic_regex_search_has_bounded_input_and_timeout() -> None:
    import regex as re2

    from src.layers.fast_rules import _safe_dynamic_search

    pattern = re2.compile(r"(a+)+$")
    assert _safe_dynamic_search(pattern, "a" * 5000 + "!") is False


@pytest.mark.asyncio
async def test_empty_dynamic_pattern_cache_short_circuits_with_real_redis() -> None:
    from config import settings as settings_module
    from config.settings import Settings
    from src.layers.fast_rules import _load_db_patterns
    from src.utils.redis_client import get_redis

    previous = settings_module._settings
    settings_module._settings = Settings(
        _env_file=None,
        telegram_admin_ids=[],
        redis_prefix="pytest:empty-patterns:",
    )
    redis = await get_redis()
    marker = "pytest:empty-patterns:db_patterns:compiled:empty"
    await redis.set(marker, "1", ex=60)

    try:
        assert await _load_db_patterns() == []
    finally:
        await redis.delete(marker)
        settings_module._settings = previous



def test_alembic_metadata_includes_shop_tables() -> None:
    import src.shop.models  # noqa: F401
    from src.db.models import Base

    expected = {
        "groups",
        "users",
        "moderation_events",
        "shop_users",
        "services",
        "shop_orders",
        "support_tickets",
    }
    assert expected.issubset(Base.metadata.tables)



def test_auto_create_tables_policy_is_environment_aware() -> None:
    from config.settings import Settings

    development = Settings(_env_file=None, environment="development")
    assert development.auto_create_tables is True

    production = Settings(
        _env_file=None,
        environment="production",
        telegram_bot_token=_VALID_TOKEN,
        auto_create_tables=False,
    )
    assert production.auto_create_tables is False

    with pytest.raises(ValueError, match="AUTO_CREATE_TABLES"):
        Settings(
            _env_file=None,
            environment="production",
            telegram_bot_token=_VALID_TOKEN,
            auto_create_tables=True,
        )


@pytest.mark.asyncio
async def test_init_db_blocks_unmigrated_production_database(tmp_path) -> None:
    from config import settings as settings_module
    from config.settings import Settings
    from src.db import session as db_module

    previous_settings = settings_module._settings
    previous_engine = db_module._engine
    previous_factory = db_module._session_factory
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'production.db'}"
    settings_module._settings = Settings(
        _env_file=None,
        environment="production",
        telegram_bot_token=_VALID_TOKEN,
        auto_create_tables=False,
        database_url=db_url,
    )
    db_module._engine = None
    db_module._session_factory = None

    try:
        with pytest.raises(RuntimeError, match="alembic upgrade head"):
            await db_module.init_db()
    finally:
        await db_module.close_db()
        settings_module._settings = previous_settings
        db_module._engine = previous_engine
        db_module._session_factory = previous_factory
