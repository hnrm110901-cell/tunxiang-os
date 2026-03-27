"""交易路由 — 订单/收银/预订/对账

Sprint 1-2+ 逐步填充真实逻辑。
"""
from fastapi import APIRouter

from ...shared.response import ok

router = APIRouter(prefix="/api/v1/trade", tags=["trade"])


@router.get("/orders")
async def list_orders(store_id: str | None = None, page: int = 1, size: int = 20):
    """订单列表 — Sprint 1 实现"""
    return ok({"items": [], "total": 0, "page": page, "size": size})


@router.get("/orders/{order_id}")
async def get_order(order_id: str):
    """订单详情"""
    return ok({"order_id": order_id, "status": "placeholder"})
