"""
九宫格人才盘点服务

九宫格映射（performance 低→高 = 左→右, potential 低→高 = 下→上）:
    cell = (perf_grid - 1) * 3 + pot_grid
    perf_grid / pot_grid ∈ {1, 2, 3}（由 1-5 分压缩得到）

输出 cell 编号表:
              potential=1(低)  potential=2  potential=3(高)
    perf=1        1                 2            3
    perf=2        4                 5            6
    perf=3        7                 8            9
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Dict, List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.employee import Employee
from ..models.talent_assessment import SuccessionPlan, TalentAssessment, TalentPool

logger = structlog.get_logger()


def _compress_to_grid(score: int) -> int:
    """1-5 → 1-3。 1-2=低 / 3=中 / 4-5=高"""
    if score is None:
        raise ValueError("score 不能为空")
    if score <= 2:
        return 1
    if score == 3:
        return 2
    return 3


def compute_nine_box_cell(performance_score: int, potential_score: int) -> int:
    """核心映射：cell = (perf_grid - 1) * 3 + pot_grid ∈ [1..9]"""
    pg = _compress_to_grid(performance_score)
    tg = _compress_to_grid(potential_score)
    return (pg - 1) * 3 + tg


CELL_LABEL = {
    1: "观察清退",
    2: "发展潜力",
    3: "待培养高潜",
    4: "稳定执行",
    5: "核心骨干",
    6: "未来之星",
    7: "绩效能手",
    8: "关键人才",
    9: "明星(接班人)",
}


class TalentAssessmentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_assessment(
        self,
        employee_id: str,
        assessor_id: str,
        performance_score: int,
        potential_score: int,
        strengths: Optional[str] = None,
        development_areas: Optional[str] = None,
        career_path: Optional[str] = None,
        assessment_date: Optional[date] = None,
    ) -> TalentAssessment:
        if not 1 <= performance_score <= 5 or not 1 <= potential_score <= 5:
            raise ValueError("performance_score / potential_score 必须在 1..5")

        cell = compute_nine_box_cell(performance_score, potential_score)
        row = TalentAssessment(
            id=uuid.uuid4(),
            employee_id=employee_id,
            assessor_id=assessor_id,
            assessment_date=assessment_date or date.today(),
            performance_score=performance_score,
            potential_score=potential_score,
            nine_box_cell=cell,
            strengths=strengths,
            development_areas=development_areas,
            career_path=career_path,
            status="draft",
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def compute_nine_box_matrix(
        self, store_id: str, as_of_date: Optional[date] = None
    ) -> Dict[int, Dict]:
        """
        返回 {cell: {"label": ..., "count": N, "employees": [{id,name,perf,pot}, ...]}}
        使用每位员工最近一次盘点。
        """
        cutoff = as_of_date or date.today()

        # 取每位员工最近一次 assessment
        stmt = (
            select(TalentAssessment, Employee)
            .join(Employee, Employee.id == TalentAssessment.employee_id)
            .where(
                Employee.store_id == store_id,
                TalentAssessment.assessment_date <= cutoff,
            )
            .order_by(TalentAssessment.employee_id, TalentAssessment.assessment_date.desc())
        )
        rows = (await self.db.execute(stmt)).all()

        seen = set()
        matrix: Dict[int, Dict] = {
            i: {"label": CELL_LABEL[i], "count": 0, "employees": []} for i in range(1, 10)
        }
        for ta, emp in rows:
            if emp.id in seen:
                continue
            seen.add(emp.id)
            cell = ta.nine_box_cell
            matrix[cell]["count"] += 1
            matrix[cell]["employees"].append(
                {
                    "id": emp.id,
                    "name": emp.name,
                    "position": emp.position,
                    "performance": ta.performance_score,
                    "potential": ta.potential_score,
                    "assessment_date": ta.assessment_date.isoformat(),
                }
            )
        return matrix

    async def add_to_talent_pool(
        self,
        employee_id: str,
        pool_type: str,
        target_position: Optional[str] = None,
        readiness: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> TalentPool:
        if pool_type not in {"high_potential", "successor", "key_position", "watch_list"}:
            raise ValueError(f"非法 pool_type: {pool_type}")
        row = TalentPool(
            id=uuid.uuid4(),
            employee_id=employee_id,
            pool_type=pool_type,
            target_position=target_position,
            readiness=readiness,
            notes=notes,
            status="active",
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def generate_successor_plan(self, key_position_id: str, top_n: int = 3) -> SuccessionPlan:
        """基于 talent_pools(successor/key_position) 推荐前 N 候选人。"""
        stmt = (
            select(TalentPool, Employee)
            .join(Employee, Employee.id == TalentPool.employee_id)
            .where(
                TalentPool.status == "active",
                TalentPool.pool_type.in_(["successor", "key_position", "high_potential"]),
                TalentPool.target_position == key_position_id,
            )
        )
        rows = (await self.db.execute(stmt)).all()
        readiness_rank = {"ready_now": 0, "1year": 1, "2year": 2}
        rows_sorted = sorted(
            rows, key=lambda r: readiness_rank.get(r[0].readiness or "2year", 3)
        )[:top_n]

        candidates = [
            {
                "employee_id": emp.id,
                "name": emp.name,
                "position": emp.position,
                "readiness": pool.readiness,
            }
            for pool, emp in rows_sorted
        ]

        plan = SuccessionPlan(
            id=uuid.uuid4(),
            key_position_id=key_position_id,
            successor_id=candidates[0]["employee_id"] if candidates else None,
            readiness=candidates[0]["readiness"] if candidates else None,
            candidates_json=candidates,
        )
        self.db.add(plan)
        await self.db.flush()
        return plan
