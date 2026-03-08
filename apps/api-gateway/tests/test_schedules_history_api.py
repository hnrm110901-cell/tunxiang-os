from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.schedules import get_schedule_history, router


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


@pytest.mark.asyncio
async def test_get_schedule_history_supports_action_keyword_and_order():
    session = AsyncMock()
    early = datetime(2026, 3, 8, 6, 0, tzinfo=timezone.utc)
    late = datetime(2026, 3, 8, 8, 0, tzinfo=timezone.utc)
    rows_raw = [
        SimpleNamespace(
            id="log-early",
            action="create",
            description="创建排班",
            user_id="u1",
            username="manager_a",
            user_role="store_manager",
            created_at=early,
            changes={},
            new_value={},
        ),
        SimpleNamespace(
            id="log-late",
            action="update",
            description="发布排班",
            user_id="u2",
            username="manager_b",
            user_role="store_manager",
            created_at=late,
            changes={"is_published": True},
            new_value={},
        ),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows_raw
    session.execute = AsyncMock(return_value=result)

    filtered = await get_schedule_history(
        schedule_id="schedule-1",
        limit=20,
        action="update",
        keyword="发布",
        order="asc",
        session=session,
        current_user=SimpleNamespace(id="u"),
    )
    assert len(filtered) == 1
    assert filtered[0].id == "log-late"

    ordered = await get_schedule_history(
        schedule_id="schedule-1",
        limit=20,
        order="asc",
        session=session,
        current_user=SimpleNamespace(id="u"),
    )
    assert len(ordered) == 2
    assert ordered[0].id == "log-early"


def test_week_view_route_is_registered():
    paths = {route.path for route in router.routes}
    assert "/schedules/week-view" in paths
