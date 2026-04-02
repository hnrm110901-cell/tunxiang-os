"""KDS 增效分析 API — 三榜单 / 累单视图 / 基准份数 / 新客率

所有接口需要 X-Tenant-ID header。
ROUTER REGISTRATION（在 main.py 中添加）：
  from .api.kds_analytics_routes import router as kds_analytics_router
  app.include_router(kds_analytics_router, prefix="/api/v1/kds-analytics")
"""
from datetime import date, datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.batch_group_service import BatchGroupService
from ..services.dish_ranking_service import DishRankingService

logger = structlog.get_logger()

router = APIRouter(tags=["kds-analytics"])


# ── 公共依赖 ─────────────────────────────────────────────────

def _tenant_id(request: Request) -> str:
    tid = (
        getattr(request.state, "tenant_id", None)
        or request.headers.get("X-Tenant-ID", "")
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ── 响应模型 ─────────────────────────────────────────────────

class DishRankItemOut(BaseModel):
    dish_id: str
    dish_name: str
    count: int
    rate: float
    rank: int


class DishRankingsOut(BaseModel):
    hot: List[DishRankItemOut]
    cold: List[DishRankItemOut]
    remake: List[DishRankItemOut]
    as_of: datetime


class BatchGroupOut(BaseModel):
    dish_id: str
    dish_name: str
    total_qty: int
    base_qty: int
    batch_count: int
    remainder: int
    table_list: List[str]
    task_ids: List[str]


class SetBaseQtyReq(BaseModel):
    quantity: int = Field(..., ge=1, description="基准批次份数，最小为1")


class SetBaseQtyRes(BaseModel):
    ok: bool
    dish_id: str
    dept_id: str
    quantity: int


class NewCustomerRateOut(BaseModel):
    store_id: str
    date: str
    total_orders: int
    new_customer_orders: int
    new_customer_rate: float
    as_of: datetime


# ── 端点实现 ─────────────────────────────────────────────────

@router.get(
    "/rankings/{store_id}",
    response_model=DishRankingsOut,
    summary="三榜单 — 今日畅销/滞销/退菜",
)
async def get_rankings(
    store_id: str,
    request: Request,
    query_date: Optional[str] = Query(None, description="查询日期 YYYY-MM-DD，默认今天"),
    db: AsyncSession = Depends(get_db),
) -> DishRankingsOut:
    """获取门店今日三榜单

    - hot: 今日出单量 TOP10
    - cold: 今日最低出单量10条（含零销量）
    - remake: 今日退菜量 TOP10（含退菜率）
    """
    tenant_id = _tenant_id(request)

    parsed_date: Optional[date] = None
    if query_date:
        try:
            parsed_date = date.fromisoformat(query_date)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid date format, expected YYYY-MM-DD: {query_date}",
            ) from exc

    try:
        rankings = await DishRankingService.get_rankings(
            store_id=store_id,
            tenant_id=tenant_id,
            db=db,
            query_date=parsed_date,
        )
    except RuntimeError as exc:
        logger.error("kds_analytics.get_rankings_error", store_id=store_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return DishRankingsOut(
        hot=[DishRankItemOut(**vars(item)) for item in rankings.hot],
        cold=[DishRankItemOut(**vars(item)) for item in rankings.cold],
        remake=[DishRankItemOut(**vars(item)) for item in rankings.remake],
        as_of=rankings.as_of,
    )


@router.get(
    "/batched-queue/{dept_id}",
    response_model=List[BatchGroupOut],
    summary="累单视图 — 指定档口按菜品合并",
)
async def get_batched_queue(
    dept_id: str,
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    db: AsyncSession = Depends(get_db),
) -> List[BatchGroupOut]:
    """获取档口当前累单视图

    切配（prep）/ 打荷（assemble）专用：
    - 按菜品合并同款 pending 任务
    - 返回批次数、余量、涉及桌台列表
    """
    tenant_id = _tenant_id(request)

    try:
        groups = await BatchGroupService.get_batched_queue(
            dept_id=dept_id,
            store_id=store_id,
            tenant_id=tenant_id,
            db=db,
        )
    except RuntimeError as exc:
        logger.error("kds_analytics.get_batched_queue_error", dept_id=dept_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return [
        BatchGroupOut(
            dish_id=g.dish_id,
            dish_name=g.dish_name,
            total_qty=g.total_qty,
            base_qty=g.base_qty,
            batch_count=g.batch_count,
            remainder=g.remainder,
            table_list=g.table_list,
            task_ids=g.task_ids,
        )
        for g in groups
    ]


@router.put(
    "/base-quantity/{dish_id}/{dept_id}",
    response_model=SetBaseQtyRes,
    summary="设置基准批次份数",
)
async def set_base_quantity(
    dish_id: str,
    dept_id: str,
    body: SetBaseQtyReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SetBaseQtyRes:
    """设置菜品在指定档口的基准批次份数

    例：烤鸭在切配档口设置 base_quantity=2，
    则 8 份烤鸭显示「4批×2只」。
    """
    tenant_id = _tenant_id(request)

    try:
        await BatchGroupService.set_base_quantity(
            dish_id=dish_id,
            dept_id=dept_id,
            quantity=body.quantity,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.error(
            "kds_analytics.set_base_quantity_error",
            dish_id=dish_id,
            dept_id=dept_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return SetBaseQtyRes(
        ok=True,
        dish_id=dish_id,
        dept_id=dept_id,
        quantity=body.quantity,
    )


@router.get(
    "/new-customer-rate/{store_id}",
    response_model=NewCustomerRateOut,
    summary="今日新客率统计",
)
async def get_new_customer_rate(
    store_id: str,
    request: Request,
    query_date: Optional[str] = Query(None, description="查询日期 YYYY-MM-DD，默认今天"),
    db: AsyncSession = Depends(get_db),
) -> NewCustomerRateOut:
    """获取门店今日外卖新客率

    统计口径：delivery_orders.is_new_customer = true 的订单数 / 总外卖订单数
    """
    tenant_id = _tenant_id(request)

    date_str = query_date or date.today().isoformat()
    try:
        date.fromisoformat(date_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format, expected YYYY-MM-DD: {date_str}",
        ) from exc

    try:
        result = await db.execute(
            text(
                """
                SELECT
                    COUNT(id)                                             AS total_orders,
                    COUNT(id) FILTER (WHERE is_new_customer = true)       AS new_orders
                FROM delivery_orders
                WHERE tenant_id = :tenant_id
                  AND store_id  = :store_id
                  AND is_deleted = false
                  AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :date_str
                """
            ),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "date_str": date_str,
            },
        )
        row = result.fetchone()
        total = row.total_orders if row else 0
        new_orders = row.new_orders if row else 0
        rate = round(new_orders / total, 4) if total > 0 else 0.0
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        logger.error(
            "kds_analytics.new_customer_rate_error",
            store_id=store_id,
            date=date_str,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return NewCustomerRateOut(
        store_id=store_id,
        date=date_str,
        total_orders=total,
        new_customer_orders=new_orders,
        new_customer_rate=rate,
        as_of=datetime.now(timezone.utc),
    )
