"""营销方案 API — 计算、创建、列出方案"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from services.marketing_engine import (
    SCHEME_TYPES,
    apply_schemes_in_order,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/member/marketing-schemes", tags=["marketing"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class OrderItem(BaseModel):
    dish_id: str
    name: str = ""
    price_fen: int = Field(..., ge=0, description="单价（分）")
    quantity: int = Field(1, ge=1)


class SchemeInput(BaseModel):
    scheme_type: str = Field(..., description=f"方案类型: {SCHEME_TYPES}")
    priority: int = Field(10, description="优先级，数字越小越高")
    rules: dict = Field(default_factory=dict)
    exclusion_rules: list[list[str]] = Field(
        default_factory=list,
        description='互斥规则，如 [["special_price","order_discount"]]',
    )


class CalculateReq(BaseModel):
    items: list[OrderItem]
    order_total_fen: int = Field(0, ge=0, description="订单总额（分），0 则自动求和")
    schemes: list[SchemeInput]
    member_level: Optional[str] = None


class CreateSchemeReq(BaseModel):
    scheme_type: str
    name: str
    priority: int = 10
    rules: dict = Field(default_factory=dict)
    exclusion_rules: list[list[str]] = Field(default_factory=list)
    store_id: str = ""
    is_active: bool = True
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置当前会话的 tenant_id，用于 RLS 隔离"""
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, TRUE)"), {"tid": tenant_id})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_schemes(
    x_tenant_id: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """列出方案"""
    try:
        await _set_tenant(db, x_tenant_id)
        rows = await db.execute(
            text(
                "SELECT id, name, scheme_type, rules, is_active, valid_from, valid_until, priority "
                "FROM marketing_schemes "
                "WHERE is_deleted = FALSE AND is_active = TRUE "
                "ORDER BY priority DESC "
                "LIMIT 50"
            )
        )
        items = [dict(r._mapping) for r in rows]
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except SQLAlchemyError as exc:
        return {"ok": False, "error": {"code": "DB_ERROR", "message": str(exc)}}


@router.post("")
async def create_scheme(
    req: CreateSchemeReq,
    x_tenant_id: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """创建方案"""
    if req.scheme_type not in SCHEME_TYPES:
        return {
            "ok": False,
            "error": {"code": "INVALID_SCHEME_TYPE", "message": f"不支持的方案类型: {req.scheme_type}"},
        }

    try:
        await _set_tenant(db, x_tenant_id)
        result = await db.execute(
            text(
                "INSERT INTO marketing_schemes "
                "(tenant_id, name, scheme_type, rules, is_active, valid_from, valid_until, priority) "
                "VALUES (:tenant_id, :name, :scheme_type, :rules, :is_active, :valid_from, :valid_until, :priority) "
                "RETURNING id"
            ),
            {
                "tenant_id": x_tenant_id,
                "name": req.name,
                "scheme_type": req.scheme_type,
                "rules": json.dumps(req.rules),
                "is_active": req.is_active,
                "valid_from": req.valid_from,
                "valid_until": req.valid_until,
                "priority": req.priority,
            },
        )
        new_id = result.scalar_one()
        await db.commit()
        return {"ok": True, "data": {"id": new_id, **req.model_dump()}}
    except SQLAlchemyError as exc:
        return {"ok": False, "error": {"code": "DB_ERROR", "message": str(exc)}}


@router.post("/calculate")
async def calculate_order_discount(
    req: CalculateReq,
    x_tenant_id: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """计算订单应用方案后的优惠"""
    try:
        await _set_tenant(db, x_tenant_id)
        rows = await db.execute(
            text(
                "SELECT scheme_type, rules, priority, exclusion_rules "
                "FROM marketing_schemes "
                "WHERE is_active = TRUE AND is_deleted = FALSE "
                "ORDER BY priority DESC"
            )
        )
        db_schemes = []
        for r in rows:
            m = dict(r._mapping)
            # rules 可能已是 dict（jsonb）或 str
            if isinstance(m.get("rules"), str):
                m["rules"] = json.loads(m["rules"])
            if isinstance(m.get("exclusion_rules"), str):
                m["exclusion_rules"] = json.loads(m["exclusion_rules"])
            db_schemes.append(m)
    except SQLAlchemyError as exc:
        return {"ok": False, "error": {"code": "DB_ERROR", "message": str(exc)}}

    # 若请求中显式传入了 schemes，则合并（DB 优先）
    items_raw = [it.model_dump() for it in req.items]

    order_total = req.order_total_fen
    if order_total == 0:
        order_total = sum(it.price_fen * it.quantity for it in req.items)

    # DB 方案与请求方案合并，DB 方案优先（排在前面）
    req_schemes_raw = [s.model_dump() for s in req.schemes]
    schemes_raw = db_schemes + req_schemes_raw

    result = apply_schemes_in_order(
        items=items_raw,
        order_total_fen=order_total,
        schemes=schemes_raw,
        member_level=req.member_level,
    )
    return {"ok": True, "data": result}
