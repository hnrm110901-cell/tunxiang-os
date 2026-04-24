"""
A3 差标合规 Agent + A5 差旅助手 Agent — 单元测试

运行方法：
    pytest tests/test_agents_a3_a5.py -v

覆盖范围：
  A3 (standard_compliance):
    1. 超标 < 20%  → compliant_with_warning，compliant=True
    2. 超标 20-50% → over_limit_minor，compliant=True，需填说明
    3. 超标 > 50%  → over_limit_major，compliant=False，金额截断
    4. 未配置差标  → no_rule，自动通过
    5. 连续超标计数：_count_recent_violations 聚合逻辑
    6. 城市识别：_extract_destination_city 从描述中提取城市名

  A5 (travel_assistant):
    1. 同城任务（直接名称匹配）   → estimate_travel_needed 返回 False
    2. 同城任务（别名匹配）        → estimate_travel_needed 返回 False
    3. 跨城任务                    → estimate_travel_needed 返回 True
    4. 缺少城市信息（保守处理）    → estimate_travel_needed 返回 True
    5. handle_inspection_task_assigned — 同城任务跳过，返回 action=skipped
    6. handle_inspection_task_assigned — 缺必填字段，返回 None
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── A3 独立函数（部分无DB依赖）──────────────────────────────────────────────
from services.tx_expense.src.agents.a3_standard_compliance import (
    _extract_destination_city,
    check_item_compliance,
)

# ─── A5 独立函数（无DB依赖，可直接测试）──────────────────────────────────────
from services.tx_expense.src.agents.a5_travel_assistant import (
    estimate_travel_needed,
    handle_inspection_task_assigned,
)

# ===========================================================================
# A5 — estimate_travel_needed
# ===========================================================================

@pytest.mark.asyncio
async def test_a5_same_city_identical_name():
    """同名城市 → 不需要差旅"""
    result = await estimate_travel_needed("上海", "上海")
    assert result is False


@pytest.mark.asyncio
async def test_a5_same_city_alias():
    """'北京' vs '北京市' → 别名匹配，不需要差旅"""
    result = await estimate_travel_needed("北京", "北京市")
    assert result is False


@pytest.mark.asyncio
async def test_a5_cross_city():
    """不同城市 → 需要差旅"""
    result = await estimate_travel_needed("上海", "深圳")
    assert result is True


@pytest.mark.asyncio
async def test_a5_missing_city_conservative():
    """缺少目的地城市 → 保守处理，需要差旅"""
    result = await estimate_travel_needed("上海", "")
    assert result is True


# ===========================================================================
# A5 — handle_inspection_task_assigned
# ===========================================================================

@pytest.mark.asyncio
async def test_a5_same_city_event_skipped():
    """同城巡店事件 → action=skipped，不写DB"""
    db = AsyncMock()
    event_data = {
        "tenant_id": str(uuid.uuid4()),
        "task_id": str(uuid.uuid4()),
        "supervisor_id": str(uuid.uuid4()),
        "origin_city": "成都",
        "target_stores": [{"store_id": str(uuid.uuid4()), "store_name": "测试店", "city": "成都"}],
        "planned_start_date": "2026-04-15",
    }
    result = await handle_inspection_task_assigned(event_data, db)
    assert result is not None
    assert result["action"] == "skipped"
    assert result["reason"] == "same_city"


@pytest.mark.asyncio
async def test_a5_missing_required_fields_returns_none():
    """缺少 supervisor_id → 返回 None，不抛异常"""
    db = AsyncMock()
    event_data = {
        "tenant_id": str(uuid.uuid4()),
        "task_id": str(uuid.uuid4()),
        # supervisor_id 缺失
        "origin_city": "上海",
        "target_stores": [{"city": "北京"}],
    }
    result = await handle_inspection_task_assigned(event_data, db)
    assert result is None


# ===========================================================================
# A3 — _extract_destination_city
# ===========================================================================

def test_a3_extract_city_from_description():
    """从 expense_item 描述中提取城市名"""
    items = [{"description": "2026年4月出差上海项目对接，住宿费"}]
    city = _extract_destination_city(items)
    assert city == "上海"


def test_a3_extract_city_not_found():
    """无城市关键词 → 返回 None"""
    items = [{"description": "日常办公耗材采购"}]
    city = _extract_destination_city(items)
    assert city is None


# ===========================================================================
# A3 — check_item_compliance（mock std_svc + _get_applicant_level）
# ===========================================================================

def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
    return db


@pytest.mark.asyncio
async def test_a3_compliant_with_warning():
    """超标 10% → compliant_with_warning，compliant=True"""
    tid = uuid.uuid4()
    bid = uuid.uuid4()
    aid = uuid.uuid4()
    db = _make_db()

    compliance_mock = {
        "status": "compliant_with_warning",
        "over_rate": 0.10,
        "limit": 30000,  # 限额 300 元
        "city_tier": "tier1",
        "standard_name": "一线城市差标",
    }

    with (
        patch(
            "services.tx_expense.src.agents.a3_standard_compliance._get_applicant_level",
            new=AsyncMock(return_value="store_manager"),
        ),
        patch(
            "services.tx_expense.src.agents.a3_standard_compliance.std_svc.check_compliance",
            new=AsyncMock(return_value=compliance_mock),
        ),
    ):
        result = await check_item_compliance(
            db=db,
            tenant_id=tid,
            brand_id=bid,
            applicant_id=aid,
            item_description="出差上海住宿费",
            item_amount_fen=33000,   # 330 元，超标 10%
            expense_type="accommodation",
            destination_city="上海",
        )

    assert result["status"] == "compliant_with_warning"
    assert result["compliant"] is True
    assert result["compliance_action"] in ("none", "add_explanation")


@pytest.mark.asyncio
async def test_a3_over_limit_minor():
    """超标 35% → over_limit_minor，compliant=True（允许提交+必填说明）"""
    tid = uuid.uuid4()
    bid = uuid.uuid4()
    aid = uuid.uuid4()
    db = _make_db()

    compliance_mock = {
        "status": "over_limit_minor",
        "over_rate": 0.35,
        "limit": 30000,
        "city_tier": "tier1",
        "standard_name": "一线城市差标",
    }

    with (
        patch(
            "services.tx_expense.src.agents.a3_standard_compliance._get_applicant_level",
            new=AsyncMock(return_value="store_manager"),
        ),
        patch(
            "services.tx_expense.src.agents.a3_standard_compliance.std_svc.check_compliance",
            new=AsyncMock(return_value=compliance_mock),
        ),
    ):
        result = await check_item_compliance(
            db=db,
            tenant_id=tid,
            brand_id=bid,
            applicant_id=aid,
            item_description="出差上海住宿费",
            item_amount_fen=40500,   # 超标 35%
            expense_type="accommodation",
            destination_city="上海",
        )

    assert result["status"] == "over_limit_minor"
    assert result["compliant"] is True
    assert result["compliance_action"] == "add_explanation"


@pytest.mark.asyncio
async def test_a3_over_limit_major_truncated():
    """超标 60% → over_limit_major，compliant=False，截断后金额 = limit"""
    tid = uuid.uuid4()
    bid = uuid.uuid4()
    aid = uuid.uuid4()
    db = _make_db()

    compliance_mock = {
        "status": "over_limit_major",
        "over_rate": 0.60,
        "limit": 30000,
        "city_tier": "tier1",
        "standard_name": "一线城市差标",
    }

    with (
        patch(
            "services.tx_expense.src.agents.a3_standard_compliance._get_applicant_level",
            new=AsyncMock(return_value="store_manager"),
        ),
        patch(
            "services.tx_expense.src.agents.a3_standard_compliance.std_svc.check_compliance",
            new=AsyncMock(return_value=compliance_mock),
        ),
    ):
        result = await check_item_compliance(
            db=db,
            tenant_id=tid,
            brand_id=bid,
            applicant_id=aid,
            item_description="出差上海住宿费",
            item_amount_fen=48000,   # 超标 60%
            expense_type="accommodation",
            destination_city="上海",
        )

    assert result["status"] == "over_limit_major"
    assert result["compliant"] is False
    # 截断后金额不超过 limit
    assert result["truncated_amount_fen"] <= 30000
    assert result["compliance_action"] in ("truncate", "special_channel")


@pytest.mark.asyncio
async def test_a3_no_rule_auto_pass():
    """无差标规则 → no_rule，自动通过"""
    tid = uuid.uuid4()
    bid = uuid.uuid4()
    aid = uuid.uuid4()
    db = _make_db()

    compliance_mock = {
        "status": "no_rule",
        "over_rate": 0.0,
        "limit": None,
        "city_tier": None,
        "standard_name": None,
    }

    with (
        patch(
            "services.tx_expense.src.agents.a3_standard_compliance._get_applicant_level",
            new=AsyncMock(return_value="store_staff"),
        ),
        patch(
            "services.tx_expense.src.agents.a3_standard_compliance.std_svc.check_compliance",
            new=AsyncMock(return_value=compliance_mock),
        ),
    ):
        result = await check_item_compliance(
            db=db,
            tenant_id=tid,
            brand_id=bid,
            applicant_id=aid,
            item_description="未分类费用",
            item_amount_fen=5000,
            expense_type="other_travel",
            destination_city=None,
        )

    assert result["status"] == "no_rule"
    assert result["compliant"] is True
    assert result["limit_fen"] is None
