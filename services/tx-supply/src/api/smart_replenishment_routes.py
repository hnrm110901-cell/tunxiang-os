"""智能补货 API 路由

端点：
  GET  /check/{store_id}                         - 检查并返回需补货清单
  POST /auto/{store_id}                          - 自动创建 draft 申购单
  GET  /thresholds/{store_id}                    - 查询阈值配置
  PUT  /thresholds/{store_id}/{ingredient_id}    - 设置阈值

统一响应格式: {"ok": bool, "data": {}, "error": {}}

# ROUTER REGISTRATION:
# from .api.smart_replenishment_routes import router as smart_replenishment_router
# app.include_router(smart_replenishment_router, prefix="/api/v1/smart-replenishment")
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["smart-replenishment"])


# ─── 数据库依赖占位 ───

async def _get_db():
    """数据库会话依赖 — 由 main.py 覆盖"""
    raise NotImplementedError("DB session dependency not configured")


# ─── 请求模型 ───

class SetThresholdRequest(BaseModel):
    safety_stock: float = Field(ge=0, description="安全库存量")
    target_stock: float = Field(ge=0, description="目标库存量（补货上限）")
    min_order_qty: float = Field(default=1.0, gt=0, description="最小订货量（取整单位）")
    trigger_rule: str = Field(
        default="safety_only",
        pattern="^(safety_only|dual)$",
        description="触发规则: safety_only | dual",
    )
    ingredient_name: str = ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /check/{store_id}
#  检查并返回需补货清单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/check/{store_id}")
async def check_replenishment(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """检查门店库存，返回需补货清单。

    对每个已配置阈值的原料检查当前库存：
    - safety_only: current < safety_stock 触发
    - dual: 额外检测近7日高速消耗，提前到 safety*1.5 触发

    Returns:
        {
          "store_id": str,
          "total": int,
          "urgent_count": int,
          "items": [ReplenishmentItem]
        }
    """
    from ..services.smart_replenishment import SmartReplenishmentService

    svc = SmartReplenishmentService()
    try:
        items = await svc.check_and_recommend(
            store_id=store_id,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "total": len(items),
            "urgent_count": sum(1 for i in items if i.urgency == "urgent"),
            "items": [i.model_dump() for i in items],
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /auto/{store_id}
#  自动创建 draft 申购单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/auto/{store_id}")
async def auto_create_requisition(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """自动触发补货，生成 draft 申购单（source='smart_replenishment'）。

    若库存充足，返回 skipped=true，不创建申购单。

    Returns:
        {
          "requisition_id": str | null,
          "items_count": int,
          "skipped": bool,
          "source": "smart_replenishment"
        }
    """
    from ..services.smart_replenishment import SmartReplenishmentService

    svc = SmartReplenishmentService()
    try:
        result = await svc.auto_create_requisition(
            store_id=store_id,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "data": result.model_dump()}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /thresholds/{store_id}
#  查询阈值配置列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/thresholds/{store_id}")
async def get_thresholds(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """查询门店所有原料的库存阈值配置。

    Returns:
        {
          "store_id": str,
          "total": int,
          "thresholds": [InventoryThreshold]
        }
    """
    from ..services.smart_replenishment import SmartReplenishmentService

    svc = SmartReplenishmentService()
    try:
        thresholds = await svc.get_thresholds(
            store_id=store_id,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "total": len(thresholds),
            "thresholds": [t.model_dump() for t in thresholds],
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PUT /thresholds/{store_id}/{ingredient_id}
#  设置/更新单个原料阈值
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.put("/thresholds/{store_id}/{ingredient_id}")
async def set_threshold(
    store_id: str,
    ingredient_id: str,
    body: SetThresholdRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """设置或更新原料库存阈值（upsert）。

    - safety_stock: 安全库存，低于此值触发补货
    - target_stock: 目标库存（补货上限），target >= safety
    - min_order_qty: 最小订货量，补货量按此向上取整
    - trigger_rule: safety_only | dual
    """
    from ..services.smart_replenishment import SmartReplenishmentService

    svc = SmartReplenishmentService()
    try:
        threshold = await svc.set_threshold(
            store_id=store_id,
            ingredient_id=ingredient_id,
            safety=body.safety_stock,
            target=body.target_stock,
            tenant_id=x_tenant_id,
            db=db,
            min_order_qty=body.min_order_qty,
            trigger_rule=body.trigger_rule,
            ingredient_name=body.ingredient_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "data": threshold.model_dump()}
