"""sync_engine.py — Mac mini 边缘同步引擎（本地PG ↔ 云端PG 双向增量）

同步策略
--------
- 上行（local → cloud）：本地产生的交易数据（订单/结账/库存消耗）
  优先推送，以 updated_at > upstream cursor 为条件增量扫描
- 下行（cloud → local）：菜单/配置/会员，以云端为主
  以 updated_at > downstream cursor 为条件增量拉取
- 冲突解决：
    1. cloud.authoritative = true  → 云端直接覆盖
    2. local.source = 'pos' 且 status in ('pending','paid') → 本地优先（POS 交易保护）
    3. 其余：比较 updated_at，较新者优先
- 断线续传：sync_cursors 表（本地PG）存储每表每方向的最后成功时间戳
- 每批 BATCH_SIZE 行，超时 SYNC_TIMEOUT_SECONDS 秒，指数退避重试
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import asyncpg
import structlog

logger = structlog.get_logger()

# ─── 同步表清单 ────────────────────────────────────────────────────────────

UPSTREAM_TABLES: list[str] = [  # 本地 → 云端（交易类，优先）
    "orders",
    "order_items",
    "payments",
    "kds_tasks",
    "live_seafood_weigh_records",
    "shift_handovers",
    "daily_summaries",
]

DOWNSTREAM_TABLES: list[str] = [  # 云端 → 本地（菜单/配置类）
    "dishes",
    "dish_combos",
    "dish_boms",
    "banquet_menus",
    "members",
    "member_level_configs",
    "payroll_configs",
    "sales_channels",
    "channel_dish_configs",
]

# 辅助表 DDL（在本地 PG 创建，不走 Alembic）
_INIT_DDL = """
CREATE TABLE IF NOT EXISTS sync_cursors (
    id              SERIAL PRIMARY KEY,
    table_name      VARCHAR NOT NULL,
    direction       VARCHAR NOT NULL,  -- upstream / downstream
    last_synced_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    synced_rows     INT DEFAULT 0,
    UNIQUE(table_name, direction)
);

CREATE TABLE IF NOT EXISTS sync_conflicts_log (
    id                SERIAL PRIMARY KEY,
    table_name        VARCHAR,
    record_id         VARCHAR,
    local_updated_at  TIMESTAMPTZ,
    cloud_updated_at  TIMESTAMPTZ,
    resolution        VARCHAR,  -- local_wins / cloud_wins / cloud_authoritative
    resolved_at       TIMESTAMPTZ DEFAULT NOW()
);
"""

# POS 交易保护状态集合
_POS_PROTECTED_STATUSES: frozenset[str] = frozenset({"pending", "paid"})

# 指数退避初始等待（秒）
_BACKOFF_INITIAL: int = 30


# ─── 结果数据类 ────────────────────────────────────────────────────────────


@dataclass
class SyncResult:
    """一轮同步结果摘要"""

    upstream_rows: int = 0
    downstream_rows: int = 0
    conflicts: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0
    tables_upstream: dict[str, int] = field(default_factory=dict)
    tables_downstream: dict[str, int] = field(default_factory=dict)

    @property
    def total_rows(self) -> int:
        return self.upstream_rows + self.downstream_rows

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


# ─── 核心同步引擎 ──────────────────────────────────────────────────────────


class SyncEngine:
    """
    增量同步引擎：本地PG（Mac mini）← → 云端PG（腾讯云）

    同步策略：
    - 上行（本地→云端）：本地产生的事务数据（订单/结账/库存消耗），优先级高
    - 下行（云端→本地）：菜单变更/配置更新/会员数据，云端为主
    - 冲突解决：以 updated_at 最新为准，但云端标记为 authoritative=true 的直接覆盖
    - 断线续传：记录上次成功同步的 cursor（每表一个），续传时从 cursor 之后开始
    """

    def __init__(
        self,
        local_dsn: str,
        cloud_dsn: str,
        store_id: str,
        tenant_id: str,
        batch_size: int = 100,
        sync_timeout: int = 60,
        max_retry_backoff: int = 3600,
    ) -> None:
        # 将 SQLAlchemy-style DSN 转换为 asyncpg 格式
        self._local_dsn = _normalize_dsn(local_dsn)
        self._cloud_dsn = _normalize_dsn(cloud_dsn)
        self._store_id = store_id
        self._tenant_id = tenant_id
        self._batch_size = batch_size
        self._sync_timeout = sync_timeout
        self._max_retry_backoff = max_retry_backoff

        self._local_pool: asyncpg.Pool | None = None
        self._cloud_pool: asyncpg.Pool | None = None

    # ─── 生命周期 ──────────────────────────────────────────────────────────

    async def init(self) -> None:
        """初始化连接池并确保辅助表存在"""
        self._local_pool = await asyncpg.create_pool(
            self._local_dsn,
            min_size=2,
            max_size=5,
            command_timeout=30,
        )
        self._cloud_pool = await asyncpg.create_pool(
            self._cloud_dsn,
            min_size=2,
            max_size=5,
            command_timeout=30,
        )
        await self._ensure_schema()
        logger.info(
            "sync_engine.initialized",
            store_id=self._store_id,
            tenant_id=self._tenant_id,
            upstream_tables=UPSTREAM_TABLES,
            downstream_tables=DOWNSTREAM_TABLES,
        )

    async def close(self) -> None:
        """关闭连接池"""
        if self._local_pool:
            await self._local_pool.close()
        if self._cloud_pool:
            await self._cloud_pool.close()
        logger.info("sync_engine.closed")

    async def _ensure_schema(self) -> None:
        """在本地 PG 创建同步辅助表（幂等）"""
        assert self._local_pool is not None
        async with self._local_pool.acquire() as conn:
            await conn.execute(_INIT_DDL)
        logger.info("sync_engine.schema_ensured")

    # ─── 公开接口 ──────────────────────────────────────────────────────────

    async def sync_once(self) -> SyncResult:
        """执行一轮完整同步（上行+下行），返回同步结果摘要"""
        start = time.perf_counter()
        result = SyncResult()

        logger.info(
            "sync_engine.sync_once_start",
            store_id=self._store_id,
            tenant_id=self._tenant_id,
        )

        # 上行：本地 → 云端（交易数据优先）
        for table in UPSTREAM_TABLES:
            try:
                cursor = await self.get_sync_cursor(table, "upstream")
                count = await self.sync_upstream(table, cursor)
                result.upstream_rows += count
                result.tables_upstream[table] = count
                if count > 0:
                    logger.info(
                        "sync_engine.upstream_done",
                        table=table,
                        rows=count,
                        since=cursor.isoformat(),
                    )
            except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError) as exc:
                msg = f"upstream:{table}:{exc!s}"
                result.errors.append(msg)
                logger.error(
                    "sync_engine.upstream_error",
                    table=table,
                    error=str(exc),
                    exc_info=True,
                )

        # 下行：云端 → 本地（菜单/配置）
        for table in DOWNSTREAM_TABLES:
            try:
                cursor = await self.get_sync_cursor(table, "downstream")
                count = await self.sync_downstream(table, cursor)
                result.downstream_rows += count
                result.tables_downstream[table] = count
                if count > 0:
                    logger.info(
                        "sync_engine.downstream_done",
                        table=table,
                        rows=count,
                        since=cursor.isoformat(),
                    )
            except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError) as exc:
                msg = f"downstream:{table}:{exc!s}"
                result.errors.append(msg)
                logger.error(
                    "sync_engine.downstream_error",
                    table=table,
                    error=str(exc),
                    exc_info=True,
                )

        duration_ms = int((time.perf_counter() - start) * 1000)
        result.duration_ms = duration_ms

        logger.info(
            "sync_engine.sync_once_done",
            upstream_rows=result.upstream_rows,
            downstream_rows=result.downstream_rows,
            conflicts=result.conflicts,
            errors=result.errors,
            duration_ms=duration_ms,
        )
        return result

    async def sync_upstream(self, table: str, since: datetime) -> int:
        """上行：查本地 updated_at > since 的记录，upsert 到云端

        Returns:
            本轮同步的记录行数
        """
        assert self._local_pool is not None
        assert self._cloud_pool is not None

        total = 0
        offset = 0
        max_updated_at = since

        while True:
            async with self._local_pool.acquire() as local_conn:
                rows = await local_conn.fetch(
                    f"""
                    SELECT * FROM {_q(table)}
                    WHERE tenant_id = $1
                      AND updated_at > $2
                    ORDER BY updated_at ASC
                    LIMIT $3 OFFSET $4
                    """,
                    self._tenant_id,
                    since,
                    self._batch_size,
                    offset,
                )

            if not rows:
                break

            records = [dict(r) for r in rows]

            # 批量 upsert 到云端
            async with self._cloud_pool.acquire() as cloud_conn:
                await _batch_upsert(cloud_conn, table, records)

            batch_max = max(r["updated_at"] for r in records if r.get("updated_at"))
            if batch_max > max_updated_at:
                max_updated_at = batch_max

            total += len(records)
            offset += len(records)

            if len(records) < self._batch_size:
                break

        if total > 0:
            await self.update_sync_cursor(table, "upstream", max_updated_at, synced_rows=total)

        return total

    async def sync_downstream(self, table: str, since: datetime) -> int:
        """下行：查云端 updated_at > since 的记录，upsert 到本地

        Returns:
            本轮同步的记录行数
        """
        assert self._local_pool is not None
        assert self._cloud_pool is not None

        total = 0
        offset = 0
        max_updated_at = since

        while True:
            async with self._cloud_pool.acquire() as cloud_conn:
                rows = await cloud_conn.fetch(
                    f"""
                    SELECT * FROM {_q(table)}
                    WHERE tenant_id = $1
                      AND updated_at > $2
                    ORDER BY updated_at ASC
                    LIMIT $3 OFFSET $4
                    """,
                    self._tenant_id,
                    since,
                    self._batch_size,
                    offset,
                )

            if not rows:
                break

            cloud_records = [dict(r) for r in rows]

            # 冲突解决后 upsert 到本地
            resolved_records: list[dict[str, Any]] = []
            for cloud_row in cloud_records:
                record_id = cloud_row.get("id")
                local_row = await self._fetch_local_row(table, record_id)
                if local_row:
                    winner = await self.resolve_conflict(local_row, cloud_row)
                    resolved_records.append(winner)
                else:
                    resolved_records.append(cloud_row)

            async with self._local_pool.acquire() as local_conn:
                await _batch_upsert(local_conn, table, resolved_records)

            batch_max = max(r["updated_at"] for r in cloud_records if r.get("updated_at"))
            if batch_max > max_updated_at:
                max_updated_at = batch_max

            total += len(cloud_records)
            offset += len(cloud_records)

            if len(cloud_records) < self._batch_size:
                break

        if total > 0:
            await self.update_sync_cursor(table, "downstream", max_updated_at, synced_rows=total)

        return total

    async def resolve_conflict(self, local_row: dict[str, Any], cloud_row: dict[str, Any]) -> dict[str, Any]:
        """冲突解决：
        - 云端 authoritative=true → 云端优先
        - 否则比较 updated_at → 较新者优先
        - 本地 source='pos' 且 status in ('pending','paid') → 本地优先（POS 交易保护）
        """
        # 规则 1：云端标记为权威 → 直接覆盖
        if cloud_row.get("authoritative") is True:
            await self._log_conflict(local_row, cloud_row, resolution="cloud_authoritative")
            return cloud_row

        # 规则 2：POS 交易保护 — 本地 source=pos 且处于活跃交易状态
        local_source = local_row.get("source", "")
        local_status = str(local_row.get("status", ""))
        if local_source == "pos" and local_status in _POS_PROTECTED_STATUSES:
            await self._log_conflict(local_row, cloud_row, resolution="local_wins")
            return local_row

        # 规则 3：比较 updated_at
        local_ts = _parse_ts(local_row.get("updated_at"))
        cloud_ts = _parse_ts(cloud_row.get("updated_at"))

        if local_ts > cloud_ts:
            await self._log_conflict(local_row, cloud_row, resolution="local_wins")
            return local_row

        await self._log_conflict(local_row, cloud_row, resolution="cloud_wins")
        return cloud_row

    async def get_sync_cursor(self, table: str, direction: str) -> datetime:
        """从 sync_cursors 表读取上次同步时间，不存在则返回 epoch"""
        assert self._local_pool is not None

        async with self._local_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT last_synced_at FROM sync_cursors
                WHERE table_name = $1 AND direction = $2
                """,
                table,
                direction,
            )

        if row:
            ts = row["last_synced_at"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts

        # 默认 epoch（首次同步全量拉取）
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

    async def update_sync_cursor(
        self,
        table: str,
        direction: str,
        cursor: datetime,
        synced_rows: int = 0,
    ) -> None:
        """更新 sync_cursors 表"""
        assert self._local_pool is not None

        async with self._local_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sync_cursors (table_name, direction, last_synced_at, synced_rows)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (table_name, direction) DO UPDATE
                    SET last_synced_at = EXCLUDED.last_synced_at,
                        synced_rows    = sync_cursors.synced_rows + EXCLUDED.synced_rows
                """,
                table,
                direction,
                cursor,
                synced_rows,
            )

        logger.debug(
            "sync_engine.cursor_updated",
            table=table,
            direction=direction,
            cursor=cursor.isoformat(),
            synced_rows=synced_rows,
        )

    async def run_forever(self, interval_seconds: int = 300) -> None:
        """主循环：每 interval_seconds 执行一次 sync_once，带指数退避重试"""
        await self.init()
        backoff = _BACKOFF_INITIAL

        logger.info(
            "sync_engine.run_forever_start",
            interval_seconds=interval_seconds,
            max_retry_backoff=self._max_retry_backoff,
        )

        while True:
            try:
                result = await asyncio.wait_for(
                    self.sync_once(),
                    timeout=self._sync_timeout,
                )
                # 成功：重置退避
                backoff = _BACKOFF_INITIAL

                if result.errors:
                    logger.warning(
                        "sync_engine.sync_partial_errors",
                        errors=result.errors,
                        upstream_rows=result.upstream_rows,
                        downstream_rows=result.downstream_rows,
                    )
                else:
                    logger.info(
                        "sync_engine.sync_cycle_ok",
                        total_rows=result.total_rows,
                        duration_ms=result.duration_ms,
                    )

                await asyncio.sleep(interval_seconds)

            except asyncio.TimeoutError:
                logger.error(
                    "sync_engine.sync_timeout",
                    timeout_seconds=self._sync_timeout,
                    msg="sync_once timed out, skipping this cycle",
                )
                # 超时不退避，按正常间隔继续
                await asyncio.sleep(interval_seconds)

            except (asyncpg.PostgresConnectionStatusError, asyncpg.TooManyConnectionsError) as exc:
                logger.error(
                    "sync_engine.pg_connection_error",
                    error=str(exc),
                    backoff_seconds=backoff,
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._max_retry_backoff)

            except OSError as exc:
                logger.error(
                    "sync_engine.os_error",
                    error=str(exc),
                    backoff_seconds=backoff,
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._max_retry_backoff)

    # ─── 内部辅助 ──────────────────────────────────────────────────────────

    async def _fetch_local_row(self, table: str, record_id: Any) -> dict[str, Any] | None:
        """按主键查询本地一条记录"""
        assert self._local_pool is not None

        try:
            async with self._local_pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT * FROM {_q(table)} WHERE id = $1",
                    record_id,
                )
            return dict(row) if row else None
        except asyncpg.PostgresError as exc:
            logger.warning(
                "sync_engine.fetch_local_row_error",
                table=table,
                record_id=record_id,
                error=str(exc),
            )
            return None

    async def _log_conflict(
        self,
        local_row: dict[str, Any],
        cloud_row: dict[str, Any],
        resolution: str,
    ) -> None:
        """写入冲突审计日志"""
        assert self._local_pool is not None

        table = local_row.get("__table__") or cloud_row.get("__table__") or "unknown"
        record_id = str(local_row.get("id") or cloud_row.get("id") or "")
        local_ts = _parse_ts(local_row.get("updated_at"))
        cloud_ts = _parse_ts(cloud_row.get("updated_at"))

        try:
            async with self._local_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO sync_conflicts_log
                        (table_name, record_id, local_updated_at, cloud_updated_at, resolution)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    table,
                    record_id,
                    local_ts,
                    cloud_ts,
                    resolution,
                )
        except asyncpg.PostgresError as exc:
            # 冲突日志写失败不阻断业务，仅记录警告
            logger.warning(
                "sync_engine.conflict_log_error",
                error=str(exc),
            )

        logger.debug(
            "sync_engine.conflict_resolved",
            table=table,
            record_id=record_id,
            resolution=resolution,
            local_updated_at=local_ts.isoformat(),
            cloud_updated_at=cloud_ts.isoformat(),
        )


# ─── 工具函数 ──────────────────────────────────────────────────────────────


def _normalize_dsn(dsn: str) -> str:
    """将 SQLAlchemy asyncpg DSN 转换为 asyncpg 原生 DSN

    例：postgresql+asyncpg://user:pass@host/db → postgresql://user:pass@host/db
    """
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


def _q(table: str) -> str:
    """对表名加双引号防止 SQL 注入（仅允许字母/数字/下划线）"""
    if not all(c.isalnum() or c == "_" for c in table):
        raise ValueError(f"Invalid table name: {table!r}")
    return f'"{table}"'


def _parse_ts(value: Any) -> datetime:
    """将 updated_at 字段（datetime / str）解析为带时区的 datetime，失败返回 epoch"""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        value = value.strip()
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f+00:00",
            "%Y-%m-%dT%H:%M:%S+00:00",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(value, fmt)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


async def _batch_upsert(
    conn: asyncpg.Connection,
    table: str,
    records: list[dict[str, Any]],
) -> None:
    """批量 UPSERT 到目标 PG 表（ON CONFLICT (id) DO UPDATE）

    要求：所有 records 列名一致，且包含 id 列。
    """
    if not records:
        return

    columns = list(records[0].keys())
    if "id" not in columns:
        raise ValueError(f"Table {table!r}: records must contain 'id' column for upsert")

    col_list = ", ".join(f'"{c}"' for c in columns)
    update_set = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in columns if c != "id")

    # asyncpg executemany — 传入参数列表
    placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
    sql = f"INSERT INTO {_q(table)} ({col_list}) VALUES ({placeholders}) ON CONFLICT (id) DO UPDATE SET {update_set}"

    rows_as_tuples = [tuple(r.get(c) for c in columns) for r in records]
    await conn.executemany(sql, rows_as_tuples)
