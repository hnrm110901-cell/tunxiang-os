"""Sync Engine — 本地 PG ↔ 云端 PG 增量同步

设计原则：
- 每 300 秒增量同步
- 冲突解决：云端为主
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
LOCAL_DB_URL = os.getenv("LOCAL_DATABASE_URL", "postgresql://tunxiang:local@localhost/tunxiang_local")

# 核心交易表（需要双向同步）
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
]


class SyncEngine:
    """增量同步引擎"""

    def __init__(self):
        self.last_sync_at: float = 0
        self.sync_count: int = 0
        self.is_running: bool = False
        self.is_connected: bool = False

    async def start(self):
        """启动同步循环"""
        self.is_running = True
        logger.info("sync_engine_started", interval=SYNC_INTERVAL, tables=len(SYNC_TABLES))

        while self.is_running:
            try:
                await self._sync_cycle()
            except Exception as e:
                logger.error("sync_error", error=str(e))
                self.is_connected = False

            await asyncio.sleep(SYNC_INTERVAL)

    async def stop(self):
        self.is_running = False
        logger.info("sync_engine_stopped", total_syncs=self.sync_count)

    async def _sync_cycle(self):
        """单次同步周期"""
        start = time.perf_counter()

        # 1. 上传：本地变更 → 云端
        local_changes = await self._get_local_changes()
        if local_changes:
            await self._push_to_cloud(local_changes)

        # 2. 下载：云端变更 → 本地
        cloud_changes = await self._get_cloud_changes()
        if cloud_changes:
            await self._apply_to_local(cloud_changes)

        duration_ms = int((time.perf_counter() - start) * 1000)
        self.last_sync_at = time.time()
        self.sync_count += 1
        self.is_connected = True

        logger.info(
            "sync_completed",
            cycle=self.sync_count,
            uploaded=len(local_changes),
            downloaded=len(cloud_changes),
            duration_ms=duration_ms,
        )

    async def _get_local_changes(self) -> list[dict]:
        """获取本地自上次同步后的变更（基于 updated_at）"""
        # TODO: 使用 PG logical replication 或 updated_at 比较
        return []

    async def _push_to_cloud(self, changes: list[dict]):
        """上传变更到云端"""
        # TODO: 批量 upsert 到云端 PG
        logger.info("push_to_cloud", count=len(changes))

    async def _get_cloud_changes(self) -> list[dict]:
        """获取云端自上次同步后的变更"""
        # TODO: 查询云端 PG 的增量变更
        return []

    async def _apply_to_local(self, changes: list[dict]):
        """应用云端变更到本地（云端为主，冲突覆盖）"""
        # TODO: 批量 upsert 到本地 PG，冲突时云端优先
        logger.info("apply_to_local", count=len(changes))

    def get_status(self) -> dict:
        return {
            "is_running": self.is_running,
            "is_connected": self.is_connected,
            "sync_count": self.sync_count,
            "last_sync_at": self.last_sync_at,
            "interval_seconds": SYNC_INTERVAL,
            "tables": SYNC_TABLES,
        }


# CLI 入口
if __name__ == "__main__":
    engine = SyncEngine()
    asyncio.run(engine.start())
