"""智能储值 API — 推荐/接受/拒绝 + 规则CRUD + 绩效统计 + 排名 + 提成

所有接口需要 X-Tenant-ID header。
ROUTER REGISTRATION（在 main.py 中添加）：
  from .api.smart_recharge_routes import router as smart_recharge_router
  app.include_router(smart_recharge_router)
"""

from datetime import date
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.recharge_performance_service import RechargePerformanceService
from ..services.smart_recharge_service import SmartRechargeService

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/member/smart-recharge", tags=["smart-recharge"])


# ── 公共依赖 ─────────────────────────────────────────────────

def _tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ── 请求模型 ─────────────────────────────────────────────────

class RecommendRequest(BaseModel):
    store_id: str
    customer_id: Optional[str] = None
    order_id: str
    order_amount_fen: int = Field(..., gt=0)
    employee_id: Optional[str] = None


class AcceptRequest(BaseModel):
    selected_tier: dict
    recharge_amount_fen: int = Field(..., gt=0)
    bonus_amount_fen: int = 0


class CreateRuleRequest(BaseModel):
    store_id: Optional[str] = None
    brand_id: Optional[str] = None
    rule_name: str
    multiplier_tiers: list
    bonus_type: str = Field("percentage", pattern="^(percentage|fixed|coupon)$")
    bonus_value: float = 0
    min_recharge_fen: int = 0
    max_recharge_fen: int = 999900
    coupon_template_id: Optional[str] = None
    effective_from: Optional[date] = None
    effective_until: Optional[date] = None
    priority: int = 0


class UpdateRuleRequest(BaseModel):
    rule_name: Optional[str] = None
    is_active: Optional[bool] = None
    multiplier_tiers: Optional[list] = None
    bonus_type: Optional[str] = None
    bonus_value: Optional[float] = None
    effective_until: Optional[date] = None
    priority: Optional[int] = None


class CreateCommissionRuleRequest(BaseModel):
    store_id: Optional[str] = None
    rule_name: str
    commission_type: str = Field(..., pattern="^(flat_per_card|percentage|tiered)$")
    commission_value: float = 0
    tiers: Optional[list] = None
    effective_from: Optional[date] = None
    effective_until: Optional[date] = None


# ── 推荐端点 ─────────────────────────────────────────────────

@router.post("/recommend")
async def generate_recommendation(
    body: RecommendRequest,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """根据订单金额生成智能储值推荐"""
    result = await SmartRechargeService.generate_recommendation(
        db,
        tenant_id,
        store_id=body.store_id,
        customer_id=body.customer_id,
        order_id=body.order_id,
        order_amount_fen=body.order_amount_fen,
        employee_id=body.employee_id,
    )
    return {"ok": True, "data": result}


@router.post("/recommendations/{recommendation_id}/accept")
async def accept_recommendation(
    recommendation_id: str,
    body: AcceptRequest,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """客户接受储值推荐"""
    result = await SmartRechargeService.accept_recommendation(
        db,
        tenant_id,
        recommendation_id=recommendation_id,
        selected_tier=body.selected_tier,
        recharge_amount_fen=body.recharge_amount_fen,
        bonus_amount_fen=body.bonus_amount_fen,
    )
    return {"ok": True, "data": result}


@router.post("/recommendations/{recommendation_id}/decline")
async def decline_recommendation(
    recommendation_id: str,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """客户拒绝储值推荐"""
    result = await SmartRechargeService.decline_recommendation(
        db,
        tenant_id,
        recommendation_id=recommendation_id,
    )
    return {"ok": True, "data": result}


@router.get("/recommendations")
async def list_recommendations(
    store_id: str = Query(...),
    status: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """列出储值推荐记录"""
    result = await SmartRechargeService.list_recommendations(
        db,
        tenant_id,
        store_id=store_id,
        status=status,
        customer_id=customer_id,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


# ── 规则 CRUD ────────────────────────────────────────────────

@router.post("/rules")
async def create_rule(
    body: CreateRuleRequest,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """创建智能储值规则"""
    result = await SmartRechargeService.create_rule(
        db,
        tenant_id,
        store_id=body.store_id,
        brand_id=body.brand_id,
        rule_name=body.rule_name,
        multiplier_tiers=body.multiplier_tiers,
        bonus_type=body.bonus_type,
        bonus_value=body.bonus_value,
        min_recharge_fen=body.min_recharge_fen,
        max_recharge_fen=body.max_recharge_fen,
        coupon_template_id=body.coupon_template_id,
        effective_from=body.effective_from,
        effective_until=body.effective_until,
        priority=body.priority,
    )
    return {"ok": True, "data": result}


@router.get("/rules")
async def list_rules(
    store_id: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """列出智能储值规则"""
    result = await SmartRechargeService.list_rules(
        db,
        tenant_id,
        store_id=store_id,
        is_active=is_active,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.get("/rules/{rule_id}")
async def get_rule(
    rule_id: str,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """获取单个储值规则"""
    result = await SmartRechargeService.get_rule(db, tenant_id, rule_id)
    if not result:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True, "data": result}


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: str,
    body: UpdateRuleRequest,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """更新储值规则"""
    result = await SmartRechargeService.update_rule(
        db,
        tenant_id,
        rule_id=rule_id,
        rule_name=body.rule_name,
        is_active=body.is_active,
        multiplier_tiers=body.multiplier_tiers,
        bonus_type=body.bonus_type,
        bonus_value=body.bonus_value,
        effective_until=body.effective_until,
        priority=body.priority,
    )
    return {"ok": True, "data": result}


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: str,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """删除储值规则"""
    result = await SmartRechargeService.delete_rule(db, tenant_id, rule_id)
    return {"ok": True, "data": result}


# ── 统计 + 绩效 ─────────────────────────────────────────────

@router.get("/stats")
async def get_stats(
    store_id: str = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """储值推荐转化统计"""
    result = await SmartRechargeService.get_stats(
        db,
        tenant_id,
        store_id=store_id,
        start_date=start_date,
        end_date=end_date,
    )
    return {"ok": True, "data": result}


@router.get("/ranking")
async def get_ranking(
    store_id: str = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    sort_by: str = Query("total_recharge_amount_fen"),
    limit: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """员工储值绩效排名"""
    result = await RechargePerformanceService.get_ranking(
        db,
        tenant_id,
        store_id=store_id,
        start_date=start_date,
        end_date=end_date,
        sort_by=sort_by,
        limit=limit,
    )
    return {"ok": True, "data": result}


@router.get("/performance/daily")
async def get_daily_performance(
    store_id: str = Query(...),
    period_date: date = Query(...),
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """门店日储值绩效汇总"""
    result = await RechargePerformanceService.get_daily_summary(
        db,
        tenant_id,
        store_id=store_id,
        period_date=period_date,
    )
    return {"ok": True, "data": result}


@router.get("/commission")
async def calculate_commission(
    store_id: str = Query(...),
    employee_id: str = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """计算员工储值提成"""
    result = await RechargePerformanceService.calculate_commission(
        db,
        tenant_id,
        store_id=store_id,
        employee_id=employee_id,
        start_date=start_date,
        end_date=end_date,
    )
    return {"ok": True, "data": result}


# ── 提成规则 ─────────────────────────────────────────────────

@router.post("/commission-rules")
async def create_commission_rule(
    body: CreateCommissionRuleRequest,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """创建储值提成规则"""
    result = await RechargePerformanceService.create_commission_rule(
        db,
        tenant_id,
        store_id=body.store_id,
        rule_name=body.rule_name,
        commission_type=body.commission_type,
        commission_value=body.commission_value,
        tiers=body.tiers,
        effective_from=body.effective_from,
        effective_until=body.effective_until,
    )
    return {"ok": True, "data": result}


@router.get("/commission-rules")
async def list_commission_rules(
    store_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """列出储值提成规则"""
    result = await RechargePerformanceService.list_commission_rules(
        db,
        tenant_id,
        store_id=store_id,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}
