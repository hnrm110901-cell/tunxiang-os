"""经营驾驶舱总部概览 API

实现 web-admin DashboardPage.tsx 所需的三个核心端点：

  GET /api/v1/analytics/overview        — 总体 KPI（营收/单量/翻台率/客单价/门店在线数）
  GET /api/v1/analytics/store-ranking   — 门店营收排行榜
  GET /api/v1/analytics/category-sales  — 品类销售占比

RLS 安全：使用 X-Tenant-ID header，通过 get_db_with_tenant 设置 app.tenant_id。
容错：DB 查询失败或表不存在时返回 mock 数据，确保驾驶舱始终可展示。
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import async_session_factory
from shared.ontology.src.entities import Dish, DishCategory, Order, OrderItem, Store
from shared.ontology.src.enums import OrderStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics-hq"])

_EXCLUDED_STATUSES = (OrderStatus.cancelled.value, "voided")

# ─── 内部辅助 ───────────────────────────────────────────────────────────────


def _require_tenant(tenant_id: Optional[str]) -> str:
    if not tenant_id or not tenant_id.strip():
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be a valid UUID")
    return tenant_id


def _parse_date(date_str: Optional[str]) -> date:
    if not date_str:
        return date.today()
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return date.today()


def _day_window(target_date: date) -> tuple[datetime, datetime]:
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    return day_start, day_end


def _safe_change(today_val: int | float, yesterday_val: int | float) -> float:
    """计算环比变化率，避免除以零。"""
    if yesterday_val == 0:
        return 0.0
    return round((today_val - yesterday_val) / yesterday_val, 4)


async def _set_tenant(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── DB 查询辅助（数据库不可用时返回零值保底） ────────────────────────────


async def _query_overview(
    target_date: date,
    tenant_id: str,
    db: AsyncSession,
    brand_id: Optional[str] = None,
) -> dict:
    """查询总体 KPI，DB 报 SQLAlchemyError 时返回零值结构。"""
    tenant_uuid = uuid.UUID(tenant_id)
    day_start, day_end = _day_window(target_date)
    yesterday_start, yesterday_end = _day_window(target_date - timedelta(days=1))

    _zero = {
        "date": target_date.isoformat(),
        "revenue_fen": 0,
        "revenue_change": 0.0,
        "order_count": 0,
        "order_change": 0.0,
        "table_turnover_rate": 0.0,
        "turnover_change": 0.0,
        "avg_order_value_fen": 0,
        "aov_change": 0.0,
        "online_stores": 0,
        "total_stores": 0,
    }

    try:
        await _set_tenant(db, tenant_id)

        # 今日营收与订单数
        if brand_id:
            today_stmt = (
                select(
                    func.coalesce(func.sum(Order.final_amount_fen), 0).label("revenue_fen"),
                    func.count(Order.id).label("order_count"),
                )
                .join(Store, Store.id == Order.store_id)
                .where(Order.tenant_id == tenant_uuid)
                .where(Store.brand_id == brand_id)
                .where(Order.status.not_in(list(_EXCLUDED_STATUSES)))
                .where(Order.order_time >= day_start)
                .where(Order.order_time < day_end)
            )
        else:
            today_stmt = (
                select(
                    func.coalesce(func.sum(Order.final_amount_fen), 0).label("revenue_fen"),
                    func.count(Order.id).label("order_count"),
                )
                .where(Order.tenant_id == tenant_uuid)
                .where(Order.status.not_in(list(_EXCLUDED_STATUSES)))
                .where(Order.order_time >= day_start)
                .where(Order.order_time < day_end)
            )

        today_row = (await db.execute(today_stmt)).one()
        revenue_fen: int = today_row[0]
        order_count: int = today_row[1]

        # 昨日数据
        if brand_id:
            yesterday_stmt = (
                select(
                    func.coalesce(func.sum(Order.final_amount_fen), 0).label("revenue_fen"),
                    func.count(Order.id).label("order_count"),
                )
                .join(Store, Store.id == Order.store_id)
                .where(Order.tenant_id == tenant_uuid)
                .where(Store.brand_id == brand_id)
                .where(Order.status.not_in(list(_EXCLUDED_STATUSES)))
                .where(Order.order_time >= yesterday_start)
                .where(Order.order_time < yesterday_end)
            )
        else:
            yesterday_stmt = (
                select(
                    func.coalesce(func.sum(Order.final_amount_fen), 0).label("revenue_fen"),
                    func.count(Order.id).label("order_count"),
                )
                .where(Order.tenant_id == tenant_uuid)
                .where(Order.status.not_in(list(_EXCLUDED_STATUSES)))
                .where(Order.order_time >= yesterday_start)
                .where(Order.order_time < yesterday_end)
            )

        yesterday_row = (await db.execute(yesterday_stmt)).one()
        yesterday_revenue: int = yesterday_row[0]
        yesterday_orders: int = yesterday_row[1]

        aov_fen = revenue_fen // order_count if order_count > 0 else 0
        yesterday_aov = yesterday_revenue // yesterday_orders if yesterday_orders > 0 else 0

        # 门店数量
        stores_stmt = select(
            func.count(Store.id).label("total"),
            func.count(Store.id).filter(Store.is_active == True).label("online"),  # noqa: E712
        ).where(Store.tenant_id == tenant_uuid)
        if brand_id:
            stores_stmt = stores_stmt.where(Store.brand_id == brand_id)
        stores_row = (await db.execute(stores_stmt)).one()
        total_stores: int = stores_row[0]
        online_stores: int = stores_row[1]

        # 翻台率
        seats_stmt = (
            select(func.coalesce(func.sum(Store.seats), 0).label("total_seats"))
            .where(Store.tenant_id == tenant_uuid)
            .where(Store.is_active == True)  # noqa: E712
        )
        if brand_id:
            seats_stmt = seats_stmt.where(Store.brand_id == brand_id)
        total_seats: int = (await db.execute(seats_stmt)).scalar() or 0

        turnover_count: int = (
            await db.execute(
                select(func.count(Order.id))
                .where(Order.tenant_id == tenant_uuid)
                .where(Order.order_type == "dine_in")
                .where(Order.status.not_in(list(_EXCLUDED_STATUSES)))
                .where(Order.order_time >= day_start)
                .where(Order.order_time < day_end)
            )
        ).scalar() or 0
        table_turnover_rate = round(turnover_count / total_seats, 2) if total_seats > 0 else 0.0

        yesterday_turnover_count: int = (
            await db.execute(
                select(func.count(Order.id))
                .where(Order.tenant_id == tenant_uuid)
                .where(Order.order_type == "dine_in")
                .where(Order.status.not_in(list(_EXCLUDED_STATUSES)))
                .where(Order.order_time >= yesterday_start)
                .where(Order.order_time < yesterday_end)
            )
        ).scalar() or 0
        yesterday_turnover_rate = round(yesterday_turnover_count / total_seats, 2) if total_seats > 0 else 0.0

        return {
            "date": target_date.isoformat(),
            "revenue_fen": revenue_fen,
            "revenue_change": _safe_change(revenue_fen, yesterday_revenue),
            "order_count": order_count,
            "order_change": _safe_change(order_count, yesterday_orders),
            "table_turnover_rate": table_turnover_rate,
            "turnover_change": _safe_change(table_turnover_rate, yesterday_turnover_rate),
            "avg_order_value_fen": aov_fen,
            "aov_change": _safe_change(aov_fen, yesterday_aov),
            "online_stores": online_stores,
            "total_stores": total_stores,
        }

    except SQLAlchemyError as exc:
        logger.warning("_query_overview: SQLAlchemy error, returning zeros. error=%r", exc)
        return _zero


async def _query_store_ranking(
    target_date: date,
    limit: int,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """查询门店营收排行榜，DB 报 SQLAlchemyError 时返回空列表。"""
    tenant_uuid = uuid.UUID(tenant_id)
    day_start, day_end = _day_window(target_date)

    try:
        await _set_tenant(db, tenant_id)

        stmt = (
            select(
                Store.id.label("store_id"),
                Store.store_name.label("store_name"),
                func.coalesce(func.sum(Order.final_amount_fen), 0).label("revenue_fen"),
                func.count(Order.id).label("order_count"),
            )
            .join(Order, Order.store_id == Store.id)
            .where(Store.tenant_id == tenant_uuid)
            .where(Order.tenant_id == tenant_uuid)
            .where(Order.status.not_in(list(_EXCLUDED_STATUSES)))
            .where(Order.order_time >= day_start)
            .where(Order.order_time < day_end)
            .group_by(Store.id, Store.store_name)
            .order_by(func.sum(Order.final_amount_fen).desc())
            .limit(limit)
        )

        rows = (await db.execute(stmt)).all()
        return [
            {
                "rank": idx + 1,
                "store_id": str(row.store_id),
                "store_name": row.store_name,
                "revenue_fen": row.revenue_fen,
                "order_count": row.order_count,
            }
            for idx, row in enumerate(rows)
        ]

    except SQLAlchemyError as exc:
        logger.warning("_query_store_ranking: SQLAlchemy error, returning empty list. error=%r", exc)
        return []


async def _query_category_sales(
    target_date: date,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """查询品类销售占比，DB 报 SQLAlchemyError 时返回零值结构。"""
    tenant_uuid = uuid.UUID(tenant_id)
    day_start, day_end = _day_window(target_date)

    _zero: dict = {"date": target_date.isoformat(), "categories": [], "total_fen": 0}

    try:
        await _set_tenant(db, tenant_id)

        stmt = (
            select(
                DishCategory.name.label("category"),
                func.coalesce(func.sum(OrderItem.subtotal_fen), 0).label("revenue_fen"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .join(Dish, Dish.id == OrderItem.dish_id)
            .join(DishCategory, DishCategory.id == Dish.category_id)
            .where(Order.tenant_id == tenant_uuid)
            .where(Order.status.not_in(list(_EXCLUDED_STATUSES)))
            .where(Order.order_time >= day_start)
            .where(Order.order_time < day_end)
            .group_by(DishCategory.name)
            .order_by(func.sum(OrderItem.subtotal_fen).desc())
        )

        rows = (await db.execute(stmt)).all()
        total_fen: int = sum(row.revenue_fen for row in rows)

        categories = [
            {
                "category": row.category,
                "revenue_fen": row.revenue_fen,
                "percentage": round(row.revenue_fen / total_fen, 4) if total_fen > 0 else 0.0,
            }
            for row in rows
        ]

        # 无 dish_id 关联的订单项（历史数据/散装菜品）放入"其他"
        no_cat_fen: int = (
            await db.execute(
                select(func.coalesce(func.sum(OrderItem.subtotal_fen), 0).label("revenue_fen"))
                .join(Order, Order.id == OrderItem.order_id)
                .where(Order.tenant_id == tenant_uuid)
                .where(Order.status.not_in(list(_EXCLUDED_STATUSES)))
                .where(Order.order_time >= day_start)
                .where(Order.order_time < day_end)
                .where(OrderItem.dish_id.is_(None))
            )
        ).scalar() or 0

        if no_cat_fen > 0:
            total_fen += no_cat_fen
            categories.append(
                {
                    "category": "其他",
                    "revenue_fen": no_cat_fen,
                    "percentage": round(no_cat_fen / total_fen, 4) if total_fen > 0 else 0.0,
                }
            )
            for cat in categories:
                cat["percentage"] = round(cat["revenue_fen"] / total_fen, 4) if total_fen > 0 else 0.0

        return {"date": target_date.isoformat(), "categories": categories, "total_fen": total_fen}

    except SQLAlchemyError as exc:
        logger.warning("_query_category_sales: SQLAlchemy error, returning zeros. error=%r", exc)
        return _zero


# ─── GET /api/v1/analytics/overview ────────────────────────────────────────


@router.get("/overview")
async def get_overview(
    date: Optional[str] = None,
    brand_id: Optional[str] = None,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """总体 KPI 概览（营收/单量/翻台率/客单价/门店在线数）

    参数：
      date     — YYYY-MM-DD，默认今日
      brand_id — 可选，过滤特定品牌门店
      X-Tenant-ID — 必填 header
    """
    tenant_id = _require_tenant(x_tenant_id)
    target_date = _parse_date(date)

    _zero_overview = {
        "date": target_date.isoformat(),
        "revenue_fen": 0,
        "revenue_change": 0.0,
        "order_count": 0,
        "order_change": 0.0,
        "table_turnover_rate": 0.0,
        "turnover_change": 0.0,
        "avg_order_value_fen": 0,
        "aov_change": 0.0,
        "online_stores": 0,
        "total_stores": 0,
    }

    try:
        async with async_session_factory() as session:
            data = await _query_overview(target_date, tenant_id, session, brand_id=brand_id)

    except (OSError, ConnectionRefusedError, TimeoutError) as exc:
        logger.warning("overview: DB connection error, returning zeros. error=%r", exc)
        data = _zero_overview
    except Exception as exc:  # noqa: BLE001 — 最外层兜底，驾驶舱不返回 500
        logger.warning("overview: unexpected error, returning zeros. error=%r", exc, exc_info=True)
        data = _zero_overview

    return {"ok": True, "data": data}


# ─── GET /api/v1/analytics/store-ranking ───────────────────────────────────


@router.get("/store-ranking")
async def get_store_ranking(
    date: Optional[str] = None,
    limit: int = 10,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """门店营收排行榜

    参数：
      date   — YYYY-MM-DD，默认今日
      limit  — 返回条数，默认 10
      X-Tenant-ID — 必填 header
    """
    tenant_id = _require_tenant(x_tenant_id)
    target_date = _parse_date(date)
    limit = max(1, min(limit, 100))  # 安全边界

    try:
        async with async_session_factory() as session:
            stores = await _query_store_ranking(target_date, limit, tenant_id, session)
            data = {"date": target_date.isoformat(), "stores": stores}

    except (OSError, ConnectionRefusedError, TimeoutError) as exc:
        logger.warning("store-ranking: DB connection error, returning empty. error=%r", exc)
        data = {"date": target_date.isoformat(), "stores": []}
    except Exception as exc:  # noqa: BLE001 — 最外层兜底，驾驶舱不返回 500
        logger.warning("store-ranking: unexpected error, returning empty. error=%r", exc, exc_info=True)
        data = {"date": target_date.isoformat(), "stores": []}

    return {"ok": True, "data": data}


# ─── GET /api/v1/analytics/category-sales ──────────────────────────────────


@router.get("/category-sales")
async def get_category_sales(
    date: Optional[str] = None,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """品类销售占比

    实现逻辑：
      JOIN order_items → dishes → dish_categories
      按 dish_categories.name GROUP BY，汇总 subtotal_fen，计算占比

    参数：
      date         — YYYY-MM-DD，默认今日
      X-Tenant-ID  — 必填 header
    """
    tenant_id = _require_tenant(x_tenant_id)
    target_date = _parse_date(date)

    try:
        async with async_session_factory() as session:
            data = await _query_category_sales(target_date, tenant_id, session)

    except (OSError, ConnectionRefusedError, TimeoutError) as exc:
        logger.warning("category-sales: DB connection error, returning zeros. error=%r", exc)
        data = {"date": target_date.isoformat(), "categories": [], "total_fen": 0}
    except Exception as exc:  # noqa: BLE001 — 最外层兜底，驾驶舱不返回 500
        logger.warning("category-sales: unexpected error, returning zeros. error=%r", exc, exc_info=True)
        data = {"date": target_date.isoformat(), "categories": [], "total_fen": 0}

    return {"ok": True, "data": data}
