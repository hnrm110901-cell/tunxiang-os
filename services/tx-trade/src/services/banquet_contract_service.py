"""宴会合同服务 — Track R2-C / Sprint R2

核心职责：
    1. 合同 CRUD（create / sign / cancel / get / list）
    2. 事件发射（CONTRACT_GENERATED / CONTRACT_SIGNED）
    3. 订金 / 毛利 / 金额阈值等前置校验（硬约束 margin 在 Agent 层做结构化）

流转图（状态机）：
    draft ──▶ pending_approval ──▶ signed
       │           │
       └───────────┴────▶ cancelled

幂等：
    - mark_signed 对已签合同幂等返回（不重复发 CONTRACT_SIGNED）
    - mark_cancelled 对已作废合同幂等返回

错误：
    - BanquetContractNotFoundError / InvalidContractTransitionError
    - CancellationReasonMissingError / SignatureRequiredError
    - 路由层捕获转 HTTP 404 / 400
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

import structlog

from shared.events.src.event_types import BanquetContractEventType
from shared.ontology.src.extensions.banquet_contracts import (
    BanquetContract,
    ContractStatus,
)
from shared.ontology.src.extensions.banquet_leads import BanquetType

from ..repositories.banquet_contract_repo import BanquetContractRepositoryBase

logger = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# 异常类型
# ──────────────────────────────────────────────────────────────────────────


class BanquetContractError(Exception):
    code: str = "BANQUET_CONTRACT_ERROR"


class BanquetContractNotFoundError(BanquetContractError):
    code = "BANQUET_CONTRACT_NOT_FOUND"


class InvalidContractTransitionError(BanquetContractError):
    code = "BANQUET_CONTRACT_INVALID_TRANSITION"


class CancellationReasonMissingError(BanquetContractError):
    code = "BANQUET_CONTRACT_CANCEL_REASON_MISSING"


class SignatureRequiredError(BanquetContractError):
    code = "BANQUET_CONTRACT_SIGNATURE_REQUIRED"


class ScheduleAlreadyLockedError(BanquetContractError):
    """档期已被其它合同 signed 锁定（C-2 修复：v283 部分 UNIQUE 索引命中）。"""

    code = "BANQUET_CONTRACT_SCHEDULE_LOCKED"


class ApprovalAlreadyRecordedError(BanquetContractError):
    """同合同同 role 的 approve/reject 日志已存在（C-3 修复：v283 部分 UNIQUE 索引命中）。"""

    code = "BANQUET_CONTRACT_APPROVAL_ALREADY_RECORDED"


# ──────────────────────────────────────────────────────────────────────────
# 状态机
# ──────────────────────────────────────────────────────────────────────────

_VALID_TRANSITIONS: dict[ContractStatus, set[ContractStatus]] = {
    ContractStatus.DRAFT: {
        ContractStatus.PENDING_APPROVAL,
        ContractStatus.SIGNED,
        ContractStatus.CANCELLED,
    },
    ContractStatus.PENDING_APPROVAL: {
        ContractStatus.SIGNED,
        ContractStatus.CANCELLED,
        ContractStatus.DRAFT,  # 审批驳回退回 draft
    },
    ContractStatus.SIGNED: {
        ContractStatus.CANCELLED,  # 已签约后作废需要补偿流程
    },
    ContractStatus.CANCELLED: set(),  # 终态
}


def _is_valid_transition(current: ContractStatus, nxt: ContractStatus) -> bool:
    return nxt in _VALID_TRANSITIONS.get(current, set())


# ──────────────────────────────────────────────────────────────────────────
# 服务
# ──────────────────────────────────────────────────────────────────────────

EmitEventFn = Callable[..., "asyncio.Future[Optional[str]] | Any"]


class BanquetContractService:
    """宴会合同服务。

    Args:
        repo:       合同 Repository（InMemory / Pg）
        emit_event: 事件发射器；默认从 shared.events.src.emitter 动态引入。
            测试场景可注入 fake 记录事件。
    """

    def __init__(
        self,
        *,
        repo: BanquetContractRepositoryBase,
        emit_event: Optional[EmitEventFn] = None,
    ) -> None:
        self._repo = repo
        self._emit_event: EmitEventFn
        if emit_event is None:
            from shared.events.src.emitter import emit_event as _default_emit

            self._emit_event = _default_emit  # type: ignore[assignment]
        else:
            self._emit_event = emit_event

    # ─────────────────────────────────────────────────────────────────
    # 创建合同
    # ─────────────────────────────────────────────────────────────────
    async def create_contract(
        self,
        *,
        tenant_id: uuid.UUID,
        lead_id: uuid.UUID,
        customer_id: uuid.UUID,
        banquet_type: BanquetType,
        tables: int,
        total_amount_fen: int,
        deposit_fen: int,
        pdf_url: Optional[str] = None,
        store_id: Optional[uuid.UUID] = None,
        sales_employee_id: Optional[uuid.UUID] = None,
        scheduled_date: Optional[date] = None,
        metadata: Optional[dict[str, Any]] = None,
        created_by: Optional[uuid.UUID] = None,
        initial_status: ContractStatus = ContractStatus.DRAFT,
        approval_chain: Optional[list[dict[str, Any]]] = None,
        generation_ms: int = 0,
    ) -> BanquetContract:
        if total_amount_fen < 0:
            raise ValueError("total_amount_fen must be non-negative int (fen)")
        if deposit_fen < 0 or deposit_fen > total_amount_fen:
            raise ValueError("deposit_fen 必须 0 <= deposit_fen <= total_amount_fen")
        if tables < 0:
            raise ValueError("tables must be >= 0")

        now = datetime.now(timezone.utc)
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
            pdf_url=pdf_url,
            status=initial_status,
            approval_chain=list(approval_chain or []),
            scheduled_date=scheduled_date,
            signed_at=None,
            cancelled_at=None,
            cancellation_reason=None,
            metadata=metadata or {},
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        await self._repo.insert_contract(contract)

        payload: dict[str, Any] = {
            "contract_id": str(contract.contract_id),
            "lead_id": str(lead_id),
            "total_amount_fen": int(total_amount_fen),
        }
        if pdf_url:
            payload["pdf_url"] = pdf_url
        if generation_ms:
            payload["generation_ms"] = int(generation_ms)

        await self._fire_event(
            event_type=BanquetContractEventType.CONTRACT_GENERATED,
            tenant_id=tenant_id,
            stream_id=str(contract.contract_id),
            payload=payload,
            store_id=store_id,
            metadata={"operator_id": str(created_by)} if created_by else None,
        )
        logger.info(
            "banquet_contract_created",
            tenant_id=str(tenant_id),
            contract_id=str(contract.contract_id),
            lead_id=str(lead_id),
            total_amount_fen=total_amount_fen,
            status=initial_status.value,
        )
        return contract

    # ─────────────────────────────────────────────────────────────────
    # 查询
    # ─────────────────────────────────────────────────────────────────
    async def get_contract(
        self, contract_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> BanquetContract:
        contract = await self._repo.get_contract(contract_id, tenant_id)
        if contract is None:
            raise BanquetContractNotFoundError(
                f"contract_id={contract_id} not found for tenant={tenant_id}"
            )
        return contract

    async def list_by_lead(
        self, lead_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> list[BanquetContract]:
        return await self._repo.list_contracts_by_lead(lead_id, tenant_id)

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
        return await self._repo.list_contracts(
            tenant_id=tenant_id,
            lead_id=lead_id,
            status=status,
            scheduled_date=scheduled_date,
            store_id=store_id,
            offset=offset,
            limit=limit,
        )

    # ─────────────────────────────────────────────────────────────────
    # 签约（幂等）
    # ─────────────────────────────────────────────────────────────────
    async def mark_signed(
        self,
        *,
        contract_id: uuid.UUID,
        tenant_id: uuid.UUID,
        signer_id: Optional[uuid.UUID] = None,
        signature_provider: str = "placeholder",
        pdf_url: Optional[str] = None,
        signed_at: Optional[datetime] = None,
        causation_id: Optional[uuid.UUID | str] = None,
    ) -> BanquetContract:
        """将合同置为 signed。

        幂等：若已 signed 直接返回（不再发事件）。

        并发保护（C-2 修复）：
            - DB 层靠 v283 部分 UNIQUE 索引
              (tenant_id, store_id, scheduled_date) WHERE status='signed'
              保证同门店同档期只能有一张 signed 合同。
            - Service 层在 update_contract 前先扫描已 signed 的同档期合同
              （InMemory 实现）；Pg 实现在 asyncpg 抛 UniqueViolationError
              时由 update_contract 转抛 ScheduleAlreadyLockedError。
            - 若命中 → 抛 ScheduleAlreadyLockedError，调用方（Agent）转候补。
        """
        contract = await self.get_contract(contract_id, tenant_id)
        if contract.status == ContractStatus.SIGNED:
            return contract
        if not _is_valid_transition(contract.status, ContractStatus.SIGNED):
            raise InvalidContractTransitionError(
                f"cannot sign contract in status={contract.status.value}"
            )
        if not signature_provider:
            raise SignatureRequiredError("signature_provider is required")

        # C-2 修复：InMemory 层原子检查同档期是否已被 signed 合同锁定。
        # 生产 Pg 实现依赖 v283 部分 UNIQUE 索引 + asyncpg UniqueViolationError。
        if (
            contract.store_id is not None
            and contract.scheduled_date is not None
        ):
            existing_signed, _ = await self._repo.list_contracts(
                tenant_id=tenant_id,
                status=ContractStatus.SIGNED,
                scheduled_date=contract.scheduled_date,
                store_id=contract.store_id,
                limit=1,
            )
            conflict = [
                c for c in existing_signed if c.contract_id != contract_id
            ]
            if conflict:
                raise ScheduleAlreadyLockedError(
                    f"schedule already locked by contract_id={conflict[0].contract_id}"
                )

        now = signed_at or datetime.now(timezone.utc)
        updated = contract.model_copy(
            update={
                "status": ContractStatus.SIGNED,
                "signed_at": now,
                "pdf_url": pdf_url or contract.pdf_url,
                "updated_at": now,
            }
        )
        try:
            await self._repo.update_contract(updated)
        except Exception as exc:  # noqa: BLE001
            # 生产 Pg 层：asyncpg.UniqueViolationError / IntegrityError
            # 经 v283 部分 UNIQUE 索引抛出时转 ScheduleAlreadyLockedError
            if _is_unique_violation(exc):
                raise ScheduleAlreadyLockedError(
                    f"schedule lock unique index violated for contract_id={contract_id}"
                ) from exc
            raise

        payload: dict[str, Any] = {
            "contract_id": str(contract_id),
            "signed_at": now.isoformat(),
            "signature_provider": signature_provider,
        }
        if signer_id:
            payload["signer_id"] = str(signer_id)

        await self._fire_event(
            event_type=BanquetContractEventType.CONTRACT_SIGNED,
            tenant_id=tenant_id,
            stream_id=str(contract_id),
            payload=payload,
            store_id=updated.store_id,
            metadata={"operator_id": str(signer_id)} if signer_id else None,
            causation_id=causation_id,
        )
        logger.info(
            "banquet_contract_signed",
            tenant_id=str(tenant_id),
            contract_id=str(contract_id),
            signature_provider=signature_provider,
        )
        return updated

    # ─────────────────────────────────────────────────────────────────
    # 作废（幂等）
    # ─────────────────────────────────────────────────────────────────
    async def mark_cancelled(
        self,
        *,
        contract_id: uuid.UUID,
        tenant_id: uuid.UUID,
        reason: str,
        operator_id: Optional[uuid.UUID] = None,
    ) -> BanquetContract:
        if not reason:
            raise CancellationReasonMissingError("cancellation reason is required")
        contract = await self.get_contract(contract_id, tenant_id)
        if contract.status == ContractStatus.CANCELLED:
            return contract
        if not _is_valid_transition(contract.status, ContractStatus.CANCELLED):
            raise InvalidContractTransitionError(
                f"cannot cancel contract in status={contract.status.value}"
            )
        now = datetime.now(timezone.utc)
        updated = contract.model_copy(
            update={
                "status": ContractStatus.CANCELLED,
                "cancelled_at": now,
                "cancellation_reason": reason,
                "updated_at": now,
            }
        )
        await self._repo.update_contract(updated)
        logger.info(
            "banquet_contract_cancelled",
            tenant_id=str(tenant_id),
            contract_id=str(contract_id),
            reason=reason,
        )
        return updated

    # ─────────────────────────────────────────────────────────────────
    # 审批日志写入（C-3 修复：幂等 + 唯一约束兜底）
    # ─────────────────────────────────────────────────────────────────
    async def insert_approval_log(self, log: Any) -> Any:
        """写入审批日志；若 DB 层 UNIQUE 约束（v283）命中则抛
        ApprovalAlreadyRecordedError。

        调用方（Agent._route_approval）捕获后降级为幂等返回。
        """
        try:
            return await self._repo.insert_approval_log(log)
        except Exception as exc:  # noqa: BLE001
            if _is_unique_violation(exc):
                raise ApprovalAlreadyRecordedError(
                    f"approval already recorded for contract_id={log.contract_id} "
                    f"role={log.role.value}"
                ) from exc
            raise

    # ─────────────────────────────────────────────────────────────────
    # 写回审批链 / status
    # ─────────────────────────────────────────────────────────────────
    async def update_status_and_chain(
        self,
        *,
        contract_id: uuid.UUID,
        tenant_id: uuid.UUID,
        new_status: ContractStatus,
        approval_chain: Optional[list[dict[str, Any]]] = None,
    ) -> BanquetContract:
        contract = await self.get_contract(contract_id, tenant_id)
        if new_status != contract.status and not _is_valid_transition(
            contract.status, new_status
        ):
            raise InvalidContractTransitionError(
                f"transition {contract.status.value} -> {new_status.value} not allowed"
            )
        now = datetime.now(timezone.utc)
        update_kwargs: dict[str, Any] = {
            "status": new_status,
            "updated_at": now,
        }
        if approval_chain is not None:
            update_kwargs["approval_chain"] = list(approval_chain)
        if new_status == ContractStatus.SIGNED and contract.signed_at is None:
            update_kwargs["signed_at"] = now
        updated = contract.model_copy(update=update_kwargs)
        await self._repo.update_contract(updated)
        return updated

    # ─────────────────────────────────────────────────────────────────
    # 内部：事件发射
    # ─────────────────────────────────────────────────────────────────
    async def _fire_event(
        self,
        *,
        event_type: BanquetContractEventType,
        tenant_id: uuid.UUID,
        stream_id: str,
        payload: dict[str, Any],
        store_id: Optional[uuid.UUID] = None,
        metadata: Optional[dict[str, Any]] = None,
        causation_id: Optional[uuid.UUID | str] = None,
    ) -> None:
        try:
            await self._emit_event(
                event_type=event_type,
                tenant_id=tenant_id,
                stream_id=stream_id,
                payload=payload,
                store_id=store_id,
                source_service="tx-trade",
                metadata=metadata,
                causation_id=causation_id,
            )
        except (asyncio.CancelledError, RuntimeError, ValueError) as exc:
            logger.warning(
                "banquet_contract_emit_event_failed",
                event_type=event_type.value,
                tenant_id=str(tenant_id),
                stream_id=stream_id,
                error=str(exc),
            )


# ──────────────────────────────────────────────────────────────────────────
# 工具：UNIQUE 约束违反识别（跨 asyncpg / psycopg2 / sqlite 的轻量兼容）
# ──────────────────────────────────────────────────────────────────────────


def _is_unique_violation(exc: BaseException) -> bool:
    """识别 DB 驱动抛出的 UNIQUE 约束违反。

    避免在 service 层 import asyncpg（tx-trade 测试 InMemory 不依赖 asyncpg）。
    通过异常类名 + sqlstate 属性软探测，足够覆盖 asyncpg / psycopg2 / sqlite3。
    """
    # asyncpg.exceptions.UniqueViolationError / UniqueViolation
    cls_name = type(exc).__name__
    if "UniqueViolation" in cls_name:
        return True
    # asyncpg 统一基类 PostgresError 挂 sqlstate；23505 = unique_violation
    sqlstate = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)
    if sqlstate == "23505":
        return True
    return False


__all__ = [
    "BanquetContractService",
    "BanquetContractError",
    "BanquetContractNotFoundError",
    "InvalidContractTransitionError",
    "CancellationReasonMissingError",
    "SignatureRequiredError",
    "ScheduleAlreadyLockedError",
    "ApprovalAlreadyRecordedError",
]
