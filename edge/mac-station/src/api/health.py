"""健康检查与服务发现 — Mac Station

端点：
  GET /health      综合健康（本地PG / 云端连接 / 同步状态 / 磁盘 / 内存）
  GET /discovery   门店设备发现（返回 mac-station 可用服务列表）
  GET /status      详细运行状态（同步延迟 / 离线时长 / 缓存命中率）
"""
from __future__ import annotations

import asyncio
import shutil
import time
from typing import Any

import psutil
import structlog
from config import get_config
from fastapi import APIRouter
from services.offline_cache import get_offline_cache

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])

_VERSION = "4.2.0"


# ── 内部探针 ──


async def _check_local_pg() -> dict[str, Any]:
    """探测本地 PostgreSQL 是否可连接。

    Mock 模式下直接返回模拟结果。
    """
    cfg = get_config()
    try:
        import asyncpg  # type: ignore[import-untyped]

        # 从 SQLAlchemy URL 提取 asyncpg DSN
        dsn = cfg.local_db_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn, timeout=3)
        row = await conn.fetchrow("SELECT 1 AS ping")
        await conn.close()
        return {"ok": True, "latency_ms": 0, "ping": row["ping"] if row else None}
    except ImportError:
        # asyncpg 未安装 —— Mock 模式
        return {"ok": True, "latency_ms": 0, "source": "mock"}
    except (OSError, asyncio.TimeoutError, ConnectionRefusedError) as exc:
        return {"ok": False, "error": str(exc)}


def _system_metrics() -> dict[str, Any]:
    """收集磁盘和内存指标。"""
    try:
        mem = psutil.virtual_memory()
        disk = shutil.disk_usage("/")
        return {
            "memory_total_mb": round(mem.total / 1024 / 1024),
            "memory_used_pct": round(mem.percent, 1),
            "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
            "disk_used_pct": round(disk.used / disk.total * 100, 1),
        }
    except (OSError, AttributeError):
        return {"memory_used_pct": 0.0, "disk_used_pct": 0.0, "source": "unavailable"}


# ── 端点 ──


@router.get("/health", summary="综合健康检查")
async def health_check() -> dict[str, Any]:
    """综合健康检查。

    检测项：
    - 本地 PostgreSQL 连通性
    - 云端 API 可达性（取缓存结果，不实时探测）
    - 磁盘 / 内存使用率
    - 离线缓存队列长度
    """
    cfg = get_config()
    cache = get_offline_cache()

    pg_result = await _check_local_pg()
    sys_metrics = _system_metrics()

    # 如果本地 PG 异常或磁盘 > 90%，标记不健康
    pg_ok: bool = pg_result.get("ok", False)
    disk_ok: bool = sys_metrics.get("disk_used_pct", 0) < 90
    overall_ok = pg_ok and disk_ok

    return {
        "ok": overall_ok,
        "data": {
            "service": "mac-station",
            "version": _VERSION,
            "store_id": cfg.store_id,
            "offline": cfg.offline,
            "checks": {
                "local_pg": pg_result,
                "cloud_reachable": not cfg.offline,
                "disk": {"ok": disk_ok, **sys_metrics},
                "offline_queue_depth": cache.queue_depth(),
            },
            "uptime_seconds": round(time.time() - cfg.boot_time),
        },
    }


@router.get("/discovery", summary="门店服务发现")
async def service_discovery() -> dict[str, Any]:
    """返回 mac-station 可用服务端点列表。

    安卓 POS / KDS / 员工手机可通过此端点发现
    当前 mac-station 暴露的所有可用能力。
    """
    cfg = get_config()
    return {
        "ok": True,
        "data": {
            "store_id": cfg.store_id,
            "station": "mac-station",
            "version": _VERSION,
            "services": [
                {"name": "local_data", "path": "/api/v1/local", "description": "本地数据查询（订单/菜单/桌台/库存）"},
                {"name": "agent_proxy", "path": "/api/v1/agent", "description": "Agent 本地代理（CoreML推理/折扣检测）"},
                {"name": "offline_query", "path": "/api/v1/offline", "description": "离线查询（营业额/库存/订单）"},
                {"name": "vision", "path": "/api/v1/vision", "description": "视觉AI（菜品质检/卫生巡检/客流统计）"},
                {"name": "voice", "path": "/api/v1/voice", "description": "语音服务（转写/意图解析）"},
                {"name": "devices", "path": "/api/v1/devices", "description": "设备心跳注册表"},
                {"name": "ota", "path": "/api/v1/ota", "description": "OTA版本检查"},
                {"name": "kds_push", "path": "/ws/kds", "description": "KDS WebSocket推送"},
                {"name": "pos_push", "path": "/ws/pos", "description": "POS WebSocket推送"},
                {"name": "coreml_bridge", "path": "http://localhost:8100", "description": "Core ML推理桥接（独立进程）"},
            ],
            "network": {
                "tailscale_ip": cfg.tailscale_ip or "not_configured",
                "cloud_api": cfg.cloud_api_url,
                "offline": cfg.offline,
            },
        },
    }


@router.get("/status", summary="详细运行状态")
async def detailed_status() -> dict[str, Any]:
    """返回详细运行状态。

    包含同步延迟、离线时长、缓存命中率等运维关键指标。
    """
    cfg = get_config()
    cache = get_offline_cache()

    # 计算离线时长
    offline_duration_s = 0.0
    if cfg.offline and cfg.last_cloud_check_at > 0:
        offline_duration_s = time.time() - cfg.last_cloud_check_at

    cache_stats = cache.stats()

    return {
        "ok": True,
        "data": {
            "store_id": cfg.store_id,
            "tenant_id": cfg.tenant_id,
            "version": _VERSION,
            "mode": "offline" if cfg.offline else "online",
            "uptime_seconds": round(time.time() - cfg.boot_time),
            "sync": {
                "last_cloud_check_at": cfg.last_cloud_check_at,
                "cloud_reachable": not cfg.offline,
                "offline_duration_seconds": round(offline_duration_s),
            },
            "offline_cache": cache_stats,
            "system": _system_metrics(),
        },
    }
