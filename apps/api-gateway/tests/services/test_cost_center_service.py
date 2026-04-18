"""
成本中心服务 — 单元测试
覆盖:
  1) 分摊比例和 != 100% 校验
  2) 非法分类校验
  3) 单一成本中心分配 (100%)
  4) 多成本中心分摊 (60+40)
  5) aggregate_by_category 汇总逻辑 (mock db)
"""

import sys
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.services.cost_center_service import (  # noqa: E402
    ALLOWED_CATEGORIES,
    CostCenterService,
)


def _mk_db():
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_create_cost_center_invalid_category():
    svc = CostCenterService(_mk_db())
    with pytest.raises(ValueError):
        await svc.create_cost_center(code="X1", name="不合法", category="非法分类")


@pytest.mark.asyncio
async def test_create_cost_center_valid_category():
    svc = CostCenterService(_mk_db())
    for cat in ALLOWED_CATEGORIES:
        cc = await svc.create_cost_center(code=f"CC_{cat}", name=cat, category=cat)
        assert cc.category == cat


@pytest.mark.asyncio
async def test_assign_employee_pct_not_100():
    svc = CostCenterService(_mk_db())
    with pytest.raises(ValueError, match="100"):
        await svc.assign_employee(
            employee_id="E1",
            allocations=[
                {"cost_center_id": uuid.uuid4(), "allocation_pct": 60, "effective_from": date.today()},
                {"cost_center_id": uuid.uuid4(), "allocation_pct": 30, "effective_from": date.today()},
            ],
        )


@pytest.mark.asyncio
async def test_assign_employee_single_100():
    svc = CostCenterService(_mk_db())
    rows = await svc.assign_employee(
        employee_id="E1",
        allocations=[{"cost_center_id": uuid.uuid4(), "allocation_pct": 100, "effective_from": date.today()}],
    )
    assert len(rows) == 1
    assert rows[0].allocation_pct == 100


@pytest.mark.asyncio
async def test_assign_employee_split_60_40():
    svc = CostCenterService(_mk_db())
    rows = await svc.assign_employee(
        employee_id="E1",
        allocations=[
            {"cost_center_id": uuid.uuid4(), "allocation_pct": 60, "effective_from": date.today()},
            {"cost_center_id": uuid.uuid4(), "allocation_pct": 40, "effective_from": date.today()},
        ],
    )
    assert len(rows) == 2
    assert sum(r.allocation_pct for r in rows) == 100


@pytest.mark.asyncio
async def test_aggregate_by_category_percentage():
    db = _mk_db()

    class MockResult:
        def mappings(self):
            return self

        def all(self):
            return [
                {"cat": "正餐", "labor_fen": 600000},  # 6000 元
                {"cat": "NPC", "labor_fen": 300000},
                {"cat": "PC", "labor_fen": 100000},
            ]

    db.execute = AsyncMock(return_value=MockResult())
    svc = CostCenterService(db)
    out = await svc.aggregate_by_category(store_id="S001", year_month="2026-04")
    assert out["正餐"]["labor_yuan"] == 6000.00
    assert out["正餐"]["share_pct"] == 60.00
    assert out["NPC"]["share_pct"] == 30.00
    assert out["PC"]["share_pct"] == 10.00
