"""Journey 触发引擎 — 事件驱动的旅程编排器

核心职责：
  - 接收业务事件（first_visit / birthday / post_order 等）
  - 查找匹配的 journey_definitions（is_active=TRUE + trigger_event 匹配）
  - 评估 trigger_conditions（字段比较，AND 逻辑）
  - 创建或推进 journey_enrollments
  - 调用 action_executors 执行具体动作
  - 写入 journey_step_executions（可审计）

设计原则：
  - engine 层不依赖 FastAPI，可独立运行（被 APScheduler / CLI / 测试 调用）
  - process_pending_steps 设计为被 APScheduler 每分钟调用
  - action_executors 用 try/except 包裹，失败记录错误不崩溃
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from engine.action_executors import ActionExecutorRegistry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 触发事件 → 表字段/条件 映射
# ---------------------------------------------------------------------------

TRIGGER_EVENT_MAP: dict[str, str] = {
    "first_visit": "first_visit",
    "7day_inactive": "7day_inactive",
    "15day_inactive": "15day_inactive",
    "30day_inactive": "30day_inactive",
    "birthday": "birthday",
    "post_order": "post_order",
    "low_repurchase_risk": "low_repurchase_risk",
    "banquet_completed": "banquet_completed",
    "high_ltv": "high_ltv",
    "reservation_abandoned": "reservation_abandoned",
    "new_dish_launch": "new_dish_launch",
    "manual": "manual",
}

# 条件比较运算符
OPERATORS: dict[str, Any] = {
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "gt": lambda a, b: float(a) > float(b),
    "gte": lambda a, b: float(a) >= float(b),
    "lt": lambda a, b: float(a) < float(b),
    "lte": lambda a, b: float(a) <= float(b),
    "contains": lambda a, b: str(b).lower() in str(a).lower(),
    "in": lambda a, b: a in (b if isinstance(b, list) else [b]),
}


class JourneyEngine:
    """
    核心执行引擎：事件驱动的旅程编排器

    所有 DB 操作通过传入的 AsyncSession 执行。
    不持有任何实例状态，线程安全。
    """

    def __init__(self) -> None:
        self._executor_registry = ActionExecutorRegistry()

    # ------------------------------------------------------------------
    # 主入口：接收业务事件
    # ------------------------------------------------------------------

    async def handle_event(
        self,
        tenant_id: uuid.UUID,
        event_type: str,
        customer_id: uuid.UUID,
        context: dict,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        主入口：接收业务事件，查找匹配的旅程定义，创建 enrollment。

        Args:
            tenant_id:   租户 UUID
            event_type:  触发事件类型（如 "first_visit", "post_order"）
            customer_id: 触发客户 UUID
            context:     上下文数据（如 {"order_id": "...", "amount": 9800}）
            db:          AsyncSession（由调用方管理生命周期）

        Returns:
            {"enrollments_created": int, "journeys_matched": int, "details": [...]}
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            event_type=event_type,
            customer_id=str(customer_id),
        )
        log.info("journey_engine_handle_event")

        # 设置 RLS 上下文
        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )

        # 查找该租户下匹配事件类型的活跃旅程
        result = await db.execute(
            text("""
                SELECT id, trigger_conditions, steps, name
                FROM journey_definitions
                WHERE tenant_id = :tenant_id
                  AND is_active = TRUE
                  AND is_deleted = FALSE
                  AND trigger_event = :event_type
            """),
            {"tenant_id": str(tenant_id), "event_type": event_type},
        )
        definitions = result.fetchall()

        if not definitions:
            log.info("journey_engine_no_matching_definitions", event_type=event_type)
            return {"enrollments_created": 0, "journeys_matched": 0, "details": []}

        # 获取客户数据（用于条件评估）
        customer_data = await self._fetch_customer_data(tenant_id, customer_id, db)
        merged_context = {**customer_data, **context}

        enrollments_created = 0
        details: list[dict] = []

        for row in definitions:
            journey_def_id = row[0]
            trigger_conditions = row[1] or []
            steps = row[2] or []
            journey_name = row[3]

            # 评估触发条件
            conditions_met = await self.evaluate_trigger_conditions(trigger_conditions, merged_context)
            if not conditions_met:
                log.info(
                    "journey_conditions_not_met",
                    journey_def_id=str(journey_def_id),
                )
                details.append(
                    {
                        "journey_def_id": str(journey_def_id),
                        "journey_name": journey_name,
                        "enrolled": False,
                        "reason": "conditions_not_met",
                    }
                )
                continue

            # 检查是否已有 active enrollment（防重入）
            existing = await db.execute(
                text("""
                    SELECT id FROM journey_enrollments
                    WHERE tenant_id = :tenant_id
                      AND journey_definition_id = :jd_id
                      AND customer_id = :customer_id
                      AND status = 'active'
                    LIMIT 1
                """),
                {
                    "tenant_id": str(tenant_id),
                    "jd_id": str(journey_def_id),
                    "customer_id": str(customer_id),
                },
            )
            if existing.fetchone():
                log.info(
                    "journey_already_enrolled",
                    journey_def_id=str(journey_def_id),
                    customer_id=str(customer_id),
                )
                details.append(
                    {
                        "journey_def_id": str(journey_def_id),
                        "journey_name": journey_name,
                        "enrolled": False,
                        "reason": "already_active",
                    }
                )
                continue

            # 创建 enrollment
            if not steps:
                continue

            enrollment = await self.enroll_customer(
                tenant_id=tenant_id,
                journey_def_id=journey_def_id,
                customer_id=customer_id,
                context=merged_context,
                steps=steps,
                db=db,
            )
            enrollments_created += 1
            details.append(
                {
                    "journey_def_id": str(journey_def_id),
                    "journey_name": journey_name,
                    "enrolled": True,
                    "enrollment_id": str(enrollment["id"]),
                }
            )
            log.info(
                "journey_enrollment_created",
                journey_def_id=str(journey_def_id),
                enrollment_id=str(enrollment["id"]),
            )

        return {
            "enrollments_created": enrollments_created,
            "journeys_matched": len(definitions),
            "details": details,
        }

    # ------------------------------------------------------------------
    # 触发条件评估
    # ------------------------------------------------------------------

    async def evaluate_trigger_conditions(
        self,
        conditions: list[dict],
        data: dict,
    ) -> bool:
        """
        评估触发条件列表（AND 逻辑）。

        条件格式：[{"field": "recency_days", "operator": "gte", "value": 7}]
        空条件列表视为无约束，返回 True。

        Args:
            conditions: 触发条件列表
            data:        客户+上下文数据字典

        Returns:
            所有条件均满足时返回 True
        """
        if not conditions:
            return True

        for cond in conditions:
            field = cond.get("field", "")
            operator = cond.get("operator", "eq")
            expected = cond.get("value")

            actual = data.get(field)
            if actual is None:
                # 字段不存在视为条件不满足
                return False

            op_fn = OPERATORS.get(operator)
            if op_fn is None:
                logger.warning("unknown_operator", operator=operator, field=field)
                return False

            try:
                if not op_fn(actual, expected):
                    return False
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "condition_eval_error",
                    field=field,
                    operator=operator,
                    error=str(exc),
                )
                return False

        return True

    # ------------------------------------------------------------------
    # 创建 enrollment
    # ------------------------------------------------------------------

    async def enroll_customer(
        self,
        tenant_id: uuid.UUID,
        journey_def_id: uuid.UUID,
        customer_id: uuid.UUID,
        context: dict,
        steps: list[dict],
        db: AsyncSession,
    ) -> dict:
        """
        创建 enrollment，写入第一步的 journey_step_execution（scheduled）。

        Args:
            tenant_id:       租户 UUID
            journey_def_id:  旅程定义 UUID
            customer_id:     客户 UUID
            context:         上下文数据
            steps:           旅程步骤列表
            db:              AsyncSession

        Returns:
            新建的 enrollment 字典
        """
        now = datetime.now(timezone.utc)
        enrollment_id = uuid.uuid4()
        first_step = steps[0]
        first_step_id = first_step.get("step_id", "step_1")

        # 首步是否有等待时间
        wait_hours = first_step.get("wait_hours", 0)
        next_step_at = now + timedelta(hours=wait_hours) if wait_hours else now

        phone = context.get("phone") or context.get("customer_phone")

        await db.execute(
            text("""
                INSERT INTO journey_enrollments
                    (id, tenant_id, journey_definition_id, customer_id, phone,
                     current_step_id, status, enrolled_at, context_data, next_step_at)
                VALUES
                    (:id, :tenant_id, :jd_id, :customer_id, :phone,
                     :step_id, 'active', :enrolled_at, :context_data::jsonb, :next_step_at)
            """),
            {
                "id": str(enrollment_id),
                "tenant_id": str(tenant_id),
                "jd_id": str(journey_def_id),
                "customer_id": str(customer_id),
                "phone": phone,
                "step_id": first_step_id,
                "enrolled_at": now,
                "context_data": _json_dumps(context),
                "next_step_at": next_step_at,
            },
        )

        # 创建第一步执行记录
        await self._create_step_execution(
            tenant_id=tenant_id,
            enrollment_id=enrollment_id,
            step=first_step,
            scheduled_at=next_step_at,
            db=db,
        )

        return {
            "id": enrollment_id,
            "tenant_id": tenant_id,
            "journey_definition_id": journey_def_id,
            "customer_id": customer_id,
            "current_step_id": first_step_id,
            "status": "active",
            "enrolled_at": now,
            "next_step_at": next_step_at,
        }

    # ------------------------------------------------------------------
    # 推进单个 enrollment
    # ------------------------------------------------------------------

    async def advance_enrollment(
        self,
        enrollment_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        推进 enrollment 到下一步（由 process_pending_steps 调用）。

        Args:
            enrollment_id: enrollment UUID
            db:            AsyncSession

        Returns:
            推进结果 {"status": "advanced"|"completed"|"failed", ...}
        """
        # 查询 enrollment 及其旅程定义
        result = await db.execute(
            text("""
                SELECT
                    e.id, e.tenant_id, e.journey_definition_id, e.customer_id,
                    e.current_step_id, e.status, e.context_data, e.phone,
                    d.steps
                FROM journey_enrollments e
                JOIN journey_definitions d ON d.id = e.journey_definition_id
                WHERE e.id = :enrollment_id
                  AND e.status = 'active'
            """),
            {"enrollment_id": str(enrollment_id)},
        )
        row = result.fetchone()
        if not row:
            return {"status": "not_found", "enrollment_id": str(enrollment_id)}

        (enroll_id, tenant_id, jd_id, customer_id, current_step_id, status, context_data, phone, steps) = row

        # 找到当前步骤
        steps_list: list[dict] = steps or []
        current_step = next(
            (s for s in steps_list if s.get("step_id") == current_step_id),
            None,
        )
        if not current_step:
            logger.warning(
                "advance_step_not_found",
                enrollment_id=str(enrollment_id),
                current_step_id=current_step_id,
            )
            await self._mark_enrollment_failed(
                enrollment_id=enroll_id,
                error=f"step not found: {current_step_id}",
                db=db,
            )
            return {"status": "failed", "reason": "step_not_found"}

        # 执行当前步骤
        execution_result = await self.execute_step(
            tenant_id=uuid.UUID(str(tenant_id)),
            enrollment_id=uuid.UUID(str(enroll_id)),
            customer_id=uuid.UUID(str(customer_id)),
            step=current_step,
            context=context_data or {},
            db=db,
        )

        if not execution_result.get("success", False):
            # 步骤执行失败
            await self._mark_enrollment_failed(
                enrollment_id=enroll_id,
                error=execution_result.get("error", "unknown"),
                db=db,
            )
            return {"status": "failed", "reason": execution_result.get("error")}

        # 找下一步
        next_steps: list[str] = current_step.get("next_steps", [])
        # condition_branch 时 execution_result 会返回 next_step_id
        if "next_step_id" in execution_result:
            next_step_id = execution_result["next_step_id"]
            next_steps = [next_step_id] if next_step_id else []

        if not next_steps:
            # 旅程完成
            await self._complete_enrollment(enroll_id, db)
            return {
                "status": "completed",
                "enrollment_id": str(enroll_id),
                "completed_step": current_step_id,
            }

        # 推进到下一步（取第一个 next_step）
        next_step_id = next_steps[0]
        next_step = next(
            (s for s in steps_list if s.get("step_id") == next_step_id),
            None,
        )
        if not next_step:
            await self._complete_enrollment(enroll_id, db)
            return {
                "status": "completed",
                "enrollment_id": str(enroll_id),
                "completed_step": current_step_id,
            }

        # 计算下一步执行时间（wait_hours）
        now = datetime.now(timezone.utc)
        wait_hours = next_step.get("wait_hours", 0)
        next_step_at = now + timedelta(hours=wait_hours) if wait_hours else now

        await db.execute(
            text("""
                UPDATE journey_enrollments
                SET current_step_id = :step_id,
                    next_step_at    = :next_step_at
                WHERE id = :enrollment_id
            """),
            {
                "step_id": next_step_id,
                "next_step_at": next_step_at,
                "enrollment_id": str(enroll_id),
            },
        )

        # 创建下一步执行记录
        await self._create_step_execution(
            tenant_id=uuid.UUID(str(tenant_id)),
            enrollment_id=uuid.UUID(str(enroll_id)),
            step=next_step,
            scheduled_at=next_step_at,
            db=db,
        )

        return {
            "status": "advanced",
            "enrollment_id": str(enroll_id),
            "from_step": current_step_id,
            "to_step": next_step_id,
            "next_step_at": next_step_at.isoformat(),
        }

    # ------------------------------------------------------------------
    # 执行具体步骤
    # ------------------------------------------------------------------

    async def execute_step(
        self,
        tenant_id: uuid.UUID,
        enrollment_id: uuid.UUID,
        customer_id: uuid.UUID,
        step: dict,
        context: dict,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        执行具体步骤，调用对应的 ActionExecutor。

        支持的 action_type：
            wait              — 等待（纯时间推迟，无实际动作）
            send_wecom        — 发企业微信消息
            send_sms          — 发短信
            send_miniapp_push — 小程序推送
            award_coupon      — 发放优惠券
            tag_customer      — 打标签
            condition_branch  — 条件分支
            notify_staff      — 通知门店人员

        Returns:
            {"success": bool, "action_type": str, "result": dict, ...}
        """
        action_type = step.get("action_type", "wait")
        action_config = step.get("action_config", {})
        step_id = step.get("step_id", "unknown")

        log = logger.bind(
            tenant_id=str(tenant_id),
            enrollment_id=str(enrollment_id),
            step_id=step_id,
            action_type=action_type,
        )
        log.info("execute_step_start")

        # 更新步骤执行状态为 executing
        await db.execute(
            text("""
                UPDATE journey_step_executions
                SET status = 'executing',
                    executed_at = NOW()
                WHERE enrollment_id = :enrollment_id
                  AND step_id = :step_id
                  AND status = 'pending'
            """),
            {"enrollment_id": str(enrollment_id), "step_id": step_id},
        )

        # 调用对应执行器
        executor = self._executor_registry.get(action_type)
        try:
            exec_result = await executor.execute(
                tenant_id=tenant_id,
                customer_id=customer_id,
                action_config=action_config,
                context=context,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            error_msg = str(exc)
            log.error("execute_step_error", error=error_msg, exc_info=True)
            await db.execute(
                text("""
                    UPDATE journey_step_executions
                    SET status = 'failed',
                        error_message = :error,
                        result = '{"success": false}'::jsonb
                    WHERE enrollment_id = :enrollment_id
                      AND step_id = :step_id
                      AND status = 'executing'
                """),
                {
                    "error": error_msg,
                    "enrollment_id": str(enrollment_id),
                    "step_id": step_id,
                },
            )
            return {"success": False, "error": error_msg, "action_type": action_type}

        # 更新步骤执行状态为 completed
        await db.execute(
            text("""
                UPDATE journey_step_executions
                SET status = 'completed',
                    result = :result::jsonb
                WHERE enrollment_id = :enrollment_id
                  AND step_id = :step_id
                  AND status = 'executing'
            """),
            {
                "result": _json_dumps(exec_result),
                "enrollment_id": str(enrollment_id),
                "step_id": step_id,
            },
        )

        log.info("execute_step_done", success=exec_result.get("success", True))
        return {"success": True, "action_type": action_type, "result": exec_result}

    # ------------------------------------------------------------------
    # 定时任务：处理所有到期的 pending steps
    # ------------------------------------------------------------------

    async def process_pending_steps(self, db: AsyncSession) -> dict[str, int]:
        """
        定时任务主入口：被 APScheduler 每分钟调用。

        查找所有 status='active' + next_step_at <= NOW() 的 enrollments，
        逐一推进。

        Args:
            db: AsyncSession（由调用方管理生命周期）

        Returns:
            {"processed": int, "advanced": int, "completed": int, "failed": int}
        """
        now = datetime.now(timezone.utc)
        log = logger.bind(tick_at=now.isoformat())
        log.info("process_pending_steps_start")

        result = await db.execute(
            text("""
                SELECT id
                FROM journey_enrollments
                WHERE status = 'active'
                  AND next_step_at <= :now
                ORDER BY next_step_at ASC
                LIMIT 500
            """),
            {"now": now},
        )
        enrollment_ids = [row[0] for row in result.fetchall()]

        stats = {"processed": 0, "advanced": 0, "completed": 0, "failed": 0}

        for enrollment_id in enrollment_ids:
            stats["processed"] += 1
            try:
                advance_result = await self.advance_enrollment(
                    enrollment_id=uuid.UUID(str(enrollment_id)),
                    db=db,
                )
                status = advance_result.get("status", "")
                if status == "advanced":
                    stats["advanced"] += 1
                elif status == "completed":
                    stats["completed"] += 1
                elif status == "failed":
                    stats["failed"] += 1
            except (OSError, RuntimeError, ValueError) as exc:
                stats["failed"] += 1
                logger.error(
                    "advance_enrollment_unhandled_error",
                    enrollment_id=str(enrollment_id),
                    error=str(exc),
                    exc_info=True,
                )

        log.info("process_pending_steps_done", **stats)
        return stats

    # ------------------------------------------------------------------
    # 私有辅助方法
    # ------------------------------------------------------------------

    async def _fetch_customer_data(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict:
        """从 DB 获取客户基本数据（用于条件评估）。"""
        try:
            result = await db.execute(
                text("""
                    SELECT
                        phone,
                        tags,
                        rfm_segment,
                        ltv_score,
                        recency_days,
                        birthday
                    FROM customers
                    WHERE tenant_id = :tenant_id
                      AND id = :customer_id
                      AND is_deleted = FALSE
                    LIMIT 1
                """),
                {"tenant_id": str(tenant_id), "customer_id": str(customer_id)},
            )
            row = result.fetchone()
            if row:
                return {
                    "phone": row[0],
                    "tags": row[1] or [],
                    "rfm_segment": row[2],
                    "ltv_score": row[3],
                    "recency_days": row[4],
                    "birthday": row[5],
                }
        except (OSError, RuntimeError) as exc:
            logger.warning(
                "fetch_customer_data_failed",
                customer_id=str(customer_id),
                error=str(exc),
            )
        return {}

    async def _create_step_execution(
        self,
        tenant_id: uuid.UUID,
        enrollment_id: uuid.UUID,
        step: dict,
        scheduled_at: datetime,
        db: AsyncSession,
    ) -> None:
        """创建步骤执行记录（status=pending）。"""
        await db.execute(
            text("""
                INSERT INTO journey_step_executions
                    (id, tenant_id, enrollment_id, step_id, action_type,
                     action_config, status, scheduled_at)
                VALUES
                    (:id, :tenant_id, :enrollment_id, :step_id, :action_type,
                     :action_config::jsonb, 'pending', :scheduled_at)
                ON CONFLICT DO NOTHING
            """),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_id),
                "enrollment_id": str(enrollment_id),
                "step_id": step.get("step_id", "unknown"),
                "action_type": step.get("action_type", "wait"),
                "action_config": _json_dumps(step.get("action_config", {})),
                "scheduled_at": scheduled_at,
            },
        )

    async def _complete_enrollment(
        self,
        enrollment_id: Any,
        db: AsyncSession,
    ) -> None:
        """将 enrollment 标记为 completed。"""
        await db.execute(
            text("""
                UPDATE journey_enrollments
                SET status = 'completed',
                    completed_at = NOW()
                WHERE id = :enrollment_id
            """),
            {"enrollment_id": str(enrollment_id)},
        )
        logger.info("enrollment_completed", enrollment_id=str(enrollment_id))

    async def _mark_enrollment_failed(
        self,
        enrollment_id: Any,
        error: str,
        db: AsyncSession,
    ) -> None:
        """将 enrollment 标记为 failed。"""
        await db.execute(
            text("""
                UPDATE journey_enrollments
                SET status = 'failed'
                WHERE id = :enrollment_id
            """),
            {"enrollment_id": str(enrollment_id)},
        )
        logger.error(
            "enrollment_failed",
            enrollment_id=str(enrollment_id),
            error=error,
        )


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _json_dumps(data: Any) -> str:
    """将 dict 序列化为 JSON 字符串（供 JSONB 参数使用）。"""
    import json

    return json.dumps(data, ensure_ascii=False, default=str)
