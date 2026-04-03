"""礼品卡 API — 6端点"""
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from services.gift_card import (
    activate_cards,
    batch_create_cards,
    create_gift_card_type,
    get_card_balance,
    online_purchase_config,
    sell_card,
    use_card,
)

router = APIRouter(prefix="/api/v1/member/gift-cards", tags=["gift-card"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class CreateTypeReq(BaseModel):
    name: str = Field(..., min_length=1, description="礼品卡名称")
    face_value_fen: int = Field(..., gt=0, description="面值（分）")


class BatchCreateReq(BaseModel):
    type_id: str
    count: int = Field(..., gt=0, le=10000)


class ActivateReq(BaseModel):
    card_ids: list[str] = Field(..., min_length=1)


class SellCardReq(BaseModel):
    card_id: str
    buyer_info: dict = Field(
        ..., description="购买者信息: {name, phone, payment_method}"
    )


class UseCardReq(BaseModel):
    card_no: str
    password: str = Field(..., min_length=6, max_length=6)
    order_id: str
    amount_fen: int = Field(..., gt=0)


class OnlineConfigReq(BaseModel):
    type_id: str
    theme: dict = Field(
        default_factory=dict,
        description="主题配置: {title, cover_image, description, greeting_template}",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/types")
async def api_create_type(
    req: CreateTypeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建礼品卡类型"""
    result = await create_gift_card_type(
        name=req.name,
        face_value_fen=req.face_value_fen,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/batch-create")
async def api_batch_create(
    req: BatchCreateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """批量制卡"""
    result = await batch_create_cards(
        type_id=req.type_id,
        count=req.count,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/activate")
async def api_activate(
    req: ActivateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """批量激活"""
    result = await activate_cards(
        card_ids=req.card_ids,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/sell")
async def api_sell(
    req: SellCardReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """售卖礼品卡"""
    result = await sell_card(
        card_id=req.card_id,
        buyer_info=req.buyer_info,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/use")
async def api_use(
    req: UseCardReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """使用礼品卡"""
    result = await use_card(
        card_no=req.card_no,
        password=req.password,
        order_id=req.order_id,
        amount_fen=req.amount_fen,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.get("/balance/{card_no}")
async def api_balance(
    card_no: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """查询余额"""
    result = await get_card_balance(
        card_no=card_no,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/online-config")
async def api_online_config(
    req: OnlineConfigReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """线上售卖配置"""
    result = await online_purchase_config(
        type_id=req.type_id,
        theme=req.theme,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}
