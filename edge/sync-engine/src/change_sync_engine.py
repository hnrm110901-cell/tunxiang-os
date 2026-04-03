"""change_sync_engine.py — 基于变更日志的双向增量同步引擎

本模块实现新一代同步协议，基于 ChangeRecord 事件流：

  推送流程：
    本地 PG (sync_changelog / updated_at 扫描)
      → _get_local_changes()
      → _push_to_cloud()  (POST /api/v1/sync/ingest)
      → 更新 push 光标

  拉取流程：
    _get_cloud_changes()  (GET /api/v1/sync/changes)
      → _apply_to_local() (UPSERT / soft-delete / 事务)
      → 更新 pull 光标

  主循环：
    run_sync_cycle()  每 SYNC_INTERVAL 秒执行一次完整循环

  断网续传：
    RetryQueue — 失败变更写入本地 retry_queue 表，按优先级重试

设计约束：
  - 同步失败不阻塞业务（完全异步后台运行）
  - 云端为主（cloud wins）冲突解决策略
  - 具体异常类型（禁止 broad except）
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = structlog.get_logger()

# ─── 配置常量 ──────────────────────────────────────────────────────────────

CLOUD_API_URL: str = os.getenv("CLOUD_API_URL", "")
LOCAL_DB_URL: str = os.getenv(
    "LOCAL_DATABASE_URL",
    "postgresql+asyncpg://tunxiang:local@localhost/tunxiang_local",
)
TENANT_ID: str = os.getenv("TENANT_ID", "")
SYNC_INTERVAL: int = int(os.getenv("SYNC_INTERVAL_SECONDS", "300"))
HTTP_TIMEOUT: float = float(os.getenv("SYNC_HTTP_TIMEOUT", "30"))
CONNECT_TIMEOUT: float = float(os.getenv("CLOUD_CONNECT_TIMEOUT", "5"))
INGEST_BATCH_SIZE: int = int(os.getenv("SYNC_INGEST_BATCH_SIZE", "200"))
APPLY_BATCH_SIZE: int = int(os.getenv("SYNC_APPLY_BATCH_SIZE", "100"))
CLOUD_PAGE_SIZE: int = int(os.getenv("SYNC_CLOUD_PAGE_SIZE", "500"))
RETRY_MAX_AGE_HOURS: int = int(os.getenv("SYNC_RETRY_MAX_AGE_HOURS", "48"))

# 关键同步表（按业务重要度排序，影响 RetryQueue 优先级）
SYNC_TABLES: List[str] = [
    "orders",
    "order_items",
    "members",
    "dishes",
    "inventory_records",
]

# 优先级映射（数字越小越优先）
TABLE_PRIORITY: dict[str, int] = {
    "orders": 1,
    "order_items": 1,
    "members": 2,
    "dishes": 3,
    "inventory_records": 3,
}


# ─── 数据模型 ──────────────────────────────────────────────────────────────

@dataclass
class ChangeRecord:
    """单条变更记录"""
    table_name: str
    record_id: str
    operation: str          # INSERT | UPDATE | DELETE
    data: dict[str, Any]
    tenant_id: str
    changed_at: datetime
    change_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "table_name": self.table_name,
            "record_id": self.record_id,
            "operation": self.operation,
            "data": self.data,
            "tenant_id": self.tenant_id,
            "changed_at": self.changed_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ChangeRecord":
        changed_at = d.get("changed_at")
        if isinstance(changed_at, str):
            changed_at = datetime.fromisoformat(changed_at)
        if changed_at is None:
            changed_at = datetime.now(timezone.utc)
        if changed_at.tzinfo is None:
            changed_at = changed_at.replace(tzinfo=timezone.utc)
        return cls(
            table_name=d["table_name"],
            record_id=d["record_id"],
            operation=d["operation"],
            data=d.get("data", {}),
            tenant_id=d["tenant_id"],
            changed_at=changed_at,
            change_id=d.get("change_id", str(uuid.uuid4())),
        )


@dataclass
class SyncResult:
    """推送到云端的结果"""
    accepted: List[str] = field(default_factory=list)    # change_id 列表
    conflicts: List[str] = field(default_factory=list)   # change_id 列表
    errors: List[str] = field(default_factory=list)      # change_id 列表
    error_messages: List[str] = field(default_factory=list)


@dataclass
class ApplyResult:
    """应用到本地的结果"""
    applied: int = 0
    skipped: int = 0
    failed: int = 0
    error_messages: List[str] = field(default_factory=list)


# ─── 同步光标管理器 ────────────────────────────────────────────────────────

class SyncCursorManager:
    """管理推送/拉取光标（持久化到本地 PG sync_cursors 表）

    表结构（首次调用时自动创建）：
      sync_cursors (cursor_key TEXT PK, cursor_ts TIMESTAMPTZ, updated_at TIMESTAMPTZ)
    """

    PUSH_KEY = "push_cursor"
    PULL_KEY = "pull_cursor"
    EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

    _DDL = """
    CREATE TABLE IF NOT EXISTS sync_cursors (
        cursor_key  TEXT PRIMARY KEY,
        cursor_ts   TIMESTAMPTZ NOT NULL DEFAULT '1970-01-01T00:00:00+00:00',
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """

    def __init__(self, pool: AsyncEngine) -> None:
        self._pool = pool
        self._initialized = False

    async def _ensure_table(self) -> None:
        if self._initialized:
            return
        async with self._pool.begin() as conn:
            await conn.execute(text(self._DDL))
        self._initialized = True

    async def get_last_push_cursor(self) -> datetime:
        """获取上次成功推送的时间戳"""
        await self._ensure_table()
        async with self._pool.connect() as conn:
            result = await conn.execute(
                text("SELECT cursor_ts FROM sync_cursors WHERE cursor_key = :k"),
                {"k": self.PUSH_KEY},
            )
            row = result.one_or_none()
        if row is None:
            return self.EPOCH
        ts = row[0]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

    async def get_last_pull_cursor(self) -> datetime:
        """获取上次成功拉取的时间戳"""
        await self._ensure_table()
        async with self._pool.connect() as conn:
            result = await conn.execute(
                text("SELECT cursor_ts FROM sync_cursors WHERE cursor_key = :k"),
                {"k": self.PULL_KEY},
            )
            row = result.one_or_none()
        if row is None:
            return self.EPOCH
        ts = row[0]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

    async def update_push_cursor(self, timestamp: datetime) -> None:
        """更新推送光标"""
        await self._ensure_table()
        now = datetime.now(timezone.utc)
        async with self._pool.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO sync_cursors (cursor_key, cursor_ts, updated_at)
                    VALUES (:k, :ts, :now)
                    ON CONFLICT (cursor_key) DO UPDATE
                        SET cursor_ts = EXCLUDED.cursor_ts,
                            updated_at = EXCLUDED.updated_at
                """),
                {"k": self.PUSH_KEY, "ts": timestamp, "now": now},
            )
        logger.debug("sync_cursor.push_updated", ts=timestamp.isoformat())

    async def update_pull_cursor(self, timestamp: datetime) -> None:
        """更新拉取光标"""
        await self._ensure_table()
        now = datetime.now(timezone.utc)
        async with self._pool.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO sync_cursors (cursor_key, cursor_ts, updated_at)
                    VALUES (:k, :ts, :now)
                    ON CONFLICT (cursor_key) DO UPDATE
                        SET cursor_ts = EXCLUDED.cursor_ts,
                            updated_at = EXCLUDED.updated_at
                """),
                {"k": self.PULL_KEY, "ts": timestamp, "now": now},
            )
        logger.debug("sync_cursor.pull_updated", ts=timestamp.isoformat())


# ─── 断网重试队列 ──────────────────────────────────────────────────────────

class RetryQueue:
    """断网续传：失败的变更持久化到本地 PG retry_queue 表

    表结构（首次调用自动创建）：
      retry_queue (
        id          UUID PK,
        change_id   TEXT UNIQUE,
        table_name  TEXT,
        priority    INT,            -- 1=高(orders) 3=低(others)
        payload     JSONB,
        error_msg   TEXT,
        retry_count INT DEFAULT 0,
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        last_retry  TIMESTAMPTZ,
        status      TEXT DEFAULT 'pending'  -- pending | success | expired
      )
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS retry_queue (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        change_id   TEXT UNIQUE NOT NULL,
        table_name  TEXT NOT NULL,
        priority    INTEGER NOT NULL DEFAULT 3,
        payload     JSONB NOT NULL,
        error_msg   TEXT,
        retry_count INTEGER NOT NULL DEFAULT 0,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_retry  TIMESTAMPTZ,
        status      TEXT NOT NULL DEFAULT 'pending'
    );
    CREATE INDEX IF NOT EXISTS idx_retry_queue_pending
        ON retry_queue (priority, created_at)
        WHERE status = 'pending';
    """

    def __init__(self, pool: AsyncEngine) -> None:
        self._pool = pool
        self._initialized = False

    async def _ensure_table(self) -> None:
        if self._initialized:
            return
        async with self._pool.begin() as conn:
            for stmt in self._DDL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(text(stmt))
        self._initialized = True

    async def enqueue(self, changes: List[ChangeRecord], error: str) -> None:
        """将失败变更写入本地 retry_queue 表"""
        if not changes:
            return
        await self._ensure_table()
        now = datetime.now(timezone.utc)
        async with self._pool.begin() as conn:
            for change in changes:
                priority = TABLE_PRIORITY.get(change.table_name, 3)
                payload_json = json.dumps(change.to_dict(), ensure_ascii=False, default=str)
                await conn.execute(
                    text("""
                        INSERT INTO retry_queue
                            (change_id, table_name, priority, payload, error_msg, created_at, status)
                        VALUES
                            (:change_id, :table_name, :priority, :payload::jsonb,
                             :error_msg, :created_at, 'pending')
                        ON CONFLICT (change_id) DO UPDATE
                            SET error_msg   = EXCLUDED.error_msg,
                                retry_count = retry_queue.retry_count + 1,
                                last_retry  = :created_at,
                                status      = 'pending'
                    """),
                    {
                        "change_id": change.change_id,
                        "table_name": change.table_name,
                        "priority": priority,
                        "payload": payload_json,
                        "error_msg": error[:500],
                        "created_at": now,
                    },
                )
        logger.info(
            "retry_queue.enqueued",
            count=len(changes),
            error=error[:100],
        )

    async def get_pending(self, max_age_hours: int = 48) -> List[ChangeRecord]:
        """获取待重试的变更（按优先级：orders > members > others，且未超龄）"""
        await self._ensure_table()
        async with self._pool.connect() as conn:
            result = await conn.execute(
                text("""
                    SELECT payload
                    FROM retry_queue
                    WHERE status = 'pending'
                      AND created_at > NOW() - :age_interval::interval
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 500
                """),
                {"age_interval": f"{max_age_hours} hours"},
            )
            rows = result.all()

        changes: List[ChangeRecord] = []
        for row in rows:
            payload = row[0]
            if isinstance(payload, str):
                payload = json.loads(payload)
            try:
                changes.append(ChangeRecord.from_dict(payload))
            except (KeyError, ValueError) as exc:
                logger.warning("retry_queue.bad_payload", error=str(exc))
        return changes

    async def mark_success(self, change_ids: List[str]) -> None:
        """标记重试成功"""
        if not change_ids:
            return
        await self._ensure_table()
        placeholders = ", ".join(f":id_{i}" for i in range(len(change_ids)))
        params: dict[str, Any] = {f"id_{i}": v for i, v in enumerate(change_ids)}
        async with self._pool.begin() as conn:
            await conn.execute(
                text(f"""
                    UPDATE retry_queue
                    SET status = 'success', last_retry = NOW()
                    WHERE change_id IN ({placeholders})
                """),
                params,
            )
        logger.info("retry_queue.marked_success", count=len(change_ids))


# ─── 核心同步引擎 ──────────────────────────────────────────────────────────

class ChangeSyncEngine:
    """基于 ChangeRecord 的双向增量同步引擎

    使用方：
        engine = ChangeSyncEngine()
        await engine.init()
        await engine.run_sync_cycle()   # 单次循环
        # 或在后台持续运行：
        await engine.run_forever()
    """

    def __init__(
        self,
        local_db_url: str | None = None,
        cloud_api_url: str | None = None,
        tenant_id: str | None = None,
        sync_interval: int | None = None,
    ) -> None:
        self._local_db_url = local_db_url or LOCAL_DB_URL
        self._cloud_api_url = cloud_api_url or CLOUD_API_URL
        self._tenant_id = tenant_id or TENANT_ID
        self._sync_interval = sync_interval or SYNC_INTERVAL
        self._pool: AsyncEngine | None = None
        self._cursor: SyncCursorManager | None = None
        self._retry: RetryQueue | None = None
        self._cycle_count: int = 0

    # ─── 生命周期 ──────────────────────────────────────────────────────────

    async def init(self) -> None:
        """初始化连接池、光标管理器、重试队列"""
        self._pool = create_async_engine(
            self._local_db_url,
            pool_size=3,
            max_overflow=5,
            pool_pre_ping=True,
        )
        self._cursor = SyncCursorManager(self._pool)
        self._retry = RetryQueue(self._pool)
        logger.info(
            "change_sync_engine.initialized",
            tenant_id=self._tenant_id or "(not set)",
            cloud_api_url=self._cloud_api_url or "(not set)",
            sync_interval=self._sync_interval,
        )

    async def close(self) -> None:
        """释放连接池"""
        if self._pool:
            await self._pool.dispose()
        logger.info("change_sync_engine.closed", cycles=self._cycle_count)

    # ─── 主循环 ────────────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """持续运行同步循环，每 sync_interval 秒执行一次"""
        await self.init()
        try:
            while True:
                await self.run_sync_cycle()
                await asyncio.sleep(self._sync_interval)
        finally:
            await self.close()

    async def run_sync_cycle(self) -> dict[str, Any]:
        """每 SYNC_INTERVAL 秒执行一次完整同步循环

        流程：
          1. 检查网络连通性（ping cloud API /health）
          2. 推送本地变更到云端
          3. 拉取云端变更到本地
          4. 处理重试队列
          5. 更新同步统计（sync_stats 表）

        Returns:
            本次循环统计摘要
        """
        assert self._pool is not None, "call init() first"
        assert self._cursor is not None
        assert self._retry is not None

        start = time.perf_counter()
        self._cycle_count += 1

        stats: dict[str, Any] = {
            "cycle": self._cycle_count,
            "pushed": 0,
            "pulled": 0,
            "retried": 0,
            "conflicts": 0,
            "errors": 0,
        }

        # ── 1. 网络连通性检查 ──────────────────────────────────────────────
        is_connected = await self._check_connectivity()
        if not is_connected:
            logger.info(
                "change_sync_engine.offline",
                cycle=self._cycle_count,
                msg="cloud unreachable, skipping this cycle",
            )
            stats["offline"] = True
            return stats

        # ── 2. 推送本地变更 ────────────────────────────────────────────────
        try:
            push_cursor = await self._cursor.get_last_push_cursor()
            local_changes = await self._get_local_changes(since=push_cursor)

            if local_changes:
                push_result = await self._push_to_cloud(local_changes)
                stats["pushed"] = len(push_result.accepted)
                stats["conflicts"] += len(push_result.conflicts)

                # 推送失败的变更进入重试队列
                if push_result.errors:
                    failed_changes = [
                        c for c in local_changes if c.change_id in set(push_result.errors)
                    ]
                    if failed_changes:
                        await self._retry.enqueue(
                            failed_changes,
                            error="; ".join(push_result.error_messages[:3]),
                        )
                    stats["errors"] += len(push_result.errors)

        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.error(
                "change_sync_engine.push_network_error",
                error=str(exc),
                exc_info=True,
            )
            stats["errors"] += 1

        # ── 3. 拉取云端变更 ────────────────────────────────────────────────
        try:
            pull_cursor = await self._cursor.get_last_pull_cursor()
            cloud_changes = await self._get_cloud_changes(since=pull_cursor)

            if cloud_changes:
                apply_result = await self._apply_to_local(cloud_changes)
                stats["pulled"] = apply_result.applied
                stats["errors"] += apply_result.failed

                # 更新拉取光标为本批最新时间戳
                max_ts = max(c.changed_at for c in cloud_changes)
                await self._cursor.update_pull_cursor(max_ts)

        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.error(
                "change_sync_engine.pull_network_error",
                error=str(exc),
                exc_info=True,
            )
            stats["errors"] += 1

        # ── 4. 处理重试队列 ────────────────────────────────────────────────
        try:
            retry_changes = await self._retry.get_pending(max_age_hours=RETRY_MAX_AGE_HOURS)
            if retry_changes:
                retry_result = await self._push_to_cloud(retry_changes)
                success_ids = retry_result.accepted
                if success_ids:
                    await self._retry.mark_success(success_ids)
                    stats["retried"] = len(success_ids)
                    logger.info(
                        "change_sync_engine.retry_success",
                        retried=len(success_ids),
                    )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning(
                "change_sync_engine.retry_network_error",
                error=str(exc),
            )

        # ── 5. 更新同步统计 ────────────────────────────────────────────────
        duration_ms = int((time.perf_counter() - start) * 1000)
        stats["duration_ms"] = duration_ms
        await self._upsert_sync_stats(stats)

        logger.info(
            "change_sync_engine.cycle_done",
            **stats,
        )
        return stats

    # ─── 核心方法：获取本地变更 ────────────────────────────────────────────

    async def _get_local_changes(self, since: datetime) -> List[ChangeRecord]:
        """从本地 PostgreSQL 获取自 since 时间之后的变更记录

        策略：
          1. 优先查询 sync_changelog 表（如存在）
          2. 降级：扫描关键表的 updated_at > since
          3. 结果按 changed_at ASC 排序（保证顺序同步）
        """
        assert self._pool is not None

        # 先尝试从 sync_changelog 表读取（精确变更追踪）
        changes = await self._get_from_changelog(since)
        if changes is not None:
            return changes

        # 降级：扫描各表 updated_at > since
        return await self._scan_tables_for_changes(since)

    async def _get_from_changelog(
        self, since: datetime
    ) -> Optional[List[ChangeRecord]]:
        """从 sync_changelog 表查询变更，表不存在则返回 None（触发降级）"""
        assert self._pool is not None
        try:
            async with self._pool.connect() as conn:
                result = await conn.execute(
                    text("""
                        SELECT table_name, record_id, operation,
                               data, tenant_id, changed_at, change_id
                        FROM sync_changelog
                        WHERE tenant_id = :tenant_id
                          AND changed_at > :since
                        ORDER BY changed_at ASC
                        LIMIT :limit
                    """),
                    {
                        "tenant_id": self._tenant_id,
                        "since": since,
                        "limit": INGEST_BATCH_SIZE,
                    },
                )
                keys = list(result.keys())
                rows = result.all()

            changes: List[ChangeRecord] = []
            for row in rows:
                d = dict(zip(keys, row))
                data = d.get("data") or {}
                if isinstance(data, str):
                    data = json.loads(data)
                changed_at = d["changed_at"]
                if isinstance(changed_at, str):
                    changed_at = datetime.fromisoformat(changed_at)
                if changed_at.tzinfo is None:
                    changed_at = changed_at.replace(tzinfo=timezone.utc)
                changes.append(ChangeRecord(
                    table_name=d["table_name"],
                    record_id=str(d["record_id"]),
                    operation=d["operation"],
                    data=data,
                    tenant_id=d["tenant_id"],
                    changed_at=changed_at,
                    change_id=d.get("change_id") or str(uuid.uuid4()),
                ))
            return changes

        except OperationalError:
            # sync_changelog 表不存在，降级
            logger.debug(
                "change_sync_engine.changelog_missing",
                msg="sync_changelog not found, falling back to updated_at scan",
            )
            return None
        except SQLAlchemyError as exc:
            logger.error(
                "change_sync_engine.changelog_error",
                error=str(exc),
                exc_info=True,
            )
            return None

    async def _scan_tables_for_changes(self, since: datetime) -> List[ChangeRecord]:
        """降级策略：扫描各关键表的 updated_at > since"""
        assert self._pool is not None
        changes: List[ChangeRecord] = []

        for table in SYNC_TABLES:
            try:
                async with self._pool.connect() as conn:
                    result = await conn.execute(
                        text(f"""
                            SELECT *
                            FROM "{table}"
                            WHERE tenant_id = :tenant_id
                              AND updated_at > :since
                              AND is_deleted = FALSE
                            ORDER BY updated_at ASC
                            LIMIT :limit
                        """),
                        {
                            "tenant_id": self._tenant_id,
                            "since": since,
                            "limit": INGEST_BATCH_SIZE,
                        },
                    )
                    cols = list(result.keys())
                    rows = result.all()

                for row in rows:
                    d = dict(zip(cols, row))
                    updated_at = d.get("updated_at") or datetime.now(timezone.utc)
                    if isinstance(updated_at, str):
                        updated_at = datetime.fromisoformat(updated_at)
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=timezone.utc)
                    # 将所有值序列化为可 JSON 化的形式
                    data = {k: _serialize_value(v) for k, v in d.items()}
                    changes.append(ChangeRecord(
                        table_name=table,
                        record_id=str(d.get("id", "")),
                        operation="UPDATE",  # 无法区分 INSERT/UPDATE，统一用 UPSERT 处理
                        data=data,
                        tenant_id=str(d.get("tenant_id", self._tenant_id)),
                        changed_at=updated_at,
                    ))

            except OperationalError as exc:
                logger.warning(
                    "change_sync_engine.scan_table_missing",
                    table=table,
                    error=str(exc),
                )
            except SQLAlchemyError as exc:
                logger.error(
                    "change_sync_engine.scan_table_error",
                    table=table,
                    error=str(exc),
                    exc_info=True,
                )

        # 全表汇总后按时间排序
        changes.sort(key=lambda c: c.changed_at)

        if changes:
            # 更新推送光标为本批最新时间戳
            max_ts = max(c.changed_at for c in changes)
            await self._cursor.update_push_cursor(max_ts)

        logger.info(
            "change_sync_engine.local_changes_scanned",
            since=since.isoformat(),
            count=len(changes),
        )
        return changes

    # ─── 核心方法：推送到云端 ─────────────────────────────────────────────

    async def _push_to_cloud(self, changes: List[ChangeRecord]) -> SyncResult:
        """将本地变更批量推送到云端

        策略：
          1. 批量 POST 到云端 API: POST /api/v1/sync/ingest
          2. 云端返回 {accepted: [...], conflicts: [...], errors: [...]}
          3. conflicts → 记录到 sync_conflicts 表
          4. errors → 加入重试队列
          5. 成功后更新本地 push 光标
        """
        if not self._cloud_api_url or not changes:
            return SyncResult()

        result = SyncResult()

        # 分批推送（每批 INGEST_BATCH_SIZE 条）
        for i in range(0, len(changes), INGEST_BATCH_SIZE):
            batch = changes[i: i + INGEST_BATCH_SIZE]
            batch_result = await self._push_batch(batch)
            result.accepted.extend(batch_result.accepted)
            result.conflicts.extend(batch_result.conflicts)
            result.errors.extend(batch_result.errors)
            result.error_messages.extend(batch_result.error_messages)

        # 记录冲突到本地
        if result.conflicts:
            await self._record_conflicts(changes, result.conflicts)

        # 成功后更新推送光标
        if result.accepted and changes:
            accepted_set = set(result.accepted)
            accepted_changes = [c for c in changes if c.change_id in accepted_set]
            if accepted_changes:
                max_ts = max(c.changed_at for c in accepted_changes)
                await self._cursor.update_push_cursor(max_ts)

        logger.info(
            "change_sync_engine.push_done",
            total=len(changes),
            accepted=len(result.accepted),
            conflicts=len(result.conflicts),
            errors=len(result.errors),
        )
        return result

    async def _push_batch(self, batch: List[ChangeRecord]) -> SyncResult:
        """推送单批变更，返回云端响应解析结果"""
        result = SyncResult()
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.post(
                    f"{self._cloud_api_url}/api/v1/sync/ingest",
                    json={"changes": [c.to_dict() for c in batch]},
                    headers={"X-Tenant-ID": self._tenant_id},
                )
                resp.raise_for_status()
                body = resp.json()

            data = body.get("data", {})
            result.accepted = data.get("accepted", [])
            result.conflicts = data.get("conflicts", [])
            result.errors = data.get("errors", [])
            result.error_messages = data.get("error_messages", [])

            if not body.get("ok"):
                # 云端返回业务错误：将整批标记为 error
                result.errors = [c.change_id for c in batch]
                result.error_messages = [body.get("error", {}).get("message", "cloud nok")]

        except httpx.ConnectError as exc:
            logger.error(
                "change_sync_engine.push_connect_error",
                error=str(exc),
            )
            raise
        except httpx.TimeoutException as exc:
            logger.error(
                "change_sync_engine.push_timeout",
                error=str(exc),
            )
            raise
        except httpx.HTTPStatusError as exc:
            logger.error(
                "change_sync_engine.push_http_error",
                status=exc.response.status_code,
                error=str(exc),
            )
            result.errors = [c.change_id for c in batch]
            result.error_messages = [f"HTTP {exc.response.status_code}"]

        return result

    async def _record_conflicts(
        self, changes: List[ChangeRecord], conflict_ids: List[str]
    ) -> None:
        """将冲突记录到本地 sync_conflicts 表（云端版本更新，不覆盖）"""
        assert self._pool is not None
        conflict_set = set(conflict_ids)
        conflict_changes = [c for c in changes if c.change_id in conflict_set]
        if not conflict_changes:
            return
        try:
            async with self._pool.begin() as conn:
                # 确保表存在
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS sync_conflicts (
                        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        change_id   TEXT NOT NULL,
                        table_name  TEXT NOT NULL,
                        record_id   TEXT NOT NULL,
                        local_data  JSONB,
                        reason      TEXT,
                        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """))
                for change in conflict_changes:
                    await conn.execute(
                        text("""
                            INSERT INTO sync_conflicts
                                (change_id, table_name, record_id, local_data, reason, created_at)
                            VALUES
                                (:change_id, :table_name, :record_id, :local_data::jsonb,
                                 'cloud_version_newer', NOW())
                            ON CONFLICT DO NOTHING
                        """),
                        {
                            "change_id": change.change_id,
                            "table_name": change.table_name,
                            "record_id": change.record_id,
                            "local_data": json.dumps(change.data, default=str),
                        },
                    )
        except SQLAlchemyError as exc:
            logger.warning(
                "change_sync_engine.conflict_record_error",
                error=str(exc),
            )

    # ─── 核心方法：从云端拉取变更 ─────────────────────────────────────────

    async def _get_cloud_changes(self, since: datetime) -> List[ChangeRecord]:
        """从云端拉取变更（菜单更新、会员充值等从总部下发的数据）

        策略：
          GET /api/v1/sync/changes?since={since}&tenant_id={tenant_id}
          分页拉取（每次最多 CLOUD_PAGE_SIZE 条）
        """
        if not self._cloud_api_url:
            return []

        all_changes: List[ChangeRecord] = []
        page = 1

        while True:
            params: dict[str, Any] = {
                "since": since.isoformat(),
                "tenant_id": self._tenant_id,
                "page": page,
                "size": CLOUD_PAGE_SIZE,
            }
            try:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                    resp = await client.get(
                        f"{self._cloud_api_url}/api/v1/sync/changes",
                        params=params,
                        headers={"X-Tenant-ID": self._tenant_id},
                    )
                    resp.raise_for_status()
                    body = resp.json()

                if not body.get("ok"):
                    logger.warning(
                        "change_sync_engine.cloud_changes_nok",
                        error=body.get("error"),
                    )
                    break

                items = body.get("data", {}).get("items", [])
                for item in items:
                    try:
                        all_changes.append(ChangeRecord.from_dict(item))
                    except (KeyError, ValueError) as exc:
                        logger.warning(
                            "change_sync_engine.bad_cloud_change",
                            error=str(exc),
                        )

                if len(items) < CLOUD_PAGE_SIZE:
                    break
                page += 1

            except httpx.ConnectError as exc:
                logger.error(
                    "change_sync_engine.pull_connect_error",
                    error=str(exc),
                )
                raise
            except httpx.TimeoutException as exc:
                logger.error(
                    "change_sync_engine.pull_timeout",
                    error=str(exc),
                )
                raise
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "change_sync_engine.pull_http_error",
                    status=exc.response.status_code,
                    error=str(exc),
                )
                break

        logger.info(
            "change_sync_engine.cloud_changes_fetched",
            since=since.isoformat(),
            count=len(all_changes),
            pages=page,
        )
        return all_changes

    # ─── 核心方法：应用到本地 PG ──────────────────────────────────────────

    async def _apply_to_local(self, changes: List[ChangeRecord]) -> ApplyResult:
        """将云端变更应用到本地 PostgreSQL

        冲突解决策略：云端为主（cloud wins）
          - INSERT/UPDATE → UPSERT（ON CONFLICT DO UPDATE）
          - DELETE → 软删除（is_deleted=TRUE）
          - 使用事务批量执行（每批 APPLY_BATCH_SIZE 条）
          - 失败则回滚，记录失败原因
        """
        assert self._pool is not None
        result = ApplyResult()

        # 分批处理
        for batch_start in range(0, len(changes), APPLY_BATCH_SIZE):
            batch = changes[batch_start: batch_start + APPLY_BATCH_SIZE]
            batch_result = await self._apply_batch(batch)
            result.applied += batch_result.applied
            result.skipped += batch_result.skipped
            result.failed += batch_result.failed
            result.error_messages.extend(batch_result.error_messages)

        logger.info(
            "change_sync_engine.apply_done",
            total=len(changes),
            applied=result.applied,
            skipped=result.skipped,
            failed=result.failed,
        )
        return result

    async def _apply_batch(self, batch: List[ChangeRecord]) -> ApplyResult:
        """在单个事务中应用一批变更，失败则回滚"""
        result = ApplyResult()
        try:
            async with self._pool.begin() as conn:
                for change in batch:
                    try:
                        if change.operation == "DELETE":
                            await self._soft_delete(conn, change)
                        else:
                            # INSERT 和 UPDATE 都用 UPSERT
                            await self._upsert_record(conn, change)
                        result.applied += 1
                    except SQLAlchemyError as exc:
                        # 记录失败，但不阻止整批（抛出会触发回滚）
                        # 整批回滚，将单条失败计为整批失败
                        raise exc
        except SQLAlchemyError as exc:
            # 整批失败，回滚
            result.applied = 0
            result.failed = len(batch)
            error_msg = f"{type(exc).__name__}: {str(exc)[:200]}"
            result.error_messages.append(error_msg)
            logger.error(
                "change_sync_engine.apply_batch_error",
                batch_size=len(batch),
                error=error_msg,
                exc_info=True,
            )
        return result

    async def _upsert_record(self, conn: Any, change: ChangeRecord) -> None:
        """UPSERT 单条记录到本地表（云端优先，无条件覆盖）

        cloud-wins 策略：直接 UPSERT，不做本地版本比较。
        终态保护由 ConflictResolver 在 SyncEngine（pull 流程）层处理。
        """
        data = change.data
        if not data or "id" not in data:
            logger.warning(
                "change_sync_engine.upsert_no_id",
                table=change.table_name,
                record_id=change.record_id,
            )
            return

        columns = list(data.keys())
        col_list = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join(f":{c}" for c in columns)
        update_set = ", ".join(
            f'"{c}" = EXCLUDED."{c}"' for c in columns if c != "id"
        )
        sql = (
            f'INSERT INTO "{change.table_name}" ({col_list}) '
            f"VALUES ({placeholders}) "
            f'ON CONFLICT (id) DO UPDATE SET {update_set}'
        )
        row = {c: data.get(c) for c in columns}
        await conn.execute(text(sql), row)

    async def _soft_delete(self, conn: Any, change: ChangeRecord) -> None:
        """软删除：设置 is_deleted=TRUE"""
        await conn.execute(
            text(f"""
                UPDATE "{change.table_name}"
                SET is_deleted = TRUE,
                    updated_at = :updated_at
                WHERE id = :id
                  AND tenant_id = :tenant_id
            """),
            {
                "id": change.record_id,
                "tenant_id": change.tenant_id,
                "updated_at": change.changed_at,
            },
        )

    # ─── 辅助方法 ──────────────────────────────────────────────────────────

    async def _check_connectivity(self) -> bool:
        """ping 云端 /health，返回是否可达"""
        if not self._cloud_api_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=CONNECT_TIMEOUT) as client:
                resp = await client.get(f"{self._cloud_api_url}/health")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
            return False

    async def _upsert_sync_stats(self, stats: dict[str, Any]) -> None:
        """更新 sync_stats 表（不存在时自动创建）"""
        assert self._pool is not None
        try:
            async with self._pool.begin() as conn:
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS sync_stats (
                        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        tenant_id   TEXT NOT NULL,
                        cycle       INTEGER,
                        pushed      INTEGER DEFAULT 0,
                        pulled      INTEGER DEFAULT 0,
                        retried     INTEGER DEFAULT 0,
                        conflicts   INTEGER DEFAULT 0,
                        errors      INTEGER DEFAULT 0,
                        duration_ms INTEGER DEFAULT 0,
                        is_offline  BOOLEAN DEFAULT FALSE,
                        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """))
                await conn.execute(
                    text("""
                        INSERT INTO sync_stats
                            (tenant_id, cycle, pushed, pulled, retried,
                             conflicts, errors, duration_ms, is_offline, created_at)
                        VALUES
                            (:tenant_id, :cycle, :pushed, :pulled, :retried,
                             :conflicts, :errors, :duration_ms, :offline, NOW())
                    """),
                    {
                        "tenant_id": self._tenant_id,
                        "cycle": stats.get("cycle", 0),
                        "pushed": stats.get("pushed", 0),
                        "pulled": stats.get("pulled", 0),
                        "retried": stats.get("retried", 0),
                        "conflicts": stats.get("conflicts", 0),
                        "errors": stats.get("errors", 0),
                        "duration_ms": stats.get("duration_ms", 0),
                        "offline": stats.get("offline", False),
                    },
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "change_sync_engine.stats_update_error",
                error=str(exc),
            )


# ─── 工具函数 ──────────────────────────────────────────────────────────────

def _serialize_value(v: Any) -> Any:
    """将 PG 数据类型转换为 JSON 安全的 Python 类型"""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    return v
