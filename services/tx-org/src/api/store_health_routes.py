"""门店级监控 — 健康概览 API（Task 2.4）

提供门店维度的运维健康总览：
  - 设备在线率（POS/KDS/打印机/员工手机）
  - 服务连通性（MacStation / CoreML / Cloud）
  - KDS积压 / 打印机缺纸 / 网络延迟
  - 日结状态 / 支付回调成功率

与现有 device_routes 互补：device_routes 管理单个设备，
本模块提供门店聚合视图。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Path, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/store-health", tags=["store_health"])


async def _get_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── 模型 ──────────────────────────────────────────────────────────────


async def _get_device_health(db: AsyncSession, store_id: str, tenant_uuid: uuid.UUID) -> Dict[str, Any]:
    """查询门店设备健康状态"""
    sid = uuid.UUID(store_id)
    result = await db.execute(
        text("""
            SELECT device_kind, health_status, COUNT(*) AS cnt
            FROM devices
            WHERE store_id = :sid AND tenant_id = :tid
            GROUP BY device_kind, health_status
            ORDER BY device_kind, health_status
        """),
        {"sid": sid, "tid": tenant_uuid},
    )
    rows = result.fetchall()
    kinds: Dict[str, Dict[str, int]] = {}
    for r in rows:
        kind = r.device_kind or "unknown"
        status = r.health_status or "unknown"
        if kind not in kinds:
            kinds[kind] = {}
        kinds[kind][status] = r.cnt

    total_online = sum(
        s.get("healthy", 0) + s.get("degraded", 0)
        for s in kinds.values()
    )
    total_devices = sum(sum(s.values()) for s in kinds.values())
    online_rate = round(total_online / total_devices * 100, 1) if total_devices > 0 else 0.0

    return {
        "total_devices": total_devices,
        "online_devices": total_online,
        "online_rate_pct": online_rate,
        "by_kind": kinds,
    }


async def _get_printer_health(db: AsyncSession, store_id: str, tenant_uuid: uuid.UUID) -> Dict[str, Any]:
    """查询打印机状态"""
    sid = uuid.UUID(store_id)
    result = await db.execute(
        text("""
            SELECT status, COUNT(*) AS cnt
            FROM printers
            WHERE store_id = :sid AND tenant_id = :tid AND is_deleted = FALSE
            GROUP BY status
        """),
        {"sid": sid, "tid": tenant_uuid},
    )
    rows = result.fetchall()
    status_map = {r.status: r.cnt for r in rows}
    return {
        "total": sum(status_map.values()),
        "online": status_map.get("online", 0),
        "offline": status_map.get("offline", 0),
        "paper_low": status_map.get("paper_low", 0),
        "error": status_map.get("error", 0),
    }


async def _get_kds_backlog(db: AsyncSession, store_id: str, tenant_uuid: uuid.UUID) -> Dict[str, Any]:
    """查询 KDS 积压情况"""
    sid = uuid.UUID(store_id)
    result = await db.execute(
        text("""
            SELECT dept_id, COUNT(*) AS pending_count,
                   MAX(EXTRACT(EPOCH FROM (NOW() - created_at)))::INT AS max_wait_sec
            FROM kds_tasks
            WHERE store_id = :sid AND tenant_id = :tid
              AND status IN ('pending', 'cooking')
              AND created_at > NOW() - INTERVAL '4 hours'
            GROUP BY dept_id
            ORDER BY pending_count DESC
        """),
        {"sid": sid, "tid": tenant_uuid},
    )
    dept_backlogs = [
        {
            "dept_id": str(r.dept_id) if r.dept_id else None,
            "pending_count": r.pending_count,
            "max_wait_sec": r.max_wait_sec or 0,
        }
        for r in result.fetchall()
    ]
    total_pending = sum(d["pending_count"] for d in dept_backlogs)
    return {
        "total_pending": total_pending,
        "by_dept": dept_backlogs,
        "alert": total_pending > 20,  # 积压 > 20 单触发告警
    }


async def _get_daily_settlement_status(
    db: AsyncSession, store_id: str, tenant_uuid: uuid.UUID
) -> Dict[str, Any]:
    """查询最近日结状态"""
    sid = uuid.UUID(store_id)
    result = await db.execute(
        text("""
            SELECT settlement_date, status, completed_at
            FROM daily_settlements
            WHERE store_id = :sid AND tenant_id = :tid
            ORDER BY settlement_date DESC
            LIMIT 7
        """),
        {"sid": sid, "tid": tenant_uuid},
    )
    rows = result.fetchall()
    recent = [
        {
            "date": str(r.settlement_date),
            "status": r.status,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in rows
    ]
    # 是否有超过 1 天未日结
    today = datetime.now(timezone.utc).date()
    has_overdue = all(
        str(r.settlement_date) != str(today) for r in rows
    ) if rows else True

    return {
        "recent_7_days": recent,
        "today_settled": not has_overdue,
        "overdue_alert": has_overdue,
    }


async def _get_sync_status(db: AsyncSession, store_id: str) -> Dict[str, Any]:
    """查询 Mac mini 数据同步状态"""
    sid = uuid.UUID(store_id)
    result = await db.execute(
        text("""
            SELECT last_sync_at, sync_lag_sec, sync_status
            FROM edge_sync_status
            WHERE store_id = :sid
            ORDER BY last_sync_at DESC
            LIMIT 1
        """),
        {"sid": sid},
    )
    r = result.fetchone()
    if not r:
        return {"synced": False, "reason": "no_sync_record"}
    return {
        "synced": r.sync_status == "ok",
        "last_sync_at": r.last_sync_at.isoformat() if r.last_sync_at else None,
        "sync_lag_sec": r.sync_lag_sec or 0,
        "status": r.sync_status,
        "alert": (r.sync_lag_sec or 0) > 600,  # 延迟 > 10min 告警
    }


# ── 端点 ───────────────────────────────────────────────────────────────


@router.get("/overview/{store_id}", summary="门店健康总览")
async def store_health_overview(
    store_id: str = Path(..., description="门店 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """返回门店运维健康总览，包含设备/打印机/KDS/日结/同步 5 维度。

    用于：DemoMonitor 页面、门店上线验收、日常运维监控。
    """
    tenant_uuid = uuid.UUID(x_tenant_id)

    # 验证门店存在
    store_result = await db.execute(
        text("SELECT id, store_name, status FROM stores WHERE id = :sid AND tenant_id = :tid"),
        {"sid": uuid.UUID(store_id), "tid": tenant_uuid},
    )
    store_row = store_result.fetchone()
    if not store_row:
        raise HTTPException(status_code=404, detail=f"门店不存在: {store_id}")

    # 并行查询各维度（FastAPI 不支持 asyncio.gather 跨 DB session，串行执行）
    devices = await _get_device_health(db, store_id, tenant_uuid)
    printers = await _get_printer_health(db, store_id, tenant_uuid)
    kds = await _get_kds_backlog(db, store_id, tenant_uuid)
    settlement = await _get_daily_settlement_status(db, store_id, tenant_uuid)
    sync = await _get_sync_status(db, store_id)

    # 计算综合健康分（0-100）
    scores = [
        devices["online_rate_pct"],  # 设备在线率
        100.0 if printers["error"] == 0 and printers["offline"] == 0 else 70.0,
        100.0 if not kds["alert"] else 50.0,
        100.0 if not settlement["overdue_alert"] else 40.0,
        100.0 if not sync.get("alert", True) else 60.0,
    ]
    health_score = round(sum(scores) / len(scores), 1)

    alerts = []
    if devices["online_rate_pct"] < 90:
        alerts.append(f"设备在线率 {devices['online_rate_pct']}% 低于 90%")
    if printers["error"] > 0:
        alerts.append(f"{printers['error']} 台打印机异常")
    if printers["paper_low"] > 0:
        alerts.append(f"{printers['paper_low']} 台打印机缺纸")
    if kds["alert"]:
        alerts.append(f"KDS 积压 {kds['total_pending']} 单")
    if settlement["overdue_alert"]:
        alerts.append("今日未日结")
    if sync.get("alert", False):
        alerts.append(f"数据同步延迟 {sync.get('sync_lag_sec', 0)}s")

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "store_name": store_row.store_name,
            "store_status": store_row.status,
            "health_score": health_score,
            "health_status": (
                "healthy" if health_score >= 90
                else "degraded" if health_score >= 70
                else "critical"
            ),
            "alerts": alerts,
            "dimensions": {
                "devices": devices,
                "printers": printers,
                "kds_backlog": kds,
                "daily_settlement": settlement,
                "sync": sync,
            },
        },
    }


@router.get("/alerts", summary="门店告警列表")
async def store_alerts(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """列出当前租户所有门店的告警（健康分 < 90 的门店）"""
    tenant_uuid = uuid.UUID(x_tenant_id)

    # 查询所有活跃门店
    result = await db.execute(
        text("""
            SELECT id, store_name, status FROM stores
            WHERE tenant_id = :tid AND status = 'active' AND is_deleted = FALSE
        """),
        {"tid": tenant_uuid},
    )
    stores = result.fetchall()

    alert_stores = []
    for store in stores:
        store_id_str = str(store.id)
        try:
            devices = await _get_device_health(db, store_id_str, tenant_uuid)
            settlement = await _get_daily_settlement_status(db, store_id_str, tenant_uuid)
            sync = await _get_sync_status(db, store_id_str)

            scores = [
                devices["online_rate_pct"],
                100.0 if not settlement["overdue_alert"] else 40.0,
                100.0 if not sync.get("alert", True) else 60.0,
            ]
            health_score = round(sum(scores) / len(scores), 1)
            if health_score < 90:
                alert_stores.append({
                    "store_id": store_id_str,
                    "store_name": store.store_name,
                    "health_score": health_score,
                    "device_online_rate": devices["online_rate_pct"],
                    "today_settled": not settlement["overdue_alert"],
                    "sync_ok": not sync.get("alert", True),
                })
        except Exception:
            logger.warning("store_alert_query_failed", store_id=store_id_str, exc_info=True)

    # 分页
    total = len(alert_stores)
    start = (page - 1) * size
    end = start + size
    return {
        "ok": True,
        "data": {
            "items": alert_stores[start:end],
            "total": total,
            "page": page,
            "size": size,
        },
    }
