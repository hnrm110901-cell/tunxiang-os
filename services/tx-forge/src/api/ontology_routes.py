from __future__ import annotations
from typing import Any, Dict, Optional
from uuid import UUID
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/forge/ontology", tags=["Ontology绑定"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class ForgeOntologyService:
    """Ontology 绑定服务 — 实体绑定 / 清单校验."""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def get_bindings(self, app_id: Optional[str], entity: Optional[str]) -> list[Dict[str, Any]]:
        clauses, params = ["tenant_id = :tid"], {"tid": self.tenant_id}
        if app_id:
            clauses.append("app_id = :app_id"); params["app_id"] = app_id
        if entity:
            clauses.append("entity_name = :entity"); params["entity"] = entity
        where = " AND ".join(clauses)
        rows = await self.db.execute(
            text(f"SELECT * FROM forge.ontology_bindings WHERE {where} ORDER BY entity_name, app_id"),
            params,
        )
        return [dict(r) for r in rows.mappings().all()]

    async def set_binding(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.db.execute(
            text("""INSERT INTO forge.ontology_bindings
                    (tenant_id, app_id, entity_name, access_mode, allowed_fields, constraints)
                    VALUES (:tid, :app_id, :entity_name, :access_mode, :allowed_fields::jsonb, :constraints::jsonb)
                    ON CONFLICT (tenant_id, app_id, entity_name)
                    DO UPDATE SET access_mode = EXCLUDED.access_mode,
                                  allowed_fields = EXCLUDED.allowed_fields,
                                  constraints = EXCLUDED.constraints,
                                  updated_at = NOW()
                    RETURNING *"""),
            {
                "tid": self.tenant_id,
                "app_id": payload["app_id"],
                "entity_name": payload["entity_name"],
                "access_mode": payload["access_mode"],
                "allowed_fields": str(payload.get("allowed_fields", [])),
                "constraints": str(payload.get("constraints", {})),
            },
        )
        await self.db.commit()
        return dict(result.mappings().one())

    async def get_entity_apps(self, entity: str) -> list[Dict[str, Any]]:
        rows = await self.db.execute(
            text("""SELECT ob.*, a.name AS app_name
                    FROM forge.ontology_bindings ob
                    LEFT JOIN forge.apps a ON a.id = ob.app_id AND a.tenant_id = ob.tenant_id
                    WHERE ob.tenant_id = :tid AND ob.entity_name = :entity
                    ORDER BY ob.app_id"""),
            {"tid": self.tenant_id, "entity": entity},
        )
        return [dict(r) for r in rows.mappings().all()]

    async def validate_manifest(self, app_id: str, manifest_content: Dict[str, Any]) -> Dict[str, Any]:
        errors: list[str] = []
        required_keys = ("name", "version", "permissions", "ontology_bindings")
        for key in required_keys:
            if key not in manifest_content:
                errors.append(f"missing required key: {key}")
        if "permissions" in manifest_content:
            valid_permissions = {"read", "write", "delete", "execute"}
            for perm in manifest_content["permissions"]:
                if perm not in valid_permissions:
                    errors.append(f"invalid permission: {perm}")
        if "ontology_bindings" in manifest_content:
            valid_entities = {"Store", "Order", "Customer", "Dish", "Ingredient", "Employee"}
            for binding in manifest_content["ontology_bindings"]:
                entity = binding.get("entity") if isinstance(binding, dict) else None
                if entity and entity not in valid_entities:
                    errors.append(f"invalid ontology entity: {entity}")
        return {"app_id": app_id, "valid": len(errors) == 0, "errors": errors}

    async def submit_manifest(self, app_id: str, manifest_content: Dict[str, Any]) -> Dict[str, Any]:
        validation = await self.validate_manifest(app_id, manifest_content)
        if not validation["valid"]:
            raise HTTPException(status_code=422, detail={"errors": validation["errors"]})
        result = await self.db.execute(
            text("""INSERT INTO forge.app_manifests
                    (tenant_id, app_id, manifest, status)
                    VALUES (:tid, :app_id, :manifest::jsonb, 'submitted')
                    ON CONFLICT (tenant_id, app_id)
                    DO UPDATE SET manifest = EXCLUDED.manifest, status = 'submitted', updated_at = NOW()
                    RETURNING *"""),
            {"tid": self.tenant_id, "app_id": app_id, "manifest": str(manifest_content)},
        )
        await self.db.commit()
        return dict(result.mappings().one())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/bindings")
async def get_bindings(
    app_id: Optional[str] = Query(None),
    entity: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> list[Dict[str, Any]]:
    """实体绑定矩阵."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeOntologyService(db, x_tenant_id)
    return await svc.get_bindings(app_id, entity)


@router.put("/bindings")
async def set_binding(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """设置/更新绑定."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeOntologyService(db, x_tenant_id)
    return await svc.set_binding(body)


@router.get("/{entity}/apps")
async def get_entity_apps(
    entity: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> list[Dict[str, Any]]:
    """操作某实体的所有应用."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeOntologyService(db, x_tenant_id)
    return await svc.get_entity_apps(entity)


@router.post("/manifest/validate")
async def validate_manifest(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """清单格式校验."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeOntologyService(db, x_tenant_id)
    return await svc.validate_manifest(body["app_id"], body["manifest_content"])


@router.post("/manifest/submit")
async def submit_manifest(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """提交清单."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeOntologyService(db, x_tenant_id)
    return await svc.submit_manifest(body["app_id"], body["manifest_content"])
