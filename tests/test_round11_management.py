from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_welcome_formats_all_documented_placeholders() -> None:
    from src.management import welcome_manager

    bot = SimpleNamespace(
        get_chat_member_count=AsyncMock(return_value=12),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=77)),
    )
    settings = AsyncMock(
        side_effect=[
            "on",
            "Welcome {name} {username} {group} #{count}\\n{rules}",
        ]
    )

    def discard_task(coro, *, name):
        coro.close()
        return MagicMock(name=name)

    with (
        patch.object(welcome_manager, "get_setting", settings),
        patch.object(welcome_manager, "get_rules", new=AsyncMock(return_value="Be kind")),
        patch.object(welcome_manager, "create_background_task", discard_task),
    ):
        await welcome_manager.send_welcome_message(
            bot,
            -100,
            42,
            "Alice",
            "alice",
            "Guardians",
        )

    sent_text = bot.send_message.await_args.kwargs["text"]
    assert "{name}" not in sent_text
    assert "Alice @alice Guardians #12" in sent_text
    assert "Be kind" in sent_text
    bot.get_chat_member_count.assert_awaited_once_with(-100)


@pytest.mark.asyncio
async def test_welcome_fails_safe_when_settings_store_is_unavailable() -> None:
    from src.management import welcome_manager

    bot = SimpleNamespace(send_message=AsyncMock())
    with patch.object(
        welcome_manager,
        "get_setting",
        new=AsyncMock(side_effect=RuntimeError("redis unavailable")),
    ):
        await welcome_manager.send_welcome_message(bot, -100, 42, "Alice", None, "Guardians")

    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_rules_ack_rejects_callback_from_another_chat() -> None:
    from src.handlers.callback_handler import handle_callback_query

    query = SimpleNamespace(
        data="rules_ack:-100",
        message=SimpleNamespace(chat_id=-200),
        from_user=SimpleNamespace(id=42),
        answer=AsyncMock(),
    )
    with patch("src.management.rules_manager.get_rules", new=AsyncMock()) as get_rules:
        await handle_callback_query(SimpleNamespace(callback_query=query), SimpleNamespace())

    query.answer.assert_awaited_once()
    assert query.answer.await_args.kwargs["show_alert"] is True
    get_rules.assert_not_awaited()


@pytest.mark.asyncio
async def test_show_rules_requires_source_chat_match() -> None:
    from src.handlers.callback_handler import handle_callback_query

    query = SimpleNamespace(
        data="show_rules:-100",
        message=SimpleNamespace(chat_id=-200),
        from_user=SimpleNamespace(id=42),
        answer=AsyncMock(),
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
    with patch("src.management.rules_manager.get_rules", new=AsyncMock()) as get_rules:
        await handle_callback_query(SimpleNamespace(callback_query=query), context)

    query.answer.assert_awaited_once()
    assert query.answer.await_args.kwargs["show_alert"] is True
    get_rules.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_skip_stops_current_stream_without_starting_second_loop() -> None:
    from src.features import voice_chat

    player = voice_chat.ChatPlayer(
        current=voice_chat.Track(title="Track", url="https://example.com/track"),
        playing=True,
    )
    voice_chat._players[100] = player
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=100),
        effective_message=message,
    )
    context = SimpleNamespace(bot=SimpleNamespace())

    with (
        patch.object(voice_chat, "_VOICE_READY", True),
        patch.object(voice_chat, "_leave_voice", new=AsyncMock(return_value=True)) as leave,
        patch.object(voice_chat, "create_background_task") as create_task,
    ):
        await voice_chat.cmd_skip(update, context)

    leave.assert_awaited_once_with(100)
    create_task.assert_not_called()
    assert player.skip_requested is True
    assert "تخطي" in message.reply_text.await_args.args[0]
    voice_chat._players.pop(100, None)


@pytest.mark.asyncio
async def test_admin_telegram_error_is_not_exposed_to_user() -> None:
    from telegram.error import TelegramError

    from src.handlers import admin_commands

    message = SimpleNamespace(
        text="/mute 42",
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_message=message,
        message=message,
        effective_chat=SimpleNamespace(id=-100, type="supergroup"),
        effective_user=SimpleNamespace(id=7),
    )
    context = SimpleNamespace(
        args=["42"],
        bot=SimpleNamespace(
            restrict_chat_member=AsyncMock(
                side_effect=TelegramError("secret Telegram response")
            )
        ),
    )
    with patch.object(admin_commands, "is_authorized_admin", new=AsyncMock(return_value=True)):
        await admin_commands.cmd_mute(update, context)

    text = message.reply_text.await_args.args[0]
    assert "secret Telegram response" not in text
    assert "تعذر تنفيذ العملية" in text
