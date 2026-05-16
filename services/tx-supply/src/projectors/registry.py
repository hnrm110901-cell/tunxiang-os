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
from sqlalchemy import text

from shared.ontology.src.database import async_session_factory

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


async def stop_all_index_split_projectors() -> None:
    """停止所有已启动的 projector daemon (lifespan shutdown 兜底).

    与 stop_index_split_projector 互补: lifespan refresh loop 在 shutdown 时可能
    维护的 `started_tenants` 闭包集合与 `_PROJECTOR_TASKS` 真实状态不一致
    (refresh loop 中途被 cancel 时), 本 helper 以 _PROJECTOR_TASKS 为准
    遍历真实已启动 task. §19 reviewer round-1 P1-1 修复.
    """
    for tenant_str in list(_PROJECTOR_TASKS.keys()):
        try:
            await stop_index_split_projector(tenant_str)
        except Exception as exc:  # noqa: BLE001 — shutdown 兜底, 单 task 失败不阻塞其他
            log.error(
                "stop_all_index_split_projectors_failed",
                tenant_id=tenant_str,
                error=str(exc),
                exc_info=True,
            )


async def list_active_tenants() -> list[str]:
    """从 tenants 表读取活跃租户 ID 列表 (lifespan refresh 用).

    Returns list[str] of UUID strings.
    Raises on DB error — caller decides how to handle (lifespan loop 应 log + 跳过).

    Filter 语义: `status = 'active'` 匹配 v006 建表 schema
    (id/code/name/brand_name/pos_system/pos_config/status/created_at/updated_at,
    无 is_deleted 列). 与 cert_expiry_alerter._fetch_active_tenants 的现有 'is_deleted'
    模式不一致 — 后者是 pre-existing bug, 单独 follow-up.
    """
    _sql = text(
        "SELECT id::text AS tenant_id"
        " FROM tenants"
        " WHERE status = 'active'"
        " ORDER BY id"
        " LIMIT 1000"
    )
    try:
        async with async_session_factory() as session:
            result = await session.execute(_sql)
            return [row.tenant_id for row in result]
    except Exception as exc:
        log.error("list_active_tenants_failed", error=str(exc), exc_info=True)
        raise
