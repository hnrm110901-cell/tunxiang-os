"""scheduler.py -- 同步调度器：主循环 + 健康检查 + 断点续传

主循环每 SYNC_INTERVAL_SECONDS 执行一轮完整同步：
  1. 对每张表：获取本地变更 + 云端变更
  2. 冲突解决
  3. 推送本地变更到云端
  4. 拉取云端变更到本地
  5. 更新同步时间戳

断点续传：同步中断后从上次成功的表继续。
健康检查：通过 get_status() 暴露上次同步时间/成功/失败/队列长度。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List

import structlog

from change_tracker import ChangeTracker
from config import BATCH_SIZE, SYNC_INTERVAL_SECONDS, SYNC_TABLES
from conflict_resolver import ConflictRecord, ConflictResolver
from sync_executor import SyncExecutor

logger = structlog.get_logger()

# 指数退避初始等待（秒）
_BACKOFF_INITIAL: int = 30
_BACKOFF_MAX: int = 3600


# ─── 同步结果数据类 ────────────────────────────────────────────────────────

@dataclass
class SyncRoundResult:
    """一轮同步的结果摘要"""

    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    finished_at: datetime | None = None
    tables_synced: List[str] = field(default_factory=list)
    tables_failed: List[str] = field(default_factory=list)
    total_pushed: int = 0
    total_pulled: int = 0
    total_conflicts: int = 0
    conflict_records: List[ConflictRecord] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "tables_synced": self.tables_synced,
            "tables_failed": self.tables_failed,
            "total_pushed": self.total_pushed,
            "total_pulled": self.total_pulled,
            "total_conflicts": self.total_conflicts,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
        }


# ─── 同步调度器 ────────────────────────────────────────────────────────────

class SyncScheduler:
    """同步调度器：管理增量同步的主循环

    Attributes:
        tracker:    变更追踪器
        executor:   同步执行器
        interval:   同步间隔（秒）
        tables:     待同步表列表
    """

    def __init__(
        self,
        tracker: ChangeTracker | None = None,
        executor: SyncExecutor | None = None,
        interval: int | None = None,
        tables: List[str] | None = None,
    ) -> None:
        self._tracker = tracker or ChangeTracker()
        self._executor = executor or SyncExecutor()
        self._interval = interval or SYNC_INTERVAL_SECONDS
        self._tables = tables or list(SYNC_TABLES)

        # 状态
        self._running: bool = False
        self._sync_count: int = 0
        self._last_result: SyncRoundResult | None = None
        self._last_success_at: datetime | None = None
        self._last_failure_at: datetime | None = None
        self._consecutive_failures: int = 0
        self._task: asyncio.Task[None] | None = None

        # 断点续传：记录上次成功同步到的表索引
        self._resume_index: int = 0

    # ─── 公开接口 ──────────────────────────────────────────────────────────

    async def sync_once(self) -> SyncRoundResult:
        """执行一轮完整同步（所有表），返回结果摘要

        支持断点续传：如果上一轮中断，从上次成功的表之后继续。
        """
        start = time.perf_counter()
        result = SyncRoundResult()

        logger.info(
            "scheduler.sync_once_start",
            tables=self._tables,
            resume_from=self._resume_index,
        )

        tables_to_sync = self._tables[self._resume_index :] + self._tables[: self._resume_index]

        for table in tables_to_sync:
            try:
                pushed, pulled, conflicts = await self._sync_table(table)
                result.tables_synced.append(table)
                result.total_pushed += pushed
                result.total_pulled += pulled
                result.total_conflicts += len(conflicts)
                result.conflict_records.extend(conflicts)

                # 更新断点续传索引（当前表成功，移到下一张）
                idx = self._tables.index(table)
                self._resume_index = (idx + 1) % len(self._tables)

            except (ValueError, OSError, RuntimeError) as exc:
                msg = f"{table}: {exc!s}"
                result.tables_failed.append(table)
                result.errors.append(msg)
                logger.error(
                    "scheduler.sync_table_error",
                    table=table,
                    error=str(exc),
                    exc_info=True,
                )
                # 继续下一张表，不中断整轮同步

        duration_ms = int((time.perf_counter() - start) * 1000)
        result.duration_ms = duration_ms
        result.finished_at = datetime.now(timezone.utc)

        self._sync_count += 1
        self._last_result = result

        if result.ok:
            self._last_success_at = result.finished_at
            self._consecutive_failures = 0
            self._resume_index = 0  # 全部成功，重置断点
        else:
            self._last_failure_at = result.finished_at
            self._consecutive_failures += 1

        logger.info(
            "scheduler.sync_once_done",
            tables_synced=len(result.tables_synced),
            tables_failed=len(result.tables_failed),
            total_pushed=result.total_pushed,
            total_pulled=result.total_pulled,
            total_conflicts=result.total_conflicts,
            duration_ms=duration_ms,
            errors=result.errors,
        )

        return result

    async def run_forever(self) -> None:
        """主循环：每 interval 秒执行一轮完整同步

        带指数退避重试。收到 CancelledError 时正常退出。
        """
        self._running = True
        backoff = _BACKOFF_INITIAL

        logger.info(
            "scheduler.run_forever_start",
            interval_seconds=self._interval,
            tables=self._tables,
        )

        try:
            while self._running:
                try:
                    result = await asyncio.wait_for(
                        self.sync_once(),
                        timeout=self._interval * 2,  # 超时 = 2 倍间隔
                    )

                    if result.ok:
                        backoff = _BACKOFF_INITIAL
                        await asyncio.sleep(self._interval)
                    else:
                        # 部分失败：正常间隔（不退避）
                        logger.warning(
                            "scheduler.partial_errors",
                            errors=result.errors,
                        )
                        await asyncio.sleep(self._interval)

                except asyncio.TimeoutError:
                    logger.error(
                        "scheduler.sync_timeout",
                        timeout_seconds=self._interval * 2,
                    )
                    await asyncio.sleep(self._interval)

                except OSError as exc:
                    logger.error(
                        "scheduler.connection_error",
                        error=str(exc),
                        backoff_seconds=backoff,
                        exc_info=True,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _BACKOFF_MAX)

        except asyncio.CancelledError:
            logger.info("scheduler.run_forever_cancelled")
            self._running = False
            raise

    def start_background(self) -> asyncio.Task[None]:
        """在后台启动调度器（非阻塞），返回 Task"""
        self._task = asyncio.create_task(self.run_forever())
        return self._task

    async def stop(self) -> None:
        """停止调度器"""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("scheduler.stopped")

    async def trigger_sync(self) -> SyncRoundResult:
        """手动触发一轮同步（不等待下一个间隔）"""
        logger.info("scheduler.manual_trigger")
        return await self.sync_once()

    def get_status(self) -> dict[str, Any]:
        """返回同步状态（健康检查）

        Returns:
            {
                "running": bool,
                "sync_count": int,
                "last_success_at": str | None,
                "last_failure_at": str | None,
                "consecutive_failures": int,
                "last_result": {...} | None,
                "interval_seconds": int,
                "tables": [...],
                "resume_index": int,
            }
        """
        return {
            "running": self._running,
            "sync_count": self._sync_count,
            "last_success_at": (
                self._last_success_at.isoformat()
                if self._last_success_at
                else None
            ),
            "last_failure_at": (
                self._last_failure_at.isoformat()
                if self._last_failure_at
                else None
            ),
            "consecutive_failures": self._consecutive_failures,
            "last_result": (
                self._last_result.to_dict() if self._last_result else None
            ),
            "interval_seconds": self._interval,
            "tables": self._tables,
            "resume_index": self._resume_index,
        }

    def get_conflict_log(self, limit: int = 100) -> List[dict[str, Any]]:
        """返回最近的冲突记录（内存中缓存的最后一轮）

        Args:
            limit: 最大返回数量

        Returns:
            冲突记录列表
        """
        if self._last_result is None:
            return []
        return [
            c.to_dict()
            for c in self._last_result.conflict_records[:limit]
        ]

    # ─── 内部方法 ──────────────────────────────────────────────────────────

    async def _sync_table(
        self, table: str
    ) -> tuple[int, int, List[ConflictRecord]]:
        """同步单张表的完整流程

        Returns:
            (pushed_count, pulled_count, conflict_records)
        """
        # 1. 获取上次同步时间
        since = await self._tracker.get_last_sync_time(table)

        # 2. 获取本地和云端的变更
        local_changes = await self._collect_all_changes(
            self._tracker.get_local_changes, table, since
        )
        cloud_changes = await self._collect_all_changes(
            self._tracker.get_cloud_changes, table, since
        )

        if not local_changes and not cloud_changes:
            logger.debug("scheduler.table_no_changes", table=table)
            return 0, 0, []

        # 3. 冲突解决
        conflict_result = ConflictResolver.resolve_conflicts(
            local_changes, cloud_changes
        )

        # 4. 推送本地变更到云端
        pushed = 0
        if conflict_result.to_push:
            pushed = await self._executor.push_to_cloud(
                table, conflict_result.to_push
            )

        # 5. 拉取云端变更到本地
        pulled = 0
        if conflict_result.to_pull:
            pulled = await self._executor.pull_to_local(
                table, conflict_result.to_pull
            )

        # 6. 更新同步时间戳（取所有变更中最大的 updated_at）
        all_records = local_changes + cloud_changes
        max_ts = _max_updated_at(all_records)
        if max_ts is not None:
            await self._tracker.update_sync_time(table, max_ts)

        logger.info(
            "scheduler.table_synced",
            table=table,
            pushed=pushed,
            pulled=pulled,
            conflicts=len(conflict_result.conflicts),
        )

        return pushed, pulled, conflict_result.conflicts

    async def _collect_all_changes(
        self,
        fetch_fn: Any,
        table: str,
        since: datetime,
    ) -> List[dict[str, Any]]:
        """分批收集所有变更记录（处理分页）

        Args:
            fetch_fn: get_local_changes 或 get_cloud_changes
            table:    表名
            since:    起始时间戳

        Returns:
            完整的变更记录列表
        """
        all_records: List[dict[str, Any]] = []
        offset = 0

        while True:
            batch = await fetch_fn(table, since, offset=offset)
            if not batch:
                break
            all_records.extend(batch)
            if len(batch) < BATCH_SIZE:
                break
            offset += len(batch)

        return all_records


# ─── 工具函数 ──────────────────────────────────────────────────────────────

def _max_updated_at(records: List[dict[str, Any]]) -> datetime | None:
    """提取记录列表中最大的 updated_at"""
    timestamps: list[datetime] = []
    for r in records:
        val = r.get("updated_at")
        if val is None:
            continue
        if isinstance(val, datetime):
            ts = val if val.tzinfo else val.replace(tzinfo=timezone.utc)
        elif isinstance(val, str):
            try:
                ts = datetime.fromisoformat(val.replace("Z", "+00:00"))
            except ValueError:
                continue
        else:
            continue
        timestamps.append(ts)

    return max(timestamps) if timestamps else None
