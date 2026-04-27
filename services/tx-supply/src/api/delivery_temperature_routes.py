"""配送在途温控告警 API (TASK-3 / v368)

8 个端点（响应统一 {ok, data, error}）：
  POST /api/v1/supply/delivery/{id}/temperature                      上报（单条/批量）
  GET  /api/v1/supply/delivery/{id}/temperature/timeline             时序查询
  GET  /api/v1/supply/delivery/{id}/temperature/summary              摘要
  GET  /api/v1/supply/delivery/{id}/temperature/proof                温度凭证（签收对比）
  GET  /api/v1/supply/delivery/temperature-alerts/active             活跃告警列表
  POST /api/v1/supply/delivery/temperature-alerts/{id}/handle        处理告警
  POST /api/v1/supply/delivery/temperature-thresholds                创建阈值
  GET  /api/v1/supply/delivery/temperature-thresholds                列出阈值
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Union

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..models.delivery_temperature import (
    AlertHandlePayload,
    ScopeType,
    Source,
    TemperatureRecord,
    ThresholdCreate,
)
from ..services import delivery_temperature_service as svc

router = APIRouter(prefix="/api/v1/supply/delivery", tags=["delivery-temperature"])


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(code: int, message: str) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}


# ─── 请求体（接受单条 or 批量）─────────────────────────────────────────


class _TempPayload(BaseModel):
    """单条 or 批量"""

    record: Optional[TemperatureRecord] = None
    records: Optional[list[TemperatureRecord]] = Field(default=None, max_length=2000)


# ════════════════════════════════════════════════════════════════════
#  上报：POST /{id}/temperature
# ════════════════════════════════════════════════════════════════════


@router.post("/{delivery_id}/temperature")
async def post_temperature(
    delivery_id: str,
    payload: Union[TemperatureRecord, list[TemperatureRecord], _TempPayload] = Body(...),
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """温度上报：body 支持单条对象 / 数组 / {record} / {records}。"""
    # 标准化为 list[TemperatureRecord]
    items: list[TemperatureRecord] = []
    if isinstance(payload, TemperatureRecord):
        items = [payload]
    elif isinstance(payload, list):
        items = payload
    elif isinstance(payload, _TempPayload):
        if payload.record is not None:
            items = [payload.record]
        elif payload.records is not None:
            items = payload.records
    else:
        raise HTTPException(status_code=422, detail="body 必须是 TemperatureRecord / 数组 / {record|records}")

    if not items:
        raise HTTPException(status_code=422, detail="records 不能为空")

    try:
        if len(items) == 1:
            r = items[0]
            result = await svc.record_temperature(
                tenant_id=x_tenant_id,
                delivery_id=delivery_id,
                temperature_celsius=r.temperature_celsius,
                recorded_at=r.recorded_at,
                humidity_percent=r.humidity_percent,
                gps_lat=r.gps_lat,
                gps_lng=r.gps_lng,
                device_id=r.device_id,
                source=r.source.value if isinstance(r.source, Source) else r.source,
                extra=r.extra,
                db=db,
            )
        else:
            result = await svc.record_temperatures_batch(
                tenant_id=x_tenant_id,
                delivery_id=delivery_id,
                records=[r.model_dump() for r in items],
                db=db,
            )
        await db.commit()
        return _ok(result)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))


# ════════════════════════════════════════════════════════════════════
#  时序查询
# ════════════════════════════════════════════════════════════════════


@router.get("/{delivery_id}/temperature/timeline")
async def get_timeline(
    delivery_id: str,
    from_at: Optional[datetime] = Query(default=None, alias="from"),
    to_at: Optional[datetime] = Query(default=None, alias="to"),
    limit: int = Query(default=5000, ge=1, le=10000),
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    rows = await svc.get_timeline(
        tenant_id=x_tenant_id,
        delivery_id=delivery_id,
        from_at=from_at,
        to_at=to_at,
        limit=limit,
        db=db,
    )
    return _ok({"delivery_id": delivery_id, "items": rows, "count": len(rows)})


# ════════════════════════════════════════════════════════════════════
#  摘要 / 凭证
# ════════════════════════════════════════════════════════════════════


@router.get("/{delivery_id}/temperature/summary")
async def get_summary(
    delivery_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    result = await svc.get_summary(tenant_id=x_tenant_id, delivery_id=delivery_id, db=db)
    return _ok(result)


@router.get("/{delivery_id}/temperature/proof")
async def get_proof(
    delivery_id: str,
    sample_step: int = Query(default=60, ge=1, le=3600),
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    result = await svc.get_temperature_proof(
        tenant_id=x_tenant_id,
        delivery_id=delivery_id,
        db=db,
        sample_step=sample_step,
    )
    return _ok(result)


# ════════════════════════════════════════════════════════════════════
#  告警
# ════════════════════════════════════════════════════════════════════


@router.get("/temperature-alerts/active")
async def list_active_alerts(
    severity: Optional[str] = Query(default=None, description="INFO|WARNING|CRITICAL"),
    limit: int = Query(default=200, ge=1, le=1000),
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    rows = await svc.list_active_alerts(
        tenant_id=x_tenant_id, severity=severity, limit=limit, db=db
    )
    return _ok({"items": rows, "count": len(rows)})


@router.post("/temperature-alerts/{alert_id}/handle")
async def handle_alert(
    alert_id: str,
    body: AlertHandlePayload,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await svc.handle_alert(
            tenant_id=x_tenant_id,
            alert_id=alert_id,
            action=body.action,
            comment=body.comment,
            handled_by=body.handled_by,
            db=db,
        )
        await db.commit()
        return _ok(result)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))


# ════════════════════════════════════════════════════════════════════
#  阈值配置
# ════════════════════════════════════════════════════════════════════


@router.post("/temperature-thresholds")
async def create_threshold(
    body: ThresholdCreate,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await svc.create_threshold(
            tenant_id=x_tenant_id,
            scope_type=body.scope_type.value if isinstance(body.scope_type, ScopeType) else body.scope_type,
            scope_value=body.scope_value,
            min_temp_celsius=body.min_temp_celsius,
            max_temp_celsius=body.max_temp_celsius,
            alert_min_seconds=body.alert_min_seconds,
            enabled=body.enabled,
            description=body.description,
            db=db,
        )
        await db.commit()
        return _ok(result)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/temperature-thresholds")
async def list_thresholds(
    enabled_only: bool = Query(default=False),
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    rows = await svc.list_thresholds(
        tenant_id=x_tenant_id, enabled_only=enabled_only, db=db
    )
    return _ok({"items": rows, "count": len(rows)})
