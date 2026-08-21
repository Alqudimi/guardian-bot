from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_game_menu_main_callback_returns_to_root_menu() -> None:
    from src.handlers.message_handler import handle_game_menu

    query = SimpleNamespace(
        data="game:menu:main",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query)

    await handle_game_menu(update, SimpleNamespace())

    query.edit_message_text.assert_awaited_once()
    assert "مركز ألعاب Guardian" in query.edit_message_text.await_args.args[0]
    assert "game:menu:local" in str(query.edit_message_text.await_args.kwargs["reply_markup"])


@pytest.mark.asyncio
async def test_runtime_probe_reports_dependency_failures_without_raising() -> None:
    from src.handlers import message_handler

    with (
        patch(
            "src.db.session.db_session",
            side_effect=RuntimeError("database unavailable"),
        ),
        patch(
            "src.utils.redis_client.get_redis",
            new_callable=AsyncMock,
            side_effect=RuntimeError("redis unavailable"),
        ),
    ):
        result = await message_handler._probe_runtime_dependencies()

    assert result == {"database": "unavailable", "redis": "unavailable"}


@pytest.mark.asyncio
async def test_pipeline_safe_records_failed_layer_name() -> None:
    from src.pipeline.orchestrator import _safe

    async def failing_layer(context) -> None:
        raise RuntimeError("layer failed")

    context = SimpleNamespace(layer_failures=[])
    await _safe(failing_layer, context, "link_analysis")

    assert context.layer_failures == ["link_analysis"]


@pytest.mark.asyncio
async def test_shop_recommendations_use_real_backend_and_render_services() -> None:
    from src.shop.handlers import shop_handler

    service = SimpleNamespace(id=7, title_ar="خدمة اختبار", base_price=12.5)
    query = SimpleNamespace(
        data="shop:recommendations",
        from_user=SimpleNamespace(id=42, username="user"),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query)
    shop_user = SimpleNamespace(id=99)
    current_service = {"price": 11.75}

    with (
        patch.object(shop_handler, "get_shop_user", new_callable=AsyncMock, return_value=shop_user),
        patch.object(
            shop_handler,
            "get_recommendations",
            new_callable=AsyncMock,
            return_value=[service],
        ) as get_recommendations,
        patch.object(
            shop_handler,
            "get_service",
            new_callable=AsyncMock,
            return_value=current_service,
        ) as get_service,
    ):
        await shop_handler.handle_shop_callback(update, SimpleNamespace())

    get_recommendations.assert_awaited_once_with(shop_user, limit=5)
    get_service.assert_awaited_once_with(7, user=shop_user)
    text = query.edit_message_text.await_args.args[0]
    markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    assert "مقترحة لك" in text
    assert markup.inline_keyboard[0][0].callback_data == "shop:service:7"
    assert "11.75" in markup.inline_keyboard[0][0].text


@pytest.mark.asyncio
async def test_shop_callback_rejects_malformed_service_id() -> None:
    from src.shop.handlers.shop_handler import handle_shop_callback

    query = SimpleNamespace(
        data="shop:service:not-an-id",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query)

    await handle_shop_callback(update, SimpleNamespace())

    assert query.answer.await_count == 2
    assert query.answer.await_args.kwargs == {"show_alert": True}
    query.edit_message_text.assert_not_awaited()
