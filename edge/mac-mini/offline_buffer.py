"""离线订单缓冲区 — Mac mini 端

断网时将新订单写入本地 SQLite 缓冲区，恢复连接后增量同步到云端。

特性：
- 幂等性：相同 order_id 不产生重复记录（UPSERT），同步也是幂等的
- 断电安全：SQLite WAL 模式保障写入持久性
- 增量同步：只同步 synced=False 的记录，已同步的不重复发送

SQLite 文件路径通过环境变量 OFFLINE_BUFFER_DB 配置。
"""

import json
import os
from datetime import datetime, timezone
from typing import Awaitable, Callable, List, Optional

import aiosqlite
import structlog

logger = structlog.get_logger()

# 默认 SQLite 数据库路径（通过环境变量覆盖）
DEFAULT_DB_PATH = os.getenv("OFFLINE_BUFFER_DB", "/var/lib/tunxiang/offline_buffer.db")

# POST 函数类型：(url: str, json_data: dict) -> dict
PostFn = Callable[[str, dict], Awaitable[dict]]


class OfflineBuffer:
    """离线订单缓冲区：SQLite 持久化 + 幂等同步"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(self._db_path) if os.path.dirname(self._db_path) else ".", exist_ok=True)

    async def init_db(self) -> None:
        """初始化 SQLite 数据库，启用 WAL 模式"""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS buffered_orders (
                    order_id        TEXT    PRIMARY KEY,
                    order_data_json TEXT    NOT NULL,
                    synced          INTEGER NOT NULL DEFAULT 0,
                    created_at      TEXT    NOT NULL,
                    synced_at       TEXT
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_buffered_orders_synced ON buffered_orders(synced)")
            await db.commit()
        logger.info("offline_buffer.db_initialized", db_path=self._db_path)

    async def buffer_order(self, order: dict) -> None:
        """断网时缓存订单（幂等：相同 order_id 执行 UPSERT）

        Args:
            order: 订单数据字典，必须包含 order_id 字段
        """
        order_id = order.get("order_id")
        if not order_id:
            logger.error("offline_buffer.missing_order_id", order_keys=list(order.keys()))
            raise ValueError("order 字典必须包含 order_id 字段")

        now = datetime.now(timezone.utc).isoformat()
        order_json = json.dumps(order, ensure_ascii=False)

        async with aiosqlite.connect(self._db_path) as db:
            # INSERT OR REPLACE 实现幂等性：相同 order_id 只保留最新数据
            # 注意：同步状态重置为未同步（新数据需要重新同步）
            # 但如果已经同步过，保留 synced=True 避免重复同步
            await db.execute(
                """
                INSERT INTO buffered_orders (order_id, order_data_json, synced, created_at)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    order_data_json = excluded.order_data_json,
                    synced = CASE
                        WHEN synced = 1 THEN 1
                        ELSE 0
                    END
                """,
                (order_id, order_json, now),
            )
            await db.commit()

        logger.info("offline_buffer.order_buffered", order_id=order_id)

    async def sync_to_cloud(self, cloud_api_url: str, post_fn: Optional[PostFn] = None) -> dict:
        """恢复连接后将未同步订单推送到云端 API（幂等）

        Args:
            cloud_api_url: 云端订单接口地址
            post_fn: 可注入的 HTTP POST 函数（测试时注入 mock）
                     默认使用 httpx 异步客户端

        Returns:
            {"synced": int, "failed": int}
        """
        if post_fn is None:
            post_fn = _default_post_fn()

        pending = await self.get_pending_orders()
        synced_count = 0
        failed_count = 0

        for record in pending:
            order_id = record["order_id"]
            order_data = json.loads(record["order_data_json"])
            log = logger.bind(order_id=order_id)

            try:
                result = await post_fn(cloud_api_url, order_data)
                if result.get("ok"):
                    await self._mark_synced(order_id)
                    synced_count += 1
                    log.info("offline_buffer.order_synced")
                else:
                    failed_count += 1
                    log.warning("offline_buffer.sync_failed", response=result)
            except Exception as exc:
                failed_count += 1
                log.error("offline_buffer.sync_exception", error=str(exc), exc_info=True)

        logger.info(
            "offline_buffer.sync_complete",
            synced=synced_count,
            failed=failed_count,
            total=len(pending),
        )
        return {"synced": synced_count, "failed": failed_count}

    async def get_pending_orders(self) -> List[dict]:
        """查询所有未同步的订单记录"""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM buffered_orders WHERE synced = 0 ORDER BY created_at ASC")
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_pending_count(self) -> int:
        """查询待同步订单数量，用于状态显示"""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM buffered_orders WHERE synced = 0")
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_all_orders(self) -> List[dict]:
        """查询所有订单（含已同步），用于调试"""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM buffered_orders ORDER BY created_at ASC")
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ─── 内部辅助方法 ───

    async def _mark_synced(self, order_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE buffered_orders SET synced = 1, synced_at = ? WHERE order_id = ?",
                (now, order_id),
            )
            await db.commit()


def _default_post_fn() -> PostFn:
    """返回使用 httpx 的默认 POST 函数"""

    async def _post(url: str, json_data: dict) -> dict:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=json_data)
                return resp.json()
        except httpx.ConnectError as exc:
            logger.error("offline_buffer.http_connect_error", url=url, error=str(exc))
            return {"ok": False, "error": str(exc)}
        except httpx.TimeoutException as exc:
            logger.error("offline_buffer.http_timeout", url=url, error=str(exc))
            return {"ok": False, "error": str(exc)}
        except httpx.HTTPError as exc:
            logger.error("offline_buffer.http_error", url=url, error=str(exc))
            return {"ok": False, "error": str(exc)}

    return _post
