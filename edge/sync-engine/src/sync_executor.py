"""sync_executor.py -- 同步执行器：批量 UPSERT 推送/拉取

负责将变更记录实际写入目标数据库：
  push_to_cloud(table, records)  -- 批量 upsert 到云端
  pull_to_local(table, records)  -- 批量 upsert 到本地

设计原则：
  - 单表同步在一个事务中完成（事务保证）
  - 使用 ON CONFLICT (id) DO UPDATE 实现幂等写入
  - 数据库操作封装为可替换接口（当前阶段使用 Mock）
"""

from __future__ import annotations

from typing import Any, List

import structlog
from change_tracker import DBConnection, MockDBConnection
from config import BATCH_SIZE

logger = structlog.get_logger()


class SyncExecutor:
    """同步执行器：批量 UPSERT 到本地/云端 PG

    通过可替换的 DBConnection 接口操作数据库。
    当前阶段使用 MockDBConnection，上线时替换为真实 asyncpg 连接。

    Attributes:
        local_db:   本地 PostgreSQL 连接
        cloud_db:   云端 PostgreSQL 连接
        batch_size: 每批次写入行数
    """

    def __init__(
        self,
        local_db: DBConnection | None = None,
        cloud_db: DBConnection | None = None,
        batch_size: int | None = None,
    ) -> None:
        self._local_db = local_db or MockDBConnection(name="local")
        self._cloud_db = cloud_db or MockDBConnection(name="cloud")
        self._batch_size = batch_size or BATCH_SIZE

    # ─── 公开接口 ──────────────────────────────────────────────────────────

    async def push_to_cloud(self, table: str, records: List[dict[str, Any]]) -> int:
        """批量 UPSERT 记录到云端 PG

        单表操作在一个逻辑事务中完成。使用 ON CONFLICT (id) DO UPDATE
        实现幂等写入。

        Args:
            table:   目标表名
            records: 待写入的记录列表（必须包含 id 列）

        Returns:
            成功写入的记录数

        Raises:
            ValueError: 记录不包含 id 列
        """
        if not records:
            return 0

        _validate_records(table, records)
        total = 0

        for batch_start in range(0, len(records), self._batch_size):
            batch = records[batch_start : batch_start + self._batch_size]
            sql, params = _build_upsert_sql(table, batch)

            await self._cloud_db.execute(sql, params)
            total += len(batch)

            logger.debug(
                "sync_executor.push_batch",
                table=table,
                batch_size=len(batch),
                total_so_far=total,
            )

        logger.info(
            "sync_executor.push_to_cloud_done",
            table=table,
            total=total,
        )
        return total

    async def pull_to_local(self, table: str, records: List[dict[str, Any]]) -> int:
        """批量 UPSERT 记录到本地 PG

        单表操作在一个逻辑事务中完成。使用 ON CONFLICT (id) DO UPDATE
        实现幂等写入。

        Args:
            table:   目标表名
            records: 待写入的记录列表（必须包含 id 列）

        Returns:
            成功写入的记录数

        Raises:
            ValueError: 记录不包含 id 列
        """
        if not records:
            return 0

        _validate_records(table, records)
        total = 0

        for batch_start in range(0, len(records), self._batch_size):
            batch = records[batch_start : batch_start + self._batch_size]
            sql, params = _build_upsert_sql(table, batch)

            await self._local_db.execute(sql, params)
            total += len(batch)

            logger.debug(
                "sync_executor.pull_batch",
                table=table,
                batch_size=len(batch),
                total_so_far=total,
            )

        logger.info(
            "sync_executor.pull_to_local_done",
            table=table,
            total=total,
        )
        return total


# ─── 工具函数 ──────────────────────────────────────────────────────────────


def _sanitize_table(table: str) -> str:
    """校验表名，防止 SQL 注入"""
    if not all(c.isalnum() or c == "_" for c in table):
        raise ValueError(f"Invalid table name: {table!r}")
    return table


def _validate_records(table: str, records: List[dict[str, Any]]) -> None:
    """校验记录列表：非空且包含 id 列"""
    if not records:
        raise ValueError(f"Table {table!r}: empty records list")
    columns = set(records[0].keys())
    if "id" not in columns:
        raise ValueError(f"Table {table!r}: records must contain 'id' column for upsert")


def _build_upsert_sql(table: str, records: List[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """构造批量 UPSERT SQL（ON CONFLICT (id) DO UPDATE）

    生成形如：
      INSERT INTO "table" ("id", "col1", "col2")
      VALUES (:id_0, :col1_0, :col2_0), (:id_1, :col1_1, :col2_1), ...
      ON CONFLICT (id) DO UPDATE SET "col1" = EXCLUDED."col1", ...

    Args:
        table:   表名
        records: 记录列表（列名取第一条记录的 keys）

    Returns:
        (sql, params) 元组
    """
    safe_table = _sanitize_table(table)
    columns = list(records[0].keys())

    col_list = ", ".join(f'"{c}"' for c in columns)
    update_set = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in columns if c != "id")

    # 构造多行 VALUES 子句
    value_rows: list[str] = []
    params: dict[str, Any] = {}
    for i, record in enumerate(records):
        placeholders = ", ".join(f":{c}_{i}" for c in columns)
        value_rows.append(f"({placeholders})")
        for c in columns:
            params[f"{c}_{i}"] = record.get(c)

    values_clause = ", ".join(value_rows)

    sql = f'INSERT INTO "{safe_table}" ({col_list}) VALUES {values_clause} ON CONFLICT (id) DO UPDATE SET {update_set}'

    return sql, params
