"""集成健康中心 API 路由（Mock 数据版）

端点:
  GET   /api/v1/platform/integrations/health          所有适配器健康状态
  GET   /api/v1/platform/integrations/{id}/detail     适配器详情
  POST  /api/v1/platform/integrations/{id}/retry      手动重试
  GET   /api/v1/platform/webhooks/recent              最近Webhook事件

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/platform", tags=["platform-integrations"])
log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Mock 数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MOCK_INTEGRATIONS: List[Dict[str, Any]] = [
    {
        "id": "intg-meituan",
        "name": "美团外卖",
        "type": "channel_adapter",
        "icon": "meituan",
        "status": "healthy",
        "uptime_pct": 99.95,
        "latency_ms": 120,
        "last_sync_at": "2026-04-10T15:28:00+08:00",
        "sync_interval_seconds": 60,
        "error_count_24h": 2,
        "warning_count_24h": 5,
        "orders_synced_today": 86,
        "config": {
            "app_key": "mt_****8821",
            "webhook_url": "https://api.tunxiang.com/webhooks/meituan",
            "stores_bound": 10,
        },
        "recent_errors": [
            {"time": "2026-04-10T02:15:00+08:00", "code": "TIMEOUT", "message": "美团API响应超时(>5s)", "resolved": True},
            {"time": "2026-04-09T23:42:00+08:00", "code": "RATE_LIMIT", "message": "接口限流，等待重试", "resolved": True},
        ],
    },
    {
        "id": "intg-ele",
        "name": "饿了么",
        "type": "channel_adapter",
        "icon": "eleme",
        "status": "healthy",
        "uptime_pct": 99.88,
        "latency_ms": 95,
        "last_sync_at": "2026-04-10T15:27:30+08:00",
        "sync_interval_seconds": 60,
        "error_count_24h": 0,
        "warning_count_24h": 1,
        "orders_synced_today": 52,
        "config": {
            "app_key": "ele_****3356",
            "webhook_url": "https://api.tunxiang.com/webhooks/eleme",
            "stores_bound": 8,
        },
        "recent_errors": [],
    },
    {
        "id": "intg-douyin",
        "name": "抖音来客",
        "type": "channel_adapter",
        "icon": "douyin",
        "status": "degraded",
        "uptime_pct": 97.2,
        "latency_ms": 350,
        "last_sync_at": "2026-04-10T15:20:00+08:00",
        "sync_interval_seconds": 120,
        "error_count_24h": 8,
        "warning_count_24h": 15,
        "orders_synced_today": 37,
        "config": {
            "app_key": "dy_****7790",
            "webhook_url": "https://api.tunxiang.com/webhooks/douyin",
            "stores_bound": 6,
        },
        "recent_errors": [
            {"time": "2026-04-10T15:10:00+08:00", "code": "API_ERROR", "message": "抖音核销接口返回500", "resolved": False},
            {"time": "2026-04-10T14:55:00+08:00", "code": "TIMEOUT", "message": "接口响应超时(>10s)", "resolved": True},
            {"time": "2026-04-10T14:30:00+08:00", "code": "API_ERROR", "message": "券码核销失败: COUPON_EXPIRED", "resolved": True},
        ],
    },
    {
        "id": "intg-pinzhi",
        "name": "品智POS",
        "type": "pos_adapter",
        "icon": "pinzhi",
        "status": "healthy",
        "uptime_pct": 99.99,
        "latency_ms": 45,
        "last_sync_at": "2026-04-10T15:29:00+08:00",
        "sync_interval_seconds": 30,
        "error_count_24h": 0,
        "warning_count_24h": 0,
        "orders_synced_today": 312,
        "config": {
            "api_version": "v3.2",
            "stores_bound": 12,
        },
        "recent_errors": [],
    },
    {
        "id": "intg-wecom",
        "name": "企业微信",
        "type": "notification_adapter",
        "icon": "wecom",
        "status": "healthy",
        "uptime_pct": 99.97,
        "latency_ms": 80,
        "last_sync_at": "2026-04-10T15:25:00+08:00",
        "sync_interval_seconds": None,
        "error_count_24h": 0,
        "warning_count_24h": 0,
        "orders_synced_today": None,
        "config": {
            "corp_id": "ww****8832",
            "agent_id": "100****",
            "bound_users": 45,
        },
        "recent_errors": [],
    },
    {
        "id": "intg-wechat-pay",
        "name": "微信支付",
        "type": "payment_adapter",
        "icon": "wechat",
        "status": "healthy",
        "uptime_pct": 99.99,
        "latency_ms": 60,
        "last_sync_at": "2026-04-10T15:29:30+08:00",
        "sync_interval_seconds": None,
        "error_count_24h": 0,
        "warning_count_24h": 0,
        "orders_synced_today": None,
        "config": {
            "mch_id": "16****88",
            "stores_bound": 12,
        },
        "recent_errors": [],
    },
    {
        "id": "intg-alipay",
        "name": "支付宝",
        "type": "payment_adapter",
        "icon": "alipay",
        "status": "error",
        "uptime_pct": 85.0,
        "latency_ms": 0,
        "last_sync_at": "2026-04-10T10:00:00+08:00",
        "sync_interval_seconds": None,
        "error_count_24h": 42,
        "warning_count_24h": 0,
        "orders_synced_today": None,
        "config": {
            "app_id": "20****66",
            "stores_bound": 12,
        },
        "recent_errors": [
            {"time": "2026-04-10T10:00:00+08:00", "code": "CERT_EXPIRED", "message": "应用证书已过期，所有支付宝交易失败", "resolved": False},
        ],
    },
]

_MOCK_WEBHOOKS: List[Dict[str, Any]] = [
    {
        "id": "wh-001",
        "source": "meituan",
        "event_type": "order.new",
        "status": "success",
        "received_at": "2026-04-10T15:28:12+08:00",
        "processed_at": "2026-04-10T15:28:12+08:00",
        "latency_ms": 85,
        "payload_size_bytes": 2048,
        "store_id": "store-001",
        "order_no": "MT20260410153201",
    },
    {
        "id": "wh-002",
        "source": "eleme",
        "event_type": "order.new",
        "status": "success",
        "received_at": "2026-04-10T15:27:45+08:00",
        "processed_at": "2026-04-10T15:27:46+08:00",
        "latency_ms": 120,
        "payload_size_bytes": 1856,
        "store_id": "store-002",
        "order_no": "ELE20260410152788",
    },
    {
        "id": "wh-003",
        "source": "douyin",
        "event_type": "coupon.verify",
        "status": "failed",
        "received_at": "2026-04-10T15:10:05+08:00",
        "processed_at": None,
        "latency_ms": None,
        "payload_size_bytes": 512,
        "store_id": "store-003",
        "order_no": None,
        "error": "抖音核销接口返回500: Internal Server Error",
    },
    {
        "id": "wh-004",
        "source": "meituan",
        "event_type": "order.cancel",
        "status": "success",
        "received_at": "2026-04-10T15:05:30+08:00",
        "processed_at": "2026-04-10T15:05:31+08:00",
        "latency_ms": 95,
        "payload_size_bytes": 1024,
        "store_id": "store-001",
        "order_no": "MT20260410142288",
    },
    {
        "id": "wh-005",
        "source": "meituan",
        "event_type": "order.refund",
        "status": "success",
        "received_at": "2026-04-10T14:50:10+08:00",
        "processed_at": "2026-04-10T14:50:11+08:00",
        "latency_ms": 110,
        "payload_size_bytes": 1536,
        "store_id": "store-002",
        "order_no": "MT20260410130155",
    },
    {
        "id": "wh-006",
        "source": "douyin",
        "event_type": "coupon.verify",
        "status": "success",
        "received_at": "2026-04-10T14:30:22+08:00",
        "processed_at": "2026-04-10T14:30:23+08:00",
        "latency_ms": 220,
        "payload_size_bytes": 480,
        "store_id": "store-004",
        "order_no": "DY20260410143022",
    },
    {
        "id": "wh-007",
        "source": "eleme",
        "event_type": "order.status_change",
        "status": "success",
        "received_at": "2026-04-10T14:15:08+08:00",
        "processed_at": "2026-04-10T14:15:09+08:00",
        "latency_ms": 75,
        "payload_size_bytes": 768,
        "store_id": "store-001",
        "order_no": "ELE20260410140233",
    },
    {
        "id": "wh-008",
        "source": "meituan",
        "event_type": "order.new",
        "status": "success",
        "received_at": "2026-04-10T14:00:55+08:00",
        "processed_at": "2026-04-10T14:00:56+08:00",
        "latency_ms": 92,
        "payload_size_bytes": 2100,
        "store_id": "store-005",
        "order_no": "MT20260410140055",
    },
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/integrations/health")
async def get_integrations_health(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """所有适配器健康状态汇总。"""
    log.info("integrations_health_requested", tenant_id=x_tenant_id)

    status_counts: Dict[str, int] = {}
    for intg in _MOCK_INTEGRATIONS:
        status_counts[intg["status"]] = status_counts.get(intg["status"], 0) + 1

    return {
        "ok": True,
        "data": {
            "total": len(_MOCK_INTEGRATIONS),
            "by_status": status_counts,
            "integrations": [
                {
                    "id": i["id"],
                    "name": i["name"],
                    "type": i["type"],
                    "icon": i["icon"],
                    "status": i["status"],
                    "uptime_pct": i["uptime_pct"],
                    "latency_ms": i["latency_ms"],
                    "last_sync_at": i["last_sync_at"],
                    "error_count_24h": i["error_count_24h"],
                    "orders_synced_today": i["orders_synced_today"],
                }
                for i in _MOCK_INTEGRATIONS
            ],
            "snapshot_time": datetime.now(tz=timezone.utc).isoformat(),
        },
    }


@router.get("/integrations/{integration_id}/detail")
async def get_integration_detail(
    integration_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """适配器详情（含配置、近期错误）。"""
    log.info("integration_detail_requested", integration_id=integration_id, tenant_id=x_tenant_id)

    for intg in _MOCK_INTEGRATIONS:
        if intg["id"] == integration_id:
            return {"ok": True, "data": intg}

    raise HTTPException(status_code=404, detail="适配器不存在")


@router.post("/integrations/{integration_id}/retry")
async def retry_integration(
    integration_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """手动重试适配器连接/同步。"""
    log.info("integration_retry_requested", integration_id=integration_id, tenant_id=x_tenant_id)

    for intg in _MOCK_INTEGRATIONS:
        if intg["id"] == integration_id:
            # Mock: 模拟重试结果
            if intg["status"] == "error":
                return {
                    "ok": True,
                    "data": {
                        "integration_id": integration_id,
                        "name": intg["name"],
                        "retry_result": "still_failing",
                        "message": f"{intg['name']} 重试失败: {intg['recent_errors'][0]['message'] if intg['recent_errors'] else '未知错误'}",
                        "next_retry_at": "2026-04-10T16:00:00+08:00",
                        "retried_at": datetime.now(tz=timezone.utc).isoformat(),
                    },
                }
            return {
                "ok": True,
                "data": {
                    "integration_id": integration_id,
                    "name": intg["name"],
                    "retry_result": "success",
                    "message": f"{intg['name']} 重连成功",
                    "retried_at": datetime.now(tz=timezone.utc).isoformat(),
                },
            }

    raise HTTPException(status_code=404, detail="适配器不存在")


@router.get("/webhooks/recent")
async def get_recent_webhooks(
    source: Optional[str] = Query(None, description="来源筛选: meituan/eleme/douyin"),
    status: Optional[str] = Query(None, description="状态筛选: success/failed"),
    limit: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """最近Webhook事件列表。"""
    log.info("webhooks_recent_requested", tenant_id=x_tenant_id, source=source, status=status)

    filtered = _MOCK_WEBHOOKS[:]
    if source:
        filtered = [w for w in filtered if w["source"] == source]
    if status:
        filtered = [w for w in filtered if w["status"] == status]

    items = filtered[:limit]

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": len(filtered),
            "success_rate_pct": round(sum(1 for w in _MOCK_WEBHOOKS if w["status"] == "success") / len(_MOCK_WEBHOOKS) * 100, 1) if _MOCK_WEBHOOKS else 0,
            "avg_latency_ms": round(sum(w["latency_ms"] for w in _MOCK_WEBHOOKS if w["latency_ms"]) / max(sum(1 for w in _MOCK_WEBHOOKS if w["latency_ms"]), 1)),
        },
    }
