"""客户增长画像服务 — 管理customer_growth_profiles表的CRUD和状态流转

金额单位：分(fen)
存储层：PostgreSQL customer_growth_profiles 表
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event

GROWTH_EVT_PREFIX = "growth"

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# GrowthProfileService
# ---------------------------------------------------------------------------


class GrowthProfileService:
    """客户增长画像服务 — customer_growth_profiles 表 CRUD + 状态流转"""

    VALID_REPURCHASE_STAGES = (
        "not_started",
        "first_order_done",
        "second_order_done",
        "stable_repeat",
    )
    VALID_REACTIVATION_PRIORITIES = ("none", "low", "medium", "high", "critical")
    VALID_REPAIR_STATUSES = (
        "none",
        "complaint_open",
        "complaint_closed_pending_repair",
        "repair_in_progress",
        "repair_observing",
        "repair_completed",
    )

    # 复购阶段有序状态机：只能顺序前进
    _REPURCHASE_ORDER: dict[str, int] = {
        "not_started": 0,
        "first_order_done": 1,
        "second_order_done": 2,
        "stable_repeat": 3,
    }

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    async def get_profile(
        self, customer_id: UUID, tenant_id: str, db: AsyncSession
    ) -> Optional[dict]:
        """获取客户增长画像"""
        await self._set_tenant(db, tenant_id)
        result = await db.execute(
            text("""
                SELECT id, tenant_id, customer_id, repurchase_stage,
                       reactivation_priority, reactivation_reason,
                       service_repair_status, service_repair_case_id,
                       has_active_owned_benefit, growth_opt_out,
                       marketing_pause_until, last_order_at,
                       created_at, updated_at
                FROM customer_growth_profiles
                WHERE tenant_id = :tid
                  AND customer_id = :cid
                  AND is_deleted = false
                LIMIT 1
            """),
            {"tid": tenant_id, "cid": str(customer_id)},
        )
        row = result.fetchone()
        if row is None:
            return None
        return dict(row._mapping)

    # ------------------------------------------------------------------
    # 创建/更新
    # ------------------------------------------------------------------

    async def upsert_profile(
        self, customer_id: UUID, data: dict, tenant_id: str, db: AsyncSession
    ) -> dict:
        """创建或更新客户增长画像（INSERT ON CONFLICT UPDATE）"""
        await self._set_tenant(db, tenant_id)

        repurchase_stage = data.get("repurchase_stage", "not_started")
        reactivation_priority = data.get("reactivation_priority", "none")
        reactivation_reason = data.get("reactivation_reason")
        service_repair_status = data.get("service_repair_status", "none")
        service_repair_case_id = data.get("service_repair_case_id")
        has_active_owned_benefit = data.get("has_active_owned_benefit", False)
        growth_opt_out = data.get("growth_opt_out", False)
        marketing_pause_until = data.get("marketing_pause_until")
        last_order_at = data.get("last_order_at")

        if repurchase_stage not in self.VALID_REPURCHASE_STAGES:
            raise ValueError(f"Invalid repurchase_stage: {repurchase_stage}")
        if reactivation_priority not in self.VALID_REACTIVATION_PRIORITIES:
            raise ValueError(f"Invalid reactivation_priority: {reactivation_priority}")
        if service_repair_status not in self.VALID_REPAIR_STATUSES:
            raise ValueError(f"Invalid service_repair_status: {service_repair_status}")

        result = await db.execute(
            text("""
                INSERT INTO customer_growth_profiles
                    (tenant_id, customer_id, repurchase_stage,
                     reactivation_priority, reactivation_reason,
                     service_repair_status, service_repair_case_id,
                     has_active_owned_benefit, growth_opt_out,
                     marketing_pause_until, last_order_at)
                VALUES
                    (:tenant_id, :customer_id, :repurchase_stage,
                     :reactivation_priority, :reactivation_reason,
                     :service_repair_status, :service_repair_case_id,
                     :has_active_owned_benefit, :growth_opt_out,
                     :marketing_pause_until, :last_order_at)
                ON CONFLICT (tenant_id, customer_id) DO UPDATE SET
                    repurchase_stage = EXCLUDED.repurchase_stage,
                    reactivation_priority = EXCLUDED.reactivation_priority,
                    reactivation_reason = EXCLUDED.reactivation_reason,
                    service_repair_status = EXCLUDED.service_repair_status,
                    service_repair_case_id = EXCLUDED.service_repair_case_id,
                    has_active_owned_benefit = EXCLUDED.has_active_owned_benefit,
                    growth_opt_out = EXCLUDED.growth_opt_out,
                    marketing_pause_until = EXCLUDED.marketing_pause_until,
                    last_order_at = EXCLUDED.last_order_at,
                    updated_at = NOW()
                RETURNING id, tenant_id, customer_id, repurchase_stage,
                          reactivation_priority, reactivation_reason,
                          service_repair_status, service_repair_case_id,
                          has_active_owned_benefit, growth_opt_out,
                          marketing_pause_until, last_order_at,
                          created_at, updated_at
            """),
            {
                "tenant_id": tenant_id,
                "customer_id": str(customer_id),
                "repurchase_stage": repurchase_stage,
                "reactivation_priority": reactivation_priority,
                "reactivation_reason": reactivation_reason,
                "service_repair_status": service_repair_status,
                "service_repair_case_id": str(service_repair_case_id) if service_repair_case_id else None,
                "has_active_owned_benefit": has_active_owned_benefit,
                "growth_opt_out": growth_opt_out,
                "marketing_pause_until": marketing_pause_until,
                "last_order_at": last_order_at,
            },
        )
        row = result.fetchone()
        profile = dict(row._mapping)

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.profile.upserted",
                tenant_id=tenant_id,
                stream_id=str(customer_id),
                payload={"customer_id": str(customer_id), "repurchase_stage": repurchase_stage},
                source_service="tx-growth",
            )
        )
        logger.info(
            "growth_profile_upserted",
            customer_id=str(customer_id),
            tenant_id=tenant_id,
        )
        return profile

    # ------------------------------------------------------------------
    # 复购阶段更新（带状态机校验）
    # ------------------------------------------------------------------

    async def update_repurchase_stage(
        self, customer_id: UUID, stage: str, tenant_id: str, db: AsyncSession
    ) -> dict:
        """更新复购阶段（带状态机校验）

        状态流转: not_started -> first_order_done -> second_order_done -> stable_repeat
        """
        if stage not in self.VALID_REPURCHASE_STAGES:
            raise ValueError(f"Invalid repurchase_stage: {stage}")

        await self._set_tenant(db, tenant_id)

        # 查当前阶段
        current = await db.execute(
            text("""
                SELECT repurchase_stage
                FROM customer_growth_profiles
                WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
            """),
            {"tid": tenant_id, "cid": str(customer_id)},
        )
        current_row = current.fetchone()
        if current_row is None:
            raise ValueError(f"Growth profile not found for customer {customer_id}")

        current_stage = current_row._mapping["repurchase_stage"]
        current_order = self._REPURCHASE_ORDER.get(current_stage, -1)
        target_order = self._REPURCHASE_ORDER.get(stage, -1)

        if target_order <= current_order:
            raise ValueError(
                f"Cannot transition repurchase_stage from '{current_stage}' to '{stage}': "
                "only forward transitions allowed"
            )

        result = await db.execute(
            text("""
                UPDATE customer_growth_profiles
                SET repurchase_stage = :stage, updated_at = NOW()
                WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
                RETURNING id, tenant_id, customer_id, repurchase_stage,
                          reactivation_priority, reactivation_reason,
                          service_repair_status, created_at, updated_at
            """),
            {"tid": tenant_id, "cid": str(customer_id), "stage": stage},
        )
        row = result.fetchone()
        profile = dict(row._mapping)

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.repurchase_stage.changed",
                tenant_id=tenant_id,
                stream_id=str(customer_id),
                payload={
                    "customer_id": str(customer_id),
                    "from_stage": current_stage,
                    "to_stage": stage,
                },
                source_service="tx-growth",
            )
        )
        logger.info(
            "repurchase_stage_updated",
            customer_id=str(customer_id),
            from_stage=current_stage,
            to_stage=stage,
            tenant_id=tenant_id,
        )
        return profile

    # ------------------------------------------------------------------
    # 召回优先级更新
    # ------------------------------------------------------------------

    async def update_reactivation(
        self,
        customer_id: UUID,
        priority: str,
        reason: Optional[str],
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """更新召回优先级"""
        if priority not in self.VALID_REACTIVATION_PRIORITIES:
            raise ValueError(f"Invalid reactivation_priority: {priority}")

        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                UPDATE customer_growth_profiles
                SET reactivation_priority = :priority,
                    reactivation_reason = :reason,
                    updated_at = NOW()
                WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
                RETURNING id, tenant_id, customer_id, repurchase_stage,
                          reactivation_priority, reactivation_reason,
                          created_at, updated_at
            """),
            {
                "tid": tenant_id,
                "cid": str(customer_id),
                "priority": priority,
                "reason": reason,
            },
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"Growth profile not found for customer {customer_id}")

        profile = dict(row._mapping)

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.reactivation.updated",
                tenant_id=tenant_id,
                stream_id=str(customer_id),
                payload={
                    "customer_id": str(customer_id),
                    "priority": priority,
                    "reason": reason,
                },
                source_service="tx-growth",
            )
        )
        logger.info(
            "reactivation_updated",
            customer_id=str(customer_id),
            priority=priority,
            tenant_id=tenant_id,
        )
        return profile

    # ------------------------------------------------------------------
    # 服务修复状态更新
    # ------------------------------------------------------------------

    async def update_repair_status(
        self,
        customer_id: UUID,
        status: str,
        case_id: Optional[UUID],
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """更新服务修复状态"""
        if status not in self.VALID_REPAIR_STATUSES:
            raise ValueError(f"Invalid service_repair_status: {status}")

        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                UPDATE customer_growth_profiles
                SET service_repair_status = :status,
                    service_repair_case_id = :case_id,
                    updated_at = NOW()
                WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
                RETURNING id, tenant_id, customer_id, service_repair_status,
                          service_repair_case_id, created_at, updated_at
            """),
            {
                "tid": tenant_id,
                "cid": str(customer_id),
                "status": status,
                "case_id": str(case_id) if case_id else None,
            },
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"Growth profile not found for customer {customer_id}")

        profile = dict(row._mapping)

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.repair_status.updated",
                tenant_id=tenant_id,
                stream_id=str(customer_id),
                payload={
                    "customer_id": str(customer_id),
                    "status": status,
                    "case_id": str(case_id) if case_id else None,
                },
                source_service="tx-growth",
            )
        )
        logger.info(
            "repair_status_updated",
            customer_id=str(customer_id),
            status=status,
            tenant_id=tenant_id,
        )
        return profile

    # ------------------------------------------------------------------
    # 批量检测沉默客户
    # ------------------------------------------------------------------

    async def batch_detect_silent(
        self, tenant_id: str, db: AsyncSession
    ) -> dict:
        """批量检测沉默客户，更新reactivation_priority

        规则:
        - 首单后7天未二访 -> medium (no_second_visit)
        - 21天未到店 + has_active_owned_benefit -> high (benefit_expiring)
        - 30天未到店 -> high (silent_30d)
        - 45天未到店 -> critical (silent_45d)
        """
        await self._set_tenant(db, tenant_id)

        # 规则1: 45天未到店 → critical
        r45 = await db.execute(
            text("""
                UPDATE customer_growth_profiles
                SET reactivation_priority = 'critical',
                    reactivation_reason = 'silent_45d',
                    updated_at = NOW()
                WHERE tenant_id = :tid
                  AND is_deleted = false
                  AND reactivation_priority != 'critical'
                  AND last_order_at IS NOT NULL
                  AND last_order_at < NOW() - INTERVAL '45 days'
                  AND growth_opt_out = false
            """),
            {"tid": tenant_id},
        )
        count_45d = r45.rowcount

        # 规则2: 30天未到店 → high (silent_30d)
        r30 = await db.execute(
            text("""
                UPDATE customer_growth_profiles
                SET reactivation_priority = 'high',
                    reactivation_reason = 'silent_30d',
                    updated_at = NOW()
                WHERE tenant_id = :tid
                  AND is_deleted = false
                  AND reactivation_priority NOT IN ('critical', 'high')
                  AND last_order_at IS NOT NULL
                  AND last_order_at < NOW() - INTERVAL '30 days'
                  AND last_order_at >= NOW() - INTERVAL '45 days'
                  AND growth_opt_out = false
            """),
            {"tid": tenant_id},
        )
        count_30d = r30.rowcount

        # 规则3: 21天未到店 + has_active_owned_benefit → high (benefit_expiring)
        r21 = await db.execute(
            text("""
                UPDATE customer_growth_profiles
                SET reactivation_priority = 'high',
                    reactivation_reason = 'benefit_expiring',
                    updated_at = NOW()
                WHERE tenant_id = :tid
                  AND is_deleted = false
                  AND reactivation_priority NOT IN ('critical', 'high')
                  AND last_order_at IS NOT NULL
                  AND last_order_at < NOW() - INTERVAL '21 days'
                  AND last_order_at >= NOW() - INTERVAL '30 days'
                  AND has_active_owned_benefit = true
                  AND growth_opt_out = false
            """),
            {"tid": tenant_id},
        )
        count_21d = r21.rowcount

        # 规则4: 首单后7天未二访 → medium (no_second_visit)
        r7 = await db.execute(
            text("""
                UPDATE customer_growth_profiles
                SET reactivation_priority = 'medium',
                    reactivation_reason = 'no_second_visit',
                    updated_at = NOW()
                WHERE tenant_id = :tid
                  AND is_deleted = false
                  AND reactivation_priority NOT IN ('critical', 'high', 'medium')
                  AND repurchase_stage = 'first_order_done'
                  AND last_order_at IS NOT NULL
                  AND last_order_at < NOW() - INTERVAL '7 days'
                  AND growth_opt_out = false
            """),
            {"tid": tenant_id},
        )
        count_7d = r7.rowcount

        total_updated = count_45d + count_30d + count_21d + count_7d

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.silent_detection.completed",
                tenant_id=tenant_id,
                stream_id=tenant_id,
                payload={
                    "total_updated": total_updated,
                    "critical_45d": count_45d,
                    "high_30d": count_30d,
                    "high_benefit_expiring": count_21d,
                    "medium_no_second_visit": count_7d,
                },
                source_service="tx-growth",
            )
        )
        logger.info(
            "batch_detect_silent_completed",
            tenant_id=tenant_id,
            total_updated=total_updated,
            critical_45d=count_45d,
            high_30d=count_30d,
            high_benefit_expiring=count_21d,
            medium_no_second_visit=count_7d,
        )
        return {
            "total_updated": total_updated,
            "critical_45d": count_45d,
            "high_30d": count_30d,
            "high_benefit_expiring": count_21d,
            "medium_no_second_visit": count_7d,
        }
