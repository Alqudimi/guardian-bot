from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_game_callback_rejects_payload_from_another_chat() -> None:
    from src.handlers.message_handler import handle_game_callback

    query = SimpleNamespace(
        data="game:mafia:vote:42:-200",
        message=SimpleNamespace(chat_id=-100),
        answer=AsyncMock(),
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=-100, type="supergroup"),
    )

    with patch(
        "src.handlers.message_handler.GameSessionManager.get_session",
        new=AsyncMock(),
    ) as get_session:
        await handle_game_callback(update, SimpleNamespace())

    query.answer.assert_awaited_once_with(
        "This game action belongs to another chat", show_alert=True
    )
    get_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_game_callback_uses_current_chat_for_valid_payload() -> None:
    from src.handlers.message_handler import handle_game_callback

    game = SimpleNamespace(
        status="running",
        handle_callback=AsyncMock(),
    )
    query = SimpleNamespace(
        data="game:mafia:vote:42:-100",
        message=SimpleNamespace(chat_id=-100),
        answer=AsyncMock(),
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=-100, type="supergroup"),
        effective_user=SimpleNamespace(id=42),
    )

    with patch(
        "src.handlers.message_handler.GameSessionManager.get_session",
        new=AsyncMock(return_value=game),
    ) as get_session, patch(
        "src.handlers.message_handler.GameSessionManager.update_session",
        new=AsyncMock(),
    ) as update_session:
        await handle_game_callback(update, SimpleNamespace())

    get_session.assert_awaited_once_with(-100, "mafia")
    game.handle_callback.assert_awaited_once()
    update_session.assert_awaited_once_with(game)


@pytest.mark.asyncio
async def test_hourly_ban_cap_records_downgraded_mute_action() -> None:
    from src.db.models import ActionType
    from src.layers import action_execution

    ctx = SimpleNamespace(
        user_id=42,
        chat_id=-100,
        message_id=7,
        risk=SimpleNamespace(total=90.0, explanation="high risk"),
        behavior=SimpleNamespace(warn_count=0),
        decision=SimpleNamespace(
            action=ActionType.BAN_PERM,
            mute_duration_seconds=0,
            ban_duration_seconds=0,
            notify_admin=False,
        ),
    )
    redis = SimpleNamespace()

    with (
        patch.object(action_execution, "get_redis", new=AsyncMock(return_value=redis)),
        patch.object(action_execution, "is_safe_mode", new=AsyncMock(return_value=False)),
        patch.object(action_execution, "can_act", new=AsyncMock(return_value=(True, ""))),
        patch.object(action_execution, "_can_execute_action", new=AsyncMock(return_value=(True, ""))),
        patch.object(action_execution, "_hourly_ban_limit_reached", new=AsyncMock(return_value=True)),
        patch.object(action_execution, "_reserve_delete_slot", new=AsyncMock(return_value=True)),
        patch.object(action_execution, "compute_action_delay", new=AsyncMock(return_value=0)),
        patch.object(action_execution, "_delete_message", new=AsyncMock()),
        patch.object(action_execution, "_mute_user", new=AsyncMock()) as mute,
        patch.object(action_execution, "_record_action_taken", new=AsyncMock()),
        patch("src.security.human_behavior.record_action_completed", new=AsyncMock()),
        patch.object(action_execution, "record_success", new=AsyncMock()),
        patch.object(action_execution, "record_action_result", new=AsyncMock()),
    ):
        await action_execution.execute_action(ctx, SimpleNamespace())

    assert ctx.decision.action == ActionType.MUTE_TEMP
    assert ctx.execution_status == "succeeded"
    assert mute.await_count == 1
    assert mute.await_args.args[1:] == (-100, 42, 3600)


@pytest.mark.asyncio
async def test_light_moderation_level_reduces_punitive_action() -> None:
    from src.db.models import ActionType
    from src.layers.decision_engine import run_decision_engine
    from tests.test_decision_engine import _make_ctx

    ctx = _make_ctx(risk_total=68.0)
    with patch(
        "src.intelligence.adaptive_thresholds.get_group_thresholds",
        new=AsyncMock(return_value=SimpleNamespace(moderation_level="light")),
    ):
        await run_decision_engine(ctx)

    assert ctx.decision.action == ActionType.WARN


@pytest.mark.asyncio
async def test_strict_moderation_level_escalates_decision_ladder() -> None:
    from src.db.models import ActionType
    from src.layers.decision_engine import run_decision_engine
    from tests.test_decision_engine import _make_ctx

    ctx = _make_ctx(risk_total=68.0)
    with patch(
        "src.intelligence.adaptive_thresholds.get_group_thresholds",
        new=AsyncMock(return_value=SimpleNamespace(moderation_level="strict")),
    ):
        await run_decision_engine(ctx)

    assert ctx.decision.action == ActionType.BAN_TEMP


@pytest.mark.asyncio
async def test_group_pattern_round_trip_and_fast_rule_hit() -> None:
    from src.layers import fast_rules
    from src.management import group_patterns
    from src.utils.redis_client import get_redis

    chat_id = -100987654321
    redis = await get_redis()
    await redis.delete(f"group_patterns:{chat_id}", f"group_patterns:{chat_id}:compiled")

    item = await group_patterns.add_group_pattern(
        chat_id, "literal", "abuse", "bad-word"
    )
    assert item.pattern_id
    listed = await group_patterns.list_group_patterns(chat_id)
    assert [pattern.pattern for pattern in listed] == ["bad-word"]

    normalized = SimpleNamespace(
        clean_text="this contains bad-word",
        mention_count=0,
        urls=[],
        is_invite_link=False,
        has_invite_link=False,
        is_forwarded=False,
        has_media=False,
        fingerprint="fp-round12",
        media_type=None,
        zalgo_detected=False,
    )
    ctx = SimpleNamespace(
        normalized=normalized,
        user_id=42,
        chat_id=chat_id,
        spam=SimpleNamespace(
            whitelist_hit=False,
            blacklist_hit=False,
            fast_rule_block=False,
            link_spam=False,
            mention_spam=False,
            forwarded_spam=False,
            media_spam=False,
            flood_score=0.0,
        ),
        decision=SimpleNamespace(action=None, reason=""),
        short_circuit=False,
    )
    with (
        patch.object(fast_rules, "_check_whitelist", new=AsyncMock(return_value=False)),
        patch.object(fast_rules, "_check_blacklist", new=AsyncMock(return_value=False)),
        patch.object(fast_rules, "_check_global_blacklist", new=AsyncMock(return_value=False)),
        patch.object(fast_rules, "get_setting", new=AsyncMock(return_value="5")),
        patch.object(fast_rules, "_load_db_patterns", new=AsyncMock(return_value=[])),
    ):
        await fast_rules.run_fast_rules(ctx)

    assert ctx.short_circuit is True
    assert ctx.decision.action == "delete"
    assert ctx.decision.reason == "group_pattern:abuse"
    assert await group_patterns.remove_group_pattern(chat_id, item.pattern_id) is True


@pytest.mark.asyncio
async def test_setmoderation_is_admin_only_and_invalid_values_are_rejected() -> None:
    from src.handlers import admin_commands

    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        message=message,
        effective_message=message,
        effective_chat=SimpleNamespace(id=-100, type="supergroup"),
        effective_user=SimpleNamespace(id=7),
    )
    context = SimpleNamespace(args=["invalid"], bot=SimpleNamespace())
    with patch.object(admin_commands, "is_authorized_admin", new=AsyncMock(return_value=True)):
        await admin_commands.cmd_setmoderation(update, context)
    assert "light|moderate|strict" in message.reply_text.await_args.args[0]

    message.reply_text.reset_mock()
    context.args = ["strict"]
    with (
        patch.object(admin_commands, "is_authorized_admin", new=AsyncMock(return_value=True)),
        patch.object(admin_commands, "set_setting", new=AsyncMock()) as set_setting,
        patch(
            "src.intelligence.adaptive_thresholds.invalidate_group_thresholds",
            new=AsyncMock(),
        ) as invalidate,
    ):
        await admin_commands.cmd_setmoderation(update, context)

    set_setting.assert_awaited_once_with(-100, "moderation_level", "strict")
    invalidate.assert_awaited_once_with(-100)
    assert "strict" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_setlimits_validates_and_persists_group_limits() -> None:
    from src.handlers import admin_commands

    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        message=message,
        effective_message=message,
        effective_chat=SimpleNamespace(id=-100, type="supergroup"),
        effective_user=SimpleNamespace(id=7),
    )
    context = SimpleNamespace(args=["0", "60"], bot=SimpleNamespace())
    with patch.object(admin_commands, "is_authorized_admin", new=AsyncMock(return_value=True)):
        await admin_commands.cmd_setlimits(update, context)
    assert "1 to 50" in message.reply_text.await_args.args[0]

    message.reply_text.reset_mock()
    context.args = ["3", "8"]
    with (
        patch.object(admin_commands, "is_authorized_admin", new=AsyncMock(return_value=True)),
        patch.object(admin_commands, "set_setting", new=AsyncMock()) as set_setting,
    ):
        await admin_commands.cmd_setlimits(update, context)

    assert set_setting.await_args_list[0].args == (-100, "max_links", "3")
    assert set_setting.await_args_list[1].args == (-100, "max_mentions", "8")
    assert "links=`3`" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_admin_command_wrapper_writes_audit_event_without_arguments() -> None:
    from src.handlers import admin_commands

    message = SimpleNamespace(reply_text=AsyncMock())
    bot = SimpleNamespace()
    update = SimpleNamespace(
        message=message,
        effective_message=message,
        effective_chat=SimpleNamespace(id=-100, type="supergroup"),
        effective_user=SimpleNamespace(id=7),
    )
    context = SimpleNamespace(args=["invalid", "secret-value"], bot=bot)
    with (
        patch.object(admin_commands, "is_authorized_admin", new=AsyncMock(return_value=True)),
        patch.object(admin_commands, "log_admin_command", new=AsyncMock()) as audit,
    ):
        await admin_commands.cmd_setmoderation(update, context)

    audit.assert_awaited_once_with(bot, -100, 7, "cmd_setmoderation")
    assert "secret-value" not in audit.await_args.args
