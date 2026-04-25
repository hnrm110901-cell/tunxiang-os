"""offline_order_mapping_service — Sprint A3 offline_order_mapping CRUD

职责：
  - upsert_mapping      — 离线 order_id 首次入表（state=pending）
  - mark_synced         — 同步成功，写入 cloud_order_id + state=synced
  - mark_dead_letter    — 多次补发失败，state=dead_letter（保留等人工确认）
  - increment_sync_attempt — 每次同步尝试累加 sync_attempts（legacy；保留兼容）
  - increment_attempts  — 同步失败累加 sync_attempts + last_error_message，返回新值
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
    ) -> bool:
        """同步成功：写入 cloud_order_id + state=synced + synced_at=now。

        **Tier1 资金安全约束（A3 §19 致命级 #2）**：
          UPDATE 语句必须带 `WHERE state='pending'` 守护，否则在以下场景将
          导致同一离线单对应两个云端订单 → 资金双扣费：
            1. 服务端首次调用 mark_synced 成功 → state=synced, cloud_order_id=A
            2. 响应在网络层丢失，客户端带原 offline_order_id 重试
            3. upsert_mapping ON CONFLICT DO NOTHING（保留既有 synced 行）
            4. 若此处无 state='pending' 守护 → 用新生成的 cloud_order_id=B
               覆盖原 cloud_order_id=A → 对账时同一离线单关联两个云端订单
            5. 后续支付/打票按 cloud_order_id=B 执行，cloud_order_id=A 也已落账

          加上守护后：state 已是 synced/dead_letter 的条目 UPDATE 0 行 →
          返回 False；调用方应跳过新生成 cloud_order_id 的逻辑，复用既有的。

        Args:
            offline_order_id: 离线 order_id 字符串
            cloud_order_id:   云端生成的订单 UUID 字符串

        Returns:
            bool: True  = 确实把 pending → synced 推进了一步（首次成功）
                  False = 条目已是 synced/dead_letter（幂等 no-op，调用方应
                          通过 get() 读取既有 cloud_order_id 而非重新生成）
        """
        if not cloud_order_id:
            raise ValueError("cloud_order_id is required for mark_synced")

        await self._bind_rls()

        now = datetime.now(timezone.utc)
        try:
            result = await self._db.execute(
                text(
                    """
                    UPDATE offline_order_mapping
                    SET cloud_order_id = :cloud_order_id,
                        state = :state,
                        synced_at = :synced_at,
                        updated_at = :synced_at
                    WHERE tenant_id = :tenant_id
                      AND offline_order_id = :offline_order_id
                      AND state = :pending_state
                    """
                ),
                {
                    "tenant_id": self._tenant_id,
                    "offline_order_id": offline_order_id,
                    "cloud_order_id": cloud_order_id,
                    "state": MappingState.SYNCED.value,
                    "pending_state": MappingState.PENDING.value,
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

        # rowcount == 0 → 条目不在 pending（可能已 synced 或 dead_letter）
        # 此为幂等 no-op，不是错误：上层重试场景的正确响应是返回既有 cloud_order_id
        rowcount = getattr(result, "rowcount", None)
        advanced = rowcount is None or rowcount >= 1

        if not advanced:
            logger.warning(
                "offline_order_mapping_mark_synced_noop",
                offline_order_id=offline_order_id,
                tenant_id=self._tenant_id,
                attempted_cloud_order_id=cloud_order_id,
                reason="state_not_pending",
            )
            return False

        logger.info(
            "offline_order_mapping_synced",
            offline_order_id=offline_order_id,
            cloud_order_id=cloud_order_id,
        )
        return True

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

    # ─── A3 §19 P1：dead_letter 触发链路 + 店长人工面板支撑接口 ─────────────

    async def increment_attempts(
        self,
        *,
        offline_order_id: str,
        last_error: Optional[str] = None,
    ) -> int:
        """同步失败：sync_attempts +1 并刷新 last_error_message，返回新值。

        与 legacy `increment_sync_attempt` 区别：
          - 新 API 返回 RETURNING 的 sync_attempts 新值（路由层用其判断
            是否达 DEAD_LETTER_MAX_ATTEMPTS 阈值）
          - 接受 last_error 参数：每次失败都记录最近错误简述（500 字符截断）

        Args:
            offline_order_id: 离线 order_id 字符串
            last_error: 失败原因简述（如 'edge_unreachable' / 'pos_adapter_500'）

        Returns:
            int: 自增后的 sync_attempts 值（用于阈值判断）。条目不存在时返回 0。

        Note:
            UPDATE 不带 state 守护：
              - dead_letter 条目按理不会再触发 increment（路由层不会调用）
              - 但若并发场景下 dead_letter 已设置，sync_attempts 仍累加无害
                （只是计数失真，由 dead_letter_reason 主导决策）
        """
        if not offline_order_id:
            raise ValueError("offline_order_id is required")

        await self._bind_rls()
        try:
            result = await self._db.execute(
                text(
                    """
                    UPDATE offline_order_mapping
                    SET sync_attempts = sync_attempts + 1,
                        last_error_message = :last_error,
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                      AND offline_order_id = :offline_order_id
                    RETURNING sync_attempts
                    """
                ),
                {
                    "tenant_id": self._tenant_id,
                    "offline_order_id": offline_order_id,
                    "last_error": (last_error or "")[:500] or None,
                },
            )
        except SQLAlchemyError as exc:
            logger.error(
                "offline_order_mapping_increment_attempts_failed",
                offline_order_id=offline_order_id,
                error=str(exc),
            )
            raise

        # MockDB / 真实 PG 都返回 rowcount；新值通过 RETURNING 抽出
        try:
            row = result.mappings().first() if hasattr(result, "mappings") else None
        except Exception:  # noqa: BLE001 — Mock 兼容
            row = None
        if row and "sync_attempts" in row:
            return int(row["sync_attempts"])

        # 兜底：RETURNING 不可用时回查一次
        existing = await self.get(offline_order_id)
        return int(existing.get("sync_attempts", 0)) if existing else 0

