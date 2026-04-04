"""change_tracker.py -- 基于 updated_at 时间戳的变更检测

提供统一接口追踪本地和云端数据变更，支持可替换的数据库后端。

核心接口：
  get_local_changes(table, since)   -- 查询本地PG自上次同步后的变更
  get_cloud_changes(table, since)   -- 查询云端变更
  get_last_sync_time(table)         -- 从 sync_state 表读取上次同步时间
  update_sync_time(table, timestamp) -- 更新同步时间戳
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Protocol

import structlog

from config import BATCH_SIZE, TENANT_ID

logger = structlog.get_logger()

# 默认 epoch（首次同步全量拉取）
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ─── 数据库连接协议（可替换接口）────────────────────────────────────────────

class DBConnection(Protocol):
    """数据库连接抽象接口，支持 Mock 替换"""

    async def fetch_all(
        self, query: str, params: dict[str, Any]
    ) -> List[dict[str, Any]]:
        """执行查询并返回所有结果行"""
        ...

    async def fetch_one(
        self, query: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        """执行查询并返回单行结果"""
        ...

    async def execute(self, query: str, params: dict[str, Any]) -> None:
        """执行写操作（INSERT/UPDATE/DELETE）"""
        ...


# ─── Mock 数据库连接（当前阶段使用）────────────────────────────────────────

class MockDBConnection:
    """Mock 数据库连接，用于开发/测试阶段

    不依赖真实 asyncpg 连接，所有操作返回空结果或静默执行。
    """

    def __init__(self, name: str = "mock") -> None:
        self._name = name
        self._sync_state: dict[str, datetime] = {}
        self._data_store: dict[str, list[dict[str, Any]]] = {}

    async def fetch_all(
        self, query: str, params: dict[str, Any]
    ) -> List[dict[str, Any]]:
        logger.debug(
            "mock_db.fetch_all",
            db=self._name,
            query=query[:80],
            params=params,
        )
        return []

    async def fetch_one(
        self, query: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        logger.debug(
            "mock_db.fetch_one",
            db=self._name,
            query=query[:80],
            params=params,
        )
        return None

    async def execute(self, query: str, params: dict[str, Any]) -> None:
        logger.debug(
            "mock_db.execute",
            db=self._name,
            query=query[:80],
            params=params,
        )

    # ── 直接访问内部状态（测试用）──

    def set_sync_time(self, table: str, ts: datetime) -> None:
        self._sync_state[table] = ts

    def get_sync_time_direct(self, table: str) -> datetime:
        return self._sync_state.get(table, _EPOCH)

    def inject_records(self, table: str, records: list[dict[str, Any]]) -> None:
        """注入测试数据"""
        self._data_store.setdefault(table, []).extend(records)


# ─── 变更追踪器 ────────────────────────────────────────────────────────────

class ChangeTracker:
    """基于 updated_at 时间戳的增量变更检测器

    通过可替换的 DBConnection 接口操作数据库，
    当前阶段使用 MockDBConnection，上线时替换为真实连接。

    Attributes:
        local_db:  本地 PostgreSQL 连接（Mac mini）
        cloud_db:  云端 PostgreSQL 连接（腾讯云）
        tenant_id: 当前租户 ID
        batch_size: 每批次查询行数
    """

    def __init__(
        self,
        local_db: DBConnection | None = None,
        cloud_db: DBConnection | None = None,
        tenant_id: str | None = None,
        batch_size: int | None = None,
    ) -> None:
        self._local_db = local_db or MockDBConnection(name="local")
        self._cloud_db = cloud_db or MockDBConnection(name="cloud")
        self._tenant_id = tenant_id or TENANT_ID
        self._batch_size = batch_size or BATCH_SIZE

    # ─── 公开接口 ──────────────────────────────────────────────────────────

    async def get_local_changes(
        self,
        table: str,
        since: datetime,
        offset: int = 0,
    ) -> List[dict[str, Any]]:
        """查询本地 PG 自 since 之后的变更记录

        Args:
            table:  表名
            since:  起始时间戳（不含）
            offset: 分页偏移

        Returns:
            变更记录列表，按 updated_at ASC 排序
        """
        query = (
            f'SELECT * FROM "{_sanitize_table(table)}" '
            f"WHERE tenant_id = :tenant_id "
            f"  AND updated_at > :since "
            f"ORDER BY updated_at ASC "
            f"LIMIT :limit OFFSET :offset"
        )
        params = {
            "tenant_id": self._tenant_id,
            "since": since,
            "limit": self._batch_size,
            "offset": offset,
        }

        records = await self._local_db.fetch_all(query, params)

        logger.info(
            "change_tracker.local_changes",
            table=table,
            since=since.isoformat(),
            count=len(records),
            offset=offset,
        )
        return records

    async def get_cloud_changes(
        self,
        table: str,
        since: datetime,
        offset: int = 0,
    ) -> List[dict[str, Any]]:
        """查询云端自 since 之后的变更记录

        Args:
            table:  表名
            since:  起始时间戳（不含）
            offset: 分页偏移

        Returns:
            变更记录列表，按 updated_at ASC 排序
        """
        query = (
            f'SELECT * FROM "{_sanitize_table(table)}" '
            f"WHERE tenant_id = :tenant_id "
            f"  AND updated_at > :since "
            f"ORDER BY updated_at ASC "
            f"LIMIT :limit OFFSET :offset"
        )
        params = {
            "tenant_id": self._tenant_id,
            "since": since,
            "limit": self._batch_size,
            "offset": offset,
        }

        records = await self._cloud_db.fetch_all(query, params)

        logger.info(
            "change_tracker.cloud_changes",
            table=table,
            since=since.isoformat(),
            count=len(records),
            offset=offset,
        )
        return records

    async def get_last_sync_time(self, table: str) -> datetime:
        """从 sync_state 表读取指定表的上次同步时间

        Args:
            table: 表名

        Returns:
            上次同步的 UTC 时间戳，不存在则返回 epoch
        """
        query = (
            "SELECT last_synced_at FROM sync_state "
            "WHERE table_name = :table_name AND tenant_id = :tenant_id"
        )
        params = {"table_name": table, "tenant_id": self._tenant_id}

        row = await self._local_db.fetch_one(query, params)
        if row is None:
            logger.debug(
                "change_tracker.no_sync_state",
                table=table,
                msg="returning epoch",
            )
            return _EPOCH

        ts = row.get("last_synced_at")
        return _ensure_tz(ts)

    async def update_sync_time(
        self, table: str, timestamp: datetime
    ) -> None:
        """更新 sync_state 表中指定表的同步时间戳

        使用 UPSERT 语义：不存在则插入，存在则更新。

        Args:
            table:     表名
            timestamp: 新的同步时间戳（UTC）
        """
        query = (
            "INSERT INTO sync_state (table_name, tenant_id, last_synced_at) "
            "VALUES (:table_name, :tenant_id, :last_synced_at) "
            "ON CONFLICT (table_name, tenant_id) DO UPDATE "
            "SET last_synced_at = EXCLUDED.last_synced_at"
        )
        params = {
            "table_name": table,
            "tenant_id": self._tenant_id,
            "last_synced_at": timestamp,
        }

        await self._local_db.execute(query, params)

        logger.info(
            "change_tracker.sync_time_updated",
            table=table,
            timestamp=timestamp.isoformat(),
        )


# ─── 工具函数 ──────────────────────────────────────────────────────────────

def _sanitize_table(table: str) -> str:
    """校验表名，防止 SQL 注入（仅允许字母/数字/下划线）"""
    if not all(c.isalnum() or c == "_" for c in table):
        raise ValueError(f"Invalid table name: {table!r}")
    return table


def _ensure_tz(value: Any) -> datetime:
    """确保时间戳带 UTC 时区，解析失败返回 epoch"""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        value = value.strip()
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(value, fmt)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return _EPOCH
