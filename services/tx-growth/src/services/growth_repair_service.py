"""服务修复案例管理 — 管理growth_service_repair_cases表

从投诉到修复完成的全生命周期管理。
联动 customer_growth_profiles.service_repair_status 字段。

金额单位：分(fen)
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event

GROWTH_EVT_PREFIX = "growth"

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 状态机定义
# ---------------------------------------------------------------------------

# 合法状态转换表: from_state -> {allowed_to_states}
_REPAIR_TRANSITIONS: dict[str, set[str]] = {
    "opened": {"acknowledged"},
    "acknowledged": {"compensating"},
    "compensating": {"observing"},
    "observing": {"recovered", "failed"},
    "recovered": {"closed"},
    "failed": {"closed"},
}


# ---------------------------------------------------------------------------
# GrowthRepairService
# ---------------------------------------------------------------------------


class GrowthRepairService:
    """服务修复案例管理"""

    VALID_STATES = (
        "opened", "acknowledged", "compensating",
        "observing", "recovered", "failed", "closed",
    )
    VALID_SEVERITIES = ("low", "medium", "high", "critical")
    VALID_SOURCE_TYPES = ("complaint", "bad_review", "refund", "agent_detected", "manual")
    VALID_OWNER_TYPES = ("system", "store_manager", "hq_cs")

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    def _validate_transition(self, current_state: str, target_state: str) -> None:
        """校验状态转换合法性"""
        allowed = _REPAIR_TRANSITIONS.get(current_state, set())
        if target_state not in allowed:
            raise ValueError(
                f"Invalid state transition: '{current_state}' -> '{target_state}'. "
                f"Allowed targets from '{current_state}': {allowed}"
            )

    async def _get_case_state(
        self, case_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """查case当前状态"""
        result = await db.execute(
            text("""
                SELECT id, customer_id, repair_state
                FROM growth_service_repair_cases
                WHERE tenant_id = :tid AND id = :cid AND is_deleted = false
            """),
            {"tid": tenant_id, "cid": str(case_id)},
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"Repair case {case_id} not found")
        return dict(row._mapping)

    async def _update_profile_repair_status(
        self, customer_id: str, status: str, case_id: Optional[str],
        tenant_id: str, db: AsyncSession,
    ) -> None:
        """同步更新customer_growth_profiles.service_repair_status"""
        await db.execute(
            text("""
                UPDATE customer_growth_profiles
                SET service_repair_status = :status,
                    service_repair_case_id = :case_id,
                    updated_at = NOW()
                WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
            """),
            {
                "tid": tenant_id,
                "cid": customer_id,
                "status": status,
                "case_id": case_id,
            },
        )

    # ------------------------------------------------------------------
    # 创建案例
    # ------------------------------------------------------------------

    async def create_case(
        self,
        customer_id: UUID,
        source_type: str,
        source_ref_id: Optional[str],
        severity: str,
        summary: Optional[str],
        owner_type: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """创建服务修复案例"""
        if source_type not in self.VALID_SOURCE_TYPES:
            raise ValueError(f"Invalid source_type: {source_type}")
        if severity not in self.VALID_SEVERITIES:
            raise ValueError(f"Invalid severity: {severity}")
        if owner_type not in self.VALID_OWNER_TYPES:
            raise ValueError(f"Invalid owner_type: {owner_type}")

        await self._set_tenant(db, tenant_id)

        case_id = str(uuid4())
        result = await db.execute(
            text("""
                INSERT INTO growth_service_repair_cases
                    (id, tenant_id, customer_id, source_type, source_ref_id,
                     severity, summary, owner_type, repair_state)
                VALUES
                    (:id, :tenant_id, :customer_id, :source_type, :source_ref_id,
                     :severity, :summary, :owner_type, 'opened')
                RETURNING id, tenant_id, customer_id, source_type, source_ref_id,
                          severity, summary, owner_type, repair_state,
                          created_at, updated_at
            """),
            {
                "id": case_id,
                "tenant_id": tenant_id,
                "customer_id": str(customer_id),
                "source_type": source_type,
                "source_ref_id": source_ref_id,
                "severity": severity,
                "summary": summary,
                "owner_type": owner_type,
            },
        )
        case = dict(result.fetchone()._mapping)

        # 同步更新profile
        await self._update_profile_repair_status(
            str(customer_id), "complaint_open", case_id, tenant_id, db
        )

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.repair.state_changed",
                tenant_id=tenant_id,
                stream_id=case_id,
                payload={
                    "case_id": case_id,
                    "customer_id": str(customer_id),
                    "new_state": "opened",
                    "severity": severity,
                    "source_type": source_type,
                },
                source_service="tx-growth",
            )
        )
        logger.info(
            "repair_case_created",
            case_id=case_id,
            customer_id=str(customer_id),
            severity=severity,
            tenant_id=tenant_id,
        )
        return case

    # ------------------------------------------------------------------
    # 确认（opened -> acknowledged）
    # ------------------------------------------------------------------

    async def acknowledge(
        self, case_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """确认案例: opened -> acknowledged"""
        await self._set_tenant(db, tenant_id)
        current = await self._get_case_state(case_id, tenant_id, db)
        self._validate_transition(current["repair_state"], "acknowledged")

        result = await db.execute(
            text("""
                UPDATE growth_service_repair_cases
                SET repair_state = 'acknowledged',
                    emotion_ack_at = NOW(),
                    updated_at = NOW()
                WHERE tenant_id = :tid AND id = :cid AND is_deleted = false
                RETURNING id, customer_id, repair_state, emotion_ack_at, updated_at
            """),
            {"tid": tenant_id, "cid": str(case_id)},
        )
        updated = dict(result.fetchone()._mapping)

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.repair.state_changed",
                tenant_id=tenant_id,
                stream_id=str(case_id),
                payload={
                    "case_id": str(case_id),
                    "customer_id": str(current["customer_id"]),
                    "new_state": "acknowledged",
                },
                source_service="tx-growth",
            )
        )
        logger.info("repair_case_acknowledged", case_id=str(case_id), tenant_id=tenant_id)
        return updated

    # ------------------------------------------------------------------
    # 提交补偿方案（acknowledged -> compensating）
    # ------------------------------------------------------------------

    async def submit_compensation(
        self,
        case_id: UUID,
        plan_json: dict,
        selected: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """提交补偿方案: acknowledged -> compensating"""
        await self._set_tenant(db, tenant_id)
        current = await self._get_case_state(case_id, tenant_id, db)
        self._validate_transition(current["repair_state"], "compensating")

        import json
        result = await db.execute(
            text("""
                UPDATE growth_service_repair_cases
                SET repair_state = 'compensating',
                    compensation_plan_json = :plan_json::jsonb,
                    selected_compensation = :selected,
                    updated_at = NOW()
                WHERE tenant_id = :tid AND id = :cid AND is_deleted = false
                RETURNING id, customer_id, repair_state, compensation_plan_json,
                          selected_compensation, updated_at
            """),
            {
                "tid": tenant_id,
                "cid": str(case_id),
                "plan_json": json.dumps(plan_json),
                "selected": selected,
            },
        )
        updated = dict(result.fetchone()._mapping)

        # 更新profile状态
        await self._update_profile_repair_status(
            str(current["customer_id"]),
            "complaint_closed_pending_repair",
            str(case_id),
            tenant_id,
            db,
        )

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.repair.state_changed",
                tenant_id=tenant_id,
                stream_id=str(case_id),
                payload={
                    "case_id": str(case_id),
                    "customer_id": str(current["customer_id"]),
                    "new_state": "compensating",
                    "selected_compensation": selected,
                },
                source_service="tx-growth",
            )
        )
        logger.info(
            "repair_compensation_submitted",
            case_id=str(case_id),
            selected=selected,
            tenant_id=tenant_id,
        )
        return updated

    # ------------------------------------------------------------------
    # 开始观察（compensating -> observing）
    # ------------------------------------------------------------------

    async def start_observe(
        self,
        case_id: UUID,
        window_hours: int,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """开始观察期: compensating -> observing"""
        await self._set_tenant(db, tenant_id)
        current = await self._get_case_state(case_id, tenant_id, db)
        self._validate_transition(current["repair_state"], "observing")

        observe_until = datetime.now(timezone.utc) + timedelta(hours=window_hours)

        result = await db.execute(
            text("""
                UPDATE growth_service_repair_cases
                SET repair_state = 'observing',
                    observe_until = :observe_until,
                    updated_at = NOW()
                WHERE tenant_id = :tid AND id = :cid AND is_deleted = false
                RETURNING id, customer_id, repair_state, observe_until, updated_at
            """),
            {
                "tid": tenant_id,
                "cid": str(case_id),
                "observe_until": observe_until,
            },
        )
        updated = dict(result.fetchone()._mapping)

        # 更新profile
        await self._update_profile_repair_status(
            str(current["customer_id"]),
            "repair_observing",
            str(case_id),
            tenant_id,
            db,
        )

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.repair.state_changed",
                tenant_id=tenant_id,
                stream_id=str(case_id),
                payload={
                    "case_id": str(case_id),
                    "customer_id": str(current["customer_id"]),
                    "new_state": "observing",
                    "observe_until": observe_until.isoformat(),
                },
                source_service="tx-growth",
            )
        )
        logger.info(
            "repair_observe_started",
            case_id=str(case_id),
            observe_until=observe_until.isoformat(),
            tenant_id=tenant_id,
        )
        return updated

    # ------------------------------------------------------------------
    # 标记恢复（observing -> recovered）
    # ------------------------------------------------------------------

    async def mark_recovered(
        self, case_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """标记客户恢复: observing -> recovered"""
        await self._set_tenant(db, tenant_id)
        current = await self._get_case_state(case_id, tenant_id, db)
        self._validate_transition(current["repair_state"], "recovered")

        result = await db.execute(
            text("""
                UPDATE growth_service_repair_cases
                SET repair_state = 'recovered', updated_at = NOW()
                WHERE tenant_id = :tid AND id = :cid AND is_deleted = false
                RETURNING id, customer_id, repair_state, updated_at
            """),
            {"tid": tenant_id, "cid": str(case_id)},
        )
        updated = dict(result.fetchone()._mapping)

        # 更新profile
        await self._update_profile_repair_status(
            str(current["customer_id"]),
            "repair_completed",
            str(case_id),
            tenant_id,
            db,
        )

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.repair.state_changed",
                tenant_id=tenant_id,
                stream_id=str(case_id),
                payload={
                    "case_id": str(case_id),
                    "customer_id": str(current["customer_id"]),
                    "new_state": "recovered",
                },
                source_service="tx-growth",
            )
        )
        logger.info("repair_marked_recovered", case_id=str(case_id), tenant_id=tenant_id)
        return updated

    # ------------------------------------------------------------------
    # 标记失败（observing -> failed）
    # ------------------------------------------------------------------

    async def mark_failed(
        self, case_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """标记修复失败: observing -> failed"""
        await self._set_tenant(db, tenant_id)
        current = await self._get_case_state(case_id, tenant_id, db)
        self._validate_transition(current["repair_state"], "failed")

        result = await db.execute(
            text("""
                UPDATE growth_service_repair_cases
                SET repair_state = 'failed', updated_at = NOW()
                WHERE tenant_id = :tid AND id = :cid AND is_deleted = false
                RETURNING id, customer_id, repair_state, updated_at
            """),
            {"tid": tenant_id, "cid": str(case_id)},
        )
        updated = dict(result.fetchone()._mapping)

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.repair.state_changed",
                tenant_id=tenant_id,
                stream_id=str(case_id),
                payload={
                    "case_id": str(case_id),
                    "customer_id": str(current["customer_id"]),
                    "new_state": "failed",
                },
                source_service="tx-growth",
            )
        )
        logger.info("repair_marked_failed", case_id=str(case_id), tenant_id=tenant_id)
        return updated

    # ------------------------------------------------------------------
    # 关闭案例（recovered/failed -> closed）
    # ------------------------------------------------------------------

    async def close_case(
        self, case_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """关闭案例: recovered/failed -> closed"""
        await self._set_tenant(db, tenant_id)
        current = await self._get_case_state(case_id, tenant_id, db)
        self._validate_transition(current["repair_state"], "closed")

        result = await db.execute(
            text("""
                UPDATE growth_service_repair_cases
                SET repair_state = 'closed', updated_at = NOW()
                WHERE tenant_id = :tid AND id = :cid AND is_deleted = false
                RETURNING id, customer_id, repair_state, updated_at
            """),
            {"tid": tenant_id, "cid": str(case_id)},
        )
        updated = dict(result.fetchone()._mapping)

        # 清理profile status -> 'none'
        await self._update_profile_repair_status(
            str(current["customer_id"]), "none", None, tenant_id, db
        )

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.repair.state_changed",
                tenant_id=tenant_id,
                stream_id=str(case_id),
                payload={
                    "case_id": str(case_id),
                    "customer_id": str(current["customer_id"]),
                    "new_state": "closed",
                },
                source_service="tx-growth",
            )
        )
        logger.info("repair_case_closed", case_id=str(case_id), tenant_id=tenant_id)
        return updated

    # ------------------------------------------------------------------
    # 通用状态转换分派器
    # ------------------------------------------------------------------

    async def transition_state(
        self,
        case_id: UUID,
        target_state: str,
        tenant_id: str,
        db: AsyncSession,
        extra_data: Optional[dict] = None,
    ) -> dict:
        """通用状态转换分派器 — 根据target_state调用对应方法"""
        if target_state == "acknowledged":
            return await self.acknowledge(case_id, tenant_id, db)
        elif target_state == "compensating":
            ed = extra_data or {}
            plan_json = ed.get("compensation_plan_json", {})
            selected = ed.get("compensation_selected", "")
            return await self.submit_compensation(case_id, plan_json, selected, tenant_id, db)
        elif target_state == "observing":
            ed = extra_data or {}
            window_hours = ed.get("window_hours", 168)
            return await self.start_observe(case_id, window_hours, tenant_id, db)
        elif target_state == "recovered":
            return await self.mark_recovered(case_id, tenant_id, db)
        elif target_state == "failed":
            return await self.mark_failed(case_id, tenant_id, db)
        elif target_state == "closed":
            return await self.close_case(case_id, tenant_id, db)
        else:
            raise ValueError(
                f"Unsupported target_state: '{target_state}'. "
                f"Valid targets: acknowledged, compensating, observing, recovered, failed, closed"
            )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    async def list_cases(
        self,
        customer_id: Optional[UUID],
        repair_state: Optional[str],
        tenant_id: str,
        page: int,
        size: int,
        db: AsyncSession,
    ) -> dict:
        """分页+过滤查询修复案例"""
        await self._set_tenant(db, tenant_id)

        where_clauses = ["tenant_id = :tid", "is_deleted = false"]
        params: dict = {"tid": tenant_id}

        if customer_id is not None:
            where_clauses.append("customer_id = :cid")
            params["cid"] = str(customer_id)
        if repair_state is not None:
            where_clauses.append("repair_state = :state")
            params["state"] = repair_state

        where_sql = " AND ".join(where_clauses)
        offset = (page - 1) * size

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM growth_service_repair_cases WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar() or 0

        params["lim"] = size
        params["off"] = offset
        rows_result = await db.execute(
            text(f"""
                SELECT id, tenant_id, customer_id, source_type, source_ref_id,
                       severity, summary, owner_type, repair_state,
                       emotion_ack_at, compensation_plan_json, selected_compensation,
                       observe_until, created_at, updated_at
                FROM growth_service_repair_cases
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
            """),
            params,
        )
        items = [dict(r._mapping) for r in rows_result.fetchall()]
        return {"items": items, "total": total}

    async def get_case(
        self, case_id: UUID, tenant_id: str, db: AsyncSession
    ) -> Optional[dict]:
        """查询单个修复案例"""
        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                SELECT id, tenant_id, customer_id, source_type, source_ref_id,
                       severity, summary, owner_type, repair_state,
                       emotion_ack_at, compensation_plan_json, selected_compensation,
                       observe_until, created_at, updated_at
                FROM growth_service_repair_cases
                WHERE tenant_id = :tid AND id = :cid AND is_deleted = false
            """),
            {"tid": tenant_id, "cid": str(case_id)},
        )
        row = result.fetchone()
        if row is None:
            return None
        return dict(row._mapping)
