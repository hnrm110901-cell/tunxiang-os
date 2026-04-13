"""集团跨店数据看板 API

GET /api/v1/analytics/group/today?brand_id=   — 所有门店今日实时汇总
GET /api/v1/analytics/group/trend?brand_id=&days=7  — 7/30天营收趋势
GET /api/v1/analytics/group/alerts?brand_id=  — 集团级异常告警
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/analytics/group", tags=["group-dashboard"])


# ─── 依赖 ────────────────────────────────────────────────────────────────────

async def _get_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _get_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


# ─── 工具 ────────────────────────────────────────────────────────────────────

def _require_tenant(tenant_id: Optional[str]) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return tenant_id


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS session 变量，隔离租户数据。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── Pydantic 响应模型 ────────────────────────────────────────────────────────

class StoreTodayData(BaseModel):
    store_id: str
    store_name: str
    status: str                   # open | closed
    revenue_fen: int
    order_count: int
    table_turnover: float
    occupied_tables: int
    total_tables: int
    current_diners: int
    avg_serve_time_min: int
    revenue_vs_yesterday_pct: float
    alerts: list[str]


class GroupSummary(BaseModel):
    total_revenue_fen: int
    total_orders: int
    avg_table_turnover: float
    active_stores: int
    total_stores: int
    revenue_vs_yesterday_pct: float
    current_diners: int


class GroupTodayResponse(BaseModel):
    summary: GroupSummary
    stores: list[StoreTodayData]


class GroupTrendResponse(BaseModel):
    dates: list[str]
    total_revenue: list[int]
    by_store: dict[str, list[int]]


class AlertItem(BaseModel):
    severity: str                 # danger | warning | info
    store_name: str
    type: str
    title: str
    body: str
    created_at: str


class GroupAlertsResponse(BaseModel):
    alerts: list[AlertItem]


# ─── 路由处理器 ──────────────────────────────────────────────────────────────

@router.get("/today", response_model=dict)
async def get_group_today(
    brand_id: Optional[str] = Query(None, description="品牌 ID（可选，不传则查全部门店）"),
    db: AsyncSession = Depends(_get_db),
    tenant_id: str = Depends(_get_tenant),
):
    """
    今日集团实时数据汇总（所有门店）
    - 从 stores 表获取门店列表（支持 brand_id 过滤）
    - 从 orders 表聚合今日已完成订单营收/单数
    """
    await _set_rls(db, tenant_id)

    # ── 1. 查询门店列表 ──────────────────────────────────────────────────────
    try:
        if brand_id:
            store_rows = (
                await db.execute(
                    text(
                        "SELECT id, store_name, brand_id "
                        "FROM stores "
                        "WHERE tenant_id = :tid AND brand_id = :bid AND is_deleted = FALSE"
                    ),
                    {"tid": tenant_id, "bid": brand_id},
                )
            ).fetchall()
        else:
            store_rows = (
                await db.execute(
                    text(
                        "SELECT id, store_name, brand_id "
                        "FROM stores "
                        "WHERE tenant_id = :tid AND is_deleted = FALSE"
                    ),
                    {"tid": tenant_id},
                )
            ).fetchall()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.warning("group_today.stores_query_failed", tenant_id=tenant_id, error=str(exc))
        return {"ok": True, "data": GroupTodayResponse(
            summary=GroupSummary(
                total_revenue_fen=0, total_orders=0, avg_table_turnover=0.0,
                active_stores=0, total_stores=0, revenue_vs_yesterday_pct=0.0,
                current_diners=0,
            ),
            stores=[],
        ).model_dump()}

    if not store_rows:
        return {"ok": True, "data": GroupTodayResponse(
            summary=GroupSummary(
                total_revenue_fen=0, total_orders=0, avg_table_turnover=0.0,
                active_stores=0, total_stores=0, revenue_vs_yesterday_pct=0.0,
                current_diners=0,
            ),
            stores=[],
        ).model_dump()}

    store_id_list = [str(r.id) for r in store_rows]
    store_name_map = {str(r.id): r.store_name for r in store_rows}

    # ── 2. 查询今日已完成订单汇总（降级：失败返回空） ────────────────────────
    today_revenue: dict[str, int] = {}
    today_orders: dict[str, int] = {}
    try:
        order_rows = (
            await db.execute(
                text(
                    "SELECT store_id, "
                    "       COALESCE(SUM(final_amount_fen), 0) AS revenue_fen, "
                    "       COUNT(*) AS order_count "
                    "FROM orders "
                    "WHERE tenant_id = :tid "
                    "  AND status = 'completed' "
                    "  AND DATE(order_time AT TIME ZONE 'Asia/Shanghai') = CURRENT_DATE "
                    "GROUP BY store_id"
                ),
                {"tid": tenant_id},
            )
        ).fetchall()
        for row in order_rows:
            sid = str(row.store_id)
            today_revenue[sid] = int(row.revenue_fen)
            today_orders[sid] = int(row.order_count)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.warning(
            "group_today.orders_query_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )
        # 降级：今日数据为空，继续组装响应

    # ── 3. 组装各门店数据 ────────────────────────────────────────────────────
    stores_data: list[StoreTodayData] = []
    for store_id in store_id_list:
        rev = today_revenue.get(store_id, 0)
        cnt = today_orders.get(store_id, 0)
        stores_data.append(
            StoreTodayData(
                store_id=store_id,
                store_name=store_name_map[store_id],
                status="open" if cnt > 0 else "closed",
                revenue_fen=rev,
                order_count=cnt,
                table_turnover=0.0,       # 需接桌台系统，暂留 0
                occupied_tables=0,
                total_tables=0,
                current_diners=0,
                avg_serve_time_min=0,
                revenue_vs_yesterday_pct=0.0,
                alerts=[],
            )
        )

    # ── 4. 汇总 ─────────────────────────────────────────────────────────────
    active = [s for s in stores_data if s.status == "open"]
    total_revenue_fen = sum(s.revenue_fen for s in stores_data)
    total_orders_cnt = sum(s.order_count for s in stores_data)

    summary = GroupSummary(
        total_revenue_fen=total_revenue_fen,
        total_orders=total_orders_cnt,
        avg_table_turnover=0.0,
        active_stores=len(active),
        total_stores=len(stores_data),
        revenue_vs_yesterday_pct=0.0,
        current_diners=0,
    )

    return {
        "ok": True,
        "data": GroupTodayResponse(summary=summary, stores=stores_data).model_dump(),
    }


@router.get("/trend", response_model=dict)
async def get_group_trend(
    brand_id: Optional[str] = Query(None, description="品牌 ID（可选）"),
    days: int = Query(7, ge=1, le=30, description="天数，支持 7 / 30"),
    db: AsyncSession = Depends(_get_db),
    tenant_id: str = Depends(_get_tenant),
):
    """
    集团营收趋势（N 天）

    - 从 stores 表获取门店列表（支持 brand_id 过滤）
    - 优先查 mv_daily_settlement 物化视图，不存在则降级查 orders 原表
    """
    await _set_rls(db, tenant_id)

    # ── 1. 构造日期序列 ──────────────────────────────────────────────────────
    from datetime import date
    today = date.today()
    date_list = [(today - timedelta(days=days - 1 - i)) for i in range(days)]
    dates = [d.isoformat() for d in date_list]
    start_date = date_list[0]
    start_ts = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)

    # ── 2. 查询门店列表（brand_id 过滤） ────────────────────────────────────
    try:
        if brand_id:
            store_rows = (
                await db.execute(
                    text(
                        "SELECT id, store_name "
                        "FROM stores "
                        "WHERE tenant_id = :tid AND brand_id = :bid AND is_deleted = FALSE"
                    ),
                    {"tid": tenant_id, "bid": brand_id},
                )
            ).fetchall()
        else:
            store_rows = (
                await db.execute(
                    text(
                        "SELECT id, store_name "
                        "FROM stores "
                        "WHERE tenant_id = :tid AND is_deleted = FALSE"
                    ),
                    {"tid": tenant_id},
                )
            ).fetchall()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.warning("group_trend.stores_query_failed", tenant_id=tenant_id, error=str(exc))
        return {"ok": True, "data": GroupTrendResponse(
            dates=dates, total_revenue=[0] * days, by_store={}
        ).model_dump()}

    store_id_list = [str(r.id) for r in store_rows]
    store_name_map = {str(r.id): r.store_name for r in store_rows}

    if not store_id_list:
        return {"ok": True, "data": GroupTrendResponse(
            dates=dates, total_revenue=[0] * days, by_store={}
        ).model_dump()}

    # ── 3. 检查物化视图是否存在 ──────────────────────────────────────────────
    try:
        mv_exists_row = (
            await db.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.tables "
                    "  WHERE table_name = 'mv_daily_settlement'"
                    ") AS mv_exists"
                )
            )
        ).fetchone()
        use_mv = bool(mv_exists_row.mv_exists) if mv_exists_row else False
    except SQLAlchemyError:
        use_mv = False

    # ── 4. 查询聚合数据 ──────────────────────────────────────────────────────
    # 结构：{store_id: {date_str: revenue_fen}}
    store_daily: dict[str, dict[str, int]] = {sid: {} for sid in store_id_list}

    try:
        if use_mv:
            # 从 mv_daily_settlement 查询
            mv_rows = (
                await db.execute(
                    text(
                        "SELECT store_id::text, biz_date, "
                        "       COALESCE(revenue_fen, 0) AS revenue_fen "
                        "FROM mv_daily_settlement "
                        "WHERE tenant_id = :tid "
                        "  AND biz_date >= :start_date "
                        "  AND store_id = ANY(:store_ids)"
                    ),
                    {
                        "tid": tenant_id,
                        "start_date": start_date,
                        "store_ids": store_id_list,
                    },
                )
            ).fetchall()
            for row in mv_rows:
                sid = str(row.store_id)
                if sid in store_daily:
                    d_str = row.biz_date.isoformat() if hasattr(row.biz_date, "isoformat") else str(row.biz_date)
                    store_daily[sid][d_str] = int(row.revenue_fen)
        else:
            # 降级：从 orders 原表按月聚合
            order_rows = (
                await db.execute(
                    text(
                        "SELECT store_id::text, "
                        "       DATE(order_time AT TIME ZONE 'Asia/Shanghai') AS day, "
                        "       COALESCE(SUM(final_amount_fen), 0) AS revenue_fen "
                        "FROM orders "
                        "WHERE tenant_id = :tid "
                        "  AND status = 'completed' "
                        "  AND order_time >= :start_ts "
                        "  AND store_id = ANY(:store_ids) "
                        "GROUP BY store_id, day "
                        "ORDER BY day"
                    ),
                    {
                        "tid": tenant_id,
                        "start_ts": start_ts,
                        "store_ids": store_id_list,
                    },
                )
            ).fetchall()
            for row in order_rows:
                sid = str(row.store_id)
                if sid in store_daily:
                    d_str = row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day)
                    store_daily[sid][d_str] = int(row.revenue_fen)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.warning("group_trend.orders_query_failed", tenant_id=tenant_id, error=str(exc))
        # 降级：所有数据为 0，继续

    # ── 5. 整形为响应格式 ────────────────────────────────────────────────────
    by_store: dict[str, list[int]] = {}
    total_revenue: list[int] = [0] * days

    for sid in store_id_list:
        store_name = store_name_map[sid]
        revenues = [store_daily[sid].get(d, 0) for d in dates]
        by_store[store_name] = revenues
        for i, v in enumerate(revenues):
            total_revenue[i] += v

    return {
        "ok": True,
        "data": GroupTrendResponse(
            dates=dates,
            total_revenue=total_revenue,
            by_store=by_store,
        ).model_dump(),
    }


@router.get("/alerts", response_model=dict)
async def get_group_alerts(
    brand_id: Optional[str] = Query(None, description="品牌 ID（可选）"),
    db: AsyncSession = Depends(_get_db),
    tenant_id: str = Depends(_get_tenant),
):
    """
    集团级异常告警列表

    从 analytics_alerts 表查询 open/acknowledged 状态的告警，
    DB 查询失败时降级返回空列表（log.warning，不抛异常）。
    """
    await _set_rls(db, tenant_id)

    # ── 1. 查询门店名称映射（用于关联 store_name） ────────────────────────────
    store_name_map: dict[str, str] = {}
    try:
        if brand_id:
            store_rows = (
                await db.execute(
                    text(
                        "SELECT id, store_name "
                        "FROM stores "
                        "WHERE tenant_id = :tid AND brand_id = :bid AND is_deleted = FALSE"
                    ),
                    {"tid": tenant_id, "bid": brand_id},
                )
            ).fetchall()
        else:
            store_rows = (
                await db.execute(
                    text(
                        "SELECT id, store_name "
                        "FROM stores "
                        "WHERE tenant_id = :tid AND is_deleted = FALSE"
                    ),
                    {"tid": tenant_id},
                )
            ).fetchall()
        store_name_map = {str(r.id): r.store_name for r in store_rows}
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.warning("group_alerts.stores_query_failed", tenant_id=tenant_id, error=str(exc))

    # ── 2. 查询告警列表 ──────────────────────────────────────────────────────
    try:
        if brand_id:
            alert_rows = (
                await db.execute(
                    text(
                        "SELECT id, store_id, brand_id, alert_type, level, "
                        "       title, message, status, created_at "
                        "FROM analytics_alerts "
                        "WHERE tenant_id = :tid "
                        "  AND brand_id = :bid "
                        "  AND status IN ('open', 'acknowledged') "
                        "ORDER BY created_at DESC "
                        "LIMIT 50"
                    ),
                    {"tid": tenant_id, "bid": brand_id},
                )
            ).fetchall()
        else:
            alert_rows = (
                await db.execute(
                    text(
                        "SELECT id, store_id, brand_id, alert_type, level, "
                        "       title, message, status, created_at "
                        "FROM analytics_alerts "
                        "WHERE tenant_id = :tid "
                        "  AND status IN ('open', 'acknowledged') "
                        "ORDER BY created_at DESC "
                        "LIMIT 50"
                    ),
                    {"tid": tenant_id},
                )
            ).fetchall()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.warning("group_alerts.query_failed", tenant_id=tenant_id, error=str(exc))
        return {"ok": True, "data": {"alerts": []}}

    # ── 3. level → severity 映射 ─────────────────────────────────────────────
    _level_map = {"critical": "danger", "error": "danger", "warning": "warning", "info": "info"}

    alerts: list[AlertItem] = []
    for row in alert_rows:
        sid = str(row.store_id) if row.store_id else ""
        store_name = store_name_map.get(sid, sid or "未知门店")
        created_str = (
            row.created_at.isoformat()
            if hasattr(row.created_at, "isoformat")
            else str(row.created_at)
        )
        alerts.append(
            AlertItem(
                severity=_level_map.get(str(row.level), "info"),
                store_name=store_name,
                type=str(row.alert_type) if row.alert_type else "unknown",
                title=str(row.title) if row.title else "",
                body=str(row.message) if row.message else "",
                created_at=created_str,
            )
        )

    return {"ok": True, "data": {"alerts": [a.model_dump() for a in alerts]}}
