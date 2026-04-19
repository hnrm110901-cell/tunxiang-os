"""
AI 薪资推荐 API 路由 (v257)

端点列表 (prefix=/api/v1/org/salary-advisor):
  POST /recommend              单员工薪酬推荐
  POST /batch                  批量推荐 + 门店成本约束校验
  GET  /role-tiers             岗位档位目录 (前端下拉用)
  GET  /regions                区域系数表
  GET  /seniority-curve        工龄系数曲线
  GET  /health                 模块健康检查

统一响应格式: {"ok": bool, "data": {}, "error": {}}
金额单位统一为 fen (分)。
"""

from __future__ import annotations

from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.ai_salary_advisor_service import (
    batch_recommend,
    get_region_factors_catalog,
    get_role_tiers_catalog,
    get_seniority_curve,
    recommend_salary_structure,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/org/salary-advisor",
    tags=["ai-salary-advisor"],
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pydantic 请求 schema
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class RecommendRequest(BaseModel):
    """单员工薪酬推荐请求"""

    role: str = Field(..., min_length=1, max_length=50, description="岗位名,如 店长/厨师/服务员")
    region: str = Field(default="tier2", description="区域编码或城市名,如 tier1/长沙/北京")
    years_of_service: int = Field(default=0, ge=0, le=60, description="工龄 (年)")
    store_monthly_revenue_fen: Optional[int] = Field(
        default=None,
        ge=0,
        description="门店月营业额 (分),可选,用于人力成本占比校验",
    )


class EmployeeInput(BaseModel):
    """批量推荐中单条员工记录"""

    model_config = ConfigDict(populate_by_name=True)

    role: str = Field(..., min_length=1, max_length=50)
    region: str = Field(default="tier2")
    years: int = Field(default=0, ge=0, le=60, alias="years_of_service")
    employee_id: Optional[str] = Field(default=None, max_length=64)
    employee_name: Optional[str] = Field(default=None, max_length=100)


class BatchRecommendRequest(BaseModel):
    """批量推荐请求"""

    employees: List[EmployeeInput] = Field(..., min_length=1, max_length=1000)
    store_monthly_revenue_fen: Optional[int] = Field(
        default=None,
        ge=0,
        description="门店月营业额 (分),可选,用于批次成本占比校验",
    )

    @field_validator("employees")
    @classmethod
    def _limit_batch_size(cls, v: List[EmployeeInput]) -> List[EmployeeInput]:
        if len(v) > 1000:
            raise ValueError("单批最多 1000 条员工,超出请分批")
        return v


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  响应包装辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(code: str, msg: str) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": msg}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/recommend")
async def recommend(payload: RecommendRequest) -> dict:
    """单员工薪酬结构推荐。"""

    try:
        rec = recommend_salary_structure(
            role=payload.role,
            region=payload.region,
            years_of_service=payload.years_of_service,
            store_monthly_revenue_fen=payload.store_monthly_revenue_fen,
        )
        log.info(
            "ai_salary_advisor.api.recommend",
            role=payload.role,
            region=payload.region,
            years=payload.years_of_service,
            total_fen=rec.estimated_total_gross_fen,
        )
        return _ok(rec.to_dict())
    except HTTPException:
        # 让已有 HTTP 异常原样传出,避免被 Exception 兜底吞成 500。
        raise
    except ValueError as e:
        log.warning("ai_salary_advisor.api.recommend.invalid", error=str(e))
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        log.exception("ai_salary_advisor.api.recommend.error")
        raise HTTPException(status_code=500, detail="internal_error") from e


@router.post("/batch")
async def batch(payload: BatchRecommendRequest) -> dict:
    """批量员工薪酬推荐 + 门店总成本占比校验。"""

    try:
        employees_dicts = [
            {
                "role": e.role,
                "region": e.region,
                "years": e.years,
                "employee_id": e.employee_id,
                "employee_name": e.employee_name,
            }
            for e in payload.employees
        ]
        result = batch_recommend(
            employees=employees_dicts,
            store_monthly_revenue_fen=payload.store_monthly_revenue_fen,
        )
        log.info(
            "ai_salary_advisor.api.batch",
            headcount=len(payload.employees),
            total_fen=result["summary"]["total_gross_fen"],
            ratio=result["summary"].get("labor_cost_ratio"),
            skipped=result["summary"].get("skipped_count", 0),
        )
        return _ok(result)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        log.exception("ai_salary_advisor.api.batch.error")
        raise HTTPException(status_code=500, detail="internal_error") from e


@router.get("/role-tiers")
async def list_role_tiers() -> dict:
    """查询所有岗位档位及示例岗位 (前端下拉用)。"""

    return _ok(get_role_tiers_catalog())


@router.get("/regions")
async def list_regions() -> dict:
    """查询所有区域系数表。"""

    return _ok(get_region_factors_catalog())


@router.get("/seniority-curve")
async def get_seniority() -> dict:
    """查询工龄系数曲线。"""

    return _ok(get_seniority_curve())


@router.get("/health")
async def health() -> dict:
    """模块健康检查 (用于 K8s liveness probe)。"""

    return _ok({
        "module": "ai_salary_advisor",
        "version": "v257",
        "status": "ok",
        "features": {
            "deterministic_recommendation": True,
            "batch_budget_check": True,
            "llm_enhanced_reasoning": False,  # Phase2 启用
        },
    })
