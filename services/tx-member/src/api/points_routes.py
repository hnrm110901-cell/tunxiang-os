"""积分 API 端点

8 个端点：积分获取、消耗、获取规则、消耗规则、倍数设置、成长值、余额、明细、跨店结算
"""
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant
from ..services.points_engine import (
    earn_points as engine_earn_points,
    spend_points as engine_spend_points,
    set_earn_rules as engine_set_earn_rules,
    set_spend_rules as engine_set_spend_rules,
    set_multiplier as engine_set_multiplier,
    manage_growth_value as engine_manage_growth_value,
    get_points_balance as engine_get_points_balance,
    get_points_history as engine_get_points_history,
    cross_store_settlement as engine_cross_store_settlement,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/member/points", tags=["member-points"])


# ── 租户依赖 ─────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── 请求模型 ──────────────────────────────────────────────────

class EarnPointsRequest(BaseModel):
    card_id: str
    source: str  # consume|recharge|activity|sign_in
    amount: int = Field(gt=0, description="积分数（正整数）")


class SpendPointsRequest(BaseModel):
    card_id: str
    amount: int = Field(gt=0, description="积分数（正整数）")
    purpose: str  # cash_offset|exchange


class SetEarnRulesRequest(BaseModel):
    rules: dict


class SetSpendRulesRequest(BaseModel):
    rules: dict


class SetMultiplierRequest(BaseModel):
    multiplier: float = Field(gt=0)
    conditions: dict


class ManageGrowthValueRequest(BaseModel):
    action: str = "add"
    amount: int = Field(gt=0)


# ── 1. 积分获取 ───────────────────────────────────────────────

@router.post("/earn")
async def earn_points(
    body: EarnPointsRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """积分获取（消费/充值/活动/签到）"""
    try:
        result = await engine_earn_points(
            card_id=body.card_id,
            source=body.source,
            amount=body.amount,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 2. 积分消耗 ───────────────────────────────────────────────

@router.post("/spend")
async def spend_points(
    body: SpendPointsRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """积分消耗（抵现/兑换）"""
    try:
        result = await engine_spend_points(
            card_id=body.card_id,
            amount=body.amount,
            purpose=body.purpose,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        detail = str(e)
        if "not_found" in detail:
            raise HTTPException(status_code=404, detail=detail) from e
        if "insufficient" in detail:
            raise HTTPException(status_code=409, detail=detail) from e
        raise HTTPException(status_code=400, detail=detail) from e


# ── 3. 设置获取规则 ───────────────────────────────────────────

@router.put("/types/{card_type_id}/earn-rules")
async def set_earn_rules(
    card_type_id: str,
    body: SetEarnRulesRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """设置积分获取规则（每消费X元获Y积分）"""
    try:
        result = await engine_set_earn_rules(
            card_type_id=card_type_id,
            rules=body.rules,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 4. 设置消耗规则 ───────────────────────────────────────────

@router.put("/types/{card_type_id}/spend-rules")
async def set_spend_rules(
    card_type_id: str,
    body: SetSpendRulesRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """设置积分消耗规则（X积分抵1元）"""
    try:
        result = await engine_set_spend_rules(
            card_type_id=card_type_id,
            rules=body.rules,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 5. 积分倍数设置 ───────────────────────────────────────────

@router.put("/types/{card_type_id}/multiplier")
async def set_multiplier(
    card_type_id: str,
    body: SetMultiplierRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """积分倍数设置（会员日/活动期）"""
    try:
        result = await engine_set_multiplier(
            card_type_id=card_type_id,
            multiplier=body.multiplier,
            conditions=body.conditions,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 6. 成长值管理 ─────────────────────────────────────────────

@router.post("/cards/{card_id}/growth-value")
async def manage_growth_value(
    card_id: str,
    body: ManageGrowthValueRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """成长值管理（只增不减）"""
    try:
        result = await engine_manage_growth_value(
            card_id=card_id,
            action=body.action,
            amount=body.amount,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 7. 积分余额 + 明细 ───────────────────────────────────────

@router.get("/cards/{card_id}/balance")
async def get_points_balance(
    card_id: str,
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """积分余额查询"""
    try:
        result = await engine_get_points_balance(
            card_id=card_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        detail = str(e)
        if "not_found" in detail:
            raise HTTPException(status_code=404, detail=detail) from e
        raise HTTPException(status_code=400, detail=detail) from e


@router.get("/cards/{card_id}/history")
async def get_points_history(
    card_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """积分明细查询"""
    result = await engine_get_points_history(
        card_id=card_id,
        tenant_id=x_tenant_id,
        db=db,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


# ── 8. 跨店积分结算 ──────────────────────────────────────────

@router.get("/settlement/{month}")
async def cross_store_settlement(
    month: str,
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """跨店积分结算（按月）"""
    result = await engine_cross_store_settlement(
        tenant_id=x_tenant_id,
        month=month,
        db=db,
    )
    return {"ok": True, "data": result}
