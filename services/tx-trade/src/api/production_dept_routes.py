"""出品部门（档口）路由配置 API

实现"点菜自动分单到对应档口"的核心配置管理接口：
  档口 CRUD：
    POST   /api/v1/production-depts              — 创建档口
    GET    /api/v1/production-depts              — 列出门店所有档口
    GET    /api/v1/production-depts/{dept_id}    — 查询单个档口
    PUT    /api/v1/production-depts/{dept_id}    — 更新档口配置（打印机/KDS）
    DELETE /api/v1/production-depts/{dept_id}    — 删除档口（需先解绑菜品）

  菜品-档口映射：
    POST /api/v1/production-depts/dish-mappings               — 设置菜品所属档口
    GET  /api/v1/production-depts/dish-mappings               — 查询菜品所属档口
    POST /api/v1/production-depts/dish-mappings/batch         — 批量设置（Excel导入）
    DELETE /api/v1/production-depts/dish-mappings/{dish_id}   — 解绑菜品与档口

  KDS设备识别：
    GET /api/v1/production-depts/kds-device/{device_id}  — KDS设备自我识别

所有接口需要 X-Tenant-ID header。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.production_dept_service import (
    batch_set_dish_dept_mappings,
    create_production_dept,
    delete_production_dept,
    get_dept_by_kds_device_id,
    get_dish_dept_mapping,
    get_production_dept_by_id,
    get_production_depts,
    list_dish_mappings_for_dept,
    remove_dish_dept_mapping,
    set_dish_dept_mapping,
    update_production_dept,
)

router = APIRouter(prefix="/api/v1/production-depts", tags=["production-depts"])


# ─── 公共依赖 ───


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 请求/响应 Schemas ───


class CreateDeptReq(BaseModel):
    brand_id: str = Field(description="品牌ID")
    store_id: Optional[str] = Field(default=None, description="门店ID（None=品牌级通用档口）")
    dept_name: str = Field(min_length=1, max_length=50, description="档口名称，如'凉菜档'")
    dept_code: str = Field(min_length=1, max_length=20, description="档口编码，如'cold'，同门店下唯一")
    printer_address: Optional[str] = Field(
        default=None,
        description="厨打网络地址 host:port，如 192.168.1.101:9100",
    )
    printer_type: str = Field(default="network", description="打印机类型：network/usb/bluetooth")
    kds_device_id: Optional[str] = Field(
        default=None,
        description="关联KDS设备标识（设备序列号或自定义名称），NULL表示无KDS屏",
    )
    display_color: str = Field(default="blue", description="KDS颜色标识：red/orange/green/blue/purple")
    fixed_fee_type: Optional[str] = Field(default=None, description="固定费用类型")
    default_timeout_minutes: int = Field(default=15, ge=1, le=120, description="默认出品时限(分钟)")
    sort_order: int = Field(default=0, ge=0, description="排序序号，越小越靠前")


class UpdateDeptReq(BaseModel):
    dept_name: Optional[str] = Field(default=None, max_length=50)
    dept_code: Optional[str] = Field(default=None, max_length=20)
    printer_address: Optional[str] = Field(default=None, description="厨打网络地址 host:port")
    printer_type: Optional[str] = Field(default=None)
    kds_device_id: Optional[str] = Field(default=None, description="KDS设备标识，传空字符串清除")
    display_color: Optional[str] = Field(default=None)
    fixed_fee_type: Optional[str] = Field(default=None)
    default_timeout_minutes: Optional[int] = Field(default=None, ge=1, le=120)
    sort_order: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = Field(default=None, description="是否启用该档口")


class SetDishMappingReq(BaseModel):
    dish_id: str = Field(description="菜品ID")
    dept_id: str = Field(description="目标档口ID")
    is_primary: bool = Field(default=True, description="是否设为主档口")
    printer_id: Optional[str] = Field(default=None, description="覆盖打印机ID（可选）")


class BatchMappingItem(BaseModel):
    dish_id: str
    dept_id: str
    is_primary: bool = True
    printer_id: Optional[str] = None


class BatchSetMappingsReq(BaseModel):
    mappings: list[BatchMappingItem] = Field(min_length=1, description="批量映射列表")


def _dept_to_dict(dept) -> dict:
    """将 ProductionDept 转为 API 响应字典。"""
    return {
        "dept_id": str(dept.id),
        "dept_name": dept.dept_name,
        "dept_code": dept.dept_code,
        "brand_id": str(dept.brand_id),
        "store_id": str(dept.store_id) if dept.store_id else None,
        "printer_address": dept.printer_address,
        "printer_type": dept.printer_type,
        "kds_device_id": dept.kds_device_id,
        "display_color": dept.display_color,
        "fixed_fee_type": dept.fixed_fee_type,
        "default_timeout_minutes": dept.default_timeout_minutes,
        "sort_order": dept.sort_order,
        "is_active": dept.is_active,
        "created_at": dept.created_at.isoformat() if dept.created_at else None,
        "updated_at": dept.updated_at.isoformat() if dept.updated_at else None,
    }


def _mapping_to_dict(m) -> dict:
    """将 DishDeptMapping 转为 API 响应字典。"""
    return {
        "mapping_id": str(m.id),
        "dish_id": str(m.dish_id),
        "dept_id": str(m.production_dept_id),
        "is_primary": m.is_primary,
        "printer_id": str(m.printer_id) if m.printer_id else None,
        "sort_order": m.sort_order,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


# ─── 档口 CRUD ───


@router.post("")
async def api_create_production_dept(
    body: CreateDeptReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """创建出品部门（档口）。

    一个档口配置打印机地址和KDS设备ID，订单提交时自动将对应菜品分发到此档口。
    """
    tenant_id = _get_tenant_id(request)
    try:
        dept = await create_production_dept(
            tenant_id=tenant_id,
            brand_id=body.brand_id,
            store_id=body.store_id,
            dept_name=body.dept_name,
            dept_code=body.dept_code,
            printer_address=body.printer_address,
            printer_type=body.printer_type,
            kds_device_id=body.kds_device_id,
            display_color=body.display_color,
            fixed_fee_type=body.fixed_fee_type,
            default_timeout_minutes=body.default_timeout_minutes,
            sort_order=body.sort_order,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _ok(_dept_to_dict(dept))


@router.get("")
async def api_list_production_depts(
    request: Request,
    store_id: Optional[str] = Query(default=None, description="按门店过滤"),
    brand_id: Optional[str] = Query(default=None, description="按品牌过滤"),
    active_only: bool = Query(default=True, description="只返回启用的档口"),
    db: AsyncSession = Depends(get_db),
):
    """查询出品部门列表。

    返回指定门店的所有档口（包含品牌级通用档口）。
    KDS平板启动时调用此接口获取档口列表。
    """
    tenant_id = _get_tenant_id(request)
    depts = await get_production_depts(
        tenant_id=tenant_id,
        store_id=store_id,
        brand_id=brand_id,
        active_only=active_only,
        db=db,
    )
    items = [_dept_to_dict(d) for d in depts]
    return _ok({"items": items, "total": len(items)})


@router.get("/kds-device/{device_id}")
async def api_get_dept_by_kds_device(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """KDS设备自我识别接口。

    KDS平板开机后携带自身 device_id 调用此接口，获取所属档口信息。
    档口信息中包含 kds_device_id 供 KDS 屏幕确认身份。
    """
    tenant_id = _get_tenant_id(request)
    dept = await get_dept_by_kds_device_id(device_id, tenant_id, db)
    if dept is None:
        return {"ok": False, "data": None, "error": {"message": f"KDS设备 {device_id} 未绑定到任何档口"}}
    return _ok(_dept_to_dict(dept))


@router.get("/{dept_id}")
async def api_get_production_dept(
    dept_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查询单个档口详情。"""
    tenant_id = _get_tenant_id(request)
    dept = await get_production_dept_by_id(dept_id, tenant_id, db)
    if dept is None:
        raise HTTPException(status_code=404, detail=f"档口 {dept_id} 不存在")
    return _ok(_dept_to_dict(dept))


@router.put("/{dept_id}")
async def api_update_production_dept(
    dept_id: str,
    body: UpdateDeptReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """更新档口配置。

    可更新：打印机IP/端口、KDS设备ID、颜色标识、是否启用等。
    """
    tenant_id = _get_tenant_id(request)
    try:
        dept = await update_production_dept(
            dept_id=dept_id,
            tenant_id=tenant_id,
            db=db,
            dept_name=body.dept_name,
            dept_code=body.dept_code,
            printer_address=body.printer_address,
            printer_type=body.printer_type,
            kds_device_id=body.kds_device_id if body.kds_device_id != "" else None,
            display_color=body.display_color,
            fixed_fee_type=body.fixed_fee_type,
            default_timeout_minutes=body.default_timeout_minutes,
            sort_order=body.sort_order,
            is_active=body.is_active,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _ok(_dept_to_dict(dept))


@router.delete("/{dept_id}")
async def api_delete_production_dept(
    dept_id: str,
    request: Request,
    force: bool = Query(default=False, description="强制删除（同时解绑所有菜品映射）"),
    db: AsyncSession = Depends(get_db),
):
    """删除档口。

    默认不允许删除有菜品映射的档口，需先解绑菜品。
    传 force=true 可强制删除（同时软删除所有菜品映射）。
    """
    tenant_id = _get_tenant_id(request)
    try:
        await delete_production_dept(dept_id, tenant_id, db, force=force)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _ok({"dept_id": dept_id, "deleted": True})


# ─── 菜品-档口映射管理 ───


@router.post("/dish-mappings")
async def api_set_dish_mapping(
    body: SetDishMappingReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """设置菜品所属档口。

    将一道菜绑定到某个档口，订单提交时该菜品会自动路由到此档口。
    设置为主档口（is_primary=True）时，会自动降级该菜品之前的主档口绑定。
    """
    tenant_id = _get_tenant_id(request)
    try:
        mapping = await set_dish_dept_mapping(
            tenant_id=tenant_id,
            dish_id=body.dish_id,
            dept_id=body.dept_id,
            db=db,
            is_primary=body.is_primary,
            printer_id=body.printer_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return _ok(_mapping_to_dict(mapping))


@router.get("/dish-mappings")
async def api_get_dish_mapping(
    request: Request,
    dish_id: str = Query(description="菜品ID"),
    primary_only: bool = Query(default=True, description="只返回主档口"),
    db: AsyncSession = Depends(get_db),
):
    """查询菜品所属档口。"""
    tenant_id = _get_tenant_id(request)
    try:
        mapping = await get_dish_dept_mapping(tenant_id, dish_id, db, primary_only=primary_only)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if mapping is None:
        return {"ok": True, "data": None, "error": None}

    return _ok(_mapping_to_dict(mapping))


@router.post("/dish-mappings/batch")
async def api_batch_set_dish_mappings(
    body: BatchSetMappingsReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """批量设置菜品-档口映射（Excel导入场景）。

    一次请求最多支持 500 条映射记录。
    """
    if len(body.mappings) > 500:
        raise HTTPException(status_code=400, detail="单次批量最多支持 500 条映射")

    tenant_id = _get_tenant_id(request)
    mappings_data = [m.model_dump() for m in body.mappings]

    try:
        results = await batch_set_dish_dept_mappings(tenant_id, mappings_data, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _ok(
        {
            "created_count": len(results),
            "items": [_mapping_to_dict(m) for m in results],
        }
    )


@router.delete("/dish-mappings/{dish_id}")
async def api_remove_dish_mapping(
    dish_id: str,
    request: Request,
    dept_id: str = Query(description="要解绑的档口ID"),
    db: AsyncSession = Depends(get_db),
):
    """解除菜品与档口的绑定。"""
    tenant_id = _get_tenant_id(request)
    try:
        await remove_dish_dept_mapping(tenant_id, dish_id, dept_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return _ok({"dish_id": dish_id, "dept_id": dept_id, "unbound": True})


@router.get("/{dept_id}/dishes")
async def api_list_dept_dishes(
    dept_id: str,
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """查询某档口下所有绑定的菜品（分页）。"""
    tenant_id = _get_tenant_id(request)

    # 验证档口存在
    dept = await get_production_dept_by_id(dept_id, tenant_id, db)
    if dept is None:
        raise HTTPException(status_code=404, detail=f"档口 {dept_id} 不存在")

    items, total = await list_dish_mappings_for_dept(
        tenant_id=tenant_id,
        dept_id=dept_id,
        db=db,
        page=page,
        size=size,
    )

    return _ok(
        {
            "items": [_mapping_to_dict(m) for m in items],
            "total": total,
            "page": page,
            "size": size,
        }
    )
