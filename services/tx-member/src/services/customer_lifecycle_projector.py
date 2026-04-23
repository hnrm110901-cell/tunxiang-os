"""CustomerLifecycleProjector — 消费订单事件 → FSM 迁移 / 回退

消费的事件：
  order.paid       → 触发 CustomerLifecycleFSM.transition()
  order.cancelled  → 触发 CustomerLifecycleFSM.handle_order_reversal()（P0-1）
  order.refunded   → 触发 CustomerLifecycleFSM.handle_order_reversal()（P0-1）

注意：
- 本投影器不直接维护物化视图（mv_customer_lifecycle 归入 R2）。
- 每条 order.paid 事件都会驱动一次 FSM 迁移，FSM 自身幂等。
- 读取 customers.total_order_count 作为 order_count 近似（FSM 内部再校验）。

时序单调性（P1-4 修复 — 独立审查报告 Q4）：
- handle 入口前置校验事件 occurred_at 不得早于已写入状态的 updated_at，
  若事件比当前状态还老（乱序或重播），直接跳过，避免覆盖更新鲜的事实。
- 幂等由 FSM.transition / FSM.handle_order_reversal 内部的
  last_transition_event_id 继续保证。

继承关系：
  ProjectorBase（shared.events.src.projector）提供监听循环、检查点管理；
  本投影器只实现 handle(event, conn) 即可。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog

from shared.events.src.projector import ProjectorBase
from shared.ontology.src.database import async_session_factory

try:
    from services.customer_lifecycle_fsm import CustomerLifecycleFSM
except ImportError:  # pragma: no cover
    from .customer_lifecycle_fsm import CustomerLifecycleFSM  # type: ignore[no-redef]

logger = structlog.get_logger(__name__)


# P0-1：扩展消费集。一处写死，下游 ProjectorBase 自动过滤。
_ORDER_PAID = "order.paid"
_ORDER_CANCELLED = "order.cancelled"
_ORDER_REFUNDED = "order.refunded"
_REVERSAL_EVENTS = {_ORDER_CANCELLED, _ORDER_REFUNDED}


class CustomerLifecycleProjector(ProjectorBase):
    """监听 order.paid / order.cancelled / order.refunded 事件 → 触发 FSM。"""

    name = "customer_lifecycle"
    event_types = {_ORDER_PAID, _ORDER_CANCELLED, _ORDER_REFUNDED}

    async def handle(self, event: dict[str, Any], conn: object) -> None:
        """单条事件处理入口。

        注意：ProjectorBase.handle 的 conn 是 asyncpg 连接；FSM 用 SQLAlchemy
        AsyncSession，因此此处独立打开一个 async_session_factory() session 完成
        FSM 事务，不复用 conn（避免 asyncpg ↔ SQLAlchemy 混用）。
        """
        event_type = str(event.get("event_type") or "")
        payload = event.get("payload") or {}

        customer_id_raw = payload.get("customer_id")
        if not customer_id_raw:
            logger.debug(
                "lifecycle_projector_skip_no_customer",
                event_id=str(event.get("event_id")),
                event_type=event_type,
            )
            return

        try:
            customer_id = UUID(str(customer_id_raw))
        except (ValueError, TypeError) as exc:
            logger.warning(
                "lifecycle_projector_bad_customer_id",
                event_id=str(event.get("event_id")),
                customer_id=customer_id_raw,
                error=str(exc),
            )
            return

        # 解析业务时间
        occurred_at = event.get("occurred_at")
        if isinstance(occurred_at, str):
            try:
                occurred_at = datetime.fromisoformat(occurred_at)
            except ValueError:
                logger.warning(
                    "lifecycle_projector_bad_occurred_at_str",
                    event_id=str(event.get("event_id")),
                    occurred_at=occurred_at,
                )
                return
        if not isinstance(occurred_at, datetime):
            logger.warning(
                "lifecycle_projector_bad_occurred_at",
                event_id=str(event.get("event_id")),
            )
            return

        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)

        trigger_event_id = event.get("event_id")
        event_id_uuid: UUID | None
        try:
            event_id_uuid = UUID(str(trigger_event_id)) if trigger_event_id else None
        except (ValueError, TypeError):
            event_id_uuid = None

        # P1-4 时序单调性：若已有状态且 occurred_at 早于该状态的 updated_at，
        # 视为乱序/重播事件，直接跳过（不覆盖更新鲜的事实）。
        # 先做轻量预检，避免无谓进入 FSM 流程。
        if await self._is_event_older_than_current_state(
            customer_id=customer_id,
            occurred_at=occurred_at,
        ):
            logger.info(
                "lifecycle_projector_skip_older_event",
                event_id=str(event.get("event_id")),
                event_type=event_type,
                customer_id=str(customer_id),
                occurred_at=occurred_at.isoformat(),
            )
            return

        async with async_session_factory() as session:
            try:
                fsm = CustomerLifecycleFSM(session, self.tenant_id)

                if event_type == _ORDER_PAID:
                    await self._handle_paid(
                        session=session,
                        fsm=fsm,
                        customer_id=customer_id,
                        occurred_at=occurred_at,
                        payload=payload,
                        event_id_uuid=event_id_uuid,
                    )
                elif event_type in _REVERSAL_EVENTS:
                    await self._handle_reversal(
                        session=session,
                        fsm=fsm,
                        customer_id=customer_id,
                        occurred_at=occurred_at,
                        payload=payload,
                        event_id_uuid=event_id_uuid,
                        event_type=event_type,
                    )
                else:
                    logger.debug(
                        "lifecycle_projector_skip_unknown_type",
                        event_id=str(event.get("event_id")),
                        event_type=event_type,
                    )
                    return

                await session.commit()
            except (RuntimeError, ValueError, ConnectionError, TimeoutError) as exc:
                await session.rollback()
                logger.error(
                    "lifecycle_projector_transition_failed",
                    event_id=str(event.get("event_id")),
                    event_type=event_type,
                    customer_id=str(customer_id),
                    error=str(exc),
                    exc_info=True,
                )

    # ──────────────────────────────────────────────────────────────
    # paid 分支
    # ──────────────────────────────────────────────────────────────

    async def _handle_paid(
        self,
        *,
        session: Any,
        fsm: CustomerLifecycleFSM,
        customer_id: UUID,
        occurred_at: datetime,
        payload: dict[str, Any],
        event_id_uuid: UUID | None,
    ) -> None:
        """order.paid：推进客户生命周期状态机。"""
        order_count = int(payload.get("order_count") or 0)
        if order_count <= 0:
            order_count = await self._fetch_order_count(
                session=session,
                customer_id=customer_id,
            )

        await fsm.transition(
            customer_id=customer_id,
            trigger_event_id=event_id_uuid,
            now=occurred_at,
            last_order_at=occurred_at,
            order_count=max(order_count, 1),  # 本次支付本身就 ≥1 单
            reason="order_paid",
        )

    # ──────────────────────────────────────────────────────────────
    # cancelled / refunded 分支（P0-1）
    # ──────────────────────────────────────────────────────────────

    async def _handle_reversal(
        self,
        *,
        session: Any,
        fsm: CustomerLifecycleFSM,
        customer_id: UUID,
        occurred_at: datetime,
        payload: dict[str, Any],
        event_id_uuid: UUID | None,
        event_type: str,
    ) -> None:
        """order.cancelled / order.refunded：按窗口期内是否还有其他已付订单决定
        是否回退状态。判断依据：

        payload 优先 —— 如果事件 payload 携带了 `previous_paid_order_at` 和
        `remaining_order_count`，直接使用（由发事件方填好，最准确）；
        否则从 customers 表 fallback 近似——last_order_at / total_order_count
        均为"本次退款已扣除"后的快照（假设业务层在发事件前已更新）。
        """
        reversal_type = (
            "order_cancelled" if event_type == _ORDER_CANCELLED else "order_refunded"
        )

        previous_paid_order_at_raw = payload.get("previous_paid_order_at")
        previous_paid_order_at: datetime | None = None
        if isinstance(previous_paid_order_at_raw, str):
            try:
                previous_paid_order_at = datetime.fromisoformat(
                    previous_paid_order_at_raw
                )
            except ValueError:
                previous_paid_order_at = None
        elif isinstance(previous_paid_order_at_raw, datetime):
            previous_paid_order_at = previous_paid_order_at_raw

        remaining_order_count_raw = payload.get("remaining_order_count")
        remaining_order_count: int
        if remaining_order_count_raw is None:
            # fallback：从 customers 表读（业务层应已扣除本次）
            remaining_order_count = await self._fetch_order_count(
                session=session,
                customer_id=customer_id,
            )
        else:
            try:
                remaining_order_count = int(remaining_order_count_raw)
            except (ValueError, TypeError):
                remaining_order_count = 0

        if previous_paid_order_at is None and remaining_order_count > 0:
            # 有遗留已付订单但未传时间：fallback 从 customers.last_order_at 读
            previous_paid_order_at = await self._fetch_last_order_at(
                session=session,
                customer_id=customer_id,
            )

        if previous_paid_order_at is not None and previous_paid_order_at.tzinfo is None:
            previous_paid_order_at = previous_paid_order_at.replace(
                tzinfo=timezone.utc
            )

        await fsm.handle_order_reversal(
            customer_id=customer_id,
            trigger_event_id=event_id_uuid,
            now=occurred_at,
            previous_paid_order_at=previous_paid_order_at,
            remaining_order_count=max(remaining_order_count, 0),
            reversal_type=reversal_type,
        )

    # ──────────────────────────────────────────────────────────────
    # 辅助查询
    # ──────────────────────────────────────────────────────────────

    async def _is_event_older_than_current_state(
        self,
        *,
        customer_id: UUID,
        occurred_at: datetime,
    ) -> bool:
        """P1-4：预检 occurred_at 是否早于已有 lifecycle 记录的 since_ts。

        原则：我们不能只靠 updated_at（那是写入时刻），since_ts 才是状态进入
        当前象限的业务时间。事件的 occurred_at 若严格早于 since_ts，说明事件
        对应的业务时刻比客户"当前状态的起点"还早——这条事件对当前状态没有
        改变意义（否则会回退更鲜的事实）。

        用独立 session 做只读查询，尽量轻量。
        """
        from sqlalchemy import text

        async with async_session_factory() as session:
            try:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(self.tenant_id)},
                )
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT since_ts
                            FROM customer_lifecycle_state
                            WHERE tenant_id = :tid AND customer_id = :cid
                            """
                        ),
                        {"tid": str(self.tenant_id), "cid": str(customer_id)},
                    )
                ).fetchone()
            except (RuntimeError, ConnectionError, TimeoutError) as exc:
                # 查询失败不阻断主流程，保守 return False 让后续逻辑继续。
                logger.warning(
                    "lifecycle_projector_monotonic_precheck_failed",
                    customer_id=str(customer_id),
                    error=str(exc),
                )
                return False

        if row is None or row[0] is None:
            return False

        since_ts = row[0]
        if isinstance(since_ts, datetime) and since_ts.tzinfo is None:
            since_ts = since_ts.replace(tzinfo=timezone.utc)
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)

        return occurred_at < since_ts

    async def _fetch_order_count(
        self,
        *,
        session: Any,
        customer_id: UUID,
    ) -> int:
        """按 tenant+customer 读 customers.total_order_count（带 RLS）。"""
        from sqlalchemy import text

        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(self.tenant_id)},
        )
        row = (
            await session.execute(
                text(
                    """
                    SELECT total_order_count
                    FROM customers
                    WHERE tenant_id = :tid AND id = :cid AND is_deleted = FALSE
                    """
                ),
                {"tid": str(self.tenant_id), "cid": str(customer_id)},
            )
        ).fetchone()
        if row is None or row[0] is None:
            return 0
        return int(row[0])

    async def _fetch_last_order_at(
        self,
        *,
        session: Any,
        customer_id: UUID,
    ) -> datetime | None:
        """fallback 读 customers.last_order_at（已扣除当前退款的业务快照）。"""
        from sqlalchemy import text

        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(self.tenant_id)},
        )
        row = (
            await session.execute(
                text(
                    """
                    SELECT last_order_at
                    FROM customers
                    WHERE tenant_id = :tid AND id = :cid AND is_deleted = FALSE
                    """
                ),
                {"tid": str(self.tenant_id), "cid": str(customer_id)},
            )
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return row[0] if isinstance(row[0], datetime) else None
