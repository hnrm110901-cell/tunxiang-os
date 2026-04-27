"""Agent Registry API 路由 — 模板/版本/部署管理

prefix: /api/v1/agent-registry

端点列表：
  # 模板
  POST   /templates                          — 创建模板
  GET    /templates                          — 列出模板（分页+过滤）
  GET    /templates/{template_id}            — 获取单个模板
  PUT    /templates/{template_id}            — 更新模板
  POST   /templates/{template_id}/activate   — 激活模板
  POST   /templates/{template_id}/deprecate  — 废弃模板

  # 版本
  POST   /templates/{template_id}/versions          — 创建版本
  GET    /templates/{template_id}/versions           — 列出版本
  POST   /versions/{version_id}/publish              — 发布版本
  POST   /templates/{template_id}/versions/rollback  — 回滚版本

  # 部署
  POST   /deployments                        — 部署
  GET    /deployments                        — 列出部署
  PUT    /deployments/{deployment_id}        — 更新部署
  DELETE /deployments/{deployment_id}        — 取消部署

  # 查询
  GET    /stores/{store_id}/active-agents    — 获取门店激活的 Agent
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.agent_registry_service import (
    AgentRegistryService,
    CreateDeploymentRequest,
    CreateTemplateRequest,
    CreateVersionRequest,
    UpdateDeploymentRequest,
    UpdateTemplateRequest,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/agent-registry", tags=["agent-registry"])


# ─────────────────────────────────────────────────────────────────────────────
# 依赖注入
# ─────────────────────────────────────────────────────────────────────────────


async def _get_db(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─────────────────────────────────────────────────────────────────────────────
# 辅助：统一序列化 ORM 对象
# ─────────────────────────────────────────────────────────────────────────────


def _serialize_template(t: Any) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "tenant_id": str(t.tenant_id),
        "name": t.name,
        "display_name": t.display_name,
        "description": t.description,
        "category": t.category,
        "priority": t.priority,
        "run_location": t.run_location,
        "agent_level": t.agent_level,
        "config_json": t.config_json,
        "model_preference": t.model_preference,
        "tool_whitelist": t.tool_whitelist,
        "status": t.status,
        "created_by": t.created_by,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _serialize_version(v: Any) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "tenant_id": str(v.tenant_id),
        "template_id": str(v.template_id),
        "version_tag": v.version_tag,
        "skill_yaml_snapshot": v.skill_yaml_snapshot,
        "prompt_snapshot": v.prompt_snapshot,
        "changelog": v.changelog,
        "is_active": v.is_active,
        "published_at": v.published_at.isoformat() if v.published_at else None,
        "published_by": v.published_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


def _serialize_deployment(d: Any) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "tenant_id": str(d.tenant_id),
        "template_id": str(d.template_id),
        "version_id": str(d.version_id),
        "scope_type": d.scope_type,
        "scope_id": str(d.scope_id),
        "enabled": d.enabled,
        "rollout_percent": d.rollout_percent,
        "allowed_actions": d.allowed_actions,
        "config_overrides": d.config_overrides,
        "deployed_at": d.deployed_at.isoformat() if d.deployed_at else None,
        "deployed_by": d.deployed_by,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 模板路由
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/templates")
async def create_template(
    body: CreateTemplateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """创建 Agent 模板"""
    svc = AgentRegistryService(db)
    try:
        template = await svc.create_template(x_tenant_id, body)
        await db.commit()
        return {"ok": True, "data": _serialize_template(template)}
    except ValueError as exc:
        return {"ok": False, "data": None, "error": str(exc)}


@router.get("/templates")
async def list_templates(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
    category: str | None = Query(default=None, description="按分类过滤"),
    status: str | None = Query(default=None, description="按状态过滤(draft/active/deprecated)"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """列出模板（分页+过滤）"""
    svc = AgentRegistryService(db)
    items, total = await svc.list_templates(
        x_tenant_id,
        category=category,
        status=status,
        page=page,
        size=size,
    )
    return {
        "ok": True,
        "data": {
            "items": [_serialize_template(t) for t in items],
            "total": total,
        },
    }


@router.get("/templates/{template_id}")
async def get_template(
    template_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """获取单个模板"""
    svc = AgentRegistryService(db)
    template = await svc.get_template(x_tenant_id, template_id)
    if template is None:
        return {"ok": False, "data": None, "error": f"模板 {template_id} 不存在"}
    return {"ok": True, "data": _serialize_template(template)}


@router.put("/templates/{template_id}")
async def update_template(
    template_id: UUID,
    body: UpdateTemplateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """更新 Agent 模板"""
    svc = AgentRegistryService(db)
    try:
        template = await svc.update_template(x_tenant_id, template_id, body)
        await db.commit()
        return {"ok": True, "data": _serialize_template(template)}
    except ValueError as exc:
        return {"ok": False, "data": None, "error": str(exc)}


@router.post("/templates/{template_id}/activate")
async def activate_template(
    template_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """激活模板（draft -> active）"""
    svc = AgentRegistryService(db)
    try:
        template = await svc.activate_template(x_tenant_id, template_id)
        await db.commit()
        return {"ok": True, "data": _serialize_template(template)}
    except ValueError as exc:
        return {"ok": False, "data": None, "error": str(exc)}


@router.post("/templates/{template_id}/deprecate")
async def deprecate_template(
    template_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """废弃模板（active -> deprecated）"""
    svc = AgentRegistryService(db)
    try:
        template = await svc.deprecate_template(x_tenant_id, template_id)
        await db.commit()
        return {"ok": True, "data": _serialize_template(template)}
    except ValueError as exc:
        return {"ok": False, "data": None, "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# 版本路由
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/templates/{template_id}/versions")
async def create_version(
    template_id: UUID,
    body: CreateVersionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """创建新版本"""
    svc = AgentRegistryService(db)
    try:
        version = await svc.create_version(x_tenant_id, template_id, body)
        await db.commit()
        return {"ok": True, "data": _serialize_version(version)}
    except ValueError as exc:
        return {"ok": False, "data": None, "error": str(exc)}


@router.get("/templates/{template_id}/versions")
async def list_versions(
    template_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """列出某模板的所有版本"""
    svc = AgentRegistryService(db)
    versions = await svc.list_versions(x_tenant_id, template_id)
    return {"ok": True, "data": [_serialize_version(v) for v in versions]}


class PublishVersionBody(BaseModel):
    published_by: str


@router.post("/versions/{version_id}/publish")
async def publish_version(
    version_id: UUID,
    body: PublishVersionBody,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """发布版本（设 is_active=True，同模板下其他版本设为 False）"""
    svc = AgentRegistryService(db)
    try:
        version = await svc.publish_version(x_tenant_id, version_id, body.published_by)
        await db.commit()
        return {"ok": True, "data": _serialize_version(version)}
    except ValueError as exc:
        return {"ok": False, "data": None, "error": str(exc)}


class RollbackVersionBody(BaseModel):
    target_version_id: UUID


@router.post("/templates/{template_id}/versions/rollback")
async def rollback_version(
    template_id: UUID,
    body: RollbackVersionBody,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """回滚到指定版本"""
    svc = AgentRegistryService(db)
    try:
        version = await svc.rollback_version(x_tenant_id, template_id, body.target_version_id)
        await db.commit()
        return {"ok": True, "data": _serialize_version(version)}
    except ValueError as exc:
        return {"ok": False, "data": None, "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# 部署路由
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/deployments")
async def deploy(
    body: CreateDeploymentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """部署 Agent 到指定范围"""
    svc = AgentRegistryService(db)
    try:
        deployment = await svc.deploy(x_tenant_id, body)
        await db.commit()
        return {"ok": True, "data": _serialize_deployment(deployment)}
    except ValueError as exc:
        return {"ok": False, "data": None, "error": str(exc)}


@router.get("/deployments")
async def list_deployments(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
    template_id: UUID | None = Query(default=None, description="按模板过滤"),
    scope_type: str | None = Query(default=None, description="按范围类型过滤"),
    scope_id: UUID | None = Query(default=None, description="按范围ID过滤"),
) -> dict[str, Any]:
    """列出部署"""
    svc = AgentRegistryService(db)
    deployments = await svc.list_deployments(
        x_tenant_id,
        template_id=template_id,
        scope_type=scope_type,
        scope_id=scope_id,
    )
    return {"ok": True, "data": [_serialize_deployment(d) for d in deployments]}


@router.put("/deployments/{deployment_id}")
async def update_deployment(
    deployment_id: UUID,
    body: UpdateDeploymentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """更新部署配置"""
    svc = AgentRegistryService(db)
    try:
        deployment = await svc.update_deployment(x_tenant_id, deployment_id, body)
        await db.commit()
        return {"ok": True, "data": _serialize_deployment(deployment)}
    except ValueError as exc:
        return {"ok": False, "data": None, "error": str(exc)}


@router.delete("/deployments/{deployment_id}")
async def undeploy(
    deployment_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """取消部署"""
    svc = AgentRegistryService(db)
    try:
        await svc.undeploy(x_tenant_id, deployment_id)
        await db.commit()
        return {"ok": True, "data": None}
    except ValueError as exc:
        return {"ok": False, "data": None, "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# 门店查询
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/stores/{store_id}/active-agents")
async def get_active_agents_for_store(
    store_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """获取某门店当前激活的所有 Agent（考虑灰度比例）"""
    svc = AgentRegistryService(db)
    agents = await svc.get_active_agents_for_store(x_tenant_id, store_id)
    return {"ok": True, "data": agents}
