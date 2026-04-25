"""划菜统计 API — 出品时效分析

提供扫码划菜的统计分析接口，用于 KDS 管理后台和经营报表。
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..models.dish_scan_log import DishScanLog

router = APIRouter(prefix="/api/v1/kds", tags=["kds-analytics"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


@router.get("/scan-stats")
async def api_scan_stats(
    request: Request,
    store_id: str = Query(description="门店ID"),
    date_from: str = Query(
        default=None,
        description="起始日期(ISO格式, 如2026-04-25)，不传默认当天",
    ),
    date_to: str = Query(
        default=None,
        description="结束日期(ISO格式)，不传默认当天",
    ),
    timeout_threshold: int = Query(
        default=900,
        description="超时阈值(秒)，默认15分钟=900秒",
    ),
    db: AsyncSession = Depends(get_db),
):
    """划菜统计 — 总数/平均出品时间/超时率/按档口统计

    用于 KDS 管理后台的出品时效仪表盘。

    返回：
    - total_scanned: 总划菜数
    - avg_duration_seconds: 平均出品时间（秒）
    - max_duration_seconds: 最长出品时间
    - min_duration_seconds: 最短出品时间
    - timeout_count: 超时数量（超过 timeout_threshold）
    - timeout_rate: 超时率
    - by_dept: 按档口分组统计
    """
    tenant_id = _get_tenant_id(request)

    try:
        tid = uuid.UUID(tenant_id)
        store_uuid = uuid.UUID(store_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 tenant_id 或 store_id")

    # 解析日期范围
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if date_from:
        try:
            from_dt = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效日期格式: {date_from}")
    else:
        from_dt = today_start

    if date_to:
        try:
            to_dt = datetime.fromisoformat(date_to).replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc,
            )
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效日期格式: {date_to}")
    else:
        to_dt = now

    # ── 基础条件 ──
    conditions = [
        DishScanLog.tenant_id == tid,
        DishScanLog.store_id == store_uuid,
        DishScanLog.scanned_at >= from_dt,
        DishScanLog.scanned_at <= to_dt,
        DishScanLog.is_deleted == False,  # noqa: E712
    ]

    # ── 总体统计 ──
    overall_stmt = select(
        func.count().label("total"),
        func.avg(DishScanLog.duration_seconds).label("avg_duration"),
        func.max(DishScanLog.duration_seconds).label("max_duration"),
        func.min(DishScanLog.duration_seconds).label("min_duration"),
        func.sum(
            case(
                (DishScanLog.duration_seconds > timeout_threshold, 1),
                else_=0,
            )
        ).label("timeout_count"),
    ).where(and_(*conditions))

    overall = (await db.execute(overall_stmt)).one()
    total = overall.total or 0
    timeout_count = overall.timeout_count or 0

    # ── 按档口统计 ──
    dept_stmt = (
        select(
            DishScanLog.dept_id,
            func.count().label("count"),
            func.avg(DishScanLog.duration_seconds).label("avg_duration"),
            func.max(DishScanLog.duration_seconds).label("max_duration"),
            func.sum(
                case(
                    (DishScanLog.duration_seconds > timeout_threshold, 1),
                    else_=0,
                )
            ).label("timeout_count"),
        )
        .where(and_(*conditions, DishScanLog.dept_id.isnot(None)))
        .group_by(DishScanLog.dept_id)
        .order_by(func.count().desc())
    )
    dept_rows = (await db.execute(dept_stmt)).all()

    by_dept = [
        {
            "dept_id": str(row.dept_id) if row.dept_id else None,
            "count": row.count,
            "avg_duration_seconds": round(float(row.avg_duration), 1) if row.avg_duration else None,
            "max_duration_seconds": row.max_duration,
            "timeout_count": row.timeout_count or 0,
            "timeout_rate": round((row.timeout_count or 0) / row.count, 4) if row.count else 0,
        }
        for row in dept_rows
    ]

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "date_from": from_dt.isoformat(),
            "date_to": to_dt.isoformat(),
            "total_scanned": total,
            "avg_duration_seconds": round(float(overall.avg_duration), 1) if overall.avg_duration else None,
            "max_duration_seconds": overall.max_duration,
            "min_duration_seconds": overall.min_duration,
            "timeout_threshold": timeout_threshold,
            "timeout_count": timeout_count,
            "timeout_rate": round(timeout_count / total, 4) if total else 0,
            "by_dept": by_dept,
        },
    }
