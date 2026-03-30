"""出单模式配置服务

支持两种出单模式：
  IMMEDIATE    — 下单即推送（默认）：创建订单后立即将任务分配到各档口 KDS
  POST_PAYMENT — 收银核销后推送：订单支付完成后才将任务推送到 KDS

# SCHEMA SQL
-- CREATE TABLE IF NOT EXISTS store_push_configs (
--   id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
--   tenant_id   UUID        NOT NULL,
--   store_id    UUID        NOT NULL,
--   push_mode   TEXT        NOT NULL DEFAULT 'immediate',
--   created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
--   updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
--   UNIQUE(tenant_id, store_id)
-- );
-- ALTER TABLE store_push_configs ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY store_push_configs_tenant ON store_push_configs
--   USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
"""
import uuid
from enum import Enum
from typing import Optional

import structlog
from sqlalchemy import select, text, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# ─── 枚举 ───

class OrderPushMode(str, Enum):
    """出单推送模式。"""
    IMMEDIATE    = "immediate"     # 下单即推
    POST_PAYMENT = "post_payment"  # 收银核销后推


_DEFAULT_MODE = OrderPushMode.IMMEDIATE

# ─── 内部查询辅助 ───

async def _fetch_mode_row(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[str]:
    """从 store_push_configs 表读取 push_mode 字段。

    Returns:
        push_mode 字符串，或 None（记录不存在时）

    Raises:
        ValueError: store_id / tenant_id 格式错误
    """
    try:
        tid = uuid.UUID(tenant_id)
        sid = uuid.UUID(store_id)
    except ValueError as exc:
        raise ValueError(f"无效的 store_id 或 tenant_id: {exc}") from exc

    stmt = text(
        "SELECT push_mode FROM store_push_configs "
        "WHERE tenant_id = :tid AND store_id = :sid AND TRUE LIMIT 1"
    )
    row = (await db.execute(stmt, {"tid": tid, "sid": sid})).one_or_none()
    return row[0] if row else None


# ─── 服务类 ───

class OrderPushConfigService:
    """门店出单推送模式配置服务。

    所有方法为 async classmethod，无需实例化。
    """

    @classmethod
    async def get_store_mode(
        cls,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> OrderPushMode:
        """读取门店出单模式，记录不存在时返回默认值 IMMEDIATE。

        Args:
            store_id:  门店 UUID（str）
            tenant_id: 租户 UUID（str）
            db:        异步数据库会话

        Returns:
            OrderPushMode 枚举值

        Raises:
            ValueError: store_id / tenant_id 格式错误
        """
        raw = await _fetch_mode_row(store_id, tenant_id, db)
        if raw is None:
            logger.bind(store_id=store_id).debug(
                "order_push_config.get_store_mode.default"
            )
            return _DEFAULT_MODE

        try:
            return OrderPushMode(raw)
        except ValueError:
            logger.bind(store_id=store_id, raw=raw).warning(
                "order_push_config.get_store_mode.unknown_value_fallback"
            )
            return _DEFAULT_MODE

    @classmethod
    async def set_store_mode(
        cls,
        store_id: str,
        mode: OrderPushMode,
        tenant_id: str,
        db: AsyncSession,
    ) -> None:
        """写入或更新门店出单模式（UPSERT）。

        Args:
            store_id:  门店 UUID（str）
            mode:      OrderPushMode 枚举值
            tenant_id: 租户 UUID（str）
            db:        异步数据库会话

        Raises:
            ValueError: store_id / tenant_id 格式错误
        """
        try:
            tid = uuid.UUID(tenant_id)
            sid = uuid.UUID(store_id)
        except ValueError as exc:
            raise ValueError(f"无效的 store_id 或 tenant_id: {exc}") from exc

        upsert_sql = text(
            """
            INSERT INTO store_push_configs (tenant_id, store_id, push_mode, updated_at)
            VALUES (:tid, :sid, :mode, NOW())
            ON CONFLICT (tenant_id, store_id)
            DO UPDATE SET push_mode = EXCLUDED.push_mode,
                          updated_at = NOW()
            """
        )
        await db.execute(upsert_sql, {"tid": tid, "sid": sid, "mode": mode.value})
        await db.flush()

        logger.bind(store_id=store_id, mode=mode.value).info(
            "order_push_config.set_store_mode.ok"
        )

    @classmethod
    async def should_push_on_order(
        cls,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> bool:
        """判断下单时是否应立即推送到 KDS。

        Returns:
            True  — IMMEDIATE 模式，下单即推
            False — POST_PAYMENT 模式，等收银完成后再推

        Raises:
            ValueError: store_id / tenant_id 格式错误
        """
        mode = await cls.get_store_mode(store_id, tenant_id, db)
        return mode == OrderPushMode.IMMEDIATE

    @classmethod
    async def push_deferred_tasks(
        cls,
        order_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> int:
        """POST_PAYMENT 模式：收银完成后将该订单的 pending KDS 任务激活。

        将 kds_tasks.status = 'pending' 且关联到本订单明细的任务
        更新为 'cooking'（进入档口活跃队列），并广播 task_activated 事件。

        Args:
            order_id:  订单 UUID（str）
            tenant_id: 租户 UUID（str）
            db:        异步数据库会话

        Returns:
            激活的任务数量

        Raises:
            ValueError: order_id / tenant_id 格式错误
        """
        try:
            tid = uuid.UUID(tenant_id)
            oid = uuid.UUID(order_id)
        except ValueError as exc:
            raise ValueError(f"无效的 order_id 或 tenant_id: {exc}") from exc

        log = logger.bind(order_id=order_id, tenant_id=tenant_id)

        # 查找该订单下所有 pending 任务
        # kds_tasks 通过 order_item_id 关联 order_items，order_items 通过 order_id 关联
        find_stmt = text(
            """
            SELECT kt.id
            FROM kds_tasks kt
            JOIN order_items oi ON oi.id = kt.order_item_id
            WHERE oi.order_id = :oid
              AND kt.tenant_id = :tid
              AND kt.status = 'pending'
              AND kt.is_deleted = FALSE
            """
        )
        rows = (await db.execute(find_stmt, {"oid": oid, "tid": tid})).all()
        task_ids = [row[0] for row in rows]

        if not task_ids:
            log.info("order_push_config.push_deferred_tasks.no_pending_tasks")
            return 0

        # 批量更新为 cooking
        update_stmt = text(
            """
            UPDATE kds_tasks
               SET status     = 'cooking',
                   started_at = NOW(),
                   updated_at = NOW()
             WHERE id = ANY(:ids)
               AND tenant_id = :tid
               AND status = 'pending'
            """
        )
        await db.execute(update_stmt, {"ids": task_ids, "tid": tid})
        await db.flush()

        count = len(task_ids)
        log.info("order_push_config.push_deferred_tasks.activated", count=count)

        # 广播激活事件（逐任务推送，方便前端按任务处理）
        try:
            import httpx as _httpx
            import os as _os

            mac_url = _os.getenv("MAC_STATION_URL", "http://localhost:8000")
            async with _httpx.AsyncClient(timeout=3) as client:
                await client.post(
                    f"{mac_url}/api/v1/kds/broadcast",
                    json={
                        "type": "tasks_activated",
                        "order_id": order_id,
                        "tenant_id": tenant_id,
                        "task_ids": [str(t) for t in task_ids],
                        "count": count,
                    },
                )
        except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
            log.warning(
                "order_push_config.push_deferred_tasks.broadcast_failed",
                exc=str(exc),
            )

        return count
