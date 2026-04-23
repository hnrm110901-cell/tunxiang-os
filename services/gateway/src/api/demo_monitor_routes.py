"""演示监控面板 API 路由 — Gap C-04

提供演示环境实时监控快照，用于演示过程中展示系统运行状态。

端点：
  GET /api/v1/demo/monitor — 统一监控快照
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import structlog
from fastapi import APIRouter

from ..response import ok

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/demo", tags=["demo-monitor"])

# ── 服务清单 ──────────────────────────────────────────────────────────────────────
_SERVICES = [
    {"name": "gateway", "port": 8000, "p0": True},
    {"name": "tx-trade", "port": 8001, "p0": True},
    {"name": "tx-menu", "port": 8002, "p0": False},
    {"name": "tx-member", "port": 8003, "p0": False},
    {"name": "tx-growth", "port": 8004, "p0": False},
    {"name": "tx-ops", "port": 8005, "p0": False},
    {"name": "tx-supply", "port": 8006, "p0": False},
    {"name": "tx-finance", "port": 8007, "p0": False},
    {"name": "tx-agent", "port": 8008, "p0": False},
    {"name": "tx-analytics", "port": 8009, "p0": True},
    {"name": "tx-brain", "port": 8010, "p0": False},
    {"name": "tx-intel", "port": 8011, "p0": False},
    {"name": "tx-org", "port": 8012, "p0": False},
]

_DEMO_MERCHANTS = ["czyz", "zqx", "sgc"]
_ANALYTICS_BASE = "http://localhost:8009"

# ── 辅助：探测单个服务 ─────────────────────────────────────────────────────────────


async def _probe_service(client: httpx.AsyncClient, name: str, port: int) -> dict:
    """探测服务健康状态，返回 name / port / status / latency_ms。"""
    url = f"http://localhost:{port}/health"
    start = asyncio.get_event_loop().time()
    try:
        resp = await client.get(url, timeout=2.0)
        latency_ms = round((asyncio.get_event_loop().time() - start) * 1000)
        status = "up" if resp.status_code < 500 else "degraded"
    except httpx.TimeoutException:
        latency_ms = 2000
        status = "timeout"
    except httpx.ConnectError:
        latency_ms = 0
        status = "down"

    return {"name": name, "port": port, "status": status, "latency_ms": latency_ms}


# ── 辅助：获取商户数据质量 ─────────────────────────────────────────────────────────


async def _fetch_merchant_data(client: httpx.AsyncClient, merchant_code: str) -> dict:
    """从 tx-analytics 服务获取商户数据质量和基础统计。"""
    fallback: dict = {
        "merchant_code": merchant_code,
        "data_quality_score": 0,
        "last_order_at": None,
        "orders_today": 0,
        "active_tables": 0,
    }

    try:
        resp = await client.get(
            f"{_ANALYTICS_BASE}/api/v1/analytics/data-quality/{merchant_code}",
            timeout=2.0,
        )
        if resp.status_code == 200:
            body = resp.json()
            score = body.get("data", {}).get("total_score", 0)
            fallback["data_quality_score"] = score
    except httpx.TimeoutException:
        logger.warning("demo_monitor_merchant_timeout", merchant_code=merchant_code)
    except httpx.ConnectError:
        logger.warning("demo_monitor_analytics_unreachable", merchant_code=merchant_code)

    return fallback


# ── 辅助：获取同步状态 ─────────────────────────────────────────────────────────────


async def _fetch_sync_status(client: httpx.AsyncClient) -> dict:
    """尝试从 analytics 获取同步状态，不可达时返回安全默认值。"""
    fallback: dict = {
        "last_sync_at": None,
        "pending_events": 0,
        "error_count_1h": 0,
    }

    try:
        resp = await client.get(
            f"{_ANALYTICS_BASE}/api/v1/analytics/data-quality",
            timeout=2.0,
        )
        if resp.status_code == 200:
            fallback["last_sync_at"] = datetime.now(timezone.utc).isoformat()
    except httpx.TimeoutException:
        logger.warning("demo_monitor_sync_status_timeout")
    except httpx.ConnectError:
        logger.warning("demo_monitor_sync_status_unreachable")

    return fallback


# ── 辅助：计算整体状态 ─────────────────────────────────────────────────────────────


def _compute_overall_status(
    services: list[dict],
    merchants: list[dict],
) -> tuple[str, list[str]]:
    """根据服务状态和商户数据质量计算整体健康状态，返回 (status, alerts)。"""
    p0_down: list[str] = []
    alerts: list[str] = []

    for svc in services:
        is_p0 = next((s["p0"] for s in _SERVICES if s["name"] == svc["name"]), False)
        if svc["status"] in ("down", "timeout") and is_p0:
            p0_down.append(svc["name"])
            alerts.append(f"P0 服务 {svc['name']} 不可达（{svc['status']}）")

    for m in merchants:
        score = m.get("data_quality_score", 0)
        if score < 60:
            alerts.append(f"商户 {m['merchant_code']} 数据质量分低于阈值（{score}/100）")

    if len(p0_down) >= 2:
        overall = "critical"
    elif len(p0_down) == 1 or any(m.get("data_quality_score", 100) < 60 for m in merchants):
        overall = "degraded"
    else:
        overall = "healthy"

    return overall, alerts


# ── 主端点 ────────────────────────────────────────────────────────────────────────


@router.get("/monitor", summary="演示环境统一监控快照")
async def get_demo_monitor() -> dict:
    """返回演示环境实时监控快照，包括服务状态、商户数据质量和同步状态。"""
    snapshot_at = datetime.now(timezone.utc).isoformat()

    async with httpx.AsyncClient() as client:
        # 并发探测所有服务
        service_tasks = [_probe_service(client, svc["name"], svc["port"]) for svc in _SERVICES]
        # 并发获取商户数据
        merchant_tasks = [_fetch_merchant_data(client, code) for code in _DEMO_MERCHANTS]
        # 获取同步状态
        sync_task = _fetch_sync_status(client)

        # 并发执行所有 IO
        results = await asyncio.gather(
            *service_tasks,
            *merchant_tasks,
            sync_task,
            return_exceptions=False,
        )

    n_services = len(_SERVICES)
    n_merchants = len(_DEMO_MERCHANTS)

    services: list[dict] = list(results[:n_services])
    merchants: list[dict] = list(results[n_services : n_services + n_merchants])
    sync_status: dict = results[n_services + n_merchants]  # type: ignore[assignment]

    overall_status, alerts = _compute_overall_status(services, merchants)

    return ok(
        {
            "snapshot_at": snapshot_at,
            "overall_status": overall_status,
            "services": services,
            "merchants": merchants,
            "sync_status": sync_status,
            "alerts": alerts,
        }
    )
