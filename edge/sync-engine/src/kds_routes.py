"""kds_routes.py — 边缘 KDS 增量同步 + 设备心跳 API

适用于 Mac mini 本地 PG（边缘），与 cloud tx-trade 的 KDS 路由独立。
边缘直接查询本地 PG，不依赖云端。

端点：
  GET  /api/v1/kds/orders/delta   — 轮询订单增量（cursor 分页）
  POST /api/v1/kds/device/heartbeat — 设备心跳注册/更新

所有端点要求 X-Tenant-ID header。
统一响应格式：{"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query, Request
from offline_sync_service import OfflineSyncService
from sqlalchemy import text

logger = structlog.get_logger()

router = APIRouter(prefix="/kds", tags=["kds"])

# ─── 常量 ──────────────────────────────────────────────────────────────────────

ALLOWED_DEVICE_KINDS = frozenset({"pos", "kds", "crew_phone", "tv_menu", "reception", "mac_mini"})
ALLOWED_HEALTH_STATUSES = frozenset({"healthy", "degraded", "offline", "unknown"})

# ─── 依赖 ──────────────────────────────────────────────────────────────────────


def _get_service(request: Request) -> OfflineSyncService:
    """从 app.state 获取已初始化的 OfflineSyncService 实例"""
    svc: OfflineSyncService | None = getattr(request.app.state, "offline_sync_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="OfflineSyncService not initialized")
    return svc


def _require_tenant(x_tenant_id: str | None) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return x_tenant_id


# ─── 辅助 ──────────────────────────────────────────────────────────────────────


def _iso(dt: Optional[datetime]) -> Optional[str]:
    """datetime → ISO8601 UTC 字符串（带 Z 后缀）"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ─── 端点 ──────────────────────────────────────────────────────────────────────


@router.get(
    "/orders/delta",
    summary="轮询 KDS 订单增量",
    description=(
        "返回 cursor 之后本地 PG 中新增或更新的 KDS 可见订单。"
        "cursor 为 ISO8601 时间戳，首次不传则返回最近 limit 条。"
    ),
)
async def get_orders_delta(
    store_id: str = Query(..., description="门店 UUID"),
    device_id: str = Query(..., description="设备 ID"),
    cursor: Optional[str] = Query(None, description="上一轮返回的 next_cursor；首次不传"),
    device_kind: str = Query("kds", description="终端类型"),
    limit: int = Query(100, ge=1, le=500),
    request: Request = None,  # type: ignore[assignment]
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    _ = _get_service(request)

    if device_kind not in ALLOWED_DEVICE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"device_kind 非法，允许值: {sorted(ALLOWED_DEVICE_KINDS)}",
        )

    # 解析 cursor
    cursor_dt: Optional[datetime] = None
    if cursor:
        try:
            s = cursor.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            cursor_dt = datetime.fromisoformat(s)
            if cursor_dt.tzinfo is None:
                cursor_dt = cursor_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"cursor 格式非法: {cursor}") from exc

    now = datetime.now(timezone.utc)

    # 从本地 PG 的 sync_checkpoints 或 offline_order_queue 获取订单数据
    # 边缘场景：查询 offline_order_queue 中的订单快照，作为 KDS 可读的订单列表
    orders: list[dict[str, Any]] = []

    svc = _get_service(request)
    try:
        async with svc._get_conn() as conn:
            # 先尝试从 offline_order_queue 查询已同步的订单
            # 按 created_offline_at 倒序取最近 limit 条
            result = await conn.execute(
                text("""
                    SELECT
                        id, tenant_id, store_id, local_order_id,
                        order_data, items_data, created_offline_at,
                        sync_status, synced_at
                    FROM offline_order_queue
                    WHERE tenant_id = :tenant_id
                      AND store_id = :store_id
                      AND (:cursor_ts IS NULL OR created_offline_at > :cursor_ts::timestamptz)
                    ORDER BY created_offline_at ASC
                    LIMIT :limit
                """),
                {
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "cursor_ts": cursor_dt,
                    "limit": limit,
                },
            )
            rows = result.mappings().all()

            for row in rows:
                order_data_raw = row.get("order_data") or {}
                # order_data 是 jsonb，已由 asyncpg 解码为 dict
                if isinstance(order_data_raw, str):
                    import json as _json
                    order_data_raw = _json.loads(order_data_raw)

                order_no = order_data_raw.get("order_no") or row.get("local_order_id", "")
                table_no = order_data_raw.get("table_number") or order_data_raw.get("table_no", "")
                items_raw = order_data_raw.get("items") or row.get("items_data") or []
                items_count = len(items_raw) if isinstance(items_raw, (list, tuple)) else 0

                # 映射为 KDSDeltaOrder 格式
                orders.append({
                    "tenant_id": str(row["tenant_id"]),
                    "id": str(row["id"]),
                    "order_no": order_no,
                    "store_id": str(row["store_id"]),
                    "status": _map_sync_status_to_kds(row.get("sync_status", "pending")),
                    "table_number": table_no or None,
                    "updated_at": _iso(row.get("synced_at") or row.get("created_offline_at")),
                    "items_count": items_count,
                })

    except Exception as exc:
        logger.error(
            "kds_routes.delta_query_error",
            tenant_id=tenant_id,
            store_id=store_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="DELTA_QUERY_ERROR") from exc

    next_cursor_val = orders[-1]["updated_at"] if orders else _iso(now)
    server_time = _iso(now)

    logger.info(
        "kds_routes.delta_ok",
        tenant_id=tenant_id,
        store_id=store_id,
        device_id=device_id,
        count=len(orders),
    )

    return {
        "ok": True,
        "data": {
            "orders": orders,
            "next_cursor": next_cursor_val,
            "server_time": server_time,
            "poll_interval_ms": 3000,
            "device_id": device_id,
            "device_kind": device_kind,
        },
    }


@router.post(
    "/device/heartbeat",
    summary="设备心跳上报",
    description=(
        "KDS / POS 等边缘设备定时上报心跳。"
        "首次上报创建记录，后续更新 last_seen_at 并递增 heartbeat_count。"
        "返回 server_time 用于客户端时钟校准，及建议的 poll_interval_ms。"
    ),
)
async def device_heartbeat(
    body: dict[str, Any],
    request: Request = None,  # type: ignore[assignment]
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)

    device_id = body.get("device_id", "")
    device_kind = body.get("device_kind", "")
    store_id = body.get("store_id", "")
    device_label = body.get("device_label")
    os_version = body.get("os_version")
    app_version = body.get("app_version")
    buffer_backlog = body.get("buffer_backlog", 0)
    health_status = body.get("health_status", "healthy")

    if not device_id or not store_id:
        raise HTTPException(status_code=400, detail="device_id 和 store_id 必填")
    if device_kind not in ALLOWED_DEVICE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"device_kind 非法，允许值: {sorted(ALLOWED_DEVICE_KINDS)}",
        )
    if health_status not in ALLOWED_HEALTH_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"health_status 非法，允许值: {sorted(ALLOWED_HEALTH_STATUSES)}",
        )

    svc = _get_service(request)
    now = datetime.now(timezone.utc)

    try:
        async with svc._get_conn() as conn:
            # 确保本地 PG 有 edge_device_registry 表（CREATE TABLE IF NOT EXISTS）
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS edge_device_registry (
                    tenant_id UUID NOT NULL,
                    device_id TEXT NOT NULL,
                    store_id UUID NOT NULL,
                    device_kind TEXT NOT NULL,
                    device_label TEXT NULL,
                    os_version TEXT NULL,
                    app_version TEXT NULL,
                    last_seen_at TIMESTAMPTZ NULL,
                    health_status TEXT NOT NULL DEFAULT 'unknown',
                    buffer_backlog INTEGER NOT NULL DEFAULT 0,
                    heartbeat_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT pk_edge_device_registry PRIMARY KEY (tenant_id, device_id)
                );
            """))

            # UPSERT 心跳
            await conn.execute(
                text("""
                    INSERT INTO edge_device_registry (
                        tenant_id, device_id, store_id, device_kind,
                        device_label, os_version, app_version,
                        last_seen_at, health_status, buffer_backlog,
                        heartbeat_count, created_at, updated_at
                    ) VALUES (
                        :tenant_id, :device_id, :store_id, :device_kind,
                        :device_label, :os_version, :app_version,
                        :last_seen_at, :health_status, :buffer_backlog,
                        1, :last_seen_at, :last_seen_at
                    )
                    ON CONFLICT (tenant_id, device_id) DO UPDATE SET
                        last_seen_at    = EXCLUDED.last_seen_at,
                        health_status   = EXCLUDED.health_status,
                        buffer_backlog  = EXCLUDED.buffer_backlog,
                        os_version      = COALESCE(EXCLUDED.os_version, edge_device_registry.os_version),
                        app_version     = COALESCE(EXCLUDED.app_version, edge_device_registry.app_version),
                        device_label    = COALESCE(EXCLUDED.device_label, edge_device_registry.device_label),
                        heartbeat_count = edge_device_registry.heartbeat_count + 1,
                        updated_at      = EXCLUDED.last_seen_at
                """),
                {
                    "tenant_id": tenant_id,
                    "device_id": device_id,
                    "store_id": store_id,
                    "device_kind": device_kind,
                    "device_label": device_label,
                    "os_version": os_version,
                    "app_version": app_version,
                    "last_seen_at": now,
                    "health_status": health_status,
                    "buffer_backlog": int(buffer_backlog),
                },
            )
    except Exception as exc:
        logger.error(
            "kds_routes.heartbeat_error",
            tenant_id=tenant_id,
            device_id=device_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="HEARTBEAT_ERROR") from exc

    # KDS 建议 30s 心跳间隔；其他设备 60s
    suggested_interval = 30000 if device_kind == "kds" else 60000

    logger.info(
        "kds_routes.heartbeat_ok",
        tenant_id=tenant_id,
        device_id=device_id,
        device_kind=device_kind,
        store_id=store_id,
    )

    return {
        "ok": True,
        "data": {
            "device_id": device_id,
            "device_kind": device_kind,
            "server_time": _iso(now),
            "poll_interval_ms": suggested_interval,
        },
    }


# ─── 内部工具 ──────────────────────────────────────────────────────────────────


def _map_sync_status_to_kds(sync_status: str) -> str:
    """将 offline_order_queue.sync_status 映射为 KDSDeltaOrder.status"""
    mapping = {
        "pending": "pending",
        "syncing": "preparing",
        "synced": "ready",
        "conflict": "confirmed",
    }
    return mapping.get(sync_status, "pending")

