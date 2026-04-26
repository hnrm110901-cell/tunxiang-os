from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/forge/runtime", tags=["运行时策略"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class ForgeRuntimeService:
    """运行时策略服务 — 策略 / 熔断 / 违规."""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def get_policy(self, app_id: str) -> Dict[str, Any]:
        row = await self.db.execute(
            text("SELECT * FROM forge.runtime_policies WHERE tenant_id = :tid AND app_id = :app_id"),
            {"tid": self.tenant_id, "app_id": app_id},
        )
        result = row.mappings().first()
        if not result:
            raise HTTPException(status_code=404, detail="runtime policy not found")
        return dict(result)

    async def update_policy(self, app_id: str, policy: Dict[str, Any]) -> Dict[str, Any]:
        sets, params = [], {"tid": self.tenant_id, "app_id": app_id}
        for field in (
            "allowed_entities",
            "allowed_actions",
            "denied_actions",
            "token_budget_daily",
            "rate_limit_rpm",
            "sandbox_mode",
        ):
            if field in policy:
                if field in ("allowed_entities", "allowed_actions", "denied_actions"):
                    sets.append(f"{field} = :{field}::jsonb")
                else:
                    sets.append(f"{field} = :{field}")
                params[field] = str(policy[field]) if isinstance(policy[field], (dict, list)) else policy[field]
        if not sets:
            raise HTTPException(status_code=400, detail="no fields to update")
        sets.append("updated_at = NOW()")
        result = await self.db.execute(
            text(f"""UPDATE forge.runtime_policies SET {", ".join(sets)}
                     WHERE tenant_id = :tid AND app_id = :app_id RETURNING *"""),
            params,
        )
        await self.db.commit()
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="runtime policy not found")
        return dict(row)

    async def activate_kill_switch(self, app_id: str, reason: str, operator_id: str) -> Dict[str, Any]:
        result = await self.db.execute(
            text("""UPDATE forge.runtime_policies
                    SET kill_switch = TRUE, kill_reason = :reason, kill_operator = :op, kill_at = NOW(), updated_at = NOW()
                    WHERE tenant_id = :tid AND app_id = :app_id RETURNING *"""),
            {"tid": self.tenant_id, "app_id": app_id, "reason": reason, "op": operator_id},
        )
        await self.db.commit()
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="app not found")
        log.warning("kill_switch_activated", app_id=app_id, reason=reason, operator=operator_id)
        return dict(row)

    async def deactivate_kill_switch(self, app_id: str) -> Dict[str, Any]:
        result = await self.db.execute(
            text("""UPDATE forge.runtime_policies
                    SET kill_switch = FALSE, kill_reason = NULL, kill_operator = NULL, kill_at = NULL, updated_at = NOW()
                    WHERE tenant_id = :tid AND app_id = :app_id RETURNING *"""),
            {"tid": self.tenant_id, "app_id": app_id},
        )
        await self.db.commit()
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="app not found")
        log.info("kill_switch_deactivated", app_id=app_id)
        return dict(row)

    async def get_violations(
        self,
        app_id: Optional[str],
        severity: Optional[str],
        resolved: Optional[bool],
        page: int,
        size: int,
    ) -> Dict[str, Any]:
        clauses, params = ["tenant_id = :tid"], {"tid": self.tenant_id, "limit": size, "offset": (page - 1) * size}
        if app_id:
            clauses.append("app_id = :app_id")
            params["app_id"] = app_id
        if severity:
            clauses.append("severity = :severity")
            params["severity"] = severity
        if resolved is not None:
            clauses.append("resolved = :resolved")
            params["resolved"] = resolved
        where = " AND ".join(clauses)
        rows = await self.db.execute(
            text(
                f"SELECT * FROM forge.runtime_violations WHERE {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        total_row = await self.db.execute(text(f"SELECT count(*) FROM forge.runtime_violations WHERE {where}"), params)
        return {
            "items": [dict(r) for r in rows.mappings().all()],
            "total": total_row.scalar(),
            "page": page,
            "size": size,
        }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/{app_id}/policy")
async def get_policy(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """查询运行时策略."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeRuntimeService(db, x_tenant_id)
    return await svc.get_policy(app_id)


@router.put("/{app_id}/policy")
async def update_policy(
    app_id: str,
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """更新运行时策略."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeRuntimeService(db, x_tenant_id)
    return await svc.update_policy(app_id, body)


@router.post("/{app_id}/kill")
async def activate_kill_switch(
    app_id: str,
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
    x_user_id: str = Header(...),
) -> Dict[str, Any]:
    """紧急熔断."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeRuntimeService(db, x_tenant_id)
    return await svc.activate_kill_switch(app_id, reason=body["reason"], operator_id=x_user_id)


@router.delete("/{app_id}/kill")
async def deactivate_kill_switch(
    app_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """解除熔断."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeRuntimeService(db, x_tenant_id)
    return await svc.deactivate_kill_switch(app_id)


@router.get("/violations")
async def get_violations(
    app_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    resolved: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """违规记录列表."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeRuntimeService(db, x_tenant_id)
    return await svc.get_violations(app_id, severity, resolved, page, size)
