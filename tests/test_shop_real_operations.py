from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_legacy_direct_deposit_path_is_rejected() -> None:
    from src.shop.wallet_engine import WalletError, deposit

    with pytest.raises(WalletError, match="Telegram Payments"):
        await deposit(telegram_id=42, amount=10)


@pytest.mark.asyncio
async def test_deposit_menu_does_not_claim_success_without_provider_token() -> None:
    from src.shop.handlers import wallet_handler

    query = SimpleNamespace(edit_message_text=AsyncMock())
    with patch.object(
        wallet_handler,
        "get_settings",
        return_value=SimpleNamespace(payment_provider_token=""),
    ):
        await wallet_handler._show_deposit_menu(query, SimpleNamespace())

    text = query.edit_message_text.await_args.args[0]
    assert "غير متاح" in text
    assert "لم يتم إضافة أي رصيد" in text


@pytest.mark.asyncio
async def test_invoice_path_creates_pending_intent_and_sends_real_invoice() -> None:
    from src.shop.handlers import wallet_handler

    bot = SimpleNamespace(send_invoice=AsyncMock())
    tx = SimpleNamespace(ref="DEP-ABC")
    with (
        patch.object(
            wallet_handler,
            "get_settings",
            return_value=SimpleNamespace(
                payment_provider_token="provider-token",
                payment_currency="USD",
            ),
        ),
        patch.object(
            wallet_handler,
            "create_deposit_intent",
            new_callable=AsyncMock,
            return_value=tx,
        ) as create_intent,
    ):
        result = await wallet_handler._send_deposit_invoice(bot, 100, 42, 25.0)

    assert result is tx
    create_intent.assert_awaited_once_with(
        telegram_id=42,
        amount=25.0,
        currency="USD",
        description="إيداع رصيد عبر Telegram Payments — 25.00 USD",
    )
    invoice = bot.send_invoice.await_args.kwargs
    assert invoice["payload"] == "wallet:DEP-ABC"
    assert invoice["provider_token"] == "provider-token"
    assert invoice["currency"] == "USD"
    assert invoice["prices"][0].amount == 2500


@pytest.mark.asyncio
async def test_precheckout_rejects_invalid_pending_intent() -> None:
    from src.shop.handlers import wallet_handler
    from src.shop.wallet_engine import WalletError

    query = SimpleNamespace(
        invoice_payload="wallet:DEP-ABC",
        from_user=SimpleNamespace(id=42),
        currency="USD",
        total_amount=2500,
        answer=AsyncMock(),
    )
    update = SimpleNamespace(pre_checkout_query=query)
    with patch.object(
        wallet_handler,
        "validate_deposit_payment",
        new_callable=AsyncMock,
        side_effect=WalletError("عملية الإيداع غير قابلة للتأكيد"),
    ):
        await wallet_handler.handle_pre_checkout_query(update, SimpleNamespace())

    query.answer.assert_awaited_once()
    assert query.answer.await_args.kwargs["ok"] is False


@pytest.mark.asyncio
async def test_successful_payment_confirms_balance_after_telegram_receipt() -> None:
    from src.shop.handlers import wallet_handler

    payment = SimpleNamespace(
        invoice_payload="wallet:DEP-ABC",
        currency="USD",
        total_amount=2500,
        telegram_payment_charge_id="telegram-charge",
        provider_payment_charge_id="provider-charge",
    )
    message = SimpleNamespace(
        successful_payment=payment,
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=42),
    )
    tx = SimpleNamespace(amount=25.0)
    with (
        patch.object(
            wallet_handler,
            "confirm_deposit_payment",
            new_callable=AsyncMock,
            return_value=tx,
        ) as confirm,
        patch.object(
            wallet_handler,
            "get_balance",
            new_callable=AsyncMock,
            return_value=(25.0, 0.0),
        ),
    ):
        await wallet_handler.handle_successful_payment(update, SimpleNamespace())

    confirm.assert_awaited_once_with(
        payload="wallet:DEP-ABC",
        telegram_id=42,
        currency="USD",
        total_amount_minor=2500,
        payment_charge_id="telegram-charge",
        provider_payment_charge_id="provider-charge",
    )
    assert "اعتماد الدفع" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_media_downloader_sends_through_bot_api(tmp_path) -> None:
    from src.features import media_downloader

    media_file = tmp_path / "track.mp3"
    media_file.write_bytes(b"real-test-media")
    status = SimpleNamespace(edit_text=AsyncMock(), delete=AsyncMock())
    message = SimpleNamespace(reply_text=AsyncMock(return_value=status))
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=100),
        effective_message=message,
    )
    bot = SimpleNamespace(send_audio=AsyncMock(), send_video=AsyncMock())

    async def fake_ytdlp(args):
        return 0, "", ""

    with (
        patch.object(media_downloader, "rate_limit_check", new_callable=AsyncMock, return_value=(True, "")),
        patch.object(media_downloader.tempfile, "mkdtemp", return_value=str(tmp_path)),
        patch.object(media_downloader, "_run_ytdlp", side_effect=fake_ytdlp),
    ):
        await media_downloader._download_and_send(
            update,
            "https://www.youtube.com/watch?v=real-test",
            audio_only=True,
            bot=bot,
        )

    bot.send_audio.assert_awaited_once()
    assert bot.send_audio.await_args.kwargs["chat_id"] == 100
    bot.send_video.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_play_fails_closed_without_real_backend() -> None:
    from src.features import voice_chat

    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=100),
        effective_message=message,
    )
    context = SimpleNamespace(args=["song"], bot=SimpleNamespace())

    with patch.object(voice_chat, "_VOICE_READY", False):
        await voice_chat.cmd_play(update, context)

    text = message.reply_text.await_args.args[0]
    assert "غير متاح" in text
    assert "قائمة وهمية" in text
