from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/civic/kitchen", tags=["civic-kitchen"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class DeviceCreate(BaseModel):
    store_id: str
    device_name: str
    device_type: str
    device_brand: Optional[str] = None
    device_model: Optional[str] = None
    serial_no: Optional[str] = None
    stream_url: Optional[str] = None
    stream_protocol: Optional[str] = None
    ai_enabled: bool = False
    ai_capabilities: List[str] = Field(default_factory=list)
    location_desc: Optional[str] = None


class AlertResolve(BaseModel):
    resolved_by: str
    resolution_notes: Optional[str] = None
    false_positive: bool = False


class StreamRegister(BaseModel):
    store_id: str
    device_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/devices")
async def create_device(
    body: DeviceCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """注册设备"""
    await _set_tenant(db, x_tenant_id)
    device_id = str(uuid4())
    try:
        await db.execute(
            text("""
                INSERT INTO civic_kitchen_devices (
                    id, tenant_id, store_id, device_name, device_type,
                    device_brand, device_model, serial_no, stream_url,
                    stream_protocol, ai_enabled, ai_capabilities, location_desc,
                    status, created_at
                ) VALUES (
                    :id, :tenant_id, :store_id, :device_name, :device_type,
                    :device_brand, :device_model, :serial_no, :stream_url,
                    :stream_protocol, :ai_enabled, :ai_capabilities, :location_desc,
                    'online', NOW()
                )
            """),
            {
                "id": device_id,
                "tenant_id": x_tenant_id,
                "store_id": body.store_id,
                "device_name": body.device_name,
                "device_type": body.device_type,
                "device_brand": body.device_brand,
                "device_model": body.device_model,
                "serial_no": body.serial_no,
                "stream_url": body.stream_url,
                "stream_protocol": body.stream_protocol,
                "ai_enabled": body.ai_enabled,
                "ai_capabilities": body.ai_capabilities,
                "location_desc": body.location_desc,
            },
        )
        await db.commit()
        log.info("kitchen_device_created", device_id=device_id, store_id=body.store_id)
        return {"ok": True, "data": {"id": device_id}}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("kitchen_device_create_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/devices")
async def list_devices(
    store_id: str = Query(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """设备列表"""
    await _set_tenant(db, x_tenant_id)
    try:
        rows = await db.execute(
            text(
                "SELECT * FROM civic_kitchen_devices "
                "WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = FALSE "
                "ORDER BY created_at DESC"
            ),
            {"tid": x_tenant_id, "sid": store_id},
        )
        items = [dict(r._mapping) for r in rows]
        log.info("kitchen_devices_listed", store_id=store_id, count=len(items))
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except SQLAlchemyError as exc:
        log.error("kitchen_devices_list_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/alerts")
async def list_alerts(
    store_id: Optional[str] = Query(None),
    resolved: Optional[bool] = Query(None),
    alert_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """AI告警列表"""
    await _set_tenant(db, x_tenant_id)
    try:
        conditions = ["tenant_id = :tid"]
        params: Dict[str, Any] = {"tid": x_tenant_id}

        if store_id:
            conditions.append("store_id = :sid")
            params["sid"] = store_id
        if resolved is not None:
            conditions.append("resolved = :resolved")
            params["resolved"] = resolved
        if alert_type:
            conditions.append("alert_type = :atype")
            params["atype"] = alert_type

        where = " AND ".join(conditions)
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM civic_kitchen_alerts WHERE {where}"), params
        )
        total = count_result.scalar() or 0

        rows = await db.execute(
            text(
                f"SELECT * FROM civic_kitchen_alerts WHERE {where} "
                f"ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        items = [dict(r._mapping) for r in rows]
        log.info("kitchen_alerts_listed", total=total)
        return {"ok": True, "data": {"items": items, "total": total}}
    except SQLAlchemyError as exc:
        log.error("kitchen_alerts_list_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    body: AlertResolve,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """处理告警"""
    await _set_tenant(db, x_tenant_id)
    try:
        result = await db.execute(
            text(
                "UPDATE civic_kitchen_alerts SET "
                "resolved = TRUE, resolved_by = :resolved_by, "
                "resolution_notes = :notes, false_positive = :fp, "
                "resolved_at = NOW(), updated_at = NOW() "
                "WHERE id = :id AND tenant_id = :tid"
            ),
            {
                "id": alert_id,
                "tid": x_tenant_id,
                "resolved_by": body.resolved_by,
                "notes": body.resolution_notes,
                "fp": body.false_positive,
            },
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

        await db.commit()
        log.info("kitchen_alert_resolved", alert_id=alert_id)
        return {"ok": True, "data": {"id": alert_id, "resolved": True}}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("kitchen_alert_resolve_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/online-rate")
async def get_online_rate(
    store_id: str = Query(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """设备在线率"""
    await _set_tenant(db, x_tenant_id)
    try:
        total_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM civic_kitchen_devices "
                "WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = FALSE"
            ),
            {"tid": x_tenant_id, "sid": store_id},
        )
        total = total_result.scalar() or 0

        online_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM civic_kitchen_devices "
                "WHERE tenant_id = :tid AND store_id = :sid "
                "AND is_deleted = FALSE AND status = 'online'"
            ),
            {"tid": x_tenant_id, "sid": store_id},
        )
        online = online_result.scalar() or 0

        rate = round((online / total * 100) if total > 0 else 0, 2)
        log.info("kitchen_online_rate", store_id=store_id, rate=rate)
        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "total_devices": total,
                "online_devices": online,
                "online_rate_pct": rate,
            },
        }
    except SQLAlchemyError as exc:
        log.error("kitchen_online_rate_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/stream/register")
async def register_stream(
    body: StreamRegister,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """视频流注册到监管平台"""
    await _set_tenant(db, x_tenant_id)
    try:
        device = await db.execute(
            text(
                "SELECT id, stream_url, stream_protocol FROM civic_kitchen_devices "
                "WHERE tenant_id = :tid AND id = :did AND store_id = :sid"
            ),
            {"tid": x_tenant_id, "did": body.device_id, "sid": body.store_id},
        )
        row = device.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Device {body.device_id} not found")

        registration_id = str(uuid4())
        await db.execute(
            text("""
                INSERT INTO civic_stream_registrations (
                    id, tenant_id, store_id, device_id, stream_url,
                    stream_protocol, platform_status, created_at
                ) VALUES (
                    :id, :tid, :sid, :did, :url, :proto, 'pending', NOW()
                )
            """),
            {
                "id": registration_id,
                "tid": x_tenant_id,
                "sid": body.store_id,
                "did": body.device_id,
                "url": row.stream_url,
                "proto": row.stream_protocol,
            },
        )
        await db.commit()
        log.info("stream_registered", registration_id=registration_id, device_id=body.device_id)
        return {
            "ok": True,
            "data": {
                "registration_id": registration_id,
                "status": "pending",
            },
        }
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("stream_register_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")
