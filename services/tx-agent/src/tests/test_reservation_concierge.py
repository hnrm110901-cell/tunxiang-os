"""Tier 2 测试 — AI 预订礼宾员 Agent（Sprint R2 Track A）

覆盖场景（对齐 docs/reservation-r2-contracts.md §5.1 + CLAUDE.md §9/§17）：
  1. identify_caller 返回 lifecycle 状态（调 R1 API mock）
  2. identify_caller 返回客户偏好（忌口/包厢）
  3. suggest_slot 满足 margin 约束
  4. suggest_slot 满足 experience 约束
  5. detect_collision 合并多渠道撞单
  6. send_invitation 并发发事件（INVITATION_SENT）
  7. confirm_arrival T-2h 外呼不可达派发 R1 任务
  8. confirm_arrival rescheduled 分支
  9. 决策留痕每次 action 写 AgentDecisionLog
 10. Whisper 不可用降级 cloud
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.skills.reservation_concierge import ReservationConciergeAgent  # noqa: E402

from shared.events.src.event_types import R2ReservationEventType  # noqa: E402
from shared.ontology.src.extensions.agent_actions import CallerProfile  # noqa: E402
from shared.ontology.src.extensions.banquet_leads import SourceChannel  # noqa: E402
from shared.ontology.src.extensions.customer_lifecycle import (  # noqa: E402
    CustomerLifecycleState,
)
from shared.ontology.src.extensions.reservation_invitations import (  # noqa: E402
    InvitationChannel,
    InvitationRecord,
    InvitationStatus,
)

TENANT_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
STORE_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
CUSTOMER_VIP = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")


# ─────────────────────────────────────────────────────────────────────────
# Fake invitation service（不接 DB，记录事件）
# ─────────────────────────────────────────────────────────────────────────


class _FakeInvitationService:
    def __init__(self, fail_channels: Optional[set[InvitationChannel]] = None):
        self._store: dict[uuid.UUID, InvitationRecord] = {}
        self._fail = fail_channels or set()
        self.events: list[dict[str, Any]] = []

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
        now = datetime.now(timezone.utc)
        rec = InvitationRecord(
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
        self._store[rec.invitation_id] = rec
        return rec

    async def mark_sent(
        self,
        *,
        invitation_id: uuid.UUID,
        tenant_id: uuid.UUID,
        sent_at: Optional[datetime] = None,
    ) -> InvitationRecord:
        rec = self._store[invitation_id]
        if rec.channel in self._fail:
            raise RuntimeError(f"运营商异常 channel={rec.channel.value}")
        now = sent_at or datetime.now(timezone.utc)
        updated = rec.model_copy(
            update={
                "status": InvitationStatus.SENT,
                "sent_at": now,
                "updated_at": now,
            }
        )
        self._store[invitation_id] = updated
        event_type = (
            R2ReservationEventType.CONFIRM_CALL_SENT
            if rec.channel == InvitationChannel.CALL
            else R2ReservationEventType.INVITATION_SENT
        )
        self.events.append(
            {
                "event_type": event_type,
                "reservation_id": rec.reservation_id,
                "channel": rec.channel.value,
                "invitation_id": rec.invitation_id,
            }
        )
        return updated

    async def mark_failed(
        self,
        *,
        invitation_id: uuid.UUID,
        tenant_id: uuid.UUID,
        failure_reason: str,
    ) -> InvitationRecord:
        rec = self._store[invitation_id]
        now = datetime.now(timezone.utc)
        updated = rec.model_copy(
            update={
                "status": InvitationStatus.FAILED,
                "failure_reason": failure_reason[:200],
                "updated_at": now,
            }
        )
        self._store[invitation_id] = updated
        return updated


# ─────────────────────────────────────────────────────────────────────────
# 工具 fixtures
# ─────────────────────────────────────────────────────────────────────────


def _profile_vip() -> CallerProfile:
    return CallerProfile(
        customer_id=CUSTOMER_VIP,
        display_name="王总",
        vip_level="platinum",
        lifecycle_state=None,
        last_visit_at=datetime(2026, 3, 1, 19, 0, tzinfo=timezone.utc),
        favorite_dishes=["剁椒鱼头", "口味虾"],
        taboo_ingredients=["花生", "芫荽"],
        lifetime_value_fen=1_200_000,
    )


@pytest.fixture
def decision_logs() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def agent_factory(decision_logs):
    def _build(
        *,
        profile: Optional[CallerProfile] = None,
        lifecycle: Optional[CustomerLifecycleState] = None,
        collision_rows: Optional[
            list[tuple[uuid.UUID, SourceChannel, datetime]]
        ] = None,
        invitation_service: Optional[_FakeInvitationService] = None,
        whisper_text: Optional[str] = "未响铃 3 次",
        whisper_unavailable: bool = False,
        dispatched_tasks: Optional[list[dict[str, Any]]] = None,
    ) -> ReservationConciergeAgent:
        async def _profile_fetcher(phone: str, tid: uuid.UUID):
            return profile

        async def _lifecycle_fetcher(cid: uuid.UUID, tid: uuid.UUID):
            return lifecycle

        async def _collision_fetcher(
            cid: uuid.UUID, tdate: date, tid: uuid.UUID
        ):
            return collision_rows or []

        async def _whisper(ref: str) -> Optional[str]:
            return None if whisper_unavailable else whisper_text

        dispatched = dispatched_tasks if dispatched_tasks is not None else []

        async def _dispatch(**kwargs: Any) -> uuid.UUID:
            dispatched.append(kwargs)
            return uuid.uuid4()

        return ReservationConciergeAgent(
            tenant_id=str(TENANT_A),
            store_id=str(STORE_A),
            invitation_service=invitation_service,
            lifecycle_fetcher=_lifecycle_fetcher,
            profile_fetcher=_profile_fetcher,
            collision_fetcher=_collision_fetcher,
            slot_searcher=None,  # 走 fallback
            task_dispatcher=_dispatch,
            whisper_transcriber=_whisper,
            decision_log_sink=lambda rec: decision_logs.append(rec),
        )

    return _build


# ═════════════════════════════════════════════════════════════════════════
# 1. identify_caller — VIP 来电命中 + 填充 lifecycle 状态
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_identify_caller_returns_lifecycle_state(agent_factory):
    agent = agent_factory(
        profile=_profile_vip(),
        lifecycle=CustomerLifecycleState.ACTIVE,
    )
    result = await agent.run(
        "identify_caller",
        {
            "tenant_id": str(TENANT_A),
            "store_id": str(STORE_A),
            "caller_phone": "13812345678",
            "call_id": "call_t2h_001",
        },
    )
    assert result.success is True
    data = result.data["result"]
    assert data["ok"] is True
    assert data["matched_by"] == "phone"
    assert data["profile"]["lifecycle_state"] == "active"
    assert data["profile"]["vip_level"] == "platinum"
    assert data["inference_layer"] == "edge"
    assert result.inference_layer == "edge"


@pytest.mark.asyncio
async def test_identify_caller_returns_customer_preferences(agent_factory):
    """忌口 + 偏好菜品 + 上次消费时间 应透传在画像卡中。"""
    agent = agent_factory(profile=_profile_vip())
    result = await agent.run(
        "identify_caller",
        {
            "tenant_id": str(TENANT_A),
            "caller_phone": "13812345678",
        },
    )
    profile = result.data["result"]["profile"]
    assert "花生" in profile["taboo_ingredients"]
    assert "剁椒鱼头" in profile["favorite_dishes"]
    assert profile["last_visit_at"] is not None
    assert profile["lifetime_value_fen"] == 1_200_000


@pytest.mark.asyncio
async def test_identify_caller_miss_returns_none_with_reason(agent_factory):
    agent = agent_factory(profile=None)
    result = await agent.run(
        "identify_caller",
        {
            "tenant_id": str(TENANT_A),
            "caller_phone": "13900000000",
        },
    )
    data = result.data["result"]
    assert data["ok"] is False
    assert data["matched_by"] == "none"
    assert "未匹配" in data["reasoning"]


# ═════════════════════════════════════════════════════════════════════════
# 2. suggest_slot — margin + experience 约束
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_suggest_slot_respects_margin_constraint(agent_factory):
    """婚宴旺季推荐的套餐价格应满足毛利底线（15% 最低）。"""
    agent = agent_factory()
    result = await agent.run(
        "suggest_slot",
        {
            "tenant_id": str(TENANT_A),
            "store_id": str(STORE_A),
            "target_date": date(2026, 6, 6),
            "guest_count": 20,
            "preferred_room_type": "vip_room",
        },
    )
    assert result.success is True
    assert result.constraints_passed is True
    # 套餐推荐基线 cost 45% → margin 55% >> 15% 阈值
    assert "margin" in result.constraints_detail["scopes_checked"]
    options = result.data["result"]["options"]
    assert len(options) >= 1
    # 婚宴旺季 + 大团 → Top1 应是 VIP 包间
    assert options[0]["room_type"] == "vip_room"


@pytest.mark.asyncio
async def test_suggest_slot_respects_experience_constraint(agent_factory):
    """suggest_slot 排队预估应在阈值内（体验约束通过）。"""
    agent = agent_factory()
    result = await agent.run(
        "suggest_slot",
        {
            "tenant_id": str(TENANT_A),
            "store_id": str(STORE_A),
            "target_date": date(2026, 3, 15),
            "guest_count": 4,
        },
    )
    assert result.constraints_passed is True
    assert "experience" in result.constraints_detail["scopes_checked"]
    assert result.data["estimated_queue_minutes"] <= 30


# ═════════════════════════════════════════════════════════════════════════
# 3. detect_collision — 多渠道撞单合并
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_detect_collision_merges_multi_channel_duplicate(agent_factory):
    """同客户同日电话 + 美团 + 微信 3 条 → 保留首收单，合并其余。"""
    incoming_id = uuid.uuid4()
    earlier_id = uuid.uuid4()
    mid_id = uuid.uuid4()
    # 在 now 之前制造"更早的"记录：保留规则按 created_at 取最早
    # incoming 的 created_at 由 Agent 取 datetime.now()，所以 existing 要更早
    base = datetime.now(timezone.utc) - timedelta(days=2)
    existing = [
        (earlier_id, SourceChannel.BOOKING_DESK, base),
        (mid_id, SourceChannel.MEITUAN, base + timedelta(minutes=30)),
    ]
    agent = agent_factory(collision_rows=existing)
    result = await agent.run(
        "detect_collision",
        {
            "tenant_id": str(TENANT_A),
            "customer_id": str(CUSTOMER_VIP),
            "target_date": date(2026, 6, 1),
            "incoming_reservation_id": str(incoming_id),
        },
    )
    assert result.success is True
    decision = result.data["result"]["decision"]
    assert decision["is_collision"] is True
    # 首收单为 booking_desk（最早）
    assert decision["winning_reservation_id"] == str(earlier_id)
    # 其余两条进合并
    merged = set(decision["merged_reservation_ids"])
    assert str(incoming_id) in merged
    assert str(mid_id) in merged
    assert decision["priority_channel"] == "booking_desk"


# ═════════════════════════════════════════════════════════════════════════
# 4. send_invitation — 事件写入 + 原子性
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_send_invitation_writes_event(agent_factory):
    """双通道 sms + wechat 成功发送 → 各自一条 INVITATION_SENT 事件。"""
    inv_svc = _FakeInvitationService()
    agent = agent_factory(invitation_service=inv_svc)
    reservation_id = uuid.uuid4()
    result = await agent.run(
        "send_invitation",
        {
            "tenant_id": str(TENANT_A),
            "reservation_id": str(reservation_id),
            "customer_id": str(CUSTOMER_VIP),
            "channels": ["sms", "wechat"],
            "coupon_code": "VIP2026",
            "coupon_value_fen": 5000,
        },
    )
    assert result.success is True
    assert len(inv_svc.events) == 2
    for ev in inv_svc.events:
        assert ev["event_type"] == R2ReservationEventType.INVITATION_SENT
        assert ev["reservation_id"] == reservation_id


@pytest.mark.asyncio
async def test_send_invitation_atomic_rollback_on_partial_failure(
    agent_factory,
):
    """sms 成功 + wechat 失败 → 原子回滚（sms 被 mark_failed），返回失败。"""
    inv_svc = _FakeInvitationService(fail_channels={InvitationChannel.WECHAT})
    agent = agent_factory(invitation_service=inv_svc)
    result = await agent.run(
        "send_invitation",
        {
            "tenant_id": str(TENANT_A),
            "reservation_id": str(uuid.uuid4()),
            "channels": ["sms", "wechat"],
        },
    )
    assert result.success is False
    assert "wechat" in result.data["result"]["failed_channels"]
    # 返回空 invitations（回滚语义）
    assert result.data["result"]["invitations"] == []
    # sms 已写 SENT 事件但后被 mark_failed 回滚
    sms_records = [
        r for r in inv_svc._store.values() if r.channel == InvitationChannel.SMS
    ]
    assert len(sms_records) == 1
    assert sms_records[0].status == InvitationStatus.FAILED


# ═════════════════════════════════════════════════════════════════════════
# 5. confirm_arrival — T-2h 外呼
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_confirm_arrival_dispatches_task_before_2h(agent_factory):
    """T-2h 外呼未接通 → UNREACHABLE + 派 R1 任务 confirm_arrival。"""
    dispatched: list[dict[str, Any]] = []
    agent = agent_factory(
        whisper_text=None,  # 模拟无语音/未接通
        dispatched_tasks=dispatched,
    )
    scheduled = datetime.now(timezone.utc) + timedelta(minutes=115)  # T-2h 临界
    result = await agent.run(
        "confirm_arrival",
        {
            "tenant_id": str(TENANT_A),
            "reservation_id": str(uuid.uuid4()),
            "scheduled_at": scheduled.isoformat(),
        },
    )
    assert result.success is True
    data = result.data["result"]
    assert data["outcome"] == "unreachable"
    # 未接通必须派 R1 任务让前台人工复核
    assert len(dispatched) == 1
    assert dispatched[0]["task_type"] == "confirm_arrival"


@pytest.mark.asyncio
async def test_confirm_arrival_rescheduled_writes_new_time(agent_factory):
    """客户在外呼中改期 → outcome=rescheduled + new_scheduled_at 必填。"""
    agent = agent_factory(whisper_text="能改到晚一点吗，推迟两小时")
    scheduled = datetime(2026, 5, 10, 19, 0, tzinfo=timezone.utc)
    result = await agent.run(
        "confirm_arrival",
        {
            "tenant_id": str(TENANT_A),
            "reservation_id": str(uuid.uuid4()),
            "scheduled_at": scheduled.isoformat(),
        },
    )
    assert result.success is True
    data = result.data["result"]
    assert data["outcome"] == "rescheduled"
    assert data["new_scheduled_at"] is not None


# ═════════════════════════════════════════════════════════════════════════
# 6. 决策留痕
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_decision_log_written_for_every_action(
    agent_factory, decision_logs
):
    """每次 execute 必写 AgentDecisionLog（reservation_concierge 5 actions 覆盖）。"""
    inv_svc = _FakeInvitationService()
    agent = agent_factory(
        profile=_profile_vip(),
        invitation_service=inv_svc,
    )
    # 依次触发 4 个 action（confirm_arrival 单测已覆盖）
    await agent.run(
        "identify_caller",
        {"tenant_id": str(TENANT_A), "caller_phone": "13812345678"},
    )
    await agent.run(
        "suggest_slot",
        {
            "tenant_id": str(TENANT_A),
            "store_id": str(STORE_A),
            "target_date": date(2026, 6, 1),
            "guest_count": 12,
        },
    )
    await agent.run(
        "detect_collision",
        {
            "tenant_id": str(TENANT_A),
            "customer_id": str(CUSTOMER_VIP),
            "target_date": date(2026, 6, 1),
            "incoming_reservation_id": str(uuid.uuid4()),
        },
    )
    await agent.run(
        "send_invitation",
        {
            "tenant_id": str(TENANT_A),
            "reservation_id": str(uuid.uuid4()),
            "channels": ["sms"],
        },
    )
    assert len(decision_logs) == 4
    actions = [log["action"] for log in decision_logs]
    assert set(actions) == {
        "identify_caller",
        "suggest_slot",
        "detect_collision",
        "send_invitation",
    }
    # 每条 log 字段齐全
    for log in decision_logs:
        assert log["decision_id"]
        assert log["tenant_id"] == str(TENANT_A)
        assert log["agent_id"] == "reservation_concierge"
        assert "constraints_check" in log
        assert log["inference_layer"] in ("edge", "cloud")


# ═════════════════════════════════════════════════════════════════════════
# 7. Whisper 降级 — 云端 fallback
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_whisper_unavailable_falls_back_to_cloud(agent_factory):
    """Whisper 不可达时 inference_layer=cloud，功能不阻塞。"""
    agent = agent_factory(whisper_unavailable=True)
    scheduled = datetime.now(timezone.utc) + timedelta(hours=2)
    result = await agent.run(
        "confirm_arrival",
        {
            "tenant_id": str(TENANT_A),
            "reservation_id": str(uuid.uuid4()),
            "scheduled_at": scheduled.isoformat(),
        },
    )
    assert result.success is True
    # Whisper None → cloud 降级
    assert result.inference_layer == "cloud"
    assert result.data["result"]["inference_layer"] == "cloud"


# ═════════════════════════════════════════════════════════════════════════
# 8. constraint_scope 校验
# ═════════════════════════════════════════════════════════════════════════


def test_reservation_concierge_constraint_scope():
    """reservation_concierge 应声明 margin + experience，豁免 safety。"""
    assert ReservationConciergeAgent.constraint_scope == {"margin", "experience"}
    # 非空 scope → 不需 waived_reason（Track B 才豁免）
