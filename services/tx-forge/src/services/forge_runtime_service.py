"""运行时策略管理 — Agent 权限沙箱"""

import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

log = structlog.get_logger(__name__)


# ── 允许通过 update_policy 修改的字段 ──────────────────────────
_ALLOWED_POLICY_FIELDS: set[str] = {
    "allowed_entities",
    "allowed_actions",
    "denied_actions",
    "token_budget_daily",
    "rate_limit_rpm",
    "sandbox_mode",
    "auto_downgrade_threshold",
}

# ── 不允许直接修改的字段（需走专用流程）──────────────────────────
_PROTECTED_FIELDS: set[str] = {"trust_tier", "kill_switch"}

# ── 违规严重级别 ──────────────────────────────────────────────
VIOLATION_SEVERITIES: set[str] = {"P0", "P1", "P2", "P3"}

VIOLATION_TYPES: set[str] = {
    "unauthorized_access",
    "rate_limit_exceeded",
    "budget_exceeded",
    "policy_violation",
    "kill_switched",
    "data_breach_attempt",
    "financial_unauthorized",
}


class ForgeRuntimeService:
    """运行时策略管理 — Agent 权限沙箱"""

    # ── 获取运行时策略 ───────────────────────────────────────────
    async def get_policy(self, db: AsyncSession, app_id: str) -> dict:
        """获取应用的运行时策略，不存在则创建默认 T0 策略"""
        result = await db.execute(
            text("""
                SELECT app_id, trust_tier, allowed_entities, allowed_actions,
                       denied_actions, token_budget_daily, rate_limit_rpm,
                       sandbox_mode, kill_switch, auto_downgrade_threshold,
                       created_at, updated_at
                FROM forge_runtime_policies
                WHERE app_id = :app_id AND is_deleted = false
            """),
            {"app_id": app_id},
        )
        row = result.mappings().first()

        if row:
            return dict(row)

        # 不存在 → 创建默认 T0 策略
        default_result = await db.execute(
            text("""
                INSERT INTO forge_runtime_policies
                    (id, tenant_id, app_id, trust_tier,
                     allowed_entities, allowed_actions, denied_actions,
                     token_budget_daily, rate_limit_rpm,
                     sandbox_mode, kill_switch, auto_downgrade_threshold)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :app_id, 'T0',
                     '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                     0, 60,
                     true, false, 3)
                RETURNING app_id, trust_tier, allowed_entities, allowed_actions,
                          denied_actions, token_budget_daily, rate_limit_rpm,
                          sandbox_mode, kill_switch, auto_downgrade_threshold,
                          created_at, updated_at
            """),
            {"app_id": app_id},
        )
        new_row = default_result.mappings().one()
        log.info("runtime_policy_created_default", app_id=app_id, tier="T0")
        return dict(new_row)

    # ── 更新运行时策略 ───────────────────────────────────────────
    async def update_policy(
        self, db: AsyncSession, app_id: str, updates: dict
    ) -> dict:
        """更新运行时策略（不可直接改 trust_tier / kill_switch）"""
        # 拦截受保护字段
        protected_in_request = _PROTECTED_FIELDS & set(updates.keys())
        if protected_in_request:
            raise HTTPException(
                status_code=422,
                detail=f"不可直接修改: {sorted(protected_in_request)}，请使用专用接口",
            )

        filtered = {k: v for k, v in updates.items() if k in _ALLOWED_POLICY_FIELDS}
        if not filtered:
            raise HTTPException(
                status_code=422,
                detail=f"无有效更新字段，允许: {sorted(_ALLOWED_POLICY_FIELDS)}",
            )

        # 构建动态 SET 子句
        jsonb_fields = {"allowed_entities", "allowed_actions", "denied_actions"}
        set_parts: list[str] = []
        params: dict = {"app_id": app_id}

        for k, v in filtered.items():
            if k in jsonb_fields:
                set_parts.append(f"{k} = :{k}::jsonb")
                params[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
            else:
                set_parts.append(f"{k} = :{k}")
                params[k] = v

        set_clause = ", ".join(set_parts)

        result = await db.execute(
            text(f"""
                UPDATE forge_runtime_policies
                SET {set_clause}, updated_at = NOW()
                WHERE app_id = :app_id AND is_deleted = false
                RETURNING app_id, trust_tier, allowed_entities, allowed_actions,
                          denied_actions, token_budget_daily, rate_limit_rpm,
                          sandbox_mode, kill_switch, auto_downgrade_threshold,
                          updated_at
            """),
            params,
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"应用运行时策略不存在: {app_id}")

        log.info("runtime_policy_updated", app_id=app_id, fields=list(filtered.keys()))
        return dict(row)

    # ── 激活熔断开关 ─────────────────────────────────────────────
    async def activate_kill_switch(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        operator_id: str,
        reason: str,
    ) -> dict:
        """激活熔断开关 — 立即禁止应用所有操作"""
        result = await db.execute(
            text("""
                UPDATE forge_runtime_policies
                SET kill_switch = true, updated_at = NOW()
                WHERE app_id = :app_id AND is_deleted = false
                RETURNING app_id, trust_tier, kill_switch, updated_at
            """),
            {"app_id": app_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"应用运行时策略不存在: {app_id}")

        # 记录 P0 违规
        violation_id = f"vio_{uuid4().hex[:12]}"
        await db.execute(
            text("""
                INSERT INTO forge_runtime_violations
                    (id, tenant_id, violation_id, app_id, agent_id,
                     violation_type, severity, context,
                     resolved, created_at)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :violation_id, :app_id, NULL,
                     'kill_switched', 'P0',
                     :context::jsonb,
                     false, NOW())
            """),
            {
                "violation_id": violation_id,
                "app_id": app_id,
                "context": json.dumps(
                    {"operator_id": operator_id, "reason": reason},
                    ensure_ascii=False,
                ),
            },
        )

        log.critical(
            "kill_switch_activated",
            app_id=app_id,
            operator_id=operator_id,
            reason=reason,
        )

        return {
            "app_id": app_id,
            "kill_switch": True,
            "killed_at": str(row["updated_at"]),
            "killed_by": operator_id,
            "reason": reason,
            "violation_id": violation_id,
        }

    # ── 解除熔断开关 ─────────────────────────────────────────────
    async def deactivate_kill_switch(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        operator_id: str,
    ) -> dict:
        """解除熔断开关"""
        result = await db.execute(
            text("""
                UPDATE forge_runtime_policies
                SET kill_switch = false, updated_at = NOW()
                WHERE app_id = :app_id AND is_deleted = false
                RETURNING app_id, trust_tier, kill_switch, updated_at
            """),
            {"app_id": app_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"应用运行时策略不存在: {app_id}")

        log.info(
            "kill_switch_deactivated",
            app_id=app_id,
            operator_id=operator_id,
        )

        return {
            "app_id": app_id,
            "kill_switch": False,
            "deactivated_at": str(row["updated_at"]),
            "deactivated_by": operator_id,
        }

    # ── 权限检查 ─────────────────────────────────────────────────
    async def check_permission(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        entity: str,
        action: str,
        is_financial: bool = False,
    ) -> dict:
        """检查应用是否有权执行指定操作"""
        from .forge_trust_service import ForgeTrustService

        policy = await self.get_policy(db, app_id)

        # 1. 熔断开关 → 全部拒绝
        if policy.get("kill_switch"):
            return {
                "allowed": False,
                "reason": "熔断开关已激活，所有操作被禁止",
                "tier": policy["trust_tier"],
            }

        tier = policy["trust_tier"]
        tier_policy = ForgeTrustService.TIER_POLICIES.get(tier, {})

        # 2. 数据访问级别检查
        data_access = tier_policy.get("data_access", "none")
        if data_access == "none":
            return {
                "allowed": False,
                "reason": f"信任等级 {tier} 不允许任何数据访问",
                "tier": tier,
            }

        # 3. 实体白名单检查
        allowed_entities = policy.get("allowed_entities") or []
        if isinstance(allowed_entities, str):
            allowed_entities = json.loads(allowed_entities)
        if allowed_entities and entity not in allowed_entities:
            return {
                "allowed": False,
                "reason": f"实体 {entity} 不在允许列表中",
                "tier": tier,
            }

        # 4. 操作黑名单检查
        denied_actions = policy.get("denied_actions") or []
        if isinstance(denied_actions, str):
            denied_actions = json.loads(denied_actions)
        if action in denied_actions:
            return {
                "allowed": False,
                "reason": f"操作 {action} 在拒绝列表中",
                "tier": tier,
            }

        # 5. 操作白名单 / 操作范围检查
        action_scope = tier_policy.get("action_scope", "none")
        if action_scope == "none":
            return {
                "allowed": False,
                "reason": f"信任等级 {tier} 不允许任何操作",
                "tier": tier,
            }

        allowed_actions = policy.get("allowed_actions") or []
        if isinstance(allowed_actions, str):
            allowed_actions = json.loads(allowed_actions)
        if allowed_actions and action not in allowed_actions:
            if action_scope != "all":
                return {
                    "allowed": False,
                    "reason": f"操作 {action} 不在允许列表中",
                    "tier": tier,
                }

        # 6. 金融操作检查
        if is_financial and not tier_policy.get("financial", False):
            return {
                "allowed": False,
                "reason": f"信任等级 {tier} 不允许金融操作",
                "tier": tier,
            }

        return {
            "allowed": True,
            "reason": "权限检查通过",
            "tier": tier,
        }

    # ── 记录违规 ─────────────────────────────────────────────────
    async def record_violation(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        agent_id: str | None = None,
        violation_type: str,
        severity: str = "P2",
        context: dict | None = None,
    ) -> dict:
        """记录运行时违规并检查是否需要自动降级"""
        if context is None:
            context = {}

        if severity not in VIOLATION_SEVERITIES:
            raise HTTPException(
                status_code=422,
                detail=f"无效严重级别: {severity}，可选: {sorted(VIOLATION_SEVERITIES)}",
            )
        if violation_type not in VIOLATION_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"无效违规类型: {violation_type}，可选: {sorted(VIOLATION_TYPES)}",
            )

        violation_id = f"vio_{uuid4().hex[:12]}"
        result = await db.execute(
            text("""
                INSERT INTO forge_runtime_violations
                    (id, tenant_id, violation_id, app_id, agent_id,
                     violation_type, severity, context,
                     resolved, created_at)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :violation_id, :app_id, :agent_id,
                     :violation_type, :severity,
                     :context::jsonb,
                     false, NOW())
                RETURNING violation_id, app_id, agent_id, violation_type,
                          severity, context, resolved, created_at
            """),
            {
                "violation_id": violation_id,
                "app_id": app_id,
                "agent_id": agent_id,
                "violation_type": violation_type,
                "severity": severity,
                "context": json.dumps(context, ensure_ascii=False),
            },
        )
        violation_row = dict(result.mappings().one())

        log.warning(
            "runtime_violation_recorded",
            violation_id=violation_id,
            app_id=app_id,
            violation_type=violation_type,
            severity=severity,
        )

        # 自动降级检查：最近 7 天 P1+ 违规数
        threshold_result = await db.execute(
            text("""
                SELECT auto_downgrade_threshold
                FROM forge_runtime_policies
                WHERE app_id = :app_id AND is_deleted = false
            """),
            {"app_id": app_id},
        )
        threshold_row = threshold_result.mappings().first()
        auto_threshold = (threshold_row["auto_downgrade_threshold"] if threshold_row else 3)

        count_result = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM forge_runtime_violations
                WHERE app_id = :app_id
                  AND is_deleted = false
                  AND severity IN ('P0', 'P1')
                  AND created_at >= NOW() - INTERVAL '7 days'
            """),
            {"app_id": app_id},
        )
        p1_plus_count = count_result.scalar_one()

        if p1_plus_count >= auto_threshold:
            from .forge_trust_service import ForgeTrustService

            trust_svc = ForgeTrustService()
            downgrade_result = await trust_svc.auto_downgrade(
                db,
                app_id=app_id,
                reason=f"7天内 P1+ 违规 {p1_plus_count} 次，超过阈值 {auto_threshold}",
            )
            violation_row["auto_downgrade"] = downgrade_result

        return violation_row

    # ── 查询违规列表 ─────────────────────────────────────────────
    async def get_violations(
        self,
        db: AsyncSession,
        *,
        app_id: str | None = None,
        severity: str | None = None,
        resolved: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询违规记录"""
        where_parts = ["is_deleted = false"]
        params: dict = {"limit": size, "offset": (page - 1) * size}

        if app_id is not None:
            where_parts.append("app_id = :app_id")
            params["app_id"] = app_id
        if severity is not None:
            where_parts.append("severity = :severity")
            params["severity"] = severity
        if resolved is not None:
            where_parts.append("resolved = :resolved")
            params["resolved"] = resolved

        where_clause = " AND ".join(where_parts)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM forge_runtime_violations WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar_one()

        result = await db.execute(
            text(f"""
                SELECT violation_id, app_id, agent_id, violation_type,
                       severity, context, resolved, resolved_at,
                       resolved_by, created_at
                FROM forge_runtime_violations
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in result.mappings().all()]
        return {"items": items, "total": total}

    # ── 解决违规 ─────────────────────────────────────────────────
    async def resolve_violation(
        self,
        db: AsyncSession,
        violation_id: str,
        *,
        resolved_by: str,
    ) -> dict:
        """标记违规已解决"""
        result = await db.execute(
            text("""
                UPDATE forge_runtime_violations
                SET resolved = true,
                    resolved_at = NOW(),
                    resolved_by = :resolved_by,
                    updated_at = NOW()
                WHERE violation_id = :violation_id AND is_deleted = false
                RETURNING violation_id, app_id, violation_type, severity,
                          resolved, resolved_at, resolved_by
            """),
            {"violation_id": violation_id, "resolved_by": resolved_by},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"违规记录不存在: {violation_id}")

        log.info(
            "violation_resolved",
            violation_id=violation_id,
            resolved_by=resolved_by,
        )
        return dict(row)
