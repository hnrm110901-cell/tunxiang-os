"""CustomerLifecycleFSM — 客户生命周期四象限状态机

四象限：
    no_order  — 尚未产生任何订单
    active    — 最近有消费（≤ dormant_threshold_days）
    dormant   — 超过 dormant_threshold_days 无消费但 < churn_threshold_days
    churned   — 超过 churn_threshold_days 无消费

转态规则（基于"最近消费距今天数 + 历史订单数"）：
    no_order   --首单-->   active
    active     --60d 无消费-->  dormant
    dormant    --180d 无消费--> churned
    dormant    --新订单-->     active   （唤醒）
    churned    --新订单-->     active   （挽回）
    active     --退款后无其他付费订单--> 回退到 previous_state（P0-1）

并发安全：
    transition() 使用 SELECT FOR UPDATE 行锁；同一 customer 的并发请求串行化。

幂等：
    同一 trigger_event_id 重复触发只写一次事件（基于 last_transition_event_id 校验）。

事件发射：
    每次真实状态变化（包括唤醒/挽回）写入 CustomerLifecycleEventType.STATE_CHANGED。
    对幂等短路（trigger_event_id 相同）不重复写事件。
    对"状态未变"的情况（例如已是 active 又触发 order.paid），不写事件。

    时序安全（P1 修复 — 独立审查报告 Q1 风险 2）：
    事件发射改为 `await emit_event(...)`（原先是 `asyncio.create_task(...)`），
    调用点在 repo.upsert_state 之后。由于 AsyncSession 在 repo 层是隐式事务，
    commit 由调用方（projector/API）统一处理，此处把发射放到写入之后保证
    "先完成内存状态改写再发事件"；若上层 session.commit() 失败，事件虽已发
    送也不至于误导下游（下游仍需幂等校验）。真正的 outbox 由统一事件总线的
    Phase 1 处理——FSM 这里做的是最小修复，避免 create_task 丢异常。

使用：
    fsm = CustomerLifecycleFSM(db, tenant_id)
    record = await fsm.transition(
        customer_id=cid,
        trigger_event_id=order_paid_event_id,
        now=occurred_at,
        order_count=5,
        last_order_at=occurred_at,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import CustomerLifecycleEventType
from shared.ontology.src.extensions.customer_lifecycle import (
    CustomerLifecycleRecord,
    CustomerLifecycleState,
)

try:
    # 运行态（tx-member 以 src/ 为 cwd 时）—— 绝对导入
    from repositories.customer_lifecycle_repo import CustomerLifecycleRepository
except ImportError:  # pragma: no cover
    # 包装态（作为 tunxiang_os.services.tx_member.src 导入）—— 相对导入兜底
    from ..repositories.customer_lifecycle_repo import CustomerLifecycleRepository  # type: ignore[no-redef]

logger = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────
# 默认阈值（契约 §7 注明门店可配置，R1 先硬编码）
# ──────────────────────────────────────────────────────────────────

DEFAULT_DORMANT_THRESHOLD_DAYS = 60
DEFAULT_CHURN_THRESHOLD_DAYS = 180


@dataclass(frozen=True)
class LifecycleThresholds:
    """生命周期时间阈值（天）"""

    dormant_after_days: int = DEFAULT_DORMANT_THRESHOLD_DAYS
    churn_after_days: int = DEFAULT_CHURN_THRESHOLD_DAYS


# ──────────────────────────────────────────────────────────────────
# 主类
# ──────────────────────────────────────────────────────────────────


class CustomerLifecycleFSM:
    """四象限状态机（纯函数 evaluate + DB 事务 transition）。"""

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: UUID | str,
        thresholds: LifecycleThresholds | None = None,
    ) -> None:
        self.db = db
        self.tenant_id = UUID(str(tenant_id))
        self.thresholds = thresholds or LifecycleThresholds()
        self.repo = CustomerLifecycleRepository(db, self.tenant_id)

    # ──────────────────────────────────────────────────────────────
    # 纯函数：评估目标状态
    # ──────────────────────────────────────────────────────────────

    def evaluate_state(
        self,
        *,
        now: datetime,
        last_order_at: datetime | None,
        order_count: int,
    ) -> CustomerLifecycleState:
        """根据"最近消费距今天数 + 历史订单数"评估当前应处状态。

        纯函数，不访问 DB。

        Args:
            now:           评估时刻
            last_order_at: 最近订单时间（None 表示从未消费）
            order_count:   历史订单总数

        Returns:
            目标状态（四象限之一）
        """
        if order_count <= 0 or last_order_at is None:
            return CustomerLifecycleState.NO_ORDER

        # 对齐时区：naive → assume UTC
        if last_order_at.tzinfo is None:
            last_order_at = last_order_at.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        age = now - last_order_at
        if age < timedelta(days=self.thresholds.dormant_after_days):
            return CustomerLifecycleState.ACTIVE
        if age < timedelta(days=self.thresholds.churn_after_days):
            return CustomerLifecycleState.DORMANT
        return CustomerLifecycleState.CHURNED

    # ──────────────────────────────────────────────────────────────
    # DB 事务：迁移状态
    # ──────────────────────────────────────────────────────────────

    async def transition(
        self,
        *,
        customer_id: UUID | str,
        trigger_event_id: UUID | str | None,
        now: datetime,
        last_order_at: datetime | None,
        order_count: int,
        reason: str | None = None,
    ) -> CustomerLifecycleRecord:
        """基于当前业务上下文评估并迁移状态。

        并发安全：内部使用 SELECT FOR UPDATE。
        幂等：同一 trigger_event_id 重复调用不重复写事件。

        Args:
            customer_id:      客户 UUID
            trigger_event_id: 触发本次迁移的事件 ID（通常是 order.paid 的 event_id）
            now:              业务时间
            last_order_at:    最近一次订单时间（含本次）
            order_count:      截至 now 的订单总数
            reason:           迁移原因（可选，写入 payload）

        Returns:
            最终 CustomerLifecycleRecord
        """
        cid = UUID(str(customer_id))
        trig = UUID(str(trigger_event_id)) if trigger_event_id else None

        # 统一时区
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        target_state = self.evaluate_state(
            now=now,
            last_order_at=last_order_at,
            order_count=order_count,
        )

        # 在 session 事务内完成：SELECT FOR UPDATE → 判断 → UPDATE
        # SQLAlchemy 的 AsyncSession 如果尚无事务，execute 会自动开启隐式事务
        current = await self.repo.get_for_update(cid)

        # 幂等短路：trigger_event_id 相同
        if (
            trig is not None
            and current is not None
            and current.last_transition_event_id == trig
        ):
            logger.info(
                "lifecycle_transition_idempotent_skip",
                tenant_id=str(self.tenant_id),
                customer_id=str(cid),
                trigger_event_id=str(trig),
                state=current.state.value,
            )
            return current

        previous_state: CustomerLifecycleState | None = (
            current.state if current is not None else None
        )

        # since_ts：真实迁移时取 now；状态未变时保留旧 since_ts
        if current is not None and current.state == target_state:
            since_ts = current.since_ts
        else:
            since_ts = now

        record = await self.repo.upsert_state(
            customer_id=cid,
            target_state=target_state,
            since_ts=since_ts,
            trigger_event_id=trig,
            previous_state=previous_state,
        )

        # 发事件：只在真实状态变化时发（previous != current）
        is_real_transition = (
            current is None and target_state != CustomerLifecycleState.NO_ORDER
        ) or (current is not None and current.state != target_state)

        if is_real_transition:
            payload: dict[str, Any] = {
                "customer_id": str(cid),
                "previous_state": previous_state.value if previous_state else None,
                "next_state": target_state.value,
                "since_ts": since_ts.isoformat(),
                "transition_count": record.transition_count,
            }
            if trig is not None:
                payload["trigger_event_id"] = str(trig)
            if reason:
                payload["reason"] = reason

            # P1 修复：从 asyncio.create_task 改为 await（commit-then-emit 时序对齐）。
            # 放在 repo.upsert_state 之后，调用方 session.commit() 之前：
            # - 事件发射失败 → 异常向上抛 → 调用方 rollback，不会产生"幽灵状态改写"
            # - 异步任务遗失异常的风险被消除
            # 参见：docs/sprint-r1-independent-review.md P1（Q1 风险 2）
            await emit_event(
                event_type=CustomerLifecycleEventType.STATE_CHANGED,
                tenant_id=self.tenant_id,
                stream_id=str(cid),
                payload=payload,
                source_service="tx-member",
                causation_id=trig,
            )

            logger.info(
                "lifecycle_state_changed",
                tenant_id=str(self.tenant_id),
                customer_id=str(cid),
                previous=previous_state.value if previous_state else None,
                next=target_state.value,
                trigger_event_id=str(trig) if trig else None,
                transition_count=record.transition_count,
            )

        return record

    # ──────────────────────────────────────────────────────────────
    # 辅助：日终重算（单客户）
    # ──────────────────────────────────────────────────────────────

    async def recompute_one(
        self,
        *,
        customer_id: UUID | str,
        now: datetime,
        last_order_at: datetime | None,
        order_count: int,
    ) -> CustomerLifecycleRecord:
        """日终重算入口（无 trigger_event_id，触发 reason=recompute）。"""
        return await self.transition(
            customer_id=customer_id,
            trigger_event_id=None,
            now=now,
            last_order_at=last_order_at,
            order_count=order_count,
            reason="daily_recompute",
        )

    # ──────────────────────────────────────────────────────────────
    # P0-1 修复：订单取消 / 退款触发的回退
    # ──────────────────────────────────────────────────────────────

    async def handle_order_reversal(
        self,
        *,
        customer_id: UUID | str,
        trigger_event_id: UUID | str | None,
        now: datetime,
        previous_paid_order_at: datetime | None,
        remaining_order_count: int,
        reversal_type: str,
    ) -> CustomerLifecycleRecord | None:
        """处理 order.cancelled / order.refunded：
        如果客户在窗口期内仍存在其他已付订单，保持当前状态不变（返回 None=未变）；
        否则把状态回退（按 remaining_order_count + previous_paid_order_at 重算
        到一个新的目标状态），并写一条 STATE_CHANGED 事件，reason=reversal_type。

        幂等：同一 trigger_event_id 重复触发不重复写事件（基于 last_transition_event_id）。

        时序守护：调用方（projector）已在入口做 occurred_at 单调性校验，
        本方法不再重复校验——只信任传入的 previous_paid_order_at 已经是
        "扣除本次被取消订单后"的最新付费订单时间。

        Args:
            customer_id:             客户 UUID
            trigger_event_id:        order.cancelled / order.refunded 事件 ID
            now:                     业务时间（通常是退款事件的 occurred_at）
            previous_paid_order_at:  扣除本次被取消订单后，客户最近一单付费时间
                                     （None = 再无其他已付订单）
            remaining_order_count:   扣除本次后剩余的已付订单总数（≥0）
            reversal_type:           "order_cancelled" / "order_refunded"

        Returns:
            若真实发生迁移返回新 record；若被幂等短路或状态未变则返回现状 record；
            若该客户从无状态记录（never had lifecycle row）→ 返回 None（不写空行）。
        """
        cid = UUID(str(customer_id))
        trig = UUID(str(trigger_event_id)) if trigger_event_id else None

        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        current = await self.repo.get_for_update(cid)

        # 该客户从来没有 lifecycle 记录（退款事件比 paid 事件先到或该客户无 paid
        # 记录）→ 不写任何行，直接返回。
        if current is None:
            logger.info(
                "lifecycle_reversal_skip_no_state",
                tenant_id=str(self.tenant_id),
                customer_id=str(cid),
                reversal_type=reversal_type,
            )
            return None

        # 幂等：同一 trigger_event_id 已处理
        if trig is not None and current.last_transition_event_id == trig:
            logger.info(
                "lifecycle_reversal_idempotent_skip",
                tenant_id=str(self.tenant_id),
                customer_id=str(cid),
                trigger_event_id=str(trig),
            )
            return current

        # 核心判断：若还有其他已付订单（previous_paid_order_at is not None
        # 且 remaining_order_count ≥ 1），重算状态 — 有可能仍在 active，不必改。
        target_state = self.evaluate_state(
            now=now,
            last_order_at=previous_paid_order_at,
            order_count=remaining_order_count,
        )

        # 状态未变 → 不写事件，仅 touch last_transition_event_id 保留审计链
        if current.state == target_state:
            # 更新 last_transition_event_id，让未来幂等短路起作用
            record = await self.repo.upsert_state(
                customer_id=cid,
                target_state=target_state,
                since_ts=current.since_ts,  # 保持旧起点
                trigger_event_id=trig,
                previous_state=current.previous_state,
            )
            logger.info(
                "lifecycle_reversal_no_state_change",
                tenant_id=str(self.tenant_id),
                customer_id=str(cid),
                state=current.state.value,
                reversal_type=reversal_type,
            )
            return record

        # 真实回退：状态发生变化
        record = await self.repo.upsert_state(
            customer_id=cid,
            target_state=target_state,
            since_ts=now,
            trigger_event_id=trig,
            previous_state=current.state,
        )

        payload: dict[str, Any] = {
            "customer_id": str(cid),
            "previous_state": current.state.value,
            "next_state": target_state.value,
            "since_ts": now.isoformat(),
            "transition_count": record.transition_count,
            "reason": reversal_type,
        }
        if trig is not None:
            payload["trigger_event_id"] = str(trig)

        # 同 transition()：commit-then-emit（commit 由上层负责；此处 await）
        await emit_event(
            event_type=CustomerLifecycleEventType.STATE_CHANGED,
            tenant_id=self.tenant_id,
            stream_id=str(cid),
            payload=payload,
            source_service="tx-member",
            causation_id=trig,
        )

        logger.info(
            "lifecycle_reversal_state_changed",
            tenant_id=str(self.tenant_id),
            customer_id=str(cid),
            previous=current.state.value,
            next=target_state.value,
            reversal_type=reversal_type,
            transition_count=record.transition_count,
        )
        return record
