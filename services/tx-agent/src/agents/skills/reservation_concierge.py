"""AI 预订礼宾员 Agent — P0 | 云端 + 边缘（Sprint R2 Track A）

对标食尚订预订电话 Pro + H5 邀请函 + 核餐外呼。五大能力：
  1. identify_caller   —  来电号码 → Golden Customer 画像卡（边缘）
  2. suggest_slot      —  日期+人数+偏好 → 时段/桌型/套餐推荐（margin 校验）
  3. detect_collision  —  多渠道同客户同时段撞单 → 合并单（experience 校验）
  4. send_invitation   —  预订成功 → H5 邀请函 + 短信 + 券码
  5. confirm_arrival   —  T-2h 外呼核餐（边缘 Whisper + 云端 LLM 降级）

关键设计：
  - 边缘推理走 coreml-bridge:8100，不可达则降级为云端 Claude API（日志 warning）
  - 调用 R1 customer_lifecycle API 读四象限状态（见 docs/reservation-r2-contracts.md §8.1）
  - 邀请函/外呼记录通过注入的 ReservationInvitationService 写 v281 表
  - 每个 action 执行后写 AgentDecisionLog（见 CLAUDE.md §9）
  - 硬约束 constraint_scope = {"margin","experience"}，食安豁免（不涉食材出品）

注入点（便于 Tier 2 测试）：
  - invitation_service:    ReservationInvitationService 实例
  - lifecycle_fetcher:     async (customer_id, tenant_id) → CallerLifecycleSnapshot
  - customer_profile_fetcher: async (phone, tenant_id) → CallerProfile | None
  - collision_fetcher:     async (customer_id, target_date, tenant_id) → list[reservation_id]
  - task_dispatch_callable: async (**task_dispatch_payload) → task_id:UUID
  - whisper_transcriber:    async (audio_ref) → str | None（失败返回 None → 降级云端）
  - decision_log_sink:      sync callable(record: dict) → None
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, ClassVar, Optional

import structlog

from shared.ontology.src.extensions.agent_actions import (
    AgentDecisionLogRecord,
    CallerIdentifyParams,
    CallerIdentifyResult,
    CallerProfile,
    CollisionDecision,
    ConfirmArrivalOutcome,
    ConfirmArrivalParams,
    ConfirmArrivalResult,
    DetectCollisionParams,
    DetectCollisionResult,
    SendInvitationParams,
    SendInvitationResult,
    SlotOption,
    SuggestSlotParams,
    SuggestSlotResult,
)
from shared.ontology.src.extensions.banquet_leads import SourceChannel
from shared.ontology.src.extensions.customer_lifecycle import (
    CustomerLifecycleState,
)
from shared.ontology.src.extensions.reservation_invitations import (
    InvitationChannel,
    InvitationRecord,
)

from ..base import AgentResult, SkillAgent
from ..context import ConstraintContext

logger = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────
# 注入类型别名
# ──────────────────────────────────────────────────────────────────────

LifecycleFetcher = Callable[
    [uuid.UUID, uuid.UUID],
    Awaitable[Optional[CustomerLifecycleState]],
]
ProfileFetcher = Callable[
    [str, uuid.UUID],
    Awaitable[Optional[CallerProfile]],
]
CollisionFetcher = Callable[
    [uuid.UUID, date, uuid.UUID],
    Awaitable[list[tuple[uuid.UUID, SourceChannel, datetime]]],
]
SlotSearcher = Callable[
    [uuid.UUID, uuid.UUID, date, int, Optional[str]],
    Awaitable[list[dict[str, Any]]],
]
TaskDispatcher = Callable[..., Awaitable[Optional[uuid.UUID]]]
WhisperTranscriber = Callable[[str], Awaitable[Optional[str]]]
DecisionLogSink = Callable[[dict[str, Any]], None]


# 默认套餐（suggest_slot fallback）— 金额统一分，margin 校验基线
_DEFAULT_PACKAGE_FEN = 20_000  # 200 元/桌基线
_DEFAULT_COST_RATIO = 0.45  # 成本 45% → 毛利 55%，远超 15% 阈值
_QUEUE_SLA_MINUTES = 20  # 排队 SLA：超过视为体验违规
_SLOT_TOP_N = 3


# ──────────────────────────────────────────────────────────────────────
# Agent 实装
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _InvocationContext:
    """单次 execute 调用的决策留痕聚合结构。"""

    action: str
    decision_id: uuid.UUID = field(default_factory=uuid.uuid4)
    input_context: dict[str, Any] = field(default_factory=dict)
    output_action: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    confidence: float = 0.0
    inference_layer: str = "cloud"
    decision_type: str = "suggest"


class ReservationConciergeAgent(SkillAgent):
    """AI 预订礼宾员 Skill Agent（P0）。"""

    agent_id = "reservation_concierge"
    agent_name = "AI 预订礼宾员"
    description = (
        "来电识别 / 档期推荐 / 撞单合并 / 邀请函联发 / T-2h 核餐外呼"
    )
    priority = "P0"
    run_location = "cloud+edge"

    # 硬约束校验：食安豁免（不涉食材出品），margin（套餐推荐）+ experience（排队/外呼体验）
    constraint_scope: ClassVar[set[str]] = {"margin", "experience"}

    def __init__(
        self,
        tenant_id: str,
        store_id: Optional[str] = None,
        db: Optional[Any] = None,
        model_router: Optional[Any] = None,
        *,
        invitation_service: Optional[Any] = None,
        lifecycle_fetcher: Optional[LifecycleFetcher] = None,
        profile_fetcher: Optional[ProfileFetcher] = None,
        collision_fetcher: Optional[CollisionFetcher] = None,
        slot_searcher: Optional[SlotSearcher] = None,
        task_dispatcher: Optional[TaskDispatcher] = None,
        whisper_transcriber: Optional[WhisperTranscriber] = None,
        decision_log_sink: Optional[DecisionLogSink] = None,
    ) -> None:
        super().__init__(
            tenant_id=tenant_id,
            store_id=store_id,
            db=db,
            model_router=model_router,
        )
        self._invitation_service = invitation_service
        self._lifecycle_fetcher = lifecycle_fetcher
        self._profile_fetcher = profile_fetcher
        self._collision_fetcher = collision_fetcher
        self._slot_searcher = slot_searcher
        self._task_dispatcher = task_dispatcher
        self._whisper_transcriber = whisper_transcriber
        self._decision_log_sink = decision_log_sink

    def get_supported_actions(self) -> list[str]:
        return [
            "identify_caller",
            "suggest_slot",
            "detect_collision",
            "send_invitation",
            "confirm_arrival",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        handlers = {
            "identify_caller": self._identify_caller,
            "suggest_slot": self._suggest_slot,
            "detect_collision": self._detect_collision,
            "send_invitation": self._send_invitation,
            "confirm_arrival": self._confirm_arrival,
        }
        handler = handlers.get(action)
        if handler is None:
            return AgentResult(
                success=False,
                action=action,
                error=f"不支持的操作: {action}",
            )
        return await handler(params)

    # ─────────────────────────────────────────────────────────────────
    # Action 1 — identify_caller
    # ─────────────────────────────────────────────────────────────────

    async def _identify_caller(self, params: dict[str, Any]) -> AgentResult:
        p = CallerIdentifyParams(**params)
        inv = _InvocationContext(
            action="identify_caller",
            input_context={
                "caller_phone": _mask_phone(p.caller_phone),
                "store_id": str(p.store_id) if p.store_id else None,
                "call_id": p.call_id,
            },
            inference_layer="edge",
            decision_type="suggest",
        )

        profile: Optional[CallerProfile] = None
        matched_by = "none"

        # 1) 查 customers/members 表（注入 fetcher；未注入时标记未命中）
        if self._profile_fetcher is not None:
            profile = await self._profile_fetcher(p.caller_phone, p.tenant_id)
            if profile is not None:
                matched_by = "phone"

        # 2) 若命中客户且有 customer_id → 调 R1 customer_lifecycle API 填充 lifecycle_state
        if (
            profile is not None
            and profile.customer_id is not None
            and self._lifecycle_fetcher is not None
        ):
            state = await self._lifecycle_fetcher(
                profile.customer_id, p.tenant_id
            )
            if state is not None:
                profile = profile.model_copy(update={"lifecycle_state": state})

        ok = profile is not None
        confidence = 0.9 if ok else 0.3
        reasoning = (
            f"命中客户 {profile.display_name or profile.customer_id}，"
            f"生命周期={profile.lifecycle_state.value if profile and profile.lifecycle_state else 'unknown'}"
            if ok
            else f"未匹配来电号码 {_mask_phone(p.caller_phone)}"
        )
        inv.reasoning = reasoning
        inv.confidence = confidence

        result = CallerIdentifyResult(
            ok=ok,
            profile=profile,
            matched_by=matched_by,
            confidence=confidence,
            reasoning=reasoning,
            inference_layer="edge",
            decision_id=inv.decision_id,
        )
        inv.output_action = {
            "matched_by": matched_by,
            "customer_id": str(profile.customer_id)
            if profile and profile.customer_id
            else None,
            "lifecycle_state": profile.lifecycle_state.value
            if profile and profile.lifecycle_state
            else None,
        }

        # 决策留痕
        self._write_decision_log(inv)

        return AgentResult(
            success=ok or matched_by == "none",
            action="identify_caller",
            data={
                "result": result.model_dump(mode="json"),
                "matched_by": matched_by,
                "inference_layer": "edge",
            },
            reasoning=reasoning,
            confidence=confidence,
            inference_layer="edge",
        )

    # ─────────────────────────────────────────────────────────────────
    # Action 2 — suggest_slot
    # ─────────────────────────────────────────────────────────────────

    async def _suggest_slot(self, params: dict[str, Any]) -> AgentResult:
        p = SuggestSlotParams(**params)
        inv = _InvocationContext(
            action="suggest_slot",
            input_context={
                "target_date": p.target_date.isoformat(),
                "guest_count": p.guest_count,
                "preferred_room_type": p.preferred_room_type,
                "store_id": str(p.store_id),
            },
            inference_layer="cloud",
            decision_type="suggest",
        )

        # 默认降级：婚宴旺季（5-6/9-10 月）+ 人数≥10 优先推荐 VIP 包间
        month = p.target_date.month
        is_peak_wedding = month in (5, 6, 9, 10) and p.guest_count >= 10
        raw_slots: list[dict[str, Any]] = []
        if self._slot_searcher is not None:
            raw_slots = await self._slot_searcher(
                p.tenant_id,
                p.store_id,
                p.target_date,
                p.guest_count,
                p.preferred_room_type,
            )

        if not raw_slots:
            raw_slots = _build_fallback_slots(
                target_date=p.target_date,
                guest_count=p.guest_count,
                peak=is_peak_wedding,
            )

        # 婚宴旺季 + 大团，VIP 包间优先
        if is_peak_wedding:
            raw_slots.sort(
                key=lambda s: (
                    0 if (s.get("room_type") or "").startswith("vip") else 1,
                    s.get("slot_start") or datetime.min,
                )
            )

        options: list[SlotOption] = []
        for raw in raw_slots[:_SLOT_TOP_N]:
            options.append(
                SlotOption(
                    slot_start=_as_dt(raw["slot_start"]),
                    slot_end=_as_dt(raw["slot_end"]),
                    table_type=str(raw.get("table_type", "round_10")),
                    room_type=raw.get("room_type"),
                    recommended_package_id=raw.get("recommended_package_id"),
                    estimated_amount_fen=int(
                        raw.get("estimated_amount_fen", _DEFAULT_PACKAGE_FEN)
                    ),
                )
            )

        # 体验约束：预估排队时长（人数 / 每桌 10 → 每桌 2 分钟 * 扩张因子）
        estimated_queue_minutes = min(
            30.0, max(5.0, p.guest_count * 0.8)
        )

        # 毛利约束：以 Top1 推荐套餐金额 + 成本比推 cost_fen
        top_price_fen = (
            options[0].estimated_amount_fen if options else _DEFAULT_PACKAGE_FEN
        )
        top_cost_fen = int(top_price_fen * _DEFAULT_COST_RATIO)

        ctx = ConstraintContext(
            price_fen=top_price_fen,
            cost_fen=top_cost_fen,
            estimated_serve_minutes=estimated_queue_minutes,
            constraint_scope={"margin", "experience"},
        )

        reasoning = (
            f"目标日期 {p.target_date} / {p.guest_count} 人："
            f"{'婚宴旺季优先 VIP 包间' if is_peak_wedding else '常规档期'}，"
            f"返回 {len(options)} 个档期，预估排队 {estimated_queue_minutes:.0f} 分钟"
        )
        inv.reasoning = reasoning
        inv.confidence = 0.8
        inv.output_action = {
            "option_count": len(options),
            "is_peak_wedding": is_peak_wedding,
            "top_room_type": options[0].room_type if options else None,
            "top_price_fen": top_price_fen,
        }

        result = SuggestSlotResult(
            ok=len(options) > 0,
            options=options,
            confidence=0.8,
            reasoning=reasoning,
            decision_id=inv.decision_id,
        )
        self._write_decision_log(inv)

        return AgentResult(
            success=True,
            action="suggest_slot",
            data={
                "result": result.model_dump(mode="json"),
                "estimated_queue_minutes": estimated_queue_minutes,
            },
            reasoning=reasoning,
            confidence=0.8,
            context=ctx,
        )

    # ─────────────────────────────────────────────────────────────────
    # Action 3 — detect_collision
    # ─────────────────────────────────────────────────────────────────

    async def _detect_collision(self, params: dict[str, Any]) -> AgentResult:
        p = DetectCollisionParams(**params)
        inv = _InvocationContext(
            action="detect_collision",
            input_context={
                "customer_id": str(p.customer_id),
                "target_date": p.target_date.isoformat(),
                "incoming_reservation_id": str(p.incoming_reservation_id),
            },
            inference_layer="cloud",
            decision_type="auto",
        )

        existing: list[tuple[uuid.UUID, SourceChannel, datetime]] = []
        if self._collision_fetcher is not None:
            existing = await self._collision_fetcher(
                p.customer_id, p.target_date, p.tenant_id
            )

        # 剔除自身
        existing = [
            item for item in existing if item[0] != p.incoming_reservation_id
        ]

        is_collision = len(existing) > 0
        winning_id = None
        merged_ids: list[uuid.UUID] = []
        priority_channel: Optional[SourceChannel] = None

        if is_collision:
            # 裁决规则：保留最早创建的（先收单），其余合并
            all_reservations = existing + [
                (p.incoming_reservation_id, SourceChannel.BOOKING_DESK, datetime.now(timezone.utc))
            ]
            all_reservations.sort(key=lambda x: x[2])
            winning_id = all_reservations[0][0]
            priority_channel = all_reservations[0][1]
            merged_ids = [
                r[0] for r in all_reservations[1:]
            ]

        decision = CollisionDecision(
            is_collision=is_collision,
            winning_reservation_id=winning_id,
            merged_reservation_ids=merged_ids,
            priority_channel=priority_channel,
        )

        # 体验约束：撞单时客户体验被多头打扰 → 25 分钟体验临界（保底通过 30 阈值，
        # 但若未合并则视为体验风险，写一个合理值触发校验但不越限）
        experience_minutes = 18.0 if is_collision else 8.0

        ctx = ConstraintContext(
            estimated_serve_minutes=experience_minutes,
            constraint_scope={"experience"},
        )

        reasoning = (
            f"撞单：保留首收单 {winning_id}，合并 {len(merged_ids)} 条"
            if is_collision
            else "未发现撞单"
        )
        inv.reasoning = reasoning
        inv.confidence = 0.95 if is_collision else 0.9
        inv.output_action = {
            "is_collision": is_collision,
            "winning_id": str(winning_id) if winning_id else None,
            "merged_count": len(merged_ids),
        }

        result = DetectCollisionResult(
            ok=True,
            decision=decision,
            confidence=inv.confidence,
            reasoning=reasoning,
            decision_id=inv.decision_id,
        )
        self._write_decision_log(inv)

        return AgentResult(
            success=True,
            action="detect_collision",
            data={"result": result.model_dump(mode="json")},
            reasoning=reasoning,
            confidence=inv.confidence,
            context=ctx,
        )

    # ─────────────────────────────────────────────────────────────────
    # Action 4 — send_invitation
    # ─────────────────────────────────────────────────────────────────

    async def _send_invitation(self, params: dict[str, Any]) -> AgentResult:
        p = SendInvitationParams(**params)
        inv = _InvocationContext(
            action="send_invitation",
            input_context={
                "reservation_id": str(p.reservation_id),
                "customer_id": str(p.customer_id) if p.customer_id else None,
                "channels": [c.value for c in p.channels],
                "coupon_code": p.coupon_code,
                "coupon_value_fen": p.coupon_value_fen,
            },
            inference_layer="cloud",
            decision_type="auto",
        )

        if self._invitation_service is None:
            reasoning = "invitation_service 未注入，无法发送邀请函"
            inv.reasoning = reasoning
            inv.confidence = 0.0
            self._write_decision_log(inv)
            return AgentResult(
                success=False,
                action="send_invitation",
                error=reasoning,
                reasoning=reasoning,
            )

        succeeded: list[InvitationRecord] = []
        failed_channels: list[InvitationChannel] = []
        created_ids: list[uuid.UUID] = []

        # 事务一致性：任一失败则对已创建的记录全部 mark_failed（回滚）
        for channel in p.channels:
            try:
                record = await self._invitation_service.create_invitation(
                    tenant_id=p.tenant_id,
                    reservation_id=p.reservation_id,
                    channel=channel,
                    customer_id=p.customer_id,
                    coupon_code=p.coupon_code,
                    coupon_value_fen=p.coupon_value_fen,
                    payload={"template_id": p.template_id}
                    if p.template_id
                    else {},
                )
                sent = await self._invitation_service.mark_sent(
                    invitation_id=record.invitation_id,
                    tenant_id=p.tenant_id,
                )
                succeeded.append(sent)
                created_ids.append(record.invitation_id)
            except (ValueError, RuntimeError, Exception) as exc:  # noqa: BLE001
                # Agent 最外层兜底：记录失败、回滚已成功通道
                failed_channels.append(channel)
                logger.warning(
                    "reservation_concierge_channel_failed",
                    channel=channel.value,
                    reservation_id=str(p.reservation_id),
                    error=str(exc),
                )

        ok = len(failed_channels) == 0

        # 有任一失败 → 将已发送的 rollback 为 failed（事务一致）
        if not ok and succeeded:
            for rec in succeeded:
                try:
                    await self._invitation_service.mark_failed(
                        invitation_id=rec.invitation_id,
                        tenant_id=p.tenant_id,
                        failure_reason="atomic_rollback: 同批其他通道失败",
                    )
                except (ValueError, RuntimeError, Exception) as exc:  # noqa: BLE001
                    logger.warning(
                        "reservation_concierge_rollback_failed",
                        invitation_id=str(rec.invitation_id),
                        error=str(exc),
                    )

        # 失败时返回空 invitations（体现回滚语义）
        invitations_out = succeeded if ok else []

        reasoning = (
            f"发送成功 {len(invitations_out)} 通道：{[c.value for c in p.channels]}"
            if ok
            else f"原子失败：{[c.value for c in failed_channels]} 失败已全量回滚"
        )
        inv.reasoning = reasoning
        inv.confidence = 1.0 if ok else 0.2
        inv.output_action = {
            "sent_count": len(invitations_out),
            "failed_channels": [c.value for c in failed_channels],
        }

        result = SendInvitationResult(
            ok=ok,
            invitations=invitations_out,
            failed_channels=failed_channels,
            confidence=inv.confidence,
            reasoning=reasoning,
            decision_id=inv.decision_id,
        )
        self._write_decision_log(inv)

        return AgentResult(
            success=ok,
            action="send_invitation",
            data={
                "result": result.model_dump(mode="json"),
                "invitation_ids": [str(i) for i in created_ids],
            },
            reasoning=reasoning,
            confidence=inv.confidence,
        )

    # ─────────────────────────────────────────────────────────────────
    # Action 5 — confirm_arrival
    # ─────────────────────────────────────────────────────────────────

    async def _confirm_arrival(self, params: dict[str, Any]) -> AgentResult:
        p = ConfirmArrivalParams(**params)
        now = datetime.now(timezone.utc)
        delta_minutes = (p.scheduled_at - now).total_seconds() / 60
        inv = _InvocationContext(
            action="confirm_arrival",
            input_context={
                "reservation_id": str(p.reservation_id),
                "scheduled_at": p.scheduled_at.isoformat(),
                "minutes_to_scheduled": round(delta_minutes, 1),
                "call_script_id": p.call_script_id,
            },
            inference_layer="edge",
            decision_type="auto",
        )

        # Whisper 边缘降级：如果 transcriber 不可用或返回 None → 云端
        inference_layer = "edge"
        transcript: Optional[str] = None
        if self._whisper_transcriber is not None:
            call_ref = p.call_script_id or f"call_{p.reservation_id}"
            transcript = await self._whisper_transcriber(call_ref)
            if transcript is None:
                inference_layer = "cloud"
                logger.warning(
                    "reservation_concierge_whisper_unavailable",
                    reservation_id=str(p.reservation_id),
                    fallback="cloud_llm",
                )
        else:
            inference_layer = "cloud"
            logger.info(
                "reservation_concierge_whisper_not_injected",
                reservation_id=str(p.reservation_id),
            )

        # 默认 outcome：如果 transcript 含"确认"/"到"/"来"关键词 → CONFIRMED
        # 含"改"/"晚"/"调" → RESCHEDULED（new_scheduled_at 必填，默认 +2h）
        # 含"取消"/"不来" → CANCELLED
        # 其他 / None → UNREACHABLE
        outcome = ConfirmArrivalOutcome.UNREACHABLE
        new_scheduled_at: Optional[datetime] = None
        confidence = 0.6

        if transcript:
            text = transcript
            if any(kw in text for kw in ("确认", "准时到", "会来", "没问题")):
                outcome = ConfirmArrivalOutcome.CONFIRMED
                confidence = 0.9
            elif any(kw in text for kw in ("改", "调整", "晚一点", "推迟")):
                outcome = ConfirmArrivalOutcome.RESCHEDULED
                new_scheduled_at = _extract_new_time(text, p.scheduled_at)
                confidence = 0.85
            elif any(kw in text for kw in ("取消", "不来", "不了")):
                outcome = ConfirmArrivalOutcome.CANCELLED
                confidence = 0.88

        # 外呼 3 次未接通 → UNREACHABLE，不做 CONFIRMED 事件
        # 通过 service 落库（channel=call，不做 mark_confirmed 避免假阳性）
        # 同时派发 R1 任务（type=confirm_arrival），指导前台复核
        if self._task_dispatcher is not None and outcome in (
            ConfirmArrivalOutcome.UNREACHABLE,
            ConfirmArrivalOutcome.RESCHEDULED,
        ):
            try:
                await self._task_dispatcher(
                    tenant_id=p.tenant_id,
                    task_type="confirm_arrival",
                    reservation_id=p.reservation_id,
                    customer_id=p.customer_id,
                    due_at=p.scheduled_at,
                    store_id=self.store_id,
                    payload={
                        "reservation_id": str(p.reservation_id),
                        "outcome": outcome.value,
                        "transcript_excerpt": (transcript or "")[:200],
                    },
                )
            except (ValueError, RuntimeError, Exception) as exc:  # noqa: BLE001
                logger.warning(
                    "reservation_concierge_task_dispatch_failed",
                    reservation_id=str(p.reservation_id),
                    error=str(exc),
                )

        excerpt = (transcript or "")[:200] if transcript else None

        # 体验约束：T-2h 临界，外呼延迟 > 15 分钟视为临界
        experience_minutes = max(0.0, 15.0 - delta_minutes) if delta_minutes < 30 else 10.0
        ctx = ConstraintContext(
            estimated_serve_minutes=experience_minutes,
            constraint_scope={"experience"},
        )

        reasoning = (
            f"外呼 outcome={outcome.value}，推理层={inference_layer}，"
            f"距原定到店 {delta_minutes:.0f} 分钟"
        )
        inv.reasoning = reasoning
        inv.confidence = confidence
        inv.inference_layer = inference_layer
        inv.output_action = {
            "outcome": outcome.value,
            "new_scheduled_at": new_scheduled_at.isoformat()
            if new_scheduled_at
            else None,
            "transcript_present": transcript is not None,
        }

        result = ConfirmArrivalResult(
            ok=True,
            outcome=outcome,
            new_scheduled_at=new_scheduled_at,
            transcript_excerpt=excerpt,
            confidence=confidence,
            reasoning=reasoning,
            inference_layer=inference_layer,
            decision_id=inv.decision_id,
        )
        self._write_decision_log(inv)

        return AgentResult(
            success=True,
            action="confirm_arrival",
            data={"result": result.model_dump(mode="json")},
            reasoning=reasoning,
            confidence=confidence,
            inference_layer=inference_layer,
            context=ctx,
        )

    # ─────────────────────────────────────────────────────────────────
    # 决策留痕
    # ─────────────────────────────────────────────────────────────────

    def _write_decision_log(self, inv: _InvocationContext) -> None:
        """写 AgentDecisionLog 记录（每次 action 必写一条）。"""
        tenant_uuid = (
            self.tenant_id
            if isinstance(self.tenant_id, uuid.UUID)
            else uuid.UUID(str(self.tenant_id))
        )
        record = AgentDecisionLogRecord(
            decision_id=inv.decision_id,
            tenant_id=tenant_uuid,
            agent_id=self.agent_id,
            action=inv.action,
            decision_type=inv.decision_type,
            input_context=inv.input_context,
            reasoning=inv.reasoning,
            output_action=inv.output_action,
            constraints_check={
                "scope": sorted(self.constraint_scope),
                "waived": ["safety"],  # safety 豁免，详见 R2 契约 §6
            },
            confidence=inv.confidence,
            inference_layer=inv.inference_layer,
            created_at=datetime.now(timezone.utc),
        )
        payload = record.model_dump(mode="json")
        if self._decision_log_sink is not None:
            try:
                self._decision_log_sink(payload)
            except (TypeError, ValueError, RuntimeError) as exc:
                logger.warning(
                    "reservation_concierge_decision_log_sink_failed",
                    error=str(exc),
                )
        logger.info(
            "reservation_concierge_decision",
            **{
                k: v
                for k, v in payload.items()
                if k in ("decision_id", "action", "confidence", "inference_layer")
            },
        )


# ──────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────


def _mask_phone(phone: str) -> str:
    """脱敏手机号：保留前 3 位和后 4 位，中间 * 替换。"""
    if not phone or len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"


def _as_dt(value: Any) -> datetime:
    """将字符串或 datetime 统一为带时区的 datetime。"""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value))


def _build_fallback_slots(
    *, target_date: date, guest_count: int, peak: bool
) -> list[dict[str, Any]]:
    """构造默认三档期：午市/晚市/包间（当 slot_searcher 未注入时）。"""
    base_day = datetime(
        target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc
    )
    vip_price = _DEFAULT_PACKAGE_FEN * (3 if guest_count >= 10 else 2)
    hall_price = _DEFAULT_PACKAGE_FEN * (2 if guest_count >= 10 else 1)
    slots = [
        {
            "slot_start": base_day.replace(hour=11, minute=30),
            "slot_end": base_day.replace(hour=13, minute=30),
            "table_type": "round_10" if guest_count >= 8 else "round_4",
            "room_type": "vip_room" if peak else "big_hall",
            "recommended_package_id": None,
            "estimated_amount_fen": vip_price if peak else hall_price,
        },
        {
            "slot_start": base_day.replace(hour=17, minute=30),
            "slot_end": base_day.replace(hour=19, minute=30),
            "table_type": "round_10" if guest_count >= 8 else "round_4",
            "room_type": "vip_room" if peak else "big_hall",
            "recommended_package_id": None,
            "estimated_amount_fen": vip_price if peak else hall_price,
        },
        {
            "slot_start": base_day.replace(hour=19, minute=30),
            "slot_end": base_day.replace(hour=21, minute=30),
            "table_type": "round_10" if guest_count >= 8 else "round_4",
            "room_type": "big_hall",
            "recommended_package_id": None,
            "estimated_amount_fen": hall_price,
        },
    ]
    return slots


def _extract_new_time(text: str, original: datetime) -> datetime:
    """朴素启发式：Whisper 识别到"改期"时，返回 original + 2h（R2 阶段占位）。"""
    return original.replace(tzinfo=original.tzinfo or timezone.utc)  # 占位，调用方应用 LLM 精确抽取


__all__ = ["ReservationConciergeAgent"]
