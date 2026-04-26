"""
OfflineBuffer — SQLite WAL 离线操作缓冲

门店断网时，将需要同步到云端的操作写入本地 SQLite，
联网后由 ForgeNode.sync_on_reconnect() 批量推送。

数据库路径：/var/lib/tunxiang/offline_buffer.db
  - 生产环境需要提前创建目录：mkdir -p /var/lib/tunxiang
  - 开发环境降级到 /tmp/tunxiang_offline_buffer.db
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

# SQLite 文件路径：生产用 /var/lib/tunxiang/，开发降级到 /tmp/
_PROD_PATH = Path("/var/lib/tunxiang/offline_buffer.db")
_DEV_PATH = Path("/tmp/tunxiang_offline_buffer.db")  # noqa: S108 — dev fallback; 生产走 _PROD_PATH

_DDL = """
CREATE TABLE IF NOT EXISTS offline_buffer (
    id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    action TEXT NOT NULL,
    payload TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    synced_at TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_offline_buffer_status
    ON offline_buffer (status, created_at);

CREATE INDEX IF NOT EXISTS idx_offline_buffer_skill
    ON offline_buffer (skill_name, status);
"""


# ─── Pydantic 模型 ────────────────────────────────────────────────────────────


class BufferedOperation(BaseModel):
    """缓冲队列中的一条操作记录"""

    id: str
    skill_name: str
    action: str
    payload: dict
    tenant_id: str
    status: str  # pending / syncing / synced / failed
    created_at: str
    synced_at: Optional[str] = None
    retry_count: int = 0
    error_message: Optional[str] = None


class BufferStats(BaseModel):
    """缓冲队列统计信息"""

    pending_count: int
    syncing_count: int
    failed_count: int
    total_count: int
    oldest_entry: Optional[str] = None  # ISO8601 时间戳
    newest_entry: Optional[str] = None
    size_bytes: int = 0


# ─── OfflineBuffer ────────────────────────────────────────────────────────────


class OfflineBuffer:
    """
    基于 SQLite WAL 的离线操作缓冲队列。

    线程安全：使用 asyncio.Lock 保护写操作，SQLite 连接在调用线程中同步执行，
    通过 asyncio.get_event_loop().run_in_executor 避免阻塞事件循环。
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path:
            self._db_path = Path(db_path)
        else:
            # 生产路径不可用时降级到 /tmp/
            if _PROD_PATH.parent.exists() and os.access(_PROD_PATH.parent, os.W_OK):
                self._db_path = _PROD_PATH
            else:
                self._db_path = _DEV_PATH
                logger.warning(
                    "offline_buffer_using_dev_path",
                    path=str(self._db_path),
                    reason="production path not writable",
                )

        self._lock = asyncio.Lock()
        self._initialized = False

    # ─── 初始化 ───────────────────────────────────────────────────────────────

    def _init_db_sync(self) -> None:
        """同步初始化 SQLite 表结构（在 executor 中运行）"""
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(_DDL)
            conn.commit()
        finally:
            conn.close()

    async def initialize(self) -> None:
        """异步初始化：建表、设置 WAL 模式"""
        if self._initialized:
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._init_db_sync)
        self._initialized = True
        logger.info("offline_buffer_initialized", path=str(self._db_path))

    # ─── 核心操作 ─────────────────────────────────────────────────────────────

    def _write_sync(
        self,
        buffer_id: str,
        skill_name: str,
        action: str,
        payload: dict,
        tenant_id: str,
        created_at: str,
    ) -> None:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                """
                INSERT INTO offline_buffer
                    (id, skill_name, action, payload, tenant_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (buffer_id, skill_name, action, json.dumps(payload, ensure_ascii=False), tenant_id, created_at),
            )
            conn.commit()
        finally:
            conn.close()

    async def write(
        self,
        skill_name: str,
        action: str,
        payload: dict,
        tenant_id: str,
    ) -> str:
        """
        将操作写入离线缓冲队列。

        Args:
            skill_name: Skill 名称，如 "wine-storage"
            action: 操作名称，如 "store"
            payload: 操作载荷（需可 JSON 序列化）
            tenant_id: 租户 ID（RLS 隔离）

        Returns:
            buffer_id: UUID 字符串，可用于追踪同步状态
        """
        buffer_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        loop = asyncio.get_event_loop()
        async with self._lock:
            await loop.run_in_executor(
                None,
                self._write_sync,
                buffer_id,
                skill_name,
                action,
                payload,
                tenant_id,
                created_at,
            )

        logger.info(
            "offline_buffer_written",
            buffer_id=buffer_id,
            skill_name=skill_name,
            action=action,
            tenant_id=tenant_id,
        )
        return buffer_id

    def _get_pending_sync(self, limit: int) -> list[tuple]:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT id, skill_name, action, payload, tenant_id,
                       status, created_at, synced_at, retry_count, error_message
                FROM offline_buffer
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    async def get_pending(self, limit: int = 100) -> list[BufferedOperation]:
        """
        获取待同步的操作列表（status='pending'），按时间升序。

        Args:
            limit: 最多返回条数，默认 100

        Returns:
            BufferedOperation 列表
        """
        loop = asyncio.get_event_loop()
        rows = await loop.run_in_executor(None, self._get_pending_sync, limit)
        return [BufferedOperation(**{**row, "payload": json.loads(row["payload"])}) for row in rows]

    def _mark_synced_sync(self, ids: list[str]) -> None:
        if not ids:
            return
        synced_at = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(str(self._db_path))
        try:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE offline_buffer SET status='synced', synced_at=? WHERE id IN ({placeholders})",
                [synced_at, *ids],
            )
            conn.commit()
        finally:
            conn.close()

    async def mark_synced(self, ids: list[str]) -> None:
        """
        标记操作为已同步。

        Args:
            ids: buffer_id 列表
        """
        if not ids:
            return
        loop = asyncio.get_event_loop()
        async with self._lock:
            await loop.run_in_executor(None, self._mark_synced_sync, ids)
        logger.info("offline_buffer_marked_synced", count=len(ids))

    def _mark_failed_sync(self, ids: list[str], error_message: str) -> None:
        if not ids:
            return
        conn = sqlite3.connect(str(self._db_path))
        try:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"""
                UPDATE offline_buffer
                SET status='failed',
                    retry_count = retry_count + 1,
                    error_message = ?
                WHERE id IN ({placeholders})
                """,
                [error_message, *ids],
            )
            conn.commit()
        finally:
            conn.close()

    async def mark_failed(self, ids: list[str], error_message: str) -> None:
        """标记操作为同步失败，增加 retry_count"""
        if not ids:
            return
        loop = asyncio.get_event_loop()
        async with self._lock:
            await loop.run_in_executor(None, self._mark_failed_sync, ids, error_message)

    def _mark_syncing_sync(self, ids: list[str]) -> None:
        if not ids:
            return
        conn = sqlite3.connect(str(self._db_path))
        try:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE offline_buffer SET status='syncing' WHERE id IN ({placeholders})",
                ids,
            )
            conn.commit()
        finally:
            conn.close()

    async def mark_syncing(self, ids: list[str]) -> None:
        """将操作标记为同步中（防止重复推送）"""
        if not ids:
            return
        loop = asyncio.get_event_loop()
        async with self._lock:
            await loop.run_in_executor(None, self._mark_syncing_sync, ids)

    # ─── 统计 ──────────────────────────────────────────────────────────────────

    def _get_stats_sync(self) -> dict:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            counts_row = conn.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status='pending')  AS pending_count,
                    COUNT(*) FILTER (WHERE status='syncing')  AS syncing_count,
                    COUNT(*) FILTER (WHERE status='failed')   AS failed_count,
                    COUNT(*)                                   AS total_count,
                    MIN(created_at) FILTER (WHERE status='pending') AS oldest_entry,
                    MAX(created_at) FILTER (WHERE status='pending') AS newest_entry
                FROM offline_buffer
                """
            ).fetchone()
            result = dict(counts_row)
            # 获取文件大小
            try:
                result["size_bytes"] = self._db_path.stat().st_size
            except OSError:
                result["size_bytes"] = 0
            return result
        finally:
            conn.close()

    async def get_stats(self) -> BufferStats:
        """
        获取缓冲队列统计信息。

        Returns:
            BufferStats（包含各状态计数、最早/最新条目时间、文件大小）
        """
        loop = asyncio.get_event_loop()
        stats = await loop.run_in_executor(None, self._get_stats_sync)
        return BufferStats(**stats)
