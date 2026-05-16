"""tx-supply service-local projector daemon helpers (PRD-11 sub-B.2 / 2026-05-16).

按架构师 D1 ① — IndexSplitProjector 物理隔离于全局 `shared.events.src.projector_registry`
(那 9 个是 mv_* "只读"投影器, 本 projector 是首次让 projector 触发业务侧写, 性质不同).

激活: 默认 OFF, env `TX_SUPPLY_ENABLE_INDEX_SPLIT_PROJECTOR=true` 才启动. 本 PR ship
代码层 ready, 激活 (lifespan 钩子接入 tx-supply main.py) 留 Phase 2 W12 灰度 follow-up
单立 PR — 与 5/13 row-lock fix 6-PR roadmap 同节奏 (代码 ship → 灰度激活独立 PR).

测试单元: 直接 new IndexSplitProjector(tenant_id) 调 handle(event, conn) 即可,
不依赖 start/stop 函数 (后者只是部署期 wrapper).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import UUID

import structlog

from .index_split import IndexSplitProjector

log = structlog.get_logger(__name__)

_PROJECTOR_TASKS: dict[str, "asyncio.Task[Any]"] = {}


def is_enabled() -> bool:
    """Feature flag gate — 默认 OFF, 激活 PR 改 default 或 env."""
    val = os.getenv("TX_SUPPLY_ENABLE_INDEX_SPLIT_PROJECTOR", "false")
    return val.lower() in ("1", "true", "yes", "on")


async def start_index_split_projector(tenant_id: UUID | str) -> None:
    """启动单租户的 IndexSplitProjector daemon (idempotent).

    多次调用同 tenant_id 不重复启动. lifespan hook 推荐用法:
        @app.on_event("startup")
        async def on_startup() -> None:
            for tenant in active_tenants():
                await start_index_split_projector(tenant)
    """
    if not is_enabled():
        log.info("index_split_projector_disabled", reason="env_off")
        return
    tenant_str = str(tenant_id)
    existing = _PROJECTOR_TASKS.get(tenant_str)
    if existing is not None and not existing.done():
        return
    projector = IndexSplitProjector(tenant_id=tenant_id)
    task = asyncio.create_task(
        projector.run(), name=f"index_split_projector_{tenant_str[:8]}"
    )
    _PROJECTOR_TASKS[tenant_str] = task
    log.info("index_split_projector_started", tenant_id=tenant_str)


async def stop_index_split_projector(tenant_id: UUID | str) -> None:
    """优雅停止 (lifespan shutdown hook 用)."""
    tenant_str = str(tenant_id)
    task = _PROJECTOR_TASKS.get(tenant_str)
    if task is None:
        return
    if not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _PROJECTOR_TASKS.pop(tenant_str, None)
    log.info("index_split_projector_stopped", tenant_id=tenant_str)
