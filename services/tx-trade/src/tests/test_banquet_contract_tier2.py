"""Tier 2 测试 — 宴会合同管家底座（Track R2-C / Sprint R2）

覆盖 service + repo + EO 工单 + 审批日志 + 幂等 + 租户隔离 + 事件发射 + 候补队列。

关联实现：
  services/tx-trade/src/services/banquet_contract_service.py
  services/tx-trade/src/services/banquet_eo_ticket_service.py
  services/tx-trade/src/repositories/banquet_contract_repo.py
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timezone
from typing import Any

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.ontology.src.extensions.banquet_contracts import (
    ApprovalAction,
    ApprovalRole,
    BanquetApprovalLog,
    ContractStatus,
    EODepartment,
    EOTicketStatus,
)
from shared.ontology.src.extensions.banquet_leads import BanquetType
from src.repositories.banquet_contract_repo import (
    InMemoryBanquetContractRepository,
)
from src.services.banquet_contract_service import (
    BanquetContractNotFoundError,
    BanquetContractService,
    CancellationReasonMissingError,
    InvalidContractTransitionError,
)
from src.services.banquet_eo_ticket_service import BanquetEOTicketService

TENANT_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
TENANT_B = uuid.UUID("00000000-0000-0000-0000-000000000002")
STORE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def repo() -> InMemoryBanquetContractRepository:
    return InMemoryBanquetContractRepository()


@pytest.fixture
def emitted() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def service(
    repo: InMemoryBanquetContractRepository, emitted: list[dict[str, Any]]
) -> BanquetContractService:
    async def _fake_emit(**kwargs: Any) -> str:
        emitted.append(kwargs)
        return str(uuid.uuid4())

    return BanquetContractService(repo=repo, emit_event=_fake_emit)


@pytest.fixture
def eo_service(
    repo: InMemoryBanquetContractRepository,
) -> BanquetEOTicketService:
    return BanquetEOTicketService(repo=repo)


# ─────────────────────────────────────────────────────────────────────────
# T1. CRUD：创建 / 查询 / 签约 / 作废
# ─────────────────────────────────────────────────────────────────────────


class TestContractCrud:
    @pytest.mark.asyncio
    async def test_create_contract_emits_generated_event(
        self,
        service: BanquetContractService,
        emitted: list[dict[str, Any]],
    ):
        contract = await service.create_contract(
            tenant_id=TENANT_A,
            lead_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.WEDDING,
            tables=20,
            total_amount_fen=2_000_000,  # 20 万元
            deposit_fen=600_000,
            pdf_url="https://fake-s3/contract.pdf",
            store_id=STORE_ID,
        )
        assert contract.status == ContractStatus.DRAFT
        assert contract.total_amount_fen == 2_000_000
        assert contract.deposit_fen == 600_000
        assert contract.pdf_url == "https://fake-s3/contract.pdf"

        assert len(emitted) == 1
        evt = emitted[0]
        assert evt["event_type"].value == "banquet.contract_generated"
        assert evt["tenant_id"] == TENANT_A
        assert evt["payload"]["total_amount_fen"] == 2_000_000
        assert evt["payload"]["pdf_url"] == "https://fake-s3/contract.pdf"

    @pytest.mark.asyncio
    async def test_create_contract_rejects_deposit_over_total(
        self,
        service: BanquetContractService,
    ):
        with pytest.raises(ValueError):
            await service.create_contract(
                tenant_id=TENANT_A,
                lead_id=uuid.uuid4(),
                customer_id=uuid.uuid4(),
                banquet_type=BanquetType.BIRTHDAY,
                tables=5,
                total_amount_fen=100_000,
                deposit_fen=200_000,  # 订金 > 总额
            )

    @pytest.mark.asyncio
    async def test_mark_signed_is_idempotent(
        self,
        service: BanquetContractService,
        emitted: list[dict[str, Any]],
    ):
        contract = await service.create_contract(
            tenant_id=TENANT_A,
            lead_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.BIRTHDAY,
            tables=3,
            total_amount_fen=80_000,
            deposit_fen=20_000,
        )
        emitted.clear()

        signed = await service.mark_signed(
            contract_id=contract.contract_id,
            tenant_id=TENANT_A,
            signer_id=uuid.uuid4(),
        )
        assert signed.status == ContractStatus.SIGNED
        assert signed.signed_at is not None
        signed_events = [e for e in emitted if e["event_type"].value == "banquet.contract_signed"]
        assert len(signed_events) == 1

        # 第二次调用 — 幂等，不重发事件
        again = await service.mark_signed(
            contract_id=contract.contract_id,
            tenant_id=TENANT_A,
        )
        assert again.status == ContractStatus.SIGNED
        signed_events_after = [e for e in emitted if e["event_type"].value == "banquet.contract_signed"]
        assert len(signed_events_after) == 1, "重复签约不应重复发事件"

    @pytest.mark.asyncio
    async def test_mark_cancelled_requires_reason(
        self,
        service: BanquetContractService,
    ):
        contract = await service.create_contract(
            tenant_id=TENANT_A,
            lead_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.BIRTHDAY,
            tables=3,
            total_amount_fen=50_000,
            deposit_fen=10_000,
        )
        with pytest.raises(CancellationReasonMissingError):
            await service.mark_cancelled(
                contract_id=contract.contract_id,
                tenant_id=TENANT_A,
                reason="",
            )
        cancelled = await service.mark_cancelled(
            contract_id=contract.contract_id,
            tenant_id=TENANT_A,
            reason="客户取消",
        )
        assert cancelled.status == ContractStatus.CANCELLED
        assert cancelled.cancellation_reason == "客户取消"

    @pytest.mark.asyncio
    async def test_get_contract_not_found_raises(
        self,
        service: BanquetContractService,
    ):
        with pytest.raises(BanquetContractNotFoundError):
            await service.get_contract(uuid.uuid4(), TENANT_A)

    @pytest.mark.asyncio
    async def test_invalid_transition_cancelled_to_signed_raises(
        self,
        service: BanquetContractService,
    ):
        contract = await service.create_contract(
            tenant_id=TENANT_A,
            lead_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.CORPORATE,
            tables=2,
            total_amount_fen=30_000,
            deposit_fen=5_000,
        )
        await service.mark_cancelled(
            contract_id=contract.contract_id,
            tenant_id=TENANT_A,
            reason="企业合并取消",
        )
        with pytest.raises(InvalidContractTransitionError):
            await service.mark_signed(
                contract_id=contract.contract_id,
                tenant_id=TENANT_A,
            )


# ─────────────────────────────────────────────────────────────────────────
# T2. 租户隔离（RLS 应用层回退）
# ─────────────────────────────────────────────────────────────────────────


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_cross_tenant_contract_not_visible(
        self,
        service: BanquetContractService,
    ):
        contract = await service.create_contract(
            tenant_id=TENANT_A,
            lead_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.WEDDING,
            tables=10,
            total_amount_fen=1_500_000,
            deposit_fen=300_000,
        )
        # TENANT_B 无法获取 TENANT_A 的合同
        with pytest.raises(BanquetContractNotFoundError):
            await service.get_contract(contract.contract_id, TENANT_B)

    @pytest.mark.asyncio
    async def test_cross_tenant_eo_tickets_not_visible(
        self,
        service: BanquetContractService,
        eo_service: BanquetEOTicketService,
        repo: InMemoryBanquetContractRepository,
    ):
        contract = await service.create_contract(
            tenant_id=TENANT_A,
            lead_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.BIRTHDAY,
            tables=4,
            total_amount_fen=100_000,
            deposit_fen=30_000,
        )
        await eo_service.create_tickets_for_contract(
            tenant_id=TENANT_A,
            contract_id=contract.contract_id,
            departments=[EODepartment.KITCHEN, EODepartment.HALL],
        )
        # TENANT_B 看不到该合同下的 EO 工单
        tickets_b = await repo.list_eo_tickets_by_contract(contract.contract_id, TENANT_B)
        assert tickets_b == []


# ─────────────────────────────────────────────────────────────────────────
# T3. EO 工单 — 5 部门原子拆分
# ─────────────────────────────────────────────────────────────────────────


class TestEoSplit:
    @pytest.mark.asyncio
    async def test_split_creates_5_department_tickets(
        self,
        service: BanquetContractService,
        eo_service: BanquetEOTicketService,
    ):
        contract = await service.create_contract(
            tenant_id=TENANT_A,
            lead_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.WEDDING,
            tables=20,
            total_amount_fen=2_000_000,
            deposit_fen=600_000,
            metadata={
                "dish_bom": [
                    {"ingredient": "龙虾", "batch_id": "B-001", "remaining_hours": 48},
                ]
            },
        )
        tickets = await eo_service.create_tickets_for_contract(
            tenant_id=TENANT_A,
            contract_id=contract.contract_id,
            departments=[
                EODepartment.KITCHEN,
                EODepartment.HALL,
                EODepartment.PURCHASE,
                EODepartment.FINANCE,
                EODepartment.MARKETING,
            ],
            contract_context={
                "tables": contract.tables,
                "total_amount_fen": contract.total_amount_fen,
                "deposit_fen": contract.deposit_fen,
                "dish_bom": contract.metadata.get("dish_bom"),
            },
        )
        assert len(tickets) == 5
        depts = [t.department for t in tickets]
        assert set(depts) == {
            EODepartment.KITCHEN,
            EODepartment.HALL,
            EODepartment.PURCHASE,
            EODepartment.FINANCE,
            EODepartment.MARKETING,
        }

        # 财务工单透传 total/deposit
        finance = next(t for t in tickets if t.department == EODepartment.FINANCE)
        assert finance.content["total_amount_fen"] == 2_000_000
        assert finance.content["deposit_fen"] == 600_000
        assert finance.content["remainder_fen"] == 1_400_000

        # 采购工单透传食材批次
        purchase = next(t for t in tickets if t.department == EODepartment.PURCHASE)
        assert purchase.content["batches"][0]["ingredient"] == "龙虾"

        # 所有工单初始 status=pending
        assert all(t.status == EOTicketStatus.PENDING for t in tickets)

    @pytest.mark.asyncio
    async def test_dispatch_and_complete_eo_ticket(
        self,
        service: BanquetContractService,
        eo_service: BanquetEOTicketService,
    ):
        contract = await service.create_contract(
            tenant_id=TENANT_A,
            lead_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.CORPORATE,
            tables=5,
            total_amount_fen=200_000,
            deposit_fen=50_000,
        )
        tickets = await eo_service.create_tickets_for_contract(
            tenant_id=TENANT_A,
            contract_id=contract.contract_id,
            departments=[EODepartment.KITCHEN],
        )
        t = tickets[0]
        assignee = uuid.uuid4()
        dispatched = await eo_service.dispatch(
            tenant_id=TENANT_A,
            eo_ticket_id=t.eo_ticket_id,
            assignee_employee_id=assignee,
        )
        assert dispatched.status == EOTicketStatus.DISPATCHED
        assert dispatched.dispatched_at is not None
        assert dispatched.assignee_employee_id == assignee

        completed = await eo_service.complete(
            tenant_id=TENANT_A,
            eo_ticket_id=t.eo_ticket_id,
        )
        assert completed.status == EOTicketStatus.COMPLETED
        assert completed.completed_at is not None


# ─────────────────────────────────────────────────────────────────────────
# T4. 审批日志 + 审批链
# ─────────────────────────────────────────────────────────────────────────


class TestApprovalLogs:
    @pytest.mark.asyncio
    async def test_approval_log_write_and_read(
        self,
        service: BanquetContractService,
        repo: InMemoryBanquetContractRepository,
    ):
        contract = await service.create_contract(
            tenant_id=TENANT_A,
            lead_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.WEDDING,
            tables=30,
            total_amount_fen=5_500_000,  # 55 万
            deposit_fen=1_500_000,
        )
        log1 = BanquetApprovalLog(
            log_id=uuid.uuid4(),
            tenant_id=TENANT_A,
            contract_id=contract.contract_id,
            approver_id=uuid.uuid4(),
            role=ApprovalRole.STORE_MANAGER,
            action=ApprovalAction.APPROVE,
            notes=None,
            source_event_id=None,
            created_at=datetime.now(timezone.utc),
        )
        await repo.insert_approval_log(log1)
        log2 = BanquetApprovalLog(
            log_id=uuid.uuid4(),
            tenant_id=TENANT_A,
            contract_id=contract.contract_id,
            approver_id=uuid.uuid4(),
            role=ApprovalRole.DISTRICT_MANAGER,
            action=ApprovalAction.APPROVE,
            notes="区经核准",
            source_event_id=None,
            created_at=datetime.now(timezone.utc),
        )
        await repo.insert_approval_log(log2)

        logs = await repo.list_approval_logs(contract.contract_id, TENANT_A)
        assert len(logs) == 2
        assert logs[0].role == ApprovalRole.STORE_MANAGER
        assert logs[1].role == ApprovalRole.DISTRICT_MANAGER


# ─────────────────────────────────────────────────────────────────────────
# T5. 候补队列（FIFO）— 多合同同档期
# ─────────────────────────────────────────────────────────────────────────


class TestScheduleQueue:
    @pytest.mark.asyncio
    async def test_fifo_queue_by_created_at(
        self,
        service: BanquetContractService,
        repo: InMemoryBanquetContractRepository,
    ):
        sched = date(2026, 10, 1)
        # 先创建三个合同（同档期）
        c1 = await service.create_contract(
            tenant_id=TENANT_A,
            lead_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.WEDDING,
            tables=20,
            total_amount_fen=2_000_000,
            deposit_fen=600_000,
            scheduled_date=sched,
            store_id=STORE_ID,
        )
        c2 = await service.create_contract(
            tenant_id=TENANT_A,
            lead_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.WEDDING,
            tables=15,
            total_amount_fen=1_600_000,
            deposit_fen=500_000,
            scheduled_date=sched,
            store_id=STORE_ID,
        )
        c3 = await service.create_contract(
            tenant_id=TENANT_A,
            lead_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.WEDDING,
            tables=18,
            total_amount_fen=1_800_000,
            deposit_fen=500_000,
            scheduled_date=sched,
            store_id=STORE_ID,
        )

        items, total = await repo.list_contracts(
            tenant_id=TENANT_A,
            scheduled_date=sched,
            store_id=STORE_ID,
            limit=100,
        )
        assert total == 3
        # created_at 升序 — FIFO
        ids_in_order = [c.contract_id for c in items]
        assert ids_in_order == [c1.contract_id, c2.contract_id, c3.contract_id]
