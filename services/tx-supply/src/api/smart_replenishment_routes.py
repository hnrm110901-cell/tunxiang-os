"""智能补货 API 路由

端点：
  GET  /check/{store_id}                         - 检查并返回需补货清单
  POST /auto/{store_id}                          - 自动创建 draft 申购单
  GET  /thresholds/{store_id}                    - 查询阈值配置
  PUT  /thresholds/{store_id}/{ingredient_id}    - 设置阈值

  -- 采购预测（procurement_forecast_service）--
  GET  /forecast/{store_id}                      - 未来7天采购预测
  POST /draft-order/{store_id}                   - 生成分供应商采购草稿
  GET  /urgent/{store_id}                        - 紧急补货预警（今日，不走AI）

统一响应格式: {"ok": bool, "data": {}, "error": {}}

# ROUTER REGISTRATION:
# from .api.smart_replenishment_routes import router as smart_replenishment_router
# app.include_router(smart_replenishment_router, prefix="/api/v1/smart-replenishment")
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from shared.ontology.src.database import get_db as _get_db

router = APIRouter(tags=["smart-replenishment"])


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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /forecast/{store_id}
#  未来7天采购预测
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/forecast/{store_id}")
async def get_procurement_forecast(
    store_id: str,
    days: int = Query(default=7, ge=1, le=30, description="预测天数，默认7天，最大30天"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """预测未来N天食材采购需求。

    基于历史销售数据（DemandForecastService）计算各食材消耗预测，
    结合当前库存和安全库存阈值，生成采购建议清单。

    - purchase_qty=0 表示库存充足，无需采购
    - confidence 字段表示预测置信度（0-1）
    - 考虑供应商交期缓冲（lead_days）

    Returns:
        {
          "store_id": str,
          "forecast_days": int,
          "total": int,
          "need_purchase_count": int,
          "items": [IngredientDemandForecast]
        }
    """
    from ..services.procurement_forecast_service import ProcurementForecastService

    svc = ProcurementForecastService()
    try:
        forecasts = await svc.forecast_ingredient_demand(
            store_id=store_id,
            tenant_id=x_tenant_id,
            forecast_days=days,
            db=db,
        )
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "forecast_days": days,
            "total": len(forecasts),
            "need_purchase_count": sum(1 for f in forecasts if f.purchase_qty > 0),
            "items": [f.model_dump() for f in forecasts],
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /draft-order/{store_id}
#  生成采购草稿（按供应商分组）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class DraftOrderRequest(BaseModel):
    forecast_days: int = Field(default=7, ge=1, le=30, description="基于N天预测生成草稿")


@router.post("/draft-order/{store_id}")
async def create_draft_order(
    store_id: str,
    body: DraftOrderRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """基于销售预测生成分供应商采购草稿单。

    流程：
      1. 调用 forecast_ingredient_demand 获取需求预测
      2. 按供应商分组整合采购项
      3. 计算各供应商采购金额
      4. 总金额 >= 1万元时，调用 AI 生成摘要说明

    Returns:
        {
          "store_id": str,
          "total_amount_fen": int,
          "suppliers_count": int,
          "ai_summary": str | null,
          "orders": [SupplierOrder]
        }
    """
    from ..services.procurement_forecast_service import ProcurementForecastService

    svc = ProcurementForecastService()
    try:
        # Step 1: 获取需求预测
        forecasts = await svc.forecast_ingredient_demand(
            store_id=store_id,
            tenant_id=x_tenant_id,
            forecast_days=body.forecast_days,
            db=db,
        )

        # Step 2: 生成草稿
        draft = await svc.generate_purchase_order_draft(
            store_id=store_id,
            tenant_id=x_tenant_id,
            demand_forecast=forecasts,
            db=db,
        )
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "total_amount_fen": draft.total_amount_fen,
            "suppliers_count": len(draft.orders_by_supplier),
            "ai_summary": draft.ai_summary,
            "created_at": draft.created_at,
            "orders": [o.model_dump() for o in draft.orders_by_supplier],
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /urgent/{store_id}
#  紧急补货预警（今日，实时，不走AI）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/urgent/{store_id}")
async def get_urgent_replenishment(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """紧急补货预警：库存不足以支撑明日营业的食材清单。

    实时计算，不走 AI，低延迟优先。
    判断条件：current_stock < tomorrow_demand 或 current_stock < safety_stock

    Returns:
        {
          "store_id": str,
          "urgent_count": int,
          "items": [UrgentIngredient]  -- 按缺口量降序
        }
    """
    from ..services.procurement_forecast_service import ProcurementForecastService

    svc = ProcurementForecastService()
    try:
        urgent_items = await svc.get_replenishment_urgency(
            store_id=store_id,
            tenant_id=x_tenant_id,
            db=db,
        )
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "urgent_count": len(urgent_items),
            "items": [i.model_dump() for i in urgent_items],
        },
    }
