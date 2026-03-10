"""
Banquet Agent Phase 20 — 单元测试

覆盖端点：
  - get_task_list
  - complete_task
  - get_followup_schedule
  - log_followup_activity
  - get_push_history
  - batch_push
  - get_staff_assignments
  - assign_staff_to_order
"""
import pytest
from datetime import datetime, date, timedelta
from unittest.mock import AsyncMock, MagicMock


# ── helpers ─────────────────────────────────────────────────────────────────

def _mock_user():
    u = MagicMock()
    u.id       = "user-001"
    u.brand_id = "BRAND-001"
    return u


def _scalars_returning(items):
    r = MagicMock()
    r.scalars.return_value.first.return_value = items[0] if items else None
    r.scalars.return_value.all.return_value   = items
    return r


def _scalar_returning(value):
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _rows_returning(rows):
    r = MagicMock()
    r.all.return_value = rows
    return r


def _make_order(oid="O-001", store_id="S001", status="confirmed", days_ahead=5):
    from src.models.banquet import OrderStatusEnum, BanquetTypeEnum
    o = MagicMock()
    o.id           = oid
    o.store_id     = store_id
    o.order_status = OrderStatusEnum.CONFIRMED if status == "confirmed" else OrderStatusEnum.COMPLETED
    o.banquet_date = date.today() + timedelta(days=days_ahead)
    o.banquet_type = BanquetTypeEnum.WEDDING
    o.contact_name = "张三"
    o.contact_phone = "138-0000-0000"
    o.total_amount_fen = 500000
    o.paid_fen = 500000
    o.owner_user_id = None
    return o


def _make_task(tid="T-001", oid="O-001", status="pending", due_days=2,
               role="manager", owner_uid=None):
    from src.models.banquet import TaskStatusEnum, TaskOwnerRoleEnum
    t = MagicMock()
    t.id               = tid
    t.banquet_order_id = oid
    t.task_name        = "准备婚宴布置"
    t.task_type        = "decoration"
    t.owner_role       = TaskOwnerRoleEnum(role) if isinstance(role, str) else role
    t.owner_user_id    = owner_uid
    t.task_status      = (
        TaskStatusEnum.DONE    if status == "done"    else
        TaskStatusEnum.PENDING if status == "pending" else
        TaskStatusEnum.IN_PROGRESS
    )
    t.due_time    = datetime.utcnow() + timedelta(days=due_days)
    t.completed_at = None
    t.remark      = None
    return t


def _make_lead(lid="L-001", store_id="S001", stage="contacted",
               next_followup_days=2, budget_fen=200000):
    from src.models.banquet import LeadStageEnum, BanquetTypeEnum
    l = MagicMock()
    l.id               = lid
    l.store_id         = store_id
    l.banquet_type     = BanquetTypeEnum.WEDDING
    l.current_stage    = LeadStageEnum(stage)
    l.next_followup_at = datetime.utcnow() + timedelta(days=next_followup_days)
    l.last_followup_at = None
    l.expected_date    = date.today() + timedelta(days=60)
    l.expected_budget_fen = budget_fen
    l.source_channel   = "微信"
    l.converted_order_id = None
    return l


def _make_log(lid="LOG-001", action_type="daily_brief"):
    from src.models.banquet import BanquetAgentTypeEnum
    log = MagicMock()
    log.id                  = lid
    log.agent_type          = BanquetAgentTypeEnum.FOLLOWUP
    log.action_type         = action_type
    log.related_object_type = "store"
    log.related_object_id   = "S001"
    log.suggestion_text     = "今日宴会简报内容"
    log.is_human_approved   = True
    log.created_at          = datetime.utcnow()
    return log


# ── TestTaskList ─────────────────────────────────────────────────────────────

class TestTaskList:

    @pytest.mark.asyncio
    async def test_overdue_task_flagged(self):
        """due_time 已过、未完成 → is_overdue=True"""
        from src.api.banquet_agent import get_task_list
        from src.models.banquet import BanquetTypeEnum

        order = _make_order()
        task  = _make_task(status="pending", due_days=-2)   # past due

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_rows_returning([
            (task, order.banquet_date, BanquetTypeEnum.WEDDING, "张三")
        ]))

        result = await get_task_list(store_id="S001", db=db, _=_mock_user())

        assert result["total"] == 1
        assert result["tasks"][0]["is_overdue"] is True
        assert result["overdue_count"] == 1

    @pytest.mark.asyncio
    async def test_done_task_not_overdue(self):
        """已完成任务即使 due_time 已过 → is_overdue=False"""
        from src.api.banquet_agent import get_task_list
        from src.models.banquet import BanquetTypeEnum

        task = _make_task(status="done", due_days=-5)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_rows_returning([
            (task, date.today(), BanquetTypeEnum.WEDDING, "李四")
        ]))

        result = await get_task_list(store_id="S001", db=db, _=_mock_user())

        assert result["tasks"][0]["is_overdue"] is False


# ── TestCompleteTask ──────────────────────────────────────────────────────────

class TestCompleteTask:

    @pytest.mark.asyncio
    async def test_status_updated_to_done(self):
        """PATCH complete → task_status = done"""
        from src.api.banquet_agent import complete_task

        task = _make_task(status="pending")

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([task]))
        db.commit  = AsyncMock()

        result = await complete_task(
            store_id="S001", task_id="T-001",
            remark="完成布置", db=db, _=_mock_user()
        )

        assert result["status"] == "done"
        assert "completed_at" in result

    @pytest.mark.asyncio
    async def test_task_not_found_raises_404(self):
        """任务不存在 → 404"""
        from src.api.banquet_agent import complete_task
        from fastapi import HTTPException

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        with pytest.raises(HTTPException) as exc:
            await complete_task(
                store_id="S001", task_id="NOPE",
                remark="", db=db, _=_mock_user()
            )
        assert exc.value.status_code == 404


# ── TestFollowupSchedule ──────────────────────────────────────────────────────

class TestFollowupSchedule:

    @pytest.mark.asyncio
    async def test_upcoming_followups_returned(self):
        """next_followup_at 在未来7天内的线索被返回"""
        from src.api.banquet_agent import get_followup_schedule

        lead = _make_lead(next_followup_days=3)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_rows_returning([
            (lead, "王五", "139-0000-0001")
        ]))

        result = await get_followup_schedule(store_id="S001", days=7, db=db, _=_mock_user())

        assert result["total"] == 1
        assert result["items"][0]["customer_name"] == "王五"
        assert result["items"][0]["budget_yuan"] == pytest.approx(2000.0)

    @pytest.mark.asyncio
    async def test_empty_schedule_returns_zero(self):
        """无待跟进线索时返回空列表"""
        from src.api.banquet_agent import get_followup_schedule

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_rows_returning([]))

        result = await get_followup_schedule(store_id="S001", days=7, db=db, _=_mock_user())

        assert result["total"] == 0
        assert result["items"] == []


# ── TestLogFollowupActivity ───────────────────────────────────────────────────

class TestLogFollowupActivity:

    @pytest.mark.asyncio
    async def test_record_created_and_lead_updated(self):
        """记录跟进后 last_followup_at 更新，record_id 返回"""
        from src.api.banquet_agent import log_followup_activity

        lead = _make_lead()

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([lead]))
        db.add     = MagicMock()
        db.commit  = AsyncMock()

        result = await log_followup_activity(
            store_id="S001", lead_id="L-001",
            followup_type="call",
            content="与客户电话确认宴会日期",
            next_followup_at="",
            db=db, _=_mock_user()
        )

        db.add.assert_called_once()
        assert "record_id" in result
        assert result["followup_type"] == "call"

    @pytest.mark.asyncio
    async def test_lead_not_found_raises_404(self):
        """线索不存在 → 404"""
        from src.api.banquet_agent import log_followup_activity
        from fastapi import HTTPException

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        with pytest.raises(HTTPException) as exc:
            await log_followup_activity(
                store_id="S001", lead_id="NOPE",
                followup_type="call", content="test",
                next_followup_at="", db=db, _=_mock_user()
            )
        assert exc.value.status_code == 404


# ── TestBatchPush ─────────────────────────────────────────────────────────────

class TestBatchPush:

    @pytest.mark.asyncio
    async def test_logs_created_for_each_target(self):
        """批量推送写入 ActionLog，queued = len(target_ids)"""
        from src.api.banquet_agent import batch_push

        db = AsyncMock()
        db.add    = MagicMock()
        db.commit = AsyncMock()

        result = await batch_push(
            store_id="S001",
            push_type="reminder",
            message="您好，请记得确认宴会菜单！",
            target_ids=["C-001", "C-002", "C-003"],
            db=db, _=_mock_user()
        )

        assert result["queued"] == 3
        assert db.add.call_count == 3

    @pytest.mark.asyncio
    async def test_empty_target_ids_raises_400(self):
        """target_ids 为空 → 400"""
        from src.api.banquet_agent import batch_push
        from fastapi import HTTPException

        db = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await batch_push(
                store_id="S001",
                push_type="reminder",
                message="测试",
                target_ids=[],
                db=db, _=_mock_user()
            )
        assert exc.value.status_code == 400


# ── TestPushHistory ───────────────────────────────────────────────────────────

class TestPushHistory:

    @pytest.mark.asyncio
    async def test_returns_paged_items(self):
        """推送历史返回分页结果"""
        from src.api.banquet_agent import get_push_history

        log = _make_log(action_type="daily_brief")

        call_n = [0]
        def side_effect(*a, **kw):
            call_n[0] += 1
            n = call_n[0]
            if n == 1: return _scalar_returning(1)          # total count
            return _scalars_returning([log])                 # items

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=side_effect)

        result = await get_push_history(store_id="S001", page=1, page_size=20, db=db, _=_mock_user())

        assert result["total"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["action_type"] == "daily_brief"


# ── TestStaffAssignments ──────────────────────────────────────────────────────

class TestStaffAssignments:

    @pytest.mark.asyncio
    async def test_completion_pct_computed(self):
        """2 done / 4 total → 50%"""
        from src.api.banquet_agent import get_staff_assignments
        from src.models.banquet import TaskOwnerRoleEnum

        row = MagicMock()
        row.owner_role    = TaskOwnerRoleEnum.MANAGER
        row.owner_user_id = "user-001"
        row.task_count    = 4
        row.done_count    = 2

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_rows_returning([row]))

        result = await get_staff_assignments(store_id="S001", db=db, _=_mock_user())

        assert len(result["assignments"]) == 1
        a = result["assignments"][0]
        assert a["task_count"]    == 4
        assert a["done_count"]    == 2
        assert a["pending_count"] == 2
        assert a["completion_pct"] == pytest.approx(50.0)
