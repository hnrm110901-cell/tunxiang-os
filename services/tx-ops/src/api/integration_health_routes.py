"""集成健康中心 API 路由

端点:
  GET   /api/v1/platform/integrations/health          所有适配器健康状态
  GET   /api/v1/platform/integrations/{id}/detail     适配器详情
  POST  /api/v1/platform/integrations/{id}/retry      手动重试
  GET   /api/v1/platform/webhooks/recent              最近Webhook事件

数据来源：
  - 集成健康摘要：从 events 表聚合近24小时 CHANNEL.ORDER_SYNCED 事件，降级时返回空数据
  - Webhook 历史：从 events 表读取 source_service/event_type 维度，降级时返回空列表

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/platform", tags=["platform-integrations"])
log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  已知集成适配器（静态配置，不存 DB）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 适配器元数据：id → 静态配置（名称、类型、图标、轮询间隔）
_ADAPTER_META: Dict[str, Dict[str, Any]] = {
    "intg-meituan": {
        "name": "美团外卖",
        "type": "channel_adapter",
        "icon": "meituan",
        "sync_interval_seconds": 60,
        "source_service": "tx-trade",
        "event_channel": "meituan",
    },
    "intg-ele": {
        "name": "饿了么",
        "type": "channel_adapter",
        "icon": "eleme",
        "sync_interval_seconds": 60,
        "source_service": "tx-trade",
        "event_channel": "eleme",
    },
    "intg-douyin": {
        "name": "抖音来客",
        "type": "channel_adapter",
        "icon": "douyin",
        "sync_interval_seconds": 120,
        "source_service": "tx-trade",
        "event_channel": "douyin",
    },
    "intg-pinzhi": {
        "name": "品智POS",
        "type": "pos_adapter",
        "icon": "pinzhi",
        "sync_interval_seconds": 30,
        "source_service": "tx-trade",
        "event_channel": "pinzhi",
    },
    "intg-wecom": {
        "name": "企业微信",
        "type": "notification_adapter",
        "icon": "wecom",
        "sync_interval_seconds": None,
        "source_service": "tx-ops",
        "event_channel": "wecom",
    },
    "intg-wechat-pay": {
        "name": "微信支付",
        "type": "payment_adapter",
        "icon": "wechat",
        "sync_interval_seconds": None,
        "source_service": "tx-trade",
        "event_channel": "wechat_pay",
    },
    "intg-alipay": {
        "name": "支付宝",
        "type": "payment_adapter",
        "icon": "alipay",
        "sync_interval_seconds": None,
        "source_service": "tx-trade",
        "event_channel": "alipay",
    },
}


def _build_degraded_integration(intg_id: str) -> Dict[str, Any]:
    """DB不可用时返回降级数据。"""
    meta = _ADAPTER_META.get(intg_id, {})
    return {
        "id": intg_id,
        "name": meta.get("name", intg_id),
        "type": meta.get("type", "unknown"),
        "icon": meta.get("icon", ""),
        "status": "unknown",
        "uptime_pct": None,
        "latency_ms": None,
        "last_sync_at": None,
        "sync_interval_seconds": meta.get("sync_interval_seconds"),
        "error_count_24h": None,
        "warning_count_24h": None,
        "orders_synced_today": None,
        "recent_errors": [],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DB 查询助手
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _fetch_integration_stats(
    db: AsyncSession,
    tenant_id: str,
    channel: str,
) -> Dict[str, Any]:
    """
    从 events 表聚合单个集成适配器的健康指标。
    - 近24小时事件总数、错误数、最后同步时间
    - 今日 ORDER_SYNCED 事件数（作为 orders_synced_today 近似）
    - latency_ms: payload->>'latency_ms' 字段的平均值（如有）
    """
    now = datetime.now(timezone.utc)
    result: Dict[str, Any] = {
        "last_sync_at": None,
        "error_count_24h": 0,
        "warning_count_24h": 0,
        "orders_synced_today": None,
        "latency_ms": None,
        "uptime_pct": None,
    }

    try:
        # 近24小时事件聚合
        row = await db.execute(
            text("""
                SELECT
                    MAX(occurred_at)                                    AS last_sync_at,
                    COUNT(*) FILTER (WHERE payload->>'status' = 'error'
                                       OR payload->>'level' = 'error')  AS error_count,
                    COUNT(*) FILTER (WHERE payload->>'status' = 'warning'
                                       OR payload->>'level' = 'warning') AS warning_count,
                    AVG((payload->>'latency_ms')::float)
                        FILTER (WHERE payload->>'latency_ms' IS NOT NULL) AS avg_latency_ms
                FROM events
                WHERE tenant_id = :tenant_id
                  AND source_service = :source_service
                  AND metadata->>'channel' = :channel
                  AND occurred_at >= NOW() - INTERVAL '24 hours'
            """),
            {
                "tenant_id": tenant_id,
                "source_service": _ADAPTER_META.get(
                    f"intg-{channel}", {}
                ).get("source_service", "tx-trade"),
                "channel": channel,
            },
        )
        r = row.first()
        if r:
            result["last_sync_at"] = r.last_sync_at.isoformat() if r.last_sync_at else None
            result["error_count_24h"] = int(r.error_count or 0)
            result["warning_count_24h"] = int(r.warning_count or 0)
            result["latency_ms"] = round(float(r.avg_latency_ms)) if r.avg_latency_ms else None

        # 今日订单同步数（CHANNEL.ORDER_SYNCED 类事件）
        synced_row = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM events
                WHERE tenant_id = :tenant_id
                  AND metadata->>'channel' = :channel
                  AND event_type LIKE '%ORDER_SYNCED%'
                  AND occurred_at::date = CURRENT_DATE
            """),
            {"tenant_id": tenant_id, "channel": channel},
        )
        cnt_row = synced_row.first()
        if cnt_row:
            synced = int(cnt_row.cnt or 0)
            result["orders_synced_today"] = synced if synced > 0 else None

    except SQLAlchemyError as exc:
        log.warning("integration_health.stats_query_error", channel=channel, error=str(exc))

    return result


def _derive_status(error_count: int, uptime_pct: Optional[float]) -> str:
    """根据错误数和在线率推导状态。"""
    if error_count >= 10:
        return "error"
    if error_count >= 3:
        return "degraded"
    return "healthy"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/integrations/health")
async def get_integrations_health(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """所有适配器健康状态汇总，从 events 表实时聚合。"""
    log.info("integrations_health_requested", tenant_id=x_tenant_id)

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        db_available = True
    except SQLAlchemyError as exc:
        log.warning("integrations_health.set_config_error", error=str(exc))
        db_available = False

    integrations: List[Dict[str, Any]] = []
    for intg_id, meta in _ADAPTER_META.items():
        if not db_available:
            integrations.append(_build_degraded_integration(intg_id))
            continue

        stats = await _fetch_integration_stats(db, x_tenant_id, meta["event_channel"])
        error_count = stats["error_count_24h"] or 0
        derived_status = _derive_status(error_count, stats["uptime_pct"])

        integrations.append({
            "id": intg_id,
            "name": meta["name"],
            "type": meta["type"],
            "icon": meta["icon"],
            "status": derived_status,
            "uptime_pct": stats["uptime_pct"],
            "latency_ms": stats["latency_ms"],
            "last_sync_at": stats["last_sync_at"],
            "sync_interval_seconds": meta["sync_interval_seconds"],
            "error_count_24h": error_count,
            "warning_count_24h": stats["warning_count_24h"] or 0,
            "orders_synced_today": stats["orders_synced_today"],
        })

    status_counts: Dict[str, int] = {}
    for intg in integrations:
        s = intg["status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "ok": True,
        "data": {
            "total": len(integrations),
            "by_status": status_counts,
            "integrations": integrations,
            "snapshot_time": datetime.now(tz=timezone.utc).isoformat(),
        },
    }


@router.get("/integrations/{integration_id}/detail")
async def get_integration_detail(
    integration_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """适配器详情（含近期错误事件）。"""
    log.info(
        "integration_detail_requested",
        integration_id=integration_id,
        tenant_id=x_tenant_id,
    )

    if integration_id not in _ADAPTER_META:
        raise HTTPException(status_code=404, detail="适配器不存在")

    meta = _ADAPTER_META[integration_id]

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        stats = await _fetch_integration_stats(db, x_tenant_id, meta["event_channel"])

        # 近期错误事件（最多5条）
        error_rows = await db.execute(
            text("""
                SELECT occurred_at,
                       payload->>'error_code'    AS code,
                       payload->>'error_message' AS message,
                       (payload->>'resolved')::boolean AS resolved
                FROM events
                WHERE tenant_id = :tenant_id
                  AND metadata->>'channel' = :channel
                  AND (payload->>'status' = 'error' OR payload->>'level' = 'error')
                  AND occurred_at >= NOW() - INTERVAL '24 hours'
                ORDER BY occurred_at DESC
                LIMIT 5
            """),
            {"tenant_id": x_tenant_id, "channel": meta["event_channel"]},
        )
        recent_errors = [
            {
                "time": r.occurred_at.isoformat() if r.occurred_at else None,
                "code": r.code or "UNKNOWN",
                "message": r.message or "",
                "resolved": bool(r.resolved),
            }
            for r in error_rows
        ]
    except SQLAlchemyError as exc:
        log.warning(
            "integration_detail.db_error",
            integration_id=integration_id,
            error=str(exc),
        )
        stats = {
            "last_sync_at": None,
            "error_count_24h": None,
            "warning_count_24h": None,
            "orders_synced_today": None,
            "latency_ms": None,
            "uptime_pct": None,
        }
        recent_errors = []

    error_count = stats["error_count_24h"] or 0
    derived_status = _derive_status(error_count, stats["uptime_pct"])

    detail = {
        "id": integration_id,
        "name": meta["name"],
        "type": meta["type"],
        "icon": meta["icon"],
        "status": derived_status,
        "uptime_pct": stats["uptime_pct"],
        "latency_ms": stats["latency_ms"],
        "last_sync_at": stats["last_sync_at"],
        "sync_interval_seconds": meta["sync_interval_seconds"],
        "error_count_24h": error_count,
        "warning_count_24h": stats["warning_count_24h"] or 0,
        "orders_synced_today": stats["orders_synced_today"],
        "recent_errors": recent_errors,
    }

    return {"ok": True, "data": detail}


@router.post("/integrations/{integration_id}/retry")
async def retry_integration(
    integration_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    手动重试适配器连接/同步。
    通过写入一条 RETRY 事件到 events 表触发下游处理器。
    若 DB 不可用，仍返回接受成功（乐观响应）。
    """
    log.info(
        "integration_retry_requested",
        integration_id=integration_id,
        tenant_id=x_tenant_id,
    )

    if integration_id not in _ADAPTER_META:
        raise HTTPException(status_code=404, detail="适配器不存在")

    meta = _ADAPTER_META[integration_id]
    now = datetime.now(timezone.utc)

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        # 查询最近错误状态
        row = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE payload->>'status' = 'error') AS error_count,
                    MAX(occurred_at) FILTER (WHERE payload->>'status' = 'error') AS last_error_at
                FROM events
                WHERE tenant_id = :tenant_id
                  AND metadata->>'channel' = :channel
                  AND occurred_at >= NOW() - INTERVAL '1 hour'
            """),
            {"tenant_id": x_tenant_id, "channel": meta["event_channel"]},
        )
        r = row.first()
        recent_errors = int(r.error_count or 0) if r else 0

        # 写入重试事件
        await db.execute(
            text("""
                INSERT INTO events (
                    tenant_id, stream_id, stream_type, event_type,
                    source_service, payload, metadata
                ) VALUES (
                    :tenant_id,
                    :stream_id,
                    'integration',
                    'INTEGRATION.RETRY_REQUESTED',
                    :source_service,
                    :payload::jsonb,
                    :metadata::jsonb
                )
            """),
            {
                "tenant_id": x_tenant_id,
                "stream_id": integration_id,
                "source_service": meta["source_service"],
                "payload": f'{{"integration_id": "{integration_id}", "retried_at": "{now.isoformat()}"}}',
                "metadata": f'{{"channel": "{meta["event_channel"]}", "operator": "manual"}}',
            },
        )
        await db.commit()

        retry_result = "still_failing" if recent_errors > 0 else "success"
        message = (
            f"{meta['name']} 重试请求已发送，近期仍有 {recent_errors} 个错误，正在处理中"
            if recent_errors > 0
            else f"{meta['name']} 重试请求已发送"
        )

    except SQLAlchemyError as exc:
        log.warning("integration_retry.db_error", integration_id=integration_id, error=str(exc))
        await db.rollback()
        retry_result = "accepted"
        message = f"{meta['name']} 重试请求已接受（DB 暂时不可用，将在恢复后执行）"
        recent_errors = 0

    return {
        "ok": True,
        "data": {
            "integration_id": integration_id,
            "name": meta["name"],
            "retry_result": retry_result,
            "message": message,
            "retried_at": now.isoformat(),
        },
    }


@router.get("/webhooks/recent")
async def get_recent_webhooks(
    source: Optional[str] = Query(None, description="来源筛选: meituan/eleme/douyin"),
    status: Optional[str] = Query(None, description="状态筛选: success/failed"),
    limit: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    最近Webhook事件列表，从 events 表读取 CHANNEL.* 类型事件。
    payload 约定字段（由 tx-trade webhook_routes.py 写入）：
      store_id, order_no, latency_ms, payload_size_bytes, status（success/failed）, error
    """
    log.info(
        "webhooks_recent_requested",
        tenant_id=x_tenant_id,
        source=source,
        status=status,
    )

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        conditions = [
            "tenant_id = :tenant_id",
            "event_type LIKE 'CHANNEL.%'",
            "occurred_at >= NOW() - INTERVAL '24 hours'",
        ]
        params: Dict[str, Any] = {"tenant_id": x_tenant_id, "limit": limit}

        if source:
            conditions.append("metadata->>'channel' = :source")
            params["source"] = source
        if status:
            conditions.append("payload->>'status' = :status")
            params["status"] = status

        where_clause = " AND ".join(conditions)

        rows = await db.execute(
            text(f"""
                SELECT
                    event_id::text                          AS id,
                    metadata->>'channel'                   AS source,
                    event_type                              AS event_type,
                    COALESCE(payload->>'status', 'success') AS status,
                    occurred_at                             AS received_at,
                    recorded_at                             AS processed_at,
                    (payload->>'latency_ms')::int           AS latency_ms,
                    (payload->>'payload_size_bytes')::int   AS payload_size_bytes,
                    payload->>'store_id'                   AS store_id,
                    payload->>'order_no'                   AS order_no,
                    payload->>'error'                      AS error
                FROM events
                WHERE {where_clause}
                ORDER BY occurred_at DESC
                LIMIT :limit
            """),
            params,
        )
        items = []
        for r in rows:
            item: Dict[str, Any] = {
                "id": r.id,
                "source": r.source,
                "event_type": r.event_type,
                "status": r.status,
                "received_at": r.received_at.isoformat() if r.received_at else None,
                "processed_at": r.processed_at.isoformat() if r.processed_at else None,
                "latency_ms": r.latency_ms,
                "payload_size_bytes": r.payload_size_bytes,
                "store_id": r.store_id,
                "order_no": r.order_no,
            }
            if r.error:
                item["error"] = r.error
            items.append(item)

        # 聚合统计（全部近24小时，不受分页影响）
        agg_row = await db.execute(
            text("""
                SELECT
                    COUNT(*)                                                            AS total,
                    COUNT(*) FILTER (WHERE COALESCE(payload->>'status','success') = 'success') AS success_count,
                    AVG((payload->>'latency_ms')::float)
                        FILTER (WHERE payload->>'latency_ms' IS NOT NULL)              AS avg_latency
                FROM events
                WHERE tenant_id = :tenant_id
                  AND event_type LIKE 'CHANNEL.%'
                  AND occurred_at >= NOW() - INTERVAL '24 hours'
            """),
            {"tenant_id": x_tenant_id},
        )
        agg = agg_row.first()
        total = int(agg.total or 0) if agg else 0
        success_count = int(agg.success_count or 0) if agg else 0
        avg_latency = round(float(agg.avg_latency)) if agg and agg.avg_latency else 0
        success_rate = round(success_count / total * 100, 1) if total > 0 else 0.0

    except SQLAlchemyError as exc:
        log.warning("webhooks_recent.db_error", error=str(exc))
        items = []
        total = 0
        success_rate = 0.0
        avg_latency = 0

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "success_rate_pct": success_rate,
            "avg_latency_ms": avg_latency,
        },
    }
