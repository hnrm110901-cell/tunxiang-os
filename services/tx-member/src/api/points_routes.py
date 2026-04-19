"""积分 API 端点

8 个端点：积分获取、消耗、获取规则、消耗规则、倍数设置、成长值、余额、明细、跨店结算
"""

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/member/points", tags=["member-points"])


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
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """积分获取（消费/充值/活动/签到）"""
    return {
        "ok": True,
        "data": {
            "card_id": body.card_id,
            "source": body.source,
            "earned": body.amount,
            "new_balance": 0,
        },
    }


# ── 2. 积分消耗 ───────────────────────────────────────────────


@router.post("/spend")
async def spend_points(
    body: SpendPointsRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """积分消耗（抵现/兑换）"""
    return {
        "ok": True,
        "data": {
            "card_id": body.card_id,
            "purpose": body.purpose,
            "spent": body.amount,
            "new_balance": 0,
        },
    }


# ── 3. 设置获取规则 ───────────────────────────────────────────


@router.put("/types/{card_type_id}/earn-rules")
async def set_earn_rules(
    card_type_id: str,
    body: SetEarnRulesRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """设置积分获取规则（每消费X元获Y积分）"""
    return {
        "ok": True,
        "data": {
            "card_type_id": card_type_id,
            "earn_rules": body.rules,
        },
    }


# ── 4. 设置消耗规则 ───────────────────────────────────────────


@router.put("/types/{card_type_id}/spend-rules")
async def set_spend_rules(
    card_type_id: str,
    body: SetSpendRulesRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """设置积分消耗规则（X积分抵1元）"""
    return {
        "ok": True,
        "data": {
            "card_type_id": card_type_id,
            "spend_rules": body.rules,
        },
    }


# ── 5. 积分倍数设置 ───────────────────────────────────────────


@router.put("/types/{card_type_id}/multiplier")
async def set_multiplier(
    card_type_id: str,
    body: SetMultiplierRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """积分倍数设置（会员日/活动期）"""
    return {
        "ok": True,
        "data": {
            "card_type_id": card_type_id,
            "multiplier": body.multiplier,
            "conditions": body.conditions,
        },
    }


# ── 6. 成长值管理 ─────────────────────────────────────────────


@router.post("/cards/{card_id}/growth-value")
async def manage_growth_value(
    card_id: str,
    body: ManageGrowthValueRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """成长值管理（只增不减）"""
    return {
        "ok": True,
        "data": {
            "card_id": card_id,
            "added": body.amount,
            "new_growth_value": 0,
        },
    }


# ── 7. 积分余额 + 明细 ───────────────────────────────────────


@router.get("/cards/{card_id}/balance")
async def get_points_balance(
    card_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """积分余额查询"""
    return {
        "ok": True,
        "data": {
            "card_id": card_id,
            "points": 0,
            "growth_value": 0,
        },
    }


@router.get("/cards/{card_id}/history")
async def get_points_history(
    card_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """积分明细查询"""
    return {
        "ok": True,
        "data": {
            "card_id": card_id,
            "items": [],
            "total": 0,
            "page": page,
            "size": size,
        },
    }


# ── 8. 跨店积分结算 ──────────────────────────────────────────


@router.get("/settlement/{month}")
async def cross_store_settlement(
    month: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """跨店积分结算（按月）"""
    return {
        "ok": True,
        "data": {
            "month": month,
            "store_settlements": [],
            "total_points_earned": 0,
            "total_points_spent": 0,
        },
    }
