"""厨房管理报表 API 路由

GET /api/v1/reports/kitchen/overtime           制作超时报表
GET /api/v1/reports/kitchen/chef-performance   厨师业绩报表
GET /api/v1/reports/kitchen/station-efficiency 档口效率报表
GET /api/v1/reports/kitchen/dish-duration      菜品制作时长分析
GET /api/v1/reports/kitchen/steaming-stats     蒸制统计
GET /api/v1/reports/kitchen/peak-analysis      厨房高峰时段
GET /api/v1/reports/kitchen/waste-stats        厨房损耗（废单/退菜）
GET /api/v1/reports/kitchen/daily-summary      厨房综合日报

公共参数：
  ?store_id=<UUID>              门店ID（必填）
  ?date_from=YYYY-MM-DD         起始日期
  ?date_to=YYYY-MM-DD           截止日期
  ?format=csv                   返回 CSV 文件

响应格式：{"code": 0, "data": {...}, "message": "ok"}

数据来源：
  kds_events (order_id, dish_id, station_id, started_at, completed_at,
              status, operated_by, tenant_id, store_id)
  所有查询均包含 tenant_id + store_id 过滤。
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/reports/kitchen", tags=["kitchen-reports"])


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


def _csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    if not rows:
        content = ""
    else:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        content = buf.getvalue()
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ──────────────────────────────────────────────
# 1. 制作超时报表
# ──────────────────────────────────────────────


@router.get("/overtime")
async def api_kitchen_overtime(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    threshold_minutes: int = Query(15, description="超时阈值（分钟），默认15"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """制作超时报表 — 超过阈值的出餐明细

    查询逻辑：
      - 从 kds_events 取 status='completed' 且制作时长超过阈值的记录
      - 制作时长 = EXTRACT(EPOCH FROM (completed_at - started_at)) / 60
      - 按 started_at 倒序分页返回
      - 同时返回总超时数和超时率（超时数/总完成数）
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)
    offset = (page - 1) * page_size

    # 超时明细
    rows = await db.execute(
        text(
            """
            SELECT
                ke.id          AS event_id,
                ke.order_id,
                ke.dish_id,
                ke.station_id,
                ke.operated_by AS chef_id,
                ke.started_at,
                ke.completed_at,
                ROUND(
                    EXTRACT(EPOCH FROM (ke.completed_at - ke.started_at)) / 60.0, 1
                )::float                                        AS duration_minutes,
                ROUND(
                    EXTRACT(EPOCH FROM (ke.completed_at - ke.started_at)) / 60.0
                    - :threshold_minutes, 1
                )::float                                        AS overtime_minutes
            FROM kds_events ke
            WHERE ke.tenant_id  = :tenant_id
              AND ke.store_id   = :store_id
              AND ke.status     = 'completed'
              AND ke.started_at IS NOT NULL
              AND ke.completed_at IS NOT NULL
              AND DATE(ke.started_at) BETWEEN :d_from AND :d_to
              AND EXTRACT(EPOCH FROM (ke.completed_at - ke.started_at)) / 60.0
                  > :threshold_minutes
            ORDER BY ke.started_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
            "threshold_minutes": threshold_minutes,
            "limit": page_size,
            "offset": offset,
        },
    )
    items = [dict(r) for r in rows.mappings()]

    # 汇总：总完成数、超时数
    stats_row = await db.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE EXTRACT(EPOCH FROM (completed_at - started_at)) / 60.0
                          > :threshold_minutes
                )                                               AS overtime_count,
                COUNT(*)                                        AS total_count
            FROM kds_events
            WHERE tenant_id   = :tenant_id
              AND store_id    = :store_id
              AND status      = 'completed'
              AND started_at  IS NOT NULL
              AND completed_at IS NOT NULL
              AND DATE(started_at) BETWEEN :d_from AND :d_to
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
            "threshold_minutes": threshold_minutes,
        },
    )
    stats = stats_row.mappings().first()
    total_overtime = int(stats["overtime_count"] or 0) if stats else 0
    total_done = int(stats["total_count"] or 0) if stats else 0
    overtime_rate = round(total_overtime / total_done, 4) if total_done > 0 else 0.0

    data = {
        "total_overtime_count": total_overtime,
        "total_completed_count": total_done,
        "overtime_rate": overtime_rate,
        "threshold_minutes": threshold_minutes,
        "page": page,
        "page_size": page_size,
        "items": items,
    }

    if format == "csv":
        return _csv_response(items, f"kitchen_overtime_{d_from}_{d_to}.csv")
    return _ok(data)


# ──────────────────────────────────────────────
# 2. 厨师业绩报表
# ──────────────────────────────────────────────


@router.get("/chef-performance")
async def api_chef_performance(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    chef_id: Optional[str] = Query(None, description="厨师ID，不传则返回全部"),
    overtime_threshold_minutes: int = Query(15, description="超时阈值（分钟），用于计算超时率"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """厨师业绩报表 — 人均出品量/超时率/综合评分

    查询逻辑：
      - 从 kds_events 按 operated_by 分组，统计每位厨师的出品量/平均制作时长/超时次数
      - LEFT JOIN employees 获取厨师姓名
      - 综合评分 = 100 - (超时率 * 50) - (平均超时分钟 * 2)，最低0分
      - 若传入 chef_id 则只返回该厨师
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    chef_filter = "AND ke.operated_by = :chef_id" if chef_id else ""
    params: dict = {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "d_from": str(d_from),
        "d_to": str(d_to),
        "threshold": overtime_threshold_minutes,
    }
    if chef_id:
        params["chef_id"] = chef_id

    rows = await db.execute(
        text(
            f"""
            SELECT
                ke.operated_by                                               AS chef_id,
                e.employee_name                                              AS chef_name,
                COUNT(*)                                                     AS total_dishes,
                ROUND(
                    AVG(EXTRACT(EPOCH FROM (ke.completed_at - ke.started_at)) / 60.0), 1
                )::float                                                     AS avg_duration_minutes,
                COUNT(*) FILTER (
                    WHERE EXTRACT(EPOCH FROM (ke.completed_at - ke.started_at)) / 60.0
                          > :threshold
                )                                                            AS overtime_count,
                ROUND(
                    COUNT(*) FILTER (
                        WHERE EXTRACT(EPOCH FROM (ke.completed_at - ke.started_at)) / 60.0
                              > :threshold
                    )::numeric * 100.0 / NULLIF(COUNT(*), 0), 2
                )::float                                                     AS overtime_rate,
                -- 综合评分: 满分100，超时率每1%扣0.5分，平均超时每1分钟扣2分
                GREATEST(
                    ROUND(
                        100.0
                        - (
                            COUNT(*) FILTER (
                                WHERE EXTRACT(EPOCH FROM (ke.completed_at - ke.started_at)) / 60.0
                                      > :threshold
                            )::numeric * 100.0 / NULLIF(COUNT(*), 0)
                          ) * 0.5
                        - GREATEST(
                            AVG(
                                CASE WHEN EXTRACT(EPOCH FROM (ke.completed_at - ke.started_at)) / 60.0 > :threshold
                                     THEN EXTRACT(EPOCH FROM (ke.completed_at - ke.started_at)) / 60.0 - :threshold
                                     ELSE 0 END
                            ), 0
                          ) * 2.0,
                    1),
                0)::float                                                    AS score
            FROM kds_events ke
            LEFT JOIN employees e
                   ON e.id::text = ke.operated_by
                  AND e.tenant_id = ke.tenant_id
                  AND e.is_deleted = FALSE
            WHERE ke.tenant_id   = :tenant_id
              AND ke.store_id    = :store_id
              AND ke.status      = 'completed'
              AND ke.started_at  IS NOT NULL
              AND ke.completed_at IS NOT NULL
              AND DATE(ke.started_at) BETWEEN :d_from AND :d_to
              {chef_filter}
            GROUP BY ke.operated_by, e.employee_name
            ORDER BY total_dishes DESC
            """
        ),
        params,
    )
    items = [dict(r) for r in rows.mappings()]

    if format == "csv":
        return _csv_response(items, f"chef_performance_{d_from}_{d_to}.csv")
    return _ok(items)


# ──────────────────────────────────────────────
# 3. 档口效率报表
# ──────────────────────────────────────────────


@router.get("/station-efficiency")
async def api_station_efficiency(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """档口效率报表 — 各档口出品量/平均等待/高峰时段/利用率

    查询逻辑：
      - 按 station_id 分组汇总 kds_events
      - 高峰时段 = 该档口 started_at 出现最多的小时
      - 利用率 = 实际有事件的分钟数 / 营业总分钟数（用日期范围天数 × 600分钟估算）
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            WITH station_stats AS (
                SELECT
                    station_id,
                    COUNT(*)                                                     AS total_output,
                    ROUND(
                        AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) / 60.0), 1
                    )::float                                                     AS avg_wait_minutes,
                    -- 高峰小时：出现频次最高的 started_at 小时
                    MODE() WITHIN GROUP (ORDER BY EXTRACT(HOUR FROM started_at)::int)
                                                                                 AS peak_hour
                FROM kds_events
                WHERE tenant_id   = :tenant_id
                  AND store_id    = :store_id
                  AND status      = 'completed'
                  AND started_at  IS NOT NULL
                  AND completed_at IS NOT NULL
                  AND DATE(started_at) BETWEEN :d_from AND :d_to
                GROUP BY station_id
            )
            SELECT
                ss.station_id,
                ss.total_output,
                ss.avg_wait_minutes,
                ss.peak_hour,
                -- 利用率粗估：每天按600分钟营业时长，日期范围天数 × 600
                ROUND(
                    ss.total_output::numeric * ss.avg_wait_minutes
                    / NULLIF(
                        (:day_count * 600.0),
                        0
                    ) * 100.0, 2
                )::float AS utilization_rate
            FROM station_stats ss
            ORDER BY ss.total_output DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
            "day_count": max((d_to - d_from).days + 1, 1),
        },
    )
    items = [dict(r) for r in rows.mappings()]

    if format == "csv":
        return _csv_response(items, f"station_efficiency_{d_from}_{d_to}.csv")
    return _ok(items)


# ──────────────────────────────────────────────
# 4. 菜品制作时长分析
# ──────────────────────────────────────────────


@router.get("/dish-duration")
async def api_dish_duration(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    dish_id: Optional[str] = Query(None, description="菜品ID，不传则返回全部"),
    overtime_threshold_minutes: int = Query(15, description="超时阈值（分钟）"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """菜品制作时长分析 — 平均/最短/最长/超时率

    查询逻辑：
      - 按 dish_id 分组，统计各菜品在 kds_events 中的制作时长分布
      - 若传入 dish_id 则过滤特定菜品
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    dish_filter = "AND ke.dish_id = :dish_id" if dish_id else ""
    params: dict = {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "d_from": str(d_from),
        "d_to": str(d_to),
        "threshold": overtime_threshold_minutes,
    }
    if dish_id:
        params["dish_id"] = dish_id

    rows = await db.execute(
        text(
            f"""
            SELECT
                ke.dish_id,
                COUNT(*)                                                         AS sample_count,
                ROUND(
                    AVG(EXTRACT(EPOCH FROM (ke.completed_at - ke.started_at)) / 60.0), 1
                )::float                                                         AS avg_duration,
                ROUND(
                    MIN(EXTRACT(EPOCH FROM (ke.completed_at - ke.started_at)) / 60.0), 1
                )::float                                                         AS min_duration,
                ROUND(
                    MAX(EXTRACT(EPOCH FROM (ke.completed_at - ke.started_at)) / 60.0), 1
                )::float                                                         AS max_duration,
                ROUND(
                    COUNT(*) FILTER (
                        WHERE EXTRACT(EPOCH FROM (ke.completed_at - ke.started_at)) / 60.0
                              > :threshold
                    )::numeric * 100.0 / NULLIF(COUNT(*), 0), 2
                )::float                                                         AS overtime_rate
            FROM kds_events ke
            WHERE ke.tenant_id   = :tenant_id
              AND ke.store_id    = :store_id
              AND ke.status      = 'completed'
              AND ke.started_at  IS NOT NULL
              AND ke.completed_at IS NOT NULL
              AND DATE(ke.started_at) BETWEEN :d_from AND :d_to
              {dish_filter}
            GROUP BY ke.dish_id
            ORDER BY avg_duration DESC
            """
        ),
        params,
    )
    items = [dict(r) for r in rows.mappings()]

    if format == "csv":
        return _csv_response(items, f"dish_duration_{d_from}_{d_to}.csv")
    return _ok(items)


# ──────────────────────────────────────────────
# 5. 蒸制统计
# ──────────────────────────────────────────────


@router.get("/steaming-stats")
async def api_steaming_stats(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """蒸制统计 — 蒸制品类次数/时长/收入

    查询逻辑（TODO 待细化）：
      - 蒸制菜品通过 kds_events 中 station_id 关联到 station_type='steaming' 的档口
      - 或通过 dish_id 关联 dishes 表的 cooking_method='steaming' 字段筛选
      - 目前返回 station_id 包含 'steam' 关键字的 kds_events 汇总（近似匹配）
      - 生产环境建议在 dishes 表增加 cooking_method 字段后精确过滤
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # 近似查询：station_id 包含 steam 的档口事件（生产环境按实际档口ID替换）
    rows = await db.execute(
        text(
            """
            SELECT
                ke.dish_id,
                ke.station_id,
                COUNT(*)                                                     AS steaming_count,
                ROUND(
                    AVG(EXTRACT(EPOCH FROM (ke.completed_at - ke.started_at)) / 60.0), 1
                )::float                                                     AS avg_duration_minutes
            FROM kds_events ke
            WHERE ke.tenant_id   = :tenant_id
              AND ke.store_id    = :store_id
              AND ke.status      = 'completed'
              AND ke.started_at  IS NOT NULL
              AND ke.completed_at IS NOT NULL
              AND DATE(ke.started_at) BETWEEN :d_from AND :d_to
              AND LOWER(ke.station_id::text) LIKE '%steam%'
            GROUP BY ke.dish_id, ke.station_id
            ORDER BY steaming_count DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]

    if format == "csv":
        return _csv_response(items, f"steaming_stats_{d_from}_{d_to}.csv")
    return _ok(items)


# ──────────────────────────────────────────────
# 6. 厨房高峰时段
# ──────────────────────────────────────────────


@router.get("/peak-analysis")
async def api_kitchen_peak_analysis(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """厨房高峰时段分析 — 每小时订单量/平均等待/压力等级

    查询逻辑：
      - 按 started_at 小时分组，统计每小时的 kds_events 数量和平均制作时长
      - 压力等级根据每小时事件数（占全日最大值比例）划分：
          < 25%  → low
          25-50% → medium
          50-75% → high
          ≥ 75%  → critical
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            WITH hourly AS (
                SELECT
                    EXTRACT(HOUR FROM started_at)::int                       AS hour,
                    COUNT(*)                                                  AS event_count,
                    ROUND(
                        AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) / 60.0), 1
                    )::float                                                  AS avg_wait_minutes
                FROM kds_events
                WHERE tenant_id   = :tenant_id
                  AND store_id    = :store_id
                  AND status      = 'completed'
                  AND started_at  IS NOT NULL
                  AND completed_at IS NOT NULL
                  AND DATE(started_at) BETWEEN :d_from AND :d_to
                GROUP BY EXTRACT(HOUR FROM started_at)::int
            ),
            max_count AS (
                SELECT MAX(event_count) AS max_event_count FROM hourly
            )
            SELECT
                h.hour,
                h.event_count,
                h.avg_wait_minutes,
                CASE
                    WHEN m.max_event_count = 0                              THEN 'low'
                    WHEN h.event_count::float / m.max_event_count < 0.25   THEN 'low'
                    WHEN h.event_count::float / m.max_event_count < 0.50   THEN 'medium'
                    WHEN h.event_count::float / m.max_event_count < 0.75   THEN 'high'
                    ELSE 'critical'
                END                                                          AS pressure_level
            FROM hourly h, max_count m
            ORDER BY h.hour
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]

    if format == "csv":
        return _csv_response(items, f"kitchen_peak_{d_from}_{d_to}.csv")
    return _ok(items)


# ──────────────────────────────────────────────
# 7. 厨房损耗（废单/退菜）
# ──────────────────────────────────────────────


@router.get("/waste-stats")
async def api_kitchen_waste_stats(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """厨房损耗报表 — 废单/退菜统计，按原因/菜品分类

    查询逻辑：
      - 废单/退菜来自 kds_events.status = 'cancelled' 或 'voided'
      - 按 dish_id 分组得到 by_dish；按 status 分组得到 by_reason
      - 损耗金额通过 JOIN order_items 获取（kds_events.order_id + dish_id 关联）
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # 按菜品统计损耗
    by_dish_rows = await db.execute(
        text(
            """
            SELECT
                ke.dish_id,
                COUNT(*)                                         AS waste_count,
                COALESCE(SUM(oi.subtotal_fen), 0)               AS waste_amount_fen,
                ke.status                                        AS waste_type
            FROM kds_events ke
            LEFT JOIN order_items oi
                   ON oi.order_id = ke.order_id
                  AND oi.dish_id  = ke.dish_id
                  AND oi.tenant_id = ke.tenant_id
                  AND oi.is_deleted = FALSE
            WHERE ke.tenant_id  = :tenant_id
              AND ke.store_id   = :store_id
              AND ke.status     IN ('cancelled', 'voided')
              AND DATE(ke.started_at) BETWEEN :d_from AND :d_to
            GROUP BY ke.dish_id, ke.status
            ORDER BY waste_amount_fen DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    by_dish = [dict(r) for r in by_dish_rows.mappings()]

    # 按原因分组汇总
    by_reason_rows = await db.execute(
        text(
            """
            SELECT
                ke.status                                        AS reason,
                COUNT(*)                                         AS waste_count,
                COALESCE(SUM(oi.subtotal_fen), 0)               AS waste_amount_fen
            FROM kds_events ke
            LEFT JOIN order_items oi
                   ON oi.order_id = ke.order_id
                  AND oi.dish_id  = ke.dish_id
                  AND oi.tenant_id = ke.tenant_id
                  AND oi.is_deleted = FALSE
            WHERE ke.tenant_id  = :tenant_id
              AND ke.store_id   = :store_id
              AND ke.status     IN ('cancelled', 'voided')
              AND DATE(ke.started_at) BETWEEN :d_from AND :d_to
            GROUP BY ke.status
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    by_reason = [dict(r) for r in by_reason_rows.mappings()]

    total_waste_count = sum(r.get("waste_count", 0) or 0 for r in by_reason)
    total_waste_amount_fen = sum(r.get("waste_amount_fen", 0) or 0 for r in by_reason)

    data = {
        "total_waste_count": total_waste_count,
        "total_waste_amount_fen": total_waste_amount_fen,
        "by_reason": by_reason,
        "by_dish": by_dish,
    }

    if format == "csv":
        return _csv_response(by_dish, f"kitchen_waste_{d_from}_{d_to}.csv")
    return _ok(data)


# ──────────────────────────────────────────────
# 8. 厨房综合日报
# ──────────────────────────────────────────────


@router.get("/daily-summary")
async def api_kitchen_daily_summary(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date: Optional[str] = Query(None, description="业务日期 YYYY-MM-DD，默认今日"),
    overtime_threshold_minutes: int = Query(15, description="超时阈值（分钟）"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """厨房综合日报 — 全天核心指标汇总

    聚合当日：总出品数、超时率、平均制作时长、最忙档口、最忙小时、损耗数、
    出品最多的厨师。
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    target_date = _parse_date(date)

    # 一次查询获取全天核心指标
    summary_row = await db.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'completed')        AS total_dishes,
                COUNT(*) FILTER (WHERE status IN ('cancelled','voided')) AS waste_count,
                ROUND(
                    AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) / 60.0)
                    FILTER (WHERE status = 'completed'
                              AND completed_at IS NOT NULL), 1
                )::float                                             AS avg_wait_minutes,
                ROUND(
                    COUNT(*) FILTER (
                        WHERE status = 'completed'
                          AND EXTRACT(EPOCH FROM (completed_at - started_at)) / 60.0
                              > :threshold
                    )::numeric * 100.0 / NULLIF(
                        COUNT(*) FILTER (WHERE status = 'completed'), 0
                    ), 2
                )::float                                             AS overtime_rate,
                MODE() WITHIN GROUP (
                    ORDER BY EXTRACT(HOUR FROM started_at)::int
                ) FILTER (WHERE status = 'completed')                AS busiest_hour,
                MODE() WITHIN GROUP (ORDER BY station_id)
                    FILTER (WHERE status = 'completed')              AS busiest_station_id,
                MODE() WITHIN GROUP (ORDER BY operated_by)
                    FILTER (WHERE status = 'completed')              AS top_chef_id
            FROM kds_events
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND started_at IS NOT NULL
              AND DATE(started_at) = :target_date
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "target_date": str(target_date),
            "threshold": overtime_threshold_minutes,
        },
    )
    summary = summary_row.mappings().first()

    data = {
        "date": str(target_date),
        "total_dishes": int(summary["total_dishes"] or 0) if summary else 0,
        "overtime_rate": float(summary["overtime_rate"] or 0.0) if summary else 0.0,
        "avg_wait_minutes": float(summary["avg_wait_minutes"] or 0.0) if summary else 0.0,
        "top_chef_id": summary["top_chef_id"] if summary else None,
        "busiest_hour": int(summary["busiest_hour"]) if summary and summary["busiest_hour"] is not None else None,
        "busiest_station_id": summary["busiest_station_id"] if summary else None,
        "waste_count": int(summary["waste_count"] or 0) if summary else 0,
    }

    if format == "csv":
        return _csv_response([data], f"kitchen_daily_summary_{target_date}.csv")
    return _ok(data)
