"""会员卡 API 端点

10 个端点：卡类型CRUD、等级设置、匿名卡、发卡、升降级、会员日、权益、批量操作
"""
from typing import Optional

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

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
async def create_card_type(
    body: CreateCardTypeRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """创建会员卡类型（含储值/积分使用规则）"""
    # TODO: 注入真实 DB session 后调用 card_engine.create_card_type
    return {
        "ok": True,
        "data": {
            "card_type_id": "placeholder",
            "name": body.name,
            "rules": body.rules,
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    }


# ── 2. 获取卡类型列表 ─────────────────────────────────────────

@router.get("/types")
async def list_card_types(
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
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
async def set_card_levels(
    card_type_id: str,
    body: SetCardLevelsRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """设置卡等级（权益/升级规则/降级规则）"""
    return {
        "ok": True,
        "data": {
            "card_type_id": card_type_id,
            "levels_count": len(body.levels),
            "levels": body.levels,
        },
    }


# ── 4. 批量创建匿名实体卡 ─────────────────────────────────────

@router.post("/types/{card_type_id}/anonymous-cards")
async def create_anonymous_cards(
    card_type_id: str,
    body: CreateAnonymousCardRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """批量创建匿名实体卡"""
    return {
        "ok": True,
        "data": {
            "batch_no": body.batch_no,
            "count": body.count,
            "card_ids": [],
        },
    }


# ── 5. 发卡 ───────────────────────────────────────────────────

@router.post("/issue")
async def issue_card(
    body: IssueCardRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """给客户发放会员卡"""
    return {
        "ok": True,
        "data": {
            "card_id": "placeholder",
            "customer_id": body.customer_id,
            "card_type_id": body.card_type_id,
            "status": "active",
            "issued_at": "2026-01-01T00:00:00+00:00",
        },
    }


# ── 6. 等级升级 ───────────────────────────────────────────────

@router.post("/cards/{card_id}/upgrade")
async def upgrade_level(
    card_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """等级升级（根据规则自动判定）"""
    return {
        "ok": True,
        "data": {
            "card_id": card_id,
            "old_rank": 0,
            "new_rank": 0,
            "upgraded": False,
        },
    }


# ── 7. 等级降级 ───────────────────────────────────────────────

@router.post("/cards/{card_id}/downgrade")
async def downgrade_level(
    card_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """等级降级"""
    return {
        "ok": True,
        "data": {
            "card_id": card_id,
            "old_rank": 0,
            "new_rank": 0,
            "downgraded": False,
        },
    }


# ── 8. 设置会员日 ─────────────────────────────────────────────

@router.put("/types/{card_type_id}/member-day")
async def set_member_day(
    card_type_id: str,
    body: SetMemberDayRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """设置会员日（周几/每月几号）"""
    return {
        "ok": True,
        "data": {
            "card_type_id": card_type_id,
            "member_day_config": body.config,
        },
    }


# ── 9. 获取卡权益 ─────────────────────────────────────────────

@router.get("/cards/{card_id}/benefits")
async def get_card_benefits(
    card_id: str,
    store_id: str = Query(..., description="门店 ID"),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """获取当前卡的所有权益（含门店差异化）"""
    return {
        "ok": True,
        "data": {
            "card_id": card_id,
            "level_name": "default",
            "level_rank": 0,
            "benefits": [],
        },
    }


# ── 10. 批量操作 ──────────────────────────────────────────────

@router.post("/batch-operations")
async def batch_card_operations(
    body: BatchOperationsRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """批量操作（充值/扣减/转移）"""
    return {
        "ok": True,
        "data": {
            "total_ops": len(body.operations),
            "success_count": 0,
            "failed_count": 0,
            "results": [],
        },
    }
