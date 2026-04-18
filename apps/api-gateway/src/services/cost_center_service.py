"""
成本中心服务

核心能力：
  - create_cost_center: 创建成本中心节点（含父子关系）
  - assign_employee: 分配员工到成本中心（支持多中心分摊，比例和必须=100%）
  - compute_cost_allocation: 按薪资 × 分摊比例 落位到各成本中心
  - aggregate_by_category: 按分类(正餐/NPC/PC/...)聚合人力成本

金额统一分(fen) + `_yuan` 伴生字段。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Dict, List, Optional

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.cost_center import CostCenter, CostCenterBudget, EmployeeCostCenter

logger = structlog.get_logger()

ALLOWED_CATEGORIES = {"正餐", "NPC", "PC", "后勤", "中央厨房", "总部"}


class CostCenterService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── 建模 ─────────────────────────────────────────
    async def create_cost_center(
        self,
        code: str,
        name: str,
        category: str,
        parent_id: Optional[uuid.UUID] = None,
        store_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> CostCenter:
        if category not in ALLOWED_CATEGORIES:
            raise ValueError(f"非法成本中心分类: {category}")

        cc = CostCenter(
            id=uuid.uuid4(),
            code=code,
            name=name,
            category=category,
            parent_id=parent_id,
            store_id=store_id,
            description=description,
            is_active=True,
        )
        self.db.add(cc)
        await self.db.flush()
        return cc

    # ── 员工分摊 ──────────────────────────────────────
    async def assign_employee(
        self,
        employee_id: str,
        allocations: List[Dict],  # [{"cost_center_id": uuid, "allocation_pct": 60, "effective_from": date}]
    ) -> List[EmployeeCostCenter]:
        """
        一员工可分摊到多个成本中心，总比例必须 = 100%。
        单一成本中心场景传单条记录即可。
        """
        total = sum(int(a.get("allocation_pct", 0)) for a in allocations)
        if total != 100:
            raise ValueError(f"分摊比例和必须 = 100%，当前 = {total}%")

        created = []
        for a in allocations:
            row = EmployeeCostCenter(
                id=uuid.uuid4(),
                employee_id=employee_id,
                cost_center_id=a["cost_center_id"],
                allocation_pct=int(a["allocation_pct"]),
                effective_from=a.get("effective_from") or date.today(),
                effective_to=a.get("effective_to"),
            )
            self.db.add(row)
            created.append(row)
        await self.db.flush()
        return created

    # ── 分摊计算 ──────────────────────────────────────
    async def compute_cost_allocation(
        self,
        pay_month: str,  # YYYY-MM
        store_id: str,
    ) -> Dict[str, Dict]:
        """
        按当月 payroll_records.gross_salary_fen × 员工分摊比例 → 落到各成本中心。
        返回: {cost_center_id(str): {"labor_fen": ..., "labor_yuan": ..., "headcount": N}}
        """
        sql = text(
            """
            SELECT
              ecc.cost_center_id AS cc_id,
              pr.employee_id AS emp_id,
              pr.gross_salary_fen AS gross_fen,
              ecc.allocation_pct AS pct
            FROM payroll_records pr
            JOIN employee_cost_centers ecc ON ecc.employee_id = pr.employee_id
            WHERE pr.store_id = :store_id
              AND pr.pay_month = :pay_month
              AND (ecc.effective_to IS NULL OR ecc.effective_to >= CURRENT_DATE)
            """
        )
        rows = (
            await self.db.execute(sql, {"store_id": store_id, "pay_month": pay_month})
        ).mappings().all()

        buckets: Dict[str, Dict] = {}
        for r in rows:
            cc_id = str(r["cc_id"])
            alloc_fen = int((r["gross_fen"] or 0) * (r["pct"] or 0) / 100)
            b = buckets.setdefault(
                cc_id, {"labor_fen": 0, "employees": set()}
            )
            b["labor_fen"] += alloc_fen
            b["employees"].add(r["emp_id"])

        # 回写 cost_center_budgets.actual_labor_fen
        for cc_id, b in buckets.items():
            existing = await self.db.execute(
                select(CostCenterBudget).where(
                    CostCenterBudget.cost_center_id == uuid.UUID(cc_id),
                    CostCenterBudget.year_month == pay_month,
                )
            )
            budget = existing.scalar_one_or_none()
            if budget is None:
                budget = CostCenterBudget(
                    id=uuid.uuid4(),
                    cost_center_id=uuid.UUID(cc_id),
                    year_month=pay_month,
                    labor_budget_fen=0,
                    revenue_target_fen=0,
                    actual_labor_fen=b["labor_fen"],
                )
                self.db.add(budget)
            else:
                budget.actual_labor_fen = b["labor_fen"]

        await self.db.flush()

        return {
            cc_id: {
                "labor_fen": b["labor_fen"],
                "labor_yuan": round(b["labor_fen"] / 100, 2),
                "headcount": len(b["employees"]),
            }
            for cc_id, b in buckets.items()
        }

    # ── 分类聚合 ──────────────────────────────────────
    async def aggregate_by_category(self, store_id: str, year_month: str) -> Dict[str, Dict]:
        """
        按 CostCenter.category 聚合 actual_labor_fen，输出占比。
        """
        sql = text(
            """
            SELECT cc.category AS cat,
                   COALESCE(SUM(ccb.actual_labor_fen), 0) AS labor_fen
            FROM cost_centers cc
            LEFT JOIN cost_center_budgets ccb
              ON ccb.cost_center_id = cc.id AND ccb.year_month = :ym
            WHERE (cc.store_id = :store_id OR cc.store_id IS NULL)
            GROUP BY cc.category
            """
        )
        rows = (
            await self.db.execute(sql, {"store_id": store_id, "ym": year_month})
        ).mappings().all()

        total_fen = sum(int(r["labor_fen"] or 0) for r in rows) or 1
        out: Dict[str, Dict] = {}
        for r in rows:
            fen = int(r["labor_fen"] or 0)
            out[r["cat"]] = {
                "labor_fen": fen,
                "labor_yuan": round(fen / 100, 2),
                "share_pct": round(fen * 100 / total_fen, 2),
            }
        return out
