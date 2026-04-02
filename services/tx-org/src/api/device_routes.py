"""设备管理 API 路由 — tx-org 品牌级设备总览

端点列表：
  GET  /api/v1/org/devices              品牌所有门店设备总览
  GET  /api/v1/org/devices/offline      离线设备告警列表（跨门店）
  GET  /api/v1/org/devices/stats        设备在线率统计（按门店/机型/版本）

业务规则：
  - 所有查询带 tenant_id 隔离（RLS + 显式 WHERE）
  - 离线判定：last_heartbeat_at < NOW() - 5分钟 AND status = 'online'
  - stats 返回：整体在线率、按门店分组、按机型分组、按App版本分组

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["org-devices"])

# 心跳超时阈值：5分钟
_HEARTBEAT_TIMEOUT_SECONDS = 5 * 60


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"ok": False, "data": None, "error": {"code": code, "message": message}},
    )


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise _err("MISSING_TENANT_ID", "X-Tenant-ID header required")
    return tid


# ── 端点实现 ──────────────────────────────────────────────────────────────────


@router.get("/api/v1/org/devices")
async def list_org_devices(
    request: Request,
    store_id: str | None = Query(None, description="按门店过滤（可选）"),
    device_type: str | None = Query(None, description="按设备类型过滤"),
    status: str | None = Query(None, description="按状态过滤: online/offline/maintenance"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/org/devices — 品牌所有门店设备总览

    支持按门店、设备类型、状态筛选，分页返回。
    用于总部运营人员查看全品牌设备分布与健康状态。
    """
    tenant_id = _get_tenant_id(request)
    offset = (page - 1) * size

    # 构建动态 WHERE 子句
    conditions = ["tenant_id = :tenant_id"]
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": size, "offset": offset}

    if store_id:
        conditions.append("store_id = :store_id::UUID")
        params["store_id"] = store_id
    if device_type:
        conditions.append("device_type = :device_type")
        params["device_type"] = device_type
    if status:
        conditions.append("status = :status")
        params["status"] = status

    where_clause = " AND ".join(conditions)

    try:
        result = await db.execute(
            text(f"""
                SELECT
                    device_id, tenant_id, store_id, device_type, device_name,
                    hardware_model, mac_address, ip_address,
                    app_version, os_version, status,
                    last_heartbeat_at, registered_at, created_at, updated_at
                FROM device_registry
                WHERE {where_clause}
                ORDER BY store_id, device_type, device_name
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.mappings().all()

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM device_registry WHERE {where_clause}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar_one()

    except (OSError, ConnectionError) as exc:
        log.error("org_devices_db_error", error=str(exc))
        raise _err("DB_ERROR", "数据库查询失败", 500) from exc

    items = [dict(r) for r in rows]

    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.get("/api/v1/org/devices/offline")
async def list_offline_devices(
    request: Request,
    store_id: str | None = Query(None, description="按门店过滤（可选，跨门店告警不传）"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/org/devices/offline — 离线设备告警列表（跨门店）

    离线判定：status = 'online' 但 last_heartbeat_at < NOW() - 5分钟。
    这些设备疑似网络断开或 App 崩溃，需要运维介入。
    """
    tenant_id = _get_tenant_id(request)
    offset = (page - 1) * size

    conditions = [
        "tenant_id = :tenant_id",
        "status = 'online'",
        "last_heartbeat_at < NOW() - INTERVAL '5 minutes'",
    ]
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": size, "offset": offset}

    if store_id:
        conditions.append("store_id = :store_id::UUID")
        params["store_id"] = store_id

    where_clause = " AND ".join(conditions)

    try:
        result = await db.execute(
            text(f"""
                SELECT
                    device_id, store_id, device_type, device_name,
                    hardware_model, ip_address, app_version,
                    last_heartbeat_at, registered_at,
                    EXTRACT(EPOCH FROM (NOW() - last_heartbeat_at))::INTEGER AS offline_seconds
                FROM device_registry
                WHERE {where_clause}
                ORDER BY last_heartbeat_at ASC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.mappings().all()

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM device_registry WHERE {where_clause}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar_one()

    except (OSError, ConnectionError) as exc:
        log.error("org_devices_offline_db_error", error=str(exc))
        raise _err("DB_ERROR", "数据库查询失败", 500) from exc

    items = [dict(r) for r in rows]

    log.info(
        "org_offline_devices_queried",
        tenant_id=tenant_id,
        store_id=store_id,
        offline_count=total,
    )

    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.get("/api/v1/org/devices/stats")
async def get_device_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/org/devices/stats — 设备在线率统计

    返回：
      - overall: 整体设备数与在线率
      - by_store: 按门店分组的在线率
      - by_hardware_model: 按硬件型号分组的在线率
      - by_app_version: 按 App 版本分组的设备分布

    离线判定同 /offline 端点：status='online' 但心跳超过5分钟。
    """
    tenant_id = _get_tenant_id(request)
    params: dict[str, Any] = {"tenant_id": tenant_id}

    try:
        # 整体统计
        overall_result = await db.execute(
            text("""
                SELECT
                    COUNT(*)                                                      AS total_devices,
                    COUNT(*) FILTER (WHERE status = 'online')                    AS status_online,
                    COUNT(*) FILTER (WHERE status = 'offline')                   AS status_offline,
                    COUNT(*) FILTER (WHERE status = 'maintenance')               AS status_maintenance,
                    COUNT(*) FILTER (
                        WHERE status = 'online'
                          AND (
                              last_heartbeat_at IS NULL
                              OR last_heartbeat_at < NOW() - INTERVAL '5 minutes'
                          )
                    )                                                             AS stale_count,
                    ROUND(
                        100.0 * COUNT(*) FILTER (
                            WHERE status = 'online'
                              AND last_heartbeat_at >= NOW() - INTERVAL '5 minutes'
                        ) / NULLIF(COUNT(*), 0),
                        2
                    )                                                             AS online_rate_pct
                FROM device_registry
                WHERE tenant_id = :tenant_id
            """),
            params,
        )
        overall_row = overall_result.mappings().one()

        # 按门店分组
        by_store_result = await db.execute(
            text("""
                SELECT
                    store_id::TEXT,
                    COUNT(*)                                                   AS total,
                    COUNT(*) FILTER (
                        WHERE status = 'online'
                          AND last_heartbeat_at >= NOW() - INTERVAL '5 minutes'
                    )                                                          AS online,
                    COUNT(*) FILTER (
                        WHERE status = 'online'
                          AND (
                              last_heartbeat_at IS NULL
                              OR last_heartbeat_at < NOW() - INTERVAL '5 minutes'
                          )
                    )                                                          AS stale,
                    ROUND(
                        100.0 * COUNT(*) FILTER (
                            WHERE status = 'online'
                              AND last_heartbeat_at >= NOW() - INTERVAL '5 minutes'
                        ) / NULLIF(COUNT(*), 0),
                        2
                    )                                                          AS online_rate_pct
                FROM device_registry
                WHERE tenant_id = :tenant_id
                GROUP BY store_id
                ORDER BY online_rate_pct ASC NULLS LAST
            """),
            params,
        )
        by_store = [dict(r) for r in by_store_result.mappings().all()]

        # 按硬件型号分组
        by_model_result = await db.execute(
            text("""
                SELECT
                    COALESCE(hardware_model, '未知型号')                        AS hardware_model,
                    COUNT(*)                                                   AS total,
                    COUNT(*) FILTER (
                        WHERE status = 'online'
                          AND last_heartbeat_at >= NOW() - INTERVAL '5 minutes'
                    )                                                          AS online,
                    ROUND(
                        100.0 * COUNT(*) FILTER (
                            WHERE status = 'online'
                              AND last_heartbeat_at >= NOW() - INTERVAL '5 minutes'
                        ) / NULLIF(COUNT(*), 0),
                        2
                    )                                                          AS online_rate_pct
                FROM device_registry
                WHERE tenant_id = :tenant_id
                GROUP BY hardware_model
                ORDER BY total DESC
            """),
            params,
        )
        by_model = [dict(r) for r in by_model_result.mappings().all()]

        # 按 App 版本分组
        by_version_result = await db.execute(
            text("""
                SELECT
                    COALESCE(app_version, '未知版本')  AS app_version,
                    COUNT(*)                          AS device_count,
                    device_type
                FROM device_registry
                WHERE tenant_id = :tenant_id
                GROUP BY app_version, device_type
                ORDER BY device_count DESC
            """),
            params,
        )
        by_version = [dict(r) for r in by_version_result.mappings().all()]

    except (OSError, ConnectionError) as exc:
        log.error("org_devices_stats_db_error", error=str(exc))
        raise _err("DB_ERROR", "数据库查询失败", 500) from exc

    return _ok({
        "overall": dict(overall_row),
        "by_store": by_store,
        "by_hardware_model": by_model,
        "by_app_version": by_version,
    })
