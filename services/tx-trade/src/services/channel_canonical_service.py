"""channel_canonical_service — Sprint E1 渠道 canonical 订单 Service

职责（CLAUDE.md §10 Repository → Service 模式）：
  - ChannelCanonicalRepository  — 表层 CRUD（带 tenant_id 过滤 + RLS 绑定）
  - ChannelCanonicalService     — 业务编排（幂等校验 + 事件旁路）

设计约束（红线：不修改任何已存在文件）：
  - 不调用 cashier_engine（避免触碰 Tier 1 收银路径）
  - 旁路 emit_event(CHANNEL.ORDER_SYNCED)，写失败不影响主流程
  - 金额一律 int 分；payload 全量保存
  - SQLAlchemyError 不被吞，向上抛由路由层兜底

幂等：
  - UNIQUE (tenant_id, channel_code, external_order_id) WHERE NOT is_deleted
  - 重复 ingest 同一 external_order_id：返回既有记录，不重复发事件

事件：
  - 首次落库 → emit CHANNEL.ORDER_SYNCED（causation_id=None）
  - 重复 ingest（幂等命中）→ 不发事件
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import ChannelEventType

from ..schemas.channel_canonical import (
    CanonicalOrderRecord,
    CanonicalOrderRequest,
)

logger = structlog.get_logger(__name__)


# ─── Repository ──────────────────────────────────────────────────────────────


class ChannelCanonicalRepository:
    """channel_canonical_orders 表 CRUD（与 RLS 绑定一致）。"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self._db = db
        self._tenant_id = str(tenant_id)

    async def _bind_rls(self) -> None:
        await self._db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self._tenant_id},
        )

    async def get_by_external(
        self,
        *,
        channel_code: str,
        external_order_id: str,
    ) -> Optional[dict[str, Any]]:
        """按 (channel_code, external_order_id) 查询（用于幂等命中）。"""
        await self._bind_rls()
        row = await self._db.execute(
            text(
                """
                SELECT id, tenant_id, store_id, channel_code, external_order_id,
                       canonical_order_id, status, total_fen, subsidy_fen,
                       merchant_share_fen, commission_fen, settlement_fen,
                       payload, received_at, created_at, updated_at, is_deleted
                FROM channel_canonical_orders
                WHERE tenant_id = :tid
                  AND channel_code = :code
                  AND external_order_id = :eid
                  AND is_deleted IS NOT TRUE
                LIMIT 1
                """
            ),
            {
                "tid": self._tenant_id,
                "code": channel_code,
                "eid": external_order_id,
            },
        )
        record = row.mappings().first()
        return dict(record) if record else None

    async def insert(
        self,
        *,
        store_id: str,
        channel_code: str,
        external_order_id: str,
        status: str,
        total_fen: int,
        subsidy_fen: int,
        merchant_share_fen: int,
        commission_fen: int,
        payload: dict[str, Any],
        received_at: datetime,
    ) -> dict[str, Any]:
        """新增一行。返回完整行（含 GENERATED settlement_fen）。

        调用方需在事务内调用，commit/rollback 由路由层管理。
        """
        await self._bind_rls()
        row = await self._db.execute(
            text(
                """
                INSERT INTO channel_canonical_orders (
                    tenant_id, store_id, channel_code, external_order_id,
                    status, total_fen, subsidy_fen, merchant_share_fen,
                    commission_fen, payload, received_at
                ) VALUES (
                    :tid, :sid, :code, :eid,
                    :st, :total, :subsidy, :merch,
                    :comm, CAST(:payload AS JSONB), :recv_at
                )
                RETURNING id, tenant_id, store_id, channel_code, external_order_id,
                          canonical_order_id, status, total_fen, subsidy_fen,
                          merchant_share_fen, commission_fen, settlement_fen,
                          payload, received_at, created_at, updated_at, is_deleted
                """
            ),
            {
                "tid": self._tenant_id,
                "sid": str(store_id),
                "code": channel_code,
                "eid": external_order_id,
                "st": status,
                "total": int(total_fen),
                "subsidy": int(subsidy_fen),
                "merch": int(merchant_share_fen),
                "comm": int(commission_fen),
                "payload": json.dumps(payload, ensure_ascii=False, default=str),
                "recv_at": received_at,
            },
        )
        record = row.mappings().first()
        if record is None:
            raise SQLAlchemyError("insert returned no row")
        return dict(record)

    async def list_by_store(
        self,
        *,
        store_id: Optional[str],
        page: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页列出（按 received_at 倒序）。"""
        await self._bind_rls()
        offset = max(0, (page - 1) * size)

        if store_id:
            count_row = await self._db.execute(
                text(
                    "SELECT COUNT(*) AS n FROM channel_canonical_orders "
                    "WHERE tenant_id = :tid AND store_id = :sid "
                    "AND is_deleted IS NOT TRUE"
                ),
                {"tid": self._tenant_id, "sid": store_id},
            )
            list_row = await self._db.execute(
                text(
                    """
                    SELECT id, tenant_id, store_id, channel_code, external_order_id,
                           canonical_order_id, status, total_fen, subsidy_fen,
                           merchant_share_fen, commission_fen, settlement_fen,
                           payload, received_at, created_at, updated_at, is_deleted
                    FROM channel_canonical_orders
                    WHERE tenant_id = :tid AND store_id = :sid
                      AND is_deleted IS NOT TRUE
                    ORDER BY received_at DESC
                    LIMIT :lim OFFSET :off
                    """
                ),
                {
                    "tid": self._tenant_id,
                    "sid": store_id,
                    "lim": size,
                    "off": offset,
                },
            )
        else:
            count_row = await self._db.execute(
                text(
                    "SELECT COUNT(*) AS n FROM channel_canonical_orders "
                    "WHERE tenant_id = :tid AND is_deleted IS NOT TRUE"
                ),
                {"tid": self._tenant_id},
            )
            list_row = await self._db.execute(
                text(
                    """
                    SELECT id, tenant_id, store_id, channel_code, external_order_id,
                           canonical_order_id, status, total_fen, subsidy_fen,
                           merchant_share_fen, commission_fen, settlement_fen,
                           payload, received_at, created_at, updated_at, is_deleted
                    FROM channel_canonical_orders
                    WHERE tenant_id = :tid AND is_deleted IS NOT TRUE
                    ORDER BY received_at DESC
                    LIMIT :lim OFFSET :off
                    """
                ),
                {"tid": self._tenant_id, "lim": size, "off": offset},
            )

        total = int(count_row.scalar_one())
        items = [dict(r) for r in list_row.mappings().all()]
        return items, total

    async def get(self, *, record_id: str) -> Optional[dict[str, Any]]:
        await self._bind_rls()
        row = await self._db.execute(
            text(
                """
                SELECT id, tenant_id, store_id, channel_code, external_order_id,
                       canonical_order_id, status, total_fen, subsidy_fen,
                       merchant_share_fen, commission_fen, settlement_fen,
                       payload, received_at, created_at, updated_at, is_deleted
                FROM channel_canonical_orders
                WHERE tenant_id = :tid AND id = :id AND is_deleted IS NOT TRUE
                LIMIT 1
                """
            ),
            {"tid": self._tenant_id, "id": record_id},
        )
        record = row.mappings().first()
        return dict(record) if record else None


# ─── Service ─────────────────────────────────────────────────────────────────


class ChannelCanonicalService:
    """编排 ingest / list / get，发射 CHANNEL.ORDER_SYNCED 事件。"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = str(tenant_id)
        self._repo = ChannelCanonicalRepository(db, tenant_id)

    async def ingest(self, req: CanonicalOrderRequest) -> tuple[CanonicalOrderRecord, bool]:
        """落库一条 canonical 订单。

        Returns:
            (record, created)
            - created=True:  首次落库，已发 CHANNEL.ORDER_SYNCED 事件
            - created=False: 幂等命中，未重复发事件，返回既有记录

        Raises:
            ValueError:        amount 不一致（subsidy+commission > total 等）
            SQLAlchemyError:   DB 异常（路由层兜底转 500）
        """
        # tenant_id 三方一致性由路由层校验，本层只确认 req.tenant_id 与 service 实例一致
        if str(req.tenant_id) != self._tenant_id:
            raise ValueError(
                f"req.tenant_id {req.tenant_id} != service tenant {self._tenant_id}"
            )

        # 业务一致性
        req.assert_amount_consistency()

        # 幂等命中
        existing = await self._repo.get_by_external(
            channel_code=req.channel_code,
            external_order_id=req.external_order_id,
        )
        if existing is not None:
            logger.info(
                "canonical_order_idempotent_hit",
                tenant_id=self._tenant_id,
                channel_code=req.channel_code,
                external_order_id=req.external_order_id,
                existing_id=str(existing["id"]),
            )
            return CanonicalOrderRecord(**existing), False

        # 首次落库
        try:
            row = await self._repo.insert(
                store_id=str(req.store_id),
                channel_code=req.channel_code,
                external_order_id=req.external_order_id,
                status=req.status,
                total_fen=req.total_fen,
                subsidy_fen=req.subsidy_fen,
                merchant_share_fen=req.merchant_share_fen,
                commission_fen=req.commission_fen,
                payload=req.payload,
                received_at=req.received_at,
            )
        except SQLAlchemyError:
            logger.exception(
                "canonical_order_insert_failed",
                tenant_id=self._tenant_id,
                channel_code=req.channel_code,
                external_order_id=req.external_order_id,
            )
            raise

        record = CanonicalOrderRecord(**row)

        # 旁路事件：CHANNEL.ORDER_SYNCED（不阻塞主流程，写失败不影响）
        asyncio.create_task(  # noqa: RUF006 — fire-and-forget by design
            emit_event(
                event_type=ChannelEventType.ORDER_SYNCED,
                tenant_id=self._tenant_id,
                stream_id=str(record.id),
                payload={
                    "channel_code": req.channel_code,
                    "external_order_id": req.external_order_id,
                    "total_fen": req.total_fen,
                    "subsidy_fen": req.subsidy_fen,
                    "merchant_share_fen": req.merchant_share_fen,
                    "commission_fen": req.commission_fen,
                    "settlement_fen": record.settlement_fen,
                    "status": req.status,
                    "received_at": req.received_at.isoformat(),
                },
                store_id=str(req.store_id),
                source_service="tx-trade",
                metadata={"phase": "E1.canonical"},
            )
        )

        logger.info(
            "canonical_order_ingested",
            tenant_id=self._tenant_id,
            channel_code=req.channel_code,
            external_order_id=req.external_order_id,
            id=str(record.id),
        )
        return record, True

    async def list_recent(
        self,
        *,
        store_id: Optional[str],
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[CanonicalOrderRecord], int]:
        if size > 100:
            size = 100
        if size < 1:
            size = 20
        if page < 1:
            page = 1
        items, total = await self._repo.list_by_store(
            store_id=store_id, page=page, size=size
        )
        return [CanonicalOrderRecord(**r) for r in items], total

    async def get(self, record_id: UUID | str) -> Optional[CanonicalOrderRecord]:
        row = await self._repo.get(record_id=str(record_id))
        return CanonicalOrderRecord(**row) if row else None


# ─── 工具：解析 received_at（FastAPI 反序列化兜底）───────────────────────────


def parse_received_at(value: str | datetime) -> datetime:
    """将字符串/datetime 统一为 timezone-aware UTC datetime。

    路由侧若 Pydantic 已解析为 datetime 则直接返回；
    保留为字符串入口以便测试桩使用。
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return datetime.fromisoformat(value).astimezone(timezone.utc)
