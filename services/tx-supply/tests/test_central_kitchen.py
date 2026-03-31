"""中央厨房服务层测试

覆盖场景：
  1.  创建生产计划，验证草稿状态
  2.  确认计划，验证工单自动生成（draft → confirmed）
  3.  开始生产（confirmed → in_progress）
  4.  完成工单（实际产量记录，所有工单完成后计划自动 completed）
  5.  update_production_progress 完整状态流转
  6.  确认收货时差异记录（>5% 自动生成 variance_notes）
  7.  确认收货时差异不超过 5% 不生成 variance_notes
  8.  看板数据计算正确性（工单状态汇总/配送单状态汇总）
  9.  需求预测（工作日 vs 周末权重）
  10. 跨租户隔离：访问他租户资源抛 ValueError
  11. 非法状态流转：已完成工单不可再更新
  12. 空菜品清单 → 自动使用需求预测填充
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest

from services.central_kitchen_service import (
    CentralKitchenService,
    _clear_store,
    _inject_consumption,
)

# ─── 公共常量 ──────────────────────────────────────────────────────────────

TENANT_A = "tenant-aaaa-0000-0000-000000000001"
TENANT_B = "tenant-bbbb-0000-0000-000000000002"
STORE_ID = "store-0001-0000-0000-000000000001"
DISH_ID_1 = "dish-0001-0000-0000-000000000001"
DISH_ID_2 = "dish-0002-0000-0000-000000000002"
OPERATOR = "emp-0001-0000-0000-000000000001"

SAMPLE_ITEMS = [
    {
        "dish_id": DISH_ID_1,
        "dish_name": "红烧肉",
        "quantity": 50.0,
        "unit": "份",
        "target_stores": [],
    },
    {
        "dish_id": DISH_ID_2,
        "dish_name": "清蒸鱼",
        "quantity": 30.0,
        "unit": "份",
        "target_stores": [],
    },
]


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_store():
    """每个测试前后清空内存存储，保证隔离。"""
    _clear_store()
    yield
    _clear_store()


@pytest.fixture
def svc() -> CentralKitchenService:
    return CentralKitchenService()


# ─── 辅助协程（在测试中 await 调用，避免 async fixture 兼容性问题）─────────


async def _make_kitchen(svc: CentralKitchenService):
    return await svc.create_kitchen(
        tenant_id=TENANT_A,
        name="屯象测试中央厨房",
        address="湖南省长沙市",
        capacity_daily=500.0,
        manager_id=OPERATOR,
    )


async def _make_confirmed_plan(svc: CentralKitchenService, kitchen_id: str):
    plan = await svc.create_production_plan(
        tenant_id=TENANT_A,
        kitchen_id=kitchen_id,
        plan_date="2026-04-01",
        items=SAMPLE_ITEMS,
        created_by=OPERATOR,
    )
    return await svc.confirm_production_plan(
        tenant_id=TENANT_A, plan_id=plan.id, operator_id=OPERATOR
    )


async def _make_dispatched_order(svc: CentralKitchenService, kitchen_id: str):
    order = await svc.create_distribution_order(
        tenant_id=TENANT_A,
        kitchen_id=kitchen_id,
        store_id=STORE_ID,
        items=[
            {
                "dish_id": DISH_ID_1,
                "dish_name": "红烧肉",
                "quantity": 50.0,
                "unit": "份",
            }
        ],
        scheduled_at="2026-04-01T10:00:00Z",
    )
    return await svc.mark_dispatched(tenant_id=TENANT_A, order_id=order.id)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 创建生产计划，验证草稿状态
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_create_production_plan_returns_draft(svc):
    kitchen = await _make_kitchen(svc)
    plan = await svc.create_production_plan(
        tenant_id=TENANT_A,
        kitchen_id=kitchen.id,
        plan_date="2026-04-01",
        items=SAMPLE_ITEMS,
        created_by=OPERATOR,
    )
    assert plan.status == "draft"
    assert plan.kitchen_id == kitchen.id
    assert plan.tenant_id == TENANT_A
    assert plan.plan_date == "2026-04-01"
    assert len(plan.items) == 2


@pytest.mark.asyncio
async def test_create_plan_invalid_kitchen_raises(svc):
    with pytest.raises(ValueError, match="不存在"):
        await svc.create_production_plan(
            tenant_id=TENANT_A,
            kitchen_id="non-existent-kitchen-id",
            plan_date="2026-04-01",
            items=SAMPLE_ITEMS,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 确认计划，验证工单自动生成（draft → confirmed）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_confirm_plan_creates_production_orders(svc):
    kitchen = await _make_kitchen(svc)
    plan = await svc.create_production_plan(
        tenant_id=TENANT_A,
        kitchen_id=kitchen.id,
        plan_date="2026-04-01",
        items=SAMPLE_ITEMS,
        created_by=OPERATOR,
    )
    confirmed = await svc.confirm_production_plan(
        tenant_id=TENANT_A, plan_id=plan.id, operator_id=OPERATOR
    )
    assert confirmed.status == "confirmed"
    assert confirmed.confirmed_at is not None

    orders_result = await svc.list_production_orders(
        tenant_id=TENANT_A, plan_id=plan.id
    )
    assert orders_result["total"] == 2  # 两个菜品对应两张工单
    for order in orders_result["items"]:
        assert order["status"] == "pending"
        assert order["plan_id"] == plan.id


@pytest.mark.asyncio
async def test_confirm_plan_wrong_status_raises(svc):
    kitchen = await _make_kitchen(svc)
    plan = await svc.create_production_plan(
        tenant_id=TENANT_A,
        kitchen_id=kitchen.id,
        plan_date="2026-04-01",
        items=SAMPLE_ITEMS,
    )
    await svc.confirm_production_plan(
        tenant_id=TENANT_A, plan_id=plan.id, operator_id=OPERATOR
    )
    # 再次确认应抛出异常
    with pytest.raises(ValueError, match="只有 draft 状态可确认"):
        await svc.confirm_production_plan(
            tenant_id=TENANT_A, plan_id=plan.id, operator_id=OPERATOR
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 开始生产（confirmed → in_progress）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_start_production_transitions_to_in_progress(svc):
    kitchen = await _make_kitchen(svc)
    plan = await _make_confirmed_plan(svc, kitchen.id)
    started = await svc.start_production(tenant_id=TENANT_A, plan_id=plan.id)
    assert started.status == "in_progress"

    # 所有工单应从 pending → in_progress
    orders = await svc.list_production_orders(tenant_id=TENANT_A, plan_id=plan.id)
    for order in orders["items"]:
        assert order["status"] == "in_progress"
        assert order["started_at"] is not None


@pytest.mark.asyncio
async def test_start_production_from_draft_raises(svc):
    kitchen = await _make_kitchen(svc)
    plan = await svc.create_production_plan(
        tenant_id=TENANT_A,
        kitchen_id=kitchen.id,
        plan_date="2026-04-01",
        items=SAMPLE_ITEMS,
    )
    with pytest.raises(ValueError, match="只有 confirmed 状态可开始生产"):
        await svc.start_production(tenant_id=TENANT_A, plan_id=plan.id)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 完成工单 + 计划自动完成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_complete_all_orders_auto_completes_plan(svc):
    kitchen = await _make_kitchen(svc)
    plan = await _make_confirmed_plan(svc, kitchen.id)
    await svc.start_production(tenant_id=TENANT_A, plan_id=plan.id)

    orders = await svc.list_production_orders(tenant_id=TENANT_A, plan_id=plan.id)
    order_ids = [o["id"] for o in orders["items"]]

    # 完成第一张工单，计划不应自动完成
    await svc.complete_production_order(
        tenant_id=TENANT_A, order_id=order_ids[0], actual_qty=48.0
    )
    partial_plan = await svc.get_production_plan(tenant_id=TENANT_A, plan_id=plan.id)
    assert partial_plan.status == "in_progress"

    # 完成最后一张工单，计划自动升为 completed
    await svc.complete_production_order(
        tenant_id=TENANT_A, order_id=order_ids[1], actual_qty=29.5
    )
    completed_plan = await svc.get_production_plan(tenant_id=TENANT_A, plan_id=plan.id)
    assert completed_plan.status == "completed"


@pytest.mark.asyncio
async def test_complete_order_records_actual_qty(svc):
    kitchen = await _make_kitchen(svc)
    plan = await _make_confirmed_plan(svc, kitchen.id)
    orders = await svc.list_production_orders(tenant_id=TENANT_A, plan_id=plan.id)
    order_id = orders["items"][0]["id"]

    completed_order = await svc.complete_production_order(
        tenant_id=TENANT_A, order_id=order_id, actual_qty=47.5
    )
    assert completed_order.status == "completed"
    assert completed_order.quantity == 47.5
    assert completed_order.completed_at is not None


@pytest.mark.asyncio
async def test_complete_order_negative_qty_raises(svc):
    kitchen = await _make_kitchen(svc)
    plan = await _make_confirmed_plan(svc, kitchen.id)
    orders = await svc.list_production_orders(tenant_id=TENANT_A, plan_id=plan.id)
    order_id = orders["items"][0]["id"]
    with pytest.raises(ValueError, match="actual_qty 不能为负数"):
        await svc.complete_production_order(
            tenant_id=TENANT_A, order_id=order_id, actual_qty=-1.0
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. update_production_progress 状态流转
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_update_progress_full_flow(svc):
    kitchen = await _make_kitchen(svc)
    plan = await _make_confirmed_plan(svc, kitchen.id)
    orders = await svc.list_production_orders(tenant_id=TENANT_A, plan_id=plan.id)
    order_id = orders["items"][0]["id"]

    # pending → in_progress
    in_prog = await svc.update_production_progress(
        tenant_id=TENANT_A, order_id=order_id, status="in_progress"
    )
    assert in_prog.status == "in_progress"
    assert in_prog.started_at is not None

    # in_progress → completed（需要 quantity_done）
    done = await svc.update_production_progress(
        tenant_id=TENANT_A,
        order_id=order_id,
        status="completed",
        quantity_done=45.0,
    )
    assert done.status == "completed"
    assert done.completed_at is not None


@pytest.mark.asyncio
async def test_update_completed_order_raises(svc):
    kitchen = await _make_kitchen(svc)
    plan = await _make_confirmed_plan(svc, kitchen.id)
    orders = await svc.list_production_orders(tenant_id=TENANT_A, plan_id=plan.id)
    order_id = orders["items"][0]["id"]

    await svc.update_production_progress(
        tenant_id=TENANT_A,
        order_id=order_id,
        status="completed",
        quantity_done=50.0,
    )
    with pytest.raises(ValueError, match="已处于 completed 状态"):
        await svc.update_production_progress(
            tenant_id=TENANT_A, order_id=order_id, status="in_progress"
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6 & 7. 确认收货时差异记录
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_confirm_receiving_variance_over_5pct_auto_notes(svc):
    """差异 >5% 时自动生成 variance_notes"""
    kitchen = await _make_kitchen(svc)
    dispatched = await _make_dispatched_order(svc, kitchen.id)

    confirmation = await svc.confirm_store_receiving(
        tenant_id=TENANT_A,
        distribution_order_id=dispatched.id,
        store_id=STORE_ID,
        confirmed_by=OPERATOR,
        items=[
            {
                "dish_id": DISH_ID_1,
                "dish_name": "红烧肉",
                "received_qty": 40.0,
                "unit": "份",
            }
        ],
    )
    assert confirmation.distribution_order_id == dispatched.id
    assert confirmation.store_id == STORE_ID

    item = confirmation.items[0]
    # 差异 = (50-40)/50 = 20% > 5%，应自动生成 variance_notes
    assert item["variance_notes"] is not None
    assert "差异" in item["variance_notes"]
    assert item["expected_qty"] == 50.0
    assert item["received_qty"] == 40.0


@pytest.mark.asyncio
async def test_confirm_receiving_no_variance_no_notes(svc):
    """差异 <=5% 时不自动生成 variance_notes"""
    kitchen = await _make_kitchen(svc)
    dispatched = await _make_dispatched_order(svc, kitchen.id)

    confirmation = await svc.confirm_store_receiving(
        tenant_id=TENANT_A,
        distribution_order_id=dispatched.id,
        store_id=STORE_ID,
        confirmed_by=OPERATOR,
        items=[
            # 差异 = (50-49)/50 = 2% < 5%
            {
                "dish_id": DISH_ID_1,
                "dish_name": "红烧肉",
                "received_qty": 49.0,
                "unit": "份",
            }
        ],
    )
    item = confirmation.items[0]
    assert item["variance_notes"] is None


@pytest.mark.asyncio
async def test_confirm_receiving_updates_distribution_status(svc):
    """确认收货后配送单状态变为 confirmed"""
    kitchen = await _make_kitchen(svc)
    dispatched = await _make_dispatched_order(svc, kitchen.id)

    await svc.confirm_store_receiving(
        tenant_id=TENANT_A,
        distribution_order_id=dispatched.id,
        store_id=STORE_ID,
        confirmed_by=OPERATOR,
        items=[
            {
                "dish_id": DISH_ID_1,
                "dish_name": "红烧肉",
                "received_qty": 50.0,
                "unit": "份",
            }
        ],
    )
    orders = await svc.list_distribution_orders(
        tenant_id=TENANT_A, status="confirmed"
    )
    assert orders["total"] == 1
    assert orders["items"][0]["id"] == dispatched.id


@pytest.mark.asyncio
async def test_confirm_receiving_store_mismatch_raises(svc):
    """门店 ID 不匹配时抛出 ValueError"""
    kitchen = await _make_kitchen(svc)
    dispatched = await _make_dispatched_order(svc, kitchen.id)

    with pytest.raises(ValueError, match="目标门店不匹配"):
        await svc.confirm_store_receiving(
            tenant_id=TENANT_A,
            distribution_order_id=dispatched.id,
            store_id="wrong-store-id",
            confirmed_by=OPERATOR,
            items=[
                {
                    "dish_id": DISH_ID_1,
                    "dish_name": "红烧肉",
                    "received_qty": 50.0,
                    "unit": "份",
                }
            ],
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. 看板数据计算正确性
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_dashboard_counts(svc):
    kitchen = await _make_kitchen(svc)
    plan = await _make_confirmed_plan(svc, kitchen.id)

    # 创建一张配送单并标记已发出
    dist = await svc.create_distribution_order(
        tenant_id=TENANT_A,
        kitchen_id=kitchen.id,
        store_id=STORE_ID,
        items=[
            {
                "dish_id": DISH_ID_1,
                "dish_name": "红烧肉",
                "quantity": 20.0,
                "unit": "份",
            }
        ],
        scheduled_at="2026-04-01T10:00:00Z",
    )
    await svc.mark_dispatched(tenant_id=TENANT_A, order_id=dist.id)

    dashboard = await svc.get_daily_dashboard(
        tenant_id=TENANT_A, kitchen_id=kitchen.id, date="2026-04-01"
    )

    assert dashboard.plan_count == 1
    assert dashboard.plans[0]["id"] == plan.id

    # 工单状态：2张 pending（未调用 start_production）
    assert dashboard.production_order_summary["pending"] == 2

    # 配送单：1张 dispatched
    assert dashboard.distribution_summary["dispatched"] == 1
    assert dashboard.distribution_summary["pending"] == 0


@pytest.mark.asyncio
async def test_dashboard_empty_for_different_date(svc):
    """不同日期看板应为空"""
    kitchen = await _make_kitchen(svc)
    await _make_confirmed_plan(svc, kitchen.id)

    dashboard = await svc.get_daily_dashboard(
        tenant_id=TENANT_A, kitchen_id=kitchen.id, date="2026-04-02"
    )
    assert dashboard.plan_count == 0
    assert dashboard.production_order_summary["pending"] == 0


@pytest.mark.asyncio
async def test_dashboard_in_progress_orders_counted(svc):
    """开始生产后，工单状态汇总更新为 in_progress"""
    kitchen = await _make_kitchen(svc)
    plan = await _make_confirmed_plan(svc, kitchen.id)
    await svc.start_production(tenant_id=TENANT_A, plan_id=plan.id)

    dashboard = await svc.get_daily_dashboard(
        tenant_id=TENANT_A, kitchen_id=kitchen.id, date="2026-04-01"
    )
    assert dashboard.production_order_summary["in_progress"] == 2
    assert dashboard.production_order_summary["pending"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  9. 需求预测（工作日 vs 周末权重）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_forecast_weekend_applies_weight(svc):
    """周末日期应用 1.3 权重"""
    kitchen = await _make_kitchen(svc)
    # 注入近30天内的历史数据（使用工作日日期 2026-03-01 ~ 2026-03-10）
    for i in range(1, 11):
        _inject_consumption(TENANT_A, STORE_ID, DISH_ID_1, f"2026-03-{i:02d}", 100.0)

    # 2026-04-05 是周六
    forecast = await svc.forecast_demand(
        tenant_id=TENANT_A, kitchen_id=kitchen.id, target_date="2026-04-05"
    )
    assert forecast.is_weekend is True
    assert len(forecast.dishes) == 1
    dish = forecast.dishes[0]
    # avg = 100, suggested = 100 * 1.3 = 130
    assert dish.suggested_qty == pytest.approx(130.0, rel=0.01)
    assert dish.weekend_adjusted is True


@pytest.mark.asyncio
async def test_forecast_weekday_no_weight(svc):
    """工作日不应用周末权重"""
    kitchen = await _make_kitchen(svc)
    for i in range(1, 11):
        _inject_consumption(TENANT_A, STORE_ID, DISH_ID_1, f"2026-03-{i:02d}", 100.0)

    # 2026-04-01 是周三
    forecast = await svc.forecast_demand(
        tenant_id=TENANT_A, kitchen_id=kitchen.id, target_date="2026-04-01"
    )
    assert forecast.is_weekend is False
    dish = forecast.dishes[0]
    assert dish.suggested_qty == pytest.approx(100.0, rel=0.01)
    assert dish.weekend_adjusted is False


@pytest.mark.asyncio
async def test_forecast_no_history_returns_empty(svc):
    """无历史记录时返回空预测列表"""
    kitchen = await _make_kitchen(svc)
    forecast = await svc.forecast_demand(
        tenant_id=TENANT_A, kitchen_id=kitchen.id, target_date="2026-04-01"
    )
    assert forecast.dishes == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  10. 跨租户隔离
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_cross_tenant_plan_access_raises(svc):
    kitchen = await _make_kitchen(svc)
    plan = await _make_confirmed_plan(svc, kitchen.id)
    with pytest.raises(ValueError, match="不属于当前租户"):
        await svc.get_production_plan(tenant_id=TENANT_B, plan_id=plan.id)


@pytest.mark.asyncio
async def test_cross_tenant_confirm_raises(svc):
    kitchen = await _make_kitchen(svc)
    plan = await svc.create_production_plan(
        tenant_id=TENANT_A,
        kitchen_id=kitchen.id,
        plan_date="2026-04-01",
        items=SAMPLE_ITEMS,
    )
    with pytest.raises(ValueError, match="不属于当前租户"):
        await svc.confirm_production_plan(
            tenant_id=TENANT_B, plan_id=plan.id, operator_id=OPERATOR
        )


@pytest.mark.asyncio
async def test_cross_tenant_start_production_raises(svc):
    kitchen = await _make_kitchen(svc)
    plan = await _make_confirmed_plan(svc, kitchen.id)
    with pytest.raises(ValueError, match="不属于当前租户"):
        await svc.start_production(tenant_id=TENANT_B, plan_id=plan.id)


@pytest.mark.asyncio
async def test_cross_tenant_distribution_raises(svc):
    kitchen = await _make_kitchen(svc)
    dispatched = await _make_dispatched_order(svc, kitchen.id)
    # 已经 dispatched，再次 dispatch 应报告"只有 pending 状态可标记发出"
    # 用 TENANT_B 尝试，应报告"不属于当前租户"
    order = await svc.create_distribution_order(
        tenant_id=TENANT_A,
        kitchen_id=kitchen.id,
        store_id=STORE_ID,
        items=[{"dish_id": DISH_ID_1, "dish_name": "红烧肉", "quantity": 10.0, "unit": "份"}],
        scheduled_at="2026-04-01T11:00:00Z",
    )
    with pytest.raises(ValueError, match="不属于当前租户"):
        await svc.mark_dispatched(tenant_id=TENANT_B, order_id=order.id)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  11. 非法状态流转
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_complete_already_completed_order_raises(svc):
    kitchen = await _make_kitchen(svc)
    plan = await _make_confirmed_plan(svc, kitchen.id)
    orders = await svc.list_production_orders(tenant_id=TENANT_A, plan_id=plan.id)
    order_id = orders["items"][0]["id"]

    await svc.complete_production_order(
        tenant_id=TENANT_A, order_id=order_id, actual_qty=50.0
    )
    with pytest.raises(ValueError, match="已处于 completed 状态"):
        await svc.complete_production_order(
            tenant_id=TENANT_A, order_id=order_id, actual_qty=50.0
        )


@pytest.mark.asyncio
async def test_dispatch_non_pending_order_raises(svc):
    """已 dispatched 的配送单不可再次 dispatch"""
    kitchen = await _make_kitchen(svc)
    dispatched = await _make_dispatched_order(svc, kitchen.id)
    with pytest.raises(ValueError, match="只有 pending 状态可标记发出"):
        await svc.mark_dispatched(tenant_id=TENANT_A, order_id=dispatched.id)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  12. 空菜品清单 → 自动使用需求预测填充
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_create_plan_empty_items_uses_forecast(svc):
    """空 items 时自动从需求预测生成菜品清单"""
    kitchen = await _make_kitchen(svc)
    # 注入历史消耗数据
    _inject_consumption(TENANT_A, STORE_ID, DISH_ID_1, "2026-03-01", 80.0)
    _inject_consumption(TENANT_A, STORE_ID, DISH_ID_1, "2026-03-02", 100.0)

    plan = await svc.create_production_plan(
        tenant_id=TENANT_A,
        kitchen_id=kitchen.id,
        plan_date="2026-04-01",
        items=[],  # 空清单
        created_by=OPERATOR,
    )
    # 预测有数据，应自动填充
    assert len(plan.items) > 0
    assert plan.items[0]["dish_id"] == DISH_ID_1


@pytest.mark.asyncio
async def test_create_plan_empty_items_no_history_stays_empty(svc):
    """空 items + 无历史记录时，items 仍为空（不报错）"""
    kitchen = await _make_kitchen(svc)
    plan = await svc.create_production_plan(
        tenant_id=TENANT_A,
        kitchen_id=kitchen.id,
        plan_date="2026-04-01",
        items=[],
    )
    assert plan.items == []
    assert plan.status == "draft"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  额外：列表接口分页与过滤
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_list_plans_filter_by_status(svc):
    """状态过滤：只返回指定状态的计划"""
    kitchen = await _make_kitchen(svc)
    plan = await svc.create_production_plan(
        tenant_id=TENANT_A,
        kitchen_id=kitchen.id,
        plan_date="2026-04-01",
        items=SAMPLE_ITEMS,
    )
    await svc.confirm_production_plan(
        tenant_id=TENANT_A, plan_id=plan.id, operator_id=OPERATOR
    )

    drafts = await svc.list_production_plans(tenant_id=TENANT_A, status="draft")
    confirmed = await svc.list_production_plans(tenant_id=TENANT_A, status="confirmed")

    assert drafts["total"] == 0
    assert confirmed["total"] == 1


@pytest.mark.asyncio
async def test_list_kitchens_tenant_isolation(svc):
    """list_kitchens 只返回当前租户的厨房"""
    await svc.create_kitchen(tenant_id=TENANT_A, name="A厨房")
    await svc.create_kitchen(tenant_id=TENANT_B, name="B厨房")

    a_kitchens = await svc.list_kitchens(tenant_id=TENANT_A)
    b_kitchens = await svc.list_kitchens(tenant_id=TENANT_B)

    assert len(a_kitchens) == 1
    assert a_kitchens[0].name == "A厨房"
    assert len(b_kitchens) == 1
    assert b_kitchens[0].name == "B厨房"
