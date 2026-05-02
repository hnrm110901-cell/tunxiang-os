"""saga_buffer_service — Sprint A2 本地 SQLite Saga 状态缓冲

PaymentSagaService 的 PG 写入失败时（断网 / 连接池耗尽 / PG 宕机），
降级到本地 aiosqlite 缓冲。网络恢复后由 recover_pending_sagas 扫描缓冲并重放到 PG。

设计约束（Tier 1 / §17）：
  - 只缓冲当前进行中的 Saga 状态，不替代 PG payment_sagas 表
  - 每条记录以 saga_id（UUID）为主键，覆盖写（upsert）
  - TTL 4 小时：超过 4h 的记录在下次 write 时被清理（避免 SQLite 无限膨胀）
  - aiosqlite 是单连接串行化，无需额外锁
  - 文件路径：优先由环境变量 SAGA_BUFFER_PATH 指定，回退到 /tmp/tx-trade/saga_buffer.db
  - 首次使用自动创建表，无外部依赖迁移

A2 集成点：
  PaymentSagaService.__init__()  注入 SagaBufferService（可选，默认 None = 未启用）
  PaymentSagaService.execute()   _update_step / _set_payment_id / saga INSERT
                                在 PG SQLAlchemyError 时 fallback 到 buffer.upsert_saga()
  PaymentSagaService.recover_pending_sagas()
                                同时扫描 buffer.list_pending() 执行恢复
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# 默认 SQLite 缓冲路径
_DEFAULT_BUFFER_DIR = "/tmp/tx-trade"  # noqa: S108 — POS local SQLite on secured Mac mini edge, path overridable via env var
_DEFAULT_BUFFER_PATH = os.path.join(_DEFAULT_BUFFER_DIR, "saga_buffer.db")

# 4 小时 TTL（秒）
_SAGA_BUFFER_TTL_SEC: int = 4 * 3600


class SagaBufferService:
    """本地 SQLite Saga 状态缓冲。

    用法：
        buffer = SagaBufferService()
        await buffer.upsert_saga(saga_id, tenant_id, step="paying", ...)
        saga = await buffer.get_saga(saga_id)
    """

    def __init__(self, db_path: str | None = None, ttl_seconds: int | None = None) -> None:
        self._db_path: str = (
            db_path or os.environ.get("SAGA_BUFFER_PATH") or _DEFAULT_BUFFER_PATH
        )
        self._ttl_seconds: int = ttl_seconds or _SAGA_BUFFER_TTL_SEC
        self._conn: Any = None  # aiosqlite.Connection（延迟初始化）
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
            CREATE TABLE IF NOT EXISTS saga_buffer (
                saga_id              TEXT PRIMARY KEY,
                tenant_id            TEXT NOT NULL,
                order_id             TEXT,
                step                 TEXT NOT NULL DEFAULT 'validating',
                payment_id           TEXT,
                payment_method       TEXT,
                payment_amount_fen   INTEGER,
                idempotency_key      TEXT,
                compensation_reason  TEXT,
                created_at           REAL NOT NULL,
                updated_at           REAL NOT NULL,
                payload_json         TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_saga_buf_tenant_step
                ON saga_buffer(tenant_id, step);
            CREATE INDEX IF NOT EXISTS idx_saga_buf_idempotency
                ON saga_buffer(idempotency_key);
            CREATE INDEX IF NOT EXISTS idx_saga_buf_updated
                ON saga_buffer(updated_at);
        """)
        await self._conn.commit()
        self._initialized = True
        logger.info("saga_buffer_db_ready", path=self._db_path)
        return self._conn

    async def close(self) -> None:
        """关闭 SQLite 连接。"""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            self._initialized = False

    # ── CRUD ────────────────────────────────────────────────────────────

    async def upsert_saga(
        self,
        saga_id: str,
        tenant_id: str,
        order_id: str | None = None,
        step: str = "validating",
        payment_id: str | None = None,
        payment_method: str | None = None,
        payment_amount_fen: int | None = None,
        idempotency_key: str | None = None,
        compensation_reason: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """插入或更新一条 Saga 缓冲记录。覆盖写（upsert）。

        在 INSERT 前自动清理超过 TTL 的陈旧记录（轻量 housekeeping）。
        """
        conn = await self._ensure_db()

        # 轻量 housekeeping：先清理过期记录
        await self._flush_ttl_expired(conn)

        now = time.time()
        await conn.execute(
            """
            INSERT INTO saga_buffer
                (saga_id, tenant_id, order_id, step, payment_id,
                 payment_method, payment_amount_fen, idempotency_key,
                 compensation_reason, created_at, updated_at, payload_json)
            VALUES
                (:saga_id, :tenant_id, :order_id, :step, :payment_id,
                 :payment_method, :payment_amount_fen, :idempotency_key,
                 :compensation_reason, :now, :now, :payload_json)
            ON CONFLICT(saga_id) DO UPDATE SET
                step                = excluded.step,
                payment_id          = excluded.payment_id,
                compensation_reason = excluded.compensation_reason,
                payload_json        = excluded.payload_json,
                updated_at          = excluded.updated_at
            """,
            {
                "saga_id": saga_id,
                "tenant_id": tenant_id,
                "order_id": order_id,
                "step": step,
                "payment_id": payment_id,
                "payment_method": payment_method,
                "payment_amount_fen": payment_amount_fen,
                "idempotency_key": idempotency_key,
                "compensation_reason": compensation_reason,
                "now": now,
                "payload_json": json.dumps(payload) if payload else None,
            },
        )
        await conn.commit()

    async def get_saga(self, saga_id: str) -> dict[str, Any] | None:
        """按 saga_id 查询缓冲记录。"""
        conn = await self._ensure_db()
        cursor = await conn.execute(
            "SELECT * FROM saga_buffer WHERE saga_id = :saga_id",
            {"saga_id": saga_id},
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def find_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        """按幂等键查询最近的一条 Saga 缓冲记录。"""
        conn = await self._ensure_db()
        cursor = await conn.execute(
            "SELECT * FROM saga_buffer WHERE idempotency_key = :key ORDER BY created_at DESC LIMIT 1",
            {"key": idempotency_key},
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_pending(self, older_than_seconds: int = 300) -> list[dict[str, Any]]:
        """列出所有未完成的悬空 Saga（step='paying' 或 'completing' 且超过指定时间未更新）。

        Args:
            older_than_seconds: 超时秒数（默认 300s = 5min，与 PG recover_pending 阈值一致）
        """
        conn = await self._ensure_db()
        cutoff = time.time() - older_than_seconds
        cursor = await conn.execute(
            "SELECT * FROM saga_buffer "
            "WHERE step IN ('paying', 'completing') AND updated_at < :cutoff "
            "ORDER BY updated_at ASC",
            {"cutoff": cutoff},
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def _flush_ttl_expired(self, conn) -> int:
        """清理超过 TTL 的陈旧记录。返回删除条数。"""
        cutoff = time.time() - self._ttl_seconds
        cursor = await conn.execute(
            "DELETE FROM saga_buffer WHERE updated_at < :cutoff",
            {"cutoff": cutoff},
        )
        await conn.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.info("saga_buffer_ttl_flush", expired_count=deleted)
        return deleted

    async def count(self) -> int:
        """返回当前缓冲中的记录总数。"""
        conn = await self._ensure_db()
        cursor = await conn.execute("SELECT COUNT(*) AS cnt FROM saga_buffer")
        row = await cursor.fetchone()
        return row["cnt"] if row else 0
