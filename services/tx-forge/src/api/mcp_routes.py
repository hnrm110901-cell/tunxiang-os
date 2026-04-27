from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/forge/mcp", tags=["MCP协议"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class ForgeMCPService:
    """MCP 协议服务 — Server 注册 / Tool 目录."""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def register_server(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.db.execute(
            text("""INSERT INTO forge.mcp_servers
                    (tenant_id, app_id, server_name, transport, base_url, capabilities, health_endpoint)
                    VALUES (:tid, :app_id, :server_name, :transport, :base_url, :capabilities::jsonb, :health_endpoint)
                    RETURNING *"""),
            {
                "tid": self.tenant_id,
                "app_id": payload["app_id"],
                "server_name": payload["server_name"],
                "transport": payload.get("transport", "stdio"),
                "base_url": payload.get("base_url"),
                "capabilities": str(payload.get("capabilities", {})),
                "health_endpoint": payload.get("health_endpoint"),
            },
        )
        await self.db.commit()
        return dict(result.mappings().one())

    async def list_servers(
        self,
        app_id: Optional[str],
        health_status: Optional[str],
        page: int,
        size: int,
    ) -> Dict[str, Any]:
        clauses, params = ["tenant_id = :tid"], {"tid": self.tenant_id, "limit": size, "offset": (page - 1) * size}
        if app_id:
            clauses.append("app_id = :app_id")
            params["app_id"] = app_id
        if health_status:
            clauses.append("health_status = :hs")
            params["hs"] = health_status
        where = " AND ".join(clauses)
        rows = await self.db.execute(
            text(f"SELECT * FROM forge.mcp_servers WHERE {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
            params,
        )
        total_row = await self.db.execute(text(f"SELECT count(*) FROM forge.mcp_servers WHERE {where}"), params)
        return {
            "items": [dict(r) for r in rows.mappings().all()],
            "total": total_row.scalar(),
            "page": page,
            "size": size,
        }

    async def get_server(self, server_id: str) -> Dict[str, Any]:
        row = await self.db.execute(
            text("SELECT * FROM forge.mcp_servers WHERE tenant_id = :tid AND id = :sid"),
            {"tid": self.tenant_id, "sid": server_id},
        )
        result = row.mappings().first()
        if not result:
            raise HTTPException(status_code=404, detail="MCP server not found")
        return dict(result)

    async def list_tools(
        self,
        server_id: Optional[str],
        entity: Optional[str],
        trust_tier: Optional[str],
        page: int,
        size: int,
    ) -> Dict[str, Any]:
        clauses, params = ["tenant_id = :tid"], {"tid": self.tenant_id, "limit": size, "offset": (page - 1) * size}
        if server_id:
            clauses.append("server_id = :server_id")
            params["server_id"] = server_id
        if entity:
            clauses.append("ontology_bindings ? :entity")
            params["entity"] = entity
        if trust_tier:
            clauses.append("trust_tier_required = :tier")
            params["tier"] = trust_tier
        where = " AND ".join(clauses)
        rows = await self.db.execute(
            text(f"SELECT * FROM forge.mcp_tools WHERE {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
            params,
        )
        total_row = await self.db.execute(text(f"SELECT count(*) FROM forge.mcp_tools WHERE {where}"), params)
        return {
            "items": [dict(r) for r in rows.mappings().all()],
            "total": total_row.scalar(),
            "page": page,
            "size": size,
        }

    async def get_tool_schema(self, tool_id: str) -> Dict[str, Any]:
        row = await self.db.execute(
            text(
                "SELECT id, tool_name, input_schema, ontology_bindings, trust_tier_required FROM forge.mcp_tools WHERE tenant_id = :tid AND id = :tool_id"
            ),
            {"tid": self.tenant_id, "tool_id": tool_id},
        )
        result = row.mappings().first()
        if not result:
            raise HTTPException(status_code=404, detail="MCP tool not found")
        return dict(result)

    async def register_tool(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.db.execute(
            text("""INSERT INTO forge.mcp_tools
                    (tenant_id, server_id, tool_name, description, input_schema, ontology_bindings, trust_tier_required)
                    VALUES (:tid, :server_id, :tool_name, :description, :input_schema::jsonb, :ontology_bindings::jsonb, :trust_tier_required)
                    RETURNING *"""),
            {
                "tid": self.tenant_id,
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "description": payload.get("description"),
                "input_schema": str(payload.get("input_schema", {})),
                "ontology_bindings": str(payload.get("ontology_bindings", {})),
                "trust_tier_required": payload.get("trust_tier_required", "basic"),
            },
        )
        await self.db.commit()
        return dict(result.mappings().one())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/servers")
async def register_server(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """注册 MCP Server."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeMCPService(db, x_tenant_id)
    return await svc.register_server(body)


@router.get("/servers")
async def list_servers(
    app_id: Optional[str] = Query(None),
    health_status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """MCP Server 列表."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeMCPService(db, x_tenant_id)
    return await svc.list_servers(app_id, health_status, page, size)


@router.get("/servers/{server_id}")
async def get_server(
    server_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """Server 详情."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeMCPService(db, x_tenant_id)
    return await svc.get_server(server_id)


@router.get("/tools")
async def list_tools(
    server_id: Optional[str] = Query(None),
    entity: Optional[str] = Query(None),
    trust_tier: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """MCP Tool 目录."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeMCPService(db, x_tenant_id)
    return await svc.list_tools(server_id, entity, trust_tier, page, size)


@router.get("/tools/{tool_id}/schema")
async def get_tool_schema(
    tool_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """工具 Schema."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeMCPService(db, x_tenant_id)
    return await svc.get_tool_schema(tool_id)


@router.post("/tools")
async def register_tool(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """注册新 Tool."""
    await _set_tenant(db, x_tenant_id)
    svc = ForgeMCPService(db, x_tenant_id)
    return await svc.register_tool(body)
