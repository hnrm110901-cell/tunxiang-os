"""
1-on-1 面谈服务 — 单元测试
覆盖:
  1) 模板 topic_category 合法性
  2) 非法 role 查询
  3) 预约冲突检测
  4) 预约无冲突成功
  5) AI 总结容错(抛异常不中断 complete_meeting)
"""

import sys
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.services.one_on_one_service import OneOnOneService  # noqa: E402


def _mk_db():
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_template_invalid_category():
    svc = OneOnOneService(_mk_db())
    with pytest.raises(ValueError):
        await svc.create_template(name="T1", topic_category="unknown", questions=[])


@pytest.mark.asyncio
async def test_template_valid():
    svc = OneOnOneService(_mk_db())
    t = await svc.create_template(name="季度反馈", topic_category="performance", questions=[{"q": "亮点?"}])
    assert t.topic_category == "performance"


@pytest.mark.asyncio
async def test_list_my_meetings_invalid_role():
    svc = OneOnOneService(_mk_db())
    # execute 返回空，但我们先触发 role 校验
    with pytest.raises(ValueError):
        await svc.list_my_meetings(user_id="E1", role="badrole")


@pytest.mark.asyncio
async def test_schedule_meeting_conflict():
    db = _mk_db()

    # 模拟找到冲突
    class HasConflict:
        def first(self):
            return ("existing_meeting",)

    db.execute = AsyncMock(return_value=HasConflict())
    svc = OneOnOneService(db)
    with pytest.raises(ValueError, match="冲突"):
        await svc.schedule_meeting(
            initiator_id="M1",
            participant_id="E1",
            scheduled_at=datetime.utcnow() + timedelta(days=1),
        )


@pytest.mark.asyncio
async def test_schedule_meeting_no_conflict():
    db = _mk_db()

    class NoConflict:
        def first(self):
            return None

    db.execute = AsyncMock(return_value=NoConflict())
    svc = OneOnOneService(db)
    m = await svc.schedule_meeting(
        initiator_id="M1",
        participant_id="E1",
        scheduled_at=datetime.utcnow() + timedelta(days=1),
        duration_min=45,
        location="二楼会议室",
    )
    assert m.status == "scheduled"
    assert m.duration_min == 45


@pytest.mark.asyncio
async def test_complete_meeting_ai_failure_tolerated(monkeypatch):
    db = _mk_db()

    # mock _get_meeting 返回一个 in_progress 会议
    fake_meeting = MagicMock(
        id=uuid.uuid4(),
        status="in_progress",
        notes=None,
        action_items_json=None,
        ai_summary=None,
    )

    class GetResult:
        def scalar_one_or_none(self):
            return fake_meeting

    db.execute = AsyncMock(return_value=GetResult())

    svc = OneOnOneService(db)

    # 让 AI 总结服务抛异常 — 验证 complete_meeting 仍然成功
    import src.services.one_on_one_ai_service as ai_mod

    class BrokenAI:
        def __init__(self, db):
            pass

        async def summarize_meeting(self, meeting_id):
            raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(ai_mod, "OneOnOneAIService", BrokenAI)

    m = await svc.complete_meeting(
        meeting_id=fake_meeting.id,
        notes="员工反馈排班压力大",
        action_items=[{"item": "减少晚班", "owner": "E1", "due": "2026-05-01"}],
        auto_ai_summary=True,
    )
    assert m.status == "completed"
