"""AI动态定价路由 — 时段x需求x库存x天气x会员 → 智能价格

端点:
- GET  /api/v1/dynamic-pricing/{store_id}/dish/{dish_id}  单品动态价格
- POST /api/v1/dynamic-pricing/{store_id}/batch            批量计算全店
- POST /api/v1/dynamic-pricing/{store_id}/simulate         What-if模拟
- GET  /api/v1/dynamic-pricing/{store_id}/history/{dish_id} 定价历史
- GET  /api/v1/dynamic-pricing/rules                       规则列表
- POST /api/v1/dynamic-pricing/rules                       创建规则
- PUT  /api/v1/dynamic-pricing/rules/{rule_id}             更新规则
- DELETE /api/v1/dynamic-pricing/rules/{rule_id}           删除规则

金额单位: 分(fen), API响应同时提供 _yuan 浮点。
"""

from datetime import date
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.dynamic_pricing_ai_service import DynamicPricingAIService

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/dynamic-pricing", tags=["dynamic-pricing"])

_svc = DynamicPricingAIService()


# ─── 请求/响应模型 ───────────────────────────────────────────────────


class DynamicPriceContext(BaseModel):
    daypart: Optional[str] = Field(None, pattern="^(lunch|afternoon|dinner|late)$")
    occupancy_rate: Optional[float] = Field(None, ge=0.0, le=1.0)
    weather: Optional[str] = None
    inventory_days: Optional[int] = Field(None, ge=0)
    member_tier: Optional[str] = None
    is_holiday: Optional[bool] = None


class SimulatePricingReq(BaseModel):
    dish_id: str
    mock_context: DynamicPriceContext


class CreateRuleReq(BaseModel):
    store_id: str
    dish_id: str
    rule_type: str = Field(
        ...,
        pattern="^(time_based|demand_based|inventory_based|weather_based|member_tier)$",
    )
    daypart: Optional[str] = Field(None, pattern="^(lunch|afternoon|dinner|late)$")
    condition: dict[str, Any] = Field(default_factory=dict)
    adjustment_type: str = Field(..., pattern="^(percent|fixed)$")
    adjustment_value: int = Field(
        ...,
        description="百分比如-10表示降10%, fixed如-500表示减5元",
    )
    min_price_fen: Optional[int] = Field(None, ge=0, description="地板价(分)")
    max_price_fen: Optional[int] = Field(None, ge=0, description="天花板价(分)")
    priority: int = Field(0, ge=0, le=100)
    is_active: bool = True
    effective_from: Optional[date] = None
    effective_until: Optional[date] = None


class UpdateRuleReq(BaseModel):
    condition: Optional[dict[str, Any]] = None
    adjustment_type: Optional[str] = Field(None, pattern="^(percent|fixed)$")
    adjustment_value: Optional[int] = None
    min_price_fen: Optional[int] = Field(None, ge=0)
    max_price_fen: Optional[int] = Field(None, ge=0)
    priority: Optional[int] = Field(None, ge=0, le=100)
    is_active: Optional[bool] = None
    daypart: Optional[str] = Field(None, pattern="^(lunch|afternoon|dinner|late)$")
    effective_from: Optional[date] = None
    effective_until: Optional[date] = None


# ─── 1. 单品动态价格 ────────────────────────────────────────────────


@router.get("/{store_id}/dish/{dish_id}")
async def get_dynamic_price(
    store_id: str,
    dish_id: str,
    daypart: Optional[str] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """计算单品AI动态价格（实时）"""
    ctx: dict[str, Any] = {}
    if daypart:
        ctx["daypart"] = daypart
    try:
        result = await _svc.calculate_dynamic_price(
            db, store_id, x_tenant_id, dish_id, context=ctx
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        log.error("dynamic_price_error", dish_id=dish_id, error=str(exc))
        raise HTTPException(status_code=500, detail="定价计算失败") from exc


# ─── 2. 批量计算全店价格 ─────────────────────────────────────────────


@router.post("/{store_id}/batch")
async def batch_calculate_prices(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """批量计算门店所有菜品动态价格（开市前刷新）"""
    try:
        results = await _svc.calculate_store_prices(
            db, store_id, x_tenant_id
        )
        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "total": len(results),
                "dishes": results,
            },
        }
    except SQLAlchemyError as exc:
        log.error("batch_price_error", store_id=store_id, error=str(exc))
        raise HTTPException(status_code=500, detail="批量定价失败") from exc


# ─── 3. What-if 模拟 ────────────────────────────────────────────────


@router.post("/{store_id}/simulate")
async def simulate_pricing(
    store_id: str,
    req: SimulatePricingReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """模拟定价 — 给定假设条件，预览定价结果（不写库）"""
    mock_ctx = req.mock_context.model_dump(exclude_none=True)
    try:
        result = await _svc.simulate_pricing(
            db, store_id, x_tenant_id, req.dish_id, mock_ctx
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        log.error("simulate_error", dish_id=req.dish_id, error=str(exc))
        raise HTTPException(status_code=500, detail="模拟定价失败") from exc


# ─── 4. 定价历史 ────────────────────────────────────────────────────


@router.get("/{store_id}/history/{dish_id}")
async def get_pricing_history(
    store_id: str,
    dish_id: str,
    days: int = 7,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询菜品动态定价历史"""
    try:
        history = await _svc.get_pricing_history(
            db, store_id, x_tenant_id, dish_id, days=days
        )
        return {
            "ok": True,
            "data": {
                "dish_id": dish_id,
                "store_id": store_id,
                "days": days,
                "records": history,
                "total": len(history),
            },
        }
    except SQLAlchemyError as exc:
        log.error("history_error", dish_id=dish_id, error=str(exc))
        raise HTTPException(status_code=500, detail="查询定价历史失败") from exc


# ─── 5. 规则列表 ────────────────────────────────────────────────────


@router.get("/rules")
async def list_rules(
    store_id: str,
    dish_id: Optional[str] = None,
    rule_type: Optional[str] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """获取动态定价规则列表"""
    try:
        rules = await _svc.list_rules(
            db, store_id, x_tenant_id, dish_id=dish_id, rule_type=rule_type
        )
        return {
            "ok": True,
            "data": {"rules": rules, "total": len(rules)},
        }
    except SQLAlchemyError as exc:
        log.error("list_rules_error", store_id=store_id, error=str(exc))
        raise HTTPException(status_code=500, detail="查询规则失败") from exc


# ─── 6. 创建规则 ────────────────────────────────────────────────────


@router.post("/rules", status_code=201)
async def create_rule(
    req: CreateRuleReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """创建动态定价规则"""
    rule_data = req.model_dump(exclude_none=True)
    store_id = rule_data.pop("store_id")
    try:
        result = await _svc.create_rule(
            db, store_id, x_tenant_id, rule_data
        )
        await db.commit()
        return {"ok": True, "data": result}
    except SQLAlchemyError as exc:
        log.error("create_rule_error", error=str(exc))
        raise HTTPException(status_code=500, detail="创建规则失败") from exc


# ─── 7. 更新规则 ────────────────────────────────────────────────────


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: str,
    req: UpdateRuleReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新动态定价规则"""
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="无有效更新字段")
    try:
        result = await _svc.update_rule(db, x_tenant_id, rule_id, updates)
        if result is None:
            raise HTTPException(status_code=404, detail=f"规则不存在: {rule_id}")
        await db.commit()
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        log.error("update_rule_error", rule_id=rule_id, error=str(exc))
        raise HTTPException(status_code=500, detail="更新规则失败") from exc


# ─── 8. 删除规则 ────────────────────────────────────────────────────


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """删除动态定价规则（软删除）"""
    try:
        deleted = await _svc.delete_rule(db, x_tenant_id, rule_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"规则不存在: {rule_id}")
        await db.commit()
        return {"ok": True, "data": {"rule_id": rule_id, "deleted": True}}
    except SQLAlchemyError as exc:
        log.error("delete_rule_error", rule_id=rule_id, error=str(exc))
        raise HTTPException(status_code=500, detail="删除规则失败") from exc
