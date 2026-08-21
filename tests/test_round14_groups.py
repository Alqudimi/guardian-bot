from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import get_settings
from src.pipeline.context import Decision, SpamSignals


@pytest.mark.asyncio
async def test_media_only_message_has_no_text_duplicate_fingerprint() -> None:
    from src.layers.normalization import run_normalization

    message = SimpleNamespace(
        text=None,
        caption=None,
        parse_entities=lambda *_args: [],
        forward_origin=None,
        forward_from=None,
        forward_from_chat=None,
        photo=[object()],
        video=None,
        document=None,
        animation=None,
        sticker=None,
        audio=None,
        voice=None,
        video_note=None,
    )
    ctx = SimpleNamespace(
        message=message,
        user_id=42,
        chat_id=-10014,
        spam=SpamSignals(),
    )

    await run_normalization(ctx)

    assert ctx.normalized.fingerprint == ""
    assert ctx.normalized.has_media is True


@pytest.mark.asyncio
async def test_exact_duplicate_key_is_scoped_to_user() -> None:
    from src.layers import flood_detection

    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[0, 0, 1, None])
    redis = MagicMock()
    redis.pipeline.return_value = pipe
    redis.set = AsyncMock(return_value=True)
    redis.sadd = AsyncMock()
    redis.scard = AsyncMock(return_value=1)
    redis.expire = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])

    ctx = SimpleNamespace(
        user_id=42,
        chat_id=-10014,
        short_circuit=False,
        normalized=SimpleNamespace(
            fingerprint="fp",
            clean_text="hello everyone",
            has_media=False,
        ),
        spam=SpamSignals(),
    )
    thresholds = SimpleNamespace(
        flood_max_messages=100,
        flood_window_seconds=60,
        attack_mode=False,
    )

    with (
        patch.object(flood_detection, "get_redis", new=AsyncMock(return_value=redis)),
        patch(
            "src.intelligence.adaptive_thresholds.get_group_thresholds",
            new=AsyncMock(return_value=thresholds),
        ),
    ):
        await flood_detection.run_flood_detection(ctx)

    prefix = get_settings().redis_prefix
    assert redis.set.await_args.args == (
        f"{prefix}dup:-10014:42:fp",
        "1",
    )
    assert redis.set.await_args.kwargs == {
        "ex": get_settings().duplicate_window_seconds,
        "nx": True,
    }


@pytest.mark.asyncio
async def test_high_confidence_fast_rule_cannot_be_overridden_by_later_layers() -> None:
    from src.layers import fast_rules

    ctx = SimpleNamespace(
        user_id=42,
        chat_id=-10014,
        normalized=SimpleNamespace(
            clean_text="free btc guaranteed profit now",
            mention_count=0,
            urls=[],
            has_invite_link=False,
            is_forwarded=False,
            has_media=False,
            zalgo_detected=False,
        ),
        spam=SpamSignals(),
        decision=Decision(),
        short_circuit=False,
    )

    with (
        patch.object(fast_rules, "_check_whitelist", new=AsyncMock(return_value=False)),
        patch.object(fast_rules, "_check_blacklist", new=AsyncMock(return_value=False)),
        patch.object(fast_rules, "_check_global_blacklist", new=AsyncMock(return_value=False)),
        patch.object(fast_rules, "get_setting", new=AsyncMock(return_value="5")),
        patch.object(fast_rules, "load_compiled_group_patterns", new=AsyncMock(return_value=[])),
        patch.object(fast_rules, "_load_db_patterns", new=AsyncMock(return_value=[])),
    ):
        await fast_rules.run_fast_rules(ctx)

    assert ctx.short_circuit is True
    assert ctx.spam.fast_rule_block is True
    assert ctx.decision.action == "delete"
    assert ctx.decision.reason == "crypto_scam_pattern"


@pytest.mark.asyncio
async def test_account_id_does_not_create_new_account_risk() -> None:
    from src.layers import account_intelligence

    redis = SimpleNamespace(
        get=AsyncMock(return_value=None),
        zremrangebyscore=AsyncMock(),
        zcard=AsyncMock(return_value=0),
    )
    ctx = SimpleNamespace(
        user_id=8_000_000_000,
        chat_id=-10014,
        user=SimpleNamespace(
            username=None,
            first_name="Member",
            last_name=None,
        ),
    )

    with patch.object(account_intelligence, "get_redis", new=AsyncMock(return_value=redis)):
        signals = await account_intelligence.analyze_account(ctx)

    assert signals.high_id_new_account is False
    assert signals.account_risk_score == 0.0
    assert "new_account:very_new" not in signals.risk_reasons


@pytest.mark.asyncio
async def test_group_admin_commands_reject_private_chat() -> None:
    from src.handlers import admin_commands, message_handler

    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        message=message,
        effective_message=message,
        effective_chat=SimpleNamespace(id=12345, type="private"),
        effective_user=SimpleNamespace(id=7),
    )
    context = SimpleNamespace(args=["off"], bot=SimpleNamespace())

    with patch.object(admin_commands, "is_authorized_admin", new=AsyncMock()) as auth:
        await admin_commands.cmd_setsmart(update, context)
    auth.assert_not_awaited()
    assert "Group-only" in message.reply_text.await_args.args[0]

    message.reply_text.reset_mock()
    with patch.object(message_handler, "is_authorized_admin", new=AsyncMock()) as auth:
        assert await message_handler._require_group_admin(update, context) is False
    auth.assert_not_awaited()
    assert "Group-only" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_language_policy_writes_canonical_group_setting_and_clears_legacy() -> None:
    from src.layers import language_guard

    redis = SimpleNamespace(delete=AsyncMock())
    with (
        patch.object(language_guard, "get_redis", new=AsyncMock(return_value=redis)),
        patch(
            "src.management.group_settings.set_setting",
            new=AsyncMock(),
        ) as set_setting,
    ):
        await language_guard.set_group_language_policy(-10014, "ar")

    set_setting.assert_awaited_once_with(-10014, "lang_policy", "ar")
    redis.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_legacy_language_policy_is_migrated_on_read() -> None:
    from src.layers import language_guard

    redis = SimpleNamespace(
        get=AsyncMock(return_value=b"ru"),
        delete=AsyncMock(),
    )
    with (
        patch.object(language_guard, "get_redis", new=AsyncMock(return_value=redis)),
        patch(
            "src.management.group_settings.set_setting",
            new=AsyncMock(),
        ) as set_setting,
    ):
        policy = await language_guard.get_group_language_policy(-10014)

    assert policy == "ru"
    set_setting.assert_awaited_once_with(-10014, "lang_policy", "ru")
    redis.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_language_policy_violation_is_a_non_overridable_delete() -> None:
    from src.layers import language_guard

    ctx = SimpleNamespace(
        chat_id=-10014,
        user_id=42,
        short_circuit=False,
        normalized=SimpleNamespace(
            clean_text="this is a sufficiently long English message",
        ),
        decision=Decision(),
    )
    with patch.object(
        language_guard,
        "get_group_language_policy",
        new=AsyncMock(return_value="ar"),
    ):
        await language_guard.run_language_guard(ctx)

    assert ctx.short_circuit is True
    assert ctx.decision.action == "delete"
    assert "language_policy:ar" in ctx.decision.reason


@pytest.mark.asyncio
async def test_high_confidence_evasion_attack_is_non_overridable() -> None:
    from src.layers import evasion_detection

    ctx = SimpleNamespace(
        chat_id=-10014,
        user_id=42,
        short_circuit=False,
        normalized=SimpleNamespace(
            original_text="safe\u202etext",
            clean_text="safetext",
            urls=[],
        ),
        spam=SpamSignals(),
        decision=Decision(),
    )

    await evasion_detection.run_evasion_detection(ctx)

    assert ctx.short_circuit is True
    assert ctx.spam.fast_rule_block is True
    assert ctx.decision.action == "delete"


@pytest.mark.asyncio
async def test_user_profile_uses_canonical_trust_and_does_not_claim_account_age() -> None:
    from src.management import user_info

    redis = SimpleNamespace(
        hget=AsyncMock(return_value=b"72"),
        get=AsyncMock(return_value=b"11"),
    )
    warn_status = SimpleNamespace(active_warn_count=1, total_warn_count=2)
    threat = SimpleNamespace(
        threat_level=0,
        ban_count=0,
        source_groups=[],
        violation_types=[],
    )

    with (
        patch.object(user_info, "get_redis", new=AsyncMock(return_value=redis)),
        patch.object(user_info, "get_warn_status", new=AsyncMock(return_value=warn_status)),
        patch.object(user_info, "get_user_threat", new=AsyncMock(return_value=threat)),
    ):
        profile = await user_info.get_user_profile(42, -10014)

    assert profile.trust_score == 72.0
    assert profile.message_count_30d == 11
    assert profile.account_age_category == "unavailable_via_bot_api"
    assert "unavailable via Bot API" in user_info.format_user_report(profile)
