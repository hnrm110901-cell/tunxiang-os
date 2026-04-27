from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/civic", tags=["civic-adapters"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class CityActivateRequest(BaseModel):
    store_id: str
    platform_credentials: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/cities")
async def list_supported_cities(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """已支持城市列表"""
    await _set_tenant(db, x_tenant_id)
    try:
        rows = await db.execute(
            text("""
                SELECT city_code, city_name, province, adapter_name,
                       supported_domains, status, activated_at
                FROM civic_city_adapters
                ORDER BY province, city_name
            """)
        )
        items = [dict(r._mapping) for r in rows]
        log.info("supported_cities_listed", count=len(items))
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except SQLAlchemyError as exc:
        log.error("cities_list_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/cities/{city_code}/activate")
async def activate_city(
    city_code: str,
    body: CityActivateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """激活城市对接"""
    await _set_tenant(db, x_tenant_id)
    try:
        # Verify city adapter exists
        adapter = await db.execute(
            text("SELECT id, city_name, adapter_name FROM civic_city_adapters WHERE city_code = :code"),
            {"code": city_code},
        )
        adapter_row = adapter.fetchone()
        if not adapter_row:
            raise HTTPException(status_code=404, detail=f"City adapter for {city_code} not found")

        activation_id = str(uuid4())
        await db.execute(
            text("""
                INSERT INTO civic_city_activations (
                    id, tenant_id, city_code, store_id,
                    adapter_id, platform_credentials, status, created_at
                ) VALUES (
                    :id, :tid, :code, :sid,
                    :aid, :creds, 'activating', NOW()
                )
            """),
            {
                "id": activation_id,
                "tid": x_tenant_id,
                "code": city_code,
                "sid": body.store_id,
                "aid": str(adapter_row.id),
                "creds": body.platform_credentials,
            },
        )
        await db.commit()
        log.info(
            "city_activation_started",
            activation_id=activation_id,
            city_code=city_code,
            store_id=body.store_id,
        )
        return {
            "ok": True,
            "data": {
                "activation_id": activation_id,
                "city_code": city_code,
                "city_name": adapter_row.city_name,
                "adapter_name": adapter_row.adapter_name,
                "status": "activating",
            },
        }
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("city_activation_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/adapters/health")
async def get_adapters_health(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """适配器健康状态"""
    await _set_tenant(db, x_tenant_id)
    try:
        rows = await db.execute(
            text("""
                SELECT
                    ca.city_code,
                    ca.city_name,
                    ca.adapter_name,
                    ca.status AS adapter_status,
                    act.store_id,
                    act.status AS activation_status,
                    act.last_heartbeat_at,
                    act.error_count
                FROM civic_city_adapters ca
                LEFT JOIN civic_city_activations act
                    ON ca.city_code = act.city_code AND act.tenant_id = :tid
                ORDER BY ca.city_code
            """),
            {"tid": x_tenant_id},
        )
        items = [dict(r._mapping) for r in rows]

        healthy = sum(1 for i in items if i.get("activation_status") == "active")
        unhealthy = sum(1 for i in items if i.get("activation_status") in ("error", "timeout"))
        inactive = sum(1 for i in items if i.get("activation_status") is None)

        log.info("adapters_health_checked", healthy=healthy, unhealthy=unhealthy)
        return {
            "ok": True,
            "data": {
                "summary": {
                    "healthy": healthy,
                    "unhealthy": unhealthy,
                    "inactive": inactive,
                    "total": len(items),
                },
                "adapters": items,
            },
        }
    except SQLAlchemyError as exc:
        log.error("adapters_health_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")
