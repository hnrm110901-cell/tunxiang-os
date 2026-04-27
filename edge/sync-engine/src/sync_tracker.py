"""sync_tracker.py — SQLite 持久化同步水位线和本地变更日志

负责：
  1. 初始化 SQLite（WAL 模式，断电安全）
  2. 读写 sync_watermarks（每张表的最后同步时间）
  3. 写入 / 查询 / 标记 local_change_log（本地操作缓冲）
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import List

import aiosqlite
import structlog
from models import (
    LOCAL_CHANGE_LOG_DDL,
    LOCAL_CHANGE_LOG_IDX,
    SYNC_WATERMARKS_DDL,
)

logger = structlog.get_logger()

DEFAULT_DB_PATH = os.getenv("SYNC_DB_PATH", "/var/lib/tunxiang/sync_engine.db")
_EPOCH = "1970-01-01T00:00:00+00:00"


class SyncTracker:
    """SQLite 持久化同步状态跟踪器"""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or DEFAULT_DB_PATH
        parent = os.path.dirname(self._db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    # ─── 初始化 ────────────────────────────────────────────────────────────

    async def init_db(self) -> None:
        """创建表结构，启用 WAL 模式"""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(SYNC_WATERMARKS_DDL)
            await db.execute(LOCAL_CHANGE_LOG_DDL)
            await db.execute(LOCAL_CHANGE_LOG_IDX)
            await db.commit()
        logger.info("sync_tracker.db_initialized", db_path=self._db_path)

    # ─── 水位线 ────────────────────────────────────────────────────────────

    async def get_watermark(self, table_name: str) -> str:
        """返回指定表的 last_sync_at（ISO 8601），默认 epoch"""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT last_sync_at FROM sync_watermarks WHERE table_name = ?",
                (table_name,),
            )
            row = await cursor.fetchone()
        return row[0] if row else _EPOCH

    async def get_upload_watermark(self, table_name: str) -> str:
        """返回上传水位（upload_at）"""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT upload_at FROM sync_watermarks WHERE table_name = ?",
                (table_name,),
            )
            row = await cursor.fetchone()
        return row[0] if row else _EPOCH

    async def set_watermark(
        self,
        table_name: str,
        last_sync_at: str,
        record_count: int = 0,
    ) -> None:
        """更新下载水位（last_sync_at）"""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO sync_watermarks (table_name, last_sync_at, record_count)
                VALUES (?, ?, ?)
                ON CONFLICT(table_name) DO UPDATE SET
                    last_sync_at = excluded.last_sync_at,
                    record_count = record_count + excluded.record_count
                """,
                (table_name, last_sync_at, record_count),
            )
            await db.commit()

    async def set_upload_watermark(self, table_name: str, upload_at: str) -> None:
        """更新上传水位（upload_at）"""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO sync_watermarks (table_name, upload_at)
                VALUES (?, ?)
                ON CONFLICT(table_name) DO UPDATE SET upload_at = excluded.upload_at
                """,
                (table_name, upload_at),
            )
            await db.commit()

    async def reset_watermarks(self, tables: List[str]) -> None:
        """全量同步前重置所有水位为 epoch（强制全量拉取）"""
        async with aiosqlite.connect(self._db_path) as db:
            for table in tables:
                await db.execute(
                    """
                    INSERT INTO sync_watermarks (table_name, last_sync_at, upload_at, record_count)
                    VALUES (?, ?, ?, 0)
                    ON CONFLICT(table_name) DO UPDATE SET
                        last_sync_at = ?,
                        upload_at    = ?,
                        record_count = 0
                    """,
                    (table, _EPOCH, _EPOCH, _EPOCH, _EPOCH),
                )
            await db.commit()
        logger.info("sync_tracker.watermarks_reset", tables=tables)

    # ─── 变更日志 ──────────────────────────────────────────────────────────

    async def log_change(
        self,
        table_name: str,
        record_id: str,
        operation: str,
        payload: dict,
    ) -> None:
        """记录一条本地变更（INSERT/UPDATE/DELETE）

        Args:
            table_name: 表名
            record_id:  主键值（字符串化）
            operation:  INSERT / UPDATE / DELETE
            payload:    完整记录的 JSON 序列化 dict
        """
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO local_change_log
                    (table_name, record_id, operation, payload, created_at, synced)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (table_name, record_id, operation, payload_json, now),
            )
            await db.commit()
        logger.debug(
            "sync_tracker.change_logged",
            table=table_name,
            record_id=record_id,
            op=operation,
        )

    async def get_pending_changes(self, batch_size: int = 500) -> List[dict]:
        """返回未同步的变更记录（按 created_at 升序，限 batch_size 条）"""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT id, table_name, record_id, operation, payload, created_at
                FROM local_change_log
                WHERE synced = 0
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (batch_size,),
            )
            rows = await cursor.fetchall()
        result = []
        for row in rows:
            r = dict(row)
            r["payload"] = json.loads(r["payload"])
            result.append(r)
        return result

    async def mark_changes_synced(self, ids: List[int]) -> None:
        """将指定 id 的变更标记为已同步"""
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                f"UPDATE local_change_log SET synced = 1 WHERE id IN ({placeholders})",
                ids,
            )
            await db.commit()
        logger.info("sync_tracker.changes_marked_synced", count=len(ids))

    async def get_pending_count(self) -> int:
        """未同步变更数量（用于状态展示）"""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM local_change_log WHERE synced = 0")
            row = await cursor.fetchone()
        return row[0] if row else 0
