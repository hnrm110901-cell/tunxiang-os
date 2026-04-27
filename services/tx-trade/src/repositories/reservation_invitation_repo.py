"""预订邀请/核餐外呼 Repository（Sprint R2 Track A）

SQL 实现（PgInvitationRepository）：
    基于 asyncpg.Connection，操作 v281 迁移建的 reservation_invitations 表。
    所有查询均假设 RLS 上下文已由调用方设置 app.tenant_id。

内存实现（InMemoryInvitationRepository）：
    Tier 2 测试使用。保持接口与 SQL 实现对齐，并严格按 tenant_id 隔离。

CRUD + 查询：
    - insert / get_by_id / update / list_by_reservation / list_by_customer
    - 幂等 upsert_pending（send_invitation 重试时复用 pending 记录）
"""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from typing import Any, Optional

from shared.ontology.src.extensions.reservation_invitations import (
    InvitationChannel,
    InvitationRecord,
    InvitationStatus,
)

# ──────────────────────────────────────────────────────────────────────────
# 抽象接口
# ──────────────────────────────────────────────────────────────────────────


class InvitationRepositoryBase(ABC):
    """邀请函/核餐外呼 Repository 抽象接口。"""

    @abstractmethod
    async def insert(self, record: InvitationRecord) -> InvitationRecord: ...

    @abstractmethod
    async def get_by_id(
        self, invitation_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[InvitationRecord]: ...

    @abstractmethod
    async def update(self, record: InvitationRecord) -> InvitationRecord: ...

    @abstractmethod
    async def list_by_reservation(
        self,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
    ) -> list[InvitationRecord]: ...

    @abstractmethod
    async def list_by_customer(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[InvitationRecord]: ...


# ──────────────────────────────────────────────────────────────────────────
# 内存实现
# ──────────────────────────────────────────────────────────────────────────


class InMemoryInvitationRepository(InvitationRepositoryBase):
    """内存版 Repository，严格按 tenant_id 隔离（Tier 2 单测使用）。"""

    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, InvitationRecord] = {}

    async def insert(self, record: InvitationRecord) -> InvitationRecord:
        self._rows[record.invitation_id] = record
        return record

    async def get_by_id(
        self, invitation_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[InvitationRecord]:
        row = self._rows.get(invitation_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return row

    async def update(self, record: InvitationRecord) -> InvitationRecord:
        # 越租户写入直接失败（内存层也保底）
        existing = self._rows.get(record.invitation_id)
        if existing is not None and existing.tenant_id != record.tenant_id:
            raise ValueError(
                f"tenant mismatch: invitation {record.invitation_id} belongs to "
                f"{existing.tenant_id}, not {record.tenant_id}"
            )
        self._rows[record.invitation_id] = record
        return record

    async def list_by_reservation(
        self,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
    ) -> list[InvitationRecord]:
        return [
            r
            for r in self._rows.values()
            if r.tenant_id == tenant_id and r.reservation_id == reservation_id
        ]

    async def list_by_customer(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[InvitationRecord]:
        rows = [
            r
            for r in self._rows.values()
            if r.tenant_id == tenant_id and r.customer_id == customer_id
        ]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows[:limit]


# ──────────────────────────────────────────────────────────────────────────
# SQL 实现（asyncpg）
# ──────────────────────────────────────────────────────────────────────────


_INSERT_SQL = """
INSERT INTO reservation_invitations (
    invitation_id, tenant_id, store_id, reservation_id, customer_id,
    channel, status, sent_at, confirmed_at,
    coupon_code, coupon_value_fen, failure_reason,
    payload, source_event_id, created_at, updated_at
) VALUES (
    $1, $2, $3, $4, $5,
    $6::invitation_channel_enum, $7::invitation_status_enum, $8, $9,
    $10, $11, $12,
    $13::jsonb, $14, $15, $16
)
"""

_UPDATE_SQL = """
UPDATE reservation_invitations SET
    status = $2::invitation_status_enum,
    sent_at = $3,
    confirmed_at = $4,
    coupon_code = $5,
    coupon_value_fen = $6,
    failure_reason = $7,
    payload = $8::jsonb,
    updated_at = $9
WHERE invitation_id = $1 AND tenant_id = $10
"""

_SELECT_BY_ID_SQL = """
SELECT invitation_id, tenant_id, store_id, reservation_id, customer_id,
       channel, status, sent_at, confirmed_at,
       coupon_code, coupon_value_fen, failure_reason,
       payload, source_event_id, created_at, updated_at
FROM reservation_invitations
WHERE invitation_id = $1 AND tenant_id = $2
"""


def _row_to_record(row: Any) -> InvitationRecord:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return InvitationRecord(
        invitation_id=row["invitation_id"],
        tenant_id=row["tenant_id"],
        store_id=row["store_id"],
        reservation_id=row["reservation_id"],
        customer_id=row["customer_id"],
        channel=InvitationChannel(row["channel"]),
        status=InvitationStatus(row["status"]),
        sent_at=row["sent_at"],
        confirmed_at=row["confirmed_at"],
        coupon_code=row["coupon_code"],
        coupon_value_fen=int(row["coupon_value_fen"] or 0),
        failure_reason=row["failure_reason"],
        payload=payload or {},
        source_event_id=row["source_event_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class PgInvitationRepository(InvitationRepositoryBase):
    """asyncpg 版 Repository（生产使用；调用方负责 RLS 上下文）。"""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def insert(self, record: InvitationRecord) -> InvitationRecord:
        await self._conn.execute(
            _INSERT_SQL,
            record.invitation_id,
            record.tenant_id,
            record.store_id,
            record.reservation_id,
            record.customer_id,
            record.channel.value,
            record.status.value,
            record.sent_at,
            record.confirmed_at,
            record.coupon_code,
            record.coupon_value_fen,
            record.failure_reason,
            json.dumps(record.payload or {}),
            record.source_event_id,
            record.created_at,
            record.updated_at,
        )
        return record

    async def get_by_id(
        self, invitation_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[InvitationRecord]:
        row = await self._conn.fetchrow(_SELECT_BY_ID_SQL, invitation_id, tenant_id)
        if row is None:
            return None
        return _row_to_record(row)

    async def update(self, record: InvitationRecord) -> InvitationRecord:
        await self._conn.execute(
            _UPDATE_SQL,
            record.invitation_id,
            record.status.value,
            record.sent_at,
            record.confirmed_at,
            record.coupon_code,
            record.coupon_value_fen,
            record.failure_reason,
            json.dumps(record.payload or {}),
            record.updated_at,
            record.tenant_id,
        )
        return record

    async def list_by_reservation(
        self,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
    ) -> list[InvitationRecord]:
        rows = await self._conn.fetch(
            """
            SELECT * FROM reservation_invitations
            WHERE tenant_id = $1 AND reservation_id = $2
            ORDER BY created_at DESC
            """,
            tenant_id,
            reservation_id,
        )
        return [_row_to_record(r) for r in rows]

    async def list_by_customer(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[InvitationRecord]:
        rows = await self._conn.fetch(
            """
            SELECT * FROM reservation_invitations
            WHERE tenant_id = $1 AND customer_id = $2
            ORDER BY created_at DESC
            LIMIT $3
            """,
            tenant_id,
            customer_id,
            limit,
        )
        return [_row_to_record(r) for r in rows]


__all__ = [
    "InvitationRepositoryBase",
    "InMemoryInvitationRepository",
    "PgInvitationRepository",
]
