"""宴会分析报表 API 路由 — S7

GET  /api/v1/analytics/banquet/source-conversion      来源转化率
GET  /api/v1/analytics/banquet/lead-conversion         商机转化率按销售
GET  /api/v1/analytics/banquet/order-analysis          订单分析按类型
GET  /api/v1/analytics/banquet/salesperson-ranking     销售排名
GET  /api/v1/analytics/banquet/lost-reasons            丢单原因TOP10
GET  /api/v1/analytics/banquet/revenue-trend           营收趋势
GET  /api/v1/analytics/banquet/dashboard               宴会仪表盘
POST /api/v1/analytics/banquet/lost-reasons            记录丢单原因

公共参数：
  ?store_id=<UUID>              门店ID（必填）
  ?date_from=YYYY-MM-DD         起始日期
  ?date_to=YYYY-MM-DD           截止日期

响应格式：{"code": 0, "data": {...}, "message": "ok"}
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.banquet_analytics_service import (
    get_banquet_dashboard,
    get_banquet_order_analysis,
    get_banquet_revenue_trend,
    get_lead_conversion_by_salesperson,
    get_lost_reason_analysis,
    get_salesperson_ranking,
    get_source_conversion,
    record_lost_reason,
)

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/analytics/banquet", tags=["banquet-analytics"])


# ──────────────────────────────────────────────
# 公共辅助
# ──────────────────────────────────────────────


def _require_store(store_id: Optional[str]) -> str:
    if not store_id:
        raise HTTPException(status_code=400, detail="store_id query parameter is required")
    return store_id


def _require_tenant(tenant_id: Optional[str]) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return tenant_id


def _parse_date(date_str: Optional[str], default: Optional[date] = None) -> date:
    if not date_str:
        return default or date.today()
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format '{date_str}', expected YYYY-MM-DD",
        )


def _ok(data: object) -> dict:
    return {"code": 0, "data": data, "message": "ok"}


# ──────────────────────────────────────────────
# 1. 来源转化率
# ──────────────────────────────────────────────


@router.get("/source-conversion")
async def api_source_conversion(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """来源转化率 — 各渠道商机→订单的转化漏斗"""
    tenant_id = _require_tenant(x_tenant_id)
    sid = _require_store(store_id)
    d_from = _parse_date(date_from, date.today() - timedelta(days=30))
    d_to = _parse_date(date_to)

    data = await get_source_conversion(db, tenant_id, sid, d_from, d_to)
    return _ok(data)


# ──────────────────────────────────────────────
# 2. 商机转化率按销售
# ──────────────────────────────────────────────


@router.get("/lead-conversion")
async def api_lead_conversion(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """商机转化率按销售 — 各销售员的漏斗转化数据"""
    tenant_id = _require_tenant(x_tenant_id)
    sid = _require_store(store_id)
    d_from = _parse_date(date_from, date.today() - timedelta(days=30))
    d_to = _parse_date(date_to)

    data = await get_lead_conversion_by_salesperson(db, tenant_id, sid, d_from, d_to)
    return _ok(data)


# ──────────────────────────────────────────────
# 3. 订单分析按类型
# ──────────────────────────────────────────────


@router.get("/order-analysis")
async def api_order_analysis(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD"),
    banquet_type: Optional[str] = Query(None, description="宴会类型过滤"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """订单分析按类型 — 婚宴/生日宴/宝宝宴/寿宴等维度统计"""
    tenant_id = _require_tenant(x_tenant_id)
    sid = _require_store(store_id)
    d_from = _parse_date(date_from, date.today() - timedelta(days=90))
    d_to = _parse_date(date_to)

    data = await get_banquet_order_analysis(
        db, tenant_id, sid, d_from, d_to, banquet_type=banquet_type
    )
    return _ok(data)


# ──────────────────────────────────────────────
# 4. 销售排名
# ──────────────────────────────────────────────


@router.get("/salesperson-ranking")
async def api_salesperson_ranking(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD"),
    sort_by: str = Query("revenue", description="排序依据: revenue|count"),
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """销售排名 — 按营收或成单数排行"""
    tenant_id = _require_tenant(x_tenant_id)
    sid = _require_store(store_id)
    d_from = _parse_date(date_from, date.today() - timedelta(days=30))
    d_to = _parse_date(date_to)

    data = await get_salesperson_ranking(
        db, tenant_id, sid, d_from, d_to, sort_by=sort_by, limit=limit
    )
    return _ok(data)


# ──────────────────────────────────────────────
# 5. 丢单原因 TOP10
# ──────────────────────────────────────────────


@router.get("/lost-reasons")
async def api_lost_reasons(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD"),
    top_n: int = Query(10, ge=1, le=50, description="返回TOP N条"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """丢单原因分析 — TOP N 丢单原因 + 竞品分析"""
    tenant_id = _require_tenant(x_tenant_id)
    sid = _require_store(store_id)
    d_from = _parse_date(date_from, date.today() - timedelta(days=90))
    d_to = _parse_date(date_to)

    data = await get_lost_reason_analysis(
        db, tenant_id, sid, d_from, d_to, top_n=top_n
    )
    return _ok(data)


# ──────────────────────────────────────────────
# 6. 营收趋势
# ──────────────────────────────────────────────


@router.get("/revenue-trend")
async def api_revenue_trend(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD"),
    granularity: str = Query("day", description="汇总粒度: day|week|month"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """营收趋势 — 按日/周/月聚合宴会营收走势"""
    tenant_id = _require_tenant(x_tenant_id)
    sid = _require_store(store_id)
    d_from = _parse_date(date_from, date.today() - timedelta(days=90))
    d_to = _parse_date(date_to)

    if granularity not in ("day", "week", "month"):
        raise HTTPException(status_code=422, detail="granularity must be day, week or month")

    data = await get_banquet_revenue_trend(
        db, tenant_id, sid, d_from, d_to, granularity=granularity
    )
    return _ok(data)


# ──────────────────────────────────────────────
# 7. 宴会仪表盘
# ──────────────────────────────────────────────


@router.get("/dashboard")
async def api_dashboard(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """宴会仪表盘 — 综合看板（订单总览/商机漏斗/类型分布/近期宴会）"""
    tenant_id = _require_tenant(x_tenant_id)
    sid = _require_store(store_id)
    d_from = _parse_date(date_from, date.today() - timedelta(days=30))
    d_to = _parse_date(date_to)

    data = await get_banquet_dashboard(db, tenant_id, sid, d_from, d_to)
    return _ok(data)


# ──────────────────────────────────────────────
# 8. 记录丢单原因（POST）
# ──────────────────────────────────────────────


@router.post("/lost-reasons")
async def api_record_lost_reason(
    store_id: str = Query(..., description="门店ID"),
    body: dict = Body(...),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """记录丢单原因 — 写入 banquet_lost_reasons 表

    请求体：
    {
        "reason_category": "价格",          // 必填
        "reason_detail": "客户觉得桌价偏高",  // 选填
        "banquet_lead_id": "uuid",           // 选填，关联商机
        "banquet_type": "wedding",           // 选填
        "competitor_name": "xxx酒店",        // 选填
        "lost_revenue_fen": 300000,          // 选填
        "lost_tables": 20,                   // 选填
        "salesperson_id": "uuid",            // 选填
        "salesperson_name": "张三",          // 选填
        "recorded_by": "uuid"               // 必填，操作人ID
    }
    """
    tenant_id = _require_tenant(x_tenant_id)

    if not body.get("reason_category"):
        raise HTTPException(status_code=422, detail="reason_category is required")
    if not body.get("recorded_by"):
        raise HTTPException(status_code=422, detail="recorded_by is required")

    data = await record_lost_reason(db, tenant_id, store_id, body)
    return _ok(data)
