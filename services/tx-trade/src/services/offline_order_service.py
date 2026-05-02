"""offline_order_service — Sprint A3 本地 SQLite 离线订单存储

当 PG 不可达时（断网 / 连接池耗尽），收银产生的订单先写入本地 SQLite。
网络恢复后由 offline_sync_api 触发重放到 PG。

设计约束（Tier 1 / §17）：
  - 三种状态：pending → synced / dead_letter
  - pending: 待同步到 PG 的订单
  - synced: 已成功写入 PG（保留供审计，TTL 后自动清理）
  - dead_letter: 重试次数超限后搁置，需人工介入
  - 每条记录有全局唯一 uuid7 字符串（cloud_order_id 候选）
  - TTL 4 小时：超过 4h 的记录在下次 write 时被清理
  - 最大重试次数 5 次（RETRY_MAX）
  - aiosqlite 单连接串行化，无需额外锁
  - 文件路径：环境变量 OFFLINE_ORDER_DB_PATH 指定，回退到 /tmp/tx-trade/offline_orders.db
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_DEFAULT_DB_DIR = "/tmp/tx-trade"  # noqa: S108 — POS local SQLite on secured Mac mini edge, path overridable via env var
_DEFAULT_DB_PATH = os.path.join(_DEFAULT_DB_DIR, "offline_orders.db")
_TTL_SECONDS: int = 4 * 3600
_RETRY_MAX: int = 5


class OfflineOrderStore:
    """本地 SQLite 离线订单存储。

    用法：
        store = OfflineOrderStore()
        await store.enqueue(order_id="...", tenant_id="...", payload={...})
        pending = await store.list_pending()
        await store.mark_synced(order_id)
    """

    def __init__(self, db_path: str | None = None, ttl_seconds: int | None = None) -> None:
        self._db_path: str = (
            db_path or os.environ.get("OFFLINE_ORDER_DB_PATH") or _DEFAULT_DB_PATH
        )
        self._ttl_seconds: int = ttl_seconds or _TTL_SECONDS
        self._conn: Any = None
        self._initialized: bool = False

    # ── 生命周期 ────────────────────────────────────────────────────────

    async def _ensure_db(self):
        """确保数据库连接已打开且表已创建。"""
        import aiosqlite

        if self._initialized and self._conn is not None:
            return self._conn

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        if self._conn is None:
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row

        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS offline_orders (
                order_id         TEXT PRIMARY KEY,  -- 离线生成的人读 order_id
                cloud_order_id   TEXT,               -- PG 侧 UUID v7（同步后填充）
                tenant_id        TEXT NOT NULL,
                store_id         TEXT,
                device_id        TEXT NOT NULL,
                state            TEXT NOT NULL DEFAULT 'pending',
                retry_count      INTEGER NOT NULL DEFAULT 0,
                last_error       TEXT,
                payload_json     TEXT NOT NULL,      -- 完整的创建订单请求体
                created_at       REAL NOT NULL,
                updated_at       REAL NOT NULL,
                synced_at        REAL
            );
            CREATE INDEX IF NOT EXISTS idx_offline_state
                ON offline_orders(state);
            CREATE INDEX IF NOT EXISTS idx_offline_tenant
                ON offline_orders(tenant_id, state);
            CREATE INDEX IF NOT EXISTS idx_offline_updated
                ON offline_orders(updated_at);
        """)
        await self._conn.commit()
        self._initialized = True
        logger.info("offline_order_db_ready", path=self._db_path)
        return self._conn

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            self._initialized = False

    # ── CRUD ────────────────────────────────────────────────────────────

    async def enqueue(
        self,
        order_id: str,
        tenant_id: str,
        device_id: str,
        payload: dict[str, Any],
        store_id: str | None = None,
        cloud_order_id: str | None = None,
    ) -> None:
        """入队一条离线订单。已存在时忽略（幂等）。"""
        conn = await self._ensure_db()
        await self._flush_ttl_expired(conn)

        now = time.time()
        await conn.execute(
            """
            INSERT OR IGNORE INTO offline_orders
                (order_id, cloud_order_id, tenant_id, store_id, device_id,
                 state, retry_count, payload_json, created_at, updated_at)
            VALUES
                (:order_id, :cloud_order_id, :tenant_id, :store_id, :device_id,
                 'pending', 0, :payload_json, :now, :now)
            """,
            {
                "order_id": order_id,
                "cloud_order_id": cloud_order_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "device_id": device_id,
                "payload_json": json.dumps(payload),
                "now": now,
            },
        )
        await conn.commit()

    async def get(self, order_id: str) -> dict[str, Any] | None:
        """按 order_id 查询记录。"""
        conn = await self._ensure_db()
        cursor = await conn.execute(
            "SELECT * FROM offline_orders WHERE order_id = :order_id",
            {"order_id": order_id},
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_pending(self, limit: int = 100) -> list[dict[str, Any]]:
        """列出所有待同步的离线订单（state='pending'），按创建时间升序。"""
        conn = await self._ensure_db()
        cursor = await conn.execute(
            "SELECT * FROM offline_orders "
            "WHERE state = 'pending' "
            "ORDER BY created_at ASC LIMIT :limit",
            {"limit": limit},
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def list_dead_letter(self, limit: int = 100) -> list[dict[str, Any]]:
        """列出所有死信订单（state='dead_letter'），按更新时间降序。"""
        conn = await self._ensure_db()
        cursor = await conn.execute(
            "SELECT * FROM offline_orders "
            "WHERE state = 'dead_letter' "
            "ORDER BY updated_at DESC LIMIT :limit",
            {"limit": limit},
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def mark_synced(self, order_id: str, cloud_order_id: str | None = None) -> None:
        """标记订单已同步到 PG。"""
        conn = await self._ensure_db()
        now = time.time()
        await conn.execute(
            """
            UPDATE offline_orders
            SET state = 'synced', cloud_order_id = COALESCE(:cloud_order_id, cloud_order_id),
                synced_at = :now, updated_at = :now
            WHERE order_id = :order_id
            """,
            {"order_id": order_id, "cloud_order_id": cloud_order_id, "now": now},
        )
        await conn.commit()

    async def mark_dead_letter(self, order_id: str, error: str) -> None:
        """标记订单为死信（同步失败超过最大重试次数）。"""
        conn = await self._ensure_db()
        now = time.time()
        await conn.execute(
            """
            UPDATE offline_orders
            SET state = 'dead_letter', last_error = :error, updated_at = :now
            WHERE order_id = :order_id
            """,
            {"order_id": order_id, "error": error, "now": now},
        )
        await conn.commit()

    async def increment_retry(self, order_id: str, error: str) -> str:
        """增加重试计数。超过 RETRY_MAX 时自动转为 dead_letter。

        Returns:
            更新后的 state: 'pending' | 'dead_letter'
        """
        conn = await self._ensure_db()
        now = time.time()

        # 读当前记录
        cursor = await conn.execute(
            "SELECT retry_count, state FROM offline_orders WHERE order_id = :order_id",
            {"order_id": order_id},
        )
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"offline order not found: {order_id}")
        if row["state"] != "pending":
            return row["state"]

        new_retry = row["retry_count"] + 1
        if new_retry >= _RETRY_MAX:
            new_state = "dead_letter"
        else:
            new_state = "pending"

        await conn.execute(
            """
            UPDATE offline_orders
            SET retry_count = :retry_count, state = :state,
                last_error = :error, updated_at = :now
            WHERE order_id = :order_id
            """,
            {
                "order_id": order_id,
                "retry_count": new_retry,
                "state": new_state,
                "error": error,
                "now": now,
            },
        )
        await conn.commit()
        return new_state

    async def manual_retry(self, order_id: str) -> None:
        """人工重试：将 dead_letter 重新置为 pending，重置重试计数。"""
        conn = await self._ensure_db()
        now = time.time()
        await conn.execute(
            """
            UPDATE offline_orders
            SET state = 'pending', retry_count = 0, last_error = NULL, updated_at = :now
            WHERE order_id = :order_id AND state = 'dead_letter'
            """,
            {"order_id": order_id, "now": now},
        )
        await conn.commit()

    async def count_pending(self) -> int:
        """返回待同步订单数量。"""
        conn = await self._ensure_db()
        cursor = await conn.execute(
            "SELECT COUNT(*) AS cnt FROM offline_orders WHERE state = 'pending'",
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def count_dead_letter(self) -> int:
        """返回死信订单数量。"""
        conn = await self._ensure_db()
        cursor = await conn.execute(
            "SELECT COUNT(*) AS cnt FROM offline_orders WHERE state = 'dead_letter'",
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def _flush_ttl_expired(self, conn) -> int:
        """清理超过 TTL 的陈旧记录（已 synced 或超过 4h 的 pending/dead_letter）。"""
        cutoff = time.time() - self._ttl_seconds
        cursor = await conn.execute(
            "DELETE FROM offline_orders WHERE updated_at < :cutoff",
            {"cutoff": cutoff},
        )
        await conn.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.info("offline_order_ttl_flush", expired_count=deleted)
        return deleted
