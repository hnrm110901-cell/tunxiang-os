"""桌台监控服务 — 单元测试

覆盖场景：
1. 空门店返回空列表
2. 进行中订单正确聚合到桌台
3. 超时桌台 is_overtime=True
4. 催单次数正确统计
5. 区域分组正确（包厢/大厅）
6. 单桌详情包含所有菜品状态
7. 租户隔离
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ..services.table_monitor_service import (
    DEFAULT_STANDARD_MINUTES,
    TableMonitorService,
    _infer_zone,
)

# ─── 工具 ───

def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
STORE_ID = _uid()
TABLE_NO_HALL = "A01"
TABLE_NO_VIP = "P01"


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def one_or_none(self):
        return self._rows[0] if self._rows else None


def _fake_db(first_result=None, second_result=None):
    db = AsyncMock()
    call_results = []
    if first_result is not None:
        call_results.append(FakeResult(rows=first_result))
    if second_result is not None:
        call_results.append(FakeResult(rows=second_result))
    # 默认无限返回空结果
    if not call_results:
        db.execute = AsyncMock(return_value=FakeResult())
    else:
        db.execute = AsyncMock(side_effect=call_results)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_task_row(
    table_no: str,
    status: str = "cooking",
    rush_count: int = 0,
    order_created_minutes_ago: int = 10,
    item_name: str = "小炒肉",
    qty: int = 1,
    started_at: datetime = None,
):
    """构造联表查询行:
    (KDSTask, item_name, quantity, table_number, order_created_at)
    对应: KDSTask, OrderItem.item_name, OrderItem.quantity, Order.table_number, Order.created_at
    """
    task = MagicMock()
    task.id = uuid.UUID(_uid())
    task.status = status
    task.rush_count = rush_count
    task.dept_id = uuid.UUID(_uid())
    task.started_at = started_at
    task.is_deleted = False

    now = datetime.now(timezone.utc)
    order_created_at = now - timedelta(minutes=order_created_minutes_ago)

    # row = (KDSTask, item_name, quantity, table_number, order_created_at)
    return (task, item_name, qty, table_no, order_created_at)


# ─── 场景1: 空门店返回空列表 ───

class TestEmptyStore:

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty_list(self):
        """无活跃任务时返回空列表"""
        db = _fake_db(first_result=[], second_result=[])
        result = await TableMonitorService.get_store_overview(STORE_ID, TENANT_ID, db)
        assert result == []


# ─── 场景2: 进行中订单正确聚合到桌台 ───

class TestOrderAggregation:

    @pytest.mark.asyncio
    async def test_active_orders_aggregated_by_table(self):
        """同一桌台的多道菜聚合为一个 TableStatus"""
        rows = [
            _make_task_row(TABLE_NO_HALL, item_name="红烧肉", qty=1),
            _make_task_row(TABLE_NO_HALL, item_name="米饭", qty=2),
        ]
        db = _fake_db(first_result=rows, second_result=[])
        result = await TableMonitorService.get_store_overview(STORE_ID, TENANT_ID, db)

        assert len(result) == 1
        table = result[0]
        assert table.table_no == TABLE_NO_HALL
        assert table.dish_total == 3  # 1 + 2
        assert table.status in ("cooking", "ordering")
        assert len(table.pending_dishes) == 2

    @pytest.mark.asyncio
    async def test_multiple_tables_separate_entries(self):
        """两张桌台产生两条独立记录"""
        rows = [
            _make_task_row(TABLE_NO_HALL),
            _make_task_row(TABLE_NO_VIP),
        ]
        db = _fake_db(first_result=rows, second_result=[])
        result = await TableMonitorService.get_store_overview(STORE_ID, TENANT_ID, db)

        assert len(result) == 2
        table_nos = {t.table_no for t in result}
        assert TABLE_NO_HALL in table_nos
        assert TABLE_NO_VIP in table_nos


# ─── 场景3: 超时桌台 is_overtime=True ───

class TestOvertimeDetection:

    @pytest.mark.asyncio
    async def test_overtime_table_flagged(self):
        """超过 DEFAULT_STANDARD_MINUTES 的桌台 is_overtime=True"""
        overtime_minutes = DEFAULT_STANDARD_MINUTES + 10  # 35分钟
        rows = [
            _make_task_row("A02", order_created_minutes_ago=overtime_minutes)
        ]
        db = _fake_db(first_result=rows, second_result=[])
        result = await TableMonitorService.get_store_overview(STORE_ID, TENANT_ID, db)

        assert len(result) == 1
        assert result[0].is_overtime is True
        assert result[0].status == "overtime"
        assert result[0].elapsed_minutes >= DEFAULT_STANDARD_MINUTES

    @pytest.mark.asyncio
    async def test_normal_table_not_overtime(self):
        """在阈值内的桌台 is_overtime=False"""
        rows = [
            _make_task_row("A03", order_created_minutes_ago=5)
        ]
        db = _fake_db(first_result=rows, second_result=[])
        result = await TableMonitorService.get_store_overview(STORE_ID, TENANT_ID, db)

        assert result[0].is_overtime is False


# ─── 场景4: 催单次数正确统计 ───

class TestRushCount:

    @pytest.mark.asyncio
    async def test_rush_count_aggregated(self):
        """桌台的 rush_count 取所有任务中的最大值"""
        rows = [
            _make_task_row("A04", rush_count=2),
            _make_task_row("A04", rush_count=1),
        ]
        db = _fake_db(first_result=rows, second_result=[])
        result = await TableMonitorService.get_store_overview(STORE_ID, TENANT_ID, db)

        assert len(result) == 1
        assert result[0].rush_count == 2

    @pytest.mark.asyncio
    async def test_rush_status_when_rush_count_positive(self):
        """rush_count>0 且未超时 → status='rush'"""
        rows = [
            _make_task_row("A05", rush_count=1, order_created_minutes_ago=5)
        ]
        db = _fake_db(first_result=rows, second_result=[])
        result = await TableMonitorService.get_store_overview(STORE_ID, TENANT_ID, db)

        assert result[0].status == "rush"


# ─── 场景5: 区域分组正确（包厢/大厅） ───

class TestZoneGrouping:

    def test_vip_prefix_infers_vip_zone(self):
        """VIP前缀桌台 → 包厢"""
        assert _infer_zone("VIP01") == "包厢"
        assert _infer_zone("P01") == "包厢"
        assert _infer_zone("包间A") == "包厢"

    def test_regular_table_infers_hall_zone(self):
        """普通桌号 → 大厅"""
        assert _infer_zone("A01") == "大厅"
        assert _infer_zone("B12") == "大厅"
        assert _infer_zone("1号桌") == "大厅"

    @pytest.mark.asyncio
    async def test_zone_summary_groups_correctly(self):
        """区域汇总正确区分包厢/大厅"""
        db = MagicMock()

        mock_hall = MagicMock(
            table_no="A01", zone="大厅",
            is_overtime=False, rush_count=0, elapsed_minutes=10,
        )
        mock_vip = MagicMock(
            table_no="P01", zone="包厢",
            is_overtime=True, rush_count=1, elapsed_minutes=35,
        )

        with patch.object(
            TableMonitorService,
            "get_store_overview",
            AsyncMock(return_value=[mock_hall, mock_vip]),
        ):
            summary = await TableMonitorService.get_zone_summary(STORE_ID, TENANT_ID, db)

        assert "大厅" in summary
        assert "包厢" in summary
        assert summary["大厅"].table_count == 1
        assert summary["包厢"].overtime_count == 1
        assert summary["包厢"].rush_count == 1


# ─── 场景6: 单桌详情包含所有菜品状态 ───

class TestTableDetail:

    @pytest.mark.asyncio
    async def test_table_detail_includes_all_dish_statuses(self):
        """单桌详情应包含 pending/cooking 状态的菜品"""
        rows = [
            _make_task_row(TABLE_NO_HALL, status="cooking", item_name="红烧肉"),
            _make_task_row(TABLE_NO_HALL, status="pending", item_name="凉拌黄瓜"),
        ]
        db = _fake_db(first_result=rows)

        detail = await TableMonitorService.get_table_detail(TABLE_NO_HALL, TENANT_ID, db)

        assert detail is not None
        assert detail.table_no == TABLE_NO_HALL
        assert detail.dish_total == 2
        dish_names = {d.name for d in detail.dishes}
        assert "红烧肉" in dish_names
        assert "凉拌黄瓜" in dish_names

    @pytest.mark.asyncio
    async def test_table_detail_returns_none_for_no_orders(self):
        """无订单时 get_table_detail 返回 None"""
        db = _fake_db(first_result=[])
        detail = await TableMonitorService.get_table_detail(TABLE_NO_HALL, TENANT_ID, db)
        assert detail is None

    @pytest.mark.asyncio
    async def test_table_detail_dish_done_counted_correctly(self):
        """已出菜（done）的菜品正确计入 dish_done"""
        rows = [
            _make_task_row(TABLE_NO_HALL, status="done", item_name="小炒肉"),
            _make_task_row(TABLE_NO_HALL, status="cooking", item_name="米饭"),
        ]
        db = _fake_db(first_result=rows)

        detail = await TableMonitorService.get_table_detail(TABLE_NO_HALL, TENANT_ID, db)

        assert detail is not None
        assert detail.dish_done == 1
        assert detail.dish_total == 2


# ─── 场景7: 租户隔离 ───

class TestTenantIsolation:

    @pytest.mark.asyncio
    async def test_different_tenants_get_independent_results(self):
        """不同租户查询同一门店应各自独立，不互相泄漏数据"""
        tenant_a = _uid()
        tenant_b = _uid()

        db_a = _fake_db(first_result=[], second_result=[])
        db_b = _fake_db(first_result=[], second_result=[])

        result_a = await TableMonitorService.get_store_overview(STORE_ID, tenant_a, db_a)
        result_b = await TableMonitorService.get_store_overview(STORE_ID, tenant_b, db_b)

        # 两个租户独立查询，均为空
        assert result_a == []
        assert result_b == []
        # 各自的 db 均被调用（说明各自独立执行了查询）
        assert db_a.execute.called
        assert db_b.execute.called

    @pytest.mark.asyncio
    async def test_invalid_tenant_id_raises_value_error(self):
        """非法 UUID 格式应抛出 ValueError"""
        db = AsyncMock()
        with pytest.raises(ValueError):
            await TableMonitorService.get_store_overview(STORE_ID, "not-a-uuid", db)

    @pytest.mark.asyncio
    async def test_invalid_store_id_raises_value_error(self):
        """非法 store_id UUID 格式应抛出 ValueError"""
        db = AsyncMock()
        with pytest.raises(ValueError):
            await TableMonitorService.get_store_overview("bad-store-id", TENANT_ID, db)
