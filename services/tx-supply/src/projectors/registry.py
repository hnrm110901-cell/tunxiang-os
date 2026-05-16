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

# Feature Flag SDK（try/except 保护，SDK 不可用时降级为 env-only 模式）
try:
    from shared.feature_flags import FlagContext
    from shared.feature_flags import is_enabled as _ff_is_enabled
    from shared.feature_flags.flag_names import SupplyFlags

    _FLAG_SDK_AVAILABLE = True
except ImportError:
    _FLAG_SDK_AVAILABLE = False

    def _ff_is_enabled(flag, context=None):  # type: ignore[no-redef]
        return False

    class FlagContext:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class SupplyFlags:  # type: ignore[no-redef]
        PRD11_INDEX_SPLIT_PROJECTOR = "supply.prd11.index_split_projector.enable"


log = structlog.get_logger(__name__)

_PROJECTOR_TASKS: dict[str, "asyncio.Task[Any]"] = {}


def _env_override() -> bool | None:
    """env override (优先级最高, 紧急停用走 false / 强制启用走 true).

    返回 None 表示未设置 env (走 feature_flags SDK 评估).
    """
    val = os.getenv("TX_SUPPLY_ENABLE_INDEX_SPLIT_PROJECTOR")
    if val is None:
        return None
    val_lower = val.lower()
    if val_lower in ("1", "true", "yes", "on"):
        return True
    if val_lower in ("0", "false", "no", "off"):
        return False
    return None


def is_enabled() -> bool:
    """全局 gate (lifespan startup 用) — env > feature_flags SDK > False.

    PRD-11 sub-B.2 灰度入口:
    - env TX_SUPPLY_ENABLE_INDEX_SPLIT_PROJECTOR 优先级最高 (紧急停用 / 强制启用).
    - 未设 env 时走 feature_flags SDK 评估 SupplyFlags.PRD11_INDEX_SPLIT_PROJECTOR
      (无 tenant context, 看全局 env defaultValue + environments).
    - SDK 抛异常 fail-open False + structlog.warn (不阻塞 lifespan).

    per-tenant gate 走 `is_enabled_for_tenant(tenant_id)` 函数.
    """
    override = _env_override()
    if override is not None:
        return override
    try:
        return bool(_ff_is_enabled(SupplyFlags.PRD11_INDEX_SPLIT_PROJECTOR))
    except Exception as exc:  # noqa: BLE001 — fail-open SDK 异常
        log.warning(
            "index_split_projector_flag_sdk_failed",
            error=str(exc),
            exc_info=True,
        )
        return False


def is_enabled_for_tenant(tenant_id: UUID | str) -> bool:
    """per-tenant gate (lifespan refresh loop 用) — env > feature_flags SDK > False.

    与 `is_enabled()` 互补:
    - env 强制 true → 所有 tenant 启 daemon (紧急强制启用).
    - env 强制 false → 所有 tenant 跳过 daemon (紧急停用, 与 is_enabled 一致).
    - 未设 env → 走 feature_flags SDK + FlagContext(tenant_id=...) 评估
      targeting_rules.prod.tenant_id 白名单 (5%→50%→100% 灰度).
    - SDK 抛异常 fail-open False + structlog.warn (不阻塞 lifespan).
    """
    override = _env_override()
    if override is not None:
        return override
    try:
        ctx = FlagContext(tenant_id=str(tenant_id))
        return bool(_ff_is_enabled(SupplyFlags.PRD11_INDEX_SPLIT_PROJECTOR, ctx))
    except Exception as exc:  # noqa: BLE001 — fail-open SDK 异常
        log.warning(
            "index_split_projector_flag_sdk_failed",
            tenant_id=str(tenant_id),
            error=str(exc),
            exc_info=True,
        )
        return False


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
