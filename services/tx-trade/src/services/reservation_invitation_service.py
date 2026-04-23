"""预订邀请函 / 核餐外呼 Service（Sprint R2 Track A）

核心职责：
    1. 邀请函/外呼 CRUD（create / mark_sent / mark_confirmed / mark_failed）
    2. 按 reservation_id / customer_id 查询历史记录
    3. 并行事件写入：INVITATION_SENT / CONFIRM_CALL_SENT / CONFIRMED / NO_SHOW

设计细节：
    - 使用注入的 emit_event 函数，默认从 shared.events.src.emitter 动态引入
    - 错误不 broad except；具体错误类型暴露给路由/Agent 层
    - 金额字段 _fen 整数；不使用 float
    - Repository 注入，便于 Tier 2 测试替换为 InMemory 实现
    - 状态跃迁遵守 pending → sent → confirmed/failed 的严格顺序
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import structlog

from shared.events.src.event_types import R2ReservationEventType
from shared.ontology.src.extensions.reservation_invitations import (
    InvitationChannel,
    InvitationRecord,
    InvitationStatus,
)

from ..repositories.reservation_invitation_repo import InvitationRepositoryBase

logger = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# 异常类型
# ──────────────────────────────────────────────────────────────────────────


class InvitationError(Exception):
    """业务错误基类。"""

    code: str = "INVITATION_ERROR"


class InvitationNotFoundError(InvitationError):
    code = "INVITATION_NOT_FOUND"


class InvalidInvitationTransitionError(InvitationError):
    code = "INVITATION_INVALID_TRANSITION"


# 合法状态跃迁
_VALID_TRANSITIONS: dict[InvitationStatus, set[InvitationStatus]] = {
    InvitationStatus.PENDING: {InvitationStatus.SENT, InvitationStatus.FAILED},
    InvitationStatus.SENT: {InvitationStatus.CONFIRMED, InvitationStatus.FAILED},
    InvitationStatus.CONFIRMED: set(),  # 终态
    InvitationStatus.FAILED: set(),  # 终态
}


def _is_valid_transition(
    current: InvitationStatus, target: InvitationStatus
) -> bool:
    return target in _VALID_TRANSITIONS.get(current, set())


EmitEventFn = Callable[..., "asyncio.Future[Optional[str]] | Any"]


# ──────────────────────────────────────────────────────────────────────────
# Service
# ──────────────────────────────────────────────────────────────────────────


class ReservationInvitationService:
    """预订邀请函 / 核餐外呼服务。

    Args:
        repo: Repository 实现（InMemory 用于测试，Pg 用于生产）
        emit_event: 事件发射器；默认从 shared.events.src.emitter 动态引入。
            测试场景可注入 mock，验证事件被正确触发。
    """

    def __init__(
        self,
        *,
        repo: InvitationRepositoryBase,
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

    async def create_invitation(
        self,
        *,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
        channel: InvitationChannel,
        customer_id: Optional[uuid.UUID] = None,
        store_id: Optional[uuid.UUID] = None,
        coupon_code: Optional[str] = None,
        coupon_value_fen: int = 0,
        payload: Optional[dict[str, Any]] = None,
        source_event_id: Optional[uuid.UUID] = None,
    ) -> InvitationRecord:
        """创建 pending 邀请记录。不立即发射事件（发送成功后由 mark_sent 触发）。"""
        if coupon_value_fen < 0:
            raise ValueError("coupon_value_fen must be non-negative int (fen)")

        now = datetime.now(timezone.utc)
        record = InvitationRecord(
            invitation_id=uuid.uuid4(),
            tenant_id=tenant_id,
            store_id=store_id,
            reservation_id=reservation_id,
            customer_id=customer_id,
            channel=channel,
            status=InvitationStatus.PENDING,
            sent_at=None,
            confirmed_at=None,
            coupon_code=coupon_code,
            coupon_value_fen=coupon_value_fen,
            failure_reason=None,
            payload=payload or {},
            source_event_id=source_event_id,
            created_at=now,
            updated_at=now,
        )
        await self._repo.insert(record)
        logger.info(
            "reservation_invitation_created",
            tenant_id=str(tenant_id),
            invitation_id=str(record.invitation_id),
            reservation_id=str(reservation_id),
            channel=channel.value,
        )
        return record

    async def mark_sent(
        self,
        *,
        invitation_id: uuid.UUID,
        tenant_id: uuid.UUID,
        sent_at: Optional[datetime] = None,
    ) -> InvitationRecord:
        """标记已发出。发射 INVITATION_SENT 或 CONFIRM_CALL_SENT 事件。"""
        record = await self._load(invitation_id, tenant_id)
        if not _is_valid_transition(record.status, InvitationStatus.SENT):
            raise InvalidInvitationTransitionError(
                f"invitation {invitation_id} in status {record.status.value} "
                f"cannot transition to sent"
            )
        now = sent_at or datetime.now(timezone.utc)
        updated = record.model_copy(
            update={
                "status": InvitationStatus.SENT,
                "sent_at": now,
                "updated_at": now,
            }
        )
        await self._repo.update(updated)

        # 外呼通道 → CONFIRM_CALL_SENT；其他 → INVITATION_SENT
        event_type = (
            R2ReservationEventType.CONFIRM_CALL_SENT
            if record.channel == InvitationChannel.CALL
            else R2ReservationEventType.INVITATION_SENT
        )
        payload: dict[str, Any] = {
            "reservation_id": str(record.reservation_id),
            "invitation_id": str(record.invitation_id),
            "channel": record.channel.value,
            "sent_at": now.isoformat(),
        }
        if record.coupon_code:
            payload["coupon_code"] = record.coupon_code
        if record.coupon_value_fen:
            payload["coupon_value_fen"] = int(record.coupon_value_fen)

        await self._fire_event(
            event_type=event_type,
            tenant_id=tenant_id,
            stream_id=str(record.reservation_id),
            payload=payload,
            store_id=record.store_id,
        )
        return updated

    async def mark_confirmed(
        self,
        *,
        invitation_id: uuid.UUID,
        tenant_id: uuid.UUID,
        confirmed_at: Optional[datetime] = None,
    ) -> InvitationRecord:
        """标记客户已确认。发射 reservation.confirmed 事件。"""
        record = await self._load(invitation_id, tenant_id)
        if not _is_valid_transition(record.status, InvitationStatus.CONFIRMED):
            raise InvalidInvitationTransitionError(
                f"invitation {invitation_id} in status {record.status.value} "
                f"cannot transition to confirmed"
            )
        now = confirmed_at or datetime.now(timezone.utc)
        updated = record.model_copy(
            update={
                "status": InvitationStatus.CONFIRMED,
                "confirmed_at": now,
                "updated_at": now,
            }
        )
        await self._repo.update(updated)

        payload = {
            "reservation_id": str(record.reservation_id),
            "confirmed_at": now.isoformat(),
            "confirm_channel": record.channel.value,
        }
        await self._fire_event(
            event_type=R2ReservationEventType.CONFIRMED,
            tenant_id=tenant_id,
            stream_id=str(record.reservation_id),
            payload=payload,
            store_id=record.store_id,
        )
        return updated

    async def mark_failed(
        self,
        *,
        invitation_id: uuid.UUID,
        tenant_id: uuid.UUID,
        failure_reason: str,
    ) -> InvitationRecord:
        """标记发送失败。不发业务事件（避免噪声）。"""
        if not failure_reason or not failure_reason.strip():
            raise ValueError("failure_reason is required for mark_failed")
        record = await self._load(invitation_id, tenant_id)
        if not _is_valid_transition(record.status, InvitationStatus.FAILED):
            raise InvalidInvitationTransitionError(
                f"invitation {invitation_id} in status {record.status.value} "
                f"cannot transition to failed"
            )
        now = datetime.now(timezone.utc)
        updated = record.model_copy(
            update={
                "status": InvitationStatus.FAILED,
                "failure_reason": failure_reason.strip()[:200],
                "updated_at": now,
            }
        )
        await self._repo.update(updated)
        logger.info(
            "reservation_invitation_failed",
            tenant_id=str(tenant_id),
            invitation_id=str(invitation_id),
            channel=record.channel.value,
            reason=failure_reason[:64],
        )
        return updated

    async def list_by_reservation(
        self,
        *,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
    ) -> list[InvitationRecord]:
        return await self._repo.list_by_reservation(tenant_id, reservation_id)

    async def get(
        self,
        *,
        invitation_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> InvitationRecord:
        return await self._load(invitation_id, tenant_id)

    # ─────────────────────────────────────────────────────────────────
    # 内部工具
    # ─────────────────────────────────────────────────────────────────

    async def _load(
        self, invitation_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> InvitationRecord:
        record = await self._repo.get_by_id(invitation_id, tenant_id)
        if record is None:
            raise InvitationNotFoundError(
                f"invitation_id={invitation_id} not found for tenant={tenant_id}"
            )
        return record

    async def _fire_event(
        self,
        *,
        event_type: R2ReservationEventType,
        tenant_id: uuid.UUID,
        stream_id: str,
        payload: dict[str, Any],
        store_id: Optional[uuid.UUID] = None,
        metadata: Optional[dict[str, Any]] = None,
        causation_id: Optional[uuid.UUID | str] = None,
    ) -> None:
        """发射事件，失败不影响主业务但留痕。"""
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
                "reservation_invitation_emit_event_failed",
                event_type=event_type.value,
                tenant_id=str(tenant_id),
                stream_id=stream_id,
                error=str(exc),
            )


__all__ = [
    "ReservationInvitationService",
    "InvitationError",
    "InvitationNotFoundError",
    "InvalidInvitationTransitionError",
]
