"""
九宫格人才盘点服务 — 单元测试
覆盖:
  1) 九宫格 cell 1..9 映射完备
  2) 评分边界 (1-5)
  3) 非法 pool_type 校验
  4) add_to_talent_pool 正向
  5) 核心映射公式: cell = (perf_grid - 1) * 3 + pot_grid
"""

import sys
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.services.talent_assessment_service import (  # noqa: E402
    CELL_LABEL,
    TalentAssessmentService,
    compute_nine_box_cell,
)


def _mk_db():
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


class TestNineBoxMapping:
    """九宫格 1..9 完备映射测试"""

    def test_low_low_cell_1(self):
        # perf=1(低) potential=1(低) → grid(1,1) → cell=1
        assert compute_nine_box_cell(1, 1) == 1
        assert compute_nine_box_cell(2, 2) == 1

    def test_low_high_cell_3(self):
        # perf=1(低) potential=5(高) → grid(1,3) → cell=3
        assert compute_nine_box_cell(1, 5) == 3
        assert compute_nine_box_cell(2, 4) == 3

    def test_mid_mid_cell_5(self):
        # perf=3 potential=3 → grid(2,2) → cell=5
        assert compute_nine_box_cell(3, 3) == 5

    def test_high_low_cell_7(self):
        # perf=5(高) potential=1(低) → grid(3,1) → cell=7
        assert compute_nine_box_cell(5, 1) == 7
        assert compute_nine_box_cell(4, 2) == 7

    def test_high_high_cell_9(self):
        # perf=5(高) potential=5(高) → grid(3,3) → cell=9
        assert compute_nine_box_cell(5, 5) == 9
        assert compute_nine_box_cell(4, 4) == 9

    def test_all_cells_1_to_9_reachable(self):
        cells = {compute_nine_box_cell(p, t) for p in range(1, 6) for t in range(1, 6)}
        assert cells == set(range(1, 10))

    def test_cell_labels_complete(self):
        for i in range(1, 10):
            assert i in CELL_LABEL
            assert CELL_LABEL[i]


@pytest.mark.asyncio
async def test_create_assessment_score_boundary():
    svc = TalentAssessmentService(_mk_db())
    with pytest.raises(ValueError):
        await svc.create_assessment("E1", "M1", performance_score=0, potential_score=3)
    with pytest.raises(ValueError):
        await svc.create_assessment("E1", "M1", performance_score=3, potential_score=6)


@pytest.mark.asyncio
async def test_create_assessment_ok_cell_9():
    svc = TalentAssessmentService(_mk_db())
    ta = await svc.create_assessment(
        employee_id="E1",
        assessor_id="M1",
        performance_score=5,
        potential_score=5,
        strengths="执行力强",
        development_areas="战略思维",
    )
    assert ta.nine_box_cell == 9
    assert ta.status == "draft"


@pytest.mark.asyncio
async def test_add_to_pool_invalid_type():
    svc = TalentAssessmentService(_mk_db())
    with pytest.raises(ValueError):
        await svc.add_to_talent_pool(employee_id="E1", pool_type="unknown")


@pytest.mark.asyncio
async def test_add_to_pool_high_potential():
    svc = TalentAssessmentService(_mk_db())
    row = await svc.add_to_talent_pool(
        employee_id="E1",
        pool_type="high_potential",
        target_position="店长",
        readiness="1year",
    )
    assert row.pool_type == "high_potential"
    assert row.status == "active"
    assert row.target_position == "店长"
