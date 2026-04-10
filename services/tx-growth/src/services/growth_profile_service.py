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

    # ── P1 心理距离分层 ──
    VALID_PSYCH_DISTANCE = ("near", "habit_break", "fading", "abstracted", "lost")
    # near: 近距离，最近7天内有互动(消费/打开触达/回复)
    # habit_break: 习惯中断，7-21天无互动但有历史高频
    # fading: 渐远，21-45天无互动
    # abstracted: 抽象化，45-90天无互动
    # lost: 失联，90天+无互动

    # ── P1 超级用户分层 ──
    VALID_SUPER_USER = ("none", "potential", "active", "advocate")
    # none: 普通客户
    # potential: 潜在超级用户 (CLV top 10% 且 复购>=3次)
    # active: 活跃超级用户 (CLV top 5% 且 复购>=6次 且 有推荐行为)
    # advocate: 品牌代言人 (CLV top 3% 且 有成功推荐>=2人)

    # ── P1 成长里程碑 ──
    VALID_MILESTONES = ("newcomer", "regular", "loyal", "vip", "legend")
    # newcomer: 新客(1-2次消费)
    # regular: 常客(3-5次)
    # loyal: 忠实客(6-11次)
    # vip: VIP客(12-23次)
    # legend: 传奇客(24次+)

    # ── P1 裂变场景 ──
    VALID_REFERRAL_SCENARIOS = ("none", "birthday_organizer", "family_host", "corporate_host", "super_referrer")

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

    # ------------------------------------------------------------------
    # P1: 心理距离分层计算
    # ------------------------------------------------------------------

    async def batch_compute_psych_distance(
        self, tenant_id: str, db: AsyncSession
    ) -> dict:
        """批量计算客户心理距离分层

        规则（基于最后互动时间，互动=消费/触达打开/触达回复）:
        - near: last_interaction <= 7天
        - habit_break: 7天 < last_interaction <= 21天
        - fading: 21天 < last_interaction <= 45天
        - abstracted: 45天 < last_interaction <= 90天
        - lost: last_interaction > 90天
        """
        await self._set_tenant(db, tenant_id)

        # 计算最后互动时间 = MAX(last_order_at, last_growth_touch_at, 最后打开触达时间)
        result = await db.execute(text("""
            WITH last_interaction AS (
                SELECT
                    cgp.customer_id,
                    GREATEST(
                        cgp.last_order_at,
                        cgp.last_growth_touch_at,
                        (SELECT MAX(gte.opened_at) FROM growth_touch_executions gte
                         WHERE gte.customer_id = cgp.customer_id
                           AND gte.is_deleted = FALSE AND gte.opened_at IS NOT NULL)
                    ) AS last_at
                FROM customer_growth_profiles cgp
                WHERE cgp.is_deleted = FALSE
            )
            UPDATE customer_growth_profiles cgp SET
                psych_distance_level = CASE
                    WHEN li.last_at >= NOW() - INTERVAL '7 days' THEN 'near'
                    WHEN li.last_at >= NOW() - INTERVAL '21 days' THEN 'habit_break'
                    WHEN li.last_at >= NOW() - INTERVAL '45 days' THEN 'fading'
                    WHEN li.last_at >= NOW() - INTERVAL '90 days' THEN 'abstracted'
                    WHEN li.last_at IS NOT NULL THEN 'lost'
                    ELSE 'lost'
                END,
                updated_at = NOW()
            FROM last_interaction li
            WHERE cgp.customer_id = li.customer_id AND cgp.is_deleted = FALSE
            RETURNING cgp.customer_id, cgp.psych_distance_level
        """))
        rows = result.fetchall()

        dist: dict[str, int] = {}
        for r in rows:
            level = r[1]
            dist[level] = dist.get(level, 0) + 1

        logger.info("batch_psych_distance_done", tenant_id=tenant_id, total=len(rows), distribution=dist)
        return {"total_updated": len(rows), "distribution": dist}

    # ------------------------------------------------------------------
    # P1: 超级用户分层计算
    # ------------------------------------------------------------------

    async def batch_compute_super_user(
        self, tenant_id: str, db: AsyncSession
    ) -> dict:
        """批量计算超级用户分层

        规则:
        - advocate: CLV top 3% 且 消费>=24次
        - active: CLV top 5% 且 复购>=6次
        - potential: CLV top 10% 且 复购>=3次
        - none: 其余
        """
        await self._set_tenant(db, tenant_id)

        # 先算CLV百分位阈值
        percentiles = await db.execute(text("""
            SELECT
                PERCENTILE_CONT(0.97) WITHIN GROUP (ORDER BY c.total_order_amount_fen) AS p97,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY c.total_order_amount_fen) AS p95,
                PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY c.total_order_amount_fen) AS p90
            FROM customers c
            WHERE c.is_deleted = FALSE AND c.total_order_count > 0
        """))
        p = percentiles.fetchone()
        if not p or p[0] is None:
            return {"total_updated": 0, "distribution": {}}

        p97, p95, p90 = int(p[0] or 0), int(p[1] or 0), int(p[2] or 0)

        result = await db.execute(text("""
            UPDATE customer_growth_profiles cgp SET
                super_user_level = CASE
                    WHEN c.total_order_amount_fen >= :p97 AND c.total_order_count >= 24 THEN 'advocate'
                    WHEN c.total_order_amount_fen >= :p95 AND c.total_order_count >= 6 THEN 'active'
                    WHEN c.total_order_amount_fen >= :p90 AND c.total_order_count >= 3 THEN 'potential'
                    ELSE 'none'
                END,
                updated_at = NOW()
            FROM customers c
            WHERE c.id = cgp.customer_id AND cgp.is_deleted = FALSE AND c.is_deleted = FALSE
            RETURNING cgp.customer_id, cgp.super_user_level
        """), {"p97": p97, "p95": p95, "p90": p90})

        rows = result.fetchall()
        dist: dict[str, int] = {}
        for r in rows:
            level = r[1]
            dist[level] = dist.get(level, 0) + 1

        logger.info("batch_super_user_done", tenant_id=tenant_id, total=len(rows), distribution=dist)
        return {"total_updated": len(rows), "distribution": dist}

    # ------------------------------------------------------------------
    # P1: 成长里程碑计算
    # ------------------------------------------------------------------

    async def batch_compute_milestones(
        self, tenant_id: str, db: AsyncSession
    ) -> dict:
        """批量计算成长里程碑

        规则基于消费次数:
        - newcomer: 1-2次
        - regular: 3-5次
        - loyal: 6-11次
        - vip: 12-23次
        - legend: 24次+
        """
        await self._set_tenant(db, tenant_id)

        result = await db.execute(text("""
            UPDATE customer_growth_profiles cgp SET
                growth_milestone_stage = CASE
                    WHEN c.total_order_count >= 24 THEN 'legend'
                    WHEN c.total_order_count >= 12 THEN 'vip'
                    WHEN c.total_order_count >= 6 THEN 'loyal'
                    WHEN c.total_order_count >= 3 THEN 'regular'
                    WHEN c.total_order_count >= 1 THEN 'newcomer'
                    ELSE NULL
                END,
                updated_at = NOW()
            FROM customers c
            WHERE c.id = cgp.customer_id AND cgp.is_deleted = FALSE AND c.is_deleted = FALSE
            RETURNING cgp.customer_id, cgp.growth_milestone_stage
        """))
        rows = result.fetchall()
        dist: dict[str, int] = {}
        for r in rows:
            stage = r[1]
            if stage:
                dist[stage] = dist.get(stage, 0) + 1

        logger.info("batch_milestones_done", tenant_id=tenant_id, total=len(rows), distribution=dist)
        return {"total_updated": len(rows), "distribution": dist}

    # ------------------------------------------------------------------
    # P1: 裂变场景识别
    # ------------------------------------------------------------------

    async def batch_compute_referral_scenario(
        self, tenant_id: str, db: AsyncSession
    ) -> dict:
        """批量识别裂变场景

        P1简化版：基于消费金额和频次粗判
        - super_referrer: super_user_level in (active, advocate)
        - corporate_host: 消费>=6次 且 客单价>=500元
        - family_host: 消费>=4次 且 客单价>=300元
        - birthday_organizer: 消费>=3次 且 客单价>=200元
        - none: 其余
        """
        await self._set_tenant(db, tenant_id)

        result = await db.execute(text("""
            UPDATE customer_growth_profiles cgp SET
                referral_scenario = CASE
                    WHEN cgp.super_user_level IN ('active', 'advocate') THEN 'super_referrer'
                    WHEN c.total_order_count >= 6 AND c.total_order_amount_fen / GREATEST(c.total_order_count, 1) >= 50000
                        THEN 'corporate_host'
                    WHEN c.total_order_count >= 4 AND c.total_order_amount_fen / GREATEST(c.total_order_count, 1) >= 30000
                        THEN 'family_host'
                    WHEN c.total_order_count >= 3 AND c.total_order_amount_fen / GREATEST(c.total_order_count, 1) >= 20000
                        THEN 'birthday_organizer'
                    ELSE 'none'
                END,
                updated_at = NOW()
            FROM customers c
            WHERE c.id = cgp.customer_id AND cgp.is_deleted = FALSE AND c.is_deleted = FALSE
            RETURNING cgp.customer_id, cgp.referral_scenario
        """))
        rows = result.fetchall()
        dist: dict[str, int] = {}
        for r in rows:
            scenario = r[1]
            if scenario and scenario != 'none':
                dist[scenario] = dist.get(scenario, 0) + 1

        logger.info("batch_referral_scenario_done", tenant_id=tenant_id, total=len(rows), distribution=dist)
        return {"total_updated": len(rows), "distribution": dist}

    # ------------------------------------------------------------------
    # P1: 统一批量计算入口
    # ------------------------------------------------------------------

    async def batch_compute_p1_fields(
        self, tenant_id: str, db: AsyncSession
    ) -> dict:
        """P1字段统一批量计算（每日定时调用）"""
        results: dict[str, dict] = {}
        results["psych_distance"] = await self.batch_compute_psych_distance(tenant_id, db)
        results["super_user"] = await self.batch_compute_super_user(tenant_id, db)
        results["milestones"] = await self.batch_compute_milestones(tenant_id, db)
        results["referral_scenario"] = await self.batch_compute_referral_scenario(tenant_id, db)
        results["stored_value"] = await self.batch_sync_stored_value(tenant_id, db)
        results["banquet"] = await self.batch_sync_banquet_info(tenant_id, db)
        results["channel"] = await self.batch_sync_channel_info(tenant_id, db)

        logger.info("batch_p1_fields_all_done", tenant_id=tenant_id, results=results)
        return results

    # ------------------------------------------------------------------
    # V2.1: 储值/宴席/渠道画像同步
    # ------------------------------------------------------------------

    async def batch_sync_stored_value(self, tenant_id: str, db: AsyncSession) -> dict:
        """同步储值卡余额到增长画像（从stored_value_cards表）"""
        await self._set_tenant(db, tenant_id)
        result = await db.execute(text("""
            UPDATE customer_growth_profiles cgp SET
                stored_value_balance_fen = COALESCE(svc.total_balance, 0),
                updated_at = NOW()
            FROM (
                SELECT customer_id, SUM(balance_fen) AS total_balance
                FROM stored_value_cards
                WHERE status = 'active' AND is_deleted = FALSE
                GROUP BY customer_id
            ) svc
            WHERE cgp.customer_id = svc.customer_id AND cgp.is_deleted = FALSE
            RETURNING cgp.customer_id
        """))
        count = len(result.fetchall())
        logger.info("batch_sync_stored_value_done", tenant_id=tenant_id, updated=count)
        return {"updated": count}

    async def batch_sync_banquet_info(self, tenant_id: str, db: AsyncSession) -> dict:
        """同步宴席消费信息到增长画像（从orders表判断高客单包厢消费）"""
        await self._set_tenant(db, tenant_id)
        # 简化方案：客单价>=50000分(500元)且状态paid的订单视为宴席
        result = await db.execute(text("""
            UPDATE customer_growth_profiles cgp SET
                last_banquet_at = banquet.last_at,
                last_banquet_store_id = banquet.last_store,
                updated_at = NOW()
            FROM (
                SELECT customer_id,
                       MAX(created_at) AS last_at,
                       (ARRAY_AGG(store_id ORDER BY created_at DESC))[1] AS last_store
                FROM orders
                WHERE is_deleted = FALSE
                  AND total_amount_fen >= 50000
                  AND status = 'paid'
                GROUP BY customer_id
            ) banquet
            WHERE cgp.customer_id = banquet.customer_id AND cgp.is_deleted = FALSE
            RETURNING cgp.customer_id
        """))
        count = len(result.fetchall())
        logger.info("batch_sync_banquet_done", tenant_id=tenant_id, updated=count)
        return {"updated": count}

    async def batch_sync_channel_info(self, tenant_id: str, db: AsyncSession) -> dict:
        """同步渠道来源信息到增长画像（统计各渠道订单占比）"""
        await self._set_tenant(db, tenant_id)
        result = await db.execute(text("""
            UPDATE customer_growth_profiles cgp SET
                primary_channel = ch.primary_ch,
                channel_order_count = ch.ch_count,
                brand_order_count = ch.brand_count,
                updated_at = NOW()
            FROM (
                SELECT
                    customer_id,
                    MODE() WITHIN GROUP (ORDER BY COALESCE(source, 'dine_in')) AS primary_ch,
                    COUNT(*) FILTER (WHERE source IN ('meituan', 'douyin', 'eleme')) AS ch_count,
                    COUNT(*) FILTER (WHERE source NOT IN ('meituan', 'douyin', 'eleme') OR source IS NULL) AS brand_count
                FROM orders
                WHERE is_deleted = FALSE AND status = 'paid'
                GROUP BY customer_id
            ) ch
            WHERE cgp.customer_id = ch.customer_id AND cgp.is_deleted = FALSE
            RETURNING cgp.customer_id
        """))
        count = len(result.fetchall())
        logger.info("batch_sync_channel_done", tenant_id=tenant_id, updated=count)
        return {"updated": count}
