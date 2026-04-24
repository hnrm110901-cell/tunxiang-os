"""桌台利用率分析 API (v287)

端点：
  GET  /api/v1/table-utilization/{store_id}              — 利用率仪表盘
  GET  /api/v1/table-utilization/{store_id}/heatmap       — 桌台×时段热力图
  GET  /api/v1/table-utilization/{store_id}/recommendations — Agent调度建议
  POST /api/v1/table-utilization/refresh                  — 手动刷新物化视图

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/table-utilization",
    tags=["table-utilization"],
)


# ─── 通用工具 ────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return str(tid)


def _ok(data: dict | list | None) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> HTTPException:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, TRUE)"), {"tid": tenant_id})


# ─── 建议生成阈值 ────────────────────────────────────────────────────────────

_LOW_UTIL_THRESHOLD = 0.3  # 座位利用率 < 30% → 建议拼桌
_LOW_SESSION_THRESHOLD = 2  # 日均翻台次数 < 2 → 建议关闭
_HIGH_DURATION_THRESHOLD = 90  # 平均用餐时长 > 90分钟 → 建议调整时限


# ─── 路由 ─────────────────────────────────────────────────────────────────────


@router.get("/{store_id}", summary="利用率仪表盘")
async def get_dashboard(
    store_id: uuid.UUID,
    request: Request,
    date_from: Optional[date] = Query(default=None, description="开始日期"),
    date_to: Optional[date] = Query(default=None, description="结束日期"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    按区域分组汇总桌台利用率，返回每区域翻台率/座位利用率/平均消费。

    默认查最近7天数据。
    """
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    if not date_to:
        date_to = date.today()
    if not date_from:
        date_from = date_to - timedelta(days=7)

    result = await db.execute(
        text("""
            SELECT
                zone_id,
                zone_type,
                zone_name,
                COUNT(DISTINCT table_id)          AS table_count,
                SUM(session_count)                AS total_sessions,
                AVG(avg_guest_count)              AS avg_guests,
                AVG(avg_seat_utilization)          AS avg_seat_util,
                AVG(avg_duration_min)             AS avg_duration,
                AVG(avg_per_capita_fen)           AS avg_per_capita_fen,
                SUM(sum_final_fen)                AS total_revenue_fen,
                AVG(avg_service_calls)            AS avg_service_calls
            FROM mv_table_utilization
            WHERE store_id = :sid
              AND tenant_id = :tid
              AND biz_date BETWEEN :d_from AND :d_to
            GROUP BY zone_id, zone_type, zone_name
            ORDER BY zone_name NULLS LAST
        """),
        {"sid": str(store_id), "tid": tid, "d_from": date_from, "d_to": date_to},
    )
    rows = result.fetchall()

    days_count = max((date_to - date_from).days, 1)
    zones = []
    for r in rows:
        total_sessions = int(r.total_sessions or 0)
        table_count = int(r.table_count or 1)
        zones.append(
            {
                "zone_id": str(r.zone_id) if r.zone_id else None,
                "zone_type": r.zone_type,
                "zone_name": r.zone_name or "未分区",
                "table_count": table_count,
                "total_sessions": total_sessions,
                "avg_turnover_rate": round(total_sessions / (table_count * days_count), 2),
                "avg_seat_utilization": round(float(r.avg_seat_util or 0), 3),
                "avg_duration_min": round(float(r.avg_duration or 0), 1),
                "avg_per_capita_fen": int(r.avg_per_capita_fen or 0),
                "total_revenue_fen": int(r.total_revenue_fen or 0),
                "avg_service_calls": round(float(r.avg_service_calls or 0), 1),
            }
        )

    return _ok(
        {
            "store_id": str(store_id),
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "zones": zones,
        }
    )


@router.get("/{store_id}/heatmap", summary="桌台×时段热力图")
async def get_heatmap(
    store_id: uuid.UUID,
    request: Request,
    date_from: Optional[date] = Query(default=None, description="开始日期"),
    date_to: Optional[date] = Query(default=None, description="结束日期"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    返回桌台×市别维度的热力图数据。

    结构: {
      zones: [{
        zone_name, tables: [{
          table_no, sessions: [{market_session, metrics}]
        }]
      }]
    }
    """
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    if not date_to:
        date_to = date.today()
    if not date_from:
        date_from = date_to - timedelta(days=7)

    result = await db.execute(
        text("""
            SELECT
                mv.table_id,
                mv.zone_id,
                mv.zone_name,
                mv.market_session_id,
                sms.name AS market_session_name,
                t.table_no,
                t.seats,
                SUM(mv.session_count)           AS session_count,
                AVG(mv.avg_seat_utilization)     AS avg_seat_util,
                AVG(mv.avg_duration_min)         AS avg_duration,
                AVG(mv.avg_per_capita_fen)       AS avg_per_capita,
                SUM(mv.sum_final_fen)           AS sum_revenue_fen
            FROM mv_table_utilization mv
                JOIN tables t ON mv.table_id = t.id
                LEFT JOIN store_market_sessions sms ON mv.market_session_id = sms.id
            WHERE mv.store_id = :sid
              AND mv.tenant_id = :tid
              AND mv.biz_date BETWEEN :d_from AND :d_to
            GROUP BY
                mv.table_id, mv.zone_id, mv.zone_name,
                mv.market_session_id, sms.name,
                t.table_no, t.seats
            ORDER BY mv.zone_name NULLS LAST, t.table_no, sms.name
        """),
        {"sid": str(store_id), "tid": tid, "d_from": date_from, "d_to": date_to},
    )
    rows = result.fetchall()

    # 组装 zone -> table -> sessions 结构
    zone_map: dict[str, dict] = {}
    table_sessions: dict[str, dict[str, list]] = {}  # zone_key -> {table_key -> [sessions]}

    for r in rows:
        zkey = str(r.zone_id) if r.zone_id else "__no_zone__"
        if zkey not in zone_map:
            zone_map[zkey] = {"zone_name": r.zone_name or "未分区", "zone_id": r.zone_id}
            table_sessions[zkey] = {}

        tkey = str(r.table_id)
        if tkey not in table_sessions[zkey]:
            table_sessions[zkey][tkey] = {
                "table_id": tkey,
                "table_no": r.table_no,
                "seats": r.seats,
                "sessions": [],
            }

        table_sessions[zkey][tkey]["sessions"].append(
            {
                "market_session_id": str(r.market_session_id) if r.market_session_id else None,
                "market_session_name": r.market_session_name,
                "session_count": int(r.session_count or 0),
                "avg_seat_utilization": round(float(r.avg_seat_util or 0), 3),
                "avg_duration_min": round(float(r.avg_duration or 0), 1),
                "avg_per_capita_fen": int(r.avg_per_capita or 0),
                "sum_revenue_fen": int(r.sum_revenue_fen or 0),
            }
        )

    zones = []
    for zkey, zinfo in zone_map.items():
        zones.append(
            {
                "zone_name": zinfo["zone_name"],
                "zone_id": str(zinfo["zone_id"]) if zinfo["zone_id"] else None,
                "tables": list(table_sessions[zkey].values()),
            }
        )

    return _ok(
        {
            "store_id": str(store_id),
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "zones": zones,
        }
    )


@router.get("/{store_id}/recommendations", summary="Agent调度建议")
async def get_recommendations(
    store_id: uuid.UUID,
    request: Request,
    date_from: Optional[date] = Query(default=None, description="分析起始日期"),
    date_to: Optional[date] = Query(default=None, description="分析结束日期"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    基于利用率数据生成桌台调度建议。

    建议类型：
    - merge_suggestion: 低利用率桌台建议拼桌
    - close_suggestion: 低翻台率桌台建议关闭
    - time_limit_adjust: 用餐时长过长建议调整时限
    """
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    if not date_to:
        date_to = date.today()
    if not date_from:
        date_from = date_to - timedelta(days=7)

    days_count = max((date_to - date_from).days, 1)

    result = await db.execute(
        text("""
            SELECT
                table_id,
                zone_name,
                market_session_id,
                SUM(session_count)           AS total_sessions,
                AVG(avg_seat_utilization)     AS avg_seat_util,
                AVG(avg_duration_min)         AS avg_duration,
                AVG(avg_per_capita_fen)       AS avg_per_capita
            FROM mv_table_utilization
            WHERE store_id = :sid
              AND tenant_id = :tid
              AND biz_date BETWEEN :d_from AND :d_to
            GROUP BY table_id, zone_name, market_session_id
        """),
        {"sid": str(store_id), "tid": tid, "d_from": date_from, "d_to": date_to},
    )
    rows = result.fetchall()

    # 补充桌号
    table_nos: dict[str, str] = {}
    if rows:
        table_ids = list({str(r.table_id) for r in rows})
        tn_result = await db.execute(
            text("SELECT id, table_no FROM tables WHERE id = ANY(:ids)"),
            {"ids": table_ids},
        )
        for tn in tn_result.fetchall():
            table_nos[str(tn.id)] = tn.table_no

    # 补充市别名称
    session_names: dict[str, str] = {}
    if rows:
        ms_ids = list({str(r.market_session_id) for r in rows if r.market_session_id})
        if ms_ids:
            sn_result = await db.execute(
                text("SELECT id, name FROM store_market_sessions WHERE id = ANY(:ids)"),
                {"ids": ms_ids},
            )
            for sn in sn_result.fetchall():
                session_names[str(sn.id)] = sn.name

    recommendations: list[dict] = []

    for r in rows:
        tid_str = str(r.table_id)
        table_no = table_nos.get(tid_str, tid_str)
        ms_name = session_names.get(str(r.market_session_id), "")
        avg_util = float(r.avg_seat_util or 0)
        avg_dur = float(r.avg_duration or 0)
        total_sessions = int(r.total_sessions or 0)
        daily_sessions = total_sessions / days_count

        # 建议1：低座位利用率 → 拼桌
        if avg_util < _LOW_UTIL_THRESHOLD and total_sessions > 0:
            confidence = round(min(1.0, (_LOW_UTIL_THRESHOLD - avg_util) / _LOW_UTIL_THRESHOLD), 2)
            recommendations.append(
                {
                    "type": "merge_suggestion",
                    "table_no": table_no,
                    "market_session": ms_name,
                    "detail": (
                        f"{r.zone_name or '未分区'} {table_no} 在{ms_name}时段"
                        f"座位利用率仅 {avg_util:.0%}，建议与相邻桌合并或调整桌型"
                    ),
                    "confidence": confidence,
                    "metrics": {
                        "avg_seat_utilization": round(avg_util, 3),
                        "daily_sessions": round(daily_sessions, 1),
                    },
                }
            )

        # 建议2：低翻台率 → 关闭
        if daily_sessions < _LOW_SESSION_THRESHOLD and total_sessions > 0:
            confidence = round(
                min(1.0, (_LOW_SESSION_THRESHOLD - daily_sessions) / _LOW_SESSION_THRESHOLD),
                2,
            )
            recommendations.append(
                {
                    "type": "close_suggestion",
                    "table_no": table_no,
                    "market_session": ms_name,
                    "detail": (
                        f"{r.zone_name or '未分区'} {table_no} 在{ms_name}时段"
                        f"日均翻台仅 {daily_sessions:.1f} 次，建议该时段关闭此桌"
                    ),
                    "confidence": confidence,
                    "metrics": {
                        "daily_sessions": round(daily_sessions, 1),
                        "total_sessions": total_sessions,
                    },
                }
            )

        # 建议3：用餐时间过长 → 调整时限
        if avg_dur > _HIGH_DURATION_THRESHOLD and total_sessions > 0:
            confidence = round(
                min(1.0, (avg_dur - _HIGH_DURATION_THRESHOLD) / _HIGH_DURATION_THRESHOLD),
                2,
            )
            recommendations.append(
                {
                    "type": "time_limit_adjust",
                    "table_no": table_no,
                    "market_session": ms_name,
                    "detail": (
                        f"{r.zone_name or '未分区'} {table_no} 在{ms_name}时段"
                        f"平均用餐时长 {avg_dur:.0f} 分钟，建议设置 {int(avg_dur * 0.8)} 分钟时限"
                    ),
                    "confidence": confidence,
                    "metrics": {
                        "avg_duration_min": round(avg_dur, 1),
                        "suggested_limit_min": int(avg_dur * 0.8),
                    },
                }
            )

    # 按置信度降序排列
    recommendations.sort(key=lambda x: x["confidence"], reverse=True)

    return _ok(
        {
            "store_id": str(store_id),
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "recommendations": recommendations,
            "total": len(recommendations),
        }
    )


@router.post("/refresh", summary="手动刷新物化视图")
async def refresh_materialized_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    手动刷新 mv_table_utilization 物化视图。

    使用 CONCURRENTLY 刷新，不阻塞读取查询。
    需要唯一索引支持（idx_mv_tu_pk）。
    """
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    logger.info("mv_table_utilization_refresh_start", tenant_id=tid)

    await db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_table_utilization"))
    await db.commit()

    logger.info("mv_table_utilization_refresh_done", tenant_id=tid)
    return _ok({"refreshed": True, "view": "mv_table_utilization"})
