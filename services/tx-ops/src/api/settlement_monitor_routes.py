"""日结监控 API — 总部多门店日结状态聚合看板

端点：
  GET  /api/v1/ops/settlement/monitor          — 所有门店当日日结状态聚合
  GET  /api/v1/ops/settlement/monitor/history  — 历史日结完成率趋势
  GET  /api/v1/ops/settlement/monitor/overdue  — 逾期未结门店列表
  POST /api/v1/ops/settlement/monitor/remark   — 手动标记备注
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/ops/settlement/monitor", tags=["ops-settlement-monitor"])
log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求 / 响应模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class RemarkRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    settlement_date: date = Field(..., description="日结日期")
    remark: str = Field(..., description="备注内容")
    operator_id: str = Field(..., description="操作员ID")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  核心逻辑
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _is_overdue(store: Dict[str, Any], now: datetime) -> bool:
    """判断门店是否逾期：当前时间 > expected_close_time + 1小时 且 status != completed。"""
    if store["status"] == "completed":
        return False
    expected_str = store.get("expected_close_time")
    if not expected_str:
        return False
    try:
        h, m = (int(x) for x in expected_str.split(":"))
        today = now.date()
        expected_dt = datetime(today.year, today.month, today.day, h, m, tzinfo=timezone.utc)
        deadline = expected_dt + timedelta(hours=1)
        return now > deadline
    except (ValueError, AttributeError):
        return False


def _overdue_minutes(store: Dict[str, Any], now: datetime) -> Optional[int]:
    """计算逾期分钟数。"""
    expected_str = store.get("expected_close_time")
    if not expected_str:
        return None
    try:
        h, m = (int(x) for x in expected_str.split(":"))
        today = now.date()
        expected_dt = datetime(today.year, today.month, today.day, h, m, tzinfo=timezone.utc)
        deadline = expected_dt + timedelta(hours=1)
        if now > deadline:
            delta = now - deadline
            return int(delta.total_seconds() / 60)
        return None
    except (ValueError, AttributeError):
        return None


def _compute_summary(stores: List[Dict[str, Any]]) -> Dict[str, Any]:
    """计算汇总统计。"""
    total = len(stores)
    completed = sum(1 for s in stores if s["status"] == "completed")
    pending = sum(1 for s in stores if s["status"] == "pending")
    running = sum(1 for s in stores if s["status"] == "running")
    overdue = sum(1 for s in stores if s["status"] == "overdue")
    completion_rate = round(completed / total * 100, 1) if total > 0 else 0.0
    return {
        "total_stores": total,
        "completed_count": completed,
        "pending_count": pending,
        "running_count": running,
        "overdue_count": overdue,
        "completion_rate": completion_rate,
    }


async def _query_db_stores(
    db: AsyncSession,
    tenant_id: str,
    settlement_date: date,
    brand_id: Optional[str],
    region_id: Optional[str],
    status_filter: Optional[str],
    now: datetime,
) -> List[Dict[str, Any]]:
    """从 DB 查询 daily_settlements + stores 联表。"""
    filters = ["ds.tenant_id = :tenant_id", "ds.settlement_date = :settlement_date", "ds.is_deleted = FALSE"]
    params: Dict[str, Any] = {"tenant_id": tenant_id, "settlement_date": settlement_date}
    if brand_id:
        filters.append("s.brand_id = :brand_id")
        params["brand_id"] = brand_id
    if region_id:
        filters.append("s.region_id = :region_id")
        params["region_id"] = region_id
    if status_filter:
        filters.append("ds.status = :status")
        params["status"] = status_filter

    where = " AND ".join(filters)
    sql = text(f"""
        SELECT
            ds.store_id,
            s.name AS store_name,
            b.name AS brand_name,
            s.brand_id,
            s.region_id,
            ds.status,
            ds.expected_close_time::text AS expected_close_time,
            ds.actual_close_time::text AS actual_close_time,
            e.name AS operator_name,
            ds.duration_minutes,
            ds.remarks
        FROM daily_settlements ds
        LEFT JOIN stores s ON s.id = ds.store_id
        LEFT JOIN brands b ON b.id = s.brand_id
        LEFT JOIN employees e ON e.id = ds.operator_id
        WHERE {where}
        ORDER BY ds.store_id
    """)
    result = await db.execute(sql, params)
    rows = result.fetchall()
    stores = []
    for row in rows:
        m = row._mapping
        s = {
            "store_id": m["store_id"],
            "store_name": m.get("store_name", ""),
            "brand_name": m.get("brand_name", ""),
            "brand_id": m.get("brand_id"),
            "region_id": m.get("region_id"),
            "status": m["status"],
            "expected_close_time": m.get("expected_close_time", "22:00"),
            "actual_close_time": m.get("actual_close_time"),
            "operator_name": m.get("operator_name", ""),
            "duration_minutes": m.get("duration_minutes"),
            "remarks": m.get("remarks", "") or "",
        }
        if _is_overdue(s, now):
            s["status"] = "overdue"
        stores.append(s)
    return stores


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("")
async def get_settlement_monitor(
    brand_id: Optional[str] = Query(None, description="品牌ID过滤"),
    region_id: Optional[str] = Query(None, description="区域ID过滤"),
    status: Optional[str] = Query(None, description="状态过滤: pending/running/completed/overdue"),
    settlement_date: Optional[date] = Query(None, description="日结日期，默认今日"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """所有门店当日日结状态聚合看板。"""
    target_date = settlement_date or date.today()
    now = datetime.now(tz=timezone.utc)

    log.info(
        "settlement_monitor_query",
        tenant_id=x_tenant_id,
        settlement_date=target_date.isoformat(),
        brand_id=brand_id,
        region_id=region_id,
        status=status,
    )

    stores = await _query_db_stores(db, x_tenant_id, target_date, brand_id, region_id, status, now)
    summary = _compute_summary(stores)

    return {
        "ok": True,
        "data": {
            "settlement_date": target_date.isoformat(),
            "summary": summary,
            "stores": stores,
        },
    }


@router.get("/history")
async def get_settlement_history(
    days: int = Query(30, ge=1, le=90, description="历史天数，默认30"),
    brand_id: Optional[str] = Query(None, description="品牌ID过滤"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """历史日结完成率趋势（近 N 天）。"""
    today = date.today()

    log.info("settlement_history_query", tenant_id=x_tenant_id, days=days, brand_id=brand_id)

    brand_filter = "AND s.brand_id = :brand_id" if brand_id else ""
    params: Dict[str, Any] = {
        "tenant_id": x_tenant_id,
        "start_date": today - timedelta(days=days - 1),
        "end_date": today,
    }
    if brand_id:
        params["brand_id"] = brand_id

    sql = text(f"""
        SELECT
            ds.settlement_date,
            COUNT(*) AS total,
            SUM(CASE WHEN ds.status='completed' THEN 1 ELSE 0 END) AS completed
        FROM daily_settlements ds
        LEFT JOIN stores s ON s.id = ds.store_id
        WHERE ds.tenant_id = :tenant_id
          AND ds.settlement_date BETWEEN :start_date AND :end_date
          AND ds.is_deleted = FALSE
          {brand_filter}
        GROUP BY ds.settlement_date
        ORDER BY ds.settlement_date
    """)
    result = await db.execute(sql, params)
    rows = result.fetchall()
    trend: List[Dict[str, Any]] = []
    for row in rows:
        m = row._mapping
        total = m["total"] or 0
        completed = m["completed"] or 0
        rate = round(completed / total * 100, 1) if total > 0 else 0.0
        trend.append(
            {
                "date": m["settlement_date"].isoformat()
                if hasattr(m["settlement_date"], "isoformat")
                else str(m["settlement_date"]),
                "total_stores": total,
                "completed_count": completed,
                "completion_rate": rate,
            }
        )

    return {
        "ok": True,
        "data": {
            "days": days,
            "brand_id": brand_id,
            "trend": trend,
        },
    }


@router.get("/overdue")
async def get_overdue_stores(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """今日所有逾期门店列表，含逾期时长。"""
    now = datetime.now(tz=timezone.utc)
    today = now.date()

    log.info("settlement_overdue_query", tenant_id=x_tenant_id)

    stores = await _query_db_stores(db, x_tenant_id, today, None, None, None, now)

    overdue_stores = []
    for s in stores:
        minutes = _overdue_minutes(s, now)
        if s["status"] == "overdue" or (minutes is not None and minutes > 0):
            overdue_stores.append(
                {
                    **s,
                    "status": "overdue",
                    "overdue_minutes": minutes or 0,
                }
            )

    return {
        "ok": True,
        "data": {
            "settlement_date": today.isoformat(),
            "overdue_count": len(overdue_stores),
            "stores": overdue_stores,
        },
    }


@router.post("/remark")
async def add_settlement_remark(
    body: RemarkRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """手动标记备注（更新日结记录的备注字段）。"""
    date_str = body.settlement_date.isoformat()
    now = datetime.now(tz=timezone.utc)

    log.info(
        "settlement_remark_update",
        tenant_id=x_tenant_id,
        store_id=body.store_id,
        settlement_date=date_str,
        operator_id=body.operator_id,
    )

    sql = text("""
        UPDATE daily_settlements
        SET remarks = :remark, updated_at = :updated_at
        WHERE tenant_id = :tenant_id
          AND store_id = :store_id
          AND settlement_date = :settlement_date
          AND is_deleted = FALSE
    """)
    result = await db.execute(
        sql,
        {
            "remark": body.remark,
            "updated_at": now,
            "tenant_id": x_tenant_id,
            "store_id": body.store_id,
            "settlement_date": body.settlement_date,
        },
    )
    await db.commit()

    return {
        "ok": True,
        "data": {
            "store_id": body.store_id,
            "settlement_date": date_str,
            "remark": body.remark,
            "operator_id": body.operator_id,
            "updated_at": now.isoformat(),
            "rows_affected": result.rowcount,
        },
    }
