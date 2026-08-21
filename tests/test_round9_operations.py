from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def _join_update() -> SimpleNamespace:
    user = SimpleNamespace(id=42, is_bot=False, username="new_user", first_name="New")
    member = SimpleNamespace(status="member", user=user)
    previous = SimpleNamespace(status="left")
    return SimpleNamespace(
        chat_member=SimpleNamespace(
            old_chat_member=previous,
            new_chat_member=member,
            chat=SimpleNamespace(id=-10042, title="Group"),
        ),
    )


@pytest.mark.asyncio
async def test_join_flow_fails_closed_when_captcha_state_is_unknown() -> None:
    from src.handlers import message_handler

    update = _join_update()
    context = SimpleNamespace(bot=SimpleNamespace())

    with (
        patch(
            "src.layers.account_intelligence._record_join",
            new_callable=AsyncMock,
        ),
        patch.object(message_handler, "check_raid", new_callable=AsyncMock, return_value=False),
        patch(
            "src.layers.captcha_gate.is_captcha_enabled",
            new_callable=AsyncMock,
            side_effect=RuntimeError("redis unavailable"),
        ),
        patch(
            "src.management.welcome_manager.send_welcome_message",
            new_callable=AsyncMock,
        ) as welcome,
    ):
        await message_handler.handle_new_member(update, context)

    welcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_join_flow_continues_after_raid_telemetry_failure() -> None:
    from src.handlers import message_handler

    update = _join_update()
    context = SimpleNamespace(bot=SimpleNamespace())

    with (
        patch(
            "src.layers.account_intelligence._record_join",
            new_callable=AsyncMock,
            side_effect=RuntimeError("telemetry unavailable"),
        ),
        patch.object(
            message_handler,
            "check_raid",
            new_callable=AsyncMock,
            side_effect=RuntimeError("raid probe unavailable"),
        ),
        patch(
            "src.layers.captcha_gate.is_captcha_enabled",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "src.management.welcome_manager.send_welcome_message",
            new_callable=AsyncMock,
        ) as welcome,
    ):
        await message_handler.handle_new_member(update, context)

    welcome.assert_awaited_once()


@pytest.mark.asyncio
async def test_captcha_keeps_challenge_when_permission_restore_fails() -> None:
    from telegram.error import TelegramError

    from src.layers import captcha_gate

    bot = SimpleNamespace(restrict_chat_member=AsyncMock(side_effect=TelegramError("forbidden")))
    with (
        patch.object(captcha_gate, "_get_stored_answer", new_callable=AsyncMock, return_value="7"),
        patch.object(captcha_gate, "_clear_challenge", new_callable=AsyncMock) as clear,
    ):
        result = await captcha_gate.handle_captcha_callback(bot, -10042, 42, "7")

    assert result is False
    clear.assert_not_awaited()


@pytest.mark.asyncio
async def test_captcha_restores_member_when_challenge_storage_fails() -> None:
    from src.layers import captcha_gate

    bot = SimpleNamespace(
        restrict_chat_member=AsyncMock(),
        send_message=AsyncMock(),
    )
    with patch.object(
        captcha_gate,
        "_store_challenge",
        new_callable=AsyncMock,
        side_effect=RuntimeError("redis unavailable"),
    ):
        await captcha_gate.send_captcha_challenge(bot, -10042, 42, "new_user")

    assert bot.restrict_chat_member.await_count == 2
    assert bot.send_message.await_count == 0
    restored_permissions = bot.restrict_chat_member.await_args_list[1].kwargs["permissions"]
    assert restored_permissions.can_send_messages is True


@pytest.mark.asyncio
async def test_captcha_callback_rejects_cross_chat_payload() -> None:
    from src.handlers.callback_handler import handle_callback_query

    query = SimpleNamespace(
        data="captcha:-2000:42:7",
        from_user=SimpleNamespace(id=42),
        message=SimpleNamespace(chat_id=-1001),
        answer=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(bot=SimpleNamespace())

    with patch(
        "src.layers.captcha_gate.handle_captcha_callback",
        new_callable=AsyncMock,
    ) as verify:
        await handle_callback_query(update, context)

    verify.assert_not_awaited()
    query.answer.assert_awaited_once_with("⛔ تحقق غير صالح لهذه المحادثة.", show_alert=True)


@pytest.mark.asyncio
async def test_escalation_requires_at_least_one_delivered_admin_message() -> None:
    from src.layers import action_execution

    ctx = SimpleNamespace(
        chat_id=-10042,
        user_id=42,
        user=SimpleNamespace(username="user"),
        risk=SimpleNamespace(total=80.0, explanation="test"),
    )
    bot = SimpleNamespace(send_message=AsyncMock())

    with patch.object(
        action_execution,
        "get_settings",
        return_value=SimpleNamespace(telegram_admin_ids=[]),
    ):
        delivered = await action_execution._escalate_to_admins(bot, ctx)

    assert delivered is False
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_raid_lockdown_propagates_primary_telegram_failure() -> None:
    from telegram.error import TelegramError

    from src.layers.action_execution import _activate_raid_lockdown

    bot = SimpleNamespace(
        set_chat_slow_mode_delay=AsyncMock(side_effect=TelegramError("forbidden")),
        send_message=AsyncMock(),
    )

    with pytest.raises(TelegramError):
        await _activate_raid_lockdown(bot, -10042)

    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_action_execution_marks_non_enforcement_states() -> None:
    from src.db.models import ActionType
    from src.layers import action_execution

    base = dict(
        user_id=42,
        chat_id=-10042,
        message_id=7,
        message=SimpleNamespace(),
        risk=SimpleNamespace(total=0.0, explanation=""),
        behavior=SimpleNamespace(warn_count=0),
        decision=SimpleNamespace(action=ActionType.ALLOW),
    )
    allow_ctx = SimpleNamespace(**base)
    silent_ctx = SimpleNamespace(
        **{**base, "decision": SimpleNamespace(action=ActionType.SILENT_LOG)}
    )

    with patch.object(action_execution, "get_redis", new_callable=AsyncMock):
        await action_execution.execute_action(allow_ctx, SimpleNamespace())
        await action_execution.execute_action(silent_ctx, SimpleNamespace())

    assert allow_ctx.execution_status == "not_required"
    assert silent_ctx.execution_status == "logged_only"


@pytest.mark.asyncio
async def test_captcha_auto_kick_task_is_cancelled_after_success() -> None:
    import asyncio

    from src.layers import captcha_gate

    bot = SimpleNamespace(
        restrict_chat_member=AsyncMock(),
        delete_message=AsyncMock(),
    )
    task = asyncio.create_task(asyncio.sleep(3600))
    captcha_gate._captcha_tasks[(-10042, 42)] = task

    with (
        patch.object(captcha_gate, "_get_stored_answer", new_callable=AsyncMock, return_value="7"),
        patch.object(captcha_gate, "_clear_challenge", new_callable=AsyncMock),
        patch.object(
            captcha_gate,
            "_get_captcha_message_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        assert await captcha_gate.handle_captcha_callback(bot, -10042, 42, "7") is True

    await asyncio.sleep(0)
    assert task.cancelled()
    assert (-10042, 42) not in captcha_gate._captcha_tasks


@pytest.mark.asyncio
async def test_support_reply_rejects_non_owner() -> None:
    from src.shop import support_engine

    ticket = SimpleNamespace(
        id=10,
        user_id=1,
        status=support_engine.TicketStatus.OPEN,
    )
    ticket_result = SimpleNamespace(scalar_one_or_none=lambda: ticket)
    sender_result = SimpleNamespace(
        scalar_one_or_none=lambda: SimpleNamespace(id=2),
    )
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[ticket_result, sender_result])
    session_context = AsyncMock()
    session_context.__aenter__.return_value = session

    with (
        patch.object(support_engine, "db_session", return_value=session_context),
        pytest.raises(PermissionError, match="لا تملك صلاحية"),
    ):
        await support_engine.reply_to_ticket("TKT-TEST", "محاولة", 999, is_admin=False)

    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_support_callback_rejects_invalid_ticket_reference() -> None:
    from src.shop.handlers.support_handler import handle_support_callback

    query = SimpleNamespace(
        data="support:view:bad-ref",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    context = SimpleNamespace(user_data={})

    await handle_support_callback(query, context)

    query.answer.assert_awaited_once_with("⛔ رقم تذكرة غير صالح.", show_alert=True)
    query.edit_message_text.assert_not_awaited()
    assert context.user_data == {}
