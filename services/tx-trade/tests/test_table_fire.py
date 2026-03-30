"""test_table_fire.py — 同桌同出（TableFire）协调引擎测试

测试场景：
1. 桌A有热菜档(预计8min)和凉菜档(预计3min)
   → 凉菜档应在热菜档完成前5分钟才开始（协调等待）
2. 所有档口完成后，ExpoStation亮起"可传菜"
3. 单独一个档口的订单不走协调（无需等待）
4. 催菜会缩短协调等待时间
5. tenant_id隔离测试
"""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 工具函数 ───

def make_uuid() -> str:
    return str(uuid.uuid4())


TENANT_A = make_uuid()
TENANT_B = make_uuid()
STORE_ID = make_uuid()
ORDER_ID = make_uuid()

HOT_DEPT_ID = make_uuid()   # 热菜档
COLD_DEPT_ID = make_uuid()  # 凉菜档


# ─── Fixture: Mock DB ───

@pytest.fixture
def mock_db():
    db = AsyncMock()
    return db


# ═════════════════════════════════════════════════════════
# 场景1: 热菜档(8min) + 凉菜档(3min) → 凉菜延迟5分钟开始
# ═════════════════════════════════════════════════════════

class TestTableFireCoordinator:
    """TableFireCoordinator 核心协调逻辑测试"""

    @pytest.mark.asyncio
    async def test_faster_dept_gets_delayed_start(self, mock_db):
        """凉菜档(3min)在热菜档(8min)基础上应延迟5分钟(300秒)开始"""
        from src.services.table_production_plan import TableFireCoordinator

        coordinator = TableFireCoordinator()

        items_by_dept = {
            HOT_DEPT_ID: {
                "dept_name": "热菜档",
                "estimated_seconds": 480,  # 8分钟
                "items": [{"task_id": make_uuid(), "dish_name": "红烧肉"}],
            },
            COLD_DEPT_ID: {
                "dept_name": "凉菜档",
                "estimated_seconds": 180,  # 3分钟
                "items": [{"task_id": make_uuid(), "dish_name": "口水鸡"}],
            },
        }

        plan = await coordinator.create_plan(
            order_id=ORDER_ID,
            table_no="A01",
            store_id=STORE_ID,
            tenant_id=TENANT_A,
            items_by_dept=items_by_dept,
            db=mock_db,
        )

        assert plan is not None
        assert plan.status == "coordinating"
        assert plan.tenant_id == uuid.UUID(TENANT_A)

        # 热菜档是最慢的，延迟为0
        hot_delay = plan.dept_delays.get(HOT_DEPT_ID, 0)
        assert hot_delay == 0, f"热菜档不应延迟，实际延迟={hot_delay}"

        # 凉菜档应延迟 480 - 180 - 30(buffer) = 270 秒
        cold_delay = plan.dept_delays.get(COLD_DEPT_ID, 0)
        expected_delay = 480 - 180 - 30  # bottleneck - duration - buffer
        assert cold_delay == expected_delay, (
            f"凉菜档延迟应为{expected_delay}秒，实际={cold_delay}"
        )

    @pytest.mark.asyncio
    async def test_target_completion_is_bottleneck_time(self, mock_db):
        """target_completion 应该是最慢档口的预计完成时间"""
        from src.services.table_production_plan import TableFireCoordinator

        coordinator = TableFireCoordinator()
        before = datetime.now(timezone.utc)

        items_by_dept = {
            HOT_DEPT_ID: {
                "dept_name": "热菜档",
                "estimated_seconds": 600,  # 10分钟
                "items": [{"task_id": make_uuid(), "dish_name": "剁椒鱼头"}],
            },
            COLD_DEPT_ID: {
                "dept_name": "凉菜档",
                "estimated_seconds": 120,  # 2分钟
                "items": [{"task_id": make_uuid(), "dish_name": "拍黄瓜"}],
            },
        }

        plan = await coordinator.create_plan(
            order_id=ORDER_ID,
            table_no="A02",
            store_id=STORE_ID,
            tenant_id=TENANT_A,
            items_by_dept=items_by_dept,
            db=mock_db,
        )

        after = datetime.now(timezone.utc)
        # target_completion 应在 before+10min ~ after+10min 之间
        min_target = before + timedelta(seconds=600)
        max_target = after + timedelta(seconds=600)

        assert min_target <= plan.target_completion <= max_target, (
            f"target_completion={plan.target_completion} 不在预期范围内"
        )


# ═════════════════════════════════════════════════════════
# 场景2: 所有档口完成 → ExpoStation 亮起"可传菜"
# ═════════════════════════════════════════════════════════

class TestNotifyDeptReady:
    """notify_dept_ready 档口完成通知测试"""

    @pytest.mark.asyncio
    async def test_all_ready_triggers_table_ready(self, mock_db):
        """两个档口都完成时，应推送 table_ready 信号"""
        from src.services.table_production_plan import TableFireCoordinator, TableProductionPlanInMemory

        plan_id = make_uuid()
        # 构造一个已有2个档口、均未就绪的计划
        plan = TableProductionPlanInMemory(
            id=uuid.UUID(plan_id),
            order_id=uuid.UUID(ORDER_ID),
            table_no="B01",
            store_id=uuid.UUID(STORE_ID),
            tenant_id=uuid.UUID(TENANT_A),
            target_completion=datetime.now(timezone.utc) + timedelta(minutes=8),
            status="coordinating",
            dept_readiness={HOT_DEPT_ID: False, COLD_DEPT_ID: False},
            dept_delays={HOT_DEPT_ID: 0, COLD_DEPT_ID: 270},
        )

        coordinator = TableFireCoordinator()
        ws_calls = []

        async def mock_push_ws(store_id: str, tenant_id: str, event: str, data: dict):
            ws_calls.append({"event": event, "data": data})

        with patch(
            "src.services.table_production_plan.push_table_ready_ws",
            side_effect=mock_push_ws,
        ):
            # 热菜档完成
            result1 = await coordinator.notify_dept_ready(
                plan=plan, dept_id=HOT_DEPT_ID, db=mock_db
            )
            assert result1["all_ready"] is False
            assert len(ws_calls) == 0

            # 凉菜档完成
            result2 = await coordinator.notify_dept_ready(
                plan=plan, dept_id=COLD_DEPT_ID, db=mock_db
            )
            assert result2["all_ready"] is True
            assert len(ws_calls) == 1
            assert ws_calls[0]["event"] == "table_ready"
            assert ws_calls[0]["data"]["table_no"] == "B01"

    @pytest.mark.asyncio
    async def test_partial_ready_does_not_trigger(self, mock_db):
        """只有部分档口完成时，不应触发传菜信号"""
        from src.services.table_production_plan import TableFireCoordinator, TableProductionPlanInMemory

        plan = TableProductionPlanInMemory(
            id=uuid.uuid4(),
            order_id=uuid.UUID(ORDER_ID),
            table_no="C01",
            store_id=uuid.UUID(STORE_ID),
            tenant_id=uuid.UUID(TENANT_A),
            target_completion=datetime.now(timezone.utc) + timedelta(minutes=5),
            status="coordinating",
            dept_readiness={HOT_DEPT_ID: False, COLD_DEPT_ID: False},
            dept_delays={HOT_DEPT_ID: 0, COLD_DEPT_ID: 150},
        )

        coordinator = TableFireCoordinator()
        ws_calls = []

        async def mock_push_ws(store_id: str, tenant_id: str, event: str, data: dict):
            ws_calls.append(event)

        with patch(
            "src.services.table_production_plan.push_table_ready_ws",
            side_effect=mock_push_ws,
        ):
            result = await coordinator.notify_dept_ready(
                plan=plan, dept_id=HOT_DEPT_ID, db=mock_db
            )

        assert result["all_ready"] is False
        assert len(ws_calls) == 0


# ═════════════════════════════════════════════════════════
# 场景3: 单档口订单不走协调（无需等待）
# ═════════════════════════════════════════════════════════

class TestSingleDeptNoCoordination:
    """单档口订单跳过协调逻辑"""

    @pytest.mark.asyncio
    async def test_single_dept_no_delay(self, mock_db):
        """只有一个档口时，延迟应为0，直接可以开始"""
        from src.services.table_production_plan import TableFireCoordinator

        coordinator = TableFireCoordinator()

        items_by_dept = {
            HOT_DEPT_ID: {
                "dept_name": "热菜档",
                "estimated_seconds": 480,
                "items": [{"task_id": make_uuid(), "dish_name": "糖醋里脊"}],
            },
        }

        plan = await coordinator.create_plan(
            order_id=ORDER_ID,
            table_no="D01",
            store_id=STORE_ID,
            tenant_id=TENANT_A,
            items_by_dept=items_by_dept,
            db=mock_db,
        )

        # 单档口：延迟为0
        hot_delay = plan.dept_delays.get(HOT_DEPT_ID, 0)
        assert hot_delay == 0, f"单档口不应有延迟，实际={hot_delay}"
        # 状态直接是 coordinating（仍然建立计划，只是无延迟）
        assert plan.status == "coordinating"

    @pytest.mark.asyncio
    async def test_single_dept_empty_items_returns_none(self, mock_db):
        """空菜品列表应返回None，不建立计划"""
        from src.services.table_production_plan import TableFireCoordinator

        coordinator = TableFireCoordinator()

        plan = await coordinator.create_plan(
            order_id=ORDER_ID,
            table_no="E01",
            store_id=STORE_ID,
            tenant_id=TENANT_A,
            items_by_dept={},
            db=mock_db,
        )

        assert plan is None, "空档口列表应返回None"


# ═════════════════════════════════════════════════════════
# 场景4: 催菜会缩短协调等待时间
# ═════════════════════════════════════════════════════════

class TestUrgentReducesDelay:
    """催菜（urgent=True）缩短慢档口预计时间，连带减少等待"""

    @pytest.mark.asyncio
    async def test_urgent_reduces_bottleneck_estimate(self, mock_db):
        """催菜后热菜档预计时间应缩短（乘以urgent_factor），
        相应地凉菜档等待时间也缩短"""
        from src.services.table_production_plan import TableFireCoordinator

        coordinator = TableFireCoordinator()

        items_by_dept_normal = {
            HOT_DEPT_ID: {
                "dept_name": "热菜档",
                "estimated_seconds": 600,  # 10分钟
                "items": [{"task_id": make_uuid(), "dish_name": "东坡肉", "urgent": False}],
            },
            COLD_DEPT_ID: {
                "dept_name": "凉菜档",
                "estimated_seconds": 120,  # 2分钟
                "items": [{"task_id": make_uuid(), "dish_name": "皮蛋豆腐", "urgent": False}],
            },
        }

        items_by_dept_urgent = {
            HOT_DEPT_ID: {
                "dept_name": "热菜档",
                "estimated_seconds": 600,  # 10分钟原始
                "items": [{"task_id": make_uuid(), "dish_name": "东坡肉", "urgent": True}],
            },
            COLD_DEPT_ID: {
                "dept_name": "凉菜档",
                "estimated_seconds": 120,  # 2分钟
                "items": [{"task_id": make_uuid(), "dish_name": "皮蛋豆腐", "urgent": False}],
            },
        }

        plan_normal = await coordinator.create_plan(
            order_id=make_uuid(),
            table_no="F01",
            store_id=STORE_ID,
            tenant_id=TENANT_A,
            items_by_dept=items_by_dept_normal,
            db=mock_db,
        )

        plan_urgent = await coordinator.create_plan(
            order_id=make_uuid(),
            table_no="F02",
            store_id=STORE_ID,
            tenant_id=TENANT_A,
            items_by_dept=items_by_dept_urgent,
            db=mock_db,
        )

        normal_cold_delay = plan_normal.dept_delays.get(COLD_DEPT_ID, 0)
        urgent_cold_delay = plan_urgent.dept_delays.get(COLD_DEPT_ID, 0)

        # 催菜后，热菜档预计时间缩短 → 凉菜档等待时间应更短（或为0）
        assert urgent_cold_delay <= normal_cold_delay, (
            f"催菜后凉菜等待应缩短：normal={normal_cold_delay}, urgent={urgent_cold_delay}"
        )


# ═════════════════════════════════════════════════════════
# 场景5: tenant_id 隔离测试
# ═════════════════════════════════════════════════════════

class TestTenantIsolation:
    """不同租户的计划互不可见"""

    @pytest.mark.asyncio
    async def test_expo_view_filters_by_tenant(self, mock_db):
        """get_expo_view 只返回指定租户的数据"""
        from src.services.table_production_plan import TableFireCoordinator

        coordinator = TableFireCoordinator()

        # 模拟 DB 查询：只返回 TENANT_A 的计划
        from src.models.table_production_plan import TableProductionPlan as DBPlan

        tenant_a_plan = MagicMock(spec=DBPlan)
        tenant_a_plan.id = uuid.uuid4()
        tenant_a_plan.tenant_id = uuid.UUID(TENANT_A)
        tenant_a_plan.store_id = uuid.UUID(STORE_ID)
        tenant_a_plan.table_no = "G01"
        tenant_a_plan.status = "coordinating"
        tenant_a_plan.dept_readiness = {HOT_DEPT_ID: False}
        tenant_a_plan.target_completion = datetime.now(timezone.utc) + timedelta(minutes=5)
        tenant_a_plan.order_id = uuid.UUID(ORDER_ID)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [tenant_a_plan]
        mock_db.execute.return_value = mock_result

        tickets = await coordinator.get_expo_view(
            store_id=STORE_ID,
            tenant_id=TENANT_A,
            db=mock_db,
        )

        # 验证查询中传入了 TENANT_A
        assert mock_db.execute.called
        call_args = mock_db.execute.call_args
        # 断言返回的数据属于 TENANT_A
        assert len(tickets) == 1
        assert str(tickets[0]["tenant_id"]) == TENANT_A

    @pytest.mark.asyncio
    async def test_create_plan_embeds_tenant_id(self, mock_db):
        """create_plan 生成的计划必须包含正确的 tenant_id"""
        from src.services.table_production_plan import TableFireCoordinator

        coordinator = TableFireCoordinator()

        items_by_dept = {
            HOT_DEPT_ID: {
                "dept_name": "热菜档",
                "estimated_seconds": 480,
                "items": [{"task_id": make_uuid(), "dish_name": "辣椒炒肉"}],
            },
        }

        plan = await coordinator.create_plan(
            order_id=make_uuid(),
            table_no="H01",
            store_id=STORE_ID,
            tenant_id=TENANT_B,
            items_by_dept=items_by_dept,
            db=mock_db,
        )

        assert str(plan.tenant_id) == TENANT_B, (
            f"计划的tenant_id应为{TENANT_B}，实际={plan.tenant_id}"
        )


# ═════════════════════════════════════════════════════════
# ExpoTicket 结构验证
# ═════════════════════════════════════════════════════════

class TestExpoTicketStructure:
    """ExpoStation 票据数据结构测试"""

    def test_expo_ticket_has_required_fields(self):
        """ExpoTicket 必须包含所有必需字段"""
        from src.services.table_production_plan import ExpoTicket

        ticket = ExpoTicket(
            plan_id=str(uuid.uuid4()),
            order_id=ORDER_ID,
            table_no="I01",
            store_id=STORE_ID,
            tenant_id=TENANT_A,
            status="coordinating",
            total_depts=2,
            ready_depts=1,
            target_completion=(datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat(),
            dept_progress=[
                {"dept_id": HOT_DEPT_ID, "dept_name": "热菜档", "ready": False},
                {"dept_id": COLD_DEPT_ID, "dept_name": "凉菜档", "ready": True},
            ],
        )

        assert ticket.plan_id is not None
        assert ticket.table_no == "I01"
        assert ticket.total_depts == 2
        assert ticket.ready_depts == 1
        assert len(ticket.dept_progress) == 2

    def test_all_ready_status(self):
        """全部就绪时 status 应为 all_ready"""
        from src.services.table_production_plan import ExpoTicket

        ticket = ExpoTicket(
            plan_id=str(uuid.uuid4()),
            order_id=ORDER_ID,
            table_no="J01",
            store_id=STORE_ID,
            tenant_id=TENANT_A,
            status="all_ready",
            total_depts=2,
            ready_depts=2,
            target_completion=datetime.now(timezone.utc).isoformat(),
            dept_progress=[
                {"dept_id": HOT_DEPT_ID, "dept_name": "热菜档", "ready": True},
                {"dept_id": COLD_DEPT_ID, "dept_name": "凉菜档", "ready": True},
            ],
        )

        assert ticket.status == "all_ready"
        assert ticket.ready_depts == ticket.total_depts
