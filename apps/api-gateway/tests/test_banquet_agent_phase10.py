"""
Banquet Agent Phase 10 — 单元测试

覆盖端点：
  - search_banquet          : 跨实体全文搜索（线索 + 订单）
  - get_revenue_target      : 读取月度营收目标
  - set_revenue_target      : 设置/更新月度营收目标（upsert）
  - create_custom_task      : 在订单下创建自定义执行任务
  - get_order_timeline      : 订单事件时间轴
"""

import pytest
from datetime import datetime, timedelta, date
from unittest.mock import AsyncMock, MagicMock


# ── helpers ─────────────────────────────────────────────────────────────────

def _mock_user():
    u = MagicMock()
    u.id = "user-001"
    u.brand_id = "BRAND-001"
    return u


def _scalars_returning(items):
    r = MagicMock()
    r.scalars.return_value.first.return_value = items[0] if items else None
    r.scalars.return_value.all.return_value = items
    r.first.return_value = items[0] if items else None
    r.all.return_value = items
    return r


def _make_customer(name="张三", phone="13800138000"):
    c = MagicMock()
    c.name = name
    c.phone = phone
    return c


def _make_lead(lead_id="L1", banquet_type=None, expected_date=None, stage="new"):
    from src.models.banquet import LeadStageEnum, BanquetTypeEnum
    l = MagicMock()
    l.id = lead_id
    l.banquet_type = banquet_type or BanquetTypeEnum.WEDDING
    l.expected_date = expected_date or date(2026, 6, 1)
    l.stage = LeadStageEnum(stage)
    return l


def _make_order(order_id="ORD-001", order_no="BQ-2026-0001", status="confirmed"):
    from src.models.banquet import OrderStatusEnum, BanquetTypeEnum
    o = MagicMock()
    o.id = order_id
    o.banquet_type = BanquetTypeEnum.WEDDING
    o.banquet_date = date(2026, 6, 15)
    o.total_amount_fen = 5_000_000   # ¥50,000
    o.order_status = OrderStatusEnum("confirmed")
    o.contact_name = "张三"
    o.contact_phone = "13800138000"
    o.store_id = "S001"
    return o


def _make_target(year=2026, month=3, target_fen=10_000_000):
    t = MagicMock()
    t.year = year
    t.month = month
    t.target_fen = target_fen
    return t


def _make_task(task_id="T1", name="摆台", role="service", status="pending",
               order_id="ORD-001", due_dt=None):
    from src.models.banquet import TaskStatusEnum, TaskOwnerRoleEnum
    t = MagicMock()
    t.id = task_id
    t.task_name = name
    t.owner_role = TaskOwnerRoleEnum(role)
    t.banquet_order_id = order_id
    t.due_time = due_dt or datetime.utcnow() + timedelta(days=1)
    t.task_status = TaskStatusEnum(status)
    t.updated_at = datetime.utcnow() - timedelta(hours=1)
    t.created_at = datetime.utcnow() - timedelta(hours=2)
    return t


def _make_payment(pay_id="PAY-001", amount_fen=500_000, method="wechat",
                  order_id="ORD-001"):
    p = MagicMock()
    p.id = pay_id
    p.banquet_order_id = order_id
    p.amount_fen = amount_fen
    p.payment_method = method
    p.created_at = datetime.utcnow() - timedelta(days=2)
    return p


def _make_agent_log(log_id="LOG-001", action_type="报价推荐", suggestion="推荐套餐A"):
    l = MagicMock()
    l.id = log_id
    l.action_type = action_type
    l.suggestion_text = suggestion
    l.created_at = datetime.utcnow() - timedelta(hours=5)
    return l


# ── search_banquet ───────────────────────────────────────────────────────────

class TestSearchBanquet:

    @pytest.mark.asyncio
    async def test_returns_leads_and_orders(self):
        from src.api.banquet_agent import search_banquet

        lead = _make_lead()
        cust = _make_customer()
        order = _make_order()

        db = AsyncMock()
        # Two execute calls: leads query, orders query
        db.execute = AsyncMock(side_effect=[
            MagicMock(all=MagicMock(return_value=[(lead, cust)])),
            MagicMock(all=MagicMock(return_value=[(order, cust)])),
        ])

        result = await search_banquet(store_id="S001", q="张三", type="all",
                                      db=db, _=_mock_user())

        assert len(result["leads"]) == 1
        assert result["leads"][0]["id"] == "L1"
        assert result["leads"][0]["type"] == "lead"
        assert len(result["orders"]) == 1
        assert result["orders"][0]["customer_name"] == "张三"
        assert result["orders"][0]["total_amount_yuan"] == pytest.approx(50000.0)

    @pytest.mark.asyncio
    async def test_type_lead_only_queries_leads(self):
        from src.api.banquet_agent import search_banquet

        lead = _make_lead()
        cust = _make_customer()

        db = AsyncMock()
        # Only one execute call expected when type="lead"
        db.execute = AsyncMock(return_value=MagicMock(
            all=MagicMock(return_value=[(lead, cust)])
        ))

        result = await search_banquet(store_id="S001", q="张三", type="lead",
                                      db=db, _=_mock_user())

        assert len(result["leads"]) == 1
        assert result["orders"] == []
        assert db.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_empty_result_when_no_matches(self):
        from src.api.banquet_agent import search_banquet

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            MagicMock(all=MagicMock(return_value=[])),
            MagicMock(all=MagicMock(return_value=[])),
        ])

        result = await search_banquet(store_id="S001", q="不存在", type="all",
                                      db=db, _=_mock_user())

        assert result["leads"] == []
        assert result["orders"] == []


# ── get_revenue_target ───────────────────────────────────────────────────────

class TestRevenueTarget:

    @pytest.mark.asyncio
    async def test_returns_null_when_not_set(self):
        from src.api.banquet_agent import get_revenue_target

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        result = await get_revenue_target(store_id="S001", year=2026, month=3,
                                          db=db, _=_mock_user())

        assert result["target_yuan"] is None
        assert result["target_fen"] is None
        assert result["year"] == 2026
        assert result["month"] == 3

    @pytest.mark.asyncio
    async def test_returns_target_when_set(self):
        from src.api.banquet_agent import get_revenue_target

        target = _make_target(year=2026, month=3, target_fen=500_000)  # ¥5,000

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([target]))

        result = await get_revenue_target(store_id="S001", year=2026, month=3,
                                          db=db, _=_mock_user())

        assert result["target_yuan"] == pytest.approx(5000.0)
        assert result["target_fen"] == 500000

    @pytest.mark.asyncio
    async def test_set_target_commits_and_returns(self):
        from pydantic import BaseModel
        from src.api.banquet_agent import set_revenue_target

        class _Body:
            target_yuan = 100000.0   # ¥100,000

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock())
        db.commit = AsyncMock()

        result = await set_revenue_target(store_id="S001", year=2026, month=4,
                                          body=_Body(), db=db, _=_mock_user())

        db.commit.assert_called_once()
        assert result["target_yuan"] == pytest.approx(100000.0)
        assert result["year"] == 2026
        assert result["month"] == 4


# ── create_custom_task ───────────────────────────────────────────────────────

class TestCreateCustomTask:

    @pytest.mark.asyncio
    async def test_creates_task_successfully(self):
        from src.api.banquet_agent import create_custom_task

        order = _make_order()

        class _Body:
            task_name  = "特殊布置"
            owner_role = "decor"
            due_time   = "2026-06-14T10:00:00"

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([order]))
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda t: setattr(t, 'id', t.id or 'NEW-ID'))

        result = await create_custom_task(store_id="S001", order_id="ORD-001",
                                          body=_Body(), db=db, _=_mock_user())

        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result["task_name"] == "特殊布置"
        assert result["owner_role"] == "decor"
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_404_on_unknown_order(self):
        from fastapi import HTTPException
        from src.api.banquet_agent import create_custom_task

        class _Body:
            task_name  = "备餐"
            owner_role = "kitchen"
            due_time   = "2026-06-14T10:00:00"

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        with pytest.raises(HTTPException) as exc:
            await create_custom_task(store_id="S001", order_id="NOORDER",
                                     body=_Body(), db=db, _=_mock_user())

        assert exc.value.status_code == 404


# ── get_order_timeline ───────────────────────────────────────────────────────

class TestOrderTimeline:

    @pytest.mark.asyncio
    async def test_merges_events_sorted_by_time(self):
        from src.api.banquet_agent import get_order_timeline

        order = _make_order()
        payment = _make_payment()
        task = _make_task(status="done")
        agent_log = _make_agent_log()

        # Calls: 1=verify order, 2=payments, 3=tasks, 4=agent_logs
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalars_returning([order]),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[payment])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[task])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[agent_log])))),
        ])

        result = await get_order_timeline(store_id="S001", order_id="ORD-001",
                                          db=db, _=_mock_user())

        assert len(result["events"]) == 3
        times = [e["time"] for e in result["events"]]
        assert times == sorted(times)  # ascending order

    @pytest.mark.asyncio
    async def test_empty_timeline_for_new_order(self):
        from src.api.banquet_agent import get_order_timeline

        order = _make_order()
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalars_returning([order]),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ])

        result = await get_order_timeline(store_id="S001", order_id="ORD-001",
                                          db=db, _=_mock_user())

        assert result["events"] == []

    @pytest.mark.asyncio
    async def test_404_on_unknown_order(self):
        from fastapi import HTTPException
        from src.api.banquet_agent import get_order_timeline

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        with pytest.raises(HTTPException) as exc:
            await get_order_timeline(store_id="S001", order_id="GHOST",
                                     db=db, _=_mock_user())

        assert exc.value.status_code == 404
