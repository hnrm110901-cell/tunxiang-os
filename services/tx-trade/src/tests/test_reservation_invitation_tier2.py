"""Tier 2 测试 — 预订邀请函 / 核餐外呼（Sprint R2 Track A）

验收场景（对齐 CLAUDE.md §17 Tier 2 + docs/reservation-r2-contracts.md §5.1）：
  - 邀请函/外呼 CRUD
  - 状态跃迁幂等 pending → sent → confirmed/failed
  - 事件并行写入（INVITATION_SENT / CONFIRM_CALL_SENT / CONFIRMED）
  - 租户隔离：A 租户不能读写 B 租户邀请
  - 券码面值校验

关联实现：
  services/tx-trade/src/services/reservation_invitation_service.py
  services/tx-trade/src/repositories/reservation_invitation_repo.py
  services/tx-trade/src/api/reservation_invitation_routes.py
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.events.src.event_types import R2ReservationEventType
from shared.ontology.src.extensions.reservation_invitations import (
    InvitationChannel,
    InvitationStatus,
)
from src.repositories.reservation_invitation_repo import (
    InMemoryInvitationRepository,
)
from src.services.reservation_invitation_service import (
    InvalidInvitationTransitionError,
    InvitationNotFoundError,
    ReservationInvitationService,
)

TENANT_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
TENANT_B = uuid.UUID("00000000-0000-0000-0000-000000000002")
STORE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def repo() -> InMemoryInvitationRepository:
    return InMemoryInvitationRepository()


@pytest.fixture
def emitted() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def service(
    repo: InMemoryInvitationRepository, emitted: list[dict[str, Any]]
) -> ReservationInvitationService:
    async def _fake_emit(**kwargs: Any) -> str:
        emitted.append(kwargs)
        return str(uuid.uuid4())

    return ReservationInvitationService(repo=repo, emit_event=_fake_emit)


# ─────────────────────────────────────────────────────────────────────────
# T1. CRUD — 徐记海鲜前台登记婚宴，H5 邀请函 + 券码
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_invitation_writes_pending_record_no_event(
    service: ReservationInvitationService,
    emitted: list[dict[str, Any]],
) -> None:
    """创建邀请函（pending）不应发事件 — 发送成功才发 INVITATION_SENT。"""
    reservation_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    record = await service.create_invitation(
        tenant_id=TENANT_A,
        reservation_id=reservation_id,
        channel=InvitationChannel.WECHAT,
        customer_id=customer_id,
        store_id=STORE_ID,
        coupon_code="VIP2026",
        coupon_value_fen=5000,
        payload={"template_id": "wedding_h5_v1"},
    )
    assert record.status == InvitationStatus.PENDING
    assert record.coupon_value_fen == 5000
    assert record.coupon_code == "VIP2026"
    assert record.payload["template_id"] == "wedding_h5_v1"
    # 不应该有事件发射
    assert emitted == []


@pytest.mark.asyncio
async def test_mark_sent_wechat_emits_invitation_sent(
    service: ReservationInvitationService,
    emitted: list[dict[str, Any]],
) -> None:
    """微信通道 sent → INVITATION_SENT 事件（含 coupon_code 与 _fen 金额）。"""
    reservation_id = uuid.uuid4()
    record = await service.create_invitation(
        tenant_id=TENANT_A,
        reservation_id=reservation_id,
        channel=InvitationChannel.WECHAT,
        coupon_code="W100",
        coupon_value_fen=10000,
    )
    await service.mark_sent(
        invitation_id=record.invitation_id, tenant_id=TENANT_A
    )

    assert len(emitted) == 1
    ev = emitted[0]
    assert ev["event_type"] == R2ReservationEventType.INVITATION_SENT
    assert ev["tenant_id"] == TENANT_A
    assert ev["stream_id"] == str(reservation_id)
    assert ev["payload"]["channel"] == "wechat"
    assert ev["payload"]["coupon_value_fen"] == 10000
    assert ev["payload"]["coupon_code"] == "W100"
    assert ev["source_service"] == "tx-trade"


@pytest.mark.asyncio
async def test_mark_sent_call_channel_emits_confirm_call_sent(
    service: ReservationInvitationService,
    emitted: list[dict[str, Any]],
) -> None:
    """外呼通道 sent → CONFIRM_CALL_SENT 事件（T-2h 核餐场景）。"""
    reservation_id = uuid.uuid4()
    record = await service.create_invitation(
        tenant_id=TENANT_A,
        reservation_id=reservation_id,
        channel=InvitationChannel.CALL,
        payload={"call_script_id": "confirm_arrival_v1"},
    )
    await service.mark_sent(
        invitation_id=record.invitation_id, tenant_id=TENANT_A
    )
    assert len(emitted) == 1
    assert emitted[0]["event_type"] == R2ReservationEventType.CONFIRM_CALL_SENT


# ─────────────────────────────────────────────────────────────────────────
# T2. 状态跃迁 — 合规性
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_confirmed_from_sent_emits_confirmed_event(
    service: ReservationInvitationService,
    emitted: list[dict[str, Any]],
) -> None:
    """客户回复确认到店 → CONFIRMED 事件，confirm_channel 正确。"""
    reservation_id = uuid.uuid4()
    record = await service.create_invitation(
        tenant_id=TENANT_A,
        reservation_id=reservation_id,
        channel=InvitationChannel.SMS,
    )
    await service.mark_sent(
        invitation_id=record.invitation_id, tenant_id=TENANT_A
    )
    emitted.clear()  # 清掉 INVITATION_SENT
    await service.mark_confirmed(
        invitation_id=record.invitation_id, tenant_id=TENANT_A
    )
    assert len(emitted) == 1
    ev = emitted[0]
    assert ev["event_type"] == R2ReservationEventType.CONFIRMED
    assert ev["payload"]["confirm_channel"] == "sms"
    assert ev["payload"]["reservation_id"] == str(reservation_id)


@pytest.mark.asyncio
async def test_invalid_transition_pending_to_confirmed_raises(
    service: ReservationInvitationService,
) -> None:
    """跳过 sent 直接 confirmed 应抛异常（保证先发后确认）。"""
    record = await service.create_invitation(
        tenant_id=TENANT_A,
        reservation_id=uuid.uuid4(),
        channel=InvitationChannel.SMS,
    )
    with pytest.raises(InvalidInvitationTransitionError):
        await service.mark_confirmed(
            invitation_id=record.invitation_id, tenant_id=TENANT_A
        )


@pytest.mark.asyncio
async def test_mark_failed_stores_reason_no_event(
    service: ReservationInvitationService,
    emitted: list[dict[str, Any]],
) -> None:
    """失败记录原因，不发业务事件（减少噪声）。"""
    record = await service.create_invitation(
        tenant_id=TENANT_A,
        reservation_id=uuid.uuid4(),
        channel=InvitationChannel.SMS,
    )
    updated = await service.mark_failed(
        invitation_id=record.invitation_id,
        tenant_id=TENANT_A,
        failure_reason="运营商返回 UNDELIVERABLE",
    )
    assert updated.status == InvitationStatus.FAILED
    assert "UNDELIVERABLE" in (updated.failure_reason or "")
    assert emitted == []


# ─────────────────────────────────────────────────────────────────────────
# T3. 幂等查询 + 租户隔离
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_by_reservation_returns_all_channels(
    service: ReservationInvitationService,
) -> None:
    """同一预订双通道（sms + wechat）查询应返回 2 条。"""
    reservation_id = uuid.uuid4()
    await service.create_invitation(
        tenant_id=TENANT_A,
        reservation_id=reservation_id,
        channel=InvitationChannel.SMS,
    )
    await service.create_invitation(
        tenant_id=TENANT_A,
        reservation_id=reservation_id,
        channel=InvitationChannel.WECHAT,
    )
    items = await service.list_by_reservation(
        tenant_id=TENANT_A, reservation_id=reservation_id
    )
    assert len(items) == 2
    channels = {i.channel for i in items}
    assert channels == {InvitationChannel.SMS, InvitationChannel.WECHAT}


@pytest.mark.asyncio
async def test_rls_cross_tenant_invitation_isolation(
    repo: InMemoryInvitationRepository,
) -> None:
    """A 租户不能读到 B 租户的邀请，即使 invitation_id 相同查询（不可能，但 tenant 不匹配即 None）。"""

    async def _fake_emit(**kwargs: Any) -> str:
        return str(uuid.uuid4())

    svc_a = ReservationInvitationService(repo=repo, emit_event=_fake_emit)
    svc_b = ReservationInvitationService(repo=repo, emit_event=_fake_emit)

    reservation_id = uuid.uuid4()
    record_a = await svc_a.create_invitation(
        tenant_id=TENANT_A,
        reservation_id=reservation_id,
        channel=InvitationChannel.SMS,
    )
    # B 租户拿 A 的 invitation_id 查 → 应该 not found
    with pytest.raises(InvitationNotFoundError):
        await svc_b.get(invitation_id=record_a.invitation_id, tenant_id=TENANT_B)

    # B 租户 list 同一个 reservation_id → 返回空
    items = await svc_b.list_by_reservation(
        tenant_id=TENANT_B, reservation_id=reservation_id
    )
    assert items == []


# ─────────────────────────────────────────────────────────────────────────
# T4. 时间戳 & 校验
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_sent_uses_provided_timestamp(
    service: ReservationInvitationService,
    emitted: list[dict[str, Any]],
) -> None:
    """mark_sent 提供显式 sent_at 时应使用外部传入值（避免时钟漂移）。"""
    reservation_id = uuid.uuid4()
    record = await service.create_invitation(
        tenant_id=TENANT_A,
        reservation_id=reservation_id,
        channel=InvitationChannel.CALL,
    )
    fixed_ts = datetime(2026, 4, 23, 18, 0, 0, tzinfo=timezone.utc)
    updated = await service.mark_sent(
        invitation_id=record.invitation_id,
        tenant_id=TENANT_A,
        sent_at=fixed_ts,
    )
    assert updated.sent_at == fixed_ts
    assert emitted[0]["payload"]["sent_at"] == fixed_ts.isoformat()


@pytest.mark.asyncio
async def test_negative_coupon_value_rejected(
    service: ReservationInvitationService,
) -> None:
    """券面值负数应被拒绝（与金额 _fen 约定一致）。"""
    with pytest.raises(ValueError, match="coupon_value_fen"):
        await service.create_invitation(
            tenant_id=TENANT_A,
            reservation_id=uuid.uuid4(),
            channel=InvitationChannel.SMS,
            coupon_value_fen=-1,
        )
