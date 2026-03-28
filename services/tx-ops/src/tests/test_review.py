"""D8 复盘与经营改进中心 — 测试套件

覆盖周复盘、月复盘、问题追踪（含状态机和红黄绿）、知识库。
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from ..services.issue_tracker import (
    assign_issue,
    create_issue,
    cross_store_benchmark,
    get_regional_issues,
    get_store_issue_board,
    update_issue_status,
)
from ..services.knowledge_base import (
    get_best_practices,
    get_sop_suggestions,
    save_case,
    search_cases,
)
from ..services.monthly_review import generate_monthly_review, generate_regional_review
from ..services.weekly_review import aggregate_weekly_from_daily, generate_weekly_review

TENANT = "tenant_test_001"
STORE = "store_001"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助：构造日复盘数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _make_daily_review(
    day: str,
    revenue: int = 100000,
    orders: int = 50,
    cost: int = 40000,
    waste: int = 2000,
    exceptions: list | None = None,
    action_items: list | None = None,
) -> dict:
    margin_pct = round((revenue - cost) / revenue * 100, 2) if revenue > 0 else 0.0
    return {
        "date": day,
        "revenue_summary": {
            "total_revenue_fen": revenue,
            "order_count": orders,
        },
        "cost_summary": {
            "total_cost_fen": cost,
            "waste_cost_fen": waste,
        },
        "margin_summary": {
            "gross_margin_pct": margin_pct,
        },
        "exception_list": exceptions or [],
        "action_items": action_items or [],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 周复盘 — 日数据聚合
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_aggregate_weekly_from_daily():
    reviews = [
        _make_daily_review("2026-03-23", revenue=100000, orders=50, cost=40000, waste=2000),
        _make_daily_review("2026-03-24", revenue=120000, orders=60, cost=50000, waste=3000),
    ]
    result = aggregate_weekly_from_daily(STORE, reviews)

    assert result["total_revenue_fen"] == 220000
    assert result["total_orders"] == 110
    assert result["total_waste_fen"] == 5000
    assert result["day_count"] == 2
    assert len(result["daily_trend"]) == 2
    assert result["gross_profit_fen"] == 220000 - 90000


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 周复盘 — 完整生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_generate_weekly_review():
    daily = [
        _make_daily_review(
            f"2026-03-{23 + i}",
            revenue=100000 + i * 10000,
            orders=50 + i * 5,
            cost=40000 + i * 3000,
            waste=1000 + i * 200,
            exceptions=[{"type": "food_safety", "summary": "温度异常", "impact_fen": 500}]
            if i % 2 == 0 else [],
        )
        for i in range(7)
    ]

    result = await generate_weekly_review(
        store_id=STORE,
        week_start=date(2026, 3, 23),
        tenant_id=TENANT,
        db=None,
        daily_reviews=daily,
    )

    assert result["store_id"] == STORE
    assert result["tenant_id"] == TENANT
    assert result["status"] == "draft"
    assert "week_summary" in result
    assert "vs_last_week" in result
    assert isinstance(result["top_issues"], list)
    assert isinstance(result["improvement_actions"], list)
    assert isinstance(result["highlights"], list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 月度复盘
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_generate_monthly_review():
    weeks = [
        {
            "week_start": f"2026-03-{2 + i * 7:02d}",
            "week_summary": {
                "total_revenue_fen": 700000 + i * 50000,
                "total_orders": 350 + i * 20,
                "total_cost_fen": 280000 + i * 15000,
                "total_waste_fen": 10000 + i * 1000,
                "avg_margin_pct": 60.0 - i,
            },
        }
        for i in range(4)
    ]

    result = await generate_monthly_review(
        store_id=STORE,
        month="2026-03",
        tenant_id=TENANT,
        db=None,
        weekly_reviews=weeks,
        targets={"revenue_target_fen": 3000000, "orders_target": 1500, "margin_target_pct": 55.0},
    )

    assert result["month"] == "2026-03"
    assert result["month_summary"]["total_revenue_fen"] > 0
    assert "trend_analysis" in result
    assert "target_achievement" in result
    assert "cost_analysis" in result
    assert "action_plan" in result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 问题生命周期（状态机）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_issue_lifecycle():
    # 创建
    issue = await create_issue(
        store_id=STORE,
        issue_type="food_safety",
        description="冰箱温度超标",
        reporter_id="user_001",
        tenant_id=TENANT,
        db=None,
        priority="high",
        deadline="2026-03-30",
    )
    assert issue["status"] == "open"
    assert issue["type"] == "food_safety"

    # 派发
    await assign_issue(
        issue_id=issue["issue_id"],
        assignee_id="user_002",
        deadline="2026-03-30",
        tenant_id=TENANT,
        db=None,
        issue=issue,
    )
    assert issue["status"] == "assigned"
    assert issue["assignee_id"] == "user_002"

    # 进入处理中
    await update_issue_status(
        issue_id=issue["issue_id"],
        status="in_progress",
        notes="已安排维修",
        tenant_id=TENANT,
        db=None,
        issue=issue,
    )
    assert issue["status"] == "in_progress"

    # 解决
    await update_issue_status(
        issue_id=issue["issue_id"],
        status="resolved",
        notes="冰箱已修复",
        tenant_id=TENANT,
        db=None,
        issue=issue,
    )
    assert issue["status"] == "resolved"

    # 验证
    await update_issue_status(
        issue_id=issue["issue_id"],
        status="verified",
        notes="验证通过",
        tenant_id=TENANT,
        db=None,
        issue=issue,
    )
    assert issue["status"] == "verified"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 问题状态机 — 非法转换
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_issue_invalid_transition():
    issue = await create_issue(
        store_id=STORE,
        issue_type="cost",
        description="食材成本超标",
        reporter_id="user_001",
        tenant_id=TENANT,
        db=None,
    )

    # open 不能直接到 resolved
    with pytest.raises(ValueError, match="Cannot transition"):
        await update_issue_status(
            issue_id=issue["issue_id"],
            status="resolved",
            notes="尝试跳过",
            tenant_id=TENANT,
            db=None,
            issue=issue,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 红黄绿看板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_issue_board_colors():
    today = date(2026, 3, 27)

    issues = [
        # 红色：已过期
        {"issue_id": "i1", "status": "in_progress", "deadline": "2026-03-25"},
        # 黄色：还有2天
        {"issue_id": "i2", "status": "assigned", "deadline": "2026-03-29"},
        # 绿色：还有7天
        {"issue_id": "i3", "status": "open", "deadline": "2026-04-03"},
        # 绿色：已解决
        {"issue_id": "i4", "status": "resolved", "deadline": "2026-03-20"},
    ]

    board = await get_store_issue_board(
        store_id=STORE,
        tenant_id=TENANT,
        db=None,
        issues=issues,
        today=today,
    )

    assert board["summary"]["red_count"] == 1
    assert board["summary"]["yellow_count"] == 1
    assert board["summary"]["green_count"] == 2
    assert board["red"][0]["issue_id"] == "i1"
    assert board["yellow"][0]["issue_id"] == "i2"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 知识库 — 案例保存与搜索
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_case_save_and_search():
    case = await save_case(
        store_id=STORE,
        case_data={
            "title": "冰箱温度管理改进",
            "category": "food_safety",
            "problem": "夏季冰箱温度频繁超标",
            "solution": "增加温度巡检频次并安装自动报警器",
            "result": "异常次数下降80%",
            "tags": ["food_safety", "equipment"],
            "author_id": "user_001",
        },
        tenant_id=TENANT,
        db=None,
    )

    assert case["case_id"].startswith("case_")
    assert case["category"] == "food_safety"

    # 搜索
    result = await search_cases(
        keyword="冰箱",
        tenant_id=TENANT,
        db=None,
        cases=[case],
    )
    assert result["total"] == 1
    assert result["results"][0]["case_id"] == case["case_id"]

    # 搜索不到
    result2 = await search_cases(
        keyword="不存在的关键词",
        tenant_id=TENANT,
        db=None,
        cases=[case],
    )
    assert result2["total"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. SOP 建议
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_sop_suggestions():
    result = await get_sop_suggestions(
        store_id=STORE,
        issue_type="food_safety",
        tenant_id=TENANT,
        db=None,
    )

    assert result["issue_type"] == "food_safety"
    assert len(result["suggestions"]) >= 1
    assert "steps" in result["suggestions"][0]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  9. 跨店对标
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_cross_store_benchmark():
    result = await cross_store_benchmark(
        issue_type="food_safety",
        tenant_id=TENANT,
        db=None,
        store_issue_counts={"store_001": 5, "store_002": 2, "store_003": 8},
    )

    assert result["issue_type"] == "food_safety"
    assert result["benchmark"]["total_stores"] == 3
    assert result["benchmark"]["max_count"] == 8
    assert result["benchmark"]["min_count"] == 2
    assert result["stores"][0]["store_id"] == "store_003"  # 最多的排第一


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  10. 区域复盘
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_generate_regional_review():
    store_reviews = [
        {
            "store_id": f"store_{i:03d}",
            "month_summary": {
                "store_id": f"store_{i:03d}",
                "total_revenue_fen": 2000000 + i * 100000,
                "total_orders": 1000 + i * 50,
                "total_cost_fen": 800000 + i * 30000,
                "gross_margin_pct": 60.0 + i,
            },
            "action_plan": [{"type": "cost", "priority": "high"}] if i < 2 else [],
        }
        for i in range(3)
    ]

    result = await generate_regional_review(
        region_id="region_001",
        month="2026-03",
        tenant_id=TENANT,
        db=None,
        store_reviews=store_reviews,
    )

    assert result["region_id"] == "region_001"
    assert result["region_summary"]["store_count"] == 3
    assert result["region_summary"]["total_revenue_fen"] > 0
    assert len(result["store_ranking"]) == 3
    assert result["store_ranking"][0]["rank"] == 1
    # store_002 有最高营收，应排第一
    assert result["store_ranking"][0]["store_id"] == "store_002"
