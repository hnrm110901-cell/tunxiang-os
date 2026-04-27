"""营收聚合 API 路由 — 真实计算引擎

端点：
  GET /api/v1/finance/revenue/daily-fast          日营收快报（含支付分布+小时分布）
  GET /api/v1/finance/revenue/range               多日期范围营收报表（day/week/month）
  GET /api/v1/finance/revenue/payment-reconcile   支付方式对账汇总

所有金额：分（fen）。统一响应格式：{"ok": bool, "data": {}}。
tenant_id 从 X-Tenant-ID header 获取，由 get_db_with_tenant 设置 RLS 上下文。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from services.revenue_aggregation_service import RevenueAggregationService
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/finance/revenue", tags=["revenue-aggregation"])

_service = RevenueAggregationService()


# ── 依赖注入 ──────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    """从 header 提取 tenant_id，返回带 RLS 的 DB session"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_date(value: str, field_name: str) -> date:
    if value == "today":
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} 格式错误，需要 YYYY-MM-DD 或 'today'，收到: {value!r}",
        ) from exc


def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} 不是合法 UUID: {value!r}",
        ) from exc


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.get(
    "/daily-fast",
    summary="日营收快报",
    description=(
        "聚合当日营收：毛收/折扣/退款/净营收/客单价，并附支付方式分布（微信/支付宝/现金/会员/挂账等）和小时级流量分布。"
    ),
)
async def get_daily_revenue_fast(
    store_id: str = Query(..., description="门店 UUID"),
    biz_date: str = Query("today", description="业务日期 YYYY-MM-DD 或 today"),
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    query_date = _parse_date(biz_date, "biz_date")

    try:
        report = await _service.get_daily_revenue_fast(tid, sid, query_date, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.error(
            "daily_revenue_fast.db_error",
            store_id=store_id,
            biz_date=str(query_date),
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="日营收查询失败") from exc

    return {"ok": True, "data": report.to_dict()}


@router.get(
    "/range",
    summary="多日期范围营收报表",
    description=(
        "查询 start_date ~ end_date 区间内营收，支持按 day/week/month 聚合。返回区间摘要（总量）+ 时序趋势数据。"
    ),
)
async def get_revenue_range(
    store_id: str = Query(..., description="门店 UUID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    granularity: Literal["day", "week", "month"] = Query("day", description="聚合粒度: day / week / month"),
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    s_date = _parse_date(start_date, "start_date")
    e_date = _parse_date(end_date, "end_date")

    if s_date > e_date:
        raise HTTPException(
            status_code=400,
            detail=f"start_date ({s_date}) 不能晚于 end_date ({e_date})",
        )
    if (e_date - s_date).days > 366:
        raise HTTPException(
            status_code=400,
            detail="查询区间不能超过 366 天",
        )

    try:
        report = await _service.get_revenue_range_report(tid, sid, s_date, e_date, granularity, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.error(
            "revenue_range.db_error",
            store_id=store_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="营收区间报表查询失败") from exc

    return {"ok": True, "data": report.to_dict()}


@router.get(
    "/payment-reconcile",
    summary="支付方式对账汇总",
    description=(
        "按支付方式（微信/支付宝/现金等）汇总：订单数、应收（订单）、实收（支付）、"
        "退款、净实收，以及应收与实收的差异（正=多收，负=少收）。"
    ),
)
async def get_payment_reconciliation(
    store_id: str = Query(..., description="门店 UUID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    s_date = _parse_date(start_date, "start_date")
    e_date = _parse_date(end_date, "end_date")

    if s_date > e_date:
        raise HTTPException(
            status_code=400,
            detail=f"start_date ({s_date}) 不能晚于 end_date ({e_date})",
        )
    if (e_date - s_date).days > 93:
        raise HTTPException(
            status_code=400,
            detail="对账查询区间不能超过 93 天（约 3 个月）",
        )

    try:
        report = await _service.get_payment_reconciliation(tid, sid, s_date, e_date, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.error(
            "payment_reconciliation.db_error",
            store_id=store_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="支付方式对账查询失败") from exc

    return {"ok": True, "data": report.to_dict()}
