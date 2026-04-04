"""企业订餐/团餐 — 周菜单 & 企业账户 & 订餐下单 Mock 路由

面向消费者小程序 enterprise-meal / enterprise-orders 页面。
4 个端点全部返回 Mock 数据，后续接入真实数据库。
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(
    prefix="/api/v1/trade/enterprise",
    tags=["enterprise-meal"],
)


def _ok(data):
    return {"ok": True, "data": data, "error": None}


# ─── Mock 数据生成 ───


def _mock_weekly_menu(week_start: str):
    """根据 week_start (YYYY-MM-DD) 生成一周午餐/晚餐 Mock 菜品"""
    lunch_dishes = [
        {"id": "wm1", "name": "红烧牛肉套餐", "image": "", "price_fen": 5800, "enterprise_price_fen": 3800, "meal_type": "lunch"},
        {"id": "wm2", "name": "清蒸鲈鱼套餐", "image": "", "price_fen": 6800, "enterprise_price_fen": 4500, "meal_type": "lunch"},
        {"id": "wm3", "name": "宫保鸡丁套餐", "image": "", "price_fen": 3600, "enterprise_price_fen": 2400, "meal_type": "lunch"},
        {"id": "wm4", "name": "扬州炒饭套餐", "image": "", "price_fen": 2800, "enterprise_price_fen": 1800, "meal_type": "lunch"},
    ]
    dinner_dishes = [
        {"id": "wm5", "name": "酸菜鱼套餐", "image": "", "price_fen": 4800, "enterprise_price_fen": 3200, "meal_type": "dinner"},
        {"id": "wm6", "name": "回锅肉套餐", "image": "", "price_fen": 3800, "enterprise_price_fen": 2600, "meal_type": "dinner"},
        {"id": "wm7", "name": "番茄牛腩套餐", "image": "", "price_fen": 4200, "enterprise_price_fen": 2800, "meal_type": "dinner"},
    ]

    try:
        start = datetime.strptime(week_start, "%Y-%m-%d")
    except (ValueError, TypeError):
        start = datetime.now()
        # 回退到本周一
        start -= timedelta(days=start.weekday())

    menu = {}
    for i in range(7):
        day = start + timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        menu[date_str] = {
            "lunch": [dict(d, date=date_str) for d in lunch_dishes],
            "dinner": [dict(d, date=date_str) for d in dinner_dishes],
        }
    return menu


def _mock_account():
    return {
        "company_name": "屯象科技",
        "balance_fen": 380000,
        "month_spent_fen": 120000,
        "month_budget_fen": 500000,
        "member_name": "员工",
    }


def _mock_orders(month: str, page: int, size: int):
    items = [
        {
            "id": "eo1", "date": month + "-28", "meal_type": "lunch",
            "dishes": [{"name": "红烧牛肉套餐", "qty": 1}],
            "total_fen": 3800, "status": "delivered", "delivery_status": "已送达",
            "created_at": month + "-28T12:05:00",
        },
        {
            "id": "eo2", "date": month + "-27", "meal_type": "lunch",
            "dishes": [{"name": "宫保鸡丁套餐", "qty": 1}, {"name": "例汤", "qty": 1}],
            "total_fen": 3300, "status": "delivered", "delivery_status": "已送达",
            "created_at": month + "-27T11:50:00",
        },
        {
            "id": "eo3", "date": month + "-27", "meal_type": "dinner",
            "dishes": [{"name": "酸菜鱼套餐", "qty": 1}],
            "total_fen": 3200, "status": "delivered", "delivery_status": "已送达",
            "created_at": month + "-27T17:30:00",
        },
        {
            "id": "eo4", "date": month + "-26", "meal_type": "lunch",
            "dishes": [{"name": "扬州炒饭套餐", "qty": 2}],
            "total_fen": 3600, "status": "preparing", "delivery_status": "制作中",
            "created_at": month + "-26T12:10:00",
        },
        {
            "id": "eo5", "date": month + "-25", "meal_type": "lunch",
            "dishes": [{"name": "清蒸鲈鱼套餐", "qty": 1}],
            "total_fen": 4500, "status": "delivered", "delivery_status": "已送达",
            "created_at": month + "-25T12:00:00",
        },
    ]
    start_idx = (page - 1) * size
    page_items = items[start_idx:start_idx + size]
    return {
        "items": page_items,
        "total": len(items),
        "summary": {
            "order_count": len(items),
            "month_spent_fen": sum(i["total_fen"] for i in items),
            "month_budget_fen": 500000,
        },
    }


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
    items: list[EnterpriseMealOrderItem]
    total_fen: int = Field(..., ge=0)


# ─── 1. 获取企业周菜单 ───


@router.get("/weekly-menu")
async def get_weekly_menu(
    company_id: str = Query(..., description="企业ID"),
    week: Optional[str] = Query(None, description="周一日期 YYYY-MM-DD，默认本周"),
):
    """返回指定周的午餐/晚餐菜单（Mock）"""
    menu = _mock_weekly_menu(week or "")
    return _ok({"menu": menu})


# ─── 2. 获取企业账户 ───


@router.get("/account")
async def get_enterprise_account(
    member_id: str = Query("", description="会员/员工ID"),
):
    """返回企业账户信息：余额、本月消费、预算（Mock）"""
    account = _mock_account()
    return _ok(account)


# ─── 3. 创建企业订餐订单 ───


@router.post("/order")
async def create_enterprise_meal_order(req: CreateEnterpriseMealOrderReq):
    """提交企业订餐订单（Mock — 直接返回成功）"""
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
    company_id: str = Query(..., description="企业ID"),
    month: str = Query("", description="月份 YYYY-MM"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """返回企业订餐历史（Mock）— 按日分组"""
    if not month:
        now = datetime.now()
        month = now.strftime("%Y-%m")
    result = _mock_orders(month, page, size)
    return _ok(result)
