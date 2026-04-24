"""宴会合同 Repository — 数据访问层（InMemory + Pg 双实现）

Track R2-C / Sprint R2 新增。

涉及三表（v282 迁移）：
    - banquet_contracts
    - banquet_eo_tickets
    - banquet_approval_logs

InMemory 实现用于 Tier 2 单元测试；Pg 实现通过 asyncpg 连接直写，依赖
`app.tenant_id` 由上层 session 设定（RLS 隔离）。
"""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from typing import Any, Optional

from shared.ontology.src.extensions.banquet_contracts import (
    ApprovalAction,
    ApprovalRole,
    BanquetApprovalLog,
    BanquetContract,
    BanquetEOTicket,
    ContractStatus,
    EODepartment,
    EOTicketStatus,
)
from shared.ontology.src.extensions.banquet_leads import BanquetType


class _UniqueViolationSim(Exception):
    """InMemory Repo 模拟 asyncpg.UniqueViolationError。

    命名含 `UniqueViolation` 子串，使 service 层 `_is_unique_violation`
    能软探测识别（与 asyncpg / psycopg2 保持一致的识别逻辑）。
    """

    sqlstate = "23505"

# ──────────────────────────────────────────────────────────────────────────
# 抽象接口
# ──────────────────────────────────────────────────────────────────────────


class BanquetContractRepositoryBase(ABC):
    """宴会合同 Repository 抽象接口（合同 / EO 工单 / 审批日志三表）。"""

    # ── 合同主表 ─────────────────────────────────────────────────────
    @abstractmethod
    async def insert_contract(self, contract: BanquetContract) -> BanquetContract: ...

    @abstractmethod
    async def get_contract(
        self, contract_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[BanquetContract]: ...

    @abstractmethod
    async def update_contract(self, contract: BanquetContract) -> BanquetContract: ...

    @abstractmethod
    async def list_contracts_by_lead(
        self, lead_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> list[BanquetContract]: ...

    @abstractmethod
    async def list_contracts(
        self,
        tenant_id: uuid.UUID,
        *,
        lead_id: Optional[uuid.UUID] = None,
        status: Optional[ContractStatus] = None,
        scheduled_date: Optional[date] = None,
        store_id: Optional[uuid.UUID] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BanquetContract], int]: ...

    # ── EO 工单 ─────────────────────────────────────────────────────
    @abstractmethod
    async def insert_eo_tickets(
        self, tickets: list[BanquetEOTicket]
    ) -> list[BanquetEOTicket]: ...

    @abstractmethod
    async def get_eo_ticket(
        self, eo_ticket_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[BanquetEOTicket]: ...

    @abstractmethod
    async def update_eo_ticket(
        self, ticket: BanquetEOTicket
    ) -> BanquetEOTicket: ...

    @abstractmethod
    async def list_eo_tickets_by_contract(
        self, contract_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> list[BanquetEOTicket]: ...

    # ── 审批日志 ────────────────────────────────────────────────────
    @abstractmethod
    async def insert_approval_log(
        self, log: BanquetApprovalLog
    ) -> BanquetApprovalLog: ...

    @abstractmethod
    async def list_approval_logs(
        self, contract_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> list[BanquetApprovalLog]: ...


# ──────────────────────────────────────────────────────────────────────────
# 内存实现（Tier 2 单元测试使用）
# ──────────────────────────────────────────────────────────────────────────


class InMemoryBanquetContractRepository(BanquetContractRepositoryBase):
    """内存版 Repository，按 tenant_id 严格隔离。"""

    def __init__(self) -> None:
        self._contracts: dict[uuid.UUID, BanquetContract] = {}
        self._eo_tickets: dict[uuid.UUID, BanquetEOTicket] = {}
        self._approval_logs: dict[uuid.UUID, BanquetApprovalLog] = {}

    # ── 合同主表 ─────────────────────────────────────────────────────
    async def insert_contract(self, contract: BanquetContract) -> BanquetContract:
        self._contracts[contract.contract_id] = contract
        return contract

    async def get_contract(
        self, contract_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[BanquetContract]:
        row = self._contracts.get(contract_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return row

    async def update_contract(
        self, contract: BanquetContract
    ) -> BanquetContract:
        # C-2 修复：模拟 v283 部分 UNIQUE 索引
        #   (tenant_id, store_id, scheduled_date) WHERE status='signed'
        # 同 (tenant, store, date) 只能有一张 signed 合同。并发场景下
        # 第二方在此处抛 _UniqueViolationSim → 上层 mark_signed 转抛
        # ScheduleAlreadyLockedError。
        if (
            contract.status == ContractStatus.SIGNED
            and contract.store_id is not None
            and contract.scheduled_date is not None
        ):
            for existing in self._contracts.values():
                if existing.contract_id == contract.contract_id:
                    continue
                if (
                    existing.tenant_id == contract.tenant_id
                    and existing.store_id == contract.store_id
                    and existing.scheduled_date == contract.scheduled_date
                    and existing.status == ContractStatus.SIGNED
                ):
                    raise _UniqueViolationSim(
                        f"schedule lock violated for "
                        f"(tenant={contract.tenant_id},store={contract.store_id},"
                        f"date={contract.scheduled_date})"
                    )
        self._contracts[contract.contract_id] = contract
        return contract

    async def list_contracts_by_lead(
        self, lead_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> list[BanquetContract]:
        return [
            c
            for c in self._contracts.values()
            if c.tenant_id == tenant_id and c.lead_id == lead_id
        ]

    async def list_contracts(
        self,
        tenant_id: uuid.UUID,
        *,
        lead_id: Optional[uuid.UUID] = None,
        status: Optional[ContractStatus] = None,
        scheduled_date: Optional[date] = None,
        store_id: Optional[uuid.UUID] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BanquetContract], int]:
        rows = [c for c in self._contracts.values() if c.tenant_id == tenant_id]
        if lead_id is not None:
            rows = [r for r in rows if r.lead_id == lead_id]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        if scheduled_date is not None:
            rows = [r for r in rows if r.scheduled_date == scheduled_date]
        if store_id is not None:
            rows = [r for r in rows if r.store_id == store_id]
        rows.sort(key=lambda r: r.created_at)
        total = len(rows)
        return rows[offset : offset + limit], total

    # ── EO 工单 ─────────────────────────────────────────────────────
    async def insert_eo_tickets(
        self, tickets: list[BanquetEOTicket]
    ) -> list[BanquetEOTicket]:
        for t in tickets:
            self._eo_tickets[t.eo_ticket_id] = t
        return list(tickets)

    async def get_eo_ticket(
        self, eo_ticket_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[BanquetEOTicket]:
        row = self._eo_tickets.get(eo_ticket_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return row

    async def update_eo_ticket(
        self, ticket: BanquetEOTicket
    ) -> BanquetEOTicket:
        self._eo_tickets[ticket.eo_ticket_id] = ticket
        return ticket

    async def list_eo_tickets_by_contract(
        self, contract_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> list[BanquetEOTicket]:
        rows = [
            t
            for t in self._eo_tickets.values()
            if t.tenant_id == tenant_id and t.contract_id == contract_id
        ]
        rows.sort(key=lambda t: t.created_at)
        return rows

    # ── 审批日志 ────────────────────────────────────────────────────
    async def insert_approval_log(
        self, log: BanquetApprovalLog
    ) -> BanquetApprovalLog:
        # C-3 修复：模拟 v283 部分 UNIQUE 索引
        #   (tenant_id, contract_id, role) WHERE action IN ('approve','reject')
        # 同合同同 role 只允许一条终结性决策日志（approve/reject）。
        if log.action in (ApprovalAction.APPROVE, ApprovalAction.REJECT):
            for existing in self._approval_logs.values():
                if (
                    existing.tenant_id == log.tenant_id
                    and existing.contract_id == log.contract_id
                    and existing.role == log.role
                    and existing.action in (
                        ApprovalAction.APPROVE,
                        ApprovalAction.REJECT,
                    )
                ):
                    raise _UniqueViolationSim(
                        f"approval log already exists for contract_id={log.contract_id} "
                        f"role={log.role.value}"
                    )
        self._approval_logs[log.log_id] = log
        return log

    async def list_approval_logs(
        self, contract_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> list[BanquetApprovalLog]:
        rows = [
            log
            for log in self._approval_logs.values()
            if log.tenant_id == tenant_id and log.contract_id == contract_id
        ]
        rows.sort(key=lambda log: log.created_at)
        return rows

    # ── 测试专用 hook ────────────────────────────────────────────────
    async def seed_contract(
        self,
        *,
        tenant_id: uuid.UUID,
        lead_id: uuid.UUID,
        customer_id: uuid.UUID,
        total_amount_fen: int = 100_000,
        deposit_fen: int = 30_000,
        status: ContractStatus = ContractStatus.DRAFT,
        banquet_type: BanquetType = BanquetType.BIRTHDAY,
        tables: int = 5,
        scheduled_date: Optional[date] = None,
        store_id: Optional[uuid.UUID] = None,
        sales_employee_id: Optional[uuid.UUID] = None,
        signed_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
    ) -> BanquetContract:
        now = created_at or datetime.now(timezone.utc)
        contract = BanquetContract(
            contract_id=uuid.uuid4(),
            tenant_id=tenant_id,
            store_id=store_id,
            lead_id=lead_id,
            customer_id=customer_id,
            sales_employee_id=sales_employee_id,
            banquet_type=banquet_type,
            tables=tables,
            total_amount_fen=total_amount_fen,
            deposit_fen=deposit_fen,
            pdf_url=None,
            status=status,
            approval_chain=[],
            scheduled_date=scheduled_date,
            signed_at=signed_at,
            cancelled_at=None,
            cancellation_reason=None,
            metadata={},
            created_by=None,
            created_at=now,
            updated_at=now,
        )
        return await self.insert_contract(contract)


# ──────────────────────────────────────────────────────────────────────────
# Pg 实现（生产使用，通过 asyncpg 直连 v282 三表）
# ──────────────────────────────────────────────────────────────────────────


_INSERT_CONTRACT_SQL = """
INSERT INTO banquet_contracts (
    contract_id, tenant_id, store_id, lead_id, customer_id, sales_employee_id,
    banquet_type, tables, total_amount_fen, deposit_fen, pdf_url, status,
    approval_chain, scheduled_date, signed_at, cancelled_at, cancellation_reason,
    metadata, created_by, created_at, updated_at
) VALUES (
    $1, $2, $3, $4, $5, $6,
    $7, $8, $9, $10, $11, $12,
    $13::jsonb, $14, $15, $16, $17,
    $18::jsonb, $19, $20, $21
)
"""

_UPDATE_CONTRACT_SQL = """
UPDATE banquet_contracts
SET store_id = $2,
    sales_employee_id = $3,
    tables = $4,
    total_amount_fen = $5,
    deposit_fen = $6,
    pdf_url = $7,
    status = $8,
    approval_chain = $9::jsonb,
    scheduled_date = $10,
    signed_at = $11,
    cancelled_at = $12,
    cancellation_reason = $13,
    metadata = $14::jsonb,
    updated_at = $15
WHERE contract_id = $1 AND tenant_id = $16
"""

_SELECT_CONTRACT_SQL = """
SELECT contract_id, tenant_id, store_id, lead_id, customer_id, sales_employee_id,
       banquet_type, tables, total_amount_fen, deposit_fen, pdf_url, status,
       approval_chain, scheduled_date, signed_at, cancelled_at, cancellation_reason,
       metadata, created_by, created_at, updated_at
FROM banquet_contracts
WHERE contract_id = $1 AND tenant_id = $2
"""


def _row_to_contract(row: Any) -> BanquetContract:
    approval_chain = row["approval_chain"]
    if isinstance(approval_chain, str):
        approval_chain = json.loads(approval_chain)
    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return BanquetContract(
        contract_id=row["contract_id"],
        tenant_id=row["tenant_id"],
        store_id=row["store_id"],
        lead_id=row["lead_id"],
        customer_id=row["customer_id"],
        sales_employee_id=row["sales_employee_id"],
        banquet_type=BanquetType(row["banquet_type"]),
        tables=row["tables"],
        total_amount_fen=row["total_amount_fen"],
        deposit_fen=row["deposit_fen"],
        pdf_url=row["pdf_url"],
        status=ContractStatus(row["status"]),
        approval_chain=approval_chain or [],
        scheduled_date=row["scheduled_date"],
        signed_at=row["signed_at"],
        cancelled_at=row["cancelled_at"],
        cancellation_reason=row["cancellation_reason"],
        metadata=metadata or {},
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_ticket(row: Any) -> BanquetEOTicket:
    content = row["content"]
    if isinstance(content, str):
        content = json.loads(content)
    return BanquetEOTicket(
        eo_ticket_id=row["eo_ticket_id"],
        tenant_id=row["tenant_id"],
        contract_id=row["contract_id"],
        department=EODepartment(row["department"]),
        assignee_employee_id=row["assignee_employee_id"],
        content=content or {},
        status=EOTicketStatus(row["status"]),
        dispatched_at=row["dispatched_at"],
        completed_at=row["completed_at"],
        reminder_sent_at=row["reminder_sent_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_log(row: Any) -> BanquetApprovalLog:
    return BanquetApprovalLog(
        log_id=row["log_id"],
        tenant_id=row["tenant_id"],
        contract_id=row["contract_id"],
        approver_id=row["approver_id"],
        role=ApprovalRole(row["role"]),
        action=ApprovalAction(row["action"]),
        notes=row["notes"],
        source_event_id=row["source_event_id"],
        created_at=row["created_at"],
    )


class PgBanquetContractRepository(BanquetContractRepositoryBase):
    """asyncpg 版 Repository。

    调用方须保证连接已设 `app.tenant_id`（RLS 由 v282 迁移提供的 USING/WITH CHECK 强制）。
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    # ── 合同主表 ─────────────────────────────────────────────────────
    async def insert_contract(self, contract: BanquetContract) -> BanquetContract:
        await self._conn.execute(
            _INSERT_CONTRACT_SQL,
            contract.contract_id,
            contract.tenant_id,
            contract.store_id,
            contract.lead_id,
            contract.customer_id,
            contract.sales_employee_id,
            contract.banquet_type.value,
            contract.tables,
            contract.total_amount_fen,
            contract.deposit_fen,
            contract.pdf_url,
            contract.status.value,
            json.dumps(contract.approval_chain or []),
            contract.scheduled_date,
            contract.signed_at,
            contract.cancelled_at,
            contract.cancellation_reason,
            json.dumps(contract.metadata or {}),
            contract.created_by,
            contract.created_at,
            contract.updated_at,
        )
        return contract

    async def get_contract(
        self, contract_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[BanquetContract]:
        row = await self._conn.fetchrow(_SELECT_CONTRACT_SQL, contract_id, tenant_id)
        if row is None:
            return None
        return _row_to_contract(row)

    async def update_contract(
        self, contract: BanquetContract
    ) -> BanquetContract:
        await self._conn.execute(
            _UPDATE_CONTRACT_SQL,
            contract.contract_id,
            contract.store_id,
            contract.sales_employee_id,
            contract.tables,
            contract.total_amount_fen,
            contract.deposit_fen,
            contract.pdf_url,
            contract.status.value,
            json.dumps(contract.approval_chain or []),
            contract.scheduled_date,
            contract.signed_at,
            contract.cancelled_at,
            contract.cancellation_reason,
            json.dumps(contract.metadata or {}),
            contract.updated_at,
            contract.tenant_id,
        )
        return contract

    async def list_contracts_by_lead(
        self, lead_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> list[BanquetContract]:
        rows = await self._conn.fetch(
            """
            SELECT * FROM banquet_contracts
            WHERE tenant_id = $1 AND lead_id = $2
            ORDER BY created_at ASC
            """,
            tenant_id,
            lead_id,
        )
        return [_row_to_contract(r) for r in rows]

    async def list_contracts(
        self,
        tenant_id: uuid.UUID,
        *,
        lead_id: Optional[uuid.UUID] = None,
        status: Optional[ContractStatus] = None,
        scheduled_date: Optional[date] = None,
        store_id: Optional[uuid.UUID] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BanquetContract], int]:
        clauses = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        if lead_id is not None:
            params.append(lead_id)
            clauses.append(f"lead_id = ${len(params)}")
        if status is not None:
            params.append(status.value)
            clauses.append(f"status = ${len(params)}")
        if scheduled_date is not None:
            params.append(scheduled_date)
            clauses.append(f"scheduled_date = ${len(params)}")
        if store_id is not None:
            params.append(store_id)
            clauses.append(f"store_id = ${len(params)}")
        where = " AND ".join(clauses)

        total_row = await self._conn.fetchrow(
            f"SELECT COUNT(*) AS n FROM banquet_contracts WHERE {where}",
            *params,
        )
        total = int(total_row["n"]) if total_row else 0

        params.extend([limit, offset])
        rows = await self._conn.fetch(
            f"""
            SELECT * FROM banquet_contracts WHERE {where}
            ORDER BY created_at ASC
            LIMIT ${len(params) - 1} OFFSET ${len(params)}
            """,
            *params,
        )
        return [_row_to_contract(r) for r in rows], total

    # ── EO 工单 ─────────────────────────────────────────────────────
    async def insert_eo_tickets(
        self, tickets: list[BanquetEOTicket]
    ) -> list[BanquetEOTicket]:
        for t in tickets:
            await self._conn.execute(
                """
                INSERT INTO banquet_eo_tickets (
                    eo_ticket_id, tenant_id, contract_id, department,
                    assignee_employee_id, content, status, dispatched_at,
                    completed_at, reminder_sent_at, created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11, $12
                )
                """,
                t.eo_ticket_id,
                t.tenant_id,
                t.contract_id,
                t.department.value,
                t.assignee_employee_id,
                json.dumps(t.content or {}),
                t.status.value,
                t.dispatched_at,
                t.completed_at,
                t.reminder_sent_at,
                t.created_at,
                t.updated_at,
            )
        return list(tickets)

    async def get_eo_ticket(
        self, eo_ticket_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[BanquetEOTicket]:
        row = await self._conn.fetchrow(
            """
            SELECT * FROM banquet_eo_tickets
            WHERE eo_ticket_id = $1 AND tenant_id = $2
            """,
            eo_ticket_id,
            tenant_id,
        )
        if row is None:
            return None
        return _row_to_ticket(row)

    async def update_eo_ticket(
        self, ticket: BanquetEOTicket
    ) -> BanquetEOTicket:
        await self._conn.execute(
            """
            UPDATE banquet_eo_tickets
            SET assignee_employee_id = $2,
                content = $3::jsonb,
                status = $4,
                dispatched_at = $5,
                completed_at = $6,
                reminder_sent_at = $7,
                updated_at = $8
            WHERE eo_ticket_id = $1 AND tenant_id = $9
            """,
            ticket.eo_ticket_id,
            ticket.assignee_employee_id,
            json.dumps(ticket.content or {}),
            ticket.status.value,
            ticket.dispatched_at,
            ticket.completed_at,
            ticket.reminder_sent_at,
            ticket.updated_at,
            ticket.tenant_id,
        )
        return ticket

    async def list_eo_tickets_by_contract(
        self, contract_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> list[BanquetEOTicket]:
        rows = await self._conn.fetch(
            """
            SELECT * FROM banquet_eo_tickets
            WHERE tenant_id = $1 AND contract_id = $2
            ORDER BY created_at ASC
            """,
            tenant_id,
            contract_id,
        )
        return [_row_to_ticket(r) for r in rows]

    # ── 审批日志 ────────────────────────────────────────────────────
    async def insert_approval_log(
        self, log: BanquetApprovalLog
    ) -> BanquetApprovalLog:
        await self._conn.execute(
            """
            INSERT INTO banquet_approval_logs (
                log_id, tenant_id, contract_id, approver_id, role, action,
                notes, source_event_id, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            log.log_id,
            log.tenant_id,
            log.contract_id,
            log.approver_id,
            log.role.value,
            log.action.value,
            log.notes,
            log.source_event_id,
            log.created_at,
        )
        return log

    async def list_approval_logs(
        self, contract_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> list[BanquetApprovalLog]:
        rows = await self._conn.fetch(
            """
            SELECT * FROM banquet_approval_logs
            WHERE tenant_id = $1 AND contract_id = $2
            ORDER BY created_at ASC
            """,
            tenant_id,
            contract_id,
        )
        return [_row_to_log(r) for r in rows]


__all__ = [
    "BanquetContractRepositoryBase",
    "InMemoryBanquetContractRepository",
    "PgBanquetContractRepository",
]
