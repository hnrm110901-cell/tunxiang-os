"""集点卡 API — 6个端点

1. POST   /api/v1/stamp-cards/templates           创建集点卡模板
2. GET    /api/v1/stamp-cards/templates           模板列表
3. POST   /api/v1/stamp-cards/stamp               手动盖章
4. POST   /api/v1/stamp-cards/auto-stamp          自动盖章（订单完成事件调用）
5. GET    /api/v1/stamp-cards/my                  我的集点卡
6. POST   /api/v1/stamp-cards/{id}/redeem         集满兑换
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.stamp_card_service import (
    create_template,
    list_templates,
    auto_stamp,
    get_my_cards,
    redeem_card,
)

router = APIRouter(prefix="/api/v1/stamp-cards", tags=["stamp-cards"])


async def get_db() -> AsyncSession:  # type: ignore[override]
    raise NotImplementedError("DB session dependency not configured")


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str) -> dict:
    return {"ok": False, "error": {"message": msg}}


# ── 请求模型 ──────────────────────────────────────────────────

class CreateTemplateReq(BaseModel):
    name: str
    target_stamps: int = Field(ge=2, le=50, default=5)
    reward_type: str = "coupon"
    reward_config: dict = {}
    validity_days: int = Field(ge=1, default=90)
    min_order_fen: int = Field(ge=0, default=0)
    applicable_stores: list[str] = []


class AutoStampReq(BaseModel):
    customer_id: str
    order_id: str
    order_amount_fen: int = Field(ge=0)
    store_id: str


class RedeemReq(BaseModel):
    customer_id: str


# ── 1. 创建集点卡模板 ────────────────────────────────────────

@router.post("/templates")
async def api_create_template(
    body: CreateTemplateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await create_template(
            name=body.name,
            target_stamps=body.target_stamps,
            reward_type=body.reward_type,
            reward_config=body.reward_config,
            validity_days=body.validity_days,
            min_order_fen=body.min_order_fen,
            applicable_stores=body.applicable_stores,
            tenant_id=x_tenant_id,
            db=db,
        )
        await db.commit()
        return ok_response(result)
    except ValueError as exc:
        return error_response(str(exc))


# ── 2. 模板列表 ──────────────────────────────────────────────

@router.get("/templates")
async def api_list_templates(
    status: Optional[str] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await list_templates(tenant_id=x_tenant_id, db=db, status=status)
    return ok_response(result)


# ── 3. 自动盖章（订单完成后调用） ────────────────────────────

@router.post("/auto-stamp")
async def api_auto_stamp(
    body: AutoStampReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await auto_stamp(
        customer_id=body.customer_id,
        order_id=body.order_id,
        order_amount_fen=body.order_amount_fen,
        store_id=body.store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    await db.commit()
    return ok_response(result)


# ── 4. 我的集点卡 ────────────────────────────────────────────

@router.get("/my")
async def api_my_cards(
    customer_id: str = Query(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await get_my_cards(
        customer_id=customer_id, tenant_id=x_tenant_id, db=db,
    )
    return ok_response(result)


# ── 5. 手动兑换 ──────────────────────────────────────────────

@router.post("/{instance_id}/redeem")
async def api_redeem(
    instance_id: str,
    body: RedeemReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await redeem_card(
            instance_id=instance_id,
            customer_id=body.customer_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        await db.commit()
        return ok_response(result)
    except ValueError as exc:
        return error_response(str(exc))
