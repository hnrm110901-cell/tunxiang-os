"""
Banquet Agent Phase 3 — 单元测试

覆盖端点（API 层，不依赖真实 DB）：
  - get_order_detail      : 订单详情（tasks + payments）
  - list_order_tasks      : 订单任务列表
  - update_task_status    : 更新任务状态
  - generate_order_tasks  : 从模板生成任务
  - list_store_tasks      : 跨订单任务视图
  - list_lead_quotes      : 线索报价单列表
  - create_lead_quote     : 创建报价单
"""

import pytest
import uuid
from datetime import datetime, date
from unittest.mock import AsyncMock, MagicMock, patch


# ── helpers ────────────────────────────────────────────────────────────────────

def _mock_user():
    u = MagicMock()
    u.id = "user-001"
    return u


def _make_order(order_id="ORD-001", store_id="S001"):
    o = MagicMock()
    o.id = order_id
    o.store_id = store_id
    o.banquet_type.value = "wedding"
    o.banquet_date = date(2026, 9, 18)
    o.people_count = 200
    o.table_count = 20
    o.contact_name = "张三"
    o.contact_phone = "13800001111"
    o.order_status.value = "confirmed"
    o.deposit_status.value = "paid"
    o.total_amount_fen = 5000000
    o.paid_fen = 5000000
    o.remark = None
    o.tasks = []
    o.payments = []
    o.bookings = []
    o.customer = MagicMock()
    o.customer.name = "张三"
    o.customer.phone = "13800001111"
    return o


def _make_task(task_id="TASK-001", order_id="ORD-001", status="pending"):
    t = MagicMock()
    t.id = task_id
    t.banquet_order_id = order_id
    t.task_name = "备场检查"
    t.task_type = "preparation"
    t.owner_role.value = "manager"
    t.due_time = datetime(2026, 9, 17, 10, 0)
    t.task_status.value = status
    t.completed_at = None
    t.remark = None
    return t


def _make_lead(lead_id="LEAD-001", store_id="S001"):
    l = MagicMock()
    l.id = lead_id
    l.store_id = store_id
    return l


def _make_quote(quote_id="QUOTE-001", lead_id="LEAD-001"):
    q = MagicMock()
    q.id = quote_id
    q.lead_id = lead_id
    q.people_count = 200
    q.table_count = 20
    q.quoted_amount_fen = 5000000
    q.valid_until = date(2026, 4, 1)
    q.is_accepted = False
    q.package_id = None
    q.created_at = datetime(2026, 3, 9, 8, 0)
    return q


def _scalars_returning(items):
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = items[0] if items else None
    mock_result.scalars.return_value.all.return_value = items
    mock_result.first.return_value = items[0] if items else None
    mock_result.all.return_value = items
    return mock_result


def _scalar_first_returning(value):
    mock_result = MagicMock()
    mock_result.first.return_value = value
    return mock_result


# ── get_order_detail ───────────────────────────────────────────────────────────

class TestGetOrderDetail:

    @pytest.mark.asyncio
    async def test_returns_order_fields(self):
        from src.api.banquet_agent import get_order_detail

        order = _make_order()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([order]))

        result = await get_order_detail(
            store_id="S001", order_id="ORD-001",
            db=db, _=_mock_user(),
        )

        assert result["order_id"]          == "ORD-001"
        assert result["banquet_type"]      == "wedding"
        assert result["people_count"]      == 200
        assert result["total_amount_yuan"] == 50000.0
        assert result["paid_yuan"]         == 50000.0
        assert result["balance_yuan"]      == 0.0

    @pytest.mark.asyncio
    async def test_includes_tasks_and_payments(self):
        from src.api.banquet_agent import get_order_detail
        from src.models.banquet import TaskStatusEnum

        order = _make_order()
        task = _make_task()
        task.task_status = TaskStatusEnum.DONE   # real enum for equality check
        order.tasks = [task]
        order.payments = []

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([order]))

        result = await get_order_detail(
            store_id="S001", order_id="ORD-001",
            db=db, _=_mock_user(),
        )

        assert result["tasks_total"] == 1
        assert result["tasks_done"]  == 1
        assert len(result["tasks"])  == 1
        assert result["tasks"][0]["task_id"] == "TASK-001"

    @pytest.mark.asyncio
    async def test_404_when_order_not_found(self):
        from fastapi import HTTPException
        from src.api.banquet_agent import get_order_detail

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        with pytest.raises(HTTPException) as exc_info:
            await get_order_detail(
                store_id="S001", order_id="MISSING",
                db=db, _=_mock_user(),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_payment_records_formatted(self):
        from src.api.banquet_agent import get_order_detail

        order = _make_order()
        payment = MagicMock()
        payment.id = "PAY-001"
        payment.payment_type.value = "deposit"
        payment.amount_fen = 1000000
        payment.payment_method = "wechat"
        payment.paid_at = datetime(2026, 3, 1, 10, 0)
        payment.receipt_no = None
        order.payments = [payment]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([order]))

        result = await get_order_detail(
            store_id="S001", order_id="ORD-001",
            db=db, _=_mock_user(),
        )
        assert len(result["payments"]) == 1
        assert result["payments"][0]["amount_yuan"] == 10000.0
        assert result["payments"][0]["payment_type"] == "deposit"


# ── list_order_tasks ───────────────────────────────────────────────────────────

class TestListOrderTasks:

    @pytest.mark.asyncio
    async def test_returns_task_list(self):
        from src.api.banquet_agent import list_order_tasks

        task = _make_task()
        db = AsyncMock()
        # first execute: order verify, second: task list
        db.execute = AsyncMock(side_effect=[
            _scalar_first_returning(MagicMock()),   # order exists
            _scalars_returning([task]),              # tasks
        ])

        result = await list_order_tasks(
            store_id="S001", order_id="ORD-001",
            db=db, _=_mock_user(),
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["task_id"] == "TASK-001"

    @pytest.mark.asyncio
    async def test_404_when_order_missing(self):
        from fastapi import HTTPException
        from src.api.banquet_agent import list_order_tasks

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_first_returning(None))

        with pytest.raises(HTTPException) as exc_info:
            await list_order_tasks(
                store_id="S001", order_id="MISSING",
                db=db, _=_mock_user(),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_list_when_no_tasks(self):
        from src.api.banquet_agent import list_order_tasks

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_first_returning(MagicMock()),
            _scalars_returning([]),
        ])

        result = await list_order_tasks(
            store_id="S001", order_id="ORD-001",
            db=db, _=_mock_user(),
        )
        assert result == []


# ── update_task_status ─────────────────────────────────────────────────────────

class TestUpdateTaskStatus:

    @pytest.mark.asyncio
    async def test_mark_done_sets_completed_at(self):
        from src.api.banquet_agent import update_task_status, TaskUpdateReq
        from src.models.banquet import TaskStatusEnum

        task = _make_task()
        task.task_status = TaskStatusEnum.PENDING
        task.completed_at = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([task]))

        result = await update_task_status(
            store_id="S001", order_id="ORD-001", task_id="TASK-001",
            body=TaskUpdateReq(status=TaskStatusEnum.DONE),
            db=db, _=_mock_user(),
        )
        assert result["task_id"] == "TASK-001"
        assert task.completed_at is not None

    @pytest.mark.asyncio
    async def test_reopen_clears_completed_at(self):
        from src.api.banquet_agent import update_task_status, TaskUpdateReq
        from src.models.banquet import TaskStatusEnum

        task = _make_task(status="done")
        task.task_status = TaskStatusEnum.DONE
        task.completed_at = datetime(2026, 9, 17, 10, 0)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([task]))

        await update_task_status(
            store_id="S001", order_id="ORD-001", task_id="TASK-001",
            body=TaskUpdateReq(status=TaskStatusEnum.PENDING),
            db=db, _=_mock_user(),
        )
        assert task.completed_at is None

    @pytest.mark.asyncio
    async def test_404_when_task_not_found(self):
        from fastapi import HTTPException
        from src.api.banquet_agent import update_task_status, TaskUpdateReq
        from src.models.banquet import TaskStatusEnum

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        with pytest.raises(HTTPException) as exc_info:
            await update_task_status(
                store_id="S001", order_id="ORD-001", task_id="MISSING",
                body=TaskUpdateReq(status=TaskStatusEnum.DONE),
                db=db, _=_mock_user(),
            )
        assert exc_info.value.status_code == 404


# ── generate_order_tasks ───────────────────────────────────────────────────────

class TestGenerateOrderTasks:

    @pytest.mark.asyncio
    async def test_calls_execution_agent(self):
        from src.api.banquet_agent import generate_order_tasks

        order = _make_order()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([order]))

        with patch("src.api.banquet_agent._execution") as mock_exec:
            mock_exec.generate_tasks_for_order = AsyncMock(return_value=[MagicMock(), MagicMock()])
            result = await generate_order_tasks(
                store_id="S001", order_id="ORD-001",
                db=db, _=_mock_user(),
            )

        assert result["tasks_generated"] == 2

    @pytest.mark.asyncio
    async def test_404_when_order_missing(self):
        from fastapi import HTTPException
        from src.api.banquet_agent import generate_order_tasks

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        with pytest.raises(HTTPException) as exc_info:
            await generate_order_tasks(
                store_id="S001", order_id="MISSING",
                db=db, _=_mock_user(),
            )
        assert exc_info.value.status_code == 404


# ── list_store_tasks ───────────────────────────────────────────────────────────

class TestListStoreTasks:

    @pytest.mark.asyncio
    async def test_returns_tasks_with_order_info(self):
        from src.api.banquet_agent import list_store_tasks

        task = _make_task()
        banquet_date = date(2026, 9, 18)
        banquet_type = MagicMock()
        banquet_type.value = "wedding"

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(task, banquet_date, banquet_type)]
        db.execute = AsyncMock(return_value=mock_result)

        result = await list_store_tasks(
            store_id="S001",
            status=None, owner_role=None, due_date=None,
            db=db, _=_mock_user(),
        )
        assert len(result) == 1
        assert result[0]["task_id"]     == "TASK-001"
        assert result[0]["order_id"]    == "ORD-001"
        assert result[0]["banquet_date"] == "2026-09-18"
        assert result[0]["banquet_type"] == "wedding"

    @pytest.mark.asyncio
    async def test_invalid_status_ignored(self):
        from src.api.banquet_agent import list_store_tasks

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        # should not raise — invalid status silently ignored
        result = await list_store_tasks(
            store_id="S001",
            status="not_a_real_status", owner_role=None, due_date=None,
            db=db, _=_mock_user(),
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty_list(self):
        from src.api.banquet_agent import list_store_tasks

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        result = await list_store_tasks(
            store_id="S999",
            status=None, owner_role=None, due_date=None,
            db=db, _=_mock_user(),
        )
        assert result == []


# ── list_lead_quotes ───────────────────────────────────────────────────────────

class TestListLeadQuotes:

    @pytest.mark.asyncio
    async def test_returns_quote_list(self):
        from src.api.banquet_agent import list_lead_quotes

        quote = _make_quote()
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_first_returning(MagicMock()),  # lead exists
            _scalars_returning([quote]),            # quotes
        ])

        result = await list_lead_quotes(
            store_id="S001", lead_id="LEAD-001",
            db=db, _=_mock_user(),
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["quote_id"]           == "QUOTE-001"
        assert result[0]["quoted_amount_yuan"]  == 50000.0

    @pytest.mark.asyncio
    async def test_404_when_lead_missing(self):
        from fastapi import HTTPException
        from src.api.banquet_agent import list_lead_quotes

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_first_returning(None))

        with pytest.raises(HTTPException) as exc_info:
            await list_lead_quotes(
                store_id="S001", lead_id="MISSING",
                db=db, _=_mock_user(),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_quotes_returns_empty_list(self):
        from src.api.banquet_agent import list_lead_quotes

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_first_returning(MagicMock()),
            _scalars_returning([]),
        ])

        result = await list_lead_quotes(
            store_id="S001", lead_id="LEAD-001",
            db=db, _=_mock_user(),
        )
        assert result == []


# ── create_lead_quote ──────────────────────────────────────────────────────────

class TestCreateLeadQuote:

    @pytest.mark.asyncio
    async def test_creates_quote_and_returns_id(self):
        from src.api.banquet_agent import create_lead_quote, QuoteCreateReq

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_first_returning(MagicMock()))
        db.add = MagicMock()
        db.commit = AsyncMock()

        result = await create_lead_quote(
            store_id="S001", lead_id="LEAD-001",
            body=QuoteCreateReq(
                people_count=200,
                table_count=20,
                quoted_amount_yuan=50000.0,
                valid_days=7,
            ),
            db=db,
            current_user=_mock_user(),
        )
        assert "quote_id" in result
        assert result["quoted_amount_yuan"] == 50000.0
        assert "valid_until" in result
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_404_when_lead_missing(self):
        from fastapi import HTTPException
        from src.api.banquet_agent import create_lead_quote, QuoteCreateReq

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_first_returning(None))

        with pytest.raises(HTTPException) as exc_info:
            await create_lead_quote(
                store_id="S001", lead_id="MISSING",
                body=QuoteCreateReq(
                    people_count=100, table_count=10,
                    quoted_amount_yuan=30000.0,
                ),
                db=db,
                current_user=_mock_user(),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_valid_until_respects_valid_days(self):
        from src.api.banquet_agent import create_lead_quote, QuoteCreateReq
        from datetime import date, timedelta

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_first_returning(MagicMock()))
        db.add = MagicMock()
        db.commit = AsyncMock()

        result = await create_lead_quote(
            store_id="S001", lead_id="LEAD-001",
            body=QuoteCreateReq(
                people_count=100, table_count=10,
                quoted_amount_yuan=30000.0,
                valid_days=14,
            ),
            db=db,
            current_user=_mock_user(),
        )
        expected_until = (date.today() + timedelta(days=14)).isoformat()
        assert result["valid_until"] == expected_until
