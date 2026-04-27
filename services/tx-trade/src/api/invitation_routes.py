"""电子邀请函 API 路由 — S7

认证端点（需 X-Tenant-ID）：
  GET    /api/v1/invitations/templates              模板列表
  GET    /api/v1/invitations/templates/{id}         模板详情
  POST   /api/v1/invitations/templates              创建自定义模板
  PUT    /api/v1/invitations/templates/{id}         更新模板
  DELETE /api/v1/invitations/templates/{id}         删除模板
  POST   /api/v1/invitations                        创建邀请函
  POST   /api/v1/invitations/{id}/publish           发布邀请函
  GET    /api/v1/invitations/{id}                   邀请函详情
  GET    /api/v1/invitations/stats                  邀请函统计列表

公开端点（无需认证，通过 share_code 访问）：
  GET    /api/v1/invitations/public/{share_code}         公开查看邀请函
  POST   /api/v1/invitations/public/{share_code}/view    记录浏览量
  POST   /api/v1/invitations/public/{share_code}/rsvp    提交 RSVP

响应格式：{"code": 0, "data": {...}, "message": "ok"}
"""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.invitation_service import (
    create_invitation,
    create_template,
    delete_template,
    get_invitation,
    get_invitation_by_share_code,
    get_invitation_stats,
    get_template,
    list_templates,
    publish_invitation,
    record_view,
    submit_rsvp,
    update_template,
)

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/invitations", tags=["电子邀请函"])


# ──────────────────────────────────────────────
# 公共辅助
# ──────────────────────────────────────────────


def _require_tenant(tenant_id: Optional[str]) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return tenant_id


def _ok(data: object) -> dict:
    return {"code": 0, "data": data, "message": "ok"}


# ══════════════════════════════════════════════════════════════════════════════
# 模板端点（需认证）
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/templates")
async def api_list_templates(
    banquet_type: Optional[str] = Query(None, description="宴会类型过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取邀请函模板列表 — 系统预置 + 租户自定义"""
    tenant_id = _require_tenant(x_tenant_id)
    data = await list_templates(db, tenant_id, banquet_type=banquet_type, page=page, size=size)
    return _ok(data)


@router.get("/templates/{template_id}")
async def api_get_template(
    template_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取单个模板详情"""
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_template(db, tenant_id, template_id)
    if not data:
        raise HTTPException(status_code=404, detail="Template not found")
    return _ok(data)


@router.post("/templates")
async def api_create_template(
    body: dict = Body(...),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建自定义邀请函模板

    请求体：
    {
        "template_name": "浪漫婚礼",       // 必填
        "template_code": "wedding_romantic", // 选填，自动生成
        "banquet_type": "wedding",           // 必填
        "cover_image_url": "https://...",
        "background_color": "#FFF5F5",
        "layout_config": {...},
        "music_url": "https://...",
        "animation_type": "fade"
    }
    """
    tenant_id = _require_tenant(x_tenant_id)
    if not body.get("template_name"):
        raise HTTPException(status_code=422, detail="template_name is required")
    data = await create_template(db, tenant_id, body)
    return _ok(data)


@router.put("/templates/{template_id}")
async def api_update_template(
    template_id: str,
    body: dict = Body(...),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """更新自定义模板（系统预置模板不可修改）"""
    tenant_id = _require_tenant(x_tenant_id)
    data = await update_template(db, tenant_id, template_id, body)
    if not data:
        raise HTTPException(status_code=404, detail="Template not found or not editable")
    return _ok(data)


@router.delete("/templates/{template_id}")
async def api_delete_template(
    template_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """删除自定义模板（软删除，系统预置模板不可删除）"""
    tenant_id = _require_tenant(x_tenant_id)
    success = await delete_template(db, tenant_id, template_id)
    if not success:
        raise HTTPException(status_code=404, detail="Template not found or not deletable")
    return _ok({"deleted": True})


# ══════════════════════════════════════════════════════════════════════════════
# 邀请函实例端点（需认证）
# ══════════════════════════════════════════════════════════════════════════════


@router.post("")
async def api_create_invitation(
    store_id: str = Query(..., description="门店ID"),
    body: dict = Body(...),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建邀请函实例（草稿状态）

    请求体：
    {
        "template_id": "uuid",            // 必填
        "title": "张三 & 李四 婚礼邀请",  // 必填
        "event_date": "2026-05-20T18:00",  // 必填
        "host_names": "张三 & 李四",
        "event_address": "长沙市xxx路xxx号",
        "event_hall": "金色大厅",
        "greeting_text": "诚邀您共同见证...",
        "banquet_order_id": "uuid",        // 选填，关联宴会订单
        "cover_image_url": "https://...",
        "gallery_urls": ["https://..."],
        "music_url": "https://...",
        "rsvp_enabled": true,
        "rsvp_deadline": "2026-05-18T23:59",
        "custom_fields": {...},
        "created_by": "uuid"               // 必填
    }
    """
    tenant_id = _require_tenant(x_tenant_id)
    if not body.get("template_id"):
        raise HTTPException(status_code=422, detail="template_id is required")
    if not body.get("title"):
        raise HTTPException(status_code=422, detail="title is required")
    if not body.get("event_date"):
        raise HTTPException(status_code=422, detail="event_date is required")
    if not body.get("created_by"):
        raise HTTPException(status_code=422, detail="created_by is required")

    data = await create_invitation(db, tenant_id, store_id, body)
    return _ok(data)


@router.post("/{invitation_id}/publish")
async def api_publish_invitation(
    invitation_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """发布邀请函 — draft → published，生成公开访问链接"""
    tenant_id = _require_tenant(x_tenant_id)
    data = await publish_invitation(db, tenant_id, invitation_id)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="Invitation not found or not in draft status",
        )
    return _ok(data)


@router.get("/stats")
async def api_invitation_stats(
    store_id: str = Query(..., description="门店ID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """邀请函统计列表 — 浏览量/RSVP回执统计"""
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_invitation_stats(db, tenant_id, store_id, page=page, size=size)
    return _ok(data)


@router.get("/{invitation_id}")
async def api_get_invitation(
    invitation_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取邀请函详情（管理端）"""
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_invitation(db, tenant_id, invitation_id)
    if not data:
        raise HTTPException(status_code=404, detail="Invitation not found")
    return _ok(data)


# ══════════════════════════════════════════════════════════════════════════════
# 公开端点（无需认证，通过 share_code 访问）
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/public/{share_code}")
async def api_public_invitation(
    share_code: str,
    db: AsyncSession = Depends(get_db),
):
    """公开查看邀请函 — 通过短码访问，无需认证

    用于微信/抖音分享链接。
    """
    data = await get_invitation_by_share_code(db, share_code)
    if not data:
        raise HTTPException(status_code=404, detail="Invitation not found or not published")
    return _ok(data)


@router.post("/public/{share_code}/view")
async def api_record_view(
    share_code: str,
    db: AsyncSession = Depends(get_db),
):
    """记录邀请函浏览量 — 无需认证

    前端打开邀请函页面时调用。
    """
    success = await record_view(db, share_code)
    if not success:
        raise HTTPException(status_code=404, detail="Invitation not found")
    return _ok({"recorded": True})


@router.post("/public/{share_code}/rsvp")
async def api_submit_rsvp(
    share_code: str,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """提交 RSVP 回执 — 无需认证

    请求体：
    {
        "attending": true,       // 是否出席
        "guest_count": 2,        // 出席人数
        "guest_name": "王五",    // 来宾姓名
        "message": "祝福新人..."  // 祝福语
    }
    """
    data = await submit_rsvp(db, share_code, body)
    if not data:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if data.get("error"):
        raise HTTPException(status_code=400, detail=data["error"])
    return _ok(data)
