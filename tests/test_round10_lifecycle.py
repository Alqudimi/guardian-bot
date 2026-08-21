from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from config.settings import get_settings


@pytest.mark.asyncio
async def test_background_task_registry_releases_completed_task() -> None:
    from src.utils import background_tasks

    async def work() -> str:
        await asyncio.sleep(0)
        return "done"

    task = background_tasks.create_background_task(work(), name="test-work")
    assert task in background_tasks._tasks
    assert await task == "done"
    await asyncio.sleep(0)
    assert task not in background_tasks._tasks


@pytest.mark.asyncio
async def test_background_task_registry_cancels_pending_tasks() -> None:
    from src.utils import background_tasks

    gate = asyncio.Event()

    async def work() -> None:
        await gate.wait()

    task = background_tasks.create_background_task(work(), name="test-cancel")
    await background_tasks.cancel_background_tasks()
    assert task.cancelled()
    assert not background_tasks._tasks


@pytest.mark.asyncio
async def test_smart_download_token_is_short_and_bound_to_chat_and_user() -> None:
    from src.features import smart_detect

    redis = SimpleNamespace(setex=AsyncMock(), getdel=AsyncMock(return_value="https://example.com/a/very-long-url"))
    with patch.object(smart_detect, "get_redis", new_callable=AsyncMock, return_value=redis):
        token = await smart_detect._create_download_token(100, 42, "https://example.com/a/very-long-url")
        url = await smart_detect._consume_download_token(100, 42, token)

    assert token
    assert len(f"smart_dl:yt:video:{token}") <= 64
    redis.setex.assert_awaited_once()
    prefix = get_settings().redis_prefix
    assert redis.setex.await_args.args[0].startswith(f"{prefix}smart_dl:100:42:")
    assert url == "https://example.com/a/very-long-url"
    redis.getdel.assert_awaited_once_with(f"{prefix}smart_dl:100:42:{token}")


@pytest.mark.asyncio
async def test_smart_offer_does_not_put_raw_url_in_callback_data() -> None:
    from src.features import smart_detect

    redis = SimpleNamespace(setex=AsyncMock())
    message = SimpleNamespace(
        chat=SimpleNamespace(id=100),
        from_user=SimpleNamespace(id=42),
        reply_text=AsyncMock(),
    )
    long_url = "https://www.youtube.com/watch?v=" + "x" * 160
    with patch.object(smart_detect, "get_redis", new_callable=AsyncMock, return_value=redis):
        await smart_detect._offer_download(message, long_url, "yt")

    markup = message.reply_text.await_args.kwargs["reply_markup"]
    callback_data = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert callback_data
    assert all(len(value.encode("utf-8")) <= 64 for value in callback_data)
    assert all(long_url not in value for value in callback_data)


@pytest.mark.asyncio
async def test_safe_fetch_validates_each_redirect_before_request() -> None:
    from src.security import ssrf_guard

    class Response:
        is_redirect = True
        is_permanent_redirect = False
        content = b""

        def __init__(self):
            self.headers = {"location": "http://127.0.0.1/admin"}

    class Client:
        def __init__(self, **kwargs):
            self.requests = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            self.requests.append(url)
            return Response()

    with (
        patch("httpx.AsyncClient", Client),
        patch.object(
            ssrf_guard,
            "validate_url",
            new=AsyncMock(side_effect=[(True, ""), (True, ""), (False, "blocked_ip")]),
        ) as validate,
    ):
        body, reason = await ssrf_guard.safe_fetch("https://example.com/start")

    assert body is None
    assert reason == "ssrf_redirect:blocked_ip"
    assert validate.await_count == 3


@pytest.mark.asyncio
async def test_link_expansion_validates_redirect_hop_before_following() -> None:
    from src.layers import link_analysis

    class Response:
        is_redirect = True
        is_permanent_redirect = False

        def __init__(self):
            self.headers = {"location": "http://127.0.0.1/admin"}

    class Client:
        def __init__(self, **kwargs):
            self.requests = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def head(self, url):
            self.requests.append(url)
            return Response()

    with (
        patch.object(link_analysis.httpx, "AsyncClient", Client),
        patch.object(
            link_analysis,
            "validate_url",
            new=AsyncMock(side_effect=[(True, ""), (True, ""), (False, "blocked_ip")]),
        ) as validate,
    ):
        final_url = await link_analysis._expand_url("https://example.com/start")

    assert final_url is None
    assert validate.await_count == 3
