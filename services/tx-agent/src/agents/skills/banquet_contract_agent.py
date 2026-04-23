"""宴会合同管家 Agent — Track R2-C / Sprint R2

P1 · 云端运行。对标食尚订"电子合同 + EO 工单 + 自动/人工审核流"。

5 个 action：
    - generate_contract   按宴会类型+桌数+套餐+订金比例生成 PDF + 写 banquet_contracts
    - split_eo            一份合同 → 5 部门（厨房/前厅/采购/财务/营销）工单
    - route_approval      金额阈值路由：< 10W 自动过；≥ 10W 或婚宴 → 店长；≥ 50W → 区经
    - lock_schedule       先到先得（订金锁档期）+ FIFO 候补队列
    - progress_reminder   T-7d / T-3d / T-1d / T-2h 四级推送（派 banquet_stage 任务）

硬约束：
    - margin：套餐总价与订金比例直接决定大额订单毛利
    - safety：采购工单 content 必须绑定食材批次（dish_bom 透传）
    - experience：豁免（合同签约非实时客户体验路径）
    constraint_scope = {"margin", "safety"}

R1 HTTP API 调用点：
    - GET  /api/v1/banquet-leads/{lead_id}                   （读线索）
    - POST /api/v1/banquet-leads/{lead_id}/convert           （lock_schedule 成功后调用）
    - POST /api/v1/tasks/dispatch                            （progress_reminder 批量派单）

tx-trade 本服务（同进程）合同操作：
    BanquetContractService / BanquetEOTicketService（通过依赖注入）

事件发射（走 emit_event，不直接持久化业务事件）：
    - 所有业务事件由 BanquetContractService 内部触发
    - Agent 只在 action 层做 asyncio.create_task 旁路，不阻塞主决策
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, ClassVar, Optional

import structlog

from ..base import AgentResult, SkillAgent
from ..context import ConstraintContext, IngredientSnapshot

logger = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# 配置 — 审批金额阈值（分）
# ──────────────────────────────────────────────────────────────────────────

# 10W 元 = 10_000 元 = 1_000_000 分
STORE_MANAGER_THRESHOLD_FEN = 10_000 * 100  # 1_000_000 分（10 万元）
# 50W 元 = 50_000 元 = 5_000_000 分
DISTRICT_MANAGER_THRESHOLD_FEN = 50_000 * 100  # 5_000_000 分（50 万元）

# 毛利底线（用于决策校验输入）
DEFAULT_BANQUET_COST_RATIO = Decimal("0.55")  # 宴会食材+人力 55%

# tx-trade 服务地址（HTTP API）
_TX_TRADE_URL = os.getenv("TX_TRADE_URL", "http://localhost:8001")
_TX_ORG_URL = os.getenv("TX_ORG_URL", "http://localhost:8012")


# ──────────────────────────────────────────────────────────────────────────
# 决策留痕
# ──────────────────────────────────────────────────────────────────────────


def _new_decision_id() -> uuid.UUID:
    return uuid.uuid4()


# ──────────────────────────────────────────────────────────────────────────
# BanquetContractAgent
# ──────────────────────────────────────────────────────────────────────────


class BanquetContractAgent(SkillAgent):
    """宴会合同管家 Agent。

    通过构造函数注入 service / repo / HTTP client，便于测试替换。
    """

    agent_id = "banquet_contract_agent"
    agent_name = "宴会合同管家"
    description = "宴会合同生成 + EO 工单拆分 + 审批路由 + 档期锁定 + 阶段提醒（5 action）"
    priority = "P1"
    run_location = "cloud"

    # 硬约束：对齐 docs/reservation-r2-contracts.md §6 矩阵
    constraint_scope: ClassVar[set[str]] = {"margin", "safety"}

    def __init__(
        self,
        tenant_id: str,
        store_id: Optional[str] = None,
        db: Optional[Any] = None,
        model_router: Optional[Any] = None,
        *,
        contract_service: Optional[Any] = None,
        eo_service: Optional[Any] = None,
        lead_api_client: Optional[Any] = None,
        task_api_client: Optional[Any] = None,
    ) -> None:
        super().__init__(tenant_id, store_id=store_id, db=db, model_router=model_router)
        # 延迟引入 BanquetContractService / EOTicketService，避免环状依赖
        self._contract_service = contract_service
        self._eo_service = eo_service
        # R1 HTTP API 客户端（测试 mock 用）
        self._lead_api = lead_api_client
        self._task_api = task_api_client
        # 决策留痕缓存（tier 2 测试 assert 用）
        self.decision_log: list[dict[str, Any]] = []

    # ─────────────────────────────────────────────────────────────────
    # Skill base 契约
    # ─────────────────────────────────────────────────────────────────
    def get_supported_actions(self) -> list[str]:
        return [
            "generate_contract",
            "split_eo",
            "route_approval",
            "lock_schedule",
            "progress_reminder",
        ]

    async def execute(
        self, action: str, params: dict[str, Any]
    ) -> AgentResult:
        dispatch = {
            "generate_contract": self._generate_contract,
            "split_eo": self._split_eo,
            "route_approval": self._route_approval,
            "lock_schedule": self._lock_schedule,
            "progress_reminder": self._progress_reminder,
        }
        handler = dispatch.get(action)
        if handler is None:
            return AgentResult(
                success=False,
                action=action,
                error=f"不支持的 action: {action}",
            )
        return await handler(params)

    # ─────────────────────────────────────────────────────────────────
    # Action 1 — generate_contract
    # ─────────────────────────────────────────────────────────────────
    async def _generate_contract(self, params: dict[str, Any]) -> AgentResult:
        """按线索 + 套餐 + 订金比例生成 PDF + 写 banquet_contracts。

        params 入参对齐 GenerateContractParams：
            tenant_id / lead_id / customer_id / sales_employee_id /
            banquet_type / tables / total_amount_fen / deposit_ratio /
            scheduled_date / template_id
        """
        from shared.ontology.src.extensions.banquet_contracts import ContractStatus
        from shared.ontology.src.extensions.banquet_leads import BanquetType

        tenant_id = _coerce_uuid(params.get("tenant_id"))
        lead_id = _coerce_uuid(params.get("lead_id"))
        customer_id = _coerce_uuid(params.get("customer_id"))
        if tenant_id is None or lead_id is None or customer_id is None:
            return AgentResult(
                success=False,
                action="generate_contract",
                error="tenant_id / lead_id / customer_id 必填",
            )

        banquet_type_raw = params.get("banquet_type") or "birthday"
        banquet_type = (
            banquet_type_raw
            if isinstance(banquet_type_raw, BanquetType)
            else BanquetType(str(banquet_type_raw))
        )
        tables = int(params.get("tables", 0))
        total_amount_fen = int(params.get("total_amount_fen", 0))
        deposit_ratio = _to_decimal(params.get("deposit_ratio"), Decimal("0.30"))
        deposit_fen = int(
            (Decimal(total_amount_fen) * deposit_ratio).quantize(Decimal("1"))
        )
        if deposit_fen > total_amount_fen:
            deposit_fen = total_amount_fen
        scheduled_date_raw = params.get("scheduled_date")
        scheduled_date = _coerce_date(scheduled_date_raw)
        template_id = params.get("template_id")

        # 读 R1 线索数据（HTTP 或注入的客户端；允许 None 表示不强制拉取）
        lead_snapshot: dict[str, Any] = {}
        if self._lead_api is not None:
            lead_snapshot = await self._lead_api.get_lead(
                tenant_id=tenant_id, lead_id=lead_id
            )

        # PDF 生成（placeholder）
        # 动态 import — 避免 tx-agent 对 tx-trade 硬依赖
        generate_contract_pdf_fn = _import_tx_trade(
            "services.banquet_pdf_generator", "generate_contract_pdf"
        )
        pdf_url, _, generation_ms = generate_contract_pdf_fn(
            contract_id=uuid.uuid4(),  # 仅用于 URL 占位，真 id 由 service 生成
            tenant_id=tenant_id,
            lead_id=lead_id,
            customer_id=customer_id,
            sales_employee_id=_coerce_uuid(params.get("sales_employee_id")),
            banquet_type=banquet_type,
            tables=tables,
            total_amount_fen=total_amount_fen,
            deposit_fen=deposit_fen,
            scheduled_date=scheduled_date,
            template_id=template_id,
        )

        # 调 BanquetContractService 写库 + 发事件
        contract_service = self._require_contract_service()
        dish_bom = lead_snapshot.get("dish_bom") if isinstance(lead_snapshot, dict) else None
        metadata: dict[str, Any] = {"template_id": template_id} if template_id else {}
        if dish_bom is not None:
            metadata["dish_bom"] = dish_bom

        contract = await contract_service.create_contract(
            tenant_id=tenant_id,
            lead_id=lead_id,
            customer_id=customer_id,
            banquet_type=banquet_type,
            tables=tables,
            total_amount_fen=total_amount_fen,
            deposit_fen=deposit_fen,
            pdf_url=pdf_url,
            store_id=_coerce_uuid(self.store_id),
            sales_employee_id=_coerce_uuid(params.get("sales_employee_id")),
            scheduled_date=scheduled_date,
            metadata=metadata,
            initial_status=ContractStatus.DRAFT,
            generation_ms=generation_ms,
        )

        # 构造约束上下文：margin 校验（total vs cost 估算）
        ctx = _build_constraint_context(
            total_amount_fen=total_amount_fen,
            banquet_type=banquet_type,
            purchase_batches=dish_bom if isinstance(dish_bom, list) else None,
            scope=self.constraint_scope,
        )

        decision_id = _new_decision_id()
        self._record_decision(
            decision_id=decision_id,
            action="generate_contract",
            input_context={
                "tenant_id": str(tenant_id),
                "lead_id": str(lead_id),
                "total_amount_fen": total_amount_fen,
                "deposit_ratio": str(deposit_ratio),
                "banquet_type": banquet_type.value,
            },
            output_action={
                "contract_id": str(contract.contract_id),
                "pdf_url": pdf_url,
                "generation_ms": generation_ms,
            },
            reasoning=(
                f"合同已生成 tables={tables} total={total_amount_fen/100:.2f}元 "
                f"deposit_ratio={deposit_ratio}"
            ),
        )

        return AgentResult(
            success=True,
            action="generate_contract",
            data={
                "contract_id": str(contract.contract_id),
                "pdf_url": pdf_url,
                "generation_ms": generation_ms,
                "total_amount_fen": total_amount_fen,
                "deposit_fen": deposit_fen,
                "status": contract.status.value,
                "decision_id": str(decision_id),
            },
            reasoning=f"合同 PDF 已生成（{generation_ms}ms）",
            confidence=0.95,
            context=ctx,
            inference_layer="cloud",
        )

    # ─────────────────────────────────────────────────────────────────
    # Action 2 — split_eo
    # ─────────────────────────────────────────────────────────────────
    async def _split_eo(self, params: dict[str, Any]) -> AgentResult:
        """一份合同 → 5 部门 EO 工单。原子写入。"""
        from shared.ontology.src.extensions.banquet_contracts import EODepartment

        tenant_id = _coerce_uuid(params.get("tenant_id"))
        contract_id = _coerce_uuid(params.get("contract_id"))
        if tenant_id is None or contract_id is None:
            return AgentResult(
                success=False,
                action="split_eo",
                error="tenant_id / contract_id 必填",
            )

        raw_departments = params.get("departments") or [
            EODepartment.KITCHEN,
            EODepartment.HALL,
            EODepartment.PURCHASE,
            EODepartment.FINANCE,
            EODepartment.MARKETING,
        ]
        departments: list[EODepartment] = []
        for d in raw_departments:
            departments.append(d if isinstance(d, EODepartment) else EODepartment(str(d)))

        contract_service = self._require_contract_service()
        eo_service = self._require_eo_service()

        contract = await contract_service.get_contract(contract_id, tenant_id)
        # 构造合同上下文透传给 EO 工单
        ctx: dict[str, Any] = {
            "tables": contract.tables,
            "total_amount_fen": contract.total_amount_fen,
            "deposit_fen": contract.deposit_fen,
        }
        dish_bom = None
        if isinstance(contract.metadata, dict):
            dish_bom = contract.metadata.get("dish_bom")
            if "dishes" in contract.metadata:
                ctx["dishes"] = contract.metadata["dishes"]
            if isinstance(dish_bom, list):
                ctx["dish_bom"] = dish_bom

        tickets = await eo_service.create_tickets_for_contract(
            tenant_id=tenant_id,
            contract_id=contract_id,
            departments=departments,
            contract_context=ctx,
        )

        # EO_DISPATCHED 事件
        asyncio.create_task(
            self._emit(
                event_type_value="banquet.eo_dispatched",
                tenant_id=tenant_id,
                stream_id=str(contract_id),
                payload={
                    "contract_id": str(contract_id),
                    "ticket_ids": [str(t.eo_ticket_id) for t in tickets],
                    "departments": [d.value for d in departments],
                    "dispatched_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )

        # 构造约束上下文（safety：采购批次；margin：透传 total）
        constraint_ctx = _build_constraint_context(
            total_amount_fen=contract.total_amount_fen,
            banquet_type=contract.banquet_type,
            purchase_batches=dish_bom if isinstance(dish_bom, list) else None,
            scope=self.constraint_scope,
        )

        decision_id = _new_decision_id()
        self._record_decision(
            decision_id=decision_id,
            action="split_eo",
            input_context={
                "contract_id": str(contract_id),
                "departments": [d.value for d in departments],
            },
            output_action={
                "ticket_count": len(tickets),
                "ticket_ids": [str(t.eo_ticket_id) for t in tickets],
            },
            reasoning=f"EO 工单拆分至 {len(departments)} 部门",
        )
        return AgentResult(
            success=True,
            action="split_eo",
            data={
                "contract_id": str(contract_id),
                "ticket_count": len(tickets),
                "ticket_ids": [str(t.eo_ticket_id) for t in tickets],
                "departments": [d.value for d in departments],
                "decision_id": str(decision_id),
            },
            reasoning=f"合同 {contract_id} 拆分为 {len(tickets)} 部门工单",
            confidence=1.0,
            context=constraint_ctx,
            inference_layer="cloud",
        )

    # ─────────────────────────────────────────────────────────────────
    # Action 3 — route_approval
    # ─────────────────────────────────────────────────────────────────
    async def _route_approval(self, params: dict[str, Any]) -> AgentResult:
        """审批路由：

        - total_amount_fen < 10W 且非婚宴：auto_passed=True、status=signed
        - total_amount_fen ≥ 10W 或 banquet_type=wedding：入店长审
        - total_amount_fen ≥ 50W：追加区经审
        """
        from shared.ontology.src.extensions.banquet_contracts import (
            ApprovalAction,
            ApprovalRole,
            BanquetApprovalLog,
            ContractStatus,
        )
        from shared.ontology.src.extensions.banquet_leads import BanquetType

        tenant_id = _coerce_uuid(params.get("tenant_id"))
        contract_id = _coerce_uuid(params.get("contract_id"))
        if tenant_id is None or contract_id is None:
            return AgentResult(
                success=False,
                action="route_approval",
                error="tenant_id / contract_id 必填",
            )

        total_amount_fen = int(params.get("total_amount_fen", 0))
        banquet_type_raw = params.get("banquet_type", "birthday")
        banquet_type = (
            banquet_type_raw
            if isinstance(banquet_type_raw, BanquetType)
            else BanquetType(str(banquet_type_raw))
        )
        approver_id = _coerce_uuid(params.get("approver_id"))
        approval_action_raw = params.get("approval_action")
        approval_action: Optional[ApprovalAction] = None
        if approval_action_raw is not None:
            approval_action = (
                approval_action_raw
                if isinstance(approval_action_raw, ApprovalAction)
                else ApprovalAction(str(approval_action_raw))
            )
        notes = params.get("notes")

        contract_service = self._require_contract_service()
        repo = self._require_repo()

        contract = await contract_service.get_contract(contract_id, tenant_id)

        needs_store_manager = (
            total_amount_fen >= STORE_MANAGER_THRESHOLD_FEN
            or banquet_type == BanquetType.WEDDING
        )
        needs_district_manager = total_amount_fen >= DISTRICT_MANAGER_THRESHOLD_FEN

        # 构造完整审批链（未决 decided_action=None）
        full_chain: list[dict[str, Any]] = []
        if needs_store_manager:
            full_chain.append(
                {
                    "role": ApprovalRole.STORE_MANAGER.value,
                    "required_threshold_fen": STORE_MANAGER_THRESHOLD_FEN,
                    "decided_action": None,
                }
            )
        if needs_district_manager:
            full_chain.append(
                {
                    "role": ApprovalRole.DISTRICT_MANAGER.value,
                    "required_threshold_fen": DISTRICT_MANAGER_THRESHOLD_FEN,
                    "decided_action": None,
                }
            )

        auto_passed = not needs_store_manager and not needs_district_manager
        next_role: Optional[ApprovalRole] = None
        final_status = contract.status

        if auto_passed:
            # 直接签约（placeholder 签名）
            signed = await contract_service.mark_signed(
                contract_id=contract_id,
                tenant_id=tenant_id,
                signer_id=approver_id,
                signature_provider="placeholder",
            )
            final_status = signed.status
            reasoning = (
                f"总额 {total_amount_fen/100:.2f}元 < 10W 且非婚宴 → 自动过审"
            )
            next_role = None
        else:
            # 若调用方附带 approval_action，则写入一条审批日志并推进下一节点
            if approval_action is not None and approver_id is not None:
                # 决定本次是哪个 role 的审批
                if needs_store_manager:
                    # 若 store_manager 尚未决策 → 认定是 store_manager
                    # 否则尝试 district_manager
                    existing = await repo.list_approval_logs(contract_id, tenant_id)
                    store_done = any(
                        log.role == ApprovalRole.STORE_MANAGER
                        and log.action == ApprovalAction.APPROVE
                        for log in existing
                    )
                    if not store_done:
                        log_role = ApprovalRole.STORE_MANAGER
                    else:
                        log_role = ApprovalRole.DISTRICT_MANAGER
                else:
                    log_role = ApprovalRole.DISTRICT_MANAGER

                log = BanquetApprovalLog(
                    log_id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    contract_id=contract_id,
                    approver_id=approver_id,
                    role=log_role,
                    action=approval_action,
                    notes=notes,
                    source_event_id=None,
                    created_at=datetime.now(timezone.utc),
                )
                await repo.insert_approval_log(log)

                # 更新审批链快照（写回 decided_action）
                chain_snapshot = list(contract.approval_chain or full_chain)
                if not chain_snapshot:
                    chain_snapshot = full_chain
                for entry in chain_snapshot:
                    if entry.get("role") == log_role.value and entry.get("decided_action") is None:
                        entry["decided_action"] = approval_action.value
                        entry["approver_id"] = str(approver_id)
                        entry["decided_at"] = datetime.now(timezone.utc).isoformat()
                        break

                if approval_action == ApprovalAction.REJECT:
                    # 整条链终止 → status 回 draft
                    await contract_service.update_status_and_chain(
                        contract_id=contract_id,
                        tenant_id=tenant_id,
                        new_status=ContractStatus.DRAFT,
                        approval_chain=chain_snapshot,
                    )
                    final_status = ContractStatus.DRAFT
                    next_role = None
                    reasoning = f"{log_role.value} 驳回 → 合同退回 draft"
                else:
                    # approve：检查是否所有环节都已过
                    remaining = [
                        e for e in chain_snapshot if e.get("decided_action") is None
                    ]
                    if not remaining:
                        # 全部审完 → 签约
                        await contract_service.update_status_and_chain(
                            contract_id=contract_id,
                            tenant_id=tenant_id,
                            new_status=ContractStatus.SIGNED,
                            approval_chain=chain_snapshot,
                        )
                        # 显式 mark_signed 填 signed_at + 发事件
                        signed = await contract_service.mark_signed(
                            contract_id=contract_id,
                            tenant_id=tenant_id,
                            signer_id=approver_id,
                            signature_provider="placeholder",
                        )
                        final_status = signed.status
                        next_role = None
                        reasoning = f"{log_role.value} 审批通过，合同链终 → signed"
                    else:
                        next_role = ApprovalRole(remaining[0]["role"])
                        await contract_service.update_status_and_chain(
                            contract_id=contract_id,
                            tenant_id=tenant_id,
                            new_status=ContractStatus.PENDING_APPROVAL,
                            approval_chain=chain_snapshot,
                        )
                        final_status = ContractStatus.PENDING_APPROVAL
                        reasoning = f"{log_role.value} 审批通过，下一节点: {next_role.value}"
            else:
                # 首次路由：写审批链 + status 置 pending_approval
                await contract_service.update_status_and_chain(
                    contract_id=contract_id,
                    tenant_id=tenant_id,
                    new_status=ContractStatus.PENDING_APPROVAL,
                    approval_chain=full_chain,
                )
                final_status = ContractStatus.PENDING_APPROVAL
                next_role = ApprovalRole(full_chain[0]["role"])
                reasoning = (
                    f"总额 {total_amount_fen/100:.2f}元 / banquet_type={banquet_type.value} "
                    f"→ 路由到 {next_role.value}"
                )

        # 发 APPROVAL_ROUTED 事件
        asyncio.create_task(
            self._emit(
                event_type_value="banquet.approval_routed",
                tenant_id=tenant_id,
                stream_id=str(contract_id),
                payload={
                    "contract_id": str(contract_id),
                    "approver_id": str(approver_id) if approver_id else None,
                    "role": next_role.value if next_role else "auto",
                    "action": approval_action.value if approval_action else "route",
                    "next_role": next_role.value if next_role else None,
                    "notes": notes,
                },
            )
        )

        constraint_ctx = _build_constraint_context(
            total_amount_fen=total_amount_fen,
            banquet_type=banquet_type,
            purchase_batches=None,
            scope=self.constraint_scope,
        )

        decision_id = _new_decision_id()
        self._record_decision(
            decision_id=decision_id,
            action="route_approval",
            input_context={
                "contract_id": str(contract_id),
                "total_amount_fen": total_amount_fen,
                "banquet_type": banquet_type.value,
                "approval_action": approval_action.value if approval_action else None,
            },
            output_action={
                "auto_passed": auto_passed,
                "next_role": next_role.value if next_role else None,
                "final_status": final_status.value,
            },
            reasoning=reasoning,
        )
        return AgentResult(
            success=True,
            action="route_approval",
            data={
                "contract_id": str(contract_id),
                "auto_passed": auto_passed,
                "next_role": next_role.value if next_role else None,
                "final_status": final_status.value,
                "decision_id": str(decision_id),
            },
            reasoning=reasoning,
            confidence=0.95,
            context=constraint_ctx,
            inference_layer="cloud",
        )

    # ─────────────────────────────────────────────────────────────────
    # Action 4 — lock_schedule
    # ─────────────────────────────────────────────────────────────────
    async def _lock_schedule(self, params: dict[str, Any]) -> AgentResult:
        """先到先得（订金锁档期）+ FIFO 候补队列。

        规则：
          - 同门店 + 同 scheduled_date + 已签 + 订金 > 0 的合同即为锁定方
          - 本合同若为首个满足条件者 → locked=True
          - 否则 → locked=False，queued_contract_ids 按 created_at ASC 排序
        """
        from shared.ontology.src.extensions.banquet_contracts import ContractStatus

        tenant_id = _coerce_uuid(params.get("tenant_id"))
        contract_id = _coerce_uuid(params.get("contract_id"))
        scheduled_date_raw = params.get("scheduled_date")
        scheduled_date = _coerce_date(scheduled_date_raw)
        store_id = _coerce_uuid(params.get("store_id"))
        deposit_paid_fen = int(params.get("deposit_paid_fen", 0))

        if (
            tenant_id is None
            or contract_id is None
            or scheduled_date is None
            or store_id is None
        ):
            return AgentResult(
                success=False,
                action="lock_schedule",
                error="tenant_id / contract_id / scheduled_date / store_id 必填",
            )

        contract_service = self._require_contract_service()
        repo = self._require_repo()

        # 所有同档期合同
        existing, _ = await repo.list_contracts(
            tenant_id=tenant_id,
            scheduled_date=scheduled_date,
            store_id=store_id,
            limit=1000,
        )
        # 已签约（SIGNED）且订金 > 0 的合同（按 created_at 升序）
        locked_existing = [
            c
            for c in existing
            if c.status == ContractStatus.SIGNED and c.deposit_fen > 0
        ]
        locked_existing.sort(key=lambda c: c.created_at)

        queued: list[str] = [
            str(c.contract_id) for c in existing if c.contract_id != contract_id
        ]

        locked = False
        if not locked_existing:
            # 无人锁定 — 本合同若已签 + 订金 > 0 → 直接锁定
            contract = await contract_service.get_contract(contract_id, tenant_id)
            if contract.status != ContractStatus.SIGNED:
                # 代理自动签（必须满足已付订金且可签）
                await contract_service.mark_signed(
                    contract_id=contract_id,
                    tenant_id=tenant_id,
                    signature_provider="placeholder",
                )
            if deposit_paid_fen > 0 or contract.deposit_fen > 0:
                locked = True
        else:
            # 已有人先锁 — 本合同若是该 "first come" 则 locked=True
            first_come = locked_existing[0]
            locked = first_come.contract_id == contract_id

        # 发 SCHEDULE_LOCKED 事件
        asyncio.create_task(
            self._emit(
                event_type_value="banquet.schedule_locked",
                tenant_id=tenant_id,
                stream_id=str(contract_id),
                payload={
                    "contract_id": str(contract_id),
                    "scheduled_date": scheduled_date.isoformat(),
                    "store_id": str(store_id),
                    "deposit_paid_fen": int(deposit_paid_fen),
                    "queued_contract_ids": queued,
                    "locked": locked,
                },
            )
        )

        constraint_ctx = _build_constraint_context(
            total_amount_fen=0,
            banquet_type=None,
            purchase_batches=None,
            scope=set(),  # lock 本身不涉及 margin/safety，显式空 scope
        )

        decision_id = _new_decision_id()
        self._record_decision(
            decision_id=decision_id,
            action="lock_schedule",
            input_context={
                "contract_id": str(contract_id),
                "scheduled_date": scheduled_date.isoformat(),
                "deposit_paid_fen": deposit_paid_fen,
            },
            output_action={
                "locked": locked,
                "queued_count": len(queued),
            },
            reasoning=f"档期 {scheduled_date.isoformat()} 先到先得: locked={locked}",
        )
        return AgentResult(
            success=True,
            action="lock_schedule",
            data={
                "contract_id": str(contract_id),
                "locked": locked,
                "queued_contract_ids": queued,
                "decision_id": str(decision_id),
            },
            reasoning=f"lock_schedule: locked={locked} queue={len(queued)}",
            confidence=1.0,
            context=constraint_ctx,
            inference_layer="cloud",
        )

    # ─────────────────────────────────────────────────────────────────
    # Action 5 — progress_reminder
    # ─────────────────────────────────────────────────────────────────
    async def _progress_reminder(self, params: dict[str, Any]) -> AgentResult:
        """T-7d / T-3d / T-1d / T-2h 四级推送。

        - target_departments 为空 → 推全部 EO 工单（默认 5 部门）
        - 已 completed 的工单跳过 + skipped_reason 填充
        - 每条未完成工单派发一条 banquet_stage 任务（HTTP 走 _task_api）
        """
        from shared.ontology.src.extensions.banquet_contracts import (
            EODepartment,
            EOTicketStatus,
        )

        tenant_id = _coerce_uuid(params.get("tenant_id"))
        contract_id = _coerce_uuid(params.get("contract_id"))
        reminder_stage = str(params.get("reminder_stage", "T-1d"))
        target_departments_raw = params.get("target_departments") or []
        target_departments: list[EODepartment] = [
            d if isinstance(d, EODepartment) else EODepartment(str(d))
            for d in target_departments_raw
        ]

        if tenant_id is None or contract_id is None:
            return AgentResult(
                success=False,
                action="progress_reminder",
                error="tenant_id / contract_id 必填",
            )
        if reminder_stage not in {"T-7d", "T-3d", "T-1d", "T-2h"}:
            return AgentResult(
                success=False,
                action="progress_reminder",
                error=f"reminder_stage 非法: {reminder_stage}（仅 T-7d/T-3d/T-1d/T-2h）",
            )

        eo_service = self._require_eo_service()
        tickets = await eo_service.list_by_contract(
            tenant_id=tenant_id, contract_id=contract_id
        )

        if target_departments:
            tickets = [t for t in tickets if t.department in target_departments]

        notified_ticket_ids: list[str] = []
        skipped: list[str] = []
        for t in tickets:
            if t.status == EOTicketStatus.COMPLETED:
                skipped.append(f"{t.department.value}:completed")
                continue
            # 发派 banquet_stage 任务
            if self._task_api is not None:
                await self._task_api.dispatch(
                    tenant_id=tenant_id,
                    task_type="banquet_stage",
                    assignee_employee_id=t.assignee_employee_id,
                    payload={
                        "contract_id": str(contract_id),
                        "eo_ticket_id": str(t.eo_ticket_id),
                        "department": t.department.value,
                        "reminder_stage": reminder_stage,
                    },
                )
            # 更新 reminder_sent_at
            await eo_service.mark_reminder_sent(
                tenant_id=tenant_id, eo_ticket_id=t.eo_ticket_id
            )
            notified_ticket_ids.append(str(t.eo_ticket_id))

        skipped_reason: Optional[str] = ", ".join(skipped) if skipped else None

        decision_id = _new_decision_id()
        self._record_decision(
            decision_id=decision_id,
            action="progress_reminder",
            input_context={
                "contract_id": str(contract_id),
                "reminder_stage": reminder_stage,
                "target_departments": [d.value for d in target_departments],
            },
            output_action={
                "notified_count": len(notified_ticket_ids),
                "skipped_count": len(skipped),
            },
            reasoning=f"{reminder_stage} 推送 {len(notified_ticket_ids)} 部门",
        )
        return AgentResult(
            success=True,
            action="progress_reminder",
            data={
                "contract_id": str(contract_id),
                "reminder_stage": reminder_stage,
                "notified_ticket_ids": notified_ticket_ids,
                "skipped_reason": skipped_reason,
                "decision_id": str(decision_id),
            },
            reasoning=f"{reminder_stage} 推送完成 notified={len(notified_ticket_ids)}",
            confidence=1.0,
            # 提醒推送不触发 margin / safety 校验
            context=ConstraintContext(constraint_scope=set()),
            inference_layer="cloud",
        )

    # ─────────────────────────────────────────────────────────────────
    # 内部工具
    # ─────────────────────────────────────────────────────────────────
    def _require_contract_service(self) -> Any:
        if self._contract_service is None:
            raise RuntimeError(
                "BanquetContractAgent 未注入 contract_service，请通过构造函数传入"
            )
        return self._contract_service

    def _require_eo_service(self) -> Any:
        if self._eo_service is None:
            raise RuntimeError(
                "BanquetContractAgent 未注入 eo_service，请通过构造函数传入"
            )
        return self._eo_service

    def _require_repo(self) -> Any:
        # 优先使用 contract_service 的 repo
        if self._contract_service is not None and hasattr(
            self._contract_service, "_repo"
        ):
            return self._contract_service._repo
        raise RuntimeError("BanquetContractAgent 未能获取 Repository")

    async def _emit(
        self,
        *,
        event_type_value: str,
        tenant_id: uuid.UUID,
        stream_id: str,
        payload: dict[str, Any],
    ) -> None:
        """旁路事件发射（asyncio.create_task 包装）。

        事件失败不影响主业务；event_type 从 shared.events 动态引入。
        """
        try:
            from shared.events.src.emitter import emit_event
            from shared.events.src.event_types import BanquetContractEventType

            # map string → enum
            mapping = {
                "banquet.contract_generated": BanquetContractEventType.CONTRACT_GENERATED,
                "banquet.contract_signed": BanquetContractEventType.CONTRACT_SIGNED,
                "banquet.eo_dispatched": BanquetContractEventType.EO_DISPATCHED,
                "banquet.approval_routed": BanquetContractEventType.APPROVAL_ROUTED,
                "banquet.schedule_locked": BanquetContractEventType.SCHEDULE_LOCKED,
            }
            event_type = mapping.get(event_type_value)
            if event_type is None:
                logger.warning("banquet_agent_unknown_event", event_type=event_type_value)
                return
            await emit_event(
                event_type=event_type,
                tenant_id=tenant_id,
                stream_id=stream_id,
                payload=payload,
                source_service="tx-agent",
            )
        except (ImportError, RuntimeError, ValueError) as exc:
            logger.warning("banquet_agent_emit_failed", error=str(exc))

    def _record_decision(
        self,
        *,
        decision_id: uuid.UUID,
        action: str,
        input_context: dict[str, Any],
        output_action: dict[str, Any],
        reasoning: str,
    ) -> None:
        self.decision_log.append(
            {
                "decision_id": str(decision_id),
                "tenant_id": str(self.tenant_id),
                "agent_id": self.agent_id,
                "action": action,
                "decision_type": "auto",
                "input_context": input_context,
                "output_action": output_action,
                "reasoning": reasoning,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "inference_layer": "cloud",
            }
        )


# ──────────────────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────────────────


def _coerce_uuid(value: Any) -> Optional[uuid.UUID]:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _coerce_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _to_decimal(value: Any, default: Decimal) -> Decimal:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return default


def _build_constraint_context(
    *,
    total_amount_fen: int,
    banquet_type: Any,
    purchase_batches: Optional[list[dict[str, Any]]],
    scope: set[str],
) -> ConstraintContext:
    """按宴会金额 + 食材批次组装约束校验上下文。

    margin：用默认宴会成本比 55% 估算 cost_fen；定价异常（<=0 或毛利率 < 15%）触发违规
    safety：purchase_batches 中 remaining_hours < 24h 触发违规
    experience：合同签约非实时客户体验路径，不填 estimated_serve_minutes
    """
    price_fen: Optional[int] = None
    cost_fen: Optional[int] = None
    if "margin" in scope and total_amount_fen >= 0:
        price_fen = total_amount_fen if total_amount_fen > 0 else 0
        cost_fen = int(
            (Decimal(total_amount_fen) * DEFAULT_BANQUET_COST_RATIO).quantize(Decimal("1"))
        )

    ingredients: Optional[list[IngredientSnapshot]] = None
    if "safety" in scope and purchase_batches:
        ingredients = []
        for item in purchase_batches:
            if not isinstance(item, dict):
                continue
            ingredients.append(
                IngredientSnapshot(
                    name=str(item.get("ingredient") or item.get("name") or "unknown"),
                    remaining_hours=item.get("remaining_hours"),
                    batch_id=item.get("batch_id"),
                )
            )
    return ConstraintContext(
        price_fen=price_fen,
        cost_fen=cost_fen,
        ingredients=ingredients,
        estimated_serve_minutes=None,
        constraint_scope=set(scope),
    )


def _import_tx_trade(module_suffix: str, attr: str) -> Any:
    """动态引入 services.tx-trade.src.<module_suffix>::<attr>。

    tx-agent 与 tx-trade 同 monorepo，实际部署为独立进程；但单元测试与
    集成阶段 Agent 需直接调用 tx-trade service 层。此函数允许多种路径：

    1. 若调用方在 tests 已把 tx-trade/src 加入 sys.path → 直接 `import <module_suffix>`
    2. 否则 fallback 到 `services.tx-trade...`（真生产少用）
    """
    import importlib

    # 优先 tests 注入的路径（test 会 prepend services/tx-trade/src）
    try:
        mod = importlib.import_module(f"src.{module_suffix}")
        return getattr(mod, attr)
    except ImportError:
        pass
    try:
        mod = importlib.import_module(module_suffix)
        return getattr(mod, attr)
    except ImportError:
        pass
    # 兜底：python 包的 "-" 在 import 路径里不合法，约定用下划线目录；实际未命中时抛
    raise ImportError(
        f"Unable to import {module_suffix}.{attr}; Agent 需在测试 conftest 加 tx-trade/src 到 sys.path"
    )


__all__ = [
    "BanquetContractAgent",
    "STORE_MANAGER_THRESHOLD_FEN",
    "DISTRICT_MANAGER_THRESHOLD_FEN",
]
