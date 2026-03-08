from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.schedules import get_schedule_history


@pytest.mark.asyncio
async def test_get_schedule_history_returns_items():
    session = AsyncMock()
    now = datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)
    item = SimpleNamespace(
        id="log-1",
        action="create",
        description="创建排班",
        user_id="user-1",
        username="manager",
        user_role="store_manager",
        created_at=now,
        changes={"shift_count": 6},
        new_value={"schedule_date": "2026-03-09"},
    )

    result = MagicMock()
    result.scalars.return_value.all.return_value = [item]
    session.execute = AsyncMock(return_value=result)

    rows = await get_schedule_history(
        schedule_id="schedule-1",
        limit=20,
        session=session,
        current_user=SimpleNamespace(id="u"),
    )

    assert len(rows) == 1
    assert rows[0].id == "log-1"
    assert rows[0].action == "create"
    assert rows[0].changes["shift_count"] == 6
