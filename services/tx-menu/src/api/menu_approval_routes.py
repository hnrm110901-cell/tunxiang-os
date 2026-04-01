"""集团菜单下发审批流 API

涵盖：
  - 菜单变更审批（price_change/new_dish/soldout/remove_dish/channel_add）
  - 下发申请管理（创建/查询/审批/拒绝/执行）
  - 门店菜单自主修改权限管理
  - 新店开业一键复制菜单

ROUTER REGISTRATION（在 tx-menu/src/main.py 中添加）：
    from .api.menu_approval_routes import router as menu_approval_router
    app.include_router(menu_approval_router)
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

from ..services.menu_approval_service import (
    MenuApprovalService,
    StoreMenuPermissionUpdate,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/menu", tags=["menu-approval"])

# 允许的审批类型
_APPROVAL_TYPES = frozenset({"price_change", "new_dish", "soldout", "remove_dish", "channel_add"})


# ─── DB 依赖占位（与其他路由保持一致） ─────────────────────────────────────────


# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── 菜单变更审批端点（menu_approvals 独立流程） ────────────────────────────────

# menu_approvals 表使用 menu_publish_requests 表（v039 已创建），
# 通过 change_type 区分 price_change/new_dish/soldout/remove_dish/channel_add


class CreateApprovalReq(BaseModel):
    approval_type: str = Field(
        ...,
        description="审批类型: price_change / new_dish / soldout / remove_dish / channel_add",
    )
    store_id: UUID
    dish_id: UUID
    payload: dict = Field(default_factory=dict, description="业务附属信息，如 new_price_fen")
    created_by: UUID
    note: str = ""


class ApprovalActionBody(BaseModel):
    approver_id: UUID
    note: str = ""


class ApprovalRejectBody(BaseModel):
    approver_id: UUID
    note: str = Field(..., min_length=1, description="拒绝原因（必填）")


@router.post("/approvals", summary="发起菜单变更审批", status_code=201)
async def create_approval(
    body: CreateApprovalReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发起审批申请（菜品上架/下架/价格变更/新品上线/渠道添加）。

    审批状态流转：pending → approved / rejected
    通过后系统自动执行对应操作。
    """
    if body.approval_type not in _APPROVAL_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的审批类型: {body.approval_type}，有效值: {sorted(_APPROVAL_TYPES)}",
        )
    tenant_id = _tenant_id(request)
    await _set_rls(db, tenant_id)

    svc = MenuApprovalService(db)
    payload = {
        "dish_id": str(body.dish_id),
        "store_id": str(body.store_id),
        "note": body.note,
        **body.payload,
    }
    result = await svc.create_publish_request(
        tenant_id=UUID(tenant_id),
        source_type="store",
        target_store_ids=[body.store_id],
        change_type=body.approval_type,
        change_payload=payload,
        created_by=body.created_by,
        expires_hours=48,
    )
    log.info("approval.created", approval_type=body.approval_type, dish_id=str(body.dish_id), tenant_id=tenant_id)
    return {"ok": True, "data": result.model_dump(mode="json")}


@router.get("/approvals", summary="审批列表（含状态筛选）")
async def list_approvals(
    request: Request,
    status: Optional[str] = Query(default=None, description="状态筛选: pending/approved/rejected/applied"),
    approval_type: Optional[str] = Query(default=None, description="审批类型筛选"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取审批列表（分页）。支持按 status / approval_type 过滤。"""
    tenant_id = _tenant_id(request)
    await _set_rls(db, tenant_id)
    tid = _uuid.UUID(tenant_id)

    svc = MenuApprovalService(db)
    items, total = await svc.get_requests(
        tenant_id=tid,
        status=status,
        page=page,
        size=size,
    )

    # 按 approval_type 在内存过滤（change_type 字段）
    data = [i.model_dump(mode="json") for i in items]
    if approval_type:
        data = [i for i in data if i.get("change_type") == approval_type]

    return {
        "ok": True,
        "data": {
            "items": data,
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.get("/approvals/{approval_id}", summary="审批详情")
async def get_approval(
    approval_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取单条审批申请详情。"""
    tenant_id = _tenant_id(request)
    await _set_rls(db, tenant_id)
    svc = MenuApprovalService(db)
    item = await svc.get_request_by_id(request_id=approval_id, tenant_id=UUID(tenant_id))
    if item is None:
        raise HTTPException(status_code=404, detail=f"审批申请不存在: {approval_id}")
    return {"ok": True, "data": item.model_dump(mode="json")}


@router.post("/approvals/{approval_id}/approve", summary="通过审批（自动执行对应操作）")
async def approve_approval(
    approval_id: UUID,
    body: ApprovalActionBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """审批通过，并自动执行对应操作：

    - price_change → 更新 dishes.price_fen
    - new_dish     → 设置 dishes.is_available = true
    - soldout      → 设置 dishes.is_available = false（临时沽清）
    - remove_dish  → 设置 dishes.is_available = false + is_deleted = true
    - channel_add  → 写入 channel_menu_items
    """
    tenant_id = _tenant_id(request)
    await _set_rls(db, tenant_id)
    svc = MenuApprovalService(db)

    # 1. 通过审批
    try:
        approved = await svc.approve_request(
            request_id=approval_id,
            approver_id=body.approver_id,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    tid = _uuid.UUID(tenant_id)
    payload = approved.change_payload
    dish_id_str = payload.get("dish_id", "")
    change_type = approved.change_type

    # 2. 自动执行对应操作
    try:
        did = _uuid.UUID(dish_id_str)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"payload.dish_id 格式错误: {dish_id_str}") from exc

    action_detail: dict = {}

    if change_type == "price_change":
        new_price = payload.get("new_price_fen")
        if new_price is None:
            raise HTTPException(status_code=422, detail="price_change 审批缺少 payload.new_price_fen")
        await db.execute(
            text("UPDATE dishes SET price_fen = :price, updated_at = NOW() WHERE id = :did AND tenant_id = :tid"),
            {"price": int(new_price), "did": did, "tid": tid},
        )
        action_detail = {"updated_price_fen": int(new_price)}

    elif change_type == "new_dish":
        await db.execute(
            text("UPDATE dishes SET is_available = true, updated_at = NOW() WHERE id = :did AND tenant_id = :tid"),
            {"did": did, "tid": tid},
        )
        action_detail = {"is_available": True}

    elif change_type == "soldout":
        await db.execute(
            text("UPDATE dishes SET is_available = false, updated_at = NOW() WHERE id = :did AND tenant_id = :tid"),
            {"did": did, "tid": tid},
        )
        action_detail = {"is_available": False}

    elif change_type == "remove_dish":
        await db.execute(
            text(
                "UPDATE dishes SET is_available = false, is_deleted = true, updated_at = NOW() "
                "WHERE id = :did AND tenant_id = :tid"
            ),
            {"did": did, "tid": tid},
        )
        action_detail = {"is_available": False, "is_deleted": True}

    elif change_type == "channel_add":
        channel = payload.get("channel", "dine_in")
        store_id_str = payload.get("store_id", "")
        try:
            store_uuid = _uuid.UUID(store_id_str)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="payload.store_id 格式错误") from exc
        price_fen = payload.get("channel_price_fen")
        await db.execute(
            text("""
                INSERT INTO channel_menu_items
                    (tenant_id, store_id, dish_id, channel, channel_price_fen, is_available)
                VALUES
                    (:tid, :sid, :did, :channel, :price, true)
                ON CONFLICT (tenant_id, store_id, dish_id, channel) DO UPDATE SET
                    is_available = true,
                    channel_price_fen = COALESCE(EXCLUDED.channel_price_fen, channel_menu_items.channel_price_fen),
                    updated_at = NOW()
            """),
            {"tid": tid, "sid": store_uuid, "did": did, "channel": channel, "price": price_fen},
        )
        action_detail = {"channel": channel, "dish_id": dish_id_str}

    await db.commit()
    log.info("approval.approved_and_applied", approval_id=str(approval_id), change_type=change_type)
    return {
        "ok": True,
        "data": {
            "approval": approved.model_dump(mode="json"),
            "action_applied": change_type,
            "action_detail": action_detail,
        },
    }


@router.post("/approvals/{approval_id}/reject", summary="拒绝审批（需填拒绝原因）")
async def reject_approval(
    approval_id: UUID,
    body: ApprovalRejectBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """拒绝审批申请。拒绝原因（note）为必填项。"""
    tenant_id = _tenant_id(request)
    await _set_rls(db, tenant_id)
    svc = MenuApprovalService(db)
    try:
        result = await svc.reject_request(
            request_id=approval_id,
            approver_id=body.approver_id,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log.info("approval.rejected", approval_id=str(approval_id), approver=str(body.approver_id))
    return {"ok": True, "data": result.model_dump(mode="json")}


# ─── 请求/响应模型（下发申请，原有流程） ─────────────────────────────────────────


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
