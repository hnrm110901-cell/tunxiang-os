"""薪资项目库 API"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.salary_item_library import (
    get_all_items,
    get_items_by_category,
    get_categories,
    init_store_salary_config,
    compute_salary_by_items,
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


# ── 端点 ──


@router.get("/salary-items")
async def list_salary_items(category: Optional[str] = None):
    """获取完整薪资项目库，可按分类筛选"""
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
    """获取薪资项目分类列表"""
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


@router.post("/salary-items/init")
async def init_salary_config(req: InitSalaryConfigReq):
    """为新门店初始化薪资配置"""
    try:
        config = init_store_salary_config(req.template)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "data": config}


@router.post("/salary-items/compute")
async def compute_salary(req: ComputeSalaryReq):
    """按启用的薪资项目计算工资"""
    result = compute_salary_by_items(req.employee_data, req.enabled_items)
    return {"ok": True, "data": result}
