"""Lifecycle-safe registry for fire-and-forget asyncio tasks."""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

_tasks: set[asyncio.Task[Any]] = set()


def create_background_task(
    coroutine: Coroutine[Any, Any, Any],
    *,
    name: str,
) -> asyncio.Task[Any]:
    """Create a task that remains referenced and reports failures."""
    task = asyncio.create_task(coroutine, name=name)
    _tasks.add(task)

    def _finish(completed: asyncio.Task[Any]) -> None:
        _tasks.discard(completed)
        if completed.cancelled():
            return
        try:
            error = completed.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            logger.error(
                "background_task_failed",
                task_name=name,
                error=type(error).__name__,
            )

    task.add_done_callback(_finish)
    return task


async def cancel_background_tasks() -> None:
    """Cancel and await all registered tasks during graceful shutdown."""
    tasks = tuple(_tasks)
    if not tasks:
        return
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _tasks.difference_update(tasks)


__all__ = ["cancel_background_tasks", "create_background_task"]
