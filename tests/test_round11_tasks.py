from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch


def test_batch_log_events_skips_duplicate_message_on_redelivery() -> None:
    from src.tasks import moderation_tasks

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class Session:
        def __init__(self):
            self.added = []
            self.execute = AsyncMock(side_effect=[Result(None), Result(123)])

        def add(self, event):
            self.added.append(event)

    session = Session()

    @asynccontextmanager
    async def fake_db_session():
        yield session

    event = {
        "group_id": -100,
        "user_id": 42,
        "message_id": 9001,
        "action_taken": "delete",
        "violation_category": "spam",
    }
    with patch("src.db.session.db_session", fake_db_session):
        result = moderation_tasks.batch_log_events.run([event, event])

    assert result == {"written": 1, "received": 2}
    assert len(session.added) == 1
    assert session.execute.await_count == 2
