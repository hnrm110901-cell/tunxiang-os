"""员工经营贡献度 API 路由

端点列表（prefix=/api/v1/contribution）：
  GET  /score/{employee_id}    单员工贡献度详情
  GET  /rankings               门店排名
  GET  /trend/{employee_id}    员工趋势
  GET  /store-comparison       跨门店对比
  POST /recalculate            手动触发重算

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.contribution_score_service import ContributionScoreService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/contribution", tags=["contribution-score"])

_service = ContributionScoreService()


# ── 辅助 ─────────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _parse_date(raw: Optional[str], default: date) -> date:
    if not raw:
        return default
    return date.fromisoformat(raw)


# ── 请求模型 ─────────────────────────────────────────────────────────────────


class RecalculateRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    period_start: Optional[str] = Field(None, description="起始日期 YYYY-MM-DD")
    period_end: Optional[str] = Field(None, description="结束日期 YYYY-MM-DD")


# ── 端点 ─────────────────────────────────────────────────────────────────────


@router.get("/score/{employee_id}")
async def get_employee_contribution(
    employee_id: str,
    request: Request,
    period_start: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    period_end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """单员工贡献度详情"""
    tid = _get_tenant_id(request)
    today = date.today()
    p_start = _parse_date(period_start, today - timedelta(days=30))
    p_end = _parse_date(period_end, today)

    try:
        data = await _service.calculate_score(db, tid, employee_id, p_start, p_end)
        return _ok(data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/rankings")
async def get_store_rankings(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    period_start: Optional[str] = Query(None, description="起始日期"),
    period_end: Optional[str] = Query(None, description="结束日期"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """门店排名"""
    tid = _get_tenant_id(request)
    today = date.today()
    p_start = _parse_date(period_start, today - timedelta(days=30))
    p_end = _parse_date(period_end, today)

    data = await _service.calculate_store_rankings(db, tid, store_id, p_start, p_end)
    return _ok(data)


@router.get("/trend/{employee_id}")
async def get_employee_trend(
    employee_id: str,
    request: Request,
    periods: int = Query(6, ge=1, le=12, description="趋势周期数"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """员工趋势"""
    tid = _get_tenant_id(request)
    data = await _service.get_employee_trend(db, tid, employee_id, periods)
    return _ok(data)


@router.get("/store-comparison")
async def get_store_comparison(
    request: Request,
    store_ids: str = Query(..., description="门店ID列表，逗号分隔"),
    period_start: Optional[str] = Query(None, description="起始日期"),
    period_end: Optional[str] = Query(None, description="结束日期"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """跨门店对比"""
    tid = _get_tenant_id(request)
    today = date.today()
    p_start = _parse_date(period_start, today - timedelta(days=30))
    p_end = _parse_date(period_end, today)

    sid_list = [s.strip() for s in store_ids.split(",") if s.strip()]
    if not sid_list:
        raise HTTPException(status_code=400, detail="store_ids 不能为空")

    comparisons: list[dict[str, Any]] = []
    for sid in sid_list:
        result = await _service.calculate_store_rankings(db, tid, sid, p_start, p_end)
        comparisons.append({
            "store_id": sid,
            "stats": result["stats"],
            "top3": result["rankings"][:3],
        })

    comparisons.sort(key=lambda x: x["stats"].get("avg", 0), reverse=True)
    return _ok({"stores": comparisons})


@router.post("/recalculate")
async def recalculate(
    body: RecalculateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动触发重算"""
    tid = _get_tenant_id(request)
    today = date.today()
    p_start = _parse_date(body.period_start, today - timedelta(days=30))
    p_end = _parse_date(body.period_end, today)

    data = await _service.calculate_store_rankings(db, tid, body.store_id, p_start, p_end)
    log.info(
        "contribution_recalculated",
        tenant_id=tid,
        store_id=body.store_id,
        employee_count=data["stats"].get("total_employees", 0),
    )
    return _ok(data)
