"""Sync Engine — 本地 PG ↔ 云端 PG 增量同步

设计原则：
- 每 300 秒增量同步
- 冲突解决：云端为主（cloud-wins）
- 基于 updated_at 时间戳的增量追踪
- 断网自动重连追补
- 不阻塞业务（异步运行）
"""
import asyncio
import os
import time

import structlog

logger = structlog.get_logger()

SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL_SECONDS", "300"))
CLOUD_DB_URL = os.getenv("CLOUD_DATABASE_URL", "")
LOCAL_DB_URL = os.getenv("LOCAL_DATABASE_URL", "postgresql+asyncpg://tunxiang:local@localhost/tunxiang_local")
BATCH_SIZE = int(os.getenv("SYNC_BATCH_SIZE", "500"))

SYNC_TABLES = [
    "orders",
    "order_items",
    "payments",
    "refunds",
    "customers",
    "dishes",
    "ingredients",
    "employees",
    "settlements",
    "stored_value_cards",
    "stored_value_transactions",
]


class SyncEngine:
    """增量同步引擎 — 基于 updated_at 时间戳"""

    def __init__(self):
        self.last_sync_at: float = 0
        self.sync_count: int = 0
        self.is_running: bool = False
        self.is_connected: bool = False
        self._local_pool = None
        self._cloud_pool = None
        self._sync_watermarks: dict[str, str] = {}

    async def start(self):
        """启动同步循环"""
        await self._init_pools()
        await self._load_watermarks()
        self.is_running = True
        logger.info("sync_engine_started", interval=SYNC_INTERVAL, tables=len(SYNC_TABLES))

        while self.is_running:
            try:
                await self._sync_cycle()
            except (OSError, ConnectionError, asyncio.TimeoutError) as e:
                logger.error("sync_network_error", error=str(e), error_type=type(e).__name__, exc_info=True)
                self.is_connected = False
            except ValueError as e:
                logger.error("sync_data_error", error=str(e), exc_info=True)
                self.is_connected = False

            await asyncio.sleep(SYNC_INTERVAL)

    async def stop(self):
        self.is_running = False
        if self._local_pool:
            await self._local_pool.dispose()
        if self._cloud_pool:
            await self._cloud_pool.dispose()
        logger.info("sync_engine_stopped", total_syncs=self.sync_count)

    async def _init_pools(self):
        """初始化数据库连接池"""
        from sqlalchemy.ext.asyncio import create_async_engine

        self._local_pool = create_async_engine(
            LOCAL_DB_URL,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )

        if CLOUD_DB_URL:
            self._cloud_pool = create_async_engine(
                CLOUD_DB_URL,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
            )
        else:
            logger.warning("no_cloud_db_url", msg="CLOUD_DATABASE_URL not set, upload disabled")

    async def _load_watermarks(self):
        """从本地 _sync_watermarks 表加载上次同步时间戳"""
        if not self._local_pool:
            return
        try:
            async with self._local_pool.connect() as conn:
                from sqlalchemy import text
                await conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS _sync_watermarks ("
                    "  table_name TEXT PRIMARY KEY,"
                    "  last_upload_at TIMESTAMPTZ NOT NULL DEFAULT '1970-01-01',"
                    "  last_download_at TIMESTAMPTZ NOT NULL DEFAULT '1970-01-01'"
                    ")"
                ))
                await conn.commit()

                result = await conn.execute(text("SELECT table_name, last_upload_at, last_download_at FROM _sync_watermarks"))
                for row in result.all():
                    self._sync_watermarks[row[0]] = {
                        "upload": str(row[1]),
                        "download": str(row[2]),
                    }
        except (OSError, ConnectionError) as e:
            logger.warning("watermark_load_failed", error=str(e))

        for table in SYNC_TABLES:
            if table not in self._sync_watermarks:
                self._sync_watermarks[table] = {
                    "upload": "1970-01-01T00:00:00+00:00",
                    "download": "1970-01-01T00:00:00+00:00",
                }

    async def _sync_cycle(self):
        """单次同步周期"""
        start = time.perf_counter()
        total_uploaded = 0
        total_downloaded = 0

        for table in SYNC_TABLES:
            uploaded = await self._upload_table(table)
            total_uploaded += uploaded

            downloaded = await self._download_table(table)
            total_downloaded += downloaded

        duration_ms = int((time.perf_counter() - start) * 1000)
        self.last_sync_at = time.time()
        self.sync_count += 1
        self.is_connected = True

        logger.info(
            "sync_completed",
            cycle=self.sync_count,
            uploaded=total_uploaded,
            downloaded=total_downloaded,
            duration_ms=duration_ms,
        )

    async def _upload_table(self, table: str) -> int:
        """上传单表增量变更：本地 → 云端"""
        if not self._cloud_pool:
            return 0

        from sqlalchemy import text

        watermark = self._sync_watermarks[table]["upload"]
        uploaded = 0

        async with self._local_pool.connect() as local_conn:
            result = await local_conn.execute(
                text(f"SELECT * FROM {table} WHERE updated_at > :since ORDER BY updated_at LIMIT :batch"),
                {"since": watermark, "batch": BATCH_SIZE},
            )
            columns = list(result.keys())
            rows = result.all()

            if not rows:
                return 0

            async with self._cloud_pool.connect() as cloud_conn:
                for row in rows:
                    data = dict(zip(columns, row))
                    placeholders = ", ".join(f":{c}" for c in columns)
                    update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "id")

                    await cloud_conn.execute(
                        text(
                            f"INSERT INTO {table} ({', '.join(columns)}) "
                            f"VALUES ({placeholders}) "
                            f"ON CONFLICT (id) DO UPDATE SET {update_set}"
                        ),
                        data,
                    )
                    uploaded += 1

                await cloud_conn.commit()

            new_watermark = str(rows[-1][columns.index("updated_at")])
            await self._save_watermark(table, "upload", new_watermark)

        logger.info("upload_table", table=table, count=uploaded)
        return uploaded

    async def _download_table(self, table: str) -> int:
        """下载单表增量变更：云端 → 本地（cloud-wins 冲突策略）"""
        if not self._cloud_pool:
            return 0

        from sqlalchemy import text

        watermark = self._sync_watermarks[table]["download"]
        downloaded = 0

        async with self._cloud_pool.connect() as cloud_conn:
            result = await cloud_conn.execute(
                text(f"SELECT * FROM {table} WHERE updated_at > :since ORDER BY updated_at LIMIT :batch"),
                {"since": watermark, "batch": BATCH_SIZE},
            )
            columns = list(result.keys())
            rows = result.all()

            if not rows:
                return 0

            async with self._local_pool.connect() as local_conn:
                for row in rows:
                    data = dict(zip(columns, row))
                    placeholders = ", ".join(f":{c}" for c in columns)
                    update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "id")

                    await local_conn.execute(
                        text(
                            f"INSERT INTO {table} ({', '.join(columns)}) "
                            f"VALUES ({placeholders}) "
                            f"ON CONFLICT (id) DO UPDATE SET {update_set}"
                        ),
                        data,
                    )
                    downloaded += 1

                await local_conn.commit()

            new_watermark = str(rows[-1][columns.index("updated_at")])
            await self._save_watermark(table, "download", new_watermark)

        logger.info("download_table", table=table, count=downloaded)
        return downloaded

    async def _save_watermark(self, table: str, direction: str, timestamp: str):
        """持久化同步水位"""
        from sqlalchemy import text

        col = "last_upload_at" if direction == "upload" else "last_download_at"
        self._sync_watermarks[table][direction] = timestamp

        async with self._local_pool.connect() as conn:
            await conn.execute(
                text(
                    f"INSERT INTO _sync_watermarks (table_name, {col}) VALUES (:table, :ts) "
                    f"ON CONFLICT (table_name) DO UPDATE SET {col} = :ts"
                ),
                {"table": table, "ts": timestamp},
            )
            await conn.commit()

    def get_status(self) -> dict:
        return {
            "is_running": self.is_running,
            "is_connected": self.is_connected,
            "sync_count": self.sync_count,
            "last_sync_at": self.last_sync_at,
            "interval_seconds": SYNC_INTERVAL,
            "tables": SYNC_TABLES,
            "watermarks": self._sync_watermarks,
        }


if __name__ == "__main__":
    engine = SyncEngine()
    asyncio.run(engine.start())
