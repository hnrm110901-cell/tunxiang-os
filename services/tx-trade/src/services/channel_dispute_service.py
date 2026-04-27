"""channel_dispute_service — Sprint E4 异议工作流 Service

职责：
  - open_dispute(req, threshold_fen)
      - 若 dispute_type ∈ NON_AUTO_ACCEPT_TYPES → state=pending（强制人工）
      - 若 claimed_amount_fen ≤ threshold_fen → state=auto_accepted
        + decision_reason="auto_accept under threshold (claim={claim} <= threshold={th})"
        + 旁路 CHANNEL.DISPUTE_AUTO_ACCEPTED
      - 否则 state=pending
      - 全部场景旁路 CHANNEL.DISPUTE_OPENED
  - resolve_dispute(id, decision, reason, operator_id)
      - 仅 pending / manual_reviewing 可被裁决，其他状态 → 409 ALREADY_RESOLVED
      - 写入 decision_by / decision_at / decision_reason
      - 旁路 CHANNEL.DISPUTE_RESOLVED
  - list_pending() / get()

设计（CLAUDE.md §13/§15）：
  - tenant_id 必填，service 实例与 req.tenant_id 一致性自校验
  - SQLAlchemyError 不吞，向上抛
  - 金额一律 int 分；threshold 默认值由 schemas.channel_dispute 提供，
    最终由路由/上游 tenant_setting 覆盖（决策点 #5）

幂等：
  - UNIQUE (tenant_id, channel_code, external_dispute_id) WHERE NOT is_deleted
  - 重复 open 同一 external_dispute_id：返回既有记录，不重复发事件
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import ChannelEventType

from ..schemas.channel_dispute import (
    DEFAULT_AUTO_ACCEPT_THRESHOLD_FEN,
    NON_AUTO_ACCEPT_TYPES,
    DisputeRecord,
    OpenDisputeRequest,
)

logger = structlog.get_logger(__name__)


_RESOLVABLE_STATES = ("pending", "manual_reviewing")


class DisputeAlreadyResolvedError(Exception):
    """409 — 试图裁决已结案的异议。"""


class DisputeNotFoundError(Exception):
    """404 — id 不存在或不属于当前租户。"""


# ─── Repository ──────────────────────────────────────────────────────────────


class ChannelDisputeRepository:
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
        external_dispute_id: str,
    ) -> Optional[dict[str, Any]]:
        await self._bind_rls()
        row = await self._db.execute(
            text(
                """
                SELECT * FROM channel_disputes
                WHERE tenant_id = :tid
                  AND channel_code = :code
                  AND external_dispute_id = :eid
                  AND is_deleted IS NOT TRUE
                LIMIT 1
                """
            ),
            {
                "tid": self._tenant_id,
                "code": channel_code,
                "eid": external_dispute_id,
            },
        )
        record = row.mappings().first()
        return dict(record) if record else None

    async def get(self, *, dispute_id: str) -> Optional[dict[str, Any]]:
        await self._bind_rls()
        row = await self._db.execute(
            text(
                """
                SELECT * FROM channel_disputes
                WHERE tenant_id = :tid AND id = :id AND is_deleted IS NOT TRUE
                LIMIT 1
                """
            ),
            {"tid": self._tenant_id, "id": dispute_id},
        )
        record = row.mappings().first()
        return dict(record) if record else None

    async def insert(
        self,
        *,
        store_id: str,
        canonical_order_id: str,
        channel_code: str,
        external_dispute_id: str,
        dispute_type: str,
        claimed_amount_fen: int,
        state: str,
        auto_accept_threshold_fen: Optional[int],
        decision_reason: Optional[str],
        decision_by: Optional[str],
        decision_at: Optional[datetime],
        payload: dict[str, Any],
        opened_at: datetime,
    ) -> dict[str, Any]:
        await self._bind_rls()
        row = await self._db.execute(
            text(
                """
                INSERT INTO channel_disputes (
                    tenant_id, store_id, canonical_order_id, channel_code,
                    external_dispute_id, dispute_type, claimed_amount_fen,
                    state, auto_accept_threshold_fen, decision_reason,
                    decision_by, decision_at, payload, opened_at
                ) VALUES (
                    :tid, :sid, :coid, :code,
                    :eid, :dtype, :claim,
                    :st, :th, :reason,
                    :dby, :dat, CAST(:payload AS JSONB), :opened
                )
                RETURNING *
                """
            ),
            {
                "tid": self._tenant_id,
                "sid": store_id,
                "coid": canonical_order_id,
                "code": channel_code,
                "eid": external_dispute_id,
                "dtype": dispute_type,
                "claim": int(claimed_amount_fen),
                "st": state,
                "th": auto_accept_threshold_fen,
                "reason": decision_reason,
                "dby": decision_by,
                "dat": decision_at,
                "payload": json.dumps(payload, ensure_ascii=False, default=str),
                "opened": opened_at,
            },
        )
        record = row.mappings().first()
        if record is None:
            raise SQLAlchemyError("insert returned no row")
        return dict(record)

    async def resolve(
        self,
        *,
        dispute_id: str,
        new_state: str,
        decision_reason: str,
        decision_by: str,
        decision_at: datetime,
    ) -> dict[str, Any]:
        """有条件 UPDATE：仅 pending / manual_reviewing 才允许写入裁决。

        Returns 更新后的完整行。如果原状态不可裁决，UPDATE 命中 0 行 → 调用方判断。
        """
        await self._bind_rls()
        stmt = text(
            """
            UPDATE channel_disputes
               SET state = :st,
                   decision_reason = :reason,
                   decision_by = :dby,
                   decision_at = :dat,
                   updated_at = NOW()
             WHERE tenant_id = :tid
               AND id = :id
               AND state IN :resolvable
               AND is_deleted IS NOT TRUE
            RETURNING *
            """  # noqa: S608
        ).bindparams(bindparam("resolvable", expanding=True))
        row = await self._db.execute(
            stmt,
            {
                "tid": self._tenant_id,
                "id": dispute_id,
                "st": new_state,
                "reason": decision_reason,
                "dby": decision_by,
                "dat": decision_at,
                "resolvable": list(_RESOLVABLE_STATES),
            },
        )
        record = row.mappings().first()
        return dict(record) if record else None

    async def list_pending(
        self,
        *,
        store_id: Optional[str],
        states: Optional[list[str]],
        page: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        await self._bind_rls()
        offset = max(0, (page - 1) * size)

        clauses = ["tenant_id = :tid", "is_deleted IS NOT TRUE"]
        params: dict[str, Any] = {"tid": self._tenant_id, "lim": size, "off": offset}
        if store_id:
            clauses.append("store_id = :sid")
            params["sid"] = store_id
        if states:
            clauses.append("state IN :states")
            params["states"] = list(states)

        where_sql = " AND ".join(clauses)

        count_stmt = text(
            f"SELECT COUNT(*) AS n FROM channel_disputes WHERE {where_sql}"  # noqa: S608
        )
        list_stmt = text(
            f"""
            SELECT * FROM channel_disputes
             WHERE {where_sql}
             ORDER BY opened_at DESC
             LIMIT :lim OFFSET :off
            """  # noqa: S608
        )
        if states:
            count_stmt = count_stmt.bindparams(bindparam("states", expanding=True))
            list_stmt = list_stmt.bindparams(bindparam("states", expanding=True))

        count_row = await self._db.execute(count_stmt, params)
        list_row = await self._db.execute(list_stmt, params)
        total = int(count_row.scalar_one())
        items = [dict(r) for r in list_row.mappings().all()]
        return items, total


# ─── Service ─────────────────────────────────────────────────────────────────


class ChannelDisputeService:
    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = str(tenant_id)
        self._repo = ChannelDisputeRepository(db, tenant_id)

    async def open_dispute(
        self,
        req: OpenDisputeRequest,
        *,
        auto_accept_threshold_fen: int = DEFAULT_AUTO_ACCEPT_THRESHOLD_FEN,
    ) -> tuple[DisputeRecord, bool]:
        """打开异议。返回 (record, created)。

        Raises:
            ValueError:    tenant 不一致
            SQLAlchemyError: DB 异常
        """
        if str(req.tenant_id) != self._tenant_id:
            raise ValueError(
                f"req.tenant_id {req.tenant_id} != service tenant {self._tenant_id}"
            )

        # 幂等命中
        existing = await self._repo.get_by_external(
            channel_code=req.channel_code,
            external_dispute_id=req.external_dispute_id,
        )
        if existing is not None:
            logger.info(
                "channel_dispute_idempotent_hit",
                tenant_id=self._tenant_id,
                channel_code=req.channel_code,
                external_dispute_id=req.external_dispute_id,
                existing_id=str(existing["id"]),
            )
            return DisputeRecord(**existing), False

        # 决定初始状态（决策点 #5）
        is_auto_acceptable = (
            req.dispute_type not in NON_AUTO_ACCEPT_TYPES
            and req.claimed_amount_fen <= auto_accept_threshold_fen
        )
        initial_state = "auto_accepted" if is_auto_acceptable else "pending"

        decision_reason: Optional[str] = None
        decision_at: Optional[datetime] = None
        if is_auto_acceptable:
            decision_reason = (
                f"auto_accept under threshold (claim={req.claimed_amount_fen}"
                f" <= threshold={auto_accept_threshold_fen})"
            )
            decision_at = datetime.now(timezone.utc)

        try:
            row = await self._repo.insert(
                store_id=str(req.store_id),
                canonical_order_id=str(req.canonical_order_id),
                channel_code=req.channel_code,
                external_dispute_id=req.external_dispute_id,
                dispute_type=req.dispute_type,
                claimed_amount_fen=req.claimed_amount_fen,
                state=initial_state,
                auto_accept_threshold_fen=auto_accept_threshold_fen,
                decision_reason=decision_reason,
                decision_by=None,  # auto_accept 没有人工操作员
                decision_at=decision_at,
                payload=req.payload,
                opened_at=req.opened_at,
            )
        except SQLAlchemyError:
            logger.exception(
                "channel_dispute_insert_failed",
                tenant_id=self._tenant_id,
                external_dispute_id=req.external_dispute_id,
            )
            raise

        record = DisputeRecord(**row)

        # 旁路事件：DISPUTE_OPENED 总是发；auto_accepted 额外发 AUTO_ACCEPTED
        common_payload = {
            "channel_code": req.channel_code,
            "external_dispute_id": req.external_dispute_id,
            "dispute_type": req.dispute_type,
            "claimed_amount_fen": req.claimed_amount_fen,
            "auto_accept_threshold_fen": auto_accept_threshold_fen,
            "state": initial_state,
            "canonical_order_id": str(req.canonical_order_id),
        }
        asyncio.create_task(  # noqa: RUF006
            emit_event(
                event_type=ChannelEventType.DISPUTE_OPENED,
                tenant_id=self._tenant_id,
                stream_id=str(record.id),
                payload=common_payload,
                store_id=str(req.store_id),
                source_service="tx-trade",
                metadata={"phase": "E4.dispute_open"},
            )
        )
        if is_auto_acceptable:
            asyncio.create_task(  # noqa: RUF006
                emit_event(
                    event_type=ChannelEventType.DISPUTE_AUTO_ACCEPTED,
                    tenant_id=self._tenant_id,
                    stream_id=str(record.id),
                    payload={**common_payload, "decision_reason": decision_reason},
                    store_id=str(req.store_id),
                    source_service="tx-trade",
                    metadata={"phase": "E4.dispute_auto_accept"},
                )
            )

        logger.info(
            "channel_dispute_opened",
            tenant_id=self._tenant_id,
            external_dispute_id=req.external_dispute_id,
            id=str(record.id),
            state=initial_state,
        )
        return record, True

    async def resolve_dispute(
        self,
        *,
        dispute_id: UUID | str,
        decision: str,
        reason: str,
        operator_id: str,
    ) -> DisputeRecord:
        """裁决异议。

        Raises:
            DisputeNotFoundError:        id 不存在或已软删
            DisputeAlreadyResolvedError: 状态已为终态（accepted/rejected/auto_accepted/escalated）
            ValueError:                  decision 非法
            SQLAlchemyError:             DB 异常
        """
        if decision not in ("accepted", "rejected", "escalated"):
            raise ValueError(f"invalid decision: {decision}")

        # 先取，看存在与否 + 当前状态
        existing = await self._repo.get(dispute_id=str(dispute_id))
        if existing is None:
            raise DisputeNotFoundError(str(dispute_id))
        if existing["state"] not in _RESOLVABLE_STATES:
            raise DisputeAlreadyResolvedError(
                f"dispute {dispute_id} state={existing['state']} not resolvable"
            )

        try:
            row = await self._repo.resolve(
                dispute_id=str(dispute_id),
                new_state=decision,
                decision_reason=reason,
                decision_by=operator_id,
                decision_at=datetime.now(timezone.utc),
            )
        except SQLAlchemyError:
            logger.exception(
                "channel_dispute_resolve_failed",
                tenant_id=self._tenant_id,
                id=str(dispute_id),
            )
            raise

        if row is None:
            # 并发：刚刚还能裁决，UPDATE 时被别人抢先
            raise DisputeAlreadyResolvedError(
                f"dispute {dispute_id} concurrently resolved"
            )

        record = DisputeRecord(**row)
        asyncio.create_task(  # noqa: RUF006
            emit_event(
                event_type=ChannelEventType.DISPUTE_RESOLVED,
                tenant_id=self._tenant_id,
                stream_id=str(record.id),
                payload={
                    "channel_code": record.channel_code,
                    "external_dispute_id": record.external_dispute_id,
                    "dispute_type": record.dispute_type,
                    "claimed_amount_fen": record.claimed_amount_fen,
                    "decision": decision,
                    "decision_reason": reason,
                    "decision_by": operator_id,
                    "canonical_order_id": str(record.canonical_order_id),
                },
                store_id=str(record.store_id),
                source_service="tx-trade",
                metadata={"phase": "E4.dispute_resolve"},
            )
        )

        logger.info(
            "channel_dispute_resolved",
            tenant_id=self._tenant_id,
            id=str(record.id),
            decision=decision,
            operator_id=operator_id,
        )
        return record

    async def list_pending(
        self,
        *,
        store_id: Optional[str] = None,
        states: Optional[list[str]] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[DisputeRecord], int]:
        if size > 100:
            size = 100
        if size < 1:
            size = 20
        if page < 1:
            page = 1
        items, total = await self._repo.list_pending(
            store_id=store_id, states=states, page=page, size=size
        )
        return [DisputeRecord(**r) for r in items], total

    async def get(self, dispute_id: UUID | str) -> Optional[DisputeRecord]:
        row = await self._repo.get(dispute_id=str(dispute_id))
        return DisputeRecord(**row) if row else None
