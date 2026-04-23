"""宴会商机漏斗服务 — Track D / Sprint R1

核心职责：
    1. 商机 CRUD（创建 / 阶段流转 / 转预订）
    2. 漏斗转化率按销售员工或渠道分组聚合
    3. 渠道归因表（来源 ROI）

流转图（状态机）：
    all  ─────▶ opportunity ─────▶ order  ─┬─▶ (converted)
     │            │                 │       └─▶ (kept at order, add reservation_id)
     └────────────┴─────────────────┴─▶ invalid（任何阶段都可置失效，需 reason）

设计细节：
    - 使用 emit_event 并行写事件（Redis + PG 双轨）
    - 错误不 broad except；具体错误类型暴露给路由层
    - 金额字段 _fen 整数；不使用 float
    - Repository 注入，便于 Tier 1 测试替换为内存实现
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import Any, Callable, Literal, Optional

import structlog

from shared.events.src.event_types import BanquetLeadEventType
from shared.ontology.src.extensions.banquet_leads import (
    BanquetLead,
    BanquetType,
    LeadStage,
    SourceChannel,
)

from ..repositories.banquet_lead_repo import BanquetLeadRepositoryBase

logger = structlog.get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────────
# 异常类型（供路由层转 HTTP 400/404）
# ──────────────────────────────────────────────────────────────────────────


class BanquetLeadError(Exception):
    """业务错误基类。"""

    code: str = "BANQUET_LEAD_ERROR"


class BanquetLeadNotFoundError(BanquetLeadError):
    code = "BANQUET_LEAD_NOT_FOUND"


class InvalidStageTransitionError(BanquetLeadError):
    code = "BANQUET_LEAD_INVALID_TRANSITION"


class InvalidationReasonMissingError(BanquetLeadError):
    code = "BANQUET_LEAD_INVALIDATION_REASON_MISSING"


class ReservationIdMissingError(BanquetLeadError):
    code = "BANQUET_LEAD_RESERVATION_ID_MISSING"


# ──────────────────────────────────────────────────────────────────────────
# 状态机
# ──────────────────────────────────────────────────────────────────────────

# 合法流转：前序 → 后继集合
_VALID_TRANSITIONS: dict[LeadStage, set[LeadStage]] = {
    LeadStage.ALL: {LeadStage.OPPORTUNITY, LeadStage.INVALID},
    LeadStage.OPPORTUNITY: {LeadStage.ORDER, LeadStage.INVALID},
    LeadStage.ORDER: {LeadStage.INVALID},  # order 终态：只能转 invalid，真正完结走 convert_to_reservation
    LeadStage.INVALID: set(),  # 终态
}


def _is_valid_transition(current: LeadStage, next_stage: LeadStage) -> bool:
    return next_stage in _VALID_TRANSITIONS.get(current, set())


# ──────────────────────────────────────────────────────────────────────────
# 服务
# ──────────────────────────────────────────────────────────────────────────


EmitEventFn = Callable[..., "asyncio.Future[Optional[str]] | Any"]


class BanquetLeadService:
    """宴会商机漏斗服务。

    Args:
        repo: Repository 实现（InMemory 用于测试，SQL 用于生产）
        emit_event: 事件发射器；默认从 shared.events.src.emitter 动态引入。
            测试场景可注入 mock，验证事件被正确触发。
    """

    def __init__(
        self,
        *,
        repo: BanquetLeadRepositoryBase,
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
    # 公共方法
    # ─────────────────────────────────────────────────────────────────

    async def create_lead(
        self,
        *,
        customer_id: uuid.UUID,
        banquet_type: BanquetType,
        source_channel: SourceChannel,
        sales_employee_id: Optional[uuid.UUID],
        estimated_amount_fen: int,
        estimated_tables: int,
        scheduled_date: Optional[date],
        tenant_id: uuid.UUID,
        store_id: Optional[uuid.UUID] = None,
        created_by: Optional[uuid.UUID] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> BanquetLead:
        """创建商机，初始 stage=all，同步发射 CREATED 事件。"""
        if estimated_amount_fen < 0:
            raise ValueError("estimated_amount_fen must be non-negative int (fen)")
        if estimated_tables < 0:
            raise ValueError("estimated_tables must be non-negative")

        now = datetime.now(timezone.utc)
        lead = BanquetLead(
            lead_id=uuid.uuid4(),
            tenant_id=tenant_id,
            store_id=store_id,
            customer_id=customer_id,
            sales_employee_id=sales_employee_id,
            banquet_type=banquet_type,
            source_channel=source_channel,
            stage=LeadStage.ALL,
            estimated_amount_fen=estimated_amount_fen,
            estimated_tables=estimated_tables,
            scheduled_date=scheduled_date,
            stage_changed_at=now,
            previous_stage=None,
            invalidation_reason=None,
            converted_reservation_id=None,
            metadata=metadata or {},
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        await self._repo.insert(lead)

        payload: dict[str, Any] = {
            "customer_id": str(customer_id),
            "banquet_type": banquet_type.value,
            "source_channel": source_channel.value,
            "stage": LeadStage.ALL.value,
            "estimated_amount_fen": int(estimated_amount_fen),
            "estimated_tables": int(estimated_tables),
        }
        if sales_employee_id is not None:
            payload["sales_employee_id"] = str(sales_employee_id)
        if scheduled_date is not None:
            payload["scheduled_date"] = scheduled_date.isoformat()

        await self._fire_event(
            event_type=BanquetLeadEventType.CREATED,
            tenant_id=tenant_id,
            stream_id=str(lead.lead_id),
            payload=payload,
            store_id=store_id,
            metadata={"operator_id": str(created_by)} if created_by else None,
        )
        logger.info(
            "banquet_lead_created",
            tenant_id=str(tenant_id),
            lead_id=str(lead.lead_id),
            source_channel=source_channel.value,
        )
        return lead

    async def transition_stage(
        self,
        *,
        lead_id: uuid.UUID,
        next_stage: LeadStage,
        operator_id: Optional[uuid.UUID],
        tenant_id: uuid.UUID,
        invalidation_reason: Optional[str] = None,
        causation_id: Optional[uuid.UUID | str] = None,
    ) -> BanquetLead:
        """阶段流转：all → opportunity → order → (invalid)。

        幂等规则：若 next_stage == 当前 stage，直接返回当前 lead，不发事件。

        Args:
            causation_id: 触发本次流转的父事件 ID（因果链追踪）。
                典型场景：订金退款 → lead 置 invalid 时，将 deposit.refunded
                的 event_id 作为 causation_id 透传，让下游 Agent 能从 lead
                回溯到原退款动作。
        """
        lead = await self._repo.get_by_id(lead_id, tenant_id)
        if lead is None:
            raise BanquetLeadNotFoundError(
                f"lead_id={lead_id} not found for tenant={tenant_id}"
            )

        # 幂等：已经在目标 stage，直接返回
        if lead.stage == next_stage:
            return lead

        if not _is_valid_transition(lead.stage, next_stage):
            raise InvalidStageTransitionError(
                f"invalid stage transition {lead.stage.value} -> {next_stage.value}"
            )

        if next_stage == LeadStage.INVALID and not invalidation_reason:
            raise InvalidationReasonMissingError(
                "invalidation_reason is required when transitioning to 'invalid'"
            )

        previous_stage = lead.stage
        now = datetime.now(timezone.utc)
        updated = lead.model_copy(
            update={
                "stage": next_stage,
                "previous_stage": previous_stage,
                "stage_changed_at": now,
                "invalidation_reason": (
                    invalidation_reason if next_stage == LeadStage.INVALID else lead.invalidation_reason
                ),
                "updated_at": now,
            }
        )
        await self._repo.update(updated)

        payload: dict[str, Any] = {
            "previous_stage": previous_stage.value,
            "next_stage": next_stage.value,
            "stage_changed_at": now.isoformat(),
        }
        if invalidation_reason:
            payload["invalidation_reason"] = invalidation_reason
        if operator_id:
            payload["operator_employee_id"] = str(operator_id)

        await self._fire_event(
            event_type=BanquetLeadEventType.STAGE_CHANGED,
            tenant_id=tenant_id,
            stream_id=str(lead_id),
            payload=payload,
            store_id=updated.store_id,
            metadata={"operator_id": str(operator_id)} if operator_id else None,
            causation_id=causation_id,
        )
        logger.info(
            "banquet_lead_stage_changed",
            tenant_id=str(tenant_id),
            lead_id=str(lead_id),
            previous_stage=previous_stage.value,
            next_stage=next_stage.value,
            causation_id=str(causation_id) if causation_id else None,
        )
        return updated

    async def convert_to_reservation(
        self,
        *,
        lead_id: uuid.UUID,
        reservation_id: uuid.UUID,
        operator_id: Optional[uuid.UUID],
        tenant_id: uuid.UUID,
    ) -> BanquetLead:
        """商机转正式预订：关联 reservation_id 并发射 CONVERTED 事件。

        前置：lead.stage 必须为 order（或上游流转到 order）。
        """
        if reservation_id is None:
            raise ReservationIdMissingError("reservation_id is required")

        lead = await self._repo.get_by_id(lead_id, tenant_id)
        if lead is None:
            raise BanquetLeadNotFoundError(
                f"lead_id={lead_id} not found for tenant={tenant_id}"
            )

        # 自动推进到 order（如仍在 all/opportunity）
        if lead.stage != LeadStage.ORDER:
            if lead.stage in (LeadStage.ALL, LeadStage.OPPORTUNITY):
                # 走正规 transition，以保持事件链完整
                if lead.stage == LeadStage.ALL:
                    lead = await self.transition_stage(
                        lead_id=lead_id,
                        next_stage=LeadStage.OPPORTUNITY,
                        operator_id=operator_id,
                        tenant_id=tenant_id,
                    )
                lead = await self.transition_stage(
                    lead_id=lead_id,
                    next_stage=LeadStage.ORDER,
                    operator_id=operator_id,
                    tenant_id=tenant_id,
                )
            else:
                raise InvalidStageTransitionError(
                    f"cannot convert lead in stage {lead.stage.value} to reservation"
                )

        now = datetime.now(timezone.utc)
        updated = lead.model_copy(
            update={
                "converted_reservation_id": reservation_id,
                "updated_at": now,
            }
        )
        await self._repo.update(updated)

        payload: dict[str, Any] = {
            "converted_reservation_id": str(reservation_id),
            "converted_at": now.isoformat(),
        }
        if operator_id:
            payload["operator_employee_id"] = str(operator_id)

        await self._fire_event(
            event_type=BanquetLeadEventType.CONVERTED,
            tenant_id=tenant_id,
            stream_id=str(lead_id),
            payload=payload,
            store_id=updated.store_id,
            metadata={"operator_id": str(operator_id)} if operator_id else None,
        )
        logger.info(
            "banquet_lead_converted",
            tenant_id=str(tenant_id),
            lead_id=str(lead_id),
            reservation_id=str(reservation_id),
        )
        return updated

    # ─────────────────────────────────────────────────────────────────
    # 订金退款 → 商机置失效（独立验证 P1-3 接入点，2026-04-23）
    # ─────────────────────────────────────────────────────────────────

    async def handle_deposit_refunded(
        self,
        *,
        lead_id: uuid.UUID,
        tenant_id: uuid.UUID,
        deposit_event_id: uuid.UUID | str,
        refund_reason: str,
        operator_id: Optional[uuid.UUID] = None,
    ) -> BanquetLead:
        """订金退款 → 商机流转到 invalid（徐记海鲜婚宴退宴场景）。

        业务流程：
          1. 客户婚宴已下订金（DepositEventType.COLLECTED/RECEIVED）
          2. 客户取消宴席 → tx-finance 发 deposit.refunded 事件
          3. BanquetFunnelProjector 订阅该事件 → 调本方法
          4. 本方法将 lead.stage 切到 invalid，invalidation_reason 自动填入
          5. 发射 banquet.lead_stage_changed 事件，causation_id = deposit_event_id

        因果链保障：R2 banquet_contract_agent 可以通过
          ``SELECT * FROM events WHERE causation_id = <deposit_refunded.event_id>``
        查到所有由退款触发的下游动作（lead 失效、销售佣金回收等）。

        Args:
            lead_id:          宴会商机 ID
            tenant_id:        租户 ID（RLS 隔离）
            deposit_event_id: 触发本次失效的退款事件 ID（因果链父）
            refund_reason:    退款原因（如 "客户取消宴席"）
            operator_id:      操作员（通常是财务员工；缺省表示系统自动）

        Returns:
            更新后的 BanquetLead（stage=invalid）

        Raises:
            BanquetLeadNotFoundError: lead 不存在或越租户访问
            InvalidStageTransitionError: 当前 stage 已无法流转到 invalid
                （实际上 INVALID 是唯一终态，从 all/opportunity/order 均可进入）
        """
        # 幂等：若 lead 已 invalid 就直接返回（transition_stage 内部已保证）
        lead = await self._repo.get_by_id(lead_id, tenant_id)
        if lead is None:
            raise BanquetLeadNotFoundError(
                f"lead_id={lead_id} not found for tenant={tenant_id}"
            )
        if lead.stage == LeadStage.INVALID:
            logger.info(
                "banquet_lead_already_invalid_on_deposit_refund",
                tenant_id=str(tenant_id),
                lead_id=str(lead_id),
                deposit_event_id=str(deposit_event_id),
            )
            return lead

        invalidation_reason = f"订金退款: {refund_reason}"
        updated = await self.transition_stage(
            lead_id=lead_id,
            next_stage=LeadStage.INVALID,
            operator_id=operator_id,
            tenant_id=tenant_id,
            invalidation_reason=invalidation_reason,
            causation_id=deposit_event_id,
        )
        logger.info(
            "banquet_lead_invalidated_by_deposit_refund",
            tenant_id=str(tenant_id),
            lead_id=str(lead_id),
            deposit_event_id=str(deposit_event_id),
            refund_reason=refund_reason,
        )
        return updated

    # ─────────────────────────────────────────────────────────────────
    # 聚合分析
    # ─────────────────────────────────────────────────────────────────

    async def compute_conversion_rate(
        self,
        *,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
        group_by: Literal["sales_employee_id", "source_channel"],
    ) -> dict[str, dict[str, Any]]:
        """按分组聚合：{group_key: {all, opportunity, order, invalid, total, conversion_rate}}。

        conversion_rate = order / total（total 为 stage_changed_at 落在期内的所有商机数）。
        若 total=0，conversion_rate=0.0。
        """
        rows = await self._repo.bulk_funnel_counts(
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            group_by=group_by,
        )
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            total = int(row["total"])
            order_cnt = int(row["order"])
            conv = (order_cnt / total) if total > 0 else 0.0
            result[row["group_key"]] = {
                "all": int(row["all"]),
                "opportunity": int(row["opportunity"]),
                "order": order_cnt,
                "invalid": int(row["invalid"]),
                "total": total,
                "estimated_amount_fen_total": int(
                    row.get("estimated_amount_fen_total", 0)
                ),
                "conversion_rate": conv,
            }
        return result

    async def source_attribution(
        self,
        *,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> list[dict[str, Any]]:
        """渠道归因：每个渠道的 total / converted / conversion_rate / 预估金额。

        conversion_rate = converted / total（converted = stage=order 的数量）。
        """
        rows = await self._repo.bulk_source_attribution(
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            total = int(row["total"])
            converted = int(row["converted"])
            conv = (converted / total) if total > 0 else 0.0
            out.append(
                {
                    "source_channel": row["source_channel"],
                    "total": total,
                    "converted": converted,
                    "invalid": int(row["invalid"]),
                    "estimated_amount_fen_total": int(
                        row["estimated_amount_fen_total"]
                    ),
                    "conversion_rate": conv,
                }
            )
        return out

    # ─────────────────────────────────────────────────────────────────
    # 内部：事件发射（并行 Redis + PG）
    # ─────────────────────────────────────────────────────────────────

    async def _fire_event(
        self,
        *,
        event_type: BanquetLeadEventType,
        tenant_id: uuid.UUID,
        stream_id: str,
        payload: dict[str, Any],
        store_id: Optional[uuid.UUID] = None,
        metadata: Optional[dict[str, Any]] = None,
        causation_id: Optional[uuid.UUID | str] = None,
    ) -> None:
        """调用注入的 emit_event。异步实现在注入函数内决定（真实用 create_task）。

        causation_id 如存在，会透传给 emitter 写入 events 表，支撑
        Agent 的因果链溯源（如：lead_stage_changed → deposit.refunded）。
        """
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
            # 事件写入失败不得影响主业务，但要显式留痕
            logger.warning(
                "banquet_lead_emit_event_failed",
                event_type=event_type.value,
                tenant_id=str(tenant_id),
                stream_id=stream_id,
                error=str(exc),
            )


__all__ = [
    "BanquetLeadService",
    "BanquetLeadError",
    "BanquetLeadNotFoundError",
    "InvalidStageTransitionError",
    "InvalidationReasonMissingError",
    "ReservationIdMissingError",
]
