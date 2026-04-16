"""薪资项目库 API — 7大类71项标准模板 + 自定义扩展"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from services.salary_item_library import (
    CATEGORIES,
    compute_salary_by_items,
    create_custom_salary_item,
    get_all_items,
    get_categories,
    get_item_by_code,
    get_items_by_category,
    get_tenant_salary_items,
    init_salary_items_for_tenant,
    init_store_salary_config,
    toggle_salary_item,
)

router = APIRouter(prefix="/api/v1/org", tags=["salary-items"])


# ── 请求模型 ──


class InitSalaryConfigReq(BaseModel):
    template: str = Field(
        default="standard",
        description="模板类型: standard(标准中餐) / seafood(海鲜酒楼) / fast_food(快餐)",
    )


class ComputeSalaryReq(BaseModel):
    employee_data: dict = Field(
        ...,
        description="员工薪资相关数据（base_salary_fen, attendance_days等）",
    )
    enabled_items: list[str] = Field(
        ...,
        description="启用的薪资项目编码列表",
    )


class InitSalaryItemsReq(BaseModel):
    template: str = Field(
        default="standard",
        description="模板类型: standard / seafood / fast_food",
    )


class CustomSalaryItemReq(BaseModel):
    item_code: str = Field(..., description="自定义薪资项编码，如 CUSTOM_001")
    item_name: str = Field(..., description="薪资项名称")
    category: str = Field(..., description="分类: attendance/leave/performance/commission/subsidy/deduction/social")
    tax_type: str = Field(default="pre_tax_add", description="税前加减: pre_tax_add / pre_tax_sub / other")
    calc_rule: str = Field(default="manual", description="计算规则: fixed / formula / manual")
    formula: str = Field(default="", description="计算公式")
    default_value_fen: int = Field(default=0, description="默认值（分）")
    description: str = Field(default="", description="说明")


class ToggleReq(BaseModel):
    is_enabled: bool = Field(..., description="启用/禁用")


# ── 端点 ──


@router.get("/salary-items")
async def list_salary_items(category: Optional[str] = None):
    """获取完整薪资项目库（内存模板），可按分类筛选"""
    if category:
        items = get_items_by_category(category)
        if not items:
            return {"ok": True, "data": {"items": [], "total": 0}}
        return {
            "ok": True,
            "data": {
                "items": [item.to_dict() for item in items],
                "total": len(items),
            },
        }
    items = get_all_items()
    return {
        "ok": True,
        "data": {
            "items": [item.to_dict() for item in items],
            "total": len(items),
        },
    }


@router.get("/salary-items/categories")
async def list_categories():
    """获取薪资项目分类列表及每类数量"""
    categories = get_categories()
    return {
        "ok": True,
        "data": {
            "categories": [
                {"key": k, "name": v, "count": len(get_items_by_category(k))}
                for k, v in categories.items()
            ]
        },
    }


@router.get("/salary-items/template-preview")
async def template_preview(template: str = "standard"):
    """预览初始化模板（不写DB，仅返回模板内容）"""
    try:
        config = init_store_salary_config(template)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "data": config}


@router.post("/salary-items/init")
async def init_salary_config(req: InitSalaryConfigReq):
    """为新门店初始化薪资配置（纯内存模板预览，向下兼容）"""
    try:
        config = init_store_salary_config(req.template)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "data": config}


@router.post("/salary-items/init-db")
async def init_salary_items_db(req: InitSalaryItemsReq, request: Request):
    """为租户初始化标准薪资项到 DB（从模板批量写入 salary_item_templates 表）"""
    tenant_id = request.headers.get("X-Tenant-ID", "")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")

    db = request.app.state.db_pool
    try:
        result = await init_salary_items_for_tenant(db, tenant_id, req.template)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "data": result}


@router.get("/salary-items/tenant")
async def list_tenant_salary_items(
    request: Request,
    category: Optional[str] = None,
    enabled_only: bool = False,
):
    """获取租户已持久化的薪资项列表（从 DB 读取）"""
    tenant_id = request.headers.get("X-Tenant-ID", "")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")

    db = request.app.state.db_pool
    items = await get_tenant_salary_items(db, tenant_id, category, enabled_only)
    return {
        "ok": True,
        "data": {
            "items": items,
            "total": len(items),
        },
    }


@router.post("/salary-items/custom")
async def create_custom_item(req: CustomSalaryItemReq, request: Request):
    """创建自定义薪资项（写入 DB）"""
    tenant_id = request.headers.get("X-Tenant-ID", "")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")

    db = request.app.state.db_pool
    try:
        result = await create_custom_salary_item(
            db,
            tenant_id,
            item_code=req.item_code,
            item_name=req.item_name,
            category=req.category,
            tax_type=req.tax_type,
            calc_rule=req.calc_rule,
            formula=req.formula,
            default_value_fen=req.default_value_fen,
            description=req.description,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "data": result}


@router.put("/salary-items/{item_code}/toggle")
async def toggle_item(item_code: str, req: ToggleReq, request: Request):
    """启用/禁用租户的某个薪资项"""
    tenant_id = request.headers.get("X-Tenant-ID", "")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")

    db = request.app.state.db_pool
    try:
        result = await toggle_salary_item(db, tenant_id, item_code, req.is_enabled)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "data": result}


@router.post("/salary-items/compute")
async def compute_salary(req: ComputeSalaryReq):
    """按启用的薪资项目计算工资"""
    result = compute_salary_by_items(req.employee_data, req.enabled_items)
    return {"ok": True, "data": result}
