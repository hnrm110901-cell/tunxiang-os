"""菜单版本管理 + 集团模板下发路由

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

# ROUTER REGISTRATION:
# from .api.menu_version_routes import router as menu_version_router
# app.include_router(menu_version_router, prefix="/api/v1/menu")
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.menu_dispatch_service import MenuDispatchService
from ..services.menu_version_service import MenuVersionService

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/menu", tags=["menu-version"])


# ─── Request Models ───


class CreateVersionReq(BaseModel):
    brand_id: str
    version_name: Optional[str] = None
    dishes_snapshot: list[dict] = Field(default_factory=list, description="菜品完整快照列表")
    created_by: Optional[str] = None


class PublishVersionReq(BaseModel):
    store_ids: list[str] = Field(description="目标门店 ID 列表")
    dispatch_type: str = Field(default="full", description="full / pilot")
    pilot_ratio: float = Field(default=0.05, ge=0.01, le=1.0, description="灰度比例（仅 pilot 有效）")
    all_store_ids: Optional[list[str]] = Field(default=None, description="全部门店列表（灰度时必填）")


class RollbackReq(BaseModel):
    store_id: str


class StoreOverrideReq(BaseModel):
    add_dishes: list[dict] = Field(default_factory=list, description="本店独有菜品")
    remove_dishes: list[str] = Field(default_factory=list, description="停售菜品 dish_id 列表")
    price_overrides: dict[str, int] = Field(
        default_factory=dict, description="{dish_id: price_fen} 本店价格覆盖"
    )


class ConfirmAppliedReq(BaseModel):
    record_id: str


# ─── 辅助 ───


def _err(status: int, msg: str):
    raise HTTPException(status_code=status, detail={"ok": False, "error": {"message": msg}})


# ═══════════════════════════════════════════
# 版本 CRUD
# ═══════════════════════════════════════════


@router.post("/versions")
async def api_create_version(
    req: CreateVersionReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建菜单版本（草稿），保存当前菜品快照"""
    try:
        version = await MenuVersionService.create_version(
            brand_id=req.brand_id,
            version_name=req.version_name,
            tenant_id=x_tenant_id,
            dishes_snapshot=req.dishes_snapshot,
            created_by=req.created_by,
        )
        return {"ok": True, "data": version}
    except ValueError as exc:
        _err(400, str(exc))


@router.get("/versions")
async def api_list_versions(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    brand_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """版本列表（按品牌筛选，分页）"""
    try:
        result = await MenuVersionService.list_versions(
            tenant_id=x_tenant_id,
            brand_id=brand_id,
            page=page,
            size=size,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))


@router.get("/versions/{version_id}")
async def api_get_version(
    version_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取版本详情（含完整菜品快照）"""
    version = await MenuVersionService.get_version(version_id, x_tenant_id)
    if not version:
        _err(404, f"版本不存在: {version_id}")
    return {"ok": True, "data": version}


# ═══════════════════════════════════════════
# 发布与下发
# ═══════════════════════════════════════════


@router.post("/versions/{version_id}/publish")
async def api_publish_version(
    version_id: str,
    req: PublishVersionReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """发布版本到门店（全量 / 灰度）

    - dispatch_type=full：直接下发到 store_ids 列表
    - dispatch_type=pilot：从 all_store_ids 中随机选取 pilot_ratio 比例先试验
    """
    try:
        if req.dispatch_type == "pilot":
            if not req.all_store_ids:
                _err(400, "灰度下发时必须提供 all_store_ids")
            result = await MenuDispatchService.pilot_dispatch(
                version_id=version_id,
                all_store_ids=req.all_store_ids,
                tenant_id=x_tenant_id,
                pilot_ratio=req.pilot_ratio,
            )
        else:
            records = await MenuVersionService.publish_to_stores(
                version_id=version_id,
                store_ids=req.store_ids,
                tenant_id=x_tenant_id,
                dispatch_type=req.dispatch_type,
            )
            result = {"records": records, "store_count": len(records)}
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))


@router.post("/versions/{version_id}/rollback")
async def api_rollback_version(
    version_id: str,
    req: RollbackReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """回滚指定门店到目标版本"""
    try:
        record = await MenuVersionService.rollback_store(
            store_id=req.store_id,
            version_id=version_id,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": record}
    except ValueError as exc:
        _err(400, str(exc))


@router.get("/versions/{version_id}/dispatch")
async def api_get_dispatch_status(
    version_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """查询版本下发进度（applied/pending/failed 数量及应用率）"""
    try:
        status = await MenuDispatchService.get_dispatch_status(
            version_id=version_id,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": status}
    except ValueError as exc:
        _err(400, str(exc))


@router.post("/versions/{version_id}/confirm-applied")
async def api_confirm_applied(
    version_id: str,
    req: ConfirmAppliedReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """门店应用菜单后回调，将下发记录状态更新为 applied"""
    try:
        record = await MenuVersionService.confirm_applied(
            record_id=req.record_id,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": record}
    except ValueError as exc:
        _err(400, str(exc))


# ═══════════════════════════════════════════
# 门店维度
# ═══════════════════════════════════════════


@router.post("/stores/{store_id}/override")
async def api_store_override(
    store_id: str,
    req: StoreOverrideReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """门店微调：在基础版本上增/停菜品或覆盖价格（不修改版本本身）"""
    try:
        record = await MenuVersionService.apply_store_override(
            store_id=store_id,
            overrides={
                "add_dishes": req.add_dishes,
                "remove_dishes": req.remove_dishes,
                "price_overrides": req.price_overrides,
            },
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": record}
    except ValueError as exc:
        _err(400, str(exc))


@router.get("/stores/{store_id}/current-version")
async def api_get_store_current_version(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """查询门店当前使用的菜单版本（最新 applied 记录 + 版本快照）"""
    try:
        result = await MenuVersionService.get_store_current_version(
            store_id=store_id,
            tenant_id=x_tenant_id,
        )
        if not result:
            _err(404, f"门店尚未应用任何版本: {store_id}")
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))
