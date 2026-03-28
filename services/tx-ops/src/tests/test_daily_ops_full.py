"""日清日结操作层完整测试 — E1/E2/E4/E5/E7

覆盖: store_opening, cruise_monitor, store_closing, daily_review, exception_workflow
"""
from __future__ import annotations

import pytest
from datetime import date, datetime, timedelta

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  E1 开店准备
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_create_opening_checklist():
    """E1: 生成开店检查单，应包含 E1 模板的所有检查项。"""
    from services.tx_ops.src.services.store_opening import create_opening_checklist

    checklist = await create_opening_checklist(
        store_id="store_001",
        date_=date(2026, 3, 27),
        tenant_id="tenant_001",
        db=None,
        template_key="xuji_seafood",
    )

    assert checklist["store_id"] == "store_001"
    assert checklist["tenant_id"] == "tenant_001"
    assert checklist["node_code"] == "E1"
    assert checklist["status"] == "pending"
    assert len(checklist["items"]) == 8  # xuji_seafood E1 has 8 items
    # 每项都有唯一 item_id
    item_ids = [i["item_id"] for i in checklist["items"]]
    assert len(set(item_ids)) == len(item_ids)


@pytest.mark.asyncio
async def test_check_item_pass():
    """E1: 打勾一项检查，状态应正确更新。"""
    from services.tx_ops.src.services.store_opening import (
        create_opening_checklist,
        check_item,
    )

    checklist = await create_opening_checklist(
        "store_001", date(2026, 3, 27), "tenant_001", db=None,
    )
    first_item = checklist["items"][0]

    result = await check_item(
        checklist["checklist_id"],
        first_item["item_id"],
        status="checked",
        operator_id="op_001",
        db=None,
        result="pass",
        tenant_id="tenant_001",
        checklist=checklist,
    )

    assert result["status"] == "checked"
    assert result["result"] == "pass"
    assert result["checked_by"] == "op_001"
    assert result["checked_at"] is not None


@pytest.mark.asyncio
async def test_opening_status_can_open():
    """E1: 所有必填项通过后 can_open 应为 True。"""
    from services.tx_ops.src.services.store_opening import (
        create_opening_checklist,
        get_opening_status,
    )

    checklist = await create_opening_checklist(
        "store_001", date(2026, 3, 27), "tenant_001", db=None,
    )

    # 将所有项设为已检查通过
    for item in checklist["items"]:
        item["status"] = "checked"
        item["result"] = "pass"

    status = get_opening_status("store_001", date(2026, 3, 27), "tenant_001", db=None, checklist=checklist)

    assert status["can_open"] is True
    assert status["blocked"] == 0
    assert status["checked"] == status["total"]


@pytest.mark.asyncio
async def test_opening_status_blocked():
    """E1: 必填项失败时 can_open 应为 False。"""
    from services.tx_ops.src.services.store_opening import (
        create_opening_checklist,
        get_opening_status,
    )

    checklist = await create_opening_checklist(
        "store_001", date(2026, 3, 27), "tenant_001", db=None,
    )

    # 第一项(required=True)设为 fail，其余 pass
    for item in checklist["items"]:
        item["status"] = "checked"
        item["result"] = "pass"
    checklist["items"][0]["result"] = "fail"

    status = get_opening_status("store_001", date(2026, 3, 27), "tenant_001", db=None, checklist=checklist)

    assert status["can_open"] is False
    assert status["blocked"] >= 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  E2 营业巡航
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_table_cruise_overtime_alert():
    """E2: 桌台超时未结账应触发告警。"""
    from services.tx_ops.src.services.cruise_monitor import check_table_cruise

    tables = [
        {
            "table_id": "T01",
            "status": "occupied",
            "occupied_since": (datetime.utcnow() - timedelta(hours=3)).isoformat(),
        },
    ]

    alerts = await check_table_cruise(
        "store_001", "tenant_001", db=None, tables=tables,
    )

    assert len(alerts) == 1
    assert alerts[0]["alert_type"] == "table_overtime"
    assert alerts[0]["table_id"] == "T01"


@pytest.mark.asyncio
async def test_cooking_cruise_backlog_alert():
    """E2: 出餐堆积应触发 critical 告警。"""
    from services.tx_ops.src.services.cruise_monitor import check_cooking_cruise

    orders = [{"order_id": f"ord_{i}", "created_at": datetime.utcnow().isoformat()} for i in range(20)]

    alerts = await check_cooking_cruise(
        "store_001", "tenant_001", db=None, orders=orders,
    )

    backlog_alerts = [a for a in alerts if a["alert_type"] == "cooking_backlog"]
    assert len(backlog_alerts) == 1
    assert backlog_alerts[0]["level"] == "critical"
    assert backlog_alerts[0]["pending_count"] == 20


@pytest.mark.asyncio
async def test_stockout_cruise_alerts():
    """E2: 已沽清菜品应触发 critical，低余量应触发 warning。"""
    from services.tx_ops.src.services.cruise_monitor import check_stockout_cruise

    dishes = [
        {"dish_id": "d1", "name": "清蒸鲈鱼", "remaining_qty": 0, "daily_avg_sales": 10},
        {"dish_id": "d2", "name": "蒜蓉龙虾", "remaining_qty": 2, "daily_avg_sales": 10},
    ]

    alerts = await check_stockout_cruise(
        "store_001", "tenant_001", db=None, dishes=dishes,
    )

    assert len(alerts) == 2
    stockout = [a for a in alerts if a["alert_type"] == "stockout_new"]
    risk = [a for a in alerts if a["alert_type"] == "stockout_risk"]
    assert len(stockout) == 1
    assert stockout[0]["level"] == "critical"
    assert len(risk) == 1
    assert risk[0]["level"] == "warning"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  E4 异常处置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_exception_report_and_escalate():
    """E4: 上报异常并升级，状态和层级应正确变更。"""
    from services.tx_ops.src.services.exception_workflow import (
        report_exception,
        escalate_exception,
    )

    exc = await report_exception(
        "store_001", "complaint", {"description": "菜品有异物"},
        "reporter_001", "tenant_001", db=None,
    )

    assert exc["type"] == "complaint"
    assert exc["status"] == "pending"
    assert exc["level"] == 1

    result = await escalate_exception(
        exc["exception_id"], to_level=2, tenant_id="tenant_001",
        db=None, exception=exc,
    )

    assert result["escalated"] is True
    assert result["to_level"] == 2
    assert exc["status"] == "escalated"


@pytest.mark.asyncio
async def test_exception_resolve():
    """E4: 异常解决后状态应为 executed。"""
    from services.tx_ops.src.services.exception_workflow import (
        report_exception,
        resolve_exception,
    )

    exc = await report_exception(
        "store_001", "equipment", {"description": "打印机卡纸"},
        "reporter_001", "tenant_001", db=None,
    )

    result = await resolve_exception(
        exc["exception_id"],
        resolution={"action_taken": "更换色带", "root_cause": "色带耗尽"},
        resolver_id="mgr_001",
        tenant_id="tenant_001",
        db=None,
        exception=exc,
    )

    assert result["resolved"] is True
    assert result["status"] == "executed"


@pytest.mark.asyncio
async def test_food_safety_auto_escalation():
    """E4: 食安异常应自动升级到区域经理级别(level 3)。"""
    from services.tx_ops.src.services.exception_workflow import report_exception

    exc = await report_exception(
        "store_001", "food_safety", {"description": "食材过期"},
        "reporter_001", "tenant_001", db=None,
    )

    assert exc["level"] == 3  # 区域经理
    assert exc["type"] == "food_safety"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  E5 闭店盘点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_closing_stocktake_variance():
    """E5: 原料盘点应正确计算差异。"""
    from services.tx_ops.src.services.store_closing import record_closing_stocktake

    items = [
        {"ingredient_id": "ing_001", "name": "三文鱼", "expected_qty": 10.0, "actual_qty": 9.5, "unit": "kg"},
        {"ingredient_id": "ing_002", "name": "鲈鱼", "expected_qty": 5.0, "actual_qty": 5.0, "unit": "条"},
    ]

    result = await record_closing_stocktake("store_001", items, "tenant_001", db=None)

    assert result["item_count"] == 2
    assert result["variance_count"] == 1  # 三文鱼有差异
    # 三文鱼差异: -0.5
    salmon = result["items"][0]
    assert salmon["variance"] == -0.5
    assert salmon["has_variance"] is True


@pytest.mark.asyncio
async def test_waste_report_total_cost():
    """E5: 损耗上报应正确计算总成本。"""
    from services.tx_ops.src.services.store_closing import record_waste_report

    waste = [
        {"ingredient_id": "i1", "name": "死虾", "qty": 2, "unit": "kg", "reason": "死损", "cost_fen": 8000},
        {"ingredient_id": "i2", "name": "变色蔬菜", "qty": 1, "unit": "kg", "reason": "过期", "cost_fen": 500},
    ]

    result = await record_waste_report("store_001", waste, "tenant_001", db=None)

    assert result["total_cost_fen"] == 8500
    assert result["item_count"] == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  E7 店长复盘
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_generate_daily_review_with_suggestions():
    """E7: 营收达成率低时应自动生成行动项建议。"""
    from services.tx_ops.src.services.daily_review import generate_daily_review

    review = await generate_daily_review(
        "store_001",
        date(2026, 3, 27),
        "tenant_001",
        db=None,
        revenue_data={
            "total_revenue_fen": 500000,
            "target_revenue_fen": 1000000,
            "order_count": 50,
        },
        cost_data={
            "total_cost_fen": 250000,
            "food_cost_fen": 220000,
        },
    )

    assert review["store_id"] == "store_001"
    assert review["revenue_summary"]["achievement_pct"] == 50.0
    assert review["margin_summary"]["gross_profit_fen"] == 250000

    # 营收达成率50% < 80%，应生成 revenue 建议
    revenue_actions = [a for a in review["action_items"] if a["type"] == "revenue"]
    assert len(revenue_actions) >= 1

    # 食材成本率 220000/500000 = 44% > 40%, 应生成 cost 建议
    cost_actions = [a for a in review["action_items"] if a["type"] == "cost"]
    assert len(cost_actions) >= 1


@pytest.mark.asyncio
async def test_submit_action_items():
    """E7: 提交行动项应返回正确数量。"""
    from services.tx_ops.src.services.daily_review import submit_action_items

    items = [
        {"title": "检查三文鱼供应商报价", "assignee_id": "chef_001", "priority": "high"},
        {"title": "优化出餐动线", "assignee_id": "mgr_001", "priority": "medium"},
    ]

    result = await submit_action_items(
        "store_001", items, "mgr_001", "tenant_001", db=None,
    )

    assert result["submitted_count"] == 2
    assert len(result["items"]) == 2
    assert result["items"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_sign_off_review():
    """E7: 店长签发后状态应变为 signed_off。"""
    from services.tx_ops.src.services.daily_review import (
        generate_daily_review,
        sign_off_review,
    )

    review = await generate_daily_review(
        "store_001", date(2026, 3, 27), "tenant_001", db=None,
    )
    assert review["status"] == "draft"

    result = await sign_off_review(
        "store_001", date(2026, 3, 27), "mgr_001", "tenant_001",
        db=None, review=review,
    )

    assert result["signed_off"] is True
    assert review["status"] == "signed_off"


@pytest.mark.asyncio
async def test_sign_off_review_already_signed():
    """E7: 已签发的复盘不能重复签发。"""
    from services.tx_ops.src.services.daily_review import (
        generate_daily_review,
        sign_off_review,
    )

    review = await generate_daily_review(
        "store_001", date(2026, 3, 27), "tenant_001", db=None,
    )
    review["status"] = "signed_off"

    with pytest.raises(ValueError, match="already signed off"):
        await sign_off_review(
            "store_001", date(2026, 3, 27), "mgr_001", "tenant_001",
            db=None, review=review,
        )
