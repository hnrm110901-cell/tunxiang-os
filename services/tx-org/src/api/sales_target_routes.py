"""销售目标 API 路由（Sprint R1 Track C）

端点列表（prefix=/api/v1/sales-targets）：
  POST  /                                  — set_target
  POST  /{target_id}/decompose             — year → month → day 分解
  POST  /{target_id}/progress              — record_progress
  GET   /                                  — 列表（employee_id / period_type / active）
  GET   /{target_id}/achievement           — 当前达成率
  GET   /leaderboard                       — 排行榜

响应格式：{"ok": bool, "data": {}, "error": {}}
租户：X-Tenant-ID header 必填（CLAUDE.md §14：禁止跳过 RLS）
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from shared.ontology.src.extensions.sales_targets import (
    MetricType,
    PeriodType,
)

from ..services.sales_target_service import SalesTargetService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/sales-targets", tags=["sales-targets"])

_service = SalesTargetService()


# ── 辅助 ─────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> UUID:
    tid = (
        getattr(request.state, "tenant_id", None)
        or request.headers.get("X-Tenant-ID", "")
    )
    if not tid:
        raise HTTPException(
            status_code=400, detail="X-Tenant-ID header required"
        )
    try:
        return UUID(str(tid))
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"X-Tenant-ID invalid UUID: {tid}"
        ) from exc


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(code: str, message: str) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}


def _serialize_target(target: dict) -> dict:
    out = dict(target)
    for k in (
        "target_id",
        "tenant_id",
        "store_id",
        "employee_id",
        "parent_target_id",
        "created_by",
    ):
        if out.get(k) is not None and not isinstance(out[k], str):
            out[k] = str(out[k])
    for k in ("period_start", "period_end"):
        v = out.get(k)
        if v is not None and hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    for k in ("created_at", "updated_at"):
        v = out.get(k)
        if v is not None and hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    mt = out.get("metric_type")
    if hasattr(mt, "value"):
        out["metric_type"] = mt.value
    pt = out.get("period_type")
    if hasattr(pt, "value"):
        out["period_type"] = pt.value
    out["target_value"] = int(out["target_value"]) if out.get("target_value") is not None else 0
    return out


def _serialize_progress(progress: dict) -> dict:
    out = dict(progress)
    for k in ("progress_id", "tenant_id", "target_id", "source_event_id"):
        v = out.get(k)
        if v is not None and not isinstance(v, str):
            out[k] = str(v)
    rate = out.get("achievement_rate")
    if rate is not None and not isinstance(rate, str):
        out["achievement_rate"] = str(rate)
    for k in ("snapshot_at", "created_at"):
        v = out.get(k)
        if v is not None and hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    out["actual_value"] = int(out["actual_value"]) if out.get("actual_value") is not None else 0
    return out


# ── 请求模型 ─────────────────────────────────────────────────────────


class SetTargetRequest(BaseModel):
    employee_id: UUID = Field(..., description="目标归属员工")
    period_type: PeriodType = Field(..., description="周期类型")
    period_start: date = Field(..., description="周期起点")
    period_end: date = Field(..., description="周期终点")
    metric_type: MetricType = Field(..., description="指标类型")
    target_value: int = Field(..., ge=0, description="目标值（金额单位=分）")
    store_id: UUID | None = Field(default=None, description="门店ID")
    parent_target_id: UUID | None = Field(
        default=None, description="上级目标ID"
    )
    notes: str | None = Field(default=None, max_length=500)


class RecordProgressRequest(BaseModel):
    actual_value: int = Field(..., ge=0, description="实际完成值")
    source_event_id: UUID | None = Field(
        default=None,
        description="触发本次快照的事件ID（幂等key）",
    )


# ── 端点 ─────────────────────────────────────────────────────────────


@router.post("")
@router.post("/")
async def set_target(
    body: SetTargetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _get_tenant_id(request)
    try:
        target = await _service.set_target(
            db,
            tenant_id=tid,
            employee_id=body.employee_id,
            period_type=body.period_type,
            period_start=body.period_start,
            period_end=body.period_end,
            metric_type=body.metric_type,
            target_value=body.target_value,
            store_id=body.store_id,
            parent_target_id=body.parent_target_id,
            notes=body.notes,
        )
        return _ok(_serialize_target(target))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{target_id}/decompose")
async def decompose_target(
    target_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _get_tenant_id(request)
    try:
        children = await _service.decompose_target(
            db, tenant_id=tid, year_target_id=target_id
        )
        return _ok(
            {
                "total": len(children),
                "children": [_serialize_target(c) for c in children],
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{target_id}/progress")
async def record_progress(
    target_id: UUID,
    body: RecordProgressRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _get_tenant_id(request)
    try:
        progress = await _service.record_progress(
            db,
            tenant_id=tid,
            target_id=target_id,
            actual_value=body.actual_value,
            source_event_id=body.source_event_id,
        )
        return _ok(_serialize_progress(progress))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
@router.get("/")
async def list_targets(
    request: Request,
    employee_id: UUID | None = Query(default=None),
    period_type: PeriodType | None = Query(default=None),
    active: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _get_tenant_id(request)
    pt_value = period_type.value if period_type else None
    if employee_id is not None:
        rows = await _service._repo.list_by_employee_and_period(
            db,
            tenant_id=tid,
            employee_id=employee_id,
            period_type=pt_value,
            active_only=active,
        )
    else:
        rows = await _service._repo.list_active_targets(
            db,
            tenant_id=tid,
            period_type=pt_value,
        )
    return _ok({"items": [_serialize_target(r) for r in rows], "total": len(rows)})


@router.get("/leaderboard")
async def leaderboard(
    request: Request,
    period: PeriodType = Query(
        default=PeriodType.MONTH, description="周期粒度"
    ),
    metric: MetricType = Query(
        default=MetricType.REVENUE_FEN, description="指标类型"
    ),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _get_tenant_id(request)
    rows = await _service.leaderboard(
        db,
        tenant_id=tid,
        period_type=period,
        metric_type=metric,
        limit=limit,
    )
    return _ok({"items": rows, "total": len(rows)})


@router.get("/{target_id}/achievement")
async def get_achievement(
    target_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _get_tenant_id(request)
    try:
        data = await _service.get_achievement(
            db, tenant_id=tid, target_id=target_id
        )
        return _ok(data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
