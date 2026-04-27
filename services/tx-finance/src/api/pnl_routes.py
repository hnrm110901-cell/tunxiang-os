"""日 P&L 损益表 API 路由

端点：
  POST /api/v1/finance/pnl/calculate          — 计算指定日期 P&L（触发 PnLEngine）
  GET  /api/v1/finance/pnl/{store_id}          — 查询日 P&L 详情（?date=YYYY-MM-DD）
  GET  /api/v1/finance/pnl/trend               — P&L 趋势（?store_id=&days=30）
  GET  /api/v1/finance/pnl/multi-store         — 多门店 P&L 对比（?date=，总部驾驶舱）
  POST /api/v1/finance/pnl/batch-calculate     — 批量计算（补算历史数据）
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from services.pnl_engine import PnLEngine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["finance-pnl"])

_pnl_engine = PnLEngine()


# ─── 请求 / 响应模型 ──────────────────────────────────────────────────────────


class CalculatePnLRequest(BaseModel):
    store_id: str = Field(..., description="门店ID（UUID）")
    date: str = Field(..., description="计算日期 YYYY-MM-DD 或 today")


class BatchCalculateRequest(BaseModel):
    store_id: str = Field(..., description="门店ID（UUID）")
    start_date: str = Field(..., description="起始日期 YYYY-MM-DD")
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD（含）")


# ─── 依赖注入 ─────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


def _parse_date_param(d: str) -> date:
    if d == "today":
        return date.today()
    try:
        return date.fromisoformat(d)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"日期格式错误: {d}，请使用 YYYY-MM-DD") from exc


# ─── POST /pnl/calculate ──────────────────────────────────────────────────────


@router.post("/pnl/calculate", summary="触发日 P&L 计算")
async def calculate_pnl(
    body: CalculatePnLRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    触发指定门店指定日期的 P&L 计算并写入 daily_pnl 表。

    - 已锁定（status=locked）的记录不会被覆盖
    - 支持重复触发（idempotent，每次重算最新数据）

    返回计算结果的完整 P&L 结构。
    """
    sid = _parse_uuid(body.store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    pnl_date = _parse_date_param(body.date)

    if pnl_date > date.today():
        raise HTTPException(status_code=400, detail="不支持计算未来日期的 P&L")

    try:
        result = await _pnl_engine.calculate_daily_pnl(tid, sid, pnl_date, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": result.to_dict()}


# ─── GET /pnl/{store_id} ──────────────────────────────────────────────────────


@router.get("/pnl/{store_id}", summary="查询门店日 P&L 详情")
async def get_daily_pnl(
    store_id: str,
    pnl_date: str = Query("today", alias="date", description="日期 YYYY-MM-DD 或 today"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    查询指定门店指定日期的 P&L 详情。

    - 若 daily_pnl 表中已有记录直接返回（无需重算）
    - 若无记录，自动触发计算并返回
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    biz_date = _parse_date_param(pnl_date)

    # 先查 daily_pnl 表
    existing = await db.execute(
        text("""
            SELECT
                gross_revenue_fen, dine_in_revenue_fen, takeaway_revenue_fen,
                banquet_revenue_fen, discount_amount_fen, net_revenue_fen,
                food_cost_fen, labor_cost_fen, rent_cost_fen,
                utilities_cost_fen, other_cost_fen, total_cost_fen,
                gross_profit_fen, gross_margin_pct,
                operating_profit_fen, net_profit_fen, net_margin_pct,
                orders_count, avg_order_value_fen, table_turnover_rate,
                status, calculated_at
            FROM daily_pnl
            WHERE tenant_id = :tenant_id::UUID
              AND store_id = :store_id::UUID
              AND pnl_date = :pnl_date
              AND is_deleted = FALSE
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "pnl_date": biz_date.isoformat(),
        },
    )
    row = existing.fetchone()

    if row is not None:
        # 有缓存记录直接返回
        return {
            "ok": True,
            "data": _row_to_pnl_dict(sid, biz_date, row),
        }

    # 无记录时自动计算
    if biz_date > date.today():
        raise HTTPException(status_code=404, detail=f"{biz_date} 尚无 P&L 数据")

    try:
        result = await _pnl_engine.calculate_daily_pnl(tid, sid, biz_date, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": result.to_dict()}


# ─── GET /pnl/trend ───────────────────────────────────────────────────────────


@router.get("/pnl/trend", summary="P&L 趋势（30天折线图数据）")
async def get_pnl_trend(
    store_id: str = Query(..., description="门店ID"),
    days: int = Query(30, ge=1, le=365, description="查询天数（默认30天）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    返回指定门店最近 N 天的 P&L 趋势数据（折线图用）。

    每日返回：
    - net_revenue_fen, gross_profit_fen, operating_profit_fen
    - gross_margin_pct, orders_count
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)

    result = await db.execute(
        text("""
            SELECT
                pnl_date,
                net_revenue_fen,
                gross_profit_fen,
                gross_margin_pct,
                operating_profit_fen,
                net_margin_pct,
                orders_count,
                avg_order_value_fen,
                table_turnover_rate,
                status
            FROM daily_pnl
            WHERE tenant_id = :tenant_id::UUID
              AND store_id = :store_id::UUID
              AND pnl_date BETWEEN :start_date AND :end_date
              AND is_deleted = FALSE
            ORDER BY pnl_date ASC
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    rows = result.fetchall()

    trend = [
        {
            "date": str(r[0]),
            "net_revenue_fen": r[1],
            "gross_profit_fen": r[2],
            "gross_margin_pct": float(r[3]) if r[3] is not None else 0.0,
            "operating_profit_fen": r[4],
            "net_margin_pct": float(r[5]) if r[5] is not None else 0.0,
            "orders_count": r[6],
            "avg_order_value_fen": r[7],
            "table_turnover_rate": float(r[8]) if r[8] is not None else 0.0,
            "status": r[9],
        }
        for r in rows
    ]

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "days": days,
            "trend": trend,
        },
    }


# ─── GET /pnl/multi-store ─────────────────────────────────────────────────────


@router.get("/pnl/multi-store", summary="多门店 P&L 对比（总部驾驶舱）")
async def get_multi_store_pnl(
    pnl_date: str = Query("today", alias="date", description="日期 YYYY-MM-DD 或 today"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    总部驾驶舱：查询当日所有门店的 P&L，按净营收降序排列。

    适用于：
    - 总部全局指标看板
    - 门店间横向对比
    - 快速发现异常门店（成本率超标/利润告警）
    """
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    biz_date = _parse_date_param(pnl_date)

    result = await db.execute(
        text("""
            SELECT
                dp.store_id,
                dp.net_revenue_fen,
                dp.gross_profit_fen,
                dp.gross_margin_pct,
                dp.operating_profit_fen,
                dp.net_margin_pct,
                dp.food_cost_fen,
                dp.labor_cost_fen,
                dp.orders_count,
                dp.avg_order_value_fen,
                dp.table_turnover_rate,
                dp.status
            FROM daily_pnl dp
            WHERE dp.tenant_id = :tenant_id::UUID
              AND dp.pnl_date = :pnl_date
              AND dp.is_deleted = FALSE
            ORDER BY dp.net_revenue_fen DESC
        """),
        {
            "tenant_id": str(tid),
            "pnl_date": biz_date.isoformat(),
        },
    )
    rows = result.fetchall()

    stores_data = [
        {
            "store_id": str(r[0]),
            "net_revenue_fen": r[1],
            "gross_profit_fen": r[2],
            "gross_margin_pct": float(r[3]) if r[3] is not None else 0.0,
            "operating_profit_fen": r[4],
            "net_margin_pct": float(r[5]) if r[5] is not None else 0.0,
            "food_cost_fen": r[6],
            "labor_cost_fen": r[7],
            "orders_count": r[8],
            "avg_order_value_fen": r[9],
            "table_turnover_rate": float(r[10]) if r[10] is not None else 0.0,
            "status": r[11],
        }
        for r in rows
    ]

    # 汇总合计
    total_revenue = sum(s["net_revenue_fen"] for s in stores_data)
    total_gross_profit = sum(s["gross_profit_fen"] for s in stores_data)
    total_operating_profit = sum(s["operating_profit_fen"] for s in stores_data)
    total_orders = sum(s["orders_count"] for s in stores_data)

    return {
        "ok": True,
        "data": {
            "date": str(biz_date),
            "store_count": len(stores_data),
            "summary": {
                "total_net_revenue_fen": total_revenue,
                "total_gross_profit_fen": total_gross_profit,
                "total_operating_profit_fen": total_operating_profit,
                "total_orders_count": total_orders,
                "avg_gross_margin_pct": (
                    round(total_gross_profit / total_revenue * 100, 2) if total_revenue > 0 else 0.0
                ),
            },
            "stores": stores_data,
        },
    }


# ─── POST /pnl/batch-calculate ────────────────────────────────────────────────


@router.post("/pnl/batch-calculate", summary="批量计算历史 P&L")
async def batch_calculate_pnl(
    body: BatchCalculateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    批量补算指定门店一段时间内的历史 P&L。

    - 最大支持 90 天范围
    - 已锁定（status=locked）的日期自动跳过
    - 未来日期自动跳过
    - 返回各日期的计算状态

    常用于：历史数据初始化、数据修正后重算。
    """
    sid = _parse_uuid(body.store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    start = _parse_date_param(body.start_date)
    end = _parse_date_param(body.end_date)

    if start > end:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    max_days = 90
    if (end - start).days >= max_days:
        raise HTTPException(status_code=400, detail=f"批量计算范围不能超过 {max_days} 天")

    today = date.today()
    results: list[dict] = []
    errors: list[dict] = []

    current = start
    while current <= end:
        if current > today:
            current += timedelta(days=1)
            continue

        try:
            daily = await _pnl_engine.calculate_daily_pnl(tid, sid, current, db)
            results.append(
                {
                    "date": str(current),
                    "ok": True,
                    "net_revenue_fen": daily.net_revenue_fen,
                    "gross_profit_fen": daily.gross_profit_fen,
                    "operating_profit_fen": daily.operating_profit_fen,
                }
            )
        except ValueError as exc:
            errors.append({"date": str(current), "ok": False, "error": str(exc)})
        current += timedelta(days=1)

    return {
        "ok": True,
        "data": {
            "store_id": body.store_id,
            "start_date": body.start_date,
            "end_date": body.end_date,
            "calculated_count": len(results),
            "error_count": len(errors),
            "results": results,
            "errors": errors,
        },
    }


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _row_to_pnl_dict(store_id: uuid.UUID, pnl_date: date, row) -> dict:
    """将 daily_pnl 查询行转为标准响应字典。"""
    return {
        "store_id": str(store_id),
        "pnl_date": str(pnl_date),
        "revenue": {
            "gross_revenue_fen": row[0],
            "dine_in_revenue_fen": row[1],
            "takeaway_revenue_fen": row[2],
            "banquet_revenue_fen": row[3],
            "discount_amount_fen": row[4],
            "net_revenue_fen": row[5],
        },
        "cost": {
            "food_cost_fen": row[6],
            "labor_cost_fen": row[7],
            "rent_cost_fen": row[8],
            "utilities_cost_fen": row[9],
            "other_cost_fen": row[10],
            "total_cost_fen": row[11],
        },
        "profit": {
            "gross_profit_fen": row[12],
            "gross_margin_pct": float(row[13]) if row[13] is not None else 0.0,
            "operating_profit_fen": row[14],
            "net_profit_fen": row[15],
            "net_margin_pct": float(row[16]) if row[16] is not None else 0.0,
        },
        "kpi": {
            "orders_count": row[17],
            "avg_order_value_fen": row[18],
            "table_turnover_rate": float(row[19]) if row[19] is not None else 0.0,
        },
        "status": row[20],
        "calculated_at": str(row[21]) if row[21] else None,
    }
