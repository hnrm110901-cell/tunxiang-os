"""main.py — Sync Engine 入口

启动策略：
  1. 检查云端连接状态
  2. 可连接且未曾同步 → 全量同步，切换增量模式
  3. 可连接已有水位   → 直接增量同步
  4. 不可连接         → 本地模式（只写 local_change_log，等待重连）
  5. 重连后           → 先 push 本地变更，再增量同步

设计原则：
  - 每 SYNC_INTERVAL 秒增量同步（默认 5 分钟）
  - 冲突解决：云端为主（cloud-wins），保留本地终态
  - 基于 updated_at 时间戳的增量追踪
  - 不阻塞业务（异步运行）
"""
from __future__ import annotations

import asyncio
import os

import httpx
import structlog

from sync_engine import SyncEngine
from sync_tracker import SyncTracker

logger = structlog.get_logger()

# ─── 配置 ──────────────────────────────────────────────────────────────────

SYNC_INTERVAL: int = int(os.getenv("SYNC_INTERVAL_SECONDS", "300"))
CLOUD_API_URL: str = os.getenv("CLOUD_API_URL", "")
SYNC_DB_PATH: str = os.getenv("SYNC_DB_PATH", "/var/lib/tunxiang/sync_engine.db")
TENANT_ID: str = os.getenv("TENANT_ID", "")
CONNECT_TIMEOUT: float = float(os.getenv("CLOUD_CONNECT_TIMEOUT", "5"))

# ─── 连接状态 ──────────────────────────────────────────────────────────────

_is_connected: bool = False
_engine: SyncEngine | None = None


async def _check_cloud_connection() -> bool:
    """尝试连接云端 /health，返回是否可达"""
    if not CLOUD_API_URL:
        logger.warning("main.no_cloud_api_url", msg="CLOUD_API_URL not set")
        return False
    try:
        async with httpx.AsyncClient(timeout=CONNECT_TIMEOUT) as client:
            resp = await client.get(f"{CLOUD_API_URL}/health")
            return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError):
        return False


async def _run_sync_loop(engine: SyncEngine, tracker: SyncTracker) -> None:
    """主同步循环"""
    global _is_connected

    needs_full_sync = True  # 首次运行标记

    while True:
        connected = await _check_cloud_connection()

        if connected and not _is_connected:
            # 重新连接：推送离线变更，再做增量同步
            logger.info("main.cloud_reconnected")
            _is_connected = True
            pending = await tracker.get_pending_count()
            if pending > 0:
                logger.info("main.flushing_offline_changes", pending=pending)
                await engine.push_local_changes(TENANT_ID)

        if not connected:
            _is_connected = False
            logger.info("main.offline_mode", msg="cloud unreachable, running local-only")
            await asyncio.sleep(SYNC_INTERVAL)
            continue

        try:
            if needs_full_sync:
                # 检查是否已有历史水位（已同步过则跳过全量）
                watermark = await tracker.get_watermark("orders")
                if watermark == "1970-01-01T00:00:00+00:00":
                    logger.info("main.full_sync_triggered", reason="first run or reset")
                    await engine.full_sync(TENANT_ID)
                else:
                    logger.info(
                        "main.skip_full_sync",
                        reason="watermark exists",
                        watermark=watermark,
                    )
                needs_full_sync = False
            else:
                await engine.incremental_sync(TENANT_ID)

        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.error(
                "main.sync_network_error",
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )
            _is_connected = False
            needs_full_sync = True  # 断线重连后重新判断

        except OSError as exc:
            logger.error("main.sync_os_error", error=str(exc), exc_info=True)
            _is_connected = False

        await asyncio.sleep(SYNC_INTERVAL)


async def main() -> None:
    """程序入口：初始化并启动同步循环"""
    logger.info(
        "main.starting",
        sync_interval=SYNC_INTERVAL,
        cloud_api_url=CLOUD_API_URL or "(not set)",
        sync_db_path=SYNC_DB_PATH,
        tenant_id=TENANT_ID or "(not set)",
    )

    tracker = SyncTracker(db_path=SYNC_DB_PATH)
    engine = SyncEngine(
        tracker=tracker,
        cloud_api_url=CLOUD_API_URL,
    )

    global _engine
    _engine = engine

    await engine.init()
    logger.info("main.engine_initialized")

    await _run_sync_loop(engine, tracker)


if __name__ == "__main__":
    asyncio.run(main())
