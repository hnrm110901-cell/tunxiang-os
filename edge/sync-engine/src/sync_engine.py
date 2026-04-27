"""sync_engine.py — 本地 PG ↔ 云端 PG 双向增量同步引擎

核心流程：
  全量同步（full_sync）   — 首次/重置：拉取云端所有数据，UPSERT 本地
  增量同步（incremental_sync） — 定时 5 分钟：仅同步 updated_at > watermark 的记录
  推送本地变更（push_local_changes） — 将 local_change_log 批量推送到云端

冲突策略：云端优先，保留本地终态（见 conflict_resolver.py）
批量大小：每批 500 条，避免内存溢出
"""

from __future__ import annotations

import os
import time
from typing import Any, List

import httpx
import structlog
from conflict_resolver import ConflictResolver
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sync_tracker import SyncTracker

logger = structlog.get_logger()

# ─── 配置常量 ──────────────────────────────────────────────────────────────

CLOUD_API_URL: str = os.getenv("CLOUD_API_URL", "")
LOCAL_DB_URL: str = os.getenv(
    "LOCAL_DATABASE_URL",
    "postgresql+asyncpg://tunxiang:local@localhost/tunxiang_local",
)
BATCH_SIZE: int = int(os.getenv("SYNC_BATCH_SIZE", "500"))
HTTP_TIMEOUT: float = float(os.getenv("SYNC_HTTP_TIMEOUT", "30"))

SYNC_TABLES: List[str] = [
    "orders",
    "order_items",
    "members",
    "inventory_records",
    "kds_tasks",
    "table_production_plans",
]


class SyncEngine:
    """增量同步引擎 — 全量 / 增量双模式"""

    SYNC_TABLES = SYNC_TABLES
    BATCH_SIZE = BATCH_SIZE

    def __init__(
        self,
        tracker: SyncTracker | None = None,
        local_db_url: str | None = None,
        cloud_api_url: str | None = None,
        batch_size: int | None = None,
    ) -> None:
        self._tracker = tracker or SyncTracker()
        self._local_db_url = local_db_url or LOCAL_DB_URL
        self._cloud_api_url = cloud_api_url or CLOUD_API_URL
        self._batch_size = batch_size or BATCH_SIZE
        self._local_pool: AsyncEngine | None = None
        self._sync_count: int = 0
        self._last_sync_at: float = 0.0

    # ─── 生命周期 ──────────────────────────────────────────────────────────

    async def init(self) -> None:
        """初始化本地 PG 连接池和 SQLite 追踪器"""
        self._local_pool = create_async_engine(
            self._local_db_url,
            pool_size=3,
            max_overflow=5,
            pool_pre_ping=True,
        )
        await self._tracker.init_db()
        logger.info(
            "sync_engine.initialized",
            tables=self.SYNC_TABLES,
            batch_size=self._batch_size,
            cloud_api_url=self._cloud_api_url or "(not set)",
        )

    async def close(self) -> None:
        """关闭连接池"""
        if self._local_pool:
            await self._local_pool.dispose()
        logger.info("sync_engine.closed", total_syncs=self._sync_count)

    # ─── 公开接口 ──────────────────────────────────────────────────────────

    async def full_sync(self, tenant_id: str) -> dict:
        """全量同步（首次部署或强制重置）

        流程：
          1. 重置所有表的水位到 epoch
          2. 从云端分批拉取全量数据，UPSERT 到本地 PG
          3. 更新 sync_watermarks

        Returns:
            {"tables": {table: count}, "total": int, "duration_ms": int}
        """
        start = time.perf_counter()
        logger.info("sync_engine.full_sync_start", tenant_id=tenant_id)

        # 重置水位，强制拉取全量
        await self._tracker.reset_watermarks(self.SYNC_TABLES)

        results: dict[str, int] = {}
        for table in self.SYNC_TABLES:
            count = await self._pull_from_cloud_full(table, tenant_id)
            results[table] = count

        total = sum(results.values())
        duration_ms = int((time.perf_counter() - start) * 1000)
        self._sync_count += 1
        self._last_sync_at = time.time()

        logger.info(
            "sync_engine.full_sync_done",
            tenant_id=tenant_id,
            total=total,
            duration_ms=duration_ms,
            tables=results,
        )
        return {"tables": results, "total": total, "duration_ms": duration_ms}

    async def incremental_sync(self, tenant_id: str) -> dict:
        """增量同步（定时每 5 分钟）

        流程：
          1. 读取各表 sync_watermarks
          2. 从云端拉取 updated_at > watermark 的记录，UPSERT 本地（冲突解决）
          3. 将 local_change_log 中未同步变更推送到云端
          4. 更新水位线

        Returns:
            {"downloaded": int, "uploaded": int, "duration_ms": int}
        """
        start = time.perf_counter()
        logger.info("sync_engine.incremental_sync_start", tenant_id=tenant_id)

        total_downloaded = 0
        for table in self.SYNC_TABLES:
            count = await self._pull_incremental(table, tenant_id)
            total_downloaded += count

        total_uploaded = await self.push_local_changes(tenant_id)

        duration_ms = int((time.perf_counter() - start) * 1000)
        self._sync_count += 1
        self._last_sync_at = time.time()

        logger.info(
            "sync_engine.incremental_sync_done",
            tenant_id=tenant_id,
            downloaded=total_downloaded,
            uploaded=total_uploaded,
            duration_ms=duration_ms,
        )
        return {
            "downloaded": total_downloaded,
            "uploaded": total_uploaded,
            "duration_ms": duration_ms,
        }

    async def push_local_changes(self, tenant_id: str) -> int:
        """将 local_change_log 中的未同步变更批量推送到云端

        流程：
          1. 查询 synced=0 的记录（每批 BATCH_SIZE 条）
          2. 批量 POST 到 /api/v1/sync/bulk-upsert
          3. 成功后标记已同步

        Returns:
            推送成功的记录总数
        """
        if not self._cloud_api_url:
            logger.warning("sync_engine.push_skipped", reason="CLOUD_API_URL not set")
            return 0

        total_synced = 0
        while True:
            pending = await self._tracker.get_pending_changes(self._batch_size)
            if not pending:
                break

            # 按表分组批量推送
            by_table: dict[str, list[dict]] = {}
            id_map: dict[str, list[int]] = {}
            for change in pending:
                t = change["table_name"]
                by_table.setdefault(t, []).append(change["payload"])
                id_map.setdefault(t, []).append(change["id"])

            synced_ids: list[int] = []
            for table, records in by_table.items():
                ok = await self._bulk_upsert_to_cloud(table, records, tenant_id)
                if ok:
                    synced_ids.extend(id_map[table])
                    total_synced += len(records)
                else:
                    logger.warning(
                        "sync_engine.push_batch_failed",
                        table=table,
                        count=len(records),
                    )

            if synced_ids:
                await self._tracker.mark_changes_synced(synced_ids)

            # 如果这批次没有完全推送成功，停止，避免无限循环
            if len(pending) < self._batch_size:
                break

        logger.info("sync_engine.push_done", total_synced=total_synced)
        return total_synced

    def get_status(self) -> dict:
        return {
            "sync_count": self._sync_count,
            "last_sync_at": self._last_sync_at,
            "batch_size": self._batch_size,
            "tables": self.SYNC_TABLES,
            "cloud_api_url": self._cloud_api_url or "(not set)",
        }

    # ─── 内部方法：云端拉取 ────────────────────────────────────────────────

    async def _pull_from_cloud_full(self, table: str, tenant_id: str) -> int:
        """全量拉取：分批拉取云端所有记录并 UPSERT 到本地 PG"""
        if not self._cloud_api_url:
            return 0

        total = 0
        page = 1
        last_ts = "1970-01-01T00:00:00+00:00"

        while True:
            records = await self._fetch_from_cloud(table, tenant_id, since=None, page=page, size=self._batch_size)
            if not records:
                break

            await self._upsert_to_local(table, records, resolve_conflicts=False)
            total += len(records)

            # 更新水位为本批最大 updated_at
            batch_ts = _max_updated_at(records)
            if batch_ts > last_ts:
                last_ts = batch_ts

            if len(records) < self._batch_size:
                break
            page += 1

        if last_ts > "1970-01-01T00:00:00+00:00":
            await self._tracker.set_watermark(table, last_ts, record_count=total)

        logger.info("sync_engine.full_pull_done", table=table, total=total)
        return total

    async def _pull_incremental(self, table: str, tenant_id: str) -> int:
        """增量拉取：只拉取 updated_at > watermark 的记录"""
        if not self._cloud_api_url:
            return 0

        watermark = await self._tracker.get_watermark(table)
        total = 0
        page = 1
        last_ts = watermark

        while True:
            records = await self._fetch_from_cloud(table, tenant_id, since=watermark, page=page, size=self._batch_size)
            if not records:
                break

            await self._upsert_to_local(table, records, resolve_conflicts=True)
            total += len(records)

            batch_ts = _max_updated_at(records)
            if batch_ts > last_ts:
                last_ts = batch_ts

            if len(records) < self._batch_size:
                break
            page += 1

        if total > 0:
            await self._tracker.set_watermark(table, last_ts)
            logger.info(
                "sync_engine.incremental_pull_done",
                table=table,
                total=total,
                new_watermark=last_ts,
            )

        return total

    async def _fetch_from_cloud(
        self,
        table: str,
        tenant_id: str,
        since: str | None,
        page: int = 1,
        size: int = 500,
    ) -> List[dict]:
        """向云端 API 请求数据

        GET /api/v1/sync/{table}?since=<ts>&page=<n>&size=<n>
        返回 {"ok": true, "data": {"items": [...], "total": int}}
        """
        params: dict[str, Any] = {"page": page, "size": size}
        if since:
            params["since"] = since

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.get(
                    f"{self._cloud_api_url}/api/v1/sync/{table}",
                    params=params,
                    headers={"X-Tenant-ID": tenant_id},
                )
                resp.raise_for_status()
                body = resp.json()
                if not body.get("ok"):
                    logger.warning(
                        "sync_engine.cloud_fetch_nok",
                        table=table,
                        error=body.get("error"),
                    )
                    return []
                return body.get("data", {}).get("items", [])
        except httpx.ConnectError as exc:
            logger.error("sync_engine.cloud_connect_error", table=table, error=str(exc))
            raise
        except httpx.TimeoutException as exc:
            logger.error("sync_engine.cloud_timeout", table=table, error=str(exc))
            raise
        except httpx.HTTPStatusError as exc:
            logger.error(
                "sync_engine.cloud_http_error",
                table=table,
                status=exc.response.status_code,
                error=str(exc),
            )
            return []

    # ─── 内部方法：本地写入 ────────────────────────────────────────────────

    async def _upsert_to_local(self, table: str, records: List[dict], resolve_conflicts: bool = True) -> None:
        """批量 UPSERT 到本地 PG

        当 resolve_conflicts=True 时，先查询本地现有记录，调用 ConflictResolver 决定最终值。
        全量同步时 resolve_conflicts=False，直接以远端为准（性能优先）。
        """
        if not records or not self._local_pool:
            return

        if resolve_conflicts:
            records = await self._apply_conflict_resolution(table, records)

        # 动态构造 UPSERT SQL（需要所有列名一致，取第一条记录的 keys）
        columns = list(records[0].keys())
        if "id" not in columns:
            logger.warning("sync_engine.upsert_no_id_column", table=table)
            return

        col_list = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join(f":{c}" for c in columns)
        update_set = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in columns if c != "id")
        sql = f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}) ON CONFLICT (id) DO UPDATE SET {update_set}'

        try:
            async with self._local_pool.begin() as conn:
                for record in records:
                    # 确保每条记录都有全部列（防止云端字段不一致）
                    row = {c: record.get(c) for c in columns}
                    await conn.execute(text(sql), row)
        except SQLAlchemyError as exc:
            logger.error(
                "sync_engine.upsert_error",
                table=table,
                error=str(exc),
                exc_info=True,
            )
            raise

    async def _apply_conflict_resolution(self, table: str, remote_records: List[dict]) -> List[dict]:
        """对每条远端记录进行冲突解决，返回最终要写入的记录列表"""
        if not self._local_pool:
            return remote_records

        ids = [r.get("id") for r in remote_records if r.get("id")]
        if not ids:
            return remote_records

        placeholders = ", ".join(f":id_{i}" for i in range(len(ids)))
        params = {f"id_{i}": v for i, v in enumerate(ids)}

        local_map: dict[Any, dict] = {}
        try:
            async with self._local_pool.connect() as conn:
                result = await conn.execute(
                    text(f'SELECT * FROM "{table}" WHERE id IN ({placeholders})'),
                    params,
                )
                columns = list(result.keys())
                for row in result.all():
                    d = dict(zip(columns, row))
                    local_map[d["id"]] = d
        except SQLAlchemyError as exc:
            logger.warning(
                "sync_engine.conflict_fetch_error",
                table=table,
                error=str(exc),
            )
            return remote_records

        resolved = []
        for remote in remote_records:
            rid = remote.get("id")
            local = local_map.get(rid)
            if local:
                resolved.append(ConflictResolver.resolve(local, remote))
            else:
                resolved.append(remote)
        return resolved

    # ─── 内部方法：云端推送 ────────────────────────────────────────────────

    async def _bulk_upsert_to_cloud(self, table: str, records: List[dict], tenant_id: str) -> bool:
        """批量推送到云端 /api/v1/sync/bulk-upsert

        POST /api/v1/sync/bulk-upsert
        Body: {"table": str, "records": [...]}
        """
        if not self._cloud_api_url or not records:
            return False

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.post(
                    f"{self._cloud_api_url}/api/v1/sync/bulk-upsert",
                    json={"table": table, "records": records},
                    headers={"X-Tenant-ID": tenant_id},
                )
                resp.raise_for_status()
                body = resp.json()
                if not body.get("ok"):
                    logger.warning(
                        "sync_engine.bulk_upsert_nok",
                        table=table,
                        error=body.get("error"),
                    )
                    return False
                return True
        except httpx.ConnectError as exc:
            logger.error(
                "sync_engine.cloud_push_connect_error",
                table=table,
                error=str(exc),
            )
            return False
        except httpx.TimeoutException as exc:
            logger.error("sync_engine.cloud_push_timeout", table=table, error=str(exc))
            return False
        except httpx.HTTPStatusError as exc:
            logger.error(
                "sync_engine.cloud_push_http_error",
                table=table,
                status=exc.response.status_code,
                error=str(exc),
            )
            return False


# ─── 工具函数 ──────────────────────────────────────────────────────────────


def _max_updated_at(records: List[dict]) -> str:
    """提取记录列表中最大的 updated_at 字符串"""
    ts_list = [str(r["updated_at"]) for r in records if r.get("updated_at") is not None]
    return max(ts_list) if ts_list else "1970-01-01T00:00:00+00:00"
