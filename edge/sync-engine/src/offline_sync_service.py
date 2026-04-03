"""offline_sync_service.py — 离线收银同步服务

职责：
  - 断网时将订单快照存入 offline_order_queue（本地 PG）
  - 网络恢复后批量推送离线订单到云端
  - 拉取云端最新数据（菜单/会员/配置）
  - 冲突解决：云端为主，保留本地备份
  - 查询同步状态（pending_count / last_sync_at / is_connected）

设计约束：
  - 所有金额以分（fen）整型存储
  - 异步运行，不阻塞收银业务
  - 冲突策略：服务端为主（server-wins），本地记录冲突原因
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = structlog.get_logger()

# ─── 环境配置 ──────────────────────────────────────────────────────────────

LOCAL_DB_URL: str = os.getenv(
    "LOCAL_DATABASE_URL",
    "postgresql+asyncpg://tunxiang:local@localhost/tunxiang_local",
)
CLOUD_API_URL: str = os.getenv("CLOUD_API_URL", "")
HTTP_TIMEOUT: float = float(os.getenv("SYNC_HTTP_TIMEOUT", "15"))
CLOUD_CONNECT_TIMEOUT: float = float(os.getenv("CLOUD_CONNECT_TIMEOUT", "5"))
MAX_RETRY_COUNT: int = int(os.getenv("OFFLINE_MAX_RETRY", "5"))
PUSH_BATCH_SIZE: int = int(os.getenv("OFFLINE_PUSH_BATCH_SIZE", "50"))


# ─── 数据模型 ──────────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    """批量同步结果"""
    success_count: int = 0
    failed_count: int = 0
    conflict_count: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class SyncStatus:
    """设备同步状态"""
    is_connected: bool
    pending_orders: int
    last_sync_at: Optional[datetime]
    last_pull_at: Optional[datetime]


@dataclass
class ConflictResolution:
    """冲突解决结果"""
    local_order_id: str
    server_order_id: Optional[str]
    resolution: str  # "server_wins" | "local_backup"
    conflict_reason: str


# ─── 核心服务 ──────────────────────────────────────────────────────────────

class OfflineSyncService:
    """离线收银同步服务

    使用方：
        service = OfflineSyncService()
        await service.init()
        ...
        await service.close()
    """

    def __init__(
        self,
        local_db_url: str | None = None,
        cloud_api_url: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self._local_db_url = local_db_url or LOCAL_DB_URL
        self._cloud_api_url = cloud_api_url or CLOUD_API_URL
        self._tenant_id = tenant_id or os.getenv("TENANT_ID", "")
        self._pool: AsyncEngine | None = None

    # ─── 生命周期 ──────────────────────────────────────────────────────────

    async def init(self) -> None:
        """初始化本地 PG 连接池"""
        self._pool = create_async_engine(
            self._local_db_url,
            pool_size=3,
            max_overflow=5,
            pool_pre_ping=True,
        )
        logger.info(
            "offline_sync_service.initialized",
            cloud_api_url=self._cloud_api_url or "(not set)",
        )

    async def close(self) -> None:
        """释放连接池"""
        if self._pool:
            await self._pool.dispose()
        logger.info("offline_sync_service.closed")

    # ─── 公开接口 ──────────────────────────────────────────────────────────

    async def queue_offline_order(
        self,
        order_data: dict[str, Any],
        items_data: list[dict[str, Any]],
        payments_data: list[dict[str, Any]] | None = None,
        tenant_id: str | None = None,
        store_id: str | None = None,
    ) -> str:
        """断网时将订单存入离线队列，返回 local_order_id

        Args:
            order_data:     完整订单快照（含 total_amount_fen 等金额字段，单位：分）
            items_data:     订单明细快照列表
            payments_data:  支付数据快照列表（可选）
            tenant_id:      租户 ID（可从订单数据中获取，此处显式传入优先）
            store_id:       门店 ID

        Returns:
            local_order_id — 本地临时唯一标识（格式：LOCAL-{uuid4_hex}）
        """
        local_order_id = f"LOCAL-{uuid.uuid4().hex.upper()}"
        tid = tenant_id or self._tenant_id or order_data.get("tenant_id", "")
        sid = store_id or order_data.get("store_id", "")

        if not tid:
            raise ValueError("tenant_id is required for offline queueing")
        if not sid:
            raise ValueError("store_id is required for offline queueing")

        now = datetime.now(timezone.utc)

        async with self._get_conn() as conn:
            await conn.execute(
                text("""
                    INSERT INTO offline_order_queue
                        (id, tenant_id, store_id, local_order_id,
                         order_data, items_data, payments_data,
                         sync_status, created_offline_at)
                    VALUES
                        (:id, :tenant_id, :store_id, :local_order_id,
                         :order_data::jsonb, :items_data::jsonb, :payments_data::jsonb,
                         'pending', :created_offline_at)
                """),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": tid,
                    "store_id": sid,
                    "local_order_id": local_order_id,
                    "order_data": _json_dumps(order_data),
                    "items_data": _json_dumps(items_data),
                    "payments_data": _json_dumps(payments_data) if payments_data else None,
                    "created_offline_at": now,
                },
            )

        logger.info(
            "offline_sync_service.order_queued",
            local_order_id=local_order_id,
            store_id=sid,
            tenant_id=tid,
        )
        return local_order_id

    async def sync_pending_orders(
        self,
        store_id: str,
        tenant_id: str | None = None,
    ) -> SyncResult:
        """网络恢复后，批量推送离线订单到服务端

        流程：
          1. 查询 sync_status='pending' 且 retry_count < MAX_RETRY_COUNT 的记录
          2. 标记为 'syncing'
          3. 批量 POST 到云端 /api/v1/sync/offline-orders
          4. 成功 → 标记 'synced'；冲突 → 调用 resolve_conflict；失败 → 增加 retry_count

        Returns:
            SyncResult 汇总推送结果
        """
        tid = tenant_id or self._tenant_id
        if not tid:
            raise ValueError("tenant_id is required for sync")

        result = SyncResult()
        page_offset = 0

        while True:
            rows = await self._fetch_pending_rows(store_id, tid, PUSH_BATCH_SIZE, page_offset)
            if not rows:
                break

            row_ids = [r["id"] for r in rows]
            await self._mark_status(row_ids, "syncing")

            for row in rows:
                local_order_id: str = row["local_order_id"]
                try:
                    push_result = await self._push_single_order(row, tid)

                    if push_result["status"] == "ok":
                        await self._mark_synced(row["id"], push_result.get("server_order_id"))
                        result.success_count += 1
                        logger.info(
                            "offline_sync_service.order_synced",
                            local_order_id=local_order_id,
                            server_order_id=push_result.get("server_order_id"),
                        )

                    elif push_result["status"] == "conflict":
                        conflict_reason = push_result.get("reason", "server conflict")
                        await self.resolve_conflict(
                            local_order_id,
                            push_result.get("server_order_id"),
                            conflict_reason=conflict_reason,
                            queue_row_id=row["id"],
                        )
                        result.conflict_count += 1

                    else:
                        error_msg = push_result.get("error", "unknown push error")
                        await self._increment_retry(row["id"], error_msg)
                        result.failed_count += 1
                        result.errors.append(f"{local_order_id}: {error_msg}")

                except (httpx.ConnectError, httpx.TimeoutException) as exc:
                    await self._increment_retry(row["id"], str(exc))
                    result.failed_count += 1
                    result.errors.append(f"{local_order_id}: network error — {exc}")
                    logger.warning(
                        "offline_sync_service.push_network_error",
                        local_order_id=local_order_id,
                        error=str(exc),
                    )
                except SQLAlchemyError as exc:
                    result.failed_count += 1
                    result.errors.append(f"{local_order_id}: db error — {exc}")
                    logger.error(
                        "offline_sync_service.push_db_error",
                        local_order_id=local_order_id,
                        error=str(exc),
                        exc_info=True,
                    )

            if len(rows) < PUSH_BATCH_SIZE:
                break
            page_offset += PUSH_BATCH_SIZE

        # 更新 sync_checkpoints.last_push_at
        await self._update_checkpoint_push(store_id, tid)

        logger.info(
            "offline_sync_service.sync_done",
            store_id=store_id,
            success=result.success_count,
            failed=result.failed_count,
            conflict=result.conflict_count,
        )
        return result

    async def pull_updates(
        self,
        store_id: str,
        device_id: str,
        since_seq: int,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """拉取服务端最新数据（菜单变更、会员信息、配置等）

        GET /api/v1/sync/pull?store_id=...&since_seq=...

        Args:
            store_id:   门店 ID
            device_id:  设备 ID（用于更新 sync_checkpoints）
            since_seq:  上次拉取的序列号（0 表示全量）
            tenant_id:  租户 ID

        Returns:
            变更记录列表 [{"seq": int, "type": str, "payload": {...}}, ...]
        """
        tid = tenant_id or self._tenant_id
        if not tid:
            raise ValueError("tenant_id is required for pull")

        if not self._cloud_api_url:
            logger.warning("offline_sync_service.pull_skipped", reason="CLOUD_API_URL not set")
            return []

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.get(
                    f"{self._cloud_api_url}/api/v1/sync/pull",
                    params={"store_id": store_id, "since_seq": since_seq},
                    headers={"X-Tenant-ID": tid},
                )
                resp.raise_for_status()
                body = resp.json()

            if not body.get("ok"):
                logger.warning(
                    "offline_sync_service.pull_nok",
                    error=body.get("error"),
                )
                return []

            items: list[dict[str, Any]] = body.get("data", {}).get("items", [])

            # 更新 sync_checkpoints
            if items:
                max_seq = max(i.get("seq", 0) for i in items)
                await self._update_checkpoint_pull(store_id, device_id, tid, max_seq)

            logger.info(
                "offline_sync_service.pull_done",
                store_id=store_id,
                device_id=device_id,
                since_seq=since_seq,
                received=len(items),
            )
            return items

        except httpx.ConnectError as exc:
            logger.warning(
                "offline_sync_service.pull_connect_error",
                store_id=store_id,
                error=str(exc),
            )
            return []
        except httpx.TimeoutException as exc:
            logger.warning(
                "offline_sync_service.pull_timeout",
                store_id=store_id,
                error=str(exc),
            )
            return []
        except httpx.HTTPStatusError as exc:
            logger.error(
                "offline_sync_service.pull_http_error",
                store_id=store_id,
                status=exc.response.status_code,
                error=str(exc),
                exc_info=True,
            )
            return []

    async def resolve_conflict(
        self,
        local_order_id: str,
        server_order_id: Optional[str],
        conflict_reason: str = "server conflict",
        queue_row_id: str | None = None,
    ) -> ConflictResolution:
        """冲突解决：以服务端为准，保留本地备份记录

        策略：server_wins
          - 本地记录标记为 conflict，写入冲突原因
          - 服务端数据已持久化（云端为准）
          - 本地离线记录作为审计备份保留

        Args:
            local_order_id:   本地临时订单 ID
            server_order_id:  服务端实际订单 ID（可为 None）
            conflict_reason:  冲突说明
            queue_row_id:     offline_order_queue 行 ID（可选，加速查找）

        Returns:
            ConflictResolution
        """
        now = datetime.now(timezone.utc)

        where_clause = "local_order_id = :local_order_id"
        params: dict[str, Any] = {
            "local_order_id": local_order_id,
            "conflict_reason": conflict_reason,
            "synced_at": now,
        }
        if queue_row_id:
            where_clause = "id = :id"
            params["id"] = queue_row_id

        async with self._get_conn() as conn:
            await conn.execute(
                text(f"""
                    UPDATE offline_order_queue
                    SET sync_status = 'conflict',
                        conflict_reason = :conflict_reason,
                        synced_at = :synced_at
                    WHERE {where_clause}
                """),
                params,
            )

        resolution = ConflictResolution(
            local_order_id=local_order_id,
            server_order_id=server_order_id,
            resolution="server_wins",
            conflict_reason=conflict_reason,
        )

        logger.warning(
            "offline_sync_service.conflict_resolved",
            local_order_id=local_order_id,
            server_order_id=server_order_id,
            reason=conflict_reason,
            resolution="server_wins",
        )
        return resolution

    async def get_sync_status(
        self,
        store_id: str,
        device_id: str,
        tenant_id: str | None = None,
    ) -> SyncStatus:
        """获取同步状态

        Returns:
            SyncStatus(is_connected, pending_orders, last_sync_at, last_pull_at)
        """
        tid = tenant_id or self._tenant_id
        if not tid:
            raise ValueError("tenant_id is required for get_sync_status")

        is_connected = await self._check_cloud_connection()
        pending_count = await self._count_pending(store_id, tid)
        checkpoint = await self._get_checkpoint(store_id, device_id, tid)

        return SyncStatus(
            is_connected=is_connected,
            pending_orders=pending_count,
            last_sync_at=checkpoint.get("last_push_at"),
            last_pull_at=checkpoint.get("last_pull_at"),
        )

    # ─── 内部：云端连通检测 ────────────────────────────────────────────────

    async def _check_cloud_connection(self) -> bool:
        """尝试 GET /health，返回是否可达"""
        if not self._cloud_api_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=CLOUD_CONNECT_TIMEOUT) as client:
                resp = await client.get(f"{self._cloud_api_url}/health")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
            return False

    # ─── 内部：离线队列查询 ────────────────────────────────────────────────

    async def _fetch_pending_rows(
        self, store_id: str, tenant_id: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        """查询待同步行"""
        async with self._get_conn() as conn:
            result = await conn.execute(
                text("""
                    SELECT id, tenant_id, store_id, local_order_id,
                           order_data, items_data, payments_data, retry_count
                    FROM offline_order_queue
                    WHERE tenant_id = :tenant_id
                      AND store_id = :store_id
                      AND sync_status = 'pending'
                      AND retry_count < :max_retry
                    ORDER BY created_offline_at ASC
                    LIMIT :limit OFFSET :offset
                """),
                {
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "max_retry": MAX_RETRY_COUNT,
                    "limit": limit,
                    "offset": offset,
                },
            )
            keys = list(result.keys())
            return [dict(zip(keys, row)) for row in result.all()]

    async def _mark_status(self, row_ids: list[str], status: str) -> None:
        """批量更新 sync_status"""
        if not row_ids:
            return
        placeholders = ", ".join(f":id_{i}" for i in range(len(row_ids)))
        params: dict[str, Any] = {"status": status}
        params.update({f"id_{i}": v for i, v in enumerate(row_ids)})
        async with self._get_conn() as conn:
            await conn.execute(
                text(f"""
                    UPDATE offline_order_queue
                    SET sync_status = :status
                    WHERE id IN ({placeholders})
                """),
                params,
            )

    async def _mark_synced(self, row_id: str, server_order_id: str | None) -> None:
        """标记单条记录同步成功"""
        async with self._get_conn() as conn:
            await conn.execute(
                text("""
                    UPDATE offline_order_queue
                    SET sync_status = 'synced',
                        synced_at = :synced_at,
                        order_data = order_data || :patch::jsonb
                    WHERE id = :id
                """),
                {
                    "id": row_id,
                    "synced_at": datetime.now(timezone.utc),
                    "patch": _json_dumps({"server_order_id": server_order_id} if server_order_id else {}),
                },
            )

    async def _increment_retry(self, row_id: str, error_msg: str) -> None:
        """推送失败：增加重试计数，回退为 pending"""
        async with self._get_conn() as conn:
            await conn.execute(
                text("""
                    UPDATE offline_order_queue
                    SET sync_status = 'pending',
                        retry_count = retry_count + 1,
                        conflict_reason = :error_msg
                    WHERE id = :id
                """),
                {"id": row_id, "error_msg": error_msg[:500]},
            )

    async def _count_pending(self, store_id: str, tenant_id: str) -> int:
        """统计待同步订单数"""
        async with self._get_conn() as conn:
            result = await conn.execute(
                text("""
                    SELECT COUNT(*)
                    FROM offline_order_queue
                    WHERE tenant_id = :tenant_id
                      AND store_id = :store_id
                      AND sync_status IN ('pending', 'syncing')
                """),
                {"tenant_id": tenant_id, "store_id": store_id},
            )
            row = result.one()
            return int(row[0])

    # ─── 内部：云端推送单条 ────────────────────────────────────────────────

    async def _push_single_order(
        self, row: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        """推送单条离线订单到云端

        POST /api/v1/sync/offline-orders
        Body: {local_order_id, order_data, items_data, payments_data}
        Response: {ok, data: {status: "ok"|"conflict", server_order_id, reason}}
        """
        if not self._cloud_api_url:
            return {"status": "failed", "error": "CLOUD_API_URL not set"}

        payload = {
            "local_order_id": row["local_order_id"],
            "order_data": row["order_data"],
            "items_data": row["items_data"],
            "payments_data": row.get("payments_data"),
        }

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{self._cloud_api_url}/api/v1/sync/offline-orders",
                json=payload,
                headers={"X-Tenant-ID": tenant_id},
            )

        if resp.status_code == 409:
            body = resp.json()
            return {
                "status": "conflict",
                "server_order_id": body.get("data", {}).get("server_order_id"),
                "reason": body.get("data", {}).get("reason", "duplicate order"),
            }

        resp.raise_for_status()
        body = resp.json()
        if not body.get("ok"):
            return {"status": "failed", "error": body.get("error", {}).get("message", "unknown")}

        return {
            "status": "ok",
            "server_order_id": body.get("data", {}).get("server_order_id"),
        }

    # ─── 内部：sync_checkpoints CRUD ──────────────────────────────────────

    async def _get_checkpoint(
        self, store_id: str, device_id: str, tenant_id: str
    ) -> dict[str, Any]:
        """读取设备同步检查点，不存在时返回空字典"""
        async with self._get_conn() as conn:
            result = await conn.execute(
                text("""
                    SELECT last_pull_seq, last_push_at, last_pull_at
                    FROM sync_checkpoints
                    WHERE tenant_id = :tenant_id
                      AND store_id = :store_id
                      AND device_id = :device_id
                """),
                {"tenant_id": tenant_id, "store_id": store_id, "device_id": device_id},
            )
            row = result.one_or_none()
            if not row:
                return {}
            keys = list(result.keys())
            return dict(zip(keys, row))

    async def _update_checkpoint_push(self, store_id: str, tenant_id: str) -> None:
        """所有设备该门店的 last_push_at 更新（不强制依赖 device_id）"""
        now = datetime.now(timezone.utc)
        async with self._get_conn() as conn:
            await conn.execute(
                text("""
                    UPDATE sync_checkpoints
                    SET last_push_at = :now
                    WHERE tenant_id = :tenant_id AND store_id = :store_id
                """),
                {"now": now, "tenant_id": tenant_id, "store_id": store_id},
            )

    async def _update_checkpoint_pull(
        self, store_id: str, device_id: str, tenant_id: str, last_seq: int
    ) -> None:
        """UPSERT 同步检查点（last_pull_seq / last_pull_at）"""
        now = datetime.now(timezone.utc)
        async with self._get_conn() as conn:
            await conn.execute(
                text("""
                    INSERT INTO sync_checkpoints
                        (id, tenant_id, store_id, device_id, last_pull_seq, last_pull_at)
                    VALUES
                        (:id, :tenant_id, :store_id, :device_id, :seq, :now)
                    ON CONFLICT (tenant_id, store_id, device_id) DO UPDATE
                        SET last_pull_seq = GREATEST(sync_checkpoints.last_pull_seq, :seq),
                            last_pull_at = :now
                """),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "device_id": device_id,
                    "seq": last_seq,
                    "now": now,
                },
            )

    # ─── 连接上下文 ────────────────────────────────────────────────────────

    def _get_conn(self):
        """返回异步连接上下文管理器"""
        if not self._pool:
            raise RuntimeError("OfflineSyncService not initialized — call await init() first")
        return self._pool.begin()


# ─── 工具函数 ──────────────────────────────────────────────────────────────

def _json_dumps(obj: Any) -> str:
    """序列化为 JSON 字符串（供 PostgreSQL JSONB 类型使用）"""
    import json

    class _Enc(json.JSONEncoder):
        def default(self, o: Any) -> Any:
            if isinstance(o, datetime):
                return o.isoformat()
            if isinstance(o, uuid.UUID):
                return str(o)
            return super().default(o)

    return json.dumps(obj, cls=_Enc)
