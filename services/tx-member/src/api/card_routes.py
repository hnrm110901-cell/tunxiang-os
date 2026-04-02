"""会员卡 API 端点

10 个端点：卡类型CRUD、等级设置、匿名卡、发卡、升降级、会员日、权益、批量操作
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.card_engine import (
    batch_card_operations,
    create_anonymous_card,
    create_card_type,
    downgrade_level,
    get_card_benefits,
    issue_card,
    set_card_levels,
    set_member_day,
    upgrade_level,
)

router = APIRouter(prefix="/api/v1/member/card", tags=["member-card"])


# ── 请求模型 ──────────────────────────────────────────────────

class CreateCardTypeRequest(BaseModel):
    name: str
    rules: dict = Field(default_factory=dict)


class SetCardLevelsRequest(BaseModel):
    levels: list[dict]


class CreateAnonymousCardRequest(BaseModel):
    batch_no: str
    count: int = Field(ge=1, le=10000)


class IssueCardRequest(BaseModel):
    customer_id: str
    card_type_id: str


class SetMemberDayRequest(BaseModel):
    config: dict


class BatchOperationsRequest(BaseModel):
    operations: list[dict]


# ── 1. 创建卡类型 ─────────────────────────────────────────────

@router.post("/types")
async def create_card_type_route(
    body: CreateCardTypeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建会员卡类型（含储值/积分使用规则）"""
    try:
        data = await create_card_type(body.name, body.rules, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── 2. 获取卡类型列表 ─────────────────────────────────────────

@router.get("/types")
async def list_card_types(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取会员卡类型列表"""
    return {
        "ok": True,
        "data": {
            "items": [],
            "total": 0,
        },
    }


# ── 3. 设置卡等级 ─────────────────────────────────────────────

@router.put("/types/{card_type_id}/levels")
async def set_card_levels_route(
    card_type_id: str,
    body: SetCardLevelsRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """设置卡等级（权益/升级规则/降级规则）"""
    try:
        data = await set_card_levels(card_type_id, body.levels, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── 4. 批量创建匿名实体卡 ─────────────────────────────────────

@router.post("/types/{card_type_id}/anonymous-cards")
async def create_anonymous_cards(
    card_type_id: str,
    body: CreateAnonymousCardRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """批量创建匿名实体卡"""
    try:
        data = await create_anonymous_card(card_type_id, body.batch_no, body.count, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── 5. 发卡 ───────────────────────────────────────────────────

@router.post("/issue")
async def issue_card_route(
    body: IssueCardRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """给客户发放会员卡"""
    try:
        data = await issue_card(body.customer_id, body.card_type_id, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── 6. 等级升级 ───────────────────────────────────────────────

@router.post("/cards/{card_id}/upgrade")
async def upgrade_level_route(
    card_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """等级升级（根据规则自动判定）"""
    try:
        data = await upgrade_level(card_id, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── 7. 等级降级 ───────────────────────────────────────────────

@router.post("/cards/{card_id}/downgrade")
async def downgrade_level_route(
    card_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """等级降级"""
    try:
        data = await downgrade_level(card_id, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── 8. 设置会员日 ─────────────────────────────────────────────

@router.put("/types/{card_type_id}/member-day")
async def set_member_day_route(
    card_type_id: str,
    body: SetMemberDayRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """设置会员日（周几/每月几号）"""
    try:
        data = await set_member_day(card_type_id, body.config, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── 9. 获取卡权益 ─────────────────────────────────────────────

@router.get("/cards/{card_id}/benefits")
async def get_card_benefits_route(
    card_id: str,
    store_id: str = Query(..., description="门店 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取当前卡的所有权益（含门店差异化）"""
    try:
        data = await get_card_benefits(card_id, store_id, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── 10. 批量操作 ──────────────────────────────────────────────

@router.post("/batch-operations")
async def batch_card_operations_route(
    body: BatchOperationsRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """批量操作（充值/扣减/转移）"""
    try:
        data = await batch_card_operations(body.operations, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
