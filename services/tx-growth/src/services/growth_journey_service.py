"""核心旅程V2服务 — 模板管理 + 客户enrollment + 步骤推进

管理 growth_journey_templates / growth_journey_template_steps /
growth_journey_enrollments 三张表。

金额单位：分(fen)
"""
import asyncio
import json
import uuid as uuid_module
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
# GrowthJourneyService
# ---------------------------------------------------------------------------


class GrowthJourneyService:
    """核心旅程V2服务 — 模板 CRUD + enrollment 生命周期 + 步骤推进"""

    VALID_JOURNEY_TYPES = ("repurchase", "reactivation", "repair", "upsell", "referral")
    VALID_STEP_TYPES = ("touch", "wait", "decision", "observe", "offer", "exit")
    VALID_ENROLLMENT_STATES = (
        "eligible", "active", "paused", "waiting_observe",
        "completed", "exited", "cancelled",
    )
    # enrollment 允许的状态转换
    _ACTIVE_STATES = ("eligible", "active", "paused", "waiting_observe")

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    # ==================================================================
    # A. 模板 CRUD
    # ==================================================================

    async def create_template(
        self, data: dict, tenant_id: str, db: AsyncSession
    ) -> dict:
        """INSERT growth_journey_templates + batch INSERT steps"""
        await self._set_tenant(db, tenant_id)

        template_id = str(uuid4())
        name = data["name"]
        journey_type = data.get("journey_type", "repurchase")
        description = data.get("description")
        trigger_rule_json = json.dumps(data.get("trigger_rule", {}))
        steps = data.get("steps", [])

        if journey_type not in self.VALID_JOURNEY_TYPES:
            raise ValueError(f"Invalid journey_type: {journey_type}")

        result = await db.execute(
            text("""
                INSERT INTO growth_journey_templates
                    (id, tenant_id, name, journey_type, description,
                     trigger_rule_json, total_steps, is_active)
                VALUES
                    (:id, :tenant_id, :name, :journey_type, :description,
                     :trigger_rule_json::jsonb, :total_steps, false)
                RETURNING id, tenant_id, name, journey_type, description,
                          trigger_rule_json, total_steps, is_active,
                          created_at, updated_at
            """),
            {
                "id": template_id,
                "tenant_id": tenant_id,
                "name": name,
                "journey_type": journey_type,
                "description": description,
                "trigger_rule_json": trigger_rule_json,
                "total_steps": len(steps),
            },
        )
        template_row = dict(result.fetchone()._mapping)

        # 批量插入steps
        for idx, step in enumerate(steps, start=1):
            step_type = step.get("step_type", "touch")
            if step_type not in self.VALID_STEP_TYPES:
                raise ValueError(f"Invalid step_type at step {idx}: {step_type}")

            await db.execute(
                text("""
                    INSERT INTO growth_journey_template_steps
                        (tenant_id, template_id, step_no, step_type,
                         touch_template_code, wait_minutes, decision_rule_json,
                         observe_window_hours, offer_type,
                         on_success_goto, on_fail_goto, on_skip_goto)
                    VALUES
                        (:tenant_id, :template_id, :step_no, :step_type,
                         :touch_template_code, :wait_minutes, :decision_rule_json::jsonb,
                         :observe_window_hours, :offer_type,
                         :on_success_goto, :on_fail_goto, :on_skip_goto)
                """),
                {
                    "tenant_id": tenant_id,
                    "template_id": template_id,
                    "step_no": idx,
                    "step_type": step_type,
                    "touch_template_code": step.get("touch_template_code"),
                    "wait_minutes": step.get("wait_minutes"),
                    "decision_rule_json": json.dumps(step.get("decision_rule", {})),
                    "observe_window_hours": step.get("observe_window_hours"),
                    "offer_type": step.get("offer_type"),
                    "on_success_goto": step.get("on_success_goto"),
                    "on_fail_goto": step.get("on_fail_goto"),
                    "on_skip_goto": step.get("on_skip_goto"),
                },
            )

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.journey_template.created",
                tenant_id=tenant_id,
                stream_id=template_id,
                payload={"template_id": template_id, "name": name, "steps_count": len(steps)},
                source_service="tx-growth",
            )
        )
        logger.info("journey_template_created", template_id=template_id, tenant_id=tenant_id)
        template_row["steps"] = steps
        return template_row

    async def list_templates(
        self,
        journey_type: Optional[str],
        is_active: Optional[bool],
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """SELECT templates with filters, 返回 {items, total}"""
        await self._set_tenant(db, tenant_id)

        where_clauses = ["tenant_id = :tid", "is_deleted = false"]
        params: dict = {"tid": tenant_id}

        if journey_type is not None:
            where_clauses.append("journey_type = :jtype")
            params["jtype"] = journey_type
        if is_active is not None:
            where_clauses.append("is_active = :is_active")
            params["is_active"] = is_active

        where_sql = " AND ".join(where_clauses)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM growth_journey_templates WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar() or 0

        rows_result = await db.execute(
            text(f"""
                SELECT id, tenant_id, name, journey_type, description,
                       total_steps, is_active, created_at, updated_at
                FROM growth_journey_templates
                WHERE {where_sql}
                ORDER BY created_at DESC
            """),
            params,
        )
        items = [dict(r._mapping) for r in rows_result.fetchall()]
        return {"items": items, "total": total}

    async def get_template(
        self, template_id: UUID, tenant_id: str, db: AsyncSession
    ) -> Optional[dict]:
        """SELECT template + JOIN steps ORDER BY step_no"""
        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                SELECT id, tenant_id, name, journey_type, description,
                       trigger_rule_json, total_steps, is_active,
                       created_at, updated_at
                FROM growth_journey_templates
                WHERE tenant_id = :tid AND id = :tmpl_id AND is_deleted = false
            """),
            {"tid": tenant_id, "tmpl_id": str(template_id)},
        )
        row = result.fetchone()
        if row is None:
            return None

        template = dict(row._mapping)

        steps_result = await db.execute(
            text("""
                SELECT step_no, step_type, touch_template_code,
                       wait_minutes, decision_rule_json,
                       observe_window_hours, offer_type,
                       on_success_goto, on_fail_goto, on_skip_goto
                FROM growth_journey_template_steps
                WHERE tenant_id = :tid AND template_id = :tmpl_id AND is_deleted = false
                ORDER BY step_no ASC
            """),
            {"tid": tenant_id, "tmpl_id": str(template_id)},
        )
        template["steps"] = [dict(s._mapping) for s in steps_result.fetchall()]
        return template

    async def update_template(
        self, template_id: UUID, data: dict, tenant_id: str, db: AsyncSession
    ) -> dict:
        """UPDATE template + 重建steps"""
        await self._set_tenant(db, tenant_id)

        name = data.get("name")
        journey_type = data.get("journey_type")
        description = data.get("description")
        trigger_rule = data.get("trigger_rule")
        steps = data.get("steps")

        # 构建动态 SET 子句
        set_parts: list[str] = ["updated_at = NOW()"]
        params: dict = {"tid": tenant_id, "tmpl_id": str(template_id)}

        if name is not None:
            set_parts.append("name = :name")
            params["name"] = name
        if journey_type is not None:
            if journey_type not in self.VALID_JOURNEY_TYPES:
                raise ValueError(f"Invalid journey_type: {journey_type}")
            set_parts.append("journey_type = :journey_type")
            params["journey_type"] = journey_type
        if description is not None:
            set_parts.append("description = :description")
            params["description"] = description
        if trigger_rule is not None:
            set_parts.append("trigger_rule_json = :trigger_rule_json::jsonb")
            params["trigger_rule_json"] = json.dumps(trigger_rule)
        if steps is not None:
            set_parts.append("total_steps = :total_steps")
            params["total_steps"] = len(steps)

        set_sql = ", ".join(set_parts)
        result = await db.execute(
            text(f"""
                UPDATE growth_journey_templates
                SET {set_sql}
                WHERE tenant_id = :tid AND id = :tmpl_id AND is_deleted = false
                RETURNING id, tenant_id, name, journey_type, description,
                          trigger_rule_json, total_steps, is_active,
                          created_at, updated_at
            """),
            params,
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"Template {template_id} not found")
        template = dict(row._mapping)

        # 重建steps
        if steps is not None:
            await db.execute(
                text("""
                    UPDATE growth_journey_template_steps
                    SET is_deleted = true, updated_at = NOW()
                    WHERE tenant_id = :tid AND template_id = :tmpl_id
                """),
                {"tid": tenant_id, "tmpl_id": str(template_id)},
            )
            for idx, step in enumerate(steps, start=1):
                step_type = step.get("step_type", "touch")
                if step_type not in self.VALID_STEP_TYPES:
                    raise ValueError(f"Invalid step_type at step {idx}: {step_type}")
                await db.execute(
                    text("""
                        INSERT INTO growth_journey_template_steps
                            (tenant_id, template_id, step_no, step_type,
                             touch_template_code, wait_minutes, decision_rule_json,
                             observe_window_hours, offer_type,
                             on_success_goto, on_fail_goto, on_skip_goto)
                        VALUES
                            (:tenant_id, :template_id, :step_no, :step_type,
                             :touch_template_code, :wait_minutes, :decision_rule_json::jsonb,
                             :observe_window_hours, :offer_type,
                             :on_success_goto, :on_fail_goto, :on_skip_goto)
                    """),
                    {
                        "tenant_id": tenant_id,
                        "template_id": str(template_id),
                        "step_no": idx,
                        "step_type": step_type,
                        "touch_template_code": step.get("touch_template_code"),
                        "wait_minutes": step.get("wait_minutes"),
                        "decision_rule_json": json.dumps(step.get("decision_rule", {})),
                        "observe_window_hours": step.get("observe_window_hours"),
                        "offer_type": step.get("offer_type"),
                        "on_success_goto": step.get("on_success_goto"),
                        "on_fail_goto": step.get("on_fail_goto"),
                        "on_skip_goto": step.get("on_skip_goto"),
                    },
                )
            template["steps"] = steps

        logger.info("journey_template_updated", template_id=str(template_id), tenant_id=tenant_id)
        return template

    async def activate_template(
        self, template_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """UPDATE is_active=true"""
        await self._set_tenant(db, tenant_id)
        result = await db.execute(
            text("""
                UPDATE growth_journey_templates
                SET is_active = true, updated_at = NOW()
                WHERE tenant_id = :tid AND id = :tmpl_id AND is_deleted = false
                RETURNING id, name, is_active, updated_at
            """),
            {"tid": tenant_id, "tmpl_id": str(template_id)},
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"Template {template_id} not found")
        logger.info("journey_template_activated", template_id=str(template_id), tenant_id=tenant_id)
        return dict(row._mapping)

    async def deactivate_template(
        self, template_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """UPDATE is_active=false"""
        await self._set_tenant(db, tenant_id)
        result = await db.execute(
            text("""
                UPDATE growth_journey_templates
                SET is_active = false, updated_at = NOW()
                WHERE tenant_id = :tid AND id = :tmpl_id AND is_deleted = false
                RETURNING id, name, is_active, updated_at
            """),
            {"tid": tenant_id, "tmpl_id": str(template_id)},
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"Template {template_id} not found")
        logger.info("journey_template_deactivated", template_id=str(template_id), tenant_id=tenant_id)
        return dict(row._mapping)

    # ==================================================================
    # B. Enrollment 生命周期
    # ==================================================================

    async def list_enrollments(
        self,
        tenant_id: str,
        db: AsyncSession,
        customer_id: Optional[str] = None,
        journey_state: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页列出旅程enrollment"""
        await self._set_tenant(db, tenant_id)

        where_clauses = ["e.tenant_id = :tid", "e.is_deleted = false"]
        params: dict = {"tid": tenant_id}

        if customer_id is not None:
            where_clauses.append("e.customer_id = :cid")
            params["cid"] = customer_id
        if journey_state is not None:
            where_clauses.append("e.journey_state = :state")
            params["state"] = journey_state

        where_sql = " AND ".join(where_clauses)
        offset = (page - 1) * size

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM growth_journey_enrollments e WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar() or 0

        params["lim"] = size
        params["off"] = offset
        rows_result = await db.execute(
            text(f"""
                SELECT e.id, e.tenant_id, e.customer_id, e.journey_template_id AS template_id,
                       e.journey_state, e.current_step_no, e.enrollment_source,
                       e.source_event_type, e.source_event_id,
                       e.assigned_agent_suggestion_id AS suggestion_id,
                       e.entered_at, e.activated_at, e.paused_at, e.completed_at,
                       e.exited_at, e.exit_reason, e.pause_reason,
                       e.next_execute_at, e.created_at, e.updated_at,
                       t.name AS template_name
                FROM growth_journey_enrollments e
                LEFT JOIN growth_journey_templates t
                  ON t.id = e.journey_template_id AND t.tenant_id = e.tenant_id
                WHERE {where_sql}
                ORDER BY e.created_at DESC
                LIMIT :lim OFFSET :off
            """),
            params,
        )
        items = [dict(r._mapping) for r in rows_result.fetchall()]
        return {"items": items, "total": total}

    async def get_enrollment(
        self, enrollment_id: UUID, tenant_id: str, db: AsyncSession
    ) -> Optional[dict]:
        """获取单个enrollment详情"""
        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                SELECT e.id, e.tenant_id, e.customer_id, e.journey_template_id AS template_id,
                       e.journey_state, e.current_step_no, e.enrollment_source,
                       e.source_event_type, e.source_event_id,
                       e.assigned_agent_suggestion_id AS suggestion_id,
                       e.entered_at, e.activated_at, e.paused_at, e.completed_at,
                       e.exited_at, e.exit_reason, e.pause_reason,
                       e.next_execute_at, e.created_at, e.updated_at,
                       t.name AS template_name
                FROM growth_journey_enrollments e
                LEFT JOIN growth_journey_templates t
                  ON t.id = e.journey_template_id AND t.tenant_id = e.tenant_id
                WHERE e.tenant_id = :tid AND e.id = :eid AND e.is_deleted = false
            """),
            {"tid": tenant_id, "eid": str(enrollment_id)},
        )
        row = result.fetchone()
        if row is None:
            return None
        return dict(row._mapping)

    async def enroll_customer(
        self,
        customer_id: UUID,
        template_id: UUID,
        source: str,
        event_type: Optional[str],
        event_id: Optional[str],
        suggestion_id: Optional[UUID],
        tenant_id: str,
        db: AsyncSession,
        store_id: Optional[UUID] = None,
        brand_id: Optional[UUID] = None,
    ) -> dict:
        """创建enrollment（去重检查后INSERT）"""
        await self._set_tenant(db, tenant_id)

        # ── 门店能力校验（V2.3）──
        # 如果指定了store_id，检查门店是否存在且活跃
        if store_id:
            store_check = await db.execute(text("""
                SELECT id, is_active FROM stores
                WHERE id = :sid AND tenant_id = :tid AND is_deleted = FALSE
            """), {"sid": str(store_id), "tid": tenant_id})
            store_row = store_check.fetchone()
            if not store_row:
                raise ValueError(f"Store {store_id} not found")
            if not store_row[1]:
                raise ValueError(f"Store {store_id} is inactive")

        # 如果模板有brand_scope=specific，校验brand_id在allowed_brand_ids中
        template_scope = await db.execute(text("""
            SELECT brand_scope, allowed_brand_ids
            FROM growth_journey_templates
            WHERE id = :tid AND is_deleted = FALSE
        """), {"tid": str(template_id)})
        scope_row = template_scope.fetchone()
        if scope_row and scope_row[0] == "specific":
            allowed_raw = scope_row[1] or []
            allowed = allowed_raw if isinstance(allowed_raw, list) else json.loads(allowed_raw) if allowed_raw else []
            if brand_id and str(brand_id) not in [str(b) for b in allowed]:
                raise ValueError(f"Template not available for brand {brand_id}")

        # 去重: 同一template+customer如果已有活跃enrollment，拒绝
        dup = await db.execute(
            text("""
                SELECT id FROM growth_journey_enrollments
                WHERE tenant_id = :tid
                  AND template_id = :tmpl_id
                  AND customer_id = :cid
                  AND journey_state IN ('eligible', 'active', 'paused', 'waiting_observe')
                  AND is_deleted = false
                LIMIT 1
            """),
            {"tid": tenant_id, "tmpl_id": str(template_id), "cid": str(customer_id)},
        )
        if dup.fetchone() is not None:
            raise ValueError(
                f"Customer {customer_id} already has an active enrollment for template {template_id}"
            )

        # ── A/B测试分组（如果模板关联了ab_test） ──
        ab_test_id = None
        ab_variant = None

        template_ab = await db.execute(text("""
            SELECT ab_test_id FROM growth_journey_templates
            WHERE id = :tid AND is_deleted = FALSE
        """), {"tid": str(template_id)})
        ab_row = template_ab.fetchone()
        if ab_row and ab_row[0]:
            ab_test_id = str(ab_row[0])
            try:
                from services.ab_test_service import ABTestService
                ab_svc = ABTestService()
                ab_variant = await ab_svc.assign_variant(
                    test_id=uuid_module.UUID(ab_test_id),
                    customer_id=customer_id,
                    customer_data={},
                    tenant_id=uuid_module.UUID(tenant_id),
                    db=db,
                )
                logger.info("ab_test_assigned",
                            enrollment_customer=str(customer_id),
                            ab_test_id=ab_test_id,
                            variant=ab_variant)
            except (ValueError, RuntimeError, OSError) as exc:
                logger.warning("ab_test_assignment_failed",
                               error=str(exc),
                               ab_test_id=ab_test_id)
                ab_variant = "control"  # 分组失败默认走control

        enrollment_id = str(uuid4())
        result = await db.execute(
            text("""
                INSERT INTO growth_journey_enrollments
                    (id, tenant_id, customer_id, template_id, journey_state,
                     current_step_no, enrollment_source, source_event_type,
                     source_event_id, suggestion_id,
                     ab_test_id, ab_variant,
                     store_id, brand_id)
                VALUES
                    (:id, :tenant_id, :customer_id, :template_id, 'eligible',
                     1, :source, :event_type, :event_id, :suggestion_id,
                     :ab_test_id, :ab_variant,
                     :store_id, :brand_id)
                RETURNING id, tenant_id, customer_id, template_id, journey_state,
                          current_step_no, enrollment_source, suggestion_id,
                          ab_test_id, ab_variant,
                          store_id, brand_id,
                          created_at, updated_at
            """),
            {
                "id": enrollment_id,
                "tenant_id": tenant_id,
                "customer_id": str(customer_id),
                "template_id": str(template_id),
                "source": source,
                "event_type": event_type,
                "event_id": event_id,
                "suggestion_id": str(suggestion_id) if suggestion_id else None,
                "ab_test_id": ab_test_id,
                "ab_variant": ab_variant,
                "store_id": str(store_id) if store_id else None,
                "brand_id": str(brand_id) if brand_id else None,
            },
        )
        enrollment = dict(result.fetchone()._mapping)

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.enrollment.state_changed",
                tenant_id=tenant_id,
                stream_id=enrollment_id,
                payload={
                    "enrollment_id": enrollment_id,
                    "customer_id": str(customer_id),
                    "template_id": str(template_id),
                    "new_state": "eligible",
                    "source": source,
                },
                source_service="tx-growth",
            )
        )
        logger.info(
            "customer_enrolled",
            enrollment_id=enrollment_id,
            customer_id=str(customer_id),
            template_id=str(template_id),
            tenant_id=tenant_id,
        )
        return enrollment

    async def advance_enrollment(
        self, enrollment_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """核心推进逻辑 — 根据当前step类型分派执行"""
        await self._set_tenant(db, tenant_id)

        # 读enrollment
        enr_result = await db.execute(
            text("""
                SELECT id, customer_id, template_id, journey_state,
                       current_step_no, next_execute_at
                FROM growth_journey_enrollments
                WHERE tenant_id = :tid AND id = :eid AND is_deleted = false
            """),
            {"tid": tenant_id, "eid": str(enrollment_id)},
        )
        enr_row = enr_result.fetchone()
        if enr_row is None:
            raise ValueError(f"Enrollment {enrollment_id} not found")

        enr = dict(enr_row._mapping)
        current_state = enr["journey_state"]
        if current_state not in ("eligible", "active", "waiting_observe"):
            raise ValueError(
                f"Cannot advance enrollment in state '{current_state}'"
            )

        template_id = enr["template_id"]
        current_step_no = enr["current_step_no"]
        customer_id = enr["customer_id"]

        # 读模板总步数
        tmpl_result = await db.execute(
            text("""
                SELECT total_steps FROM growth_journey_templates
                WHERE tenant_id = :tid AND id = :tmpl_id AND is_deleted = false
            """),
            {"tid": tenant_id, "tmpl_id": str(template_id)},
        )
        tmpl_row = tmpl_result.fetchone()
        if tmpl_row is None:
            raise ValueError(f"Template {template_id} not found")
        total_steps = tmpl_row._mapping["total_steps"]

        # 读当前step
        step_result = await db.execute(
            text("""
                SELECT step_no, step_type, touch_template_code, wait_minutes,
                       decision_rule_json, observe_window_hours, offer_type,
                       on_success_goto, on_fail_goto, on_skip_goto
                FROM growth_journey_template_steps
                WHERE tenant_id = :tid AND template_id = :tmpl_id
                  AND step_no = :step_no AND is_deleted = false
            """),
            {"tid": tenant_id, "tmpl_id": str(template_id), "step_no": current_step_no},
        )
        step_row = step_result.fetchone()
        if step_row is None:
            raise ValueError(f"Step {current_step_no} not found for template {template_id}")

        step = dict(step_row._mapping)
        step_type = step["step_type"]

        new_state = "active"
        new_step_no = current_step_no
        next_execute_at: Optional[datetime] = None
        now = datetime.now(timezone.utc)

        if step_type == "touch":
            # 触达步骤：记录触达执行（实际发送由touch_service处理）
            # advance到下一步
            new_step_no = current_step_no + 1
            if new_step_no > total_steps:
                new_state = "completed"
                new_step_no = current_step_no

        elif step_type == "wait":
            # 等待步骤：设置next_execute_at
            wait_minutes = step.get("wait_minutes") or 60
            next_execute_at = now + timedelta(minutes=wait_minutes)
            new_step_no = current_step_no + 1
            if new_step_no > total_steps:
                new_state = "completed"
                new_step_no = current_step_no

        elif step_type == "decision":
            # 决策步骤：评估decision_rule_json
            decision_rule = step.get("decision_rule_json") or {}
            if isinstance(decision_rule, str):
                decision_rule = json.loads(decision_rule) if decision_rule else {}

            check_type = decision_rule.get("check", "")
            goto_step = None

            if check_type == "field_value":
                # P1: 查询客户画像字段做分支
                field_name = decision_rule.get("field", "")
                expected_value = decision_rule.get("value")
                op = decision_rule.get("op", "eq")

                # 安全：只允许查询白名单字段
                _ALLOWED_FIELDS = {
                    "psych_distance_level", "super_user_level", "growth_milestone_stage",
                    "referral_scenario", "repurchase_stage", "reactivation_priority",
                    "service_repair_status", "has_active_owned_benefit",
                }
                if field_name in _ALLOWED_FIELDS:
                    profile_result = await db.execute(text(
                        f"SELECT {field_name} FROM customer_growth_profiles"  # noqa: S608
                        " WHERE customer_id = :cid AND is_deleted = FALSE"
                    ), {"cid": str(customer_id)})
                    row = profile_result.fetchone()
                    actual_value = row[0] if row else None

                    matched = False
                    if op == "eq":
                        matched = (actual_value == expected_value)
                    elif op == "ne":
                        matched = (actual_value != expected_value)
                    elif op == "in":
                        matched = (actual_value in (expected_value if isinstance(expected_value, list) else [expected_value]))
                    elif op == "not_in":
                        matched = (actual_value not in (expected_value if isinstance(expected_value, list) else [expected_value]))

                    goto_step = decision_rule.get("true_next") if matched else decision_rule.get("false_next")

            elif check_type == "has_active_owned_benefit":
                # 检查客户是否持有有效权益
                profile_result = await db.execute(text("""
                    SELECT has_active_owned_benefit FROM customer_growth_profiles
                    WHERE customer_id = :cid AND is_deleted = FALSE
                """), {"cid": str(customer_id)})
                row = profile_result.fetchone()
                has_benefit = row[0] if row else False
                goto_step = decision_rule.get("true_next") if has_benefit else decision_rule.get("false_next")

            elif check_type == "touch_opened":
                # 检查某步骤的触达是否已被打开
                touch_step = decision_rule.get("touch_step_no")
                if touch_step and enrollment_id:
                    touch_result = await db.execute(text("""
                        SELECT execution_state FROM growth_touch_executions
                        WHERE journey_enrollment_id = :eid AND step_no = :sno AND is_deleted = FALSE
                        ORDER BY created_at DESC LIMIT 1
                    """), {"eid": str(enrollment_id), "sno": touch_step})
                    trow = touch_result.fetchone()
                    opened = trow is not None and trow[0] in ("opened", "clicked", "replied")
                    goto_step = decision_rule.get("true_next") if opened else decision_rule.get("false_next")

            elif check_type == "ab_variant":
                # A/B测试变体分支
                enr_ab = await db.execute(text("""
                    SELECT ab_variant FROM growth_journey_enrollments
                    WHERE id = :eid AND is_deleted = FALSE
                """), {"eid": str(enrollment_id)})
                ab_row = enr_ab.fetchone()
                enrollment_variant = ab_row[0] if ab_row and ab_row[0] else "control"
                expected_variant = decision_rule.get("value", "control")
                matched = (enrollment_variant == expected_variant)
                goto_step = decision_rule.get("true_next") if matched else decision_rule.get("false_next")

            elif check_type == "has_revisited":
                # 查客户是否在旅程期间有新订单
                profile_result = await db.execute(text("""
                    SELECT last_order_at FROM customer_growth_profiles
                    WHERE customer_id = :cid AND is_deleted = FALSE
                """), {"cid": str(customer_id)})
                row = profile_result.fetchone()
                # 读enrollment的entered_at作为基准
                enr_entered = await db.execute(text("""
                    SELECT entered_at FROM growth_journey_enrollments
                    WHERE id = :eid AND is_deleted = FALSE
                """), {"eid": str(enrollment_id)})
                enr_row = enr_entered.fetchone()
                entered_at = enr_row[0] if enr_row else None
                revisited = (row is not None and row[0] is not None
                             and entered_at is not None and row[0] > entered_at)
                goto_step = decision_rule.get("true_next") if revisited else decision_rule.get("false_next")

            # 如果没有匹配的check_type，走默认success分支
            if goto_step is not None:
                new_step_no = goto_step
            else:
                # P0 fallback: 默认走success分支
                fallback_goto = step.get("on_success_goto")
                if fallback_goto is not None:
                    new_step_no = fallback_goto
                else:
                    new_step_no = current_step_no + 1
            if new_step_no > total_steps:
                new_state = "completed"
                new_step_no = current_step_no

        elif step_type == "observe":
            # 观察步骤：设state='waiting_observe'
            observe_hours = step.get("observe_window_hours") or 24
            next_execute_at = now + timedelta(hours=observe_hours)
            new_state = "waiting_observe"

        elif step_type == "offer":
            # P0简化: 记录offer，advance
            new_step_no = current_step_no + 1
            if new_step_no > total_steps:
                new_state = "completed"
                new_step_no = current_step_no

        elif step_type == "exit":
            new_state = "exited" if step.get("on_fail_goto") else "completed"

        # 更新enrollment
        result = await db.execute(
            text("""
                UPDATE growth_journey_enrollments
                SET journey_state = :state,
                    current_step_no = :step_no,
                    next_execute_at = :next_at,
                    updated_at = NOW()
                WHERE tenant_id = :tid AND id = :eid AND is_deleted = false
                RETURNING id, customer_id, template_id, journey_state,
                          current_step_no, next_execute_at, updated_at
            """),
            {
                "tid": tenant_id,
                "eid": str(enrollment_id),
                "state": new_state,
                "step_no": new_step_no,
                "next_at": next_execute_at,
            },
        )
        updated = dict(result.fetchone()._mapping)

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.enrollment.advanced",
                tenant_id=tenant_id,
                stream_id=str(enrollment_id),
                payload={
                    "enrollment_id": str(enrollment_id),
                    "customer_id": str(customer_id),
                    "step_type": step_type,
                    "from_step": current_step_no,
                    "to_step": new_step_no,
                    "new_state": new_state,
                },
                source_service="tx-growth",
            )
        )
        logger.info(
            "enrollment_advanced",
            enrollment_id=str(enrollment_id),
            step_type=step_type,
            from_step=current_step_no,
            to_step=new_step_no,
            new_state=new_state,
            tenant_id=tenant_id,
        )
        return updated

    async def pause_enrollment(
        self, enrollment_id: UUID, reason: str, tenant_id: str, db: AsyncSession
    ) -> dict:
        """state -> paused"""
        await self._set_tenant(db, tenant_id)

        # 校验当前state
        cur = await db.execute(
            text("""
                SELECT journey_state FROM growth_journey_enrollments
                WHERE tenant_id = :tid AND id = :eid AND is_deleted = false
            """),
            {"tid": tenant_id, "eid": str(enrollment_id)},
        )
        cur_row = cur.fetchone()
        if cur_row is None:
            raise ValueError(f"Enrollment {enrollment_id} not found")
        if cur_row._mapping["journey_state"] not in ("eligible", "active", "waiting_observe"):
            raise ValueError(
                f"Cannot pause enrollment in state '{cur_row._mapping['journey_state']}'"
            )

        result = await db.execute(
            text("""
                UPDATE growth_journey_enrollments
                SET journey_state = 'paused', updated_at = NOW()
                WHERE tenant_id = :tid AND id = :eid AND is_deleted = false
                RETURNING id, customer_id, template_id, journey_state, updated_at
            """),
            {"tid": tenant_id, "eid": str(enrollment_id)},
        )
        updated = dict(result.fetchone()._mapping)

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.enrollment.state_changed",
                tenant_id=tenant_id,
                stream_id=str(enrollment_id),
                payload={
                    "enrollment_id": str(enrollment_id),
                    "new_state": "paused",
                    "reason": reason,
                },
                source_service="tx-growth",
            )
        )
        logger.info("enrollment_paused", enrollment_id=str(enrollment_id), reason=reason)
        return updated

    async def resume_enrollment(
        self, enrollment_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """state -> active"""
        await self._set_tenant(db, tenant_id)

        cur = await db.execute(
            text("""
                SELECT journey_state FROM growth_journey_enrollments
                WHERE tenant_id = :tid AND id = :eid AND is_deleted = false
            """),
            {"tid": tenant_id, "eid": str(enrollment_id)},
        )
        cur_row = cur.fetchone()
        if cur_row is None:
            raise ValueError(f"Enrollment {enrollment_id} not found")
        if cur_row._mapping["journey_state"] != "paused":
            raise ValueError(
                f"Cannot resume enrollment in state '{cur_row._mapping['journey_state']}', must be 'paused'"
            )

        result = await db.execute(
            text("""
                UPDATE growth_journey_enrollments
                SET journey_state = 'active', updated_at = NOW()
                WHERE tenant_id = :tid AND id = :eid AND is_deleted = false
                RETURNING id, customer_id, template_id, journey_state, updated_at
            """),
            {"tid": tenant_id, "eid": str(enrollment_id)},
        )
        updated = dict(result.fetchone()._mapping)

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.enrollment.state_changed",
                tenant_id=tenant_id,
                stream_id=str(enrollment_id),
                payload={"enrollment_id": str(enrollment_id), "new_state": "active"},
                source_service="tx-growth",
            )
        )
        logger.info("enrollment_resumed", enrollment_id=str(enrollment_id))
        return updated

    async def cancel_enrollment(
        self, enrollment_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """state -> cancelled"""
        await self._set_tenant(db, tenant_id)

        cur = await db.execute(
            text("""
                SELECT journey_state FROM growth_journey_enrollments
                WHERE tenant_id = :tid AND id = :eid AND is_deleted = false
            """),
            {"tid": tenant_id, "eid": str(enrollment_id)},
        )
        cur_row = cur.fetchone()
        if cur_row is None:
            raise ValueError(f"Enrollment {enrollment_id} not found")
        current_state = cur_row._mapping["journey_state"]
        if current_state in ("completed", "exited", "cancelled"):
            raise ValueError(f"Cannot cancel enrollment in terminal state '{current_state}'")

        result = await db.execute(
            text("""
                UPDATE growth_journey_enrollments
                SET journey_state = 'cancelled', updated_at = NOW()
                WHERE tenant_id = :tid AND id = :eid AND is_deleted = false
                RETURNING id, customer_id, template_id, journey_state, updated_at
            """),
            {"tid": tenant_id, "eid": str(enrollment_id)},
        )
        updated = dict(result.fetchone()._mapping)

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.enrollment.state_changed",
                tenant_id=tenant_id,
                stream_id=str(enrollment_id),
                payload={"enrollment_id": str(enrollment_id), "new_state": "cancelled"},
                source_service="tx-growth",
            )
        )
        logger.info("enrollment_cancelled", enrollment_id=str(enrollment_id))
        return updated

    # ==================================================================
    # C. 批量处理到期enrollment
    # ==================================================================

    async def process_pending(
        self, tenant_id: Optional[str], db: AsyncSession
    ) -> dict:
        """批量处理到期enrollment: state IN ('active','waiting_observe') AND next_execute_at <= NOW()"""
        if tenant_id is not None:
            await self._set_tenant(db, tenant_id)

        where_tenant = "AND tenant_id = :tid" if tenant_id else ""
        params: dict = {}
        if tenant_id:
            params["tid"] = tenant_id

        pending = await db.execute(
            text(f"""
                SELECT id, tenant_id
                FROM growth_journey_enrollments
                WHERE journey_state IN ('active', 'waiting_observe')
                  AND next_execute_at IS NOT NULL
                  AND next_execute_at <= NOW()
                  AND is_deleted = false
                  {where_tenant}
                ORDER BY next_execute_at ASC
                LIMIT 500
            """),
            params,
        )
        rows = pending.fetchall()

        scanned = len(rows)
        advanced = 0
        failed = 0

        for row in rows:
            row_map = row._mapping
            eid = row_map["id"]
            row_tid = row_map["tenant_id"]
            try:
                await self.advance_enrollment(
                    enrollment_id=UUID(str(eid)),
                    tenant_id=str(row_tid),
                    db=db,
                )
                advanced += 1
            except (ValueError, RuntimeError) as exc:
                failed += 1
                logger.warning(
                    "process_pending_advance_failed",
                    enrollment_id=str(eid),
                    error=str(exc),
                )

        logger.info(
            "process_pending_completed",
            scanned=scanned,
            advanced=advanced,
            failed=failed,
        )
        return {"scanned": scanned, "advanced": advanced, "failed": failed}
