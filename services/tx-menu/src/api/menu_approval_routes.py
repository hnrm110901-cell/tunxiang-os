"""集团菜单下发审批流 API

涵盖：
  - 下发申请管理（创建/查询/审批/拒绝/执行）
  - 门店菜单自主修改权限管理
  - 新店开业一键复制菜单

ROUTER REGISTRATION（在 tx-menu/src/main.py 中添加）：
    from .api.menu_approval_routes import router as menu_approval_router
    app.include_router(menu_approval_router)
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.menu_approval_service import (
    MenuApprovalService,
    StoreMenuPermissionUpdate,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/menu", tags=["menu-approval"])


# ─── DB 依赖占位（与其他路由保持一致） ─────────────────────────────────────────


async def get_db() -> AsyncSession:  # type: ignore[override]
    """数据库会话依赖 — 由 main.py 中 app.dependency_overrides 注入"""
    raise NotImplementedError("DB session dependency not configured")


# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求/响应模型 ────────────────────────────────────────────────────────────


class CreatePublishRequestBody(BaseModel):
    source_type: str
    target_store_ids: list[UUID]
    change_type: str
    change_payload: dict
    created_by: UUID
    expires_hours: int = 48


class ApproveBody(BaseModel):
    approver_id: UUID
    note: str = ""


class RejectBody(BaseModel):
    approver_id: UUID
    note: str


class CloneStoreMenuBody(BaseModel):
    source_store_id: UUID
    target_store_id: UUID


# ─── 下发申请管理 ─────────────────────────────────────────────────────────────


@router.post("/publish-requests")
async def create_publish_request(body: CreatePublishRequestBody, request: Request) -> dict:
    """创建菜单下发申请"""
    tid = _tenant_id(request)
    db: AsyncSession = request.app.state.db_session_factory()
    try:
        svc = MenuApprovalService(db)
        result = await svc.create_publish_request(
            tenant_id=UUID(tid),
            source_type=body.source_type,
            target_store_ids=body.target_store_ids,
            change_type=body.change_type,
            change_payload=body.change_payload,
            created_by=body.created_by,
            expires_hours=body.expires_hours,
        )
        return {"ok": True, "data": result.model_dump(mode="json")}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await db.close()


@router.get("/publish-requests")
async def list_publish_requests(
    request: Request,
    status: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict:
    """获取下发申请列表（分页）"""
    tid = _tenant_id(request)
    db: AsyncSession = request.app.state.db_session_factory()
    try:
        svc = MenuApprovalService(db)
        items, total = await svc.get_requests(
            tenant_id=UUID(tid),
            status=status,
            page=page,
            size=size,
        )
        return {
            "ok": True,
            "data": {
                "items": [item.model_dump(mode="json") for item in items],
                "total": total,
            },
        }
    finally:
        await db.close()


@router.get("/publish-requests/{request_id}")
async def get_publish_request(request_id: UUID, request: Request) -> dict:
    """获取申请详情"""
    tid = _tenant_id(request)
    db: AsyncSession = request.app.state.db_session_factory()
    try:
        svc = MenuApprovalService(db)
        item = await svc.get_request_by_id(request_id=request_id, tenant_id=UUID(tid))
        if item is None:
            raise HTTPException(status_code=404, detail="Publish request not found")
        return {"ok": True, "data": item.model_dump(mode="json")}
    finally:
        await db.close()


@router.post("/publish-requests/{request_id}/approve")
async def approve_publish_request(
    request_id: UUID,
    body: ApproveBody,
    request: Request,
) -> dict:
    """审批通过下发申请"""
    db: AsyncSession = request.app.state.db_session_factory()
    try:
        svc = MenuApprovalService(db)
        result = await svc.approve_request(
            request_id=request_id,
            approver_id=body.approver_id,
            note=body.note,
        )
        return {"ok": True, "data": result.model_dump(mode="json")}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await db.close()


@router.post("/publish-requests/{request_id}/reject")
async def reject_publish_request(
    request_id: UUID,
    body: RejectBody,
    request: Request,
) -> dict:
    """拒绝下发申请"""
    db: AsyncSession = request.app.state.db_session_factory()
    try:
        svc = MenuApprovalService(db)
        result = await svc.reject_request(
            request_id=request_id,
            approver_id=body.approver_id,
            note=body.note,
        )
        return {"ok": True, "data": result.model_dump(mode="json")}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await db.close()


@router.post("/publish-requests/{request_id}/apply")
async def apply_publish_request(request_id: UUID, request: Request) -> dict:
    """执行已批准的菜单变更"""
    db: AsyncSession = request.app.state.db_session_factory()
    try:
        svc = MenuApprovalService(db)
        result = await svc.apply_approved_request(request_id=request_id)
        return {"ok": True, "data": result.model_dump(mode="json")}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await db.close()


# ─── 门店权限管理 ─────────────────────────────────────────────────────────────


@router.get("/store-permissions/{store_id}")
async def get_store_permission(store_id: UUID, request: Request) -> dict:
    """获取门店菜单自主修改权限"""
    tid = _tenant_id(request)
    db: AsyncSession = request.app.state.db_session_factory()
    try:
        svc = MenuApprovalService(db)
        perm = await svc.get_store_permission(store_id=store_id, tenant_id=UUID(tid))
        return {"ok": True, "data": perm.model_dump(mode="json")}
    finally:
        await db.close()


@router.put("/store-permissions/{store_id}")
async def update_store_permission(
    store_id: UUID,
    body: StoreMenuPermissionUpdate,
    request: Request,
) -> dict:
    """更新门店菜单自主修改权限"""
    tid = _tenant_id(request)
    db: AsyncSession = request.app.state.db_session_factory()
    try:
        svc = MenuApprovalService(db)
        perm = await svc.update_store_permission(
            store_id=store_id,
            tenant_id=UUID(tid),
            permission=body,
        )
        return {"ok": True, "data": perm.model_dump(mode="json")}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await db.close()


# ─── 新店开业 ─────────────────────────────────────────────────────────────────


@router.post("/clone-store-menu")
async def clone_store_menu(body: CloneStoreMenuBody, request: Request) -> dict:
    """新店开业一键复制菜单（跳过审批流，直接执行）"""
    tid = _tenant_id(request)
    db: AsyncSession = request.app.state.db_session_factory()
    try:
        svc = MenuApprovalService(db)
        result = await svc.clone_store_menu(
            source_store_id=body.source_store_id,
            target_store_id=body.target_store_id,
            tenant_id=UUID(tid),
        )
        return {"ok": True, "data": result.model_dump(mode="json")}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await db.close()
