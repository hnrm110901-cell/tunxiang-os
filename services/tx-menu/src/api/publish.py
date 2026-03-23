"""菜品发布方案 API"""
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel

from ..services.publish_service import (
    create_publish_plan,
    execute_publish,
    create_price_adjustment,
)

router = APIRouter(prefix="/api/v1/menu", tags=["publish"])


# ---------- Request Models ----------

class CreatePublishPlanReq(BaseModel):
    plan_name: str
    dish_ids: list[str]
    target_store_ids: list[str]
    schedule_time: Optional[str] = None


class ExecutePublishReq(BaseModel):
    dish_data: list[dict]
    target_stores: list[str]


class PriceAdjustmentRule(BaseModel):
    condition: str
    price_modifier: int
    description: Optional[str] = None


class CreatePriceAdjustmentReq(BaseModel):
    store_id: str
    adjustment_type: str
    rules: list[PriceAdjustmentRule]


# ---------- In-Memory Storage (demo) ----------

_publish_plans: dict[str, dict] = {}
_price_adjustments: dict[str, dict] = {}


# ---------- Publish Plan Endpoints ----------

@router.post("/publish-plans")
async def api_create_publish_plan(req: CreatePublishPlanReq):
    """创建发布方案"""
    plan = create_publish_plan(
        plan_name=req.plan_name,
        dish_ids=req.dish_ids,
        target_store_ids=req.target_store_ids,
        schedule_time=req.schedule_time,
    )
    _publish_plans[plan["plan_id"]] = plan
    return {"ok": True, "data": plan}


@router.post("/publish-plans/{plan_id}/execute")
async def api_execute_publish(plan_id: str, req: ExecutePublishReq):
    """执行发布方案"""
    result = execute_publish(
        plan_id=plan_id,
        dish_data=req.dish_data,
        target_stores=req.target_stores,
    )
    # 更新方案状态
    if plan_id in _publish_plans:
        _publish_plans[plan_id]["status"] = "published"
    return {"ok": True, "data": result}


@router.get("/publish-plans")
async def api_list_publish_plans(page: int = 1, size: int = 20):
    """列出发布方案"""
    plans = list(_publish_plans.values())
    start = (page - 1) * size
    end = start + size
    return {
        "ok": True,
        "data": {
            "items": plans[start:end],
            "total": len(plans),
            "page": page,
            "size": size,
        },
    }


# ---------- Price Adjustment Endpoints ----------

@router.post("/price-adjustments")
async def api_create_price_adjustment(req: CreatePriceAdjustmentReq):
    """创建价格调整方案"""
    adjustment = create_price_adjustment(
        store_id=req.store_id,
        adjustment_type=req.adjustment_type,
        rules=[r.model_dump() for r in req.rules],
    )
    _price_adjustments[adjustment["adjustment_id"]] = adjustment
    return {"ok": True, "data": adjustment}


@router.get("/price-adjustments")
async def api_list_price_adjustments(store_id: Optional[str] = None, page: int = 1, size: int = 20):
    """列出价格调整方案"""
    items = list(_price_adjustments.values())
    if store_id:
        items = [a for a in items if a["store_id"] == store_id]
    start = (page - 1) * size
    end = start + size
    return {
        "ok": True,
        "data": {
            "items": items[start:end],
            "total": len(items),
            "page": page,
            "size": size,
        },
    }
