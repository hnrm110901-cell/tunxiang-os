"""Sprint D4b — 薪资异常 API

端点：
  POST /api/v1/org/salary/anomaly/analyze
    入参：月度/批量员工薪资信号
    出参：ranked_anomalies + remediation + cache stats
  POST /api/v1/org/salary/anomaly/review/{id}
    入参：{action: act_on | dismiss | escalate}
  GET  /api/v1/org/salary/anomaly/summary
    按 status + 城市 + 法律风险聚合 + Prompt Cache 命中率
"""

from __future__ import annotations

import logging
from datetime import date as date_cls
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.salary_anomaly_service import (
    EmployeeSalarySignal,
    SalaryAnomalyService,
    SalarySignalBundle,
    save_analysis_to_db,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/org/salary/anomaly",
    tags=["org-salary-anomaly"],
)


# ── 请求模型 ─────────────────────────────────────────────────────


class EmployeeSignalInput(BaseModel):
    employee_id: str
    emp_name: str = Field(..., max_length=100)
    role: str = Field(..., description="waiter|chef|cashier|manager|head_chef")
    city: str = Field(..., max_length=50)
    seniority_months: int = Field(ge=0)
    base_salary_fen: int = Field(ge=0)
    overtime_hours: float = Field(ge=0)
    overtime_pay_fen: int = Field(ge=0)
    commission_fen: int = Field(ge=0)
    total_pay_fen: int = Field(ge=0)
    prev_total_pay_fen: Optional[int] = None
    social_insurance_paid: bool = True
    housing_fund_paid: bool = True


class AnalyzeRequest(BaseModel):
    analysis_month: date_cls = Field(..., description="YYYY-MM-01")
    city: str = Field(..., description="城市名，用于关联基准表")
    store_id: Optional[str] = None
    store_name: Optional[str] = None
    employees: list[EmployeeSignalInput] = Field(..., min_length=1)
    analysis_scope: str = Field(
        default="monthly_batch",
        description="monthly_batch|single_employee|anomaly_triggered|manual",
    )
    employee_id_focus: Optional[str] = Field(
        default=None,
        description="single_employee 分析时的焦点员工 ID",
    )


class ReviewRequest(BaseModel):
    action: str = Field(..., description="act_on|dismiss|escalate")


# ── 端点 ────────────────────────────────────────────────────────


@router.post("/analyze", response_model=dict)
async def analyze_salary_anomaly(
    req: AnalyzeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """调 Sonnet 4.7 分析员工薪资异常"""
    tenant_uuid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    if req.analysis_scope not in (
        "monthly_batch",
        "single_employee",
        "anomaly_triggered",
        "manual",
    ):
        raise HTTPException(status_code=400, detail=f"未知 analysis_scope: {req.analysis_scope}")

    bundle = SalarySignalBundle(
        tenant_id=str(tenant_uuid),
        store_id=req.store_id,
        store_name=req.store_name,
        analysis_month=req.analysis_month,
        city=req.city,
        employees=[
            EmployeeSalarySignal(
                employee_id=e.employee_id,
                emp_name=e.emp_name,
                role=e.role,
                city=e.city,
                seniority_months=e.seniority_months,
                base_salary_fen=e.base_salary_fen,
                overtime_hours=e.overtime_hours,
                overtime_pay_fen=e.overtime_pay_fen,
                commission_fen=e.commission_fen,
                total_pay_fen=e.total_pay_fen,
                prev_total_pay_fen=e.prev_total_pay_fen,
                social_insurance_paid=e.social_insurance_paid,
                housing_fund_paid=e.housing_fund_paid,
            )
            for e in req.employees
        ],
    )

    service = SalaryAnomalyService()
    result = await service.analyze(bundle)

    try:
        analysis_id = await save_analysis_to_db(
            db,
            tenant_id=x_tenant_id,
            signal_bundle=bundle,
            result=result,
            analysis_scope=req.analysis_scope,
            employee_id=req.employee_id_focus,
        )
    except SQLAlchemyError as exc:
        logger.exception("salary_anomaly_save_failed")
        raise HTTPException(status_code=500, detail=f"持久化失败: {exc}") from exc

    status = "escalated" if result.has_critical or result.has_legal_risk else "analyzed"

    return {
        "ok": True,
        "data": {
            "analysis_id": analysis_id,
            "status": status,
            "model_id": result.model_id,
            "sonnet_analysis": result.sonnet_analysis,
            "ranked_anomalies": [
                {
                    "employee_id": a.employee_id,
                    "employee_name": a.employee_name,
                    "anomaly_type": a.anomaly_type,
                    "severity": a.severity,
                    "evidence": a.evidence,
                    "impact_fen": a.impact_fen,
                    "legal_risk": a.legal_risk,
                }
                for a in result.ranked_anomalies
            ],
            "remediation_actions": [
                {
                    "action": a.action,
                    "owner_role": a.owner_role,
                    "deadline_days": a.deadline_days,
                    "impact_fen": a.impact_fen,
                }
                for a in result.remediation_actions
            ],
            "summary": {
                "anomaly_count": len(result.ranked_anomalies),
                "critical_count": sum(1 for a in result.ranked_anomalies if a.severity == "critical"),
                "legal_risk_count": sum(1 for a in result.ranked_anomalies if a.legal_risk),
            },
            "prompt_cache_stats": {
                "cache_read_tokens": result.cache_read_tokens,
                "cache_creation_tokens": result.cache_creation_tokens,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cache_hit_rate": result.cache_hit_rate,
            },
        },
    }


@router.post("/review/{analysis_id}", response_model=dict)
async def review_analysis(
    analysis_id: str,
    req: ReviewRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """HRD 审核：act_on / dismiss / escalate"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(analysis_id, "analysis_id")
    _parse_uuid(x_operator_id, "X-Operator-ID")

    status_map = {
        "act_on": "acted_on",
        "dismiss": "dismissed",
        "escalate": "escalated",
    }
    new_status = status_map.get(req.action)
    if not new_status:
        raise HTTPException(
            status_code=400,
            detail=f"action 必须是 act_on|dismiss|escalate，收到 {req.action!r}",
        )

    try:
        result = await db.execute(
            text("""
            UPDATE salary_anomaly_analyses
            SET status = :new_status,
                reviewed_by = CAST(:op AS uuid),
                reviewed_at = NOW(),
                updated_at = NOW()
            WHERE id = CAST(:id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
              AND status IN ('analyzed', 'escalated')
              AND is_deleted = false
            RETURNING id, status
        """),
            {
                "id": analysis_id,
                "tenant_id": x_tenant_id,
                "op": x_operator_id,
                "new_status": new_status,
            },
        )
        row = result.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("salary_anomaly_review_failed")
        raise HTTPException(status_code=500, detail=f"状态迁移失败: {exc}") from exc

    if not row:
        raise HTTPException(
            status_code=404,
            detail="分析不存在或状态不允许 review",
        )

    return {"ok": True, "data": {"analysis_id": analysis_id, "status": row["status"]}}


@router.get("/summary", response_model=dict)
async def salary_anomaly_summary(
    months_back: int = 3,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按状态 + 城市聚合 + Prompt Cache 命中率"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    if months_back < 1 or months_back > 12:
        raise HTTPException(status_code=400, detail="months_back ∈ [1, 12]")

    try:
        result = await db.execute(
            text("""
            SELECT
                status,
                city,
                COUNT(*)                                        AS total,
                COALESCE(SUM(employee_count), 0)::bigint        AS employee_sum,
                COALESCE(SUM(total_payroll_fen), 0)::bigint     AS payroll_sum,
                COALESCE(SUM(cache_read_tokens), 0)::bigint     AS cache_read_sum,
                COALESCE(SUM(cache_creation_tokens), 0)::bigint AS cache_create_sum,
                COALESCE(SUM(input_tokens), 0)::bigint          AS input_sum,
                COALESCE(SUM(output_tokens), 0)::bigint         AS output_sum
            FROM salary_anomaly_analyses
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND is_deleted = false
              AND created_at >= CURRENT_DATE - (:months_back || ' months')::interval
            GROUP BY status, city
            ORDER BY status, city NULLS LAST
        """),
            {"tenant_id": x_tenant_id, "months_back": str(months_back)},
        )
        rows = [dict(r) for r in result.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("salary_anomaly_summary_failed")
        raise HTTPException(status_code=500, detail=f"汇总失败: {exc}") from exc

    total_cache_read = sum(int(r.get("cache_read_sum") or 0) for r in rows)
    total_cache_create = sum(int(r.get("cache_create_sum") or 0) for r in rows)
    total_input = sum(int(r.get("input_sum") or 0) for r in rows)
    total_output = sum(int(r.get("output_sum") or 0) for r in rows)
    total_input_all = total_cache_read + total_cache_create + total_input
    cache_hit_rate = round(total_cache_read / total_input_all, 4) if total_input_all > 0 else 0.0

    return {
        "ok": True,
        "data": {
            "period": {"months_back": months_back},
            "by_status_city": rows,
            "aggregate": {
                "total_analyses": sum(int(r.get("total") or 0) for r in rows),
                "total_employees_scanned": sum(int(r.get("employee_sum") or 0) for r in rows),
                "total_payroll_fen": sum(int(r.get("payroll_sum") or 0) for r in rows),
            },
            "prompt_cache": {
                "cache_read_tokens": total_cache_read,
                "cache_creation_tokens": total_cache_create,
                "non_cached_input_tokens": total_input,
                "output_tokens": total_output,
                "cache_hit_rate": cache_hit_rate,
                "cache_hit_target": 0.75,
                "meets_target": cache_hit_rate >= 0.75,
            },
        },
    }


# ── 辅助 ─────────────────────────────────────────────────────────


def _parse_uuid(value: str, field_name: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} 非法 UUID: {value!r}") from exc
