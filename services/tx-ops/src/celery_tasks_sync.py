"""四系统数据同步 Celery 定时任务

任务列表：
  sync.pinzhi_orders_15min        — 每15分钟同步品智订单
  sync.aoqiwei_members_hourly     — 每小时同步奥琦玮会员
  sync.aoqiwei_inventory_hourly   — 每小时同步奥琦玮库存
  sync.yiding_reservations_5min   — 每5分钟轮询易订预订

Celery Beat Schedule 示例（在 celeryconfig.py 或 app.conf.beat_schedule 中注册）：
  from celery.schedules import crontab
  beat_schedule = {
      "sync-pinzhi-15min":        {"task": "sync.pinzhi_orders_15min",      "schedule": crontab(minute="*/15")},
      "sync-aoqiwei-members-1h":  {"task": "sync.aoqiwei_members_hourly",   "schedule": crontab(minute=0)},
      "sync-aoqiwei-supply-1h":   {"task": "sync.aoqiwei_inventory_hourly", "schedule": crontab(minute=5)},
      "sync-yiding-5min":         {"task": "sync.yiding_reservations_5min", "schedule": crontab(minute="*/5")},
  }

设计决策：
  - Celery 任务本身是同步函数，内部通过 asyncio.run() 驱动 async 协调器
  - 遍历所有 sync_enabled=True 的租户门店（从 DB 查询）
  - 任务异常捕获具体类型，禁止 except Exception 作为唯一兜底
  - 任务结果写入 operation_logs（由 MultiSystemSyncService 内部处理）
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Celery App 初始化
# ──────────────────────────────────────────────────────────────────────

try:
    from celery import Celery
    from celery.schedules import crontab

    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

    app = Celery(
        "tx_ops_sync",
        broker=CELERY_BROKER_URL,
        backend=CELERY_RESULT_BACKEND,
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="Asia/Shanghai",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,           # 任务完成后再 ack，防止意外丢失
        worker_prefetch_multiplier=1,  # 防止大任务积压
    )

    # ── Beat Schedule ───────────────────────────────────────────────────
    app.conf.beat_schedule = {
        "sync-pinzhi-orders-15min": {
            "task": "sync.pinzhi_orders_15min",
            "schedule": crontab(minute="*/15"),
            "options": {"expires": 14 * 60},  # 14分钟内未执行则过期
        },
        "sync-aoqiwei-members-hourly": {
            "task": "sync.aoqiwei_members_hourly",
            "schedule": crontab(minute=0),     # 每小时整点
            "options": {"expires": 55 * 60},
        },
        "sync-aoqiwei-inventory-hourly": {
            "task": "sync.aoqiwei_inventory_hourly",
            "schedule": crontab(minute=5),     # 每小时05分（错开CRM任务）
            "options": {"expires": 55 * 60},
        },
        "sync-yiding-reservations-5min": {
            "task": "sync.yiding_reservations_5min",
            "schedule": crontab(minute="*/5"),
            "options": {"expires": 4 * 60},
        },
    }

    _CELERY_AVAILABLE = True

except ImportError:
    # Celery 未安装时降级（允许模块被 import，任务函数不可用）
    _CELERY_AVAILABLE = False
    app = None  # type: ignore[assignment]
    logger.warning("celery_not_installed", note="Celery 未安装，定时任务不可用")


# ──────────────────────────────────────────────────────────────────────
# DB Engine 懒初始化
# ──────────────────────────────────────────────────────────────────────

_engine = None


def _get_engine():
    """获取 AsyncEngine（懒初始化，Celery worker 进程级单例）"""
    global _engine
    if _engine is None:
        from sqlalchemy.ext.asyncio import create_async_engine

        db_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/tunxiang",
        )
        _engine = create_async_engine(db_url, pool_size=5, max_overflow=10)
    return _engine


def _get_sync_service():
    from .services.multi_system_sync_service import MultiSystemSyncService
    return MultiSystemSyncService(_get_engine())


# ──────────────────────────────────────────────────────────────────────
# 辅助：查询需要同步的租户门店列表
# ──────────────────────────────────────────────────────────────────────


async def _fetch_sync_enabled_stores() -> List[Dict[str, Any]]:
    """从 DB 查询 sync_enabled=True 的所有租户门店

    返回 [{"tenant_id": "...", "store_id": "...", "systems": [...]}]
    """
    from sqlalchemy import text

    engine = _get_engine()
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("""
                    SELECT
                        s.tenant_id,
                        s.id        AS store_id,
                        s.extra_data->>'sync_systems' AS sync_systems_json
                    FROM stores s
                    WHERE s.is_deleted    = FALSE
                      AND (s.extra_data->>'sync_enabled')::boolean = TRUE
                    ORDER BY s.tenant_id, s.id
                    LIMIT 500
                """)
            )
            import json as _json

            result = []
            for row in rows.fetchall():
                systems = None
                if row.sync_systems_json:
                    try:
                        systems = _json.loads(row.sync_systems_json)
                    except (ValueError, TypeError):
                        systems = None
                result.append({
                    "tenant_id": str(row.tenant_id),
                    "store_id": str(row.store_id),
                    "systems": systems,
                })
            return result
    except Exception as exc:  # noqa: BLE001  # 查询失败时返回空列表，任务自然退出
        logger.error("fetch_sync_enabled_stores_failed", error=str(exc), exc_info=True)
        return []


# ──────────────────────────────────────────────────────────────────────
# Celery 任务定义
# ──────────────────────────────────────────────────────────────────────

if _CELERY_AVAILABLE:

    @app.task(
        name="sync.pinzhi_orders_15min",
        bind=True,
        max_retries=2,
        default_retry_delay=60,
        soft_time_limit=600,   # 10分钟软超时
        time_limit=720,        # 12分钟硬超时
    )
    def sync_pinzhi_orders_task(self) -> Dict[str, Any]:
        """每15分钟同步品智订单

        遍历所有 sync_enabled=True 且包含 'pinzhi' 的租户门店。
        """
        async def _run():
            stores = await _fetch_sync_enabled_stores()
            svc = _get_sync_service()
            total_synced = 0
            all_errors: List[str] = []

            for store_info in stores:
                systems = store_info.get("systems")
                if systems is not None and "pinzhi" not in systems:
                    continue
                try:
                    result = await svc.sync_pinzhi_orders(
                        tenant_id=store_info["tenant_id"],
                        store_id=store_info["store_id"],
                    )
                    total_synced += result.get("synced", 0)
                    all_errors.extend(result.get("errors", []))
                except (ValueError, RuntimeError) as exc:
                    all_errors.append(f"{store_info['store_id']}: {exc}")
                    logger.error(
                        "sync_pinzhi_orders_task_store_failed",
                        store_id=store_info["store_id"],
                        error=str(exc),
                        exc_info=True,
                    )

            return {"total_synced": total_synced, "errors": all_errors}

        try:
            return asyncio.run(_run())
        except RuntimeError as exc:
            logger.error("sync_pinzhi_orders_task_failed", error=str(exc), exc_info=True)
            raise self.retry(exc=exc)

    @app.task(
        name="sync.aoqiwei_members_hourly",
        bind=True,
        max_retries=2,
        default_retry_delay=120,
        soft_time_limit=1800,  # 30分钟软超时（会员量可能较大）
        time_limit=2100,
    )
    def sync_aoqiwei_members_task(self) -> Dict[str, Any]:
        """每小时同步奥琦玮会员"""

        async def _run():
            stores = await _fetch_sync_enabled_stores()
            svc = _get_sync_service()
            total_synced = 0
            all_errors: List[str] = []

            for store_info in stores:
                systems = store_info.get("systems")
                if systems is not None and "aoqiwei_crm" not in systems:
                    continue
                try:
                    result = await svc.sync_aoqiwei_members(
                        tenant_id=store_info["tenant_id"],
                        store_id=store_info["store_id"],
                    )
                    total_synced += result.get("synced", 0)
                    all_errors.extend(result.get("errors", []))
                except (ValueError, RuntimeError) as exc:
                    all_errors.append(f"{store_info['store_id']}: {exc}")
                    logger.error(
                        "sync_aoqiwei_members_task_store_failed",
                        store_id=store_info["store_id"],
                        error=str(exc),
                        exc_info=True,
                    )

            return {"total_synced": total_synced, "errors": all_errors}

        try:
            return asyncio.run(_run())
        except RuntimeError as exc:
            logger.error("sync_aoqiwei_members_task_failed", error=str(exc), exc_info=True)
            raise self.retry(exc=exc)

    @app.task(
        name="sync.aoqiwei_inventory_hourly",
        bind=True,
        max_retries=2,
        default_retry_delay=120,
        soft_time_limit=900,
        time_limit=1080,
    )
    def sync_aoqiwei_inventory_task(self) -> Dict[str, Any]:
        """每小时同步奥琦玮库存"""

        async def _run():
            stores = await _fetch_sync_enabled_stores()
            svc = _get_sync_service()
            total_synced = 0
            all_errors: List[str] = []

            for store_info in stores:
                systems = store_info.get("systems")
                if systems is not None and "aoqiwei_supply" not in systems:
                    continue
                try:
                    result = await svc.sync_aoqiwei_inventory(
                        tenant_id=store_info["tenant_id"],
                        store_id=store_info["store_id"],
                    )
                    total_synced += result.get("synced", 0)
                    all_errors.extend(result.get("errors", []))
                except (ValueError, RuntimeError) as exc:
                    all_errors.append(f"{store_info['store_id']}: {exc}")
                    logger.error(
                        "sync_aoqiwei_inventory_task_store_failed",
                        store_id=store_info["store_id"],
                        error=str(exc),
                        exc_info=True,
                    )

            return {"total_synced": total_synced, "errors": all_errors}

        try:
            return asyncio.run(_run())
        except RuntimeError as exc:
            logger.error("sync_aoqiwei_inventory_task_failed", error=str(exc), exc_info=True)
            raise self.retry(exc=exc)

    @app.task(
        name="sync.yiding_reservations_5min",
        bind=True,
        max_retries=3,
        default_retry_delay=30,
        soft_time_limit=240,
        time_limit=300,
    )
    def sync_yiding_reservations_task(self) -> Dict[str, Any]:
        """每5分钟轮询易订预订"""

        async def _run():
            stores = await _fetch_sync_enabled_stores()
            svc = _get_sync_service()
            total_synced = 0
            all_errors: List[str] = []

            for store_info in stores:
                systems = store_info.get("systems")
                if systems is not None and "yiding" not in systems:
                    continue
                try:
                    result = await svc.sync_yiding_reservations(
                        tenant_id=store_info["tenant_id"],
                        store_id=store_info["store_id"],
                    )
                    total_synced += result.get("synced", 0)
                    all_errors.extend(result.get("errors", []))
                except (ValueError, RuntimeError) as exc:
                    all_errors.append(f"{store_info['store_id']}: {exc}")
                    logger.error(
                        "sync_yiding_reservations_task_store_failed",
                        store_id=store_info["store_id"],
                        error=str(exc),
                        exc_info=True,
                    )

            return {"total_synced": total_synced, "errors": all_errors}

        try:
            return asyncio.run(_run())
        except RuntimeError as exc:
            logger.error("sync_yiding_reservations_task_failed", error=str(exc), exc_info=True)
            raise self.retry(exc=exc)
