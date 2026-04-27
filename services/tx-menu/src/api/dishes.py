"""菜品管理 API"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/menu", tags=["menu"])


class CreateDishReq(BaseModel):
    dish_name: str
    dish_code: str
    price_fen: int
    category_id: Optional[str] = None
    kitchen_station: Optional[str] = None
    preparation_time: Optional[int] = None


class BOMItemReq(BaseModel):
    ingredient_id: str
    quantity: float
    unit: str


# 菜品 CRUD
@router.get("/dishes")
async def list_dishes(store_id: str, category_id: Optional[str] = None, page: int = 1, size: int = 20):
    return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size}}


@router.post("/dishes")
async def create_dish(req: CreateDishReq):
    return {"ok": True, "data": {"dish_id": "new", "dish_code": req.dish_code}}


@router.get("/dishes/{dish_id}")
async def get_dish(dish_id: str):
    return {"ok": True, "data": None}


@router.patch("/dishes/{dish_id}")
async def update_dish(dish_id: str, req: dict):
    return {"ok": True, "data": {"dish_id": dish_id, "updated": True}}


@router.delete("/dishes/{dish_id}")
async def delete_dish(dish_id: str):
    return {"ok": True, "data": {"deleted": True}}


# BOM 配方
@router.get("/dishes/{dish_id}/bom")
async def get_dish_bom(dish_id: str):
    return {"ok": True, "data": {"dish_id": dish_id, "items": []}}


@router.put("/dishes/{dish_id}/bom")
async def update_dish_bom(dish_id: str, items: list[BOMItemReq]):
    return {"ok": True, "data": {"dish_id": dish_id, "bom_count": len(items)}}


# 菜品分析
@router.get("/dishes/{dish_id}/quadrant")
async def get_dish_quadrant(dish_id: str):
    """四象限分类：明星/金牛/问题/瘦狗"""
    return {"ok": True, "data": {"quadrant": "star"}}


@router.get("/ranking")
async def get_menu_ranking(store_id: str, period: str = "week"):
    """菜单排名（按销量/毛利/评分）"""
    return {"ok": True, "data": {"rankings": []}}


@router.post("/pricing/simulate")
async def simulate_pricing(dish_id: str, scenarios: list[dict]):
    """动态定价仿真"""
    return {"ok": True, "data": {"scenarios": []}}


# 分类管理
@router.get("/categories")
async def list_categories(store_id: str):
    return {"ok": True, "data": {"categories": []}}


@router.post("/categories")
async def create_category(name: str, parent_id: Optional[str] = None):
    return {"ok": True, "data": {"category_id": "new"}}
