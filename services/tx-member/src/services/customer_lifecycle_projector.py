"""CustomerLifecycleProjector — 消费事件 → FSM 迁移

消费的事件：
  order.paid  → 触发 CustomerLifecycleFSM.transition()
                （order_count 和 last_order_at 从 payload / customers 表推断）

注意：
- 本投影器不直接维护物化视图（mv_customer_lifecycle 归入 R2）。
- 每条 order.paid 事件都会驱动一次 FSM 迁移，FSM 自身幂等。
- 读取 customers.total_order_count 作为 order_count 近似（FSM 内部再校验）。

继承关系：
  ProjectorBase（shared.events.src.projector）提供监听循环、检查点管理；
  本投影器只实现 handle(event, conn) 即可。
"""

from __future__ import annotations

from datetime import datetime
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


class CustomerLifecycleProjector(ProjectorBase):
    """监听 order.paid 事件 → 触发客户生命周期 FSM。"""

    name = "customer_lifecycle"
    event_types = {"order.paid"}

    async def handle(self, event: dict[str, Any], conn: object) -> None:
        """单条事件处理入口。

        注意：ProjectorBase.handle 的 conn 是 asyncpg 连接；FSM 用 SQLAlchemy
        AsyncSession，因此此处独立打开一个 async_session_factory() session 完成
        FSM 事务，不复用 conn（避免 asyncpg ↔ SQLAlchemy 混用）。
        """
        payload = event.get("payload") or {}
        customer_id_raw = payload.get("customer_id")
        if not customer_id_raw:
            logger.debug(
                "lifecycle_projector_skip_no_customer",
                event_id=str(event.get("event_id")),
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
            occurred_at = datetime.fromisoformat(occurred_at)
        if not isinstance(occurred_at, datetime):
            logger.warning(
                "lifecycle_projector_bad_occurred_at",
                event_id=str(event.get("event_id")),
            )
            return

        # 订单计数：payload 优先，fallback 用 customers.total_order_count
        order_count = int(payload.get("order_count") or 0)
        last_order_at = occurred_at  # 本次就是最新一次

        trigger_event_id = event.get("event_id")
        event_id_uuid: UUID | None
        try:
            event_id_uuid = UUID(str(trigger_event_id)) if trigger_event_id else None
        except (ValueError, TypeError):
            event_id_uuid = None

        async with async_session_factory() as session:
            try:
                # 如果 payload 没传 order_count，从 customers 查一次（带 RLS）
                if order_count <= 0:
                    order_count = await self._fetch_order_count(
                        session=session,
                        customer_id=customer_id,
                    )

                fsm = CustomerLifecycleFSM(session, self.tenant_id)
                await fsm.transition(
                    customer_id=customer_id,
                    trigger_event_id=event_id_uuid,
                    now=occurred_at,
                    last_order_at=last_order_at,
                    order_count=max(order_count, 1),  # 本次支付本身就 ≥1 单
                    reason="order_paid",
                )
                await session.commit()
            except (RuntimeError, ValueError, ConnectionError, TimeoutError) as exc:
                await session.rollback()
                logger.error(
                    "lifecycle_projector_transition_failed",
                    event_id=str(event.get("event_id")),
                    customer_id=str(customer_id),
                    error=str(exc),
                    exc_info=True,
                )

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
