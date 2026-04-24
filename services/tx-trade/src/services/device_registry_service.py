"""device_registry_service — Sprint C3 边缘设备注册表 CRUD

职责：
  - heartbeat        — 首次 insert / 后续 update last_seen_at（30s 一次）
  - get              — 读单台设备（RLS 强制 tenant_id）
  - list_by_store    — 列出某门店所有设备（用于运维面板）
  - mark_offline     — 后台定时任务扫 10 min 无心跳设备 → health=offline

设计约束（CLAUDE.md §6 + §17 Tier1）：
  - device_kind 必须 ∈ ALLOWED_DEVICE_KINDS（service 层拦截 + 迁移 CHECK 双层）
  - 所有查询显式带 tenant_id 过滤 + RLS 兜底
  - heartbeat 必须 idempotent（UPSERT），避免 PK (tenant_id, device_id) 冲突
  - 不删除 offline 设备，保留历史供运营审计（CLAUDE.md §13 不自动吞数据）

与 A3/A2 契约共享：
  - device_id 字段名 / 格式与 offline_order_mapping、saga_buffer_meta 一致
  - sync-engine Phase 1 基于本表判断设备是否需要 push delta
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = structlog.get_logger(__name__)


# ─── 枚举 ─────────────────────────────────────────────────────────────────────


class DeviceKind(str, Enum):
    """允许的终端类型（与 v271 CHECK ck_edge_device_kind_enum 一致）。"""

    POS = "pos"
    KDS = "kds"
    CREW_PHONE = "crew_phone"
    TV_MENU = "tv_menu"
    RECEPTION = "reception"
    MAC_MINI = "mac_mini"


class HealthStatus(str, Enum):
    """设备健康状态（与 v271 CHECK ck_edge_device_health_enum 一致）。"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


ALLOWED_DEVICE_KINDS: set[str] = {k.value for k in DeviceKind}
ALLOWED_HEALTH_STATUSES: set[str] = {h.value for h in HealthStatus}

# 无心跳超过此秒数标 offline（默认 10 min）
DEFAULT_OFFLINE_THRESHOLD_SEC = 600


# ─── Service ──────────────────────────────────────────────────────────────────


class DeviceRegistryService:
    """edge_device_registry 表操作封装。

    使用方式：
        svc = DeviceRegistryService(db, tenant_id=X)
        await svc.heartbeat(
            device_id="kds-xuji-17-01", device_kind="kds",
            store_id="...", os_version="Android 13",
        )
    """

    def __init__(self, db: Any, tenant_id: str) -> None:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self._db = db
        self._tenant_id = str(tenant_id)

    async def _bind_rls(self) -> None:
        await self._db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self._tenant_id},
        )

    async def heartbeat(
        self,
        *,
        device_id: str,
        device_kind: str,
        store_id: str,
        device_label: Optional[str] = None,
        os_version: Optional[str] = None,
        app_version: Optional[str] = None,
        buffer_backlog: int = 0,
        health_status: str = HealthStatus.HEALTHY.value,
        now: Optional[datetime] = None,
    ) -> None:
        """首次 insert / 后续 update last_seen_at。

        UPSERT 语义：
          - 存在 → 更新 last_seen_at / buffer_backlog / health_status / 版本号
            并 heartbeat_count +1
          - 不存在 → 首次插入

        Raises:
            ValueError: device_kind / health_status 非法，device_id / store_id 空
            SQLAlchemyError: DB 异常（向上抛）
        """
        if not device_id:
            raise ValueError("device_id is required")
        if not store_id:
            raise ValueError("store_id is required")
        if device_kind not in ALLOWED_DEVICE_KINDS:
            raise ValueError(
                f"device_kind must be one of {sorted(ALLOWED_DEVICE_KINDS)}, got {device_kind!r}"
            )
        if health_status not in ALLOWED_HEALTH_STATUSES:
            raise ValueError(
                f"health_status must be one of {sorted(ALLOWED_HEALTH_STATUSES)}, got {health_status!r}"
            )
        if buffer_backlog < 0:
            raise ValueError("buffer_backlog must be >= 0")

        ts = now or datetime.now(timezone.utc)

        await self._bind_rls()
        try:
            await self._db.execute(
                text(
                    """
                    INSERT INTO edge_device_registry (
                        tenant_id, device_id, store_id, device_kind,
                        device_label, os_version, app_version,
                        last_seen_at, health_status, buffer_backlog,
                        heartbeat_count, created_at, updated_at
                    ) VALUES (
                        :tenant_id, :device_id, :store_id, :device_kind,
                        :device_label, :os_version, :app_version,
                        :last_seen_at, :health_status, :buffer_backlog,
                        1, :last_seen_at, :last_seen_at
                    )
                    ON CONFLICT (tenant_id, device_id) DO UPDATE SET
                        last_seen_at    = EXCLUDED.last_seen_at,
                        health_status   = EXCLUDED.health_status,
                        buffer_backlog  = EXCLUDED.buffer_backlog,
                        os_version      = COALESCE(EXCLUDED.os_version, edge_device_registry.os_version),
                        app_version     = COALESCE(EXCLUDED.app_version, edge_device_registry.app_version),
                        device_label    = COALESCE(EXCLUDED.device_label, edge_device_registry.device_label),
                        heartbeat_count = edge_device_registry.heartbeat_count + 1,
                        updated_at      = EXCLUDED.last_seen_at
                    """
                ),
                {
                    "tenant_id": self._tenant_id,
                    "device_id": device_id,
                    "store_id": str(store_id),
                    "device_kind": device_kind,
                    "device_label": device_label,
                    "os_version": os_version,
                    "app_version": app_version,
                    "last_seen_at": ts,
                    "health_status": health_status,
                    "buffer_backlog": int(buffer_backlog),
                },
            )
        except SQLAlchemyError as exc:
            logger.error(
                "device_registry_heartbeat_failed",
                device_id=device_id,
                tenant_id=self._tenant_id,
                error=str(exc),
            )
            raise

        logger.info(
            "device_registry_heartbeat",
            device_id=device_id,
            device_kind=device_kind,
            tenant_id=self._tenant_id,
            store_id=str(store_id),
            buffer_backlog=buffer_backlog,
            health_status=health_status,
        )

    async def get(self, device_id: str) -> Optional[dict]:
        """按 device_id 读取（RLS 已绑定当前租户）。"""
        if not device_id:
            raise ValueError("device_id is required")
        await self._bind_rls()
        try:
            result = await self._db.execute(
                text(
                    """
                    SELECT tenant_id, device_id, store_id, device_kind,
                           device_label, os_version, app_version,
                           last_seen_at, health_status, buffer_backlog,
                           heartbeat_count, created_at, updated_at
                    FROM edge_device_registry
                    WHERE tenant_id = :tenant_id
                      AND device_id = :device_id
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": self._tenant_id,
                    "device_id": device_id,
                },
            )
            row = result.mappings().first()
            return dict(row) if row else None
        except SQLAlchemyError as exc:
            logger.error(
                "device_registry_get_failed",
                device_id=device_id,
                error=str(exc),
            )
            raise

    async def list_by_store(
        self,
        *,
        store_id: str,
        device_kind: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        """列出门店下的设备（可按 device_kind 过滤）。"""
        if not store_id:
            raise ValueError("store_id is required")
        if device_kind is not None and device_kind not in ALLOWED_DEVICE_KINDS:
            raise ValueError(f"device_kind must be one of {sorted(ALLOWED_DEVICE_KINDS)}")
        if limit <= 0 or limit > 1000:
            raise ValueError(f"limit out of range [1, 1000]: {limit}")

        await self._bind_rls()
        try:
            result = await self._db.execute(
                text(
                    """
                    SELECT tenant_id, device_id, store_id, device_kind,
                           device_label, os_version, app_version,
                           last_seen_at, health_status, buffer_backlog,
                           heartbeat_count
                    FROM edge_device_registry
                    WHERE tenant_id = :tenant_id
                      AND store_id = :store_id
                      AND (:device_kind::text IS NULL OR device_kind = :device_kind)
                    ORDER BY last_seen_at DESC NULLS LAST
                    LIMIT :limit
                    """
                ),
                {
                    "tenant_id": self._tenant_id,
                    "store_id": str(store_id),
                    "device_kind": device_kind,
                    "limit": int(limit),
                },
            )
            rows = result.mappings().all()
            return [dict(r) for r in rows]
        except SQLAlchemyError as exc:
            logger.error(
                "device_registry_list_failed",
                store_id=str(store_id),
                error=str(exc),
            )
            raise

    async def mark_offline_if_stale(
        self,
        *,
        threshold_sec: int = DEFAULT_OFFLINE_THRESHOLD_SEC,
        now: Optional[datetime] = None,
    ) -> int:
        """后台定时任务：扫 last_seen_at 超过 threshold 的设备 → health=offline。

        Returns:
            受影响行数（便于运维监控）
        """
        if threshold_sec <= 0:
            raise ValueError("threshold_sec must be > 0")

        ts = now or datetime.now(timezone.utc)

        await self._bind_rls()
        try:
            result = await self._db.execute(
                text(
                    """
                    UPDATE edge_device_registry
                    SET health_status = 'offline',
                        updated_at = :ts
                    WHERE tenant_id = :tenant_id
                      AND health_status != 'offline'
                      AND last_seen_at IS NOT NULL
                      AND last_seen_at < (:ts::timestamptz - (:threshold_sec || ' seconds')::interval)
                    """
                ),
                {
                    "tenant_id": self._tenant_id,
                    "ts": ts,
                    "threshold_sec": int(threshold_sec),
                },
            )
            affected = getattr(result, "rowcount", 0) or 0
        except SQLAlchemyError as exc:
            logger.error(
                "device_registry_mark_offline_failed",
                tenant_id=self._tenant_id,
                error=str(exc),
            )
            raise

        if affected:
            logger.warning(
                "device_registry_devices_marked_offline",
                tenant_id=self._tenant_id,
                count=affected,
                threshold_sec=threshold_sec,
            )
        return affected
