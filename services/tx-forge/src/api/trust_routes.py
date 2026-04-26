from __future__ import annotations
from typing import Any, Dict, Optional
from uuid import UUID
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/forge/trust", tags=["信任管理"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ---------------------------------------------------------------------------
# Service (placeholder – will be replaced by real import once module lands)
# ---------------------------------------------------------------------------
class ForgeTrustService:
    """信任治理服务 — 审计 / 等级 / 升降级."""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def submit_trust_audit(self, app_id: str, requested_tier: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.db.execute(
            text("""INSERT INTO forge.trust_audits
                    (tenant_id, app_id, requested_tier, evidence, status)
                    VALUES (:tid, :app_id, :tier, :evidence::jsonb, 'pending')
                    RETURNING *"""),
            {"tid": self.tenant_id, "app_id": app_id, "tier": requested_tier, "evidence": str(evidence)},
        )
        await self.db.commit()
        return dict(result.mappings().one())

    async def get_tier_definitions(self) -> list[Dict[str, Any]]:
        rows = await self.db.execute(text("SELECT * FROM forge.trust_tiers ORDER BY level ASC"))
        return [dict(r) for r in rows.mappings().all()]

    async def get_app_trust_status(self, app_id: str) -> Dict[str, Any]:
        row = await self.db.execute(
            text("SELECT * FROM forge.app_trust_status WHERE tenant_id = :tid AND app_id = :app_id"),
            {"tid": self.tenant_id, "app_id": app_id},
        )
        result = row.mappings().first()
        if not result:
            raise HTTPException(status_code=404, detail="app trust status not found")
        return dict(result)

    async def request_upgrade(self, app_id: str, target_tier: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.db.execute(
            text("""INSERT INTO forge.trust_upgrade_requests
                    (tenant_id, app_id, target_tier, evidence, status)
                    VALUES (:tid, :app_id, :tier, :evidence::jsonb, 'pending')
                    RETURNING *"""),
            {"tid": self.tenant_id, "app_id": app_id, "tier": target_tier, "evidence": str(evidence)},
        )
        await self.db.commit()
        return dict(result.mappings().one())

    async def auto_downgrade(self, app_id: str, reason: str) -> Dict[str, Any]:
        result = await self.db.execute(
            text("""UPDATE forge.app_trust_status
                    SET current_tier = current_tier - 1, downgrade_reason = :reason, updated_at = NOW()
                    WHERE tenant_id = :tid AND app_id = :app_id
                    RETURNING *"""),
            {"tid": self.tenant_id, "app_id": app_id, "reason": reason},
        )
        await self.db.commit()
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="app not found")
        return dict(row)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/audit")
async def submit_trust_audit(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """提交信任审计."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeTrustService(db, x_tenant_id)
    return await svc.submit_trust_audit(
        app_id=body["app_id"],
        requested_tier=body["requested_tier"],
        evidence=body.get("evidence", {}),
    )


@router.get("/tiers")
async def get_tier_definitions(
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> list[Dict[str, Any]]:
    """查询信任等级定义."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeTrustService(db, x_tenant_id)
    return await svc.get_tier_definitions()


@router.get("/{app_id}/status")
async def get_app_trust_status(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """查询应用信任状态."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeTrustService(db, x_tenant_id)
    return await svc.get_app_trust_status(app_id)


@router.post("/{app_id}/upgrade")
async def request_upgrade(
    app_id: str,
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """申请升级信任等级."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeTrustService(db, x_tenant_id)
    return await svc.request_upgrade(
        app_id=app_id,
        target_tier=body["target_tier"],
        evidence=body.get("evidence", {}),
    )


@router.post("/{app_id}/downgrade")
async def auto_downgrade(
    app_id: str,
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """降级（通常自动触发）."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeTrustService(db, x_tenant_id)
    return await svc.auto_downgrade(app_id=app_id, reason=body["reason"])
