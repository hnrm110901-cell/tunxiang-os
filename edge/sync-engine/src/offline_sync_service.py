"""offline_sync_service.py — 离线收银同步服务

职责：
  - 断网时将订单快照存入 offline_order_queue（本地 PG）
  - 网络恢复后批量推送离线订单到云端
  - 拉取云端最新数据（菜单/会员/配置）
  - 冲突解决：字段级 LWW-Register（W12-3 接线）+ 金额字段保留 server_wins（PN-Counter 语义）
  - 查询同步状态（pending_count / last_sync_at / is_connected）
  - 增量同步 watermark 升级为 SyncToken（双键 ts+seq，崩溃恢复可续跑，v393 持久化）

设计约束：
  - 所有金额以分（fen）整型存储
  - 异步运行，不阻塞收银业务
  - LWW-Register 字段（status/桌号/会员绑定/备注等）由 lww_register.resolve_lww 决策
  - 累加金额（PN-Counter）保持 server_wins，避免 LWW 错误覆盖累加结果
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog

# W12-3 LWW-Register 接线（lww_register.py 已 23 测试全绿）
from lww_register import LWWValue, SyncToken, resolve_lww
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = structlog.get_logger()


# ─── 字段级冲突策略表 ──────────────────────────────────────────────────────
# 决策规则：
#   - LWW_FIELDS（状态类标量）：调 resolve_lww 字段级决策
#   - MONETARY_FIELDS（PN-Counter 语义）：server_wins，绝不允许 LWW 覆盖累加值
#   - LIST_FIELDS（顺序敏感列表）：server_wins，pragmatic（应使用 RGA/Logoot，暂不实现）
#   - 其它未列字段：默认 server_wins（保守兜底）

# LWW 字段：末次写入即真相的状态/标量字段
LWW_FIELDS: frozenset[str] = frozenset(
    {
        "status",  # 订单状态（open/paid/cancelled/refunded）
        "table_no",  # 桌号
        "table_id",  # 桌台 ID
        "customer_id",  # 顾客绑定
        "member_id",  # 会员绑定
        "notes",  # 备注
        "remark",  # 备注（兼容字段名）
        "operator_id",  # 经手人
        "channel",  # 渠道
    }
)

# 金额字段：PN-Counter 语义，禁止走 LWW，必须服务端为准
MONETARY_FIELDS: frozenset[str] = frozenset(
    {
        "total_amount_fen",
        "subtotal_fen",
        "discount_fen",
        "tax_fen",
        "tip_fen",
        "paid_fen",
        "refund_fen",
        "service_fee_fen",
        "delivery_fee_fen",
        "balance_fen",
    }
)

# 顺序敏感列表：暂走 server_wins（应使用 RGA/Logoot，未来扩展）
LIST_FIELDS: frozenset[str] = frozenset(
    {
        "items_data",
        "items",
        "payments_data",
        "payments",
    }
)

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
    """冲突解决结果

    resolution 取值：
      - "lww_field_merge"   字段级 LWW 合并（W12-3 接线后默认策略）
      - "server_wins"       仅服务端胜（无本地 payload 或纯金额冲突时回退）
      - "local_backup"      仅作为审计备份（不再使用，保留兼容）
    """

    local_order_id: str
    server_order_id: Optional[str]
    resolution: str
    conflict_reason: str
    # W12-3 接线后新增：字段级决策明细，用于审计
    field_decisions: dict[str, str] = field(default_factory=dict)
    # 合并后的最终值（仅 LWW 字段；金额字段以 server 为准不在此体现）
    merged_payload: dict[str, Any] = field(default_factory=dict)


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
                            local_payload=row.get("order_data"),
                            server_payload=push_result.get("server_payload"),
                            local_node_id=row.get("local_node_id") or self._tenant_id or "edge",
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
        since_seq: int | None = None,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """拉取服务端最新数据（菜单变更、会员信息、配置等）

        W12-3 升级：watermark 从单一 since_seq 升级为 SyncToken（双键 ts+seq），
        从 sync_checkpoints.last_pull_token 持久化加载，崩溃恢复后续跑。
        since_seq 仍保留作为初始化兼容入参（None 时从持久化 token 读取）。

        GET /api/v1/sync/pull?store_id=...&since_ts=...&since_seq=...

        Args:
            store_id:   门店 ID
            device_id:  设备 ID（用于更新 sync_checkpoints）
            since_seq:  兼容入参（None 时从持久化 token 读取）
            tenant_id:  租户 ID

        Returns:
            变更记录列表（已经按 SyncToken.filter_unseen 过滤过，仅返回 token 之后的事件）
        """
        tid = tenant_id or self._tenant_id
        if not tid:
            raise ValueError("tenant_id is required for pull")

        if not self._cloud_api_url:
            logger.warning("offline_sync_service.pull_skipped", reason="CLOUD_API_URL not set")
            return []

        # 加载持久化 SyncToken（崩溃恢复入口）
        token = await self.load_sync_token(store_id, device_id, tid)
        if since_seq is not None and since_seq > token.last_seen_seq:
            # 显式 since_seq 比持久化 token 更新（罕见场景：手动重置）
            token = SyncToken(last_seen_ts=token.last_seen_ts, last_seen_seq=since_seq)

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.get(
                    f"{self._cloud_api_url}/api/v1/sync/pull",
                    params={
                        "store_id": store_id,
                        "since_seq": token.last_seen_seq,
                        "since_ts": token.last_seen_ts.isoformat(),
                    },
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

            # SyncToken 过滤（双保险：服务端可能返回边界事件，本地按 token 严格过滤）
            unseen = token.filter_unseen(items) if items else items

            # 推进并持久化 token（即便 unseen 为空，server 端可能确认了 token）
            if unseen:
                new_token = token.advance(unseen)
                await self.save_sync_token(store_id, device_id, tid, new_token)

            logger.info(
                "offline_sync_service.pull_done",
                store_id=store_id,
                device_id=device_id,
                since_token=token.to_string(),
                received=len(items),
                unseen=len(unseen),
            )
            return unseen

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

    async def load_sync_token(self, store_id: str, device_id: str, tenant_id: str) -> SyncToken:
        """从 sync_checkpoints 持久化恢复 SyncToken（崩溃恢复入口，W12-3 接线）

        优先级：
          1. last_pull_token（v393 新列，权威序列化形式）
          2. last_pull_token_ts + last_pull_seq（v393 新列，显式拆分形式）
          3. last_pull_seq + last_pull_at（v036 老列，向后兼容）
          4. SyncToken.initial()（首次拉取）
        """
        async with self._get_conn() as conn:
            result = await conn.execute(
                text("""
                    SELECT last_pull_token, last_pull_token_ts,
                           last_pull_seq, last_pull_at
                    FROM sync_checkpoints
                    WHERE tenant_id = :tenant_id
                      AND store_id = :store_id
                      AND device_id = :device_id
                """),
                {"tenant_id": tenant_id, "store_id": store_id, "device_id": device_id},
            )
            row = result.one_or_none()

        if not row:
            return SyncToken.initial()

        keys = ["last_pull_token", "last_pull_token_ts", "last_pull_seq", "last_pull_at"]
        d = dict(zip(keys, row))

        token_str = d.get("last_pull_token")
        if token_str:
            return SyncToken.from_string(token_str)

        token_ts = d.get("last_pull_token_ts") or d.get("last_pull_at")
        token_seq = int(d.get("last_pull_seq") or 0)
        if token_ts is not None:
            ts = token_ts
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return SyncToken(last_seen_ts=ts, last_seen_seq=token_seq)

        return SyncToken.initial()

    async def save_sync_token(
        self,
        store_id: str,
        device_id: str,
        tenant_id: str,
        token: SyncToken,
    ) -> None:
        """持久化 SyncToken 到 sync_checkpoints（v393 新列）

        UPSERT，并应用 GREATEST 防止并发回退。
        """
        now = datetime.now(timezone.utc)
        async with self._get_conn() as conn:
            await conn.execute(
                text("""
                    INSERT INTO sync_checkpoints
                        (id, tenant_id, store_id, device_id,
                         last_pull_seq, last_pull_at,
                         last_pull_token, last_pull_token_ts)
                    VALUES
                        (:id, :tenant_id, :store_id, :device_id,
                         :seq, :now,
                         :token_str, :token_ts)
                    ON CONFLICT (tenant_id, store_id, device_id) DO UPDATE
                        SET last_pull_seq = GREATEST(sync_checkpoints.last_pull_seq, :seq),
                            last_pull_at = :now,
                            last_pull_token = :token_str,
                            last_pull_token_ts = GREATEST(
                                COALESCE(sync_checkpoints.last_pull_token_ts, :token_ts),
                                :token_ts
                            )
                """),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "device_id": device_id,
                    "seq": token.last_seen_seq,
                    "now": now,
                    "token_str": token.to_string(),
                    "token_ts": token.last_seen_ts,
                },
            )

    async def resolve_conflict(
        self,
        local_order_id: str,
        server_order_id: Optional[str],
        conflict_reason: str = "server conflict",
        queue_row_id: str | None = None,
        local_payload: dict[str, Any] | None = None,
        server_payload: dict[str, Any] | None = None,
        local_node_id: str = "edge",
        server_node_id: str = "cloud",
    ) -> ConflictResolution:
        """冲突解决：字段级 LWW-Register（W12-3 接线）+ 金额字段 server_wins

        策略矩阵（详见模块顶部 LWW_FIELDS / MONETARY_FIELDS / LIST_FIELDS）：
          - LWW_FIELDS（status/桌号/会员绑定/备注等标量）→ resolve_lww 按 (ts, node_id)
            选最新写入；本地胜出则将合并值写回 offline_order_queue.order_data。
          - MONETARY_FIELDS（*_fen 金额字段）→ 强制 server_wins（PN-Counter 语义，
            LWW 会丢失累加，详见 lww_register.py 注释）。
          - LIST_FIELDS（items/payments）→ server_wins（顺序敏感，应使用 RGA/Logoot）。
          - 缺失 local_payload 或 server_payload → 整体回退 server_wins（向后兼容）。

        本地记录始终标记为 'conflict' 状态（无论字段级胜负），保留原始离线快照
        作为审计备份；如果 LWW 决策出本地新字段值，将其追加到 order_data 的
        merged_local_lww 子对象中（不覆盖原始字段，便于回溯）。

        Args:
            local_order_id:   本地临时订单 ID
            server_order_id:  服务端实际订单 ID（可为 None）
            conflict_reason:  冲突说明
            queue_row_id:     offline_order_queue 行 ID（可选，加速查找）
            local_payload:    本地订单 order_data（含 _ts/_node_id 元信息）
            server_payload:   服务端返回的最新订单 payload（含字段级时间戳）
            local_node_id:    本地节点标识（默认 'edge'，可由 POS device_id 覆盖）
            server_node_id:   服务端节点标识（默认 'cloud'）

        Returns:
            ConflictResolution（含 field_decisions 字段级决策明细 + merged_payload）
        """
        now = datetime.now(timezone.utc)
        field_decisions: dict[str, str] = {}
        merged_payload: dict[str, Any] = {}
        resolution_strategy = "server_wins"

        # 字段级 LWW 决策（仅当 local + server payload 都存在时执行）
        if local_payload is not None and server_payload is not None:
            resolution_strategy = "lww_field_merge"
            local_ts = _extract_ts(local_payload, fallback=now)
            server_ts = _extract_ts(server_payload, fallback=now)

            # 收集双方所有出现过的字段（避免漏掉单边新增字段）
            all_fields: set[str] = set(local_payload.keys()) | set(server_payload.keys())
            for fname in all_fields:
                if fname.startswith("_"):
                    # 元字段（_ts/_node_id 等）跳过决策
                    continue
                local_v = local_payload.get(fname)
                server_v = server_payload.get(fname)

                if fname in MONETARY_FIELDS:
                    # PN-Counter 语义：金额字段强制服务端胜
                    field_decisions[fname] = "server_wins_monetary"
                    if server_v is not None:
                        merged_payload[fname] = server_v
                elif fname in LIST_FIELDS:
                    # 顺序敏感列表：服务端胜（应使用 RGA/Logoot，暂未实现）
                    field_decisions[fname] = "server_wins_list"
                    if server_v is not None:
                        merged_payload[fname] = server_v
                elif fname in LWW_FIELDS:
                    # LWW-Register 决策
                    if local_v is None:
                        field_decisions[fname] = "server_wins_local_missing"
                        merged_payload[fname] = server_v
                    elif server_v is None:
                        field_decisions[fname] = "local_wins_server_missing"
                        merged_payload[fname] = local_v
                    else:
                        local_lww = LWWValue(value=local_v, timestamp=local_ts, node_id=local_node_id)
                        server_lww = LWWValue(value=server_v, timestamp=server_ts, node_id=server_node_id)
                        winner = resolve_lww(local_lww, server_lww)
                        if winner.node_id == local_node_id and winner.value == local_v:
                            field_decisions[fname] = "local_wins_lww"
                        else:
                            field_decisions[fname] = "server_wins_lww"
                        merged_payload[fname] = winner.value
                else:
                    # 未列入策略表的字段 → 默认 server_wins（保守兜底）
                    field_decisions[fname] = "server_wins_default"
                    if server_v is not None:
                        merged_payload[fname] = server_v

            conflict_reason = (
                f"{conflict_reason} | strategy=lww_field_merge "
                f"local_wins={sum(1 for v in field_decisions.values() if v.startswith('local_wins'))} "
                f"server_wins={sum(1 for v in field_decisions.values() if v.startswith('server_wins'))}"
            )
        else:
            # 缺失任一 payload → 完全回退 server_wins
            conflict_reason = f"{conflict_reason} | strategy=server_wins (payload missing)"

        where_clause = "local_order_id = :local_order_id"
        params: dict[str, Any] = {
            "local_order_id": local_order_id,
            "conflict_reason": conflict_reason[:500],
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

            # 如有 LWW 合并结果，把决策明细回写到 order_data._lww_resolution 子对象（审计用）
            if resolution_strategy == "lww_field_merge" and merged_payload:
                await conn.execute(
                    text(f"""
                        UPDATE offline_order_queue
                        SET order_data = order_data || :patch::jsonb
                        WHERE {where_clause}
                    """),
                    {
                        **{k: v for k, v in params.items() if k != "conflict_reason"},
                        "patch": _json_dumps(
                            {
                                "_lww_resolution": {
                                    "merged_payload": merged_payload,
                                    "field_decisions": field_decisions,
                                    "server_order_id": server_order_id,
                                    "resolved_at": now.isoformat(),
                                },
                            }
                        ),
                    },
                )

        resolution = ConflictResolution(
            local_order_id=local_order_id,
            server_order_id=server_order_id,
            resolution=resolution_strategy,
            conflict_reason=conflict_reason,
            field_decisions=field_decisions,
            merged_payload=merged_payload,
        )

        logger.warning(
            "offline_sync_service.conflict_resolved",
            local_order_id=local_order_id,
            server_order_id=server_order_id,
            reason=conflict_reason,
            resolution=resolution_strategy,
            field_decisions=field_decisions,
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

    async def _fetch_pending_rows(self, store_id: str, tenant_id: str, limit: int, offset: int) -> list[dict[str, Any]]:
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

    async def _push_single_order(self, row: dict[str, Any], tenant_id: str) -> dict[str, Any]:
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
            data = body.get("data", {}) or {}
            return {
                "status": "conflict",
                "server_order_id": data.get("server_order_id"),
                "reason": data.get("reason", "duplicate order"),
                # W12-3 接线：服务端返回最新订单 payload，供字段级 LWW 决策
                "server_payload": data.get("server_payload") or data.get("order_data"),
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

    async def _get_checkpoint(self, store_id: str, device_id: str, tenant_id: str) -> dict[str, Any]:
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

    async def _update_checkpoint_pull(self, store_id: str, device_id: str, tenant_id: str, last_seq: int) -> None:
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


def _extract_ts(payload: dict[str, Any], fallback: datetime) -> datetime:
    """从 payload 中提取 LWW 用的时间戳

    优先级：
      1. payload['_ts']           — 显式 LWW 时间戳元字段
      2. payload['updated_at']    — 业务字段
      3. payload['client_ts']     — 离线事件时间戳
      4. payload['created_at']    — 兜底
      5. fallback                 — 全部缺失时使用调用方提供的兜底（通常是 now()）

    时间戳必须带 tzinfo（UTC）；字符串自动解析。
    """
    for key in ("_ts", "updated_at", "client_ts", "created_at"):
        v = payload.get(key)
        if v is None:
            continue
        if isinstance(v, datetime):
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            return v
        if isinstance(v, str):
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    return fallback
