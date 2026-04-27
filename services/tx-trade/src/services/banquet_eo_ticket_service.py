"""宴会 EO 工单拆分服务 — Track R2-C / Sprint R2

职责：一份合同 → 拆到 5 部门（kitchen/hall/purchase/finance/marketing）
    各部门一条工单，保存于 banquet_eo_tickets 表。

事件：
    EO_DISPATCHED — 合同签约后一次性触发

拆分原子性：
    原子：split 流程在同一个 insert_eo_tickets 调用内批量写入。
    测试 + Pg 实现必须保证 tickets 列表整体写入或整体失败。

食安合规（硬约束 safety 输入）：
    采购部门工单 content 必填 batches 列表，元素结构 {ingredient, batch_id,
    remaining_hours}；banquet_contract_agent 在 Agent 层调用
    ConstraintContext 统一校验。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from shared.ontology.src.extensions.banquet_contracts import (
    BanquetEOTicket,
    EODepartment,
    EOTicketStatus,
)

from ..repositories.banquet_contract_repo import BanquetContractRepositoryBase

logger = structlog.get_logger(__name__)


# 5 部门默认模板（department → 默认 content schema）
DEFAULT_DEPARTMENT_CONTENT: dict[EODepartment, dict[str, Any]] = {
    EODepartment.KITCHEN: {
        "dishes": [],  # [{dish_id, name, quantity}]
        "courses": [],
    },
    EODepartment.HALL: {
        "tables": 0,
        "vip_required": False,
        "reception_notes": "",
    },
    EODepartment.PURCHASE: {
        "ingredients": [],
        "batches": [],  # [{ingredient, batch_id, remaining_hours}]
    },
    EODepartment.FINANCE: {
        "total_amount_fen": 0,
        "deposit_fen": 0,
        "remainder_fen": 0,
    },
    EODepartment.MARKETING: {
        "invitations": 0,
        "banners": [],
    },
}


class BanquetEOTicketService:
    """EO 工单拆分服务。"""

    def __init__(self, *, repo: BanquetContractRepositoryBase) -> None:
        self._repo = repo

    def _compose_content(
        self,
        department: EODepartment,
        *,
        base_content: Optional[dict[str, Any]] = None,
        contract_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """合成单部门 content JSON：默认模板 + 合同上下文派生。"""
        content = dict(DEFAULT_DEPARTMENT_CONTENT.get(department, {}))
        ctx = contract_context or {}
        if department == EODepartment.HALL and "tables" in ctx:
            content["tables"] = int(ctx["tables"])
        if department == EODepartment.FINANCE:
            total = int(ctx.get("total_amount_fen", 0))
            deposit = int(ctx.get("deposit_fen", 0))
            content["total_amount_fen"] = total
            content["deposit_fen"] = deposit
            content["remainder_fen"] = max(total - deposit, 0)
        if department == EODepartment.PURCHASE:
            # 透传合同 metadata.dish_bom（食材批次信息）到采购工单
            dish_bom = ctx.get("dish_bom")
            if isinstance(dish_bom, list):
                content["batches"] = dish_bom
        if department == EODepartment.KITCHEN:
            dishes = ctx.get("dishes")
            if isinstance(dishes, list):
                content["dishes"] = dishes
        if base_content:
            content.update(base_content)
        return content

    async def create_tickets_for_contract(
        self,
        *,
        tenant_id: uuid.UUID,
        contract_id: uuid.UUID,
        departments: list[EODepartment],
        content_by_department: Optional[dict[str, dict[str, Any]]] = None,
        contract_context: Optional[dict[str, Any]] = None,
    ) -> list[BanquetEOTicket]:
        """为合同批量生成 5 部门工单（原子）。

        content_by_department: 外部覆盖的 content（key = department 枚举 value）。
        contract_context:      从合同派生的派生字段（tables / amount / dish_bom ...）。
        """
        if not departments:
            raise ValueError("departments cannot be empty")

        now = datetime.now(timezone.utc)
        overrides = content_by_department or {}
        tickets: list[BanquetEOTicket] = []
        for dept in departments:
            base_content = overrides.get(dept.value)
            content = self._compose_content(
                dept,
                base_content=base_content,
                contract_context=contract_context,
            )
            tickets.append(
                BanquetEOTicket(
                    eo_ticket_id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    contract_id=contract_id,
                    department=dept,
                    assignee_employee_id=None,
                    content=content,
                    status=EOTicketStatus.PENDING,
                    dispatched_at=None,
                    completed_at=None,
                    reminder_sent_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )

        await self._repo.insert_eo_tickets(tickets)
        logger.info(
            "banquet_eo_tickets_created",
            tenant_id=str(tenant_id),
            contract_id=str(contract_id),
            count=len(tickets),
            departments=[d.value for d in departments],
        )
        return tickets

    async def list_by_contract(
        self,
        *,
        tenant_id: uuid.UUID,
        contract_id: uuid.UUID,
    ) -> list[BanquetEOTicket]:
        return await self._repo.list_eo_tickets_by_contract(contract_id, tenant_id)

    async def dispatch(
        self,
        *,
        tenant_id: uuid.UUID,
        eo_ticket_id: uuid.UUID,
        assignee_employee_id: Optional[uuid.UUID] = None,
    ) -> BanquetEOTicket:
        ticket = await self._repo.get_eo_ticket(eo_ticket_id, tenant_id)
        if ticket is None:
            raise ValueError(f"eo_ticket {eo_ticket_id} not found")
        now = datetime.now(timezone.utc)
        updated = ticket.model_copy(
            update={
                "status": EOTicketStatus.DISPATCHED,
                "dispatched_at": now,
                "assignee_employee_id": assignee_employee_id
                or ticket.assignee_employee_id,
                "updated_at": now,
            }
        )
        await self._repo.update_eo_ticket(updated)
        return updated

    async def complete(
        self,
        *,
        tenant_id: uuid.UUID,
        eo_ticket_id: uuid.UUID,
    ) -> BanquetEOTicket:
        ticket = await self._repo.get_eo_ticket(eo_ticket_id, tenant_id)
        if ticket is None:
            raise ValueError(f"eo_ticket {eo_ticket_id} not found")
        now = datetime.now(timezone.utc)
        updated = ticket.model_copy(
            update={
                "status": EOTicketStatus.COMPLETED,
                "completed_at": now,
                "updated_at": now,
            }
        )
        await self._repo.update_eo_ticket(updated)
        return updated

    async def mark_reminder_sent(
        self,
        *,
        tenant_id: uuid.UUID,
        eo_ticket_id: uuid.UUID,
    ) -> BanquetEOTicket:
        ticket = await self._repo.get_eo_ticket(eo_ticket_id, tenant_id)
        if ticket is None:
            raise ValueError(f"eo_ticket {eo_ticket_id} not found")
        now = datetime.now(timezone.utc)
        updated = ticket.model_copy(
            update={
                "reminder_sent_at": now,
                "updated_at": now,
            }
        )
        await self._repo.update_eo_ticket(updated)
        return updated


__all__ = ["BanquetEOTicketService", "DEFAULT_DEPARTMENT_CONTENT"]
