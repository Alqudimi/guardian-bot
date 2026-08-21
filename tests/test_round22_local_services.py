import asyncio


def test_celery_async_runner_reuses_open_loop_between_tasks() -> None:
    from src.tasks import moderation_tasks

    previous_loop = moderation_tasks._task_loop

    async def value(number: int) -> int:
        await asyncio.sleep(0)
        return number

    try:
        assert moderation_tasks._run_async(value(1)) == 1
        loop = moderation_tasks._task_loop
        assert loop is not None
        assert not loop.is_closed()
        assert moderation_tasks._run_async(value(2)) == 2
        assert moderation_tasks._task_loop is loop
    finally:
        current_loop = moderation_tasks._task_loop
        if current_loop is not previous_loop and current_loop is not None:
            current_loop.close()
        moderation_tasks._task_loop = previous_loop
