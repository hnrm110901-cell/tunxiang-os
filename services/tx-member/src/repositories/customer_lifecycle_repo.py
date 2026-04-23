"""customer_lifecycle_state 仓储 — FSM 单行读写 + 日终批量重算

对应表：customer_lifecycle_state（迁移 v264）
所有方法：
- 强制 tenant_id + RLS（SET LOCAL app.tenant_id）
- SELECT FOR UPDATE 行锁规避 200 并发下的竞态
- upsert_state 幂等：当 trigger_event_id 与上一次相同则短路返回旧记录

调用方：CustomerLifecycleFSM、CustomerLifecycleProjector、API routes
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.extensions.customer_lifecycle import (
    CustomerLifecycleRecord,
    CustomerLifecycleState,
)

logger = structlog.get_logger(__name__)


class CustomerLifecycleRepository:
    """customer_lifecycle_state 表仓储（单行级别读写 + 批量聚合）。"""

    def __init__(self, db: AsyncSession, tenant_id: UUID | str) -> None:
        self.db = db
        self.tenant_id = UUID(str(tenant_id))

    # ──────────────────────────────────────────────────────────────────
    # RLS 上下文
    # ──────────────────────────────────────────────────────────────────

    async def _set_rls(self) -> None:
        """注入 RLS 上下文，保证后续查询只命中当前租户。"""
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(self.tenant_id)},
        )

    # ──────────────────────────────────────────────────────────────────
    # 单行读取
    # ──────────────────────────────────────────────────────────────────

    async def get_current_state(
        self,
        customer_id: UUID | str,
    ) -> CustomerLifecycleRecord | None:
        """按 (tenant_id, customer_id) 查询当前状态。

        Returns:
            CustomerLifecycleRecord 或 None（该客户尚未写入任何状态）
        """
        await self._set_rls()
        cid = UUID(str(customer_id))
        row = (
            await self.db.execute(
                text(
                    """
                    SELECT customer_id, tenant_id, state, since_ts,
                           previous_state, transition_count,
                           last_transition_event_id, updated_at
                    FROM customer_lifecycle_state
                    WHERE tenant_id = :tid AND customer_id = :cid
                    """
                ),
                {"tid": str(self.tenant_id), "cid": str(cid)},
            )
        ).fetchone()

        if row is None:
            return None
        return self._row_to_record(row)

    async def get_for_update(
        self,
        customer_id: UUID | str,
    ) -> CustomerLifecycleRecord | None:
        """行锁读取当前状态（用于 FSM transition 的并发安全区）。

        必须在一个事务内调用。asyncpg / SQLAlchemy 需要配合 session 的事务边界。
        """
        await self._set_rls()
        cid = UUID(str(customer_id))
        row = (
            await self.db.execute(
                text(
                    """
                    SELECT customer_id, tenant_id, state, since_ts,
                           previous_state, transition_count,
                           last_transition_event_id, updated_at
                    FROM customer_lifecycle_state
                    WHERE tenant_id = :tid AND customer_id = :cid
                    FOR UPDATE
                    """
                ),
                {"tid": str(self.tenant_id), "cid": str(cid)},
            )
        ).fetchone()

        if row is None:
            return None
        return self._row_to_record(row)

    # ──────────────────────────────────────────────────────────────────
    # 幂等写入
    # ──────────────────────────────────────────────────────────────────

    async def upsert_state(
        self,
        *,
        customer_id: UUID | str,
        target_state: CustomerLifecycleState,
        since_ts: datetime,
        trigger_event_id: UUID | str | None,
        previous_state: CustomerLifecycleState | None,
    ) -> CustomerLifecycleRecord:
        """幂等写入一行 customer_lifecycle_state。

        逻辑：
        - 若同一 customer 尚无记录 → INSERT（previous_state=NULL，transition_count=1 当
          target_state != no_order 时）。
        - 若已有记录：
            * trigger_event_id 相同 → 短路返回旧记录（幂等）
            * state 相同 → 仅更新 updated_at 与 trigger_event_id
            * state 不同 → UPDATE previous_state + state + since_ts + transition_count+1

        Returns:
            最终记录（Pydantic）
        """
        await self._set_rls()
        cid = UUID(str(customer_id))
        trig = UUID(str(trigger_event_id)) if trigger_event_id else None

        existing_row = (
            await self.db.execute(
                text(
                    """
                    SELECT customer_id, tenant_id, state, since_ts,
                           previous_state, transition_count,
                           last_transition_event_id, updated_at
                    FROM customer_lifecycle_state
                    WHERE tenant_id = :tid AND customer_id = :cid
                    FOR UPDATE
                    """
                ),
                {"tid": str(self.tenant_id), "cid": str(cid)},
            )
        ).fetchone()

        now = datetime.now(timezone.utc)

        if existing_row is None:
            # 新建：transition_count 从 1 开始（视为 NULL → target 的首次迁移）
            await self.db.execute(
                text(
                    """
                    INSERT INTO customer_lifecycle_state
                        (customer_id, tenant_id, state, since_ts, previous_state,
                         transition_count, last_transition_event_id, updated_at)
                    VALUES (:cid, :tid, :state, :since, :prev, 1, :evt, :now)
                    """
                ),
                {
                    "cid": str(cid),
                    "tid": str(self.tenant_id),
                    "state": target_state.value,
                    "since": since_ts,
                    "prev": previous_state.value if previous_state else None,
                    "evt": str(trig) if trig else None,
                    "now": now,
                },
            )
            return CustomerLifecycleRecord(
                customer_id=cid,
                tenant_id=self.tenant_id,
                state=target_state,
                since_ts=since_ts,
                previous_state=previous_state,
                transition_count=1,
                last_transition_event_id=trig,
                updated_at=now,
            )

        current = self._row_to_record(existing_row)

        # 幂等：同一 trigger_event_id 已被处理过
        if (
            trig is not None
            and current.last_transition_event_id is not None
            and current.last_transition_event_id == trig
        ):
            logger.info(
                "lifecycle_upsert_idempotent",
                tenant_id=str(self.tenant_id),
                customer_id=str(cid),
                trigger_event_id=str(trig),
                state=current.state.value,
            )
            return current

        # 状态未变：只 touch updated_at + trigger_event_id（驱动审计链）
        if current.state == target_state:
            await self.db.execute(
                text(
                    """
                    UPDATE customer_lifecycle_state
                    SET last_transition_event_id = :evt,
                        updated_at = :now
                    WHERE tenant_id = :tid AND customer_id = :cid
                    """
                ),
                {
                    "cid": str(cid),
                    "tid": str(self.tenant_id),
                    "evt": str(trig) if trig else None,
                    "now": now,
                },
            )
            return CustomerLifecycleRecord(
                customer_id=cid,
                tenant_id=self.tenant_id,
                state=current.state,
                since_ts=current.since_ts,
                previous_state=current.previous_state,
                transition_count=current.transition_count,
                last_transition_event_id=trig or current.last_transition_event_id,
                updated_at=now,
            )

        # 真实迁移：previous_state 取当前 state，transition_count+1
        new_count = current.transition_count + 1
        await self.db.execute(
            text(
                """
                UPDATE customer_lifecycle_state
                SET state = :state,
                    since_ts = :since,
                    previous_state = :prev,
                    transition_count = :cnt,
                    last_transition_event_id = :evt,
                    updated_at = :now
                WHERE tenant_id = :tid AND customer_id = :cid
                """
            ),
            {
                "cid": str(cid),
                "tid": str(self.tenant_id),
                "state": target_state.value,
                "since": since_ts,
                "prev": current.state.value,
                "cnt": new_count,
                "evt": str(trig) if trig else None,
                "now": now,
            },
        )

        return CustomerLifecycleRecord(
            customer_id=cid,
            tenant_id=self.tenant_id,
            state=target_state,
            since_ts=since_ts,
            previous_state=current.state,
            transition_count=new_count,
            last_transition_event_id=trig,
            updated_at=now,
        )

    # ──────────────────────────────────────────────────────────────────
    # 聚合查询（API /summary 用）
    # ──────────────────────────────────────────────────────────────────

    async def count_by_state(self) -> dict[str, int]:
        """按 (tenant_id, state) 聚合 4 象限计数。

        Returns:
            {"no_order": n, "active": n, "dormant": n, "churned": n}
        """
        await self._set_rls()
        rows = (
            await self.db.execute(
                text(
                    """
                    SELECT state, count(*) AS cnt
                    FROM customer_lifecycle_state
                    WHERE tenant_id = :tid
                    GROUP BY state
                    """
                ),
                {"tid": str(self.tenant_id)},
            )
        ).fetchall()

        result: dict[str, int] = {s.value: 0 for s in CustomerLifecycleState}
        for row in rows:
            state_key = row[0]
            if state_key in result:
                result[state_key] = int(row[1])
        return result

    async def count_flows(self, window_days: int = 30) -> dict[str, int]:
        """按 previous_state → state 汇总 4 类流量（近 N 天）。

        流量定义：
        - new_active：previous_state=no_order AND state=active
        - new_dormant：previous_state=active AND state=dormant
        - recalled：previous_state=dormant AND state=active
        - recovered：previous_state=churned AND state=active

        Returns:
            {"new_active": n, "new_dormant": n, "recalled": n, "recovered": n}
        """
        await self._set_rls()
        rows = (
            await self.db.execute(
                text(
                    """
                    SELECT previous_state, state, count(*) AS cnt
                    FROM customer_lifecycle_state
                    WHERE tenant_id = :tid
                      AND since_ts >= NOW() - (:days || ' days')::interval
                    GROUP BY previous_state, state
                    """
                ),
                {"tid": str(self.tenant_id), "days": str(window_days)},
            )
        ).fetchall()

        flows = {
            "new_active": 0,
            "new_dormant": 0,
            "recalled": 0,
            "recovered": 0,
        }
        for row in rows:
            prev = row[0]
            curr = row[1]
            cnt = int(row[2])
            if prev == "no_order" and curr == "active":
                flows["new_active"] += cnt
            elif prev == "active" and curr == "dormant":
                flows["new_dormant"] += cnt
            elif prev == "dormant" and curr == "active":
                flows["recalled"] += cnt
            elif prev == "churned" and curr == "active":
                flows["recovered"] += cnt
        return flows

    # ──────────────────────────────────────────────────────────────────
    # 日终批量重算（读 customers 订单统计，驱动 FSM 重算）
    # ──────────────────────────────────────────────────────────────────

    async def bulk_recompute_by_orders(
        self,
        window_days: int = 365,
    ) -> list[dict[str, Any]]:
        """扫描 customers + 最近订单，返回待重算客户列表（不直接改表）。

        FSM 在外层消费本列表，逐个调用 transition()。

        Returns:
            [{customer_id, last_order_at, order_count}, ...]
        """
        await self._set_rls()
        rows = (
            await self.db.execute(
                text(
                    """
                    SELECT id AS customer_id,
                           last_order_at,
                           total_order_count
                    FROM customers
                    WHERE tenant_id = :tid
                      AND is_deleted = FALSE
                      AND (last_order_at IS NULL
                           OR last_order_at >= NOW() - (:days || ' days')::interval)
                    """
                ),
                {"tid": str(self.tenant_id), "days": str(window_days)},
            )
        ).fetchall()

        return [
            {
                "customer_id": str(row[0]),
                "last_order_at": row[1],
                "order_count": int(row[2] or 0),
            }
            for row in rows
        ]

    # ──────────────────────────────────────────────────────────────────
    # 内部工具
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_record(row: Any) -> CustomerLifecycleRecord:
        """SQLAlchemy Row → Pydantic 记录。"""
        return CustomerLifecycleRecord(
            customer_id=UUID(str(row[0])),
            tenant_id=UUID(str(row[1])),
            state=CustomerLifecycleState(row[2]),
            since_ts=row[3],
            previous_state=CustomerLifecycleState(row[4]) if row[4] else None,
            transition_count=int(row[5]),
            last_transition_event_id=UUID(str(row[6])) if row[6] else None,
            updated_at=row[7],
        )
