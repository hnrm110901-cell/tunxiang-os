"""付费会员卡 API — 次卡（count_card）+ 周期卡（period_card）

端点列表：
  GET  /api/v1/member/premium-cards/templates     模板列表
  POST /api/v1/member/premium-cards/templates     创建模板
  POST /api/v1/member/premium-cards/purchase      购卡
  POST /api/v1/member/premium-cards/{id}/use      核销次卡一次
  POST /api/v1/member/premium-cards/{id}/benefit  使用周期权益
  POST /api/v1/member/premium-cards/{id}/renew    续费周期卡
  GET  /api/v1/member/premium-cards/{id}          卡详情
  GET  /api/v1/member/premium-cards/my            我的卡列表
  GET  /api/v1/member/premium-cards/{id}/history  使用历史

旧版兼容端点（保留）：
  GET  /api/v1/member/premium/plans               年卡方案列表
  POST /api/v1/member/premium/purchase            购买年卡
  GET  /api/v1/member/premium/cards/{id}/benefits 权益清单
  GET  /api/v1/member/premium/cards/{id}/usage    权益使用情况
  POST /api/v1/member/premium/cards/{id}/renew    续费
  POST /api/v1/member/premium/gift                赠送年卡
"""
import uuid
from typing import Optional

import services.premium_card as svc
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

router = APIRouter(prefix="/api/v1/member/premium-cards", tags=["premium-card"])

# 旧版路由单独注册
_legacy_router = APIRouter(prefix="/api/v1/member/premium", tags=["premium-card-legacy"])


# ── DB / 租户依赖 ─────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"X-Tenant-ID 格式错误: {x_tenant_id}",
        ) from e


# ── 请求模型 ──────────────────────────────────────────────────


class CreateTemplateReq(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    card_type: str = Field(description="count_card | period_card")
    price_fen: int = Field(gt=0, description="售价（分）")
    benefits: list[dict] = Field(default_factory=list)
    total_uses: Optional[int] = Field(None, gt=0, description="次卡总次数")
    period_type: Optional[str] = Field(None, description="monthly | quarterly | yearly")
    valid_days: Optional[int] = Field(None, gt=0, description="次卡有效天数")
    sort_order: int = Field(0)


class PurchaseCardReq(BaseModel):
    customer_id: str
    template_id: str
    store_id: Optional[str] = None


class UseCountCardReq(BaseModel):
    order_id: Optional[str] = None
    store_id: Optional[str] = None
    operator_id: Optional[str] = None


class UseBenefitReq(BaseModel):
    benefit_type: str = Field(description="权益类型：discount | free_dish | priority_queue 等")
    order_id: Optional[str] = None
    store_id: Optional[str] = None
    operator_id: Optional[str] = None


# 旧版请求模型（保留）
class _LegacyPurchaseReq(BaseModel):
    customer_id: str
    plan_id: str
    payment_id: str


class _LegacyGiftReq(BaseModel):
    sender_id: str
    receiver_phone: str = Field(min_length=11, max_length=11)
    plan_id: str


# ── 统一响应包装 ──────────────────────────────────────────────


def _ok(data: dict) -> dict:
    return {"ok": True, "data": data}


def _err(msg: str, code: str = "BAD_REQUEST") -> dict:
    return {"ok": False, "error": {"code": code, "message": msg}}


# ── 404 / 400 业务错误判断 ─────────────────────────────────────

_NOT_FOUND_KEYWORDS = frozenset({"not_found", "inactive", "template_not_found"})


def _is_not_found(err_msg: str) -> bool:
    return any(kw in err_msg for kw in _NOT_FOUND_KEYWORDS)


# ── 1. 模板列表 ───────────────────────────────────────────────


@router.get("/templates")
async def list_templates(
    active_only: bool = Query(True, description="仅返回启用中的模板"),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """付费卡模板列表（次卡/周期卡）"""
    templates = await svc.list_templates(
        tenant_id=str(tenant_id),
        db=db,
        active_only=active_only,
    )
    return _ok({"templates": templates})


# ── 2. 创建模板 ───────────────────────────────────────────────


@router.post("/templates")
async def create_template(
    body: CreateTemplateReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """创建付费卡模板（管理端使用）"""
    try:
        result = await svc.create_template(
            name=body.name,
            card_type=body.card_type,
            price_fen=body.price_fen,
            benefits=body.benefits,
            tenant_id=str(tenant_id),
            db=db,
            total_uses=body.total_uses,
            period_type=body.period_type,
            valid_days=body.valid_days,
            sort_order=body.sort_order,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _ok(result)


# ── 3. 购卡 ───────────────────────────────────────────────────


@router.post("/purchase")
async def purchase_card(
    body: PurchaseCardReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """购买付费会员卡（次卡或周期卡）"""
    try:
        result = await svc.purchase_card(
            customer_id=body.customer_id,
            template_id=body.template_id,
            tenant_id=str(tenant_id),
            db=db,
            store_id=body.store_id,
        )
    except ValueError as e:
        status_code = 404 if _is_not_found(str(e)) else 400
        raise HTTPException(status_code=status_code, detail=str(e)) from e
    return _ok(result)


# ── 4. 我的卡列表（路由必须在 /{card_id} 之前注册）────────────


@router.get("/my")
async def list_my_cards(
    customer_id: str = Query(..., description="会员 ID"),
    active_only: bool = Query(True),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """我的付费卡列表（按 customer_id 查询）"""
    cards = await svc.list_customer_cards(
        customer_id=customer_id,
        tenant_id=str(tenant_id),
        db=db,
        active_only=active_only,
    )
    return _ok({"customer_id": customer_id, "cards": cards})


# ── 5. 卡详情 ─────────────────────────────────────────────────


@router.get("/{card_id}")
async def get_card_detail(
    card_id: str,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """单张付费卡详情（含当前权益使用情况）"""
    try:
        result = await svc.get_card_detail(
            card_id=card_id,
            tenant_id=str(tenant_id),
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _ok(result)


# ── 6. 核销次卡 ───────────────────────────────────────────────


@router.post("/{card_id}/use")
async def use_count_card(
    card_id: str,
    body: UseCountCardReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """核销次卡一次（扣减 remaining_uses）"""
    try:
        result = await svc.use_count_card(
            card_id=card_id,
            tenant_id=str(tenant_id),
            db=db,
            order_id=body.order_id,
            store_id=body.store_id,
            operator_id=body.operator_id,
        )
    except ValueError as e:
        status_code = 404 if _is_not_found(str(e)) else 400
        raise HTTPException(status_code=status_code, detail=str(e)) from e
    return _ok(result)


# ── 7. 使用周期权益 ───────────────────────────────────────────


@router.post("/{card_id}/benefit")
async def use_benefit(
    card_id: str,
    body: UseBenefitReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """使用周期卡权益（如免费菜、停车等）"""
    try:
        result = await svc.use_benefit(
            card_id=card_id,
            benefit_type=body.benefit_type,
            tenant_id=str(tenant_id),
            db=db,
            order_id=body.order_id,
            store_id=body.store_id,
            operator_id=body.operator_id,
        )
    except ValueError as e:
        status_code = 404 if _is_not_found(str(e)) else 400
        raise HTTPException(status_code=status_code, detail=str(e)) from e
    return _ok(result)


# ── 8. 续费周期卡 ─────────────────────────────────────────────


@router.post("/{card_id}/renew")
async def renew_period_card(
    card_id: str,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """续费周期卡（延长一个周期，重置已用权益）"""
    try:
        result = await svc.renew_period(
            card_id=card_id,
            tenant_id=str(tenant_id),
            db=db,
        )
    except ValueError as e:
        status_code = 404 if _is_not_found(str(e)) else 400
        raise HTTPException(status_code=status_code, detail=str(e)) from e
    return _ok(result)


# ── 9. 使用历史 ───────────────────────────────────────────────


@router.get("/{card_id}/history")
async def get_card_usage_history(
    card_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """付费卡使用历史（分页）"""
    result = await svc.get_card_usage_history(
        card_id=card_id,
        tenant_id=str(tenant_id),
        db=db,
        page=page,
        size=size,
    )
    return _ok(result)


# ════════════════════════════════════════════════════════════════
# 旧版兼容路由（/api/v1/member/premium/*）
# ════════════════════════════════════════════════════════════════


@_legacy_router.get("/plans")
async def list_annual_plans(
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """年卡方案列表 — 银卡698/金卡1298/钻石2998（元/年）"""
    plans = [{"plan_id": k, **v} for k, v in svc.ANNUAL_PLANS.items()]
    return _ok({"plans": plans})


@_legacy_router.post("/purchase")
async def purchase_annual_card(
    body: _LegacyPurchaseReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """购买超级年卡（旧接口）"""
    try:
        result = await svc.purchase_annual_card(
            customer_id=body.customer_id,
            plan_id=body.plan_id,
            payment_id=body.payment_id,
            tenant_id=str(tenant_id),
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _ok(result)


@_legacy_router.get("/cards/{card_id}/benefits")
async def get_card_benefits(
    card_id: str,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """权益清单（旧接口）"""
    try:
        result = await svc.get_card_detail(
            card_id=card_id,
            tenant_id=str(tenant_id),
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _ok({
        "card_id": card_id,
        "benefits": result.get("tpl_benefits", []),
        "status": result.get("status"),
        "expires_at": result.get("expires_at"),
        "period_end": result.get("period_end"),
    })


@_legacy_router.get("/cards/{card_id}/usage")
async def check_benefit_usage(
    card_id: str,
    benefit_type: str = Query(...),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """权益使用情况（旧接口）"""
    try:
        result = await svc.check_benefit(
            card_id=card_id,
            benefit_type=benefit_type,
            tenant_id=str(tenant_id),
            db=db,
        )
    except ValueError as e:
        status_code = 404 if _is_not_found(str(e)) else 400
        raise HTTPException(status_code=status_code, detail=str(e)) from e
    return _ok({
        "card_id": card_id,
        "benefit_type": benefit_type,
        "available": result.get("available"),
        "remaining_quota": result.get("remaining_quota"),
        "resets_at": result.get("resets_at"),
        "benefit_config": result.get("benefit_config"),
    })


@_legacy_router.post("/cards/{card_id}/renew")
async def renew_card_legacy(
    card_id: str,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """续费年卡（旧接口）"""
    try:
        result = await svc.renew_period(
            card_id=card_id,
            tenant_id=str(tenant_id),
            db=db,
        )
    except ValueError as e:
        status_code = 404 if _is_not_found(str(e)) else 400
        raise HTTPException(status_code=status_code, detail=str(e)) from e
    return _ok(result)


@_legacy_router.post("/gift")
async def gift_card(
    body: _LegacyGiftReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict:
    """赠送年卡（旧接口）"""
    try:
        result = await svc.gift_card(
            sender_id=body.sender_id,
            receiver_phone=body.receiver_phone,
            plan_id=body.plan_id,
            tenant_id=str(tenant_id),
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _ok(result)
