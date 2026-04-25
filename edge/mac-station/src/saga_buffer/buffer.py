"""SagaBuffer — Sprint A2 Saga 本地 SQLite 缓冲（aiosqlite 异步）

断网 4h 期间，收银端推送到 Mac mini 的结算请求先入本地 SQLite，
恢复联网后由 SagaFlusher 补发到 tx-trade `/api/v1/settle/retry`。

设计约束（CLAUDE.md §17 Tier1 零容忍）：
  - aiosqlite 全异步，不阻塞主业务（禁止 sqlite3 同步写）
  - 同一 idempotency_key（契约：`settle:{orderId}`）重复 enqueue → UPSERT 复用 saga_id
  - 4h TTL（expires_at = created_at + 14400s）
  - 超期未补发 → mark_dead_letter，不自动删除（等人工确认）
  - tenant_id 行级隔离 + device_id 隔离（文件层 + 行级双隔离）
  - /var/tunxiang/saga_buffer.db 不可写时降级到内存字典（disk_io_error warn）
    — 内存降级模式不持久化，重启丢失，仅保证进程不崩溃（对齐 A1 R1）

不改动：
  - services/tx-trade/src/services/payment_saga_service.py._PENDING_TIMEOUT_MINUTES
    — 保持 5min，与前端 3s soft timeout 是不同时间轴

状态机：pending → flushing → sent / dead_letter

关联：edge/mac-mini/offline_buffer.py 已有 aiosqlite 样板可对照
Flag：edge.payment.saga_buffer（默认 off）
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


# ─── 常量 ─────────────────────────────────────────────────────────────────────

# 生产路径（Docker volume 映射点 — §15 风险 #4）
DEFAULT_BUFFER_PATH = Path("/var/tunxiang/saga_buffer.db")

# 4h TTL（14400 秒）— Sprint 规划 L34 明确约定
TTL_SECONDS = 4 * 60 * 60

# 状态机枚举
_STATE_PENDING = "pending"
_STATE_FLUSHING = "flushing"
_STATE_SENT = "sent"
_STATE_DEAD_LETTER = "dead_letter"

# SQLite DDL（aiosqlite 兼容：idempotency_key 作 PRIMARY KEY 实现 UPSERT 去重）
_DDL = """
CREATE TABLE IF NOT EXISTS saga_buffer (
    idempotency_key TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    store_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    saga_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at INTEGER,
    state TEXT NOT NULL DEFAULT 'pending',
    last_error TEXT,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_saga_buffer_state_expiry
    ON saga_buffer(state, expires_at);

CREATE INDEX IF NOT EXISTS idx_saga_buffer_tenant_store
    ON saga_buffer(tenant_id, store_id);
"""


class SagaBufferState:
    """状态常量，便于外部模块 import."""

    PENDING = _STATE_PENDING
    FLUSHING = _STATE_FLUSHING
    SENT = _STATE_SENT
    DEAD_LETTER = _STATE_DEAD_LETTER


# ─── 数据模型 ─────────────────────────────────────────────────────────────────


@dataclass
class SagaBufferEntry:
    """SQLite 一行的结构化表示。"""

    idempotency_key: str
    tenant_id: str
    store_id: str
    device_id: str
    saga_id: str
    payload: dict
    attempts: int
    last_attempt_at: Optional[int]
    state: str
    last_error: Optional[str]
    created_at: int
    expires_at: int


@dataclass
class SagaBufferStats:
    """缓冲队列健康度统计（供 Flusher 回传 saga_buffer_meta）。"""

    pending_count: int = 0
    flushing_count: int = 0
    sent_count: int = 0
    dead_letter_count: int = 0
    oldest_pending_at: Optional[int] = None
    size_bytes: int = 0
    mode: str = "sqlite"  # sqlite / memory（磁盘满降级）


# ─── SagaBuffer 实现 ─────────────────────────────────────────────────────────


class SagaBuffer:
    """Saga 本地 SQLite 缓冲。

    使用方式：
        buf = SagaBuffer(device_id="pos-001")
        await buf.initialize()
        await buf.enqueue(
            idempotency_key="settle:O-100",
            tenant_id=tid, store_id=sid,
            saga_id=uuid.uuid4().hex, payload={"amount_fen": 8800},
        )
        ready = await buf.flush_ready()   # 按 state=pending 扫表
        for entry in ready:
            ... POST 到 tx-trade ...
            await buf.mark_sent(entry.idempotency_key)
    """

    def __init__(
        self,
        device_id: str,
        db_path: Optional[Path] = None,
        ttl_seconds: int = TTL_SECONDS,
        clock: Optional[Any] = None,
    ) -> None:
        self._device_id = device_id
        self._db_path = Path(db_path) if db_path else DEFAULT_BUFFER_PATH
        self._ttl = ttl_seconds
        self._clock = clock or time.time
        self._lock = asyncio.Lock()
        self._initialized = False
        # 磁盘写满降级：内存字典 {idempotency_key: SagaBufferEntry}
        self._memory_mode = False
        self._memory_rows: dict[str, SagaBufferEntry] = {}
        # 持久 aiosqlite 连接（Flusher 单例持有，避免每次 open/close 的开销）
        self._conn = None

    # ─── 初始化 ───────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """建表 + 设 WAL 模式。路径不可写时降级到内存模式。"""
        if self._initialized:
            return

        # 路径预检（风险 #4：容器卷权限）
        parent = self._db_path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "saga_buffer_parent_mkdir_failed_fallback_memory",
                path=str(self._db_path),
                error=str(exc),
            )
            self._memory_mode = True
            self._initialized = True
            return

        if not os.access(parent, os.W_OK):
            logger.warning(
                "saga_buffer_parent_not_writable_fallback_memory",
                path=str(self._db_path),
            )
            self._memory_mode = True
            self._initialized = True
            return

        try:
            import aiosqlite

            conn = await aiosqlite.connect(str(self._db_path))
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.executescript(_DDL)
            await conn.commit()
            self._conn = conn

            # 启动时复位 flushing → pending（防进程崩溃后死单泄漏）
            # 原 flushing 状态实际归属已丢失（写该状态的 worker 已死），
            # 安全做法是重新 enqueue 让下一轮 flush_ready 重新选中。
            now = int(self._clock())
            cur = await conn.execute(
                "UPDATE saga_buffer "
                "SET state = 'pending', last_attempt_at = ? "
                "WHERE state = 'flushing'",
                (now,),
            )
            reset_count = cur.rowcount or 0
            await cur.close()
            await conn.commit()
            if reset_count > 0:
                logger.warning(
                    "saga_buffer.flushing_reset_on_startup",
                    count=reset_count,
                    device_id=self._device_id,
                )
        except (OSError, ImportError) as exc:
            # 磁盘写满 / 权限异常 / aiosqlite 缺失 → 降级（A1 R1 disk_io_error）
            logger.warning(
                "saga_buffer_init_failed_fallback_memory",
                path=str(self._db_path),
                error=str(exc),
            )
            self._memory_mode = True

        self._initialized = True
        logger.info(
            "saga_buffer_initialized",
            path=str(self._db_path),
            device_id=self._device_id,
            mode="memory" if self._memory_mode else "sqlite",
        )

    # ─── enqueue / UPSERT 幂等 ────────────────────────────────────────────────

    async def enqueue(
        self,
        *,
        idempotency_key: str,
        tenant_id: str,
        store_id: str,
        saga_id: str,
        payload: dict,
    ) -> SagaBufferEntry:
        """入队一条结算请求。

        同一 idempotency_key 已存在（state != sent）→ UPSERT 复用 saga_id，
        防止前端 abort 重试触发 saga 双扣费（A1 合约 R2）。

        已 sent 的记录不会被覆盖：直接返回既有条目供上层复用结果。
        """
        if not self._initialized:
            await self.initialize()
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not store_id:
            raise ValueError("store_id is required")
        if not saga_id:
            raise ValueError("saga_id is required")

        now = int(self._clock())
        expires_at = now + self._ttl
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)

        async with self._lock:
            if self._memory_mode:
                existing = self._memory_rows.get(idempotency_key)
                if existing is not None and existing.state != _STATE_SENT:
                    # 复用之前 saga_id（防双扣费）
                    logger.info(
                        "saga_buffer_enqueue_dedup_memory",
                        idempotency_key=idempotency_key,
                        existing_saga_id=existing.saga_id,
                    )
                    return existing
                if existing is not None and existing.state == _STATE_SENT:
                    return existing
                entry = SagaBufferEntry(
                    idempotency_key=idempotency_key,
                    tenant_id=tenant_id,
                    store_id=store_id,
                    device_id=self._device_id,
                    saga_id=saga_id,
                    payload=payload,
                    attempts=0,
                    last_attempt_at=None,
                    state=_STATE_PENDING,
                    last_error=None,
                    created_at=now,
                    expires_at=expires_at,
                )
                self._memory_rows[idempotency_key] = entry
                return entry

            entry = await self._enqueue_sqlite(
                idempotency_key=idempotency_key,
                tenant_id=tenant_id,
                store_id=store_id,
                saga_id=saga_id,
                payload=payload,
                payload_json=payload_json,
                created_at=now,
                expires_at=expires_at,
            )
            return entry

    async def _enqueue_sqlite(
        self,
        *,
        idempotency_key: str,
        tenant_id: str,
        store_id: str,
        saga_id: str,
        payload: dict,
        payload_json: str,
        created_at: int,
        expires_at: int,
    ) -> SagaBufferEntry:
        try:
            db = self._conn
            # 查询是否存在
            cur = await db.execute(
                "SELECT idempotency_key, tenant_id, store_id, device_id, "
                "       saga_id, payload_json, attempts, last_attempt_at, "
                "       state, last_error, created_at, expires_at "
                "FROM saga_buffer WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            row = await cur.fetchone()
            await cur.close()
            if row is not None:
                existing = _row_to_entry(row)
                if existing.state != _STATE_SENT:
                    logger.info(
                        "saga_buffer_enqueue_dedup",
                        idempotency_key=idempotency_key,
                        existing_saga_id=existing.saga_id,
                        state=existing.state,
                    )
                return existing

            await db.execute(
                "INSERT INTO saga_buffer "
                "(idempotency_key, tenant_id, store_id, device_id, saga_id, "
                " payload_json, attempts, state, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, 'pending', ?, ?)",
                (
                    idempotency_key,
                    tenant_id,
                    store_id,
                    self._device_id,
                    saga_id,
                    payload_json,
                    created_at,
                    expires_at,
                ),
            )
            await db.commit()
        except OSError as exc:
            # 运行期磁盘满：降级当前这条到内存并标记 memory_mode
            logger.error(
                "saga_buffer_enqueue_disk_io_error_fallback_memory",
                idempotency_key=idempotency_key,
                error=str(exc),
                exc_info=True,
            )
            self._memory_mode = True
            entry = SagaBufferEntry(
                idempotency_key=idempotency_key,
                tenant_id=tenant_id,
                store_id=store_id,
                device_id=self._device_id,
                saga_id=saga_id,
                payload=payload,
                attempts=0,
                last_attempt_at=None,
                state=_STATE_PENDING,
                last_error=None,
                created_at=created_at,
                expires_at=expires_at,
            )
            self._memory_rows[idempotency_key] = entry
            return entry

        return SagaBufferEntry(
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
            store_id=store_id,
            device_id=self._device_id,
            saga_id=saga_id,
            payload=payload,
            attempts=0,
            last_attempt_at=None,
            state=_STATE_PENDING,
            last_error=None,
            created_at=created_at,
            expires_at=expires_at,
        )

    # ─── flush_ready / mark_* ─────────────────────────────────────────────────

    async def flush_ready(
        self,
        *,
        tenant_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[SagaBufferEntry]:
        """扫描 state=pending 且未到期条目，返回供 Flusher 补发。

        tenant_id 过滤：不同租户 Worker 只取自己租户的条目（行级隔离）。
        tenant_id=None 仅供测试或跨租户统计用，生产 Flusher 必须传入。
        """
        if not self._initialized:
            await self.initialize()
        now = int(self._clock())

        async with self._lock:
            if self._memory_mode:
                rows = [
                    e for e in self._memory_rows.values()
                    if e.state == _STATE_PENDING and e.expires_at > now
                    and (tenant_id is None or e.tenant_id == tenant_id)
                ]
                rows.sort(key=lambda e: e.created_at)
                return rows[:limit]

            db = self._conn
            if tenant_id is None:
                cur = await db.execute(
                    "SELECT idempotency_key, tenant_id, store_id, device_id, "
                    "       saga_id, payload_json, attempts, last_attempt_at, "
                    "       state, last_error, created_at, expires_at "
                    "FROM saga_buffer "
                    "WHERE state = 'pending' AND expires_at > ? "
                    "ORDER BY created_at ASC LIMIT ?",
                    (now, limit),
                )
            else:
                cur = await db.execute(
                    "SELECT idempotency_key, tenant_id, store_id, device_id, "
                    "       saga_id, payload_json, attempts, last_attempt_at, "
                    "       state, last_error, created_at, expires_at "
                    "FROM saga_buffer "
                    "WHERE state = 'pending' AND expires_at > ? "
                    "  AND tenant_id = ? "
                    "ORDER BY created_at ASC LIMIT ?",
                    (now, tenant_id, limit),
                )
            rows = await cur.fetchall()
            await cur.close()
            return [_row_to_entry(r) for r in rows]

    async def mark_flushing(self, idempotency_key: str) -> None:
        """标记 flushing 时同步打 last_attempt_at 时间戳，
        供 SagaFlusher.reset_stuck_flushing 计算卡死时长。"""
        if not self._initialized:
            await self.initialize()
        now = int(self._clock())
        async with self._lock:
            if self._memory_mode:
                e = self._memory_rows.get(idempotency_key)
                if e is None:
                    return
                e.state = _STATE_FLUSHING
                e.last_attempt_at = now
                return

            try:
                db = self._conn
                await db.execute(
                    "UPDATE saga_buffer "
                    "SET state = 'flushing', last_attempt_at = ? "
                    "WHERE idempotency_key = ?",
                    (now, idempotency_key),
                )
                await db.commit()
            except OSError as exc:
                logger.error(
                    "saga_buffer_mark_flushing_disk_io_error",
                    idempotency_key=idempotency_key,
                    error=str(exc),
                )

    async def mark_sent(self, idempotency_key: str) -> None:
        await self._update_state(idempotency_key, _STATE_SENT)

    async def mark_failed(self, idempotency_key: str, error_message: str) -> None:
        """补发失败：attempts++，last_error 记录，状态回 pending 等下轮。"""
        if not self._initialized:
            await self.initialize()
        now = int(self._clock())
        async with self._lock:
            if self._memory_mode:
                e = self._memory_rows.get(idempotency_key)
                if e is None:
                    return
                e.attempts += 1
                e.last_attempt_at = now
                e.last_error = error_message
                e.state = _STATE_PENDING
                return

            try:
                db = self._conn
                await db.execute(
                    "UPDATE saga_buffer "
                    "SET attempts = attempts + 1, last_attempt_at = ?, "
                    "    last_error = ?, state = 'pending' "
                    "WHERE idempotency_key = ?",
                    (now, error_message, idempotency_key),
                )
                await db.commit()
            except OSError as exc:
                logger.error(
                    "saga_buffer_mark_failed_disk_io_error",
                    idempotency_key=idempotency_key,
                    error=str(exc),
                )

    async def mark_dead_letter(self, idempotency_key: str, reason: str) -> None:
        """4h 到期：标 dead_letter，不删除，等人工处理。"""
        if not self._initialized:
            await self.initialize()
        async with self._lock:
            if self._memory_mode:
                e = self._memory_rows.get(idempotency_key)
                if e is None:
                    return
                e.state = _STATE_DEAD_LETTER
                e.last_error = reason
                return

            try:
                db = self._conn
                await db.execute(
                    "UPDATE saga_buffer "
                    "SET state = 'dead_letter', last_error = ? "
                    "WHERE idempotency_key = ?",
                    (reason, idempotency_key),
                )
                await db.commit()
            except OSError as exc:
                logger.error(
                    "saga_buffer_mark_dead_letter_disk_io_error",
                    idempotency_key=idempotency_key,
                    error=str(exc),
                )

    async def sweep_expired(
        self,
        *,
        tenant_id: Optional[str] = None,
    ) -> int:
        """扫描所有 pending 中 expires_at<=now 的条目，批量标 dead_letter。

        返回：被标 dead_letter 的条数。由 Flusher 定期调用。
        """
        if not self._initialized:
            await self.initialize()
        now = int(self._clock())

        async with self._lock:
            if self._memory_mode:
                count = 0
                for e in self._memory_rows.values():
                    if (
                        e.state == _STATE_PENDING
                        and e.expires_at <= now
                        and (tenant_id is None or e.tenant_id == tenant_id)
                    ):
                        e.state = _STATE_DEAD_LETTER
                        e.last_error = "ttl_expired_4h"
                        count += 1
                return count

            try:
                db = self._conn
                if tenant_id is None:
                    cur = await db.execute(
                        "UPDATE saga_buffer "
                        "SET state = 'dead_letter', last_error = 'ttl_expired_4h' "
                        "WHERE state = 'pending' AND expires_at <= ?",
                        (now,),
                    )
                else:
                    cur = await db.execute(
                        "UPDATE saga_buffer "
                        "SET state = 'dead_letter', last_error = 'ttl_expired_4h' "
                        "WHERE state = 'pending' AND expires_at <= ? "
                        "  AND tenant_id = ?",
                        (now, tenant_id),
                    )
                count = cur.rowcount or 0
                await cur.close()
                await db.commit()
                return count
            except OSError as exc:
                logger.error(
                    "saga_buffer_sweep_disk_io_error",
                    error=str(exc),
                )
                return 0

    async def reset_stuck_flushing(
        self,
        *,
        threshold_seconds: int,
        tenant_id: Optional[str] = None,
    ) -> int:
        """运行期保护：扫描 state=flushing 且 last_attempt_at 距今超过
        threshold_seconds 的条目，强制复位为 pending（针对进程没崩但
        flush 卡死的边缘场景）。

        返回：被复位的条数。由 SagaFlusher heartbeat 周期性调用。
        """
        if not self._initialized:
            await self.initialize()
        now = int(self._clock())
        cutoff = now - max(0, threshold_seconds)

        async with self._lock:
            if self._memory_mode:
                count = 0
                for e in self._memory_rows.values():
                    if (
                        e.state == _STATE_FLUSHING
                        and (tenant_id is None or e.tenant_id == tenant_id)
                        and (e.last_attempt_at is None or e.last_attempt_at <= cutoff)
                    ):
                        e.state = _STATE_PENDING
                        e.last_attempt_at = now
                        count += 1
                return count

            try:
                db = self._conn
                if tenant_id is None:
                    cur = await db.execute(
                        "UPDATE saga_buffer "
                        "SET state = 'pending', last_attempt_at = ? "
                        "WHERE state = 'flushing' "
                        "  AND (last_attempt_at IS NULL OR last_attempt_at <= ?)",
                        (now, cutoff),
                    )
                else:
                    cur = await db.execute(
                        "UPDATE saga_buffer "
                        "SET state = 'pending', last_attempt_at = ? "
                        "WHERE state = 'flushing' "
                        "  AND tenant_id = ? "
                        "  AND (last_attempt_at IS NULL OR last_attempt_at <= ?)",
                        (now, tenant_id, cutoff),
                    )
                count = cur.rowcount or 0
                await cur.close()
                await db.commit()
                return count
            except OSError as exc:
                logger.error(
                    "saga_buffer_reset_stuck_flushing_disk_io_error",
                    error=str(exc),
                )
                return 0

    async def _update_state(self, idempotency_key: str, state: str) -> None:
        if not self._initialized:
            await self.initialize()
        async with self._lock:
            if self._memory_mode:
                e = self._memory_rows.get(idempotency_key)
                if e is None:
                    return
                e.state = state
                return

            try:
                db = self._conn
                await db.execute(
                    "UPDATE saga_buffer SET state = ? WHERE idempotency_key = ?",
                    (state, idempotency_key),
                )
                await db.commit()
            except OSError as exc:
                logger.error(
                    "saga_buffer_update_state_disk_io_error",
                    idempotency_key=idempotency_key,
                    state=state,
                    error=str(exc),
                )

    # ─── 查询 / 统计 ──────────────────────────────────────────────────────────

    async def get(
        self,
        idempotency_key: str,
        *,
        tenant_id: Optional[str] = None,
    ) -> Optional[SagaBufferEntry]:
        """按 idempotency_key 取单条。

        tenant_id 传入时做行级隔离：跨租户查询返回 None（不漏传）。
        """
        if not self._initialized:
            await self.initialize()

        if self._memory_mode:
            e = self._memory_rows.get(idempotency_key)
            if e is None:
                return None
            if tenant_id is not None and e.tenant_id != tenant_id:
                return None
            return e

        try:
            db = self._conn
            cur = await db.execute(
                "SELECT idempotency_key, tenant_id, store_id, device_id, "
                "       saga_id, payload_json, attempts, last_attempt_at, "
                "       state, last_error, created_at, expires_at "
                "FROM saga_buffer WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            row = await cur.fetchone()
            await cur.close()
            if row is None:
                return None
            entry = _row_to_entry(row)
            if tenant_id is not None and entry.tenant_id != tenant_id:
                return None
            return entry
        except OSError:
            return None

    async def stats(self, *, tenant_id: Optional[str] = None) -> SagaBufferStats:
        """统计当前租户的缓冲状态（供 saga_buffer_meta heartbeat）。"""
        if not self._initialized:
            await self.initialize()

        if self._memory_mode:
            rows = [
                e for e in self._memory_rows.values()
                if tenant_id is None or e.tenant_id == tenant_id
            ]
            pending = [e for e in rows if e.state == _STATE_PENDING]
            flushing = [e for e in rows if e.state == _STATE_FLUSHING]
            sent = [e for e in rows if e.state == _STATE_SENT]
            dead = [e for e in rows if e.state == _STATE_DEAD_LETTER]
            return SagaBufferStats(
                pending_count=len(pending),
                flushing_count=len(flushing),
                sent_count=len(sent),
                dead_letter_count=len(dead),
                oldest_pending_at=min((e.created_at for e in pending), default=None),
                size_bytes=0,
                mode="memory",
            )

        try:
            db = self._conn
            if tenant_id is None:
                cur = await db.execute(
                    "SELECT state, COUNT(*) AS c, MIN(created_at) AS oldest "
                    "FROM saga_buffer GROUP BY state"
                )
            else:
                cur = await db.execute(
                    "SELECT state, COUNT(*) AS c, MIN(created_at) AS oldest "
                    "FROM saga_buffer WHERE tenant_id = ? GROUP BY state",
                    (tenant_id,),
                )
            rows = await cur.fetchall()
            await cur.close()
            stats = SagaBufferStats(mode="sqlite")
            oldest_pending: Optional[int] = None
            for r in rows:
                state, c, oldest = r["state"], r["c"], r["oldest"]
                if state == _STATE_PENDING:
                    stats.pending_count = c
                    oldest_pending = oldest
                elif state == _STATE_FLUSHING:
                    stats.flushing_count = c
                elif state == _STATE_SENT:
                    stats.sent_count = c
                elif state == _STATE_DEAD_LETTER:
                    stats.dead_letter_count = c
            stats.oldest_pending_at = oldest_pending
            try:
                stats.size_bytes = self._db_path.stat().st_size
            except OSError:
                stats.size_bytes = 0
            return stats
        except OSError:
            return SagaBufferStats(mode="error")

    async def close(self) -> None:
        """关闭持久 aiosqlite 连接（由 mac-station lifespan 调用）。"""
        if self._conn is not None:
            try:
                await self._conn.close()
            except OSError as exc:
                logger.warning("saga_buffer_close_error", error=str(exc))
            self._conn = None

    @property
    def is_memory_mode(self) -> bool:
        return self._memory_mode

    @property
    def device_id(self) -> str:
        return self._device_id


# ─── 工具 ─────────────────────────────────────────────────────────────────────


def _row_to_entry(row) -> SagaBufferEntry:
    """aiosqlite.Row → SagaBufferEntry."""
    return SagaBufferEntry(
        idempotency_key=row["idempotency_key"],
        tenant_id=row["tenant_id"],
        store_id=row["store_id"],
        device_id=row["device_id"],
        saga_id=row["saga_id"],
        payload=json.loads(row["payload_json"]),
        attempts=row["attempts"],
        last_attempt_at=row["last_attempt_at"],
        state=row["state"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


def generate_saga_id() -> str:
    """生成 saga_id（与 payment_saga_service uuid4 对齐）。"""
    return str(uuid.uuid4())
