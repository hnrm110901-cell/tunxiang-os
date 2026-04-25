"""企业素材库 API 路由

分组管理:
POST   /api/v1/materials/groups            创建分组
GET    /api/v1/materials/groups            分组列表（树结构）
PUT    /api/v1/materials/groups/{id}       更新分组
DELETE /api/v1/materials/groups/{id}       删除分组

素材管理:
POST   /api/v1/materials/                  创建素材
GET    /api/v1/materials/                  素材列表（筛选）
GET    /api/v1/materials/current           当前时段素材
GET    /api/v1/materials/{id}              素材详情
PUT    /api/v1/materials/{id}              更新素材
DELETE /api/v1/materials/{id}              删除素材
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .material_service import MaterialService
from .response import err, ok, paginated

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/materials", tags=["materials"])

_service = MaterialService()


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


# ─────────────────────────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────────────────────────


class CreateGroupRequest(BaseModel):
    group_name: str = Field(..., min_length=1, max_length=100, description="分组名称")
    parent_id: str | None = Field(default=None, description="父分组 ID")
    icon: str | None = Field(default=None, max_length=50, description="图标")
    sort_order: int = Field(default=0, description="排序权重")


class UpdateGroupRequest(BaseModel):
    group_name: str | None = Field(default=None, max_length=100, description="分组名称")
    parent_id: str | None = Field(default=None, description="父分组 ID")
    icon: str | None = Field(default=None, max_length=50, description="图标")
    sort_order: int | None = Field(default=None, description="排序权重")


class CreateMaterialRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300, description="素材标题")
    material_type: str = Field(..., description="text|image|link|miniapp|video|file|poster")
    group_id: str | None = Field(default=None, description="所属分组 ID")
    content: str | None = Field(default=None, description="文本内容")
    media_url: str | None = Field(default=None, description="媒体文件 URL")
    thumbnail_url: str | None = Field(default=None, description="缩略图 URL")
    link_url: str | None = Field(default=None, description="链接 URL")
    link_title: str | None = Field(default=None, max_length=300, description="链接标题")
    miniapp_appid: str | None = Field(default=None, max_length=100, description="小程序 appid")
    miniapp_path: str | None = Field(default=None, max_length=500, description="小程序路径")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")
    time_slots: list[dict[str, str]] = Field(
        default_factory=list,
        description='时段列表，如 [{"start":"08:00","end":"12:00","label":"早餐"}]',
    )
    tags: list[str] = Field(default_factory=list, description="标签列表")
    is_template: bool = Field(default=False, description="是否为模板")
    sort_order: int = Field(default=0, description="排序权重")
    created_by: str | None = Field(default=None, description="创建人 UUID")


class UpdateMaterialRequest(BaseModel):
    title: str | None = Field(default=None, max_length=300, description="素材标题")
    group_id: str | None = Field(default=None, description="所属分组 ID")
    content: str | None = Field(default=None, description="文本内容")
    media_url: str | None = Field(default=None, description="媒体文件 URL")
    thumbnail_url: str | None = Field(default=None, description="缩略图 URL")
    link_url: str | None = Field(default=None, description="链接 URL")
    link_title: str | None = Field(default=None, max_length=300, description="链接标题")
    miniapp_appid: str | None = Field(default=None, max_length=100, description="小程序 appid")
    miniapp_path: str | None = Field(default=None, max_length=500, description="小程序路径")
    metadata: dict[str, Any] | None = Field(default=None, description="扩展元数据")
    time_slots: list[dict[str, str]] | None = Field(default=None, description="时段列表")
    tags: list[str] | None = Field(default=None, description="标签列表")
    is_template: bool | None = Field(default=None, description="是否为模板")
    sort_order: int | None = Field(default=None, description="排序权重")


# ─────────────────────────────────────────────────────────────────
# 分组管理路由
# ─────────────────────────────────────────────────────────────────


@router.post("/groups")
async def create_group(
    req: CreateGroupRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建素材分组"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    parent_uuid = _parse_uuid(req.parent_id, "parent_id") if req.parent_id else None

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.create_group(
            tenant_id=tenant_id,
            group_name=req.group_name,
            db=db,
            parent_id=parent_uuid,
            icon=req.icon,
            sort_order=req.sort_order,
        )
        if not result.get("success"):
            return err(result.get("error", "创建失败"), code="CREATE_GROUP_ERROR")
        return ok(result)


@router.get("/groups")
async def list_groups(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """查询素材分组（树结构）"""
    tenant_id = _parse_tenant_id(x_tenant_id)

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        tree = await _service.list_groups(tenant_id=tenant_id, db=db)
        return ok(tree)


@router.put("/groups/{group_id}")
async def update_group(
    group_id: str,
    req: UpdateGroupRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新素材分组"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    gid = _parse_uuid(group_id, "group_id")
    parent_uuid = _parse_uuid(req.parent_id, "parent_id") if req.parent_id else None

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.update_group(
            tenant_id=tenant_id,
            group_id=gid,
            db=db,
            group_name=req.group_name,
            parent_id=parent_uuid,
            icon=req.icon,
            sort_order=req.sort_order,
        )
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "分组不存在"))
        return ok(result)


@router.delete("/groups/{group_id}")
async def delete_group(
    group_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """删除素材分组"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    gid = _parse_uuid(group_id, "group_id")

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.delete_group(tenant_id=tenant_id, group_id=gid, db=db)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "分组不存在"))
        return ok(result)


# ─────────────────────────────────────────────────────────────────
# 素材 CRUD 路由
# ─────────────────────────────────────────────────────────────────


@router.post("/")
async def create_material(
    req: CreateMaterialRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建素材"""
    tenant_id = _parse_tenant_id(x_tenant_id)

    valid_types = ("text", "image", "link", "miniapp", "video", "file", "poster")
    if req.material_type not in valid_types:
        return err(f"material_type 必须为 {', '.join(valid_types)}", code="INVALID_TYPE")

    group_uuid = _parse_uuid(req.group_id, "group_id") if req.group_id else None
    created_by_uuid = _parse_uuid(req.created_by, "created_by") if req.created_by else None

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.create_material(
            tenant_id=tenant_id,
            title=req.title,
            material_type=req.material_type,
            db=db,
            group_id=group_uuid,
            content=req.content,
            media_url=req.media_url,
            thumbnail_url=req.thumbnail_url,
            link_url=req.link_url,
            link_title=req.link_title,
            miniapp_appid=req.miniapp_appid,
            miniapp_path=req.miniapp_path,
            metadata=req.metadata,
            time_slots=req.time_slots,
            tags=req.tags,
            is_template=req.is_template,
            sort_order=req.sort_order,
            created_by=created_by_uuid,
        )
        return ok(result)


@router.get("/")
async def list_materials(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    group_id: str | None = Query(default=None, description="按分组过滤"),
    material_type: str | None = Query(default=None, description="按类型过滤"),
    keyword: str | None = Query(default=None, description="按标题关键词搜索"),
    is_template: bool | None = Query(default=None, description="是否模板"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """素材列表（分页 + 筛选）"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    group_uuid = _parse_uuid(group_id, "group_id") if group_id else None

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.list_materials(
            tenant_id=tenant_id,
            db=db,
            group_id=group_uuid,
            material_type=material_type,
            keyword=keyword,
            is_template=is_template,
            page=page,
            size=size,
        )
        return paginated(result["items"], result["total"], result["page"], result["size"])


@router.get("/current")
async def get_current_materials(
    material_type: str | None = Query(default=None, description="按类型过滤"),
    limit: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取当前时段匹配的素材"""
    tenant_id = _parse_tenant_id(x_tenant_id)

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        items = await _service.get_current_materials(
            tenant_id=tenant_id,
            db=db,
            material_type=material_type,
            limit=limit,
        )
        return ok(items)


@router.get("/{material_id}")
async def get_material(
    material_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取素材详情"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    mid = _parse_uuid(material_id, "material_id")

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.get_material(tenant_id=tenant_id, material_id=mid, db=db)
        if result is None:
            raise HTTPException(status_code=404, detail="素材不存在")
        return ok(result)


@router.put("/{material_id}")
async def update_material(
    material_id: str,
    req: UpdateMaterialRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新素材"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    mid = _parse_uuid(material_id, "material_id")

    update_data: dict[str, Any] = {}
    for field_name in (
        "title",
        "content",
        "media_url",
        "thumbnail_url",
        "link_url",
        "link_title",
        "miniapp_appid",
        "miniapp_path",
        "is_template",
        "sort_order",
    ):
        val = getattr(req, field_name, None)
        if val is not None:
            update_data[field_name] = val

    if req.group_id is not None:
        update_data["group_id"] = _parse_uuid(req.group_id, "group_id")
    if req.metadata is not None:
        update_data["metadata"] = req.metadata
    if req.time_slots is not None:
        update_data["time_slots"] = req.time_slots
    if req.tags is not None:
        update_data["tags"] = req.tags

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.update_material(
            tenant_id=tenant_id,
            material_id=mid,
            db=db,
            **update_data,
        )
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "素材不存在"))
        return ok(result)


@router.delete("/{material_id}")
async def delete_material(
    material_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """删除素材"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    mid = _parse_uuid(material_id, "material_id")

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.delete_material(tenant_id=tenant_id, material_id=mid, db=db)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "素材不存在"))
        return ok(result)
