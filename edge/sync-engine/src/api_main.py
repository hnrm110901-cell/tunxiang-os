"""api_main.py — 离线同步引擎 FastAPI 服务入口

职责：
  - 注册 sync_routes（/sync/push、/sync/pull、/sync/status、/sync/checkpoint）
  - 管理 OfflineSyncService 生命周期
  - 后台运行增量同步循环（每 SYNC_INTERVAL 秒）
  - 提供健康检查端点 /health

启动：
  uvicorn api_main:app --host 0.0.0.0 --port 8200

注：后台同步守护进程（main.py）仍独立运行，本文件专为 HTTP API 服务。
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from offline_sync_service import OfflineSyncService
from sync_routes import router as sync_router

logger = structlog.get_logger()

# ─── 配置 ──────────────────────────────────────────────────────────────────

TENANT_ID: str = os.getenv("TENANT_ID", "")
STORE_ID: str = os.getenv("STORE_ID", "")
SYNC_INTERVAL: int = int(os.getenv("SYNC_INTERVAL_SECONDS", "300"))
DEVICE_ID: str = os.getenv("DEVICE_ID", "mac-mini-01")


# ─── 后台同步任务 ──────────────────────────────────────────────────────────

async def _background_sync_loop(svc: OfflineSyncService) -> None:
    """后台定时同步：每 SYNC_INTERVAL 秒推送待同步离线订单"""
    logger.info(
        "api_main.sync_loop_start",
        interval_seconds=SYNC_INTERVAL,
        tenant_id=TENANT_ID or "(not set)",
        store_id=STORE_ID or "(not set)",
    )
    while True:
        await asyncio.sleep(SYNC_INTERVAL)
        if not TENANT_ID or not STORE_ID:
            logger.warning(
                "api_main.sync_loop_skipped",
                reason="TENANT_ID or STORE_ID not configured",
            )
            continue
        try:
            is_connected = await svc._check_cloud_connection()
            if not is_connected:
                logger.info("api_main.sync_loop_offline", msg="cloud unreachable, skipping push")
                continue

            result = await svc.sync_pending_orders(
                store_id=STORE_ID, tenant_id=TENANT_ID
            )
            if result.success_count > 0 or result.failed_count > 0:
                logger.info(
                    "api_main.sync_loop_done",
                    success=result.success_count,
                    failed=result.failed_count,
                    conflict=result.conflict_count,
                )
        except (ValueError, RuntimeError, ConnectionError) as exc:
            logger.error(
                "api_main.sync_loop_error",
                error=str(exc),
                exc_info=True,
            )


# ─── 应用生命周期 ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """启动时初始化 OfflineSyncService，关闭时清理"""
    svc = OfflineSyncService(tenant_id=TENANT_ID)
    await svc.init()
    app.state.offline_sync_service = svc

    # 启动后台同步循环（不阻塞启动）
    sync_task = asyncio.create_task(_background_sync_loop(svc))

    logger.info("api_main.started", device_id=DEVICE_ID)
    yield

    # 关闭时取消后台任务
    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass

    await svc.close()
    logger.info("api_main.shutdown")


# ─── FastAPI 应用 ──────────────────────────────────────────────────────────

app = FastAPI(
    title="屯象OS 离线同步引擎",
    description=(
        "Mac mini 门店边缘服务 — 离线收银队列管理与增量同步。\n\n"
        "断网时订单存入本地 PostgreSQL；网络恢复后自动推送到云端。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 路由注册 ──────────────────────────────────────────────────────────────

app.include_router(sync_router, prefix="/api/v1")


# ─── 健康检查 ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["infra"])
async def health_check() -> dict:
    """服务健康检查"""
    svc: OfflineSyncService | None = getattr(app.state, "offline_sync_service", None)
    is_connected = False
    if svc:
        is_connected = await svc._check_cloud_connection()

    return {
        "ok": True,
        "data": {
            "service": "sync-engine",
            "device_id": DEVICE_ID,
            "cloud_connected": is_connected,
            "tenant_id": TENANT_ID or None,
            "store_id": STORE_ID or None,
        },
    }
