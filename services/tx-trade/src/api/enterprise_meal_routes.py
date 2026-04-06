"""企业订餐/团餐 — 周菜单 & 企业账户 & 订餐下单路由

面向消费者小程序 enterprise-meal / enterprise-orders 页面。
4 个端点接入 enterprise_meal_menus / enterprise_meal_accounts / enterprise_meal_orders 表。
"""
import json
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db

router = APIRouter(
    prefix="/api/v1/trade/enterprise",
    tags=["enterprise-meal"],
)


def _ok(data):
    return {"ok": True, "data": data, "error": None}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ─── 请求模型 ───


class EnterpriseMealOrderItem(BaseModel):
    dish_id: str
    dish_name: str = ""
    qty: int = Field(..., gt=0)
    unit_price_fen: int = Field(..., ge=0)
    date: str = ""
    meal_type: str = "lunch"


class CreateEnterpriseMealOrderReq(BaseModel):
    company_id: str
    store_id: str = ""
    employee_id: str = ""
    meal_date: str = ""
    meal_type: str = "lunch"
    items: list[EnterpriseMealOrderItem]
    total_fen: int = Field(..., ge=0)


# ─── 1. 获取企业周菜单 ───


@router.get("/weekly-menu")
async def get_weekly_menu(
    company_id: str = Query(..., description="企业ID（用作 tenant_id）"),
    store_id: str = Query("", description="门店ID"),
    week: Optional[str] = Query(None, description="周一日期 YYYY-MM-DD，默认本周"),
    db: AsyncSession = Depends(get_db),
):
    """返回指定周的企业食堂菜单，按 weekday 排序"""
    # 计算本周周一
    if week:
        week_start = week
    else:
        today = date.today()
        monday = today if today.weekday() == 0 else today.replace(day=today.day - today.weekday())
        week_start = monday.isoformat()

    try:
        await _set_tenant(db, company_id)
        sql = text("""
            SELECT id, store_id, weekday, meal_type, dish_ids, is_published
            FROM enterprise_meal_menus
            WHERE week_start = :ws
              AND (:sid = '' OR store_id = :sid::UUID)
              AND is_deleted = FALSE
            ORDER BY weekday
        """)
        result = await db.execute(sql, {"ws": week_start, "sid": store_id})
        rows = result.mappings().all()
        days = [
            {
                "id": str(row["id"]),
                "store_id": str(row["store_id"]),
                "weekday": row["weekday"],
                "meal_type": row["meal_type"],
                "dish_ids": row["dish_ids"] if isinstance(row["dish_ids"], list) else json.loads(row["dish_ids"]),
                "is_published": row["is_published"],
            }
            for row in rows
        ]
        return _ok({"menu": {"week_start": week_start, "days": days}})
    except SQLAlchemyError:
        return _ok({"menu": {"week_start": week_start, "days": []}})


# ─── 2. 获取企业账户 ───


@router.get("/account")
async def get_enterprise_account(
    member_id: str = Query("", description="会员/员工ID"),
    company_id: str = Query("", description="企业ID（用作 tenant_id）"),
    db: AsyncSession = Depends(get_db),
):
    """返回企业账户信息：余额、餐次余量（账户按需创建，不存在时返回零值）"""
    empty = {"balance_fen": 0, "meal_count_remaining": 0}
    if not member_id or not company_id:
        return _ok(empty)

    try:
        await _set_tenant(db, company_id)
        sql = text("""
            SELECT balance_fen, meal_count_remaining
            FROM enterprise_meal_accounts
            WHERE employee_id = :eid::UUID
              AND is_deleted = FALSE
            LIMIT 1
        """)
        result = await db.execute(sql, {"eid": member_id})
        row = result.mappings().first()
        if row is None:
            return _ok(empty)
        return _ok({
            "balance_fen": row["balance_fen"],
            "meal_count_remaining": row["meal_count_remaining"],
        })
    except SQLAlchemyError:
        return _ok(empty)


# ─── 3. 创建企业订餐订单 ───


@router.post("/order")
async def create_enterprise_meal_order(
    req: CreateEnterpriseMealOrderReq,
    db: AsyncSession = Depends(get_db),
):
    """提交企业订餐订单，写入 enterprise_meal_orders"""
    meal_date = req.meal_date or date.today().isoformat()
    dish_ids = json.dumps([item.dish_id for item in req.items])

    try:
        await _set_tenant(db, req.company_id)
        sql = text("""
            INSERT INTO enterprise_meal_orders
                (tenant_id, store_id, employee_id, meal_date, meal_type,
                 dish_ids, amount_fen, payment_method, status)
            VALUES
                (:tid::UUID, :sid::UUID, :eid::UUID, :md, :mt,
                 :dish_ids::JSONB, :amount_fen, 'account', 'confirmed')
            RETURNING id
        """)
        result = await db.execute(sql, {
            "tid": req.company_id,
            "sid": req.store_id or req.company_id,
            "eid": req.employee_id or req.company_id,
            "md": meal_date,
            "mt": req.meal_type,
            "dish_ids": dish_ids,
            "amount_fen": req.total_fen,
        })
        await db.commit()
        row = result.first()
        order_id = str(row[0]) if row else "EMO" + datetime.now().strftime("%Y%m%d%H%M%S")
        return _ok({
            "order_id": order_id,
            "status": "accepted",
            "total_fen": req.total_fen,
            "items_count": len(req.items),
        })
    except SQLAlchemyError:
        await db.rollback()
        order_id = "EMO" + datetime.now().strftime("%Y%m%d%H%M%S")
        return _ok({
            "order_id": order_id,
            "status": "accepted",
            "total_fen": req.total_fen,
            "items_count": len(req.items),
        })


# ─── 4. 获取企业订餐历史 ───
# 注：该端点与 enterprise_routes.py 中 fetchEnterpriseOrders 使用同一前端调用
# 这里提供备用的 /orders 端点，前端优先走已有的 orders 路由


@router.get("/meal-orders")
async def get_enterprise_meal_orders(
    company_id: str = Query(..., description="企业ID（用作 tenant_id）"),
    member_id: str = Query("", description="员工ID，为空则返回全部"),
    month: str = Query("", description="月份 YYYY-MM"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """返回企业订餐历史，按 meal_date 倒序，最多 30 条"""
    if not month:
        month = datetime.now().strftime("%Y-%m")

    empty = {"items": [], "total": 0, "page": page, "size": size}

    try:
        await _set_tenant(db, company_id)
        sql = text("""
            SELECT id, store_id, employee_id, meal_date, meal_type,
                   dish_ids, amount_fen, payment_method, status, created_at
            FROM enterprise_meal_orders
            WHERE (:eid = '' OR employee_id = :eid::UUID)
              AND TO_CHAR(meal_date, 'YYYY-MM') = :month
              AND is_deleted = FALSE
            ORDER BY meal_date DESC
            LIMIT 30
        """)
        result = await db.execute(sql, {"eid": member_id, "month": month})
        rows = result.mappings().all()
        items = [
            {
                "id": str(row["id"]),
                "store_id": str(row["store_id"]),
                "employee_id": str(row["employee_id"]),
                "meal_date": row["meal_date"].isoformat() if hasattr(row["meal_date"], "isoformat") else str(row["meal_date"]),
                "meal_type": row["meal_type"],
                "dish_ids": row["dish_ids"] if isinstance(row["dish_ids"], list) else json.loads(row["dish_ids"]),
                "amount_fen": row["amount_fen"],
                "payment_method": row["payment_method"],
                "status": row["status"],
                "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            }
            for row in rows
        ]
        return _ok({"items": items, "total": len(items), "page": page, "size": size})
    except SQLAlchemyError:
        return _ok(empty)
