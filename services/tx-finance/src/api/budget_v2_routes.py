"""预算管理 v2 — 简化版端点（v118）

prefix=/api/v1/finance/budget（注意：复数版 /budgets 由 budget_routes.py 提供完整 CRUD）

本文件提供面向前端报表的快捷接口：
  GET  /api/v1/finance/budget              — 年度预算列表（?store_id=&year=）
  POST /api/v1/finance/budget              — 创建月度预算（简化 body）
  GET  /api/v1/finance/budget/execution    — 预算执行情况（?store_id=&year=&month=）

执行情况端点会自动从 orders/payroll_records/purchase_orders 汇总实际数据，
与预算目标对比，返回执行率（actual_revenue / target_revenue）。
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/budget", tags=["finance-budget-v2"])


# ─── DB 依赖 ──────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class CreateMonthlyBudgetRequest(BaseModel):
    store_id: str = Field(..., description="门店 ID（UUID）")
    year: int = Field(..., ge=2020, le=2099, description="年份")
    month: int = Field(..., ge=1, le=12, description="月份（1-12）")
    revenue_target_fen: int = Field(..., ge=0, description="营收目标（分）")
    cost_budget_fen: int = Field(..., ge=0, description="食材成本预算（分）")
    labor_budget_fen: int = Field(..., ge=0, description="人力成本预算（分）")
    note: Optional[str] = Field(None, max_length=500, description="备注")

    @field_validator("store_id")
    @classmethod
    def check_store_id(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError as exc:
            raise ValueError(f"store_id 必须是有效 UUID: {v}") from exc
        return v


# ─── GET /budget — 年度预算列表 ───────────────────────────────────────────────


@router.get("", summary="年度月度预算列表")
async def list_annual_budgets(
    store_id: str = Query(..., description="门店 ID"),
    year: int = Query(..., ge=2020, le=2099, description="年份"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """查询门店某年度所有月度预算计划。

    返回 12 个月的营收目标、食材成本预算、人力成本预算。
    若某月无预算记录则该月返回 null。
    """
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id")

    try:
        result = await db.execute(
            text("""
                SELECT
                    period,
                    MAX(CASE WHEN category = 'revenue'         THEN budget_fen END) AS revenue_target_fen,
                    MAX(CASE WHEN category = 'ingredient_cost' THEN budget_fen END) AS cost_budget_fen,
                    MAX(CASE WHEN category = 'labor_cost'      THEN budget_fen END) AS labor_budget_fen,
                    MAX(status) AS status
                FROM budget_plans
                WHERE tenant_id = :tid::UUID
                  AND store_id = :sid::UUID
                  AND period_type = 'monthly'
                  AND period LIKE :year_prefix
                GROUP BY period
                ORDER BY period ASC
            """),
            {
                "tid": str(tid),
                "sid": str(sid),
                "year_prefix": f"{year:04d}-%",
            },
        )
        rows = result.fetchall()

        items = [
            {
                "period": r[0],
                "revenue_target_fen": int(r[1]) if r[1] is not None else None,
                "cost_budget_fen": int(r[2]) if r[2] is not None else None,
                "labor_budget_fen": int(r[3]) if r[3] is not None else None,
                "status": r[4],
            }
            for r in rows
        ]

        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "year": year,
                "items": items,
                "total": len(items),
            },
        }

    except (OSError, RuntimeError) as exc:
        logger.warning("list_annual_budgets_error", error=str(exc), store_id=store_id, year=year, tenant_id=x_tenant_id)
        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "year": year,
                "items": [],
                "total": 0,
                "_is_mock": True,
            },
        }


# ─── POST /budget — 创建月度预算 ──────────────────────────────────────────────


@router.post("", summary="创建月度预算", status_code=201)
async def create_monthly_budget(
    body: CreateMonthlyBudgetRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """创建（或更新）门店月度预算。

    body 包含营收目标、食材成本预算、人力成本预算三个科目。
    底层通过 budget_plans UPSERT 实现幂等，重复提交则更新金额。
    """
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(body.store_id, "store_id")
    period_str = f"{body.year:04d}-{body.month:02d}"

    # 三个科目分别 UPSERT
    categories = [
        ("revenue", body.revenue_target_fen),
        ("ingredient_cost", body.cost_budget_fen),
        ("labor_cost", body.labor_budget_fen),
    ]

    try:
        upserted = []
        for cat, fen in categories:
            result = await db.execute(
                text("""
                    INSERT INTO budget_plans
                        (tenant_id, store_id, period_type, period, category, budget_fen, note, status)
                    VALUES
                        (:tid, :sid, 'monthly', :period, :cat, :fen, :note, 'draft')
                    ON CONFLICT (tenant_id, store_id, period_type, period, category)
                    DO UPDATE SET
                        budget_fen = EXCLUDED.budget_fen,
                        note       = COALESCE(EXCLUDED.note, budget_plans.note),
                        updated_at = NOW()
                    RETURNING id, category, budget_fen, status, created_at, updated_at
                """),
                {
                    "tid": tid,
                    "sid": sid,
                    "period": period_str,
                    "cat": cat,
                    "fen": fen,
                    "note": body.note,
                },
            )
            row = result.fetchone()
            if row:
                upserted.append(
                    {
                        "plan_id": str(row[0]),
                        "category": row[1],
                        "budget_fen": int(row[2]),
                        "status": row[3],
                    }
                )

        await db.commit()
        logger.info("monthly_budget_created", store_id=body.store_id, period=period_str, tenant_id=x_tenant_id)

        return {
            "ok": True,
            "data": {
                "store_id": body.store_id,
                "period": period_str,
                "revenue_target_fen": body.revenue_target_fen,
                "cost_budget_fen": body.cost_budget_fen,
                "labor_budget_fen": body.labor_budget_fen,
                "plans": upserted,
            },
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─── GET /budget/execution — 预算执行情况 ─────────────────────────────────────


@router.get("/execution", summary="月度预算执行情况")
async def get_budget_execution(
    store_id: str = Query(..., description="门店 ID"),
    year: int = Query(..., ge=2020, le=2099, description="年份"),
    month: int = Query(..., ge=1, le=12, description="月份（1-12）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """月度预算执行情况：预算 vs 实际 vs 差异 vs 执行率。

    实际数据来源：
    - actual_revenue: orders 表（paid/completed/settled）
    - actual_labor_cost: payroll_records 表（approved/paid）
    - actual_food_cost: purchase_orders 表（received）

    execution_rate = actual_revenue / revenue_target（营收执行率）
    若无预算数据则返回 mock 数据（带 _is_mock 标记）。
    """
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id")
    period_str = f"{year:04d}-{month:02d}"
    days_in_month = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, days_in_month)

    try:
        # ── 读取预算计划 ──────────────────────────────────────
        budget_result = await db.execute(
            text("""
                SELECT category, budget_fen
                FROM budget_plans
                WHERE tenant_id = :tid::UUID
                  AND store_id = :sid::UUID
                  AND period_type = 'monthly'
                  AND period = :period
            """),
            {"tid": str(tid), "sid": str(sid), "period": period_str},
        )
        budget_rows = budget_result.fetchall()
        budget_map: Dict[str, int] = {r[0]: int(r[1]) for r in budget_rows}

        revenue_target_fen = budget_map.get("revenue", 0)
        cost_budget_fen = budget_map.get("ingredient_cost", 0)
        labor_budget_fen = budget_map.get("labor_cost", 0)
        has_budget = bool(budget_map)

        # ── 实际营收 ─────────────────────────────────────────
        rev_result = await db.execute(
            text("""
                SELECT COALESCE(SUM(total_amount_fen), 0)
                FROM orders
                WHERE tenant_id = :tid::UUID
                  AND store_id = :sid::UUID
                  AND status IN ('paid', 'completed', 'settled')
                  AND is_deleted = FALSE
                  AND DATE(created_at) BETWEEN :sd AND :ed
            """),
            {"tid": str(tid), "sid": str(sid), "sd": start_date.isoformat(), "ed": end_date.isoformat()},
        )
        actual_revenue_fen = int(rev_result.scalar() or 0)

        # ── 实际人力成本 ─────────────────────────────────────
        labor_result = await db.execute(
            text("""
                SELECT COALESCE(SUM(net_pay_fen), 0)
                FROM payroll_records
                WHERE tenant_id = :tid::UUID
                  AND store_id = :sid::UUID
                  AND status IN ('approved', 'paid')
                  AND is_deleted = FALSE
                  AND pay_year = :year AND pay_month = :month
            """),
            {"tid": str(tid), "sid": str(sid), "year": year, "month": month},
        )
        actual_labor_fen = int(labor_result.scalar() or 0)

        # ── 实际食材成本 ─────────────────────────────────────
        food_result = await db.execute(
            text("""
                SELECT COALESCE(SUM(total_amount_fen), 0)
                FROM purchase_orders
                WHERE tenant_id = :tid::UUID
                  AND store_id = :sid::UUID
                  AND status = 'received'
                  AND is_deleted = FALSE
                  AND DATE(received_at) BETWEEN :sd AND :ed
            """),
            {"tid": str(tid), "sid": str(sid), "sd": start_date.isoformat(), "ed": end_date.isoformat()},
        )
        actual_food_fen = int(food_result.scalar() or 0)

        # ── 计算执行率与差异 ──────────────────────────────────
        execution_rate = round(actual_revenue_fen / revenue_target_fen, 4) if revenue_target_fen > 0 else 0.0

        revenue_variance_fen = actual_revenue_fen - revenue_target_fen
        cost_variance_fen = actual_food_fen - cost_budget_fen
        labor_variance_fen = actual_labor_fen - labor_budget_fen

        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "period": period_str,
                "has_budget": has_budget,
                "budget": {
                    "revenue_target_fen": revenue_target_fen,
                    "cost_budget_fen": cost_budget_fen,
                    "labor_budget_fen": labor_budget_fen,
                },
                "actual": {
                    "revenue_fen": actual_revenue_fen,
                    "food_cost_fen": actual_food_fen,
                    "labor_cost_fen": actual_labor_fen,
                },
                "variance": {
                    "revenue_fen": revenue_variance_fen,
                    "cost_fen": cost_variance_fen,
                    "labor_fen": labor_variance_fen,
                    "revenue_over_budget": revenue_variance_fen >= 0,
                    "cost_over_budget": cost_variance_fen > 0,
                    "labor_over_budget": labor_variance_fen > 0,
                },
                "execution_rate": execution_rate,
                "execution_status": (
                    "on_track" if execution_rate >= 0.95 else "below_target" if execution_rate >= 0.80 else "critical"
                ),
            },
        }

    except (OSError, RuntimeError) as exc:
        logger.warning(
            "budget_execution_error", error=str(exc), store_id=store_id, year=year, month=month, tenant_id=x_tenant_id
        )
        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "period": period_str,
                "has_budget": False,
                "_is_mock": True,
                "budget": {
                    "revenue_target_fen": 0,
                    "cost_budget_fen": 0,
                    "labor_budget_fen": 0,
                },
                "actual": {
                    "revenue_fen": 0,
                    "food_cost_fen": 0,
                    "labor_cost_fen": 0,
                },
                "variance": {
                    "revenue_fen": 0,
                    "cost_fen": 0,
                    "labor_fen": 0,
                    "revenue_over_budget": False,
                    "cost_over_budget": False,
                    "labor_over_budget": False,
                },
                "execution_rate": 0.0,
                "execution_status": "critical",
            },
        }
