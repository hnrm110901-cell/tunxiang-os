"""社群运营工具 API 路由

标签管理:
POST   /api/v1/wecom/group-ops/tags                  创建标签
GET    /api/v1/wecom/group-ops/tags                  标签列表
DELETE /api/v1/wecom/group-ops/tags/{tag_id}         删除标签
POST   /api/v1/wecom/group-ops/groups/{id}/tags      为群绑定标签
DELETE /api/v1/wecom/group-ops/groups/{id}/tags/{tid} 解绑标签
GET    /api/v1/wecom/group-ops/groups/{id}/tags      获取群标签
GET    /api/v1/wecom/group-ops/tags/{id}/groups      按标签查群
POST   /api/v1/wecom/group-ops/groups/batch-tags     批量绑定标签

群发管理:
POST   /api/v1/wecom/group-ops/mass-sends            创建群发
GET    /api/v1/wecom/group-ops/mass-sends            群发列表
GET    /api/v1/wecom/group-ops/mass-sends/{id}       群发详情
POST   /api/v1/wecom/group-ops/mass-sends/{id}/execute 执行群发
POST   /api/v1/wecom/group-ops/mass-sends/{id}/cancel  取消群发
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .group_ops_service import GroupOpsService
from .response import err, ok, paginated

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/wecom/group-ops", tags=["group-ops"])

_service = GroupOpsService()


# ─────────────────────────────────────────────────────────────────
# 依赖
# ─────────────────────────────────────────────────────────────────


def _parse_tenant_id(x_tenant_id: str) -> UUID:
    try:
        return UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误") from exc


def _parse_uuid(value: str, label: str = "ID") -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{label} 格式错误") from exc


async def _get_db():  # type: ignore[return]
    try:
        from .database import get_async_session  # type: ignore[import]

        async for session in get_async_session():
            yield session
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="数据库未配置") from exc


# ─────────────────────────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────────────────────────


class CreateTagRequest(BaseModel):
    tag_group: str = Field(..., min_length=1, max_length=100, description="标签组名称")
    tag_name: str = Field(..., min_length=1, max_length=100, description="标签名称")
    tag_color: str = Field(default="#666", max_length=20, description="标签颜色")
    sort_order: int = Field(default=0, description="排序权重")


class BindTagsRequest(BaseModel):
    tag_ids: list[str] = Field(..., min_length=1, description="标签 ID 列表")


class BatchBindTagsRequest(BaseModel):
    group_chat_ids: list[str] = Field(..., min_length=1, description="群 chat_id 列表")
    tag_ids: list[str] = Field(..., min_length=1, description="标签 ID 列表")


class CreateMassSendRequest(BaseModel):
    send_name: str = Field(..., min_length=1, max_length=200, description="任务名称")
    content: dict[str, Any] = Field(..., description="消息内容")
    target_tag_ids: list[str] = Field(default_factory=list, description="目标标签 ID")
    exclude_tag_ids: list[str] = Field(default_factory=list, description="排除标签 ID")
    target_group_ids: list[str] = Field(default_factory=list, description="直接指定的群 chat_id")
    send_type: str = Field(default="immediate", description="immediate | scheduled")
    scheduled_at: datetime | None = Field(default=None, description="定时发送时间")
    created_by: str | None = Field(default=None, description="创建人 UUID")


# ─────────────────────────────────────────────────────────────────
# 标签 CRUD 路由
# ─────────────────────────────────────────────────────────────────


@router.post("/tags")
async def create_tag(
    req: CreateTagRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建群标签"""
    tenant_id = _parse_tenant_id(x_tenant_id)

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.create_tag(
            tenant_id=tenant_id,
            tag_group=req.tag_group,
            tag_name=req.tag_name,
            db=db,
            tag_color=req.tag_color,
            sort_order=req.sort_order,
        )
        if not result.get("success"):
            return err(result.get("error", "创建失败"), code="TAG_DUPLICATE")
        return ok(result)


@router.get("/tags")
async def list_tags(
    tag_group: str | None = Query(default=None, description="按标签组过滤"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """查询标签列表"""
    tenant_id = _parse_tenant_id(x_tenant_id)

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        items = await _service.list_tags(tenant_id=tenant_id, db=db, tag_group=tag_group)
        return ok(items)


@router.delete("/tags/{tag_id}")
async def delete_tag(
    tag_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """删除标签"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    tid = _parse_uuid(tag_id, "tag_id")

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.delete_tag(tenant_id=tenant_id, tag_id=tid, db=db)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "标签不存在"))
        return ok(result)


# ─────────────────────────────────────────────────────────────────
# 标签绑定路由
# ─────────────────────────────────────────────────────────────────


@router.post("/groups/{group_chat_id}/tags")
async def bind_tags_to_group(
    group_chat_id: str,
    req: BindTagsRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """为群绑定标签"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    tag_uuids = [_parse_uuid(tid, "tag_id") for tid in req.tag_ids]

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.bind_tags(
            tenant_id=tenant_id,
            group_chat_id=group_chat_id,
            tag_ids=tag_uuids,
            db=db,
        )
        if not result.get("success"):
            return err(result.get("error", "绑定失败"), code="BIND_ERROR")
        return ok(result)


@router.delete("/groups/{group_chat_id}/tags/{tag_id}")
async def unbind_tag_from_group(
    group_chat_id: str,
    tag_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """解绑群标签"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    tid = _parse_uuid(tag_id, "tag_id")

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.unbind_tag(
            tenant_id=tenant_id,
            group_chat_id=group_chat_id,
            tag_id=tid,
            db=db,
        )
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "绑定关系不存在"))
        return ok(result)


@router.get("/groups/{group_chat_id}/tags")
async def get_group_tags(
    group_chat_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取群已绑定的标签"""
    tenant_id = _parse_tenant_id(x_tenant_id)

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        items = await _service.get_group_tags(
            tenant_id=tenant_id,
            group_chat_id=group_chat_id,
            db=db,
        )
        return ok(items)


@router.get("/tags/{tag_id}/groups")
async def list_groups_by_tag(
    tag_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """查询标签下的所有群"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    tid = _parse_uuid(tag_id, "tag_id")

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        group_ids = await _service.list_groups_by_tag(
            tenant_id=tenant_id,
            tag_id=tid,
            db=db,
        )
        return ok({"group_chat_ids": group_ids, "count": len(group_ids)})


@router.post("/groups/batch-tags")
async def batch_bind_tags(
    req: BatchBindTagsRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """批量为多个群绑定多个标签"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    tag_uuids = [_parse_uuid(tid, "tag_id") for tid in req.tag_ids]

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.batch_bind_tags(
            tenant_id=tenant_id,
            group_chat_ids=req.group_chat_ids,
            tag_ids=tag_uuids,
            db=db,
        )
        if not result.get("success"):
            return err(result.get("error", "批量绑定失败"), code="BATCH_BIND_ERROR")
        return ok(result)


# ─────────────────────────────────────────────────────────────────
# 群发任务路由
# ─────────────────────────────────────────────────────────────────


@router.post("/mass-sends")
async def create_mass_send(
    req: CreateMassSendRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建群发任务"""
    tenant_id = _parse_tenant_id(x_tenant_id)

    if req.send_type not in ("immediate", "scheduled"):
        return err("send_type 必须为 immediate 或 scheduled", code="INVALID_SEND_TYPE")
    if req.send_type == "scheduled" and not req.scheduled_at:
        return err("定时发送必须指定 scheduled_at", code="MISSING_SCHEDULED_AT")

    created_by = _parse_uuid(req.created_by, "created_by") if req.created_by else None

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.create_mass_send(
            tenant_id=tenant_id,
            send_name=req.send_name,
            content=req.content,
            db=db,
            target_tag_ids=req.target_tag_ids,
            exclude_tag_ids=req.exclude_tag_ids,
            target_group_ids=req.target_group_ids,
            send_type=req.send_type,
            scheduled_at=req.scheduled_at,
            created_by=created_by,
        )
        return ok(result)


@router.get("/mass-sends")
async def list_mass_sends(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None, description="按状态过滤"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """群发任务列表"""
    tenant_id = _parse_tenant_id(x_tenant_id)

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.list_mass_sends(
            tenant_id=tenant_id,
            db=db,
            status=status,
            page=page,
            size=size,
        )
        return paginated(result["items"], result["total"], result["page"], result["size"])


@router.get("/mass-sends/{send_id}")
async def get_mass_send(
    send_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取群发任务详情"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    sid = _parse_uuid(send_id, "send_id")

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.get_mass_send(tenant_id=tenant_id, send_id=sid, db=db)
        if result is None:
            raise HTTPException(status_code=404, detail="群发任务不存在")
        return ok(result)


@router.post("/mass-sends/{send_id}/execute")
async def execute_mass_send(
    send_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """执行群发任务"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    sid = _parse_uuid(send_id, "send_id")

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.execute_mass_send(
            tenant_id=tenant_id,
            send_id=sid,
            db=db,
        )
        if not result.get("success"):
            return err(result.get("error", "执行失败"), code="EXECUTE_ERROR")
        return ok(result)


@router.post("/mass-sends/{send_id}/cancel")
async def cancel_mass_send(
    send_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """取消群发任务"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    sid = _parse_uuid(send_id, "send_id")

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.cancel_mass_send(
            tenant_id=tenant_id,
            send_id=sid,
            db=db,
        )
        if not result.get("success"):
            return err(result.get("error", "取消失败"), code="CANCEL_ERROR")
        return ok(result)
