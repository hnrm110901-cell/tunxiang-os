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


# ─── Mock 数据（数据库不可用时的保底） ─────────────────────────────────────


def _mock_overview(target_date: date) -> dict:
    return {
        "date": target_date.isoformat(),
        "revenue_fen": 12500000,
        "revenue_change": 0.08,
        "order_count": 280,
        "order_change": 0.05,
        "table_turnover_rate": 2.3,
        "turnover_change": 0.02,
        "avg_order_value_fen": 44642,
        "aov_change": -0.01,
        "online_stores": 3,
        "total_stores": 5,
        "_is_mock": True,
    }


def _mock_store_ranking(target_date: date, limit: int) -> list[dict]:
    sample = [
        {"rank": 1, "store_id": "mock-001", "store_name": "旗舰店", "revenue_fen": 3500000, "order_count": 85},
        {"rank": 2, "store_id": "mock-002", "store_name": "商场店", "revenue_fen": 2800000, "order_count": 72},
        {"rank": 3, "store_id": "mock-003", "store_name": "社区店", "revenue_fen": 2200000, "order_count": 60},
        {"rank": 4, "store_id": "mock-004", "store_name": "街边店", "revenue_fen": 1800000, "order_count": 45},
        {"rank": 5, "store_id": "mock-005", "store_name": "写字楼店", "revenue_fen": 1200000, "order_count": 38},
    ]
    return sample[:min(limit, len(sample))]


def _mock_category_sales(target_date: date) -> dict:
    categories = [
        {"category": "海鲜", "revenue_fen": 4500000, "percentage": 0.36},
        {"category": "热菜", "revenue_fen": 3200000, "percentage": 0.256},
        {"category": "凉菜", "revenue_fen": 1800000, "percentage": 0.144},
        {"category": "汤品", "revenue_fen": 1500000, "percentage": 0.12},
        {"category": "饮品", "revenue_fen": 900000, "percentage": 0.072},
        {"category": "主食", "revenue_fen": 600000, "percentage": 0.048},
    ]
    return {"categories": categories, "total_fen": 12500000, "_is_mock": True}


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
    day_start, day_end = _day_window(target_date)
    yesterday_start, yesterday_end = _day_window(target_date - timedelta(days=1))
    tenant_uuid = uuid.UUID(tenant_id)

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)

            # ── 1. 今日营收与订单数 ──────────────────────────────────────────
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
            if brand_id:
                # 通过 Store JOIN 过滤品牌
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

            today_result = await session.execute(today_stmt)
            today_row = today_result.one()
            revenue_fen: int = today_row[0]
            order_count: int = today_row[1]

            # ── 2. 昨日数据（计算环比） ──────────────────────────────────────
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

            yesterday_result = await session.execute(yesterday_stmt)
            yesterday_row = yesterday_result.one()
            yesterday_revenue: int = yesterday_row[0]
            yesterday_orders: int = yesterday_row[1]

            # ── 3. 客单价 ────────────────────────────────────────────────────
            aov_fen = revenue_fen // order_count if order_count > 0 else 0
            yesterday_aov = yesterday_revenue // yesterday_orders if yesterday_orders > 0 else 0

            # ── 4. 门店数量（在线 + 总数） ───────────────────────────────────
            stores_stmt = select(
                func.count(Store.id).label("total"),
                func.count(Store.id).filter(Store.is_active == True).label("online"),  # noqa: E712
            ).where(Store.tenant_id == tenant_uuid)
            if brand_id:
                stores_stmt = stores_stmt.where(Store.brand_id == brand_id)

            stores_result = await session.execute(stores_stmt)
            stores_row = stores_result.one()
            total_stores: int = stores_row[0]
            online_stores: int = stores_row[1]

            # ── 5. 翻台率：当日结束桌次 / 总桌台数（用座位数近似） ──────────
            seats_stmt = select(
                func.coalesce(func.sum(Store.seats), 0).label("total_seats"),
            ).where(Store.tenant_id == tenant_uuid).where(Store.is_active == True)  # noqa: E712
            if brand_id:
                seats_stmt = seats_stmt.where(Store.brand_id == brand_id)

            seats_result = await session.execute(seats_stmt)
            total_seats: int = seats_result.scalar() or 0

            # 翻台次数 ≈ 今日有桌号的订单数（dine_in 类型）
            turnover_count_stmt = (
                select(func.count(Order.id))
                .where(Order.tenant_id == tenant_uuid)
                .where(Order.order_type == "dine_in")
                .where(Order.status.not_in(list(_EXCLUDED_STATUSES)))
                .where(Order.order_time >= day_start)
                .where(Order.order_time < day_end)
            )
            turnover_count_result = await session.execute(turnover_count_stmt)
            turnover_count: int = turnover_count_result.scalar() or 0

            table_turnover_rate = round(turnover_count / total_seats, 2) if total_seats > 0 else 0.0

            # 昨日翻台率（用于环比）
            yesterday_turnover_stmt = (
                select(func.count(Order.id))
                .where(Order.tenant_id == tenant_uuid)
                .where(Order.order_type == "dine_in")
                .where(Order.status.not_in(list(_EXCLUDED_STATUSES)))
                .where(Order.order_time >= yesterday_start)
                .where(Order.order_time < yesterday_end)
            )
            yesterday_turnover_result = await session.execute(yesterday_turnover_stmt)
            yesterday_turnover_count: int = yesterday_turnover_result.scalar() or 0
            yesterday_turnover_rate = round(yesterday_turnover_count / total_seats, 2) if total_seats > 0 else 0.0

            data = {
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

    except (OSError, ConnectionRefusedError, TimeoutError) as exc:
        logger.warning("overview: DB connection error, using mock data. error=%r", exc)
        data = _mock_overview(target_date)
    except Exception as exc:  # noqa: BLE001 — 最外层兜底，驾驶舱不返回 500
        logger.warning("overview: unexpected DB error, using mock data. error=%r", exc, exc_info=True)
        data = _mock_overview(target_date)

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
    day_start, day_end = _day_window(target_date)
    tenant_uuid = uuid.UUID(tenant_id)
    limit = max(1, min(limit, 100))  # 安全边界

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)

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

            result = await session.execute(stmt)
            rows = result.all()

            stores = [
                {
                    "rank": idx + 1,
                    "store_id": str(row.store_id),
                    "store_name": row.store_name,
                    "revenue_fen": row.revenue_fen,
                    "order_count": row.order_count,
                }
                for idx, row in enumerate(rows)
            ]

            data = {
                "date": target_date.isoformat(),
                "stores": stores,
            }

    except (OSError, ConnectionRefusedError, TimeoutError) as exc:
        logger.warning("store-ranking: DB connection error, using mock data. error=%r", exc)
        data = {
            "date": target_date.isoformat(),
            "stores": _mock_store_ranking(target_date, limit),
            "_is_mock": True,
        }
    except Exception as exc:  # noqa: BLE001 — 最外层兜底，驾驶舱不返回 500
        logger.warning("store-ranking: unexpected DB error, using mock data. error=%r", exc, exc_info=True)
        data = {
            "date": target_date.isoformat(),
            "stores": _mock_store_ranking(target_date, limit),
            "_is_mock": True,
        }

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
    day_start, day_end = _day_window(target_date)
    tenant_uuid = uuid.UUID(tenant_id)

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)

            # 通过 order_items → dish → dish_categories JOIN 统计品类销售
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

            result = await session.execute(stmt)
            rows = result.all()

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
            no_category_stmt = (
                select(
                    func.coalesce(func.sum(OrderItem.subtotal_fen), 0).label("revenue_fen"),
                )
                .join(Order, Order.id == OrderItem.order_id)
                .where(Order.tenant_id == tenant_uuid)
                .where(Order.status.not_in(list(_EXCLUDED_STATUSES)))
                .where(Order.order_time >= day_start)
                .where(Order.order_time < day_end)
                .where(OrderItem.dish_id.is_(None))
            )
            no_cat_result = await session.execute(no_category_stmt)
            no_cat_fen: int = no_cat_result.scalar() or 0

            if no_cat_fen > 0:
                total_fen += no_cat_fen
                categories.append({
                    "category": "其他",
                    "revenue_fen": no_cat_fen,
                    "percentage": round(no_cat_fen / total_fen, 4) if total_fen > 0 else 0.0,
                })
                # 重新计算占比（因 total 变了）
                for cat in categories:
                    cat["percentage"] = round(cat["revenue_fen"] / total_fen, 4) if total_fen > 0 else 0.0

            data = {
                "date": target_date.isoformat(),
                "categories": categories,
                "total_fen": total_fen,
            }

    except (OSError, ConnectionRefusedError, TimeoutError) as exc:
        logger.warning("category-sales: DB connection error, using mock data. error=%r", exc)
        data = _mock_category_sales(target_date)
    except Exception as exc:  # noqa: BLE001 — 最外层兜底，驾驶舱不返回 500
        logger.warning("category-sales: unexpected DB error, using mock data. error=%r", exc, exc_info=True)
        data = _mock_category_sales(target_date)

    return {"ok": True, "data": data}
