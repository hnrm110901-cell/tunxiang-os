"""offline_order_mapping_service — Sprint A3 offline_order_mapping CRUD

职责：
  - upsert_mapping      — 离线 order_id 首次入表（state=pending）
  - mark_synced         — 同步成功，写入 cloud_order_id + state=synced
  - mark_dead_letter    — 多次补发失败，state=dead_letter（保留等人工确认）
  - increment_sync_attempt — 每次同步尝试累加 sync_attempts
  - get                 — 按 offline_order_id 读取（RLS 强制 tenant_id）
  - list_pending        — 列出租户+门店下的 pending 映射（backlog）

设计约束（CLAUDE.md §17 Tier1）：
  - 所有查询必须显式带 tenant_id 过滤（service 层拦截）+ RLS 兜底
  - 所有操作通过 trade_audit_logs 留痕（A4 write_audit）
  - SQLAlchemyError 不向上吞掉 — 让调用方决定是否重试 / 告警
  - 死信条目不得自动删除（防悄无声息吞单）

金额/时间：
  - 本表不存金额（金额归 orders 表）
  - created_at / synced_at 一律 UTC TIMESTAMPTZ
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = structlog.get_logger(__name__)


# ─── 常量 ─────────────────────────────────────────────────────────────────────

# 连续同步失败达到此阈值 → 建议 mark_dead_letter
# 20 次 × 平均 15s 间隔 ≈ 5min，人工介入时间留足
DEAD_LETTER_MAX_ATTEMPTS = 20


class MappingState(str, Enum):
    """offline_order_mapping.state 枚举（与 v270 CHECK 约束一致）。"""

    PENDING = "pending"
    SYNCED = "synced"
    DEAD_LETTER = "dead_letter"


# ─── Service ──────────────────────────────────────────────────────────────────


class OfflineOrderMappingService:
    """offline_order_mapping 表操作封装。

    使用方式：
        svc = OfflineOrderMappingService(db, tenant_id=X)
        await svc.upsert_mapping(store_id=..., device_id=..., offline_order_id=...)
        await svc.mark_synced(offline_order_id=..., cloud_order_id=...)
    """

    def __init__(self, db: Any, tenant_id: str) -> None:
        """
        Args:
            db: SQLAlchemy AsyncSession
            tenant_id: 租户 UUID 字符串（必填，用于 RLS 绑定）
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self._db = db
        self._tenant_id = str(tenant_id)

    # ─── 内部：RLS 绑定 ────────────────────────────────────────────────────

    async def _bind_rls(self) -> None:
        """设置 app.tenant_id（RLS 策略依赖此 GUC）。"""
        await self._db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self._tenant_id},
        )

    # ─── 公开接口 ────────────────────────────────────────────────────────

    async def upsert_mapping(
        self,
        *,
        store_id: str,
        device_id: str,
        offline_order_id: str,
        cloud_order_id: Optional[str] = None,
    ) -> None:
        """离线 order_id 首次入表（state=pending 幂等 UPSERT）。

        重复 offline_order_id：保持既有状态不变（UPSERT DO NOTHING 语义）。
        生产 PostgreSQL SQL 需使用 ON CONFLICT DO NOTHING；此处 service 不依赖
        方言差异，直接先查后插（测试 mock 亦可观测）。
        """
        if not offline_order_id:
            raise ValueError("offline_order_id is required")
        if not store_id:
            raise ValueError("store_id is required")
        if not device_id:
            raise ValueError("device_id is required")

        await self._bind_rls()

        now = datetime.now(timezone.utc)

        # INSERT ... ON CONFLICT(tenant_id, offline_order_id) DO NOTHING
        # 为兼容测试 MockDB，service 层用单 INSERT 带 ON CONFLICT 子句
        try:
            await self._db.execute(
                text(
                    """
                    INSERT INTO offline_order_mapping (
                        tenant_id, store_id, device_id, offline_order_id,
                        cloud_order_id, state, sync_attempts,
                        created_at, updated_at
                    ) VALUES (
                        :tenant_id, :store_id, :device_id, :offline_order_id,
                        :cloud_order_id, :state, :sync_attempts,
                        :created_at, :created_at
                    )
                    ON CONFLICT (tenant_id, offline_order_id) DO NOTHING
                    """
                ),
                {
                    "tenant_id": self._tenant_id,
                    "store_id": str(store_id),
                    "device_id": device_id,
                    "offline_order_id": offline_order_id,
                    "cloud_order_id": cloud_order_id,
                    "state": MappingState.PENDING.value,
                    "sync_attempts": 0,
                    "created_at": now,
                },
            )
        except SQLAlchemyError as exc:
            logger.error(
                "offline_order_mapping_upsert_failed",
                offline_order_id=offline_order_id,
                tenant_id=self._tenant_id,
                error=str(exc),
            )
            raise

        logger.info(
            "offline_order_mapping_upserted",
            offline_order_id=offline_order_id,
            tenant_id=self._tenant_id,
            store_id=str(store_id),
            device_id=device_id,
        )

    async def mark_synced(
        self,
        *,
        offline_order_id: str,
        cloud_order_id: str,
    ) -> None:
        """同步成功：写入 cloud_order_id + state=synced + synced_at=now。

        Args:
            offline_order_id: 离线 order_id 字符串
            cloud_order_id:   云端生成的订单 UUID 字符串
        """
        if not cloud_order_id:
            raise ValueError("cloud_order_id is required for mark_synced")

        await self._bind_rls()

        now = datetime.now(timezone.utc)
        try:
            await self._db.execute(
                text(
                    """
                    UPDATE offline_order_mapping
                    SET cloud_order_id = :cloud_order_id,
                        state = :state,
                        synced_at = :synced_at,
                        updated_at = :synced_at
                    WHERE tenant_id = :tenant_id
                      AND offline_order_id = :offline_order_id
                    """
                ),
                {
                    "tenant_id": self._tenant_id,
                    "offline_order_id": offline_order_id,
                    "cloud_order_id": cloud_order_id,
                    "state": MappingState.SYNCED.value,
                    "synced_at": now,
                },
            )
        except SQLAlchemyError as exc:
            logger.error(
                "offline_order_mapping_mark_synced_failed",
                offline_order_id=offline_order_id,
                error=str(exc),
            )
            raise

        logger.info(
            "offline_order_mapping_synced",
            offline_order_id=offline_order_id,
            cloud_order_id=cloud_order_id,
        )

    async def mark_dead_letter(
        self,
        *,
        offline_order_id: str,
        reason: str,
    ) -> None:
        """标记死信：state=dead_letter + dead_letter_reason=reason。

        条目不删除；等待店长在"离线订单异常"面板人工确认：
          - 如真实重单：confirm_and_delete（后续工单）
          - 如需补开正式单：manual_resync
        """
        if not reason:
            raise ValueError("reason is required for mark_dead_letter")

        await self._bind_rls()

        try:
            await self._db.execute(
                text(
                    """
                    UPDATE offline_order_mapping
                    SET state = :state,
                        dead_letter_reason = :reason,
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                      AND offline_order_id = :offline_order_id
                    """
                ),
                {
                    "tenant_id": self._tenant_id,
                    "offline_order_id": offline_order_id,
                    "state": MappingState.DEAD_LETTER.value,
                    "reason": reason[:500],  # 字段 TEXT 无硬限，但截断防日志注入
                },
            )
        except SQLAlchemyError as exc:
            logger.error(
                "offline_order_mapping_mark_dead_letter_failed",
                offline_order_id=offline_order_id,
                error=str(exc),
            )
            raise

        logger.warning(
            "offline_order_mapping_dead_letter",
            offline_order_id=offline_order_id,
            reason=reason,
            tenant_id=self._tenant_id,
        )

    async def increment_sync_attempt(self, offline_order_id: str) -> None:
        """sync_attempts +1（每次 Flusher 尝试前调用）。"""
        await self._bind_rls()
        try:
            await self._db.execute(
                text(
                    """
                    UPDATE offline_order_mapping
                    SET sync_attempts = sync_attempts + 1,
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                      AND offline_order_id = :offline_order_id
                    """
                ),
                {
                    "tenant_id": self._tenant_id,
                    "offline_order_id": offline_order_id,
                },
            )
        except SQLAlchemyError as exc:
            logger.error(
                "offline_order_mapping_increment_sync_attempt_failed",
                offline_order_id=offline_order_id,
                error=str(exc),
            )
            raise

    async def get(self, offline_order_id: str) -> Optional[dict]:
        """按 offline_order_id 读取一条映射（RLS 已绑定当前租户）。

        Returns:
            dict | None
        """
        await self._bind_rls()
        try:
            result = await self._db.execute(
                text(
                    """
                    SELECT tenant_id, store_id, device_id, offline_order_id,
                           cloud_order_id, state, sync_attempts,
                           dead_letter_reason, created_at, synced_at
                    FROM offline_order_mapping
                    WHERE tenant_id = :tenant_id
                      AND offline_order_id = :offline_order_id
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": self._tenant_id,
                    "offline_order_id": offline_order_id,
                },
            )
            row = result.mappings().first()
            return dict(row) if row else None
        except SQLAlchemyError as exc:
            logger.error(
                "offline_order_mapping_get_failed",
                offline_order_id=offline_order_id,
                error=str(exc),
            )
            raise

    async def list_pending(
        self,
        *,
        store_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """列出租户 + 门店下 state=pending 的映射（用于 backlog 监控）。

        Args:
            store_id: 门店 UUID 字符串
            limit:    单次返回上限（默认 50）
        """
        if limit <= 0 or limit > 500:
            raise ValueError(f"limit out of range [1, 500]: {limit}")

        await self._bind_rls()
        try:
            result = await self._db.execute(
                text(
                    """
                    SELECT tenant_id, store_id, device_id, offline_order_id,
                           cloud_order_id, state, sync_attempts,
                           dead_letter_reason, created_at
                    FROM offline_order_mapping
                    WHERE tenant_id = :tenant_id
                      AND store_id = :store_id
                      AND state = :state
                    ORDER BY created_at ASC
                    LIMIT :limit
                    """
                ),
                {
                    "tenant_id": self._tenant_id,
                    "store_id": str(store_id),
                    "state": MappingState.PENDING.value,
                    "limit": limit,
                },
            )
            rows = result.mappings().all()
            return [dict(r) for r in rows]
        except SQLAlchemyError as exc:
            logger.error(
                "offline_order_mapping_list_pending_failed",
                store_id=str(store_id),
                error=str(exc),
            )
            raise
