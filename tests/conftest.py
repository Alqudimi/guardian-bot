"""Shared pytest cleanup for external resources used by integration tests."""

import pytest_asyncio

from src.utils.redis_client import close_redis


@pytest_asyncio.fixture(autouse=True)
async def close_shared_redis_after_test():
    yield
    await close_redis()
