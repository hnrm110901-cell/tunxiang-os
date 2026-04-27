"""信任分级管理 — 对标 ServiceNow AI Control Tower"""

import json
from uuid import uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


# ── 信任等级序号映射 ───────────────────────────────────────────
_TIER_ORDER = {"T0": 0, "T1": 1, "T2": 2, "T3": 3, "T4": 4}


class ForgeTrustService:
    """信任分级管理 — 对标 ServiceNow AI Control Tower"""

    TIER_POLICIES: dict[str, dict] = {
        "T0": {"data_access": "none", "action_scope": "none", "financial": False},
        "T1": {"data_access": "read", "action_scope": "none", "financial": False},
        "T2": {"data_access": "read_write", "action_scope": "non_financial", "financial": False},
        "T3": {"data_access": "read_write", "action_scope": "all", "financial": True},
        "T4": {"data_access": "full", "action_scope": "all", "financial": True},
    }

    # ── 获取信任等级定义 ─────────────────────────────────────────
    async def get_tier_definitions(self, db: AsyncSession) -> list[dict]:
        """返回所有信任等级定义，按 sort_order 排序"""
        result = await db.execute(
            text("""
                SELECT tier_id, tier_name, description, sort_order,
                       data_access, action_scope, financial_allowed,
                       created_at
                FROM forge_trust_tiers
                ORDER BY sort_order ASC
            """),
        )
        rows = result.mappings().all()
        if not rows:
            # 回退到内存定义
            return [{"tier_id": k, "policy": v, "sort_order": i} for i, (k, v) in enumerate(self.TIER_POLICIES.items())]
        return [dict(r) for r in rows]

    # ── 获取应用信任状态 ─────────────────────────────────────────
    async def get_app_trust_status(self, db: AsyncSession, app_id: str) -> dict:
        """获取应用当前信任等级、最近审计记录和违规统计"""
        # 1. 当前信任等级
        policy_result = await db.execute(
            text("""
                SELECT app_id, trust_tier, allowed_entities, allowed_actions,
                       denied_actions, token_budget_daily, rate_limit_rpm,
                       sandbox_mode, kill_switch, updated_at
                FROM forge_runtime_policies
                WHERE app_id = :app_id AND is_deleted = false
            """),
            {"app_id": app_id},
        )
        policy_row = policy_result.mappings().first()
        if not policy_row:
            raise HTTPException(status_code=404, detail=f"应用运行时策略不存在: {app_id}")

        current_tier = policy_row["trust_tier"]
        tier_name = current_tier
        tier_policy = self.TIER_POLICIES.get(current_tier, {})

        # 2. 最近 10 条审计记录
        audit_result = await db.execute(
            text("""
                SELECT audit_id, audit_type, previous_tier, requested_tier,
                       auditor_id, evidence, status, created_at
                FROM forge_trust_audits
                WHERE app_id = :app_id AND is_deleted = false
                ORDER BY created_at DESC
                LIMIT 10
            """),
            {"app_id": app_id},
        )
        recent_audits = [dict(r) for r in audit_result.mappings().all()]

        # 3. 最近 30 天违规计数
        violation_result = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM forge_runtime_violations
                WHERE app_id = :app_id
                  AND is_deleted = false
                  AND created_at >= NOW() - INTERVAL '30 days'
            """),
            {"app_id": app_id},
        )
        violation_count_30d = violation_result.scalar_one()

        return {
            "app_id": app_id,
            "current_tier": current_tier,
            "tier_name": tier_name,
            "policy": tier_policy,
            "recent_audits": recent_audits,
            "violation_count_30d": violation_count_30d,
        }

    # ── 提交信任审计 ─────────────────────────────────────────────
    async def submit_trust_audit(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        requested_tier: str,
        auditor_id: str,
        evidence: dict | None = None,
    ) -> dict:
        """直接执行信任等级变更（管理员操作）"""
        if evidence is None:
            evidence = {}

        # 校验目标等级
        if requested_tier not in self.TIER_POLICIES:
            raise HTTPException(
                status_code=422,
                detail=f"无效信任等级: {requested_tier}，可选: {sorted(self.TIER_POLICIES)}",
            )

        # 获取当前等级
        current_result = await db.execute(
            text("""
                SELECT trust_tier FROM forge_runtime_policies
                WHERE app_id = :app_id AND is_deleted = false
            """),
            {"app_id": app_id},
        )
        current_row = current_result.mappings().first()
        if not current_row:
            raise HTTPException(status_code=404, detail=f"应用运行时策略不存在: {app_id}")

        previous_tier = current_row["trust_tier"]

        # 判断审计类型
        old_order = _TIER_ORDER.get(previous_tier, 0)
        new_order = _TIER_ORDER.get(requested_tier, 0)
        if new_order > old_order:
            audit_type = "upgrade"
        elif new_order < old_order:
            audit_type = "downgrade"
        else:
            audit_type = "reconfirm"

        audit_id = f"audit_{uuid4().hex[:12]}"
        new_policy = self.TIER_POLICIES[requested_tier]

        # 插入审计记录
        await db.execute(
            text("""
                INSERT INTO forge_trust_audits
                    (id, tenant_id, audit_id, app_id, audit_type,
                     previous_tier, requested_tier, auditor_id,
                     evidence, status, created_at)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :audit_id, :app_id, :audit_type,
                     :previous_tier, :requested_tier, :auditor_id,
                     :evidence::jsonb, 'approved', NOW())
            """),
            {
                "audit_id": audit_id,
                "app_id": app_id,
                "audit_type": audit_type,
                "previous_tier": previous_tier,
                "requested_tier": requested_tier,
                "auditor_id": auditor_id,
                "evidence": json.dumps(evidence, ensure_ascii=False),
            },
        )

        # 更新运行时策略
        await db.execute(
            text("""
                UPDATE forge_runtime_policies
                SET trust_tier = :tier,
                    updated_at = NOW()
                WHERE app_id = :app_id AND is_deleted = false
            """),
            {"tier": requested_tier, "app_id": app_id},
        )

        log.info(
            "trust_audit_submitted",
            app_id=app_id,
            audit_id=audit_id,
            audit_type=audit_type,
            from_tier=previous_tier,
            to_tier=requested_tier,
        )

        return {
            "audit_id": audit_id,
            "app_id": app_id,
            "audit_type": audit_type,
            "previous_tier": previous_tier,
            "requested_tier": requested_tier,
            "status": "approved",
        }

    # ── 请求信任升级 ─────────────────────────────────────────────
    async def request_upgrade(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        target_tier: str,
        evidence: dict,
    ) -> dict:
        """应用自助申请信任升级（仅允许逐级升级）"""
        if target_tier not in self.TIER_POLICIES:
            raise HTTPException(
                status_code=422,
                detail=f"无效信任等级: {target_tier}，可选: {sorted(self.TIER_POLICIES)}",
            )

        # 获取当前等级
        current_result = await db.execute(
            text("""
                SELECT trust_tier FROM forge_runtime_policies
                WHERE app_id = :app_id AND is_deleted = false
            """),
            {"app_id": app_id},
        )
        current_row = current_result.mappings().first()
        if not current_row:
            raise HTTPException(status_code=404, detail=f"应用运行时策略不存在: {app_id}")

        current_tier = current_row["trust_tier"]
        current_order = _TIER_ORDER.get(current_tier, 0)
        target_order = _TIER_ORDER.get(target_tier, 0)

        # 只允许逐级升级
        if target_order != current_order + 1:
            raise HTTPException(
                status_code=422,
                detail=f"只允许逐级升级: 当前 {current_tier}，只能升级到 T{current_order + 1}",
            )

        # 检查升级前置条件
        requirements_met = True
        requirement_errors: list[str] = []

        if target_order >= 2:
            # T2+ 要求：3个月以上运行历史 + 评分 >= 4.0
            history_result = await db.execute(
                text("""
                    SELECT
                        created_at,
                        EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400 AS days_active
                    FROM forge_runtime_policies
                    WHERE app_id = :app_id AND is_deleted = false
                """),
                {"app_id": app_id},
            )
            history_row = history_result.mappings().first()
            if history_row and history_row["days_active"] < 90:
                requirements_met = False
                requirement_errors.append(f"运行时间不足 90 天 (当前 {int(history_row['days_active'])} 天)")

            rating_result = await db.execute(
                text("""
                    SELECT rating FROM forge_apps
                    WHERE app_id = :app_id AND is_deleted = false
                """),
                {"app_id": app_id},
            )
            rating_row = rating_result.mappings().first()
            if rating_row and (rating_row["rating"] or 0) < 4.0:
                requirements_met = False
                requirement_errors.append(f"评分低于 4.0 (当前 {rating_row['rating']})")

        # 创建待审核记录
        audit_id = f"audit_{uuid4().hex[:12]}"
        await db.execute(
            text("""
                INSERT INTO forge_trust_audits
                    (id, tenant_id, audit_id, app_id, audit_type,
                     previous_tier, requested_tier, auditor_id,
                     evidence, status, created_at)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :audit_id, :app_id, 'upgrade',
                     :previous_tier, :requested_tier, :app_id,
                     :evidence::jsonb, 'pending_review', NOW())
            """),
            {
                "audit_id": audit_id,
                "app_id": app_id,
                "previous_tier": current_tier,
                "requested_tier": target_tier,
                "evidence": json.dumps(evidence, ensure_ascii=False),
            },
        )

        log.info(
            "trust_upgrade_requested",
            app_id=app_id,
            audit_id=audit_id,
            from_tier=current_tier,
            to_tier=target_tier,
            requirements_met=requirements_met,
        )

        return {
            "audit_id": audit_id,
            "app_id": app_id,
            "current_tier": current_tier,
            "target_tier": target_tier,
            "status": "pending_review",
            "requirements_met": requirements_met,
            "requirement_errors": requirement_errors,
        }

    # ── 自动降级 ─────────────────────────────────────────────────
    async def auto_downgrade(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        reason: str,
    ) -> dict:
        """违规超限时触发自动降级（每次降一级，不低于 T0）"""
        # 获取当前等级
        current_result = await db.execute(
            text("""
                SELECT trust_tier FROM forge_runtime_policies
                WHERE app_id = :app_id AND is_deleted = false
            """),
            {"app_id": app_id},
        )
        current_row = current_result.mappings().first()
        if not current_row:
            raise HTTPException(status_code=404, detail=f"应用运行时策略不存在: {app_id}")

        current_tier = current_row["trust_tier"]
        current_order = _TIER_ORDER.get(current_tier, 0)

        # 降一级，不低于 T0
        new_order = max(0, current_order - 1)
        new_tier = f"T{new_order}"

        if new_tier == current_tier:
            log.warning(
                "auto_downgrade_already_t0",
                app_id=app_id,
                reason=reason,
            )
            return {
                "app_id": app_id,
                "previous_tier": current_tier,
                "new_tier": new_tier,
                "downgraded": False,
                "reason": "已在最低等级 T0",
            }

        # 插入降级审计记录
        audit_id = f"audit_{uuid4().hex[:12]}"
        await db.execute(
            text("""
                INSERT INTO forge_trust_audits
                    (id, tenant_id, audit_id, app_id, audit_type,
                     previous_tier, requested_tier, auditor_id,
                     evidence, status, created_at)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :audit_id, :app_id, 'downgrade',
                     :previous_tier, :new_tier, 'system',
                     :evidence::jsonb, 'approved', NOW())
            """),
            {
                "audit_id": audit_id,
                "app_id": app_id,
                "previous_tier": current_tier,
                "new_tier": new_tier,
                "evidence": json.dumps({"reason": reason}, ensure_ascii=False),
            },
        )

        # 更新运行时策略
        await db.execute(
            text("""
                UPDATE forge_runtime_policies
                SET trust_tier = :tier,
                    updated_at = NOW()
                WHERE app_id = :app_id AND is_deleted = false
            """),
            {"tier": new_tier, "app_id": app_id},
        )

        log.warning(
            "trust_auto_downgrade",
            app_id=app_id,
            audit_id=audit_id,
            from_tier=current_tier,
            to_tier=new_tier,
            reason=reason,
        )

        return {
            "app_id": app_id,
            "audit_id": audit_id,
            "previous_tier": current_tier,
            "new_tier": new_tier,
            "downgraded": True,
            "reason": reason,
        }
