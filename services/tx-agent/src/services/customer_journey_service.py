"""客户触达SOP旅程服务 — 模板CRUD + 步骤管理 + 触发引擎 + 执行调度

核心流程:
  1. trigger_journey: 事件触发 → 匹配模板 → 创建enrollment → 计算next_action_at
  2. process_pending_steps: 定时扫描 → 渲染模板 → 发送消息 → 记日志 → 推进步骤

表依赖(v303):
  customer_journey_templates / customer_journey_steps /
  customer_journey_enrollments / customer_journey_step_logs
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ── 预设旅程定义 ──

PRESET_JOURNEYS: list[dict] = [
    {
        "name": "消费后关怀链",
        "trigger_type": "post_payment",
        "trigger_config": {},
        "steps": [
            {
                "name": "用餐反馈收集",
                "delay_minutes": 1440,
                "channel": "wecom_private",
                "content": {
                    "text": "亲爱的{{customer_name}}，感谢您到店用餐！诚邀您进行满意度打分，点击反馈即可获得100积分。"
                },
            },
            {
                "name": "新品推荐",
                "delay_minutes": 10080,
                "channel": "wecom_private",
                "content": {"text": "亲爱的{{customer_name}}，门店最近上新特色菜品，新品9折优惠，欢迎到店品尝！"},
            },
            {
                "name": "活动邀约",
                "delay_minutes": 20160,
                "channel": "wecom_private",
                "content": {
                    "text": "亲爱的{{customer_name}}，{{store_name}}正在举行会员回馈活动，到店享免费饮品一份！"
                },
            },
        ],
    },
    {
        "name": "沉睡客户召回",
        "trigger_type": "dormancy",
        "trigger_config": {"dormancy_days": 30},
        "steps": [
            {
                "name": "温情召回",
                "delay_minutes": 0,
                "channel": "wecom_private",
                "content": {"text": "亲爱的{{customer_name}}，好久不见！我们为您准备了专属回归礼券，期待光临。"},
            },
            {
                "name": "店长亲邀",
                "delay_minutes": 10080,
                "channel": "wecom_private",
                "content": {
                    "text": "{{customer_name}}您好，我是{{store_name}}店长，诚邀您体验新菜品，已为您留了老友专享券。"
                },
            },
        ],
    },
    {
        "name": "生日关怀",
        "trigger_type": "birthday",
        "trigger_config": {},
        "steps": [
            {
                "name": "生日祝福",
                "delay_minutes": 0,
                "channel": "wecom_private",
                "content": {
                    "text": "生日快乐！亲爱的{{customer_name}}，您的生日惊喜已发放到小程序卡包，到店消费使用哦。"
                },
            },
        ],
    },
]


class CustomerJourneyService:
    """客户触达SOP旅程引擎"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ══════════════════════════════════════════════
    # 模板 CRUD
    # ══════════════════════════════════════════════

    async def create_template(
        self,
        tenant_id: str,
        template_name: str,
        trigger_type: str,
        *,
        description: str | None = None,
        trigger_config: dict | None = None,
        audience_filter: dict | None = None,
        is_active: bool = True,
        priority: int = 0,
        max_concurrent: int = 1,
        created_by: str | None = None,
    ) -> dict:
        """创建旅程模板"""
        tid = UUID(tenant_id)
        template_id = uuid4()

        await self.db.execute(
            text("""
                INSERT INTO customer_journey_templates (
                    id, tenant_id, template_name, description, trigger_type,
                    trigger_config, audience_filter, is_active, priority,
                    max_concurrent, created_by
                ) VALUES (
                    :id, :tenant_id, :template_name, :description, :trigger_type,
                    :trigger_config, :audience_filter, :is_active, :priority,
                    :max_concurrent, :created_by
                )
            """),
            {
                "id": template_id,
                "tenant_id": tid,
                "template_name": template_name,
                "description": description or "",
                "trigger_type": trigger_type,
                "trigger_config": json.dumps(trigger_config or {}),
                "audience_filter": json.dumps(audience_filter or {}),
                "is_active": is_active,
                "priority": priority,
                "max_concurrent": max_concurrent,
                "created_by": UUID(created_by) if created_by else None,
            },
        )
        await self.db.flush()

        logger.info(
            "customer_journey.create_template",
            tenant_id=tenant_id,
            template_id=str(template_id),
            trigger_type=trigger_type,
        )

        return {
            "template_id": str(template_id),
            "template_name": template_name,
            "trigger_type": trigger_type,
            "is_active": is_active,
        }

    async def update_template(
        self,
        tenant_id: str,
        template_id: str,
        *,
        template_name: str | None = None,
        description: str | None = None,
        trigger_config: dict | None = None,
        audience_filter: dict | None = None,
        priority: int | None = None,
        max_concurrent: int | None = None,
    ) -> dict:
        """更新旅程模板"""
        tid = UUID(tenant_id)
        tpl_id = UUID(template_id)

        # 构建动态SET子句
        sets: list[str] = ["updated_at = NOW()"]
        params: dict = {"tenant_id": tid, "template_id": tpl_id}

        if template_name is not None:
            sets.append("template_name = :template_name")
            params["template_name"] = template_name
        if description is not None:
            sets.append("description = :description")
            params["description"] = description
        if trigger_config is not None:
            sets.append("trigger_config = :trigger_config")
            params["trigger_config"] = json.dumps(trigger_config)
        if audience_filter is not None:
            sets.append("audience_filter = :audience_filter")
            params["audience_filter"] = json.dumps(audience_filter)
        if priority is not None:
            sets.append("priority = :priority")
            params["priority"] = priority
        if max_concurrent is not None:
            sets.append("max_concurrent = :max_concurrent")
            params["max_concurrent"] = max_concurrent

        set_clause = ", ".join(sets)
        result = await self.db.execute(
            text(f"""
                UPDATE customer_journey_templates
                SET {set_clause}
                WHERE id = :template_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                RETURNING id, template_name, trigger_type, is_active
            """),
            params,
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"模板不存在: {template_id}")

        await self.db.flush()
        logger.info(
            "customer_journey.update_template",
            tenant_id=tenant_id,
            template_id=template_id,
        )

        return {
            "template_id": str(row.id),
            "template_name": row.template_name,
            "trigger_type": row.trigger_type,
            "is_active": row.is_active,
        }

    async def get_template(
        self,
        tenant_id: str,
        template_id: str,
    ) -> dict | None:
        """获取模板详情(含步骤列表)"""
        tid = UUID(tenant_id)
        tpl_id = UUID(template_id)

        tpl_result = await self.db.execute(
            text("""
                SELECT id, template_name, description, trigger_type,
                       trigger_config, audience_filter, is_active, priority,
                       max_concurrent, created_by, created_at, updated_at
                FROM customer_journey_templates
                WHERE id = :template_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {"template_id": tpl_id, "tenant_id": tid},
        )
        tpl = tpl_result.fetchone()
        if tpl is None:
            return None

        # 获取步骤
        steps_result = await self.db.execute(
            text("""
                SELECT id, step_order, step_name, delay_minutes, channel,
                       content_template, condition, skip_if_responded
                FROM customer_journey_steps
                WHERE template_id = :template_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                ORDER BY step_order
            """),
            {"template_id": tpl_id, "tenant_id": tid},
        )
        steps = [
            {
                "step_id": str(s.id),
                "step_order": s.step_order,
                "step_name": s.step_name,
                "delay_minutes": s.delay_minutes,
                "channel": s.channel,
                "content_template": s.content_template,
                "condition": s.condition,
                "skip_if_responded": s.skip_if_responded,
            }
            for s in steps_result.fetchall()
        ]

        return {
            "template_id": str(tpl.id),
            "template_name": tpl.template_name,
            "description": tpl.description,
            "trigger_type": tpl.trigger_type,
            "trigger_config": tpl.trigger_config,
            "audience_filter": tpl.audience_filter,
            "is_active": tpl.is_active,
            "priority": tpl.priority,
            "max_concurrent": tpl.max_concurrent,
            "created_by": str(tpl.created_by) if tpl.created_by else None,
            "created_at": tpl.created_at.isoformat() if tpl.created_at else None,
            "updated_at": tpl.updated_at.isoformat() if tpl.updated_at else None,
            "steps": steps,
        }

    async def list_templates(
        self,
        tenant_id: str,
        *,
        trigger_type: str | None = None,
        is_active: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页列出旅程模板"""
        tid = UUID(tenant_id)
        params: dict = {
            "tenant_id": tid,
            "limit": size,
            "offset": (page - 1) * size,
        }

        filters = ""
        if trigger_type is not None:
            filters += " AND trigger_type = :trigger_type"
            params["trigger_type"] = trigger_type
        if is_active is not None:
            filters += " AND is_active = :is_active"
            params["is_active"] = is_active

        count_result = await self.db.execute(
            text(f"""
                SELECT COUNT(*) AS total
                FROM customer_journey_templates
                WHERE tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  {filters}
            """),
            params,
        )
        total = count_result.scalar() or 0

        result = await self.db.execute(
            text(f"""
                SELECT id, template_name, description, trigger_type,
                       trigger_config, is_active, priority, max_concurrent,
                       created_at, updated_at
                FROM customer_journey_templates
                WHERE tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  {filters}
                ORDER BY priority DESC, created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [
            {
                "template_id": str(r.id),
                "template_name": r.template_name,
                "description": r.description,
                "trigger_type": r.trigger_type,
                "trigger_config": r.trigger_config,
                "is_active": r.is_active,
                "priority": r.priority,
                "max_concurrent": r.max_concurrent,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in result.fetchall()
        ]

        return {"items": items, "total": total}

    async def delete_template(
        self,
        tenant_id: str,
        template_id: str,
    ) -> dict:
        """软删除旅程模板"""
        tid = UUID(tenant_id)
        tpl_id = UUID(template_id)

        result = await self.db.execute(
            text("""
                UPDATE customer_journey_templates
                SET is_deleted = TRUE, updated_at = NOW()
                WHERE id = :template_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {"template_id": tpl_id, "tenant_id": tid},
        )
        if result.fetchone() is None:
            raise ValueError(f"模板不存在: {template_id}")

        # 同时软删除步骤
        await self.db.execute(
            text("""
                UPDATE customer_journey_steps
                SET is_deleted = TRUE, updated_at = NOW()
                WHERE template_id = :template_id
                  AND tenant_id = :tenant_id
            """),
            {"template_id": tpl_id, "tenant_id": tid},
        )
        await self.db.flush()

        logger.info(
            "customer_journey.delete_template",
            tenant_id=tenant_id,
            template_id=template_id,
        )
        return {"template_id": template_id, "deleted": True}

    async def toggle_active(
        self,
        tenant_id: str,
        template_id: str,
    ) -> dict:
        """切换模板启用/停用"""
        tid = UUID(tenant_id)
        tpl_id = UUID(template_id)

        result = await self.db.execute(
            text("""
                UPDATE customer_journey_templates
                SET is_active = NOT is_active, updated_at = NOW()
                WHERE id = :template_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                RETURNING id, is_active
            """),
            {"template_id": tpl_id, "tenant_id": tid},
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"模板不存在: {template_id}")

        await self.db.flush()
        logger.info(
            "customer_journey.toggle_active",
            tenant_id=tenant_id,
            template_id=template_id,
            is_active=row.is_active,
        )
        return {"template_id": template_id, "is_active": row.is_active}

    # ══════════════════════════════════════════════
    # 步骤管理
    # ══════════════════════════════════════════════

    async def add_step(
        self,
        tenant_id: str,
        template_id: str,
        step_name: str,
        channel: str,
        *,
        step_order: int | None = None,
        delay_minutes: int = 0,
        content_template: dict | None = None,
        condition: dict | None = None,
        skip_if_responded: bool = False,
    ) -> dict:
        """添加旅程步骤"""
        tid = UUID(tenant_id)
        tpl_id = UUID(template_id)
        step_id = uuid4()

        # 自动计算step_order
        if step_order is None:
            max_result = await self.db.execute(
                text("""
                    SELECT COALESCE(MAX(step_order), -1) + 1 AS next_order
                    FROM customer_journey_steps
                    WHERE template_id = :template_id
                      AND tenant_id = :tenant_id
                      AND is_deleted = FALSE
                """),
                {"template_id": tpl_id, "tenant_id": tid},
            )
            step_order = max_result.scalar() or 0

        await self.db.execute(
            text("""
                INSERT INTO customer_journey_steps (
                    id, tenant_id, template_id, step_order, step_name,
                    delay_minutes, channel, content_template, condition,
                    skip_if_responded
                ) VALUES (
                    :id, :tenant_id, :template_id, :step_order, :step_name,
                    :delay_minutes, :channel, :content_template, :condition,
                    :skip_if_responded
                )
            """),
            {
                "id": step_id,
                "tenant_id": tid,
                "template_id": tpl_id,
                "step_order": step_order,
                "step_name": step_name,
                "delay_minutes": delay_minutes,
                "channel": channel,
                "content_template": json.dumps(content_template or {}),
                "condition": json.dumps(condition) if condition else None,
                "skip_if_responded": skip_if_responded,
            },
        )
        await self.db.flush()

        logger.info(
            "customer_journey.add_step",
            tenant_id=tenant_id,
            template_id=template_id,
            step_id=str(step_id),
            step_name=step_name,
        )

        return {
            "step_id": str(step_id),
            "template_id": template_id,
            "step_order": step_order,
            "step_name": step_name,
            "delay_minutes": delay_minutes,
            "channel": channel,
        }

    async def update_step(
        self,
        tenant_id: str,
        step_id: str,
        *,
        step_name: str | None = None,
        delay_minutes: int | None = None,
        channel: str | None = None,
        content_template: dict | None = None,
        condition: dict | None = None,
        skip_if_responded: bool | None = None,
    ) -> dict:
        """更新旅程步骤"""
        tid = UUID(tenant_id)
        sid = UUID(step_id)

        sets: list[str] = ["updated_at = NOW()"]
        params: dict = {"tenant_id": tid, "step_id": sid}

        if step_name is not None:
            sets.append("step_name = :step_name")
            params["step_name"] = step_name
        if delay_minutes is not None:
            sets.append("delay_minutes = :delay_minutes")
            params["delay_minutes"] = delay_minutes
        if channel is not None:
            sets.append("channel = :channel")
            params["channel"] = channel
        if content_template is not None:
            sets.append("content_template = :content_template")
            params["content_template"] = json.dumps(content_template)
        if condition is not None:
            sets.append("condition = :condition")
            params["condition"] = json.dumps(condition)
        if skip_if_responded is not None:
            sets.append("skip_if_responded = :skip_if_responded")
            params["skip_if_responded"] = skip_if_responded

        set_clause = ", ".join(sets)
        result = await self.db.execute(
            text(f"""
                UPDATE customer_journey_steps
                SET {set_clause}
                WHERE id = :step_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                RETURNING id, step_name, step_order, channel
            """),
            params,
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"步骤不存在: {step_id}")

        await self.db.flush()
        return {
            "step_id": str(row.id),
            "step_name": row.step_name,
            "step_order": row.step_order,
            "channel": row.channel,
        }

    async def delete_step(
        self,
        tenant_id: str,
        step_id: str,
    ) -> dict:
        """软删除旅程步骤"""
        tid = UUID(tenant_id)
        sid = UUID(step_id)

        result = await self.db.execute(
            text("""
                UPDATE customer_journey_steps
                SET is_deleted = TRUE, updated_at = NOW()
                WHERE id = :step_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {"step_id": sid, "tenant_id": tid},
        )
        if result.fetchone() is None:
            raise ValueError(f"步骤不存在: {step_id}")

        await self.db.flush()
        return {"step_id": step_id, "deleted": True}

    async def reorder_steps(
        self,
        tenant_id: str,
        template_id: str,
        step_ids: list[str],
    ) -> dict:
        """调整步骤顺序"""
        tid = UUID(tenant_id)
        tpl_id = UUID(template_id)

        for order, sid in enumerate(step_ids):
            await self.db.execute(
                text("""
                    UPDATE customer_journey_steps
                    SET step_order = :step_order, updated_at = NOW()
                    WHERE id = :step_id
                      AND template_id = :template_id
                      AND tenant_id = :tenant_id
                      AND is_deleted = FALSE
                """),
                {
                    "step_order": order,
                    "step_id": UUID(sid),
                    "template_id": tpl_id,
                    "tenant_id": tid,
                },
            )

        await self.db.flush()
        logger.info(
            "customer_journey.reorder_steps",
            tenant_id=tenant_id,
            template_id=template_id,
            count=len(step_ids),
        )
        return {"template_id": template_id, "reordered": len(step_ids)}

    # ══════════════════════════════════════════════
    # 核心1: 触发旅程
    # ══════════════════════════════════════════════

    async def trigger_journey(
        self,
        tenant_id: str,
        trigger_type: str,
        customer_id: str,
        store_id: str,
        event_data: dict,
    ) -> list[dict]:
        """事件触发旅程

        1. 查询匹配trigger_type的活跃模板
        2. 检查audience_filter(预留)
        3. 检查max_concurrent限制
        4. 创建enrollment + 计算第一步next_action_at

        返回: 创建的enrollment列表
        """
        tid = UUID(tenant_id)
        cid = UUID(customer_id)
        sid = UUID(store_id)

        # 1. 查匹配模板
        templates_result = await self.db.execute(
            text("""
                SELECT id, template_name, trigger_type, trigger_config,
                       audience_filter, max_concurrent, priority
                FROM customer_journey_templates
                WHERE tenant_id = :tenant_id
                  AND trigger_type = :trigger_type
                  AND is_active = TRUE
                  AND is_deleted = FALSE
                ORDER BY priority DESC
            """),
            {"tenant_id": tid, "trigger_type": trigger_type},
        )
        templates = templates_result.fetchall()

        if not templates:
            logger.debug(
                "customer_journey.trigger.no_templates",
                tenant_id=tenant_id,
                trigger_type=trigger_type,
            )
            return []

        created_enrollments: list[dict] = []
        now = datetime.now(timezone.utc)

        for tpl in templates:
            # 2. audience_filter检查
            audience_filter = tpl.audience_filter or {}
            if audience_filter:
                passed = await self._check_audience_filter(
                    cid, tid, audience_filter,
                )
                if not passed:
                    logger.debug(
                        "customer_journey.trigger.audience_filtered",
                        tenant_id=tenant_id,
                        template_id=str(tpl.id),
                        customer_id=customer_id,
                        filter_keys=list(audience_filter.keys()),
                    )
                    continue

            # 3. 检查max_concurrent
            active_count_result = await self.db.execute(
                text("""
                    SELECT COUNT(*) AS cnt
                    FROM customer_journey_enrollments
                    WHERE tenant_id = :tenant_id
                      AND template_id = :template_id
                      AND customer_id = :customer_id
                      AND status = 'active'
                      AND is_deleted = FALSE
                """),
                {
                    "tenant_id": tid,
                    "template_id": tpl.id,
                    "customer_id": cid,
                },
            )
            active_count = active_count_result.scalar() or 0
            if active_count >= tpl.max_concurrent:
                logger.info(
                    "customer_journey.trigger.max_concurrent",
                    tenant_id=tenant_id,
                    template_id=str(tpl.id),
                    customer_id=customer_id,
                    active_count=active_count,
                )
                continue

            # 4. 获取第一个步骤
            first_step_result = await self.db.execute(
                text("""
                    SELECT id, delay_minutes
                    FROM customer_journey_steps
                    WHERE template_id = :template_id
                      AND tenant_id = :tenant_id
                      AND is_deleted = FALSE
                    ORDER BY step_order
                    LIMIT 1
                """),
                {"template_id": tpl.id, "tenant_id": tid},
            )
            first_step = first_step_result.fetchone()
            if first_step is None:
                logger.warning(
                    "customer_journey.trigger.no_steps",
                    template_id=str(tpl.id),
                )
                continue

            # 计算next_action_at
            next_action_at = now + timedelta(minutes=first_step.delay_minutes)

            # 5. 创建enrollment
            enrollment_id = uuid4()
            await self.db.execute(
                text("""
                    INSERT INTO customer_journey_enrollments (
                        id, tenant_id, template_id, customer_id, store_id,
                        trigger_event, current_step_id, status,
                        next_action_at, started_at
                    ) VALUES (
                        :id, :tenant_id, :template_id, :customer_id, :store_id,
                        :trigger_event, :current_step_id, 'active',
                        :next_action_at, :started_at
                    )
                """),
                {
                    "id": enrollment_id,
                    "tenant_id": tid,
                    "template_id": tpl.id,
                    "customer_id": cid,
                    "store_id": sid,
                    "trigger_event": json.dumps(event_data),
                    "current_step_id": first_step.id,
                    "next_action_at": next_action_at,
                    "started_at": now,
                },
            )

            created_enrollments.append(
                {
                    "enrollment_id": str(enrollment_id),
                    "template_id": str(tpl.id),
                    "template_name": tpl.template_name,
                    "customer_id": customer_id,
                    "next_action_at": next_action_at.isoformat(),
                }
            )

        if created_enrollments:
            await self.db.flush()
            logger.info(
                "customer_journey.trigger.enrolled",
                tenant_id=tenant_id,
                trigger_type=trigger_type,
                customer_id=customer_id,
                count=len(created_enrollments),
            )

        return created_enrollments

    # ══════════════════════════════════════════════
    # 核心2: 处理待执行步骤
    # ══════════════════════════════════════════════

    async def process_pending_steps(self, tenant_id: str) -> dict:
        """定时调度: 处理所有待执行的旅程步骤

        1. 查询 next_action_at <= NOW() AND status='active' 的enrollments
        2. 获取当前步骤 → 渲染模板 → 发送消息 → 记日志
        3. 推进到下一步或标记完成
        """
        tid = UUID(tenant_id)
        now = datetime.now(timezone.utc)

        pending_result = await self.db.execute(
            text("""
                SELECT e.id AS enrollment_id, e.template_id, e.customer_id,
                       e.store_id, e.current_step_id, e.trigger_event,
                       s.step_name, s.channel, s.content_template,
                       s.condition, s.skip_if_responded, s.step_order
                FROM customer_journey_enrollments e
                JOIN customer_journey_steps s ON s.id = e.current_step_id
                WHERE e.tenant_id = :tenant_id
                  AND e.status = 'active'
                  AND e.next_action_at <= :now
                  AND e.is_deleted = FALSE
                  AND s.is_deleted = FALSE
                ORDER BY e.next_action_at
                LIMIT 100
            """),
            {"tenant_id": tid, "now": now},
        )
        pending = pending_result.fetchall()

        processed = 0
        failed = 0

        for enrollment in pending:
            try:
                await self._execute_step(tid, enrollment, now)
                processed += 1
            except (OSError, RuntimeError, ValueError, KeyError) as exc:
                logger.error(
                    "customer_journey.process_step.failed",
                    enrollment_id=str(enrollment.enrollment_id),
                    step_name=enrollment.step_name,
                    error=str(exc),
                    exc_info=True,
                )
                failed += 1

        if processed > 0 or failed > 0:
            await self.db.flush()
            logger.info(
                "customer_journey.process_pending",
                tenant_id=tenant_id,
                processed=processed,
                failed=failed,
            )

        return {"processed": processed, "failed": failed}

    async def _execute_step(
        self,
        tid: UUID,
        enrollment,
        now: datetime,
    ) -> None:
        """执行单个旅程步骤"""
        enrollment_id = enrollment.enrollment_id
        step_id = enrollment.current_step_id

        # 检查skip_if_responded: 是否已有responded日志
        if enrollment.skip_if_responded:
            responded_result = await self.db.execute(
                text("""
                    SELECT 1
                    FROM customer_journey_step_logs
                    WHERE enrollment_id = :enrollment_id
                      AND tenant_id = :tenant_id
                      AND send_status = 'responded'
                      AND is_deleted = FALSE
                    LIMIT 1
                """),
                {"enrollment_id": enrollment_id, "tenant_id": tid},
            )
            if responded_result.fetchone() is not None:
                # 客户已响应, 跳过此步骤
                await self._log_step(
                    tid,
                    enrollment_id,
                    step_id,
                    enrollment.channel,
                    None,
                    "skipped",
                    now,
                )
                await self._advance_to_next_step(tid, enrollment, now)
                return

        # 检查条件分支
        if enrollment.condition is not None:
            condition_met = self._evaluate_condition(
                enrollment.condition,
                enrollment.trigger_event,
            )
            if not condition_met:
                await self._log_step(
                    tid,
                    enrollment_id,
                    step_id,
                    enrollment.channel,
                    None,
                    "skipped",
                    now,
                )
                await self._advance_to_next_step(tid, enrollment, now)
                return

        # 渲染内容模板
        content = self._render_template(
            enrollment.content_template,
            enrollment.trigger_event,
        )

        # 发送消息(此处为消息入队, 实际发送由消息网关处理)
        send_status = "sent"
        failure_reason = None
        try:
            await self._send_message(
                channel=enrollment.channel,
                customer_id=str(enrollment.customer_id),
                content=content,
                tenant_id=str(tid),
            )
        except (OSError, RuntimeError, ValueError, ConnectionError) as exc:
            send_status = "failed"
            failure_reason = str(exc)
            logger.warning(
                "customer_journey.send.failed",
                enrollment_id=str(enrollment_id),
                channel=enrollment.channel,
                error=str(exc),
            )

        # 记日志
        await self._log_step(
            tid,
            enrollment_id,
            step_id,
            enrollment.channel,
            content,
            send_status,
            now,
            failure_reason=failure_reason,
        )

        # 推进到下一步
        await self._advance_to_next_step(tid, enrollment, now)

    async def _advance_to_next_step(
        self,
        tid: UUID,
        enrollment,
        now: datetime,
    ) -> None:
        """推进到下一步骤或标记完成"""
        # 查询下一步骤
        next_step_result = await self.db.execute(
            text("""
                SELECT id, delay_minutes
                FROM customer_journey_steps
                WHERE template_id = :template_id
                  AND tenant_id = :tenant_id
                  AND step_order > :current_order
                  AND is_deleted = FALSE
                ORDER BY step_order
                LIMIT 1
            """),
            {
                "template_id": enrollment.template_id,
                "tenant_id": tid,
                "current_order": enrollment.step_order,
            },
        )
        next_step = next_step_result.fetchone()

        if next_step is None:
            # 旅程完成
            await self.db.execute(
                text("""
                    UPDATE customer_journey_enrollments
                    SET status = 'completed',
                        current_step_id = NULL,
                        next_action_at = NULL,
                        completed_at = :now,
                        updated_at = :now
                    WHERE id = :enrollment_id
                      AND tenant_id = :tenant_id
                """),
                {
                    "enrollment_id": enrollment.enrollment_id,
                    "tenant_id": tid,
                    "now": now,
                },
            )
        else:
            # 推进到下一步
            next_action_at = now + timedelta(minutes=next_step.delay_minutes)
            await self.db.execute(
                text("""
                    UPDATE customer_journey_enrollments
                    SET current_step_id = :next_step_id,
                        next_action_at = :next_action_at,
                        updated_at = :now
                    WHERE id = :enrollment_id
                      AND tenant_id = :tenant_id
                """),
                {
                    "next_step_id": next_step.id,
                    "next_action_at": next_action_at,
                    "enrollment_id": enrollment.enrollment_id,
                    "tenant_id": tid,
                    "now": now,
                },
            )

    async def _log_step(
        self,
        tid: UUID,
        enrollment_id: UUID,
        step_id: UUID,
        channel: str,
        content: dict | None,
        send_status: str,
        now: datetime,
        *,
        failure_reason: str | None = None,
    ) -> None:
        """记录步骤执行日志"""
        log_id = uuid4()
        sent_at = now if send_status in ("sent", "delivered") else None

        await self.db.execute(
            text("""
                INSERT INTO customer_journey_step_logs (
                    id, tenant_id, enrollment_id, step_id, channel,
                    content_sent, send_status, failure_reason, sent_at
                ) VALUES (
                    :id, :tenant_id, :enrollment_id, :step_id, :channel,
                    :content_sent, :send_status, :failure_reason, :sent_at
                )
            """),
            {
                "id": log_id,
                "tenant_id": tid,
                "enrollment_id": enrollment_id,
                "step_id": step_id,
                "channel": channel,
                "content_sent": json.dumps(content) if content else None,
                "send_status": send_status,
                "failure_reason": failure_reason,
                "sent_at": sent_at,
            },
        )

    def _render_template(
        self,
        content_template: dict,
        trigger_event: dict | None,
    ) -> dict:
        """渲染内容模板, 替换变量占位符"""
        if not content_template:
            return {}

        event = trigger_event or {}
        variables = {
            "customer_name": event.get("customer_name", "valued customer"),
            "store_name": event.get("store_name", ""),
            "last_dish": event.get("last_dish", ""),
            "days_since_visit": str(event.get("days_since_visit", "")),
            "points_balance": str(event.get("points_balance", "")),
            "stored_value": str(event.get("stored_value", "")),
        }

        rendered = {}
        for key, value in content_template.items():
            if isinstance(value, str):
                for var_name, var_value in variables.items():
                    value = value.replace(f"{{{{{var_name}}}}}", var_value)
                rendered[key] = value
            else:
                rendered[key] = value

        return rendered

    def _evaluate_condition(
        self,
        condition: dict,
        trigger_event: dict | None,
    ) -> bool:
        """评估条件分支(简单规则引擎)"""
        if not condition:
            return True

        event = trigger_event or {}
        field = condition.get("field", "")
        operator = condition.get("operator", "eq")
        target = condition.get("value")

        actual = event.get(field)
        if actual is None:
            return False

        if operator == "eq":
            return actual == target
        if operator == "gt":
            return float(actual) > float(target)
        if operator == "lt":
            return float(actual) < float(target)
        if operator == "gte":
            return float(actual) >= float(target)
        if operator == "lte":
            return float(actual) <= float(target)
        if operator == "in":
            return actual in (target or [])

        return True

    async def _check_audience_filter(
        self,
        customer_id: UUID,
        tenant_id: UUID,
        criteria: dict,
    ) -> bool:
        """检查会员是否满足受众过滤条件

        支持的条件:
          - member_level: ["gold", "silver"]  → members.level IN (...)
          - tags: ["high_value", "frequent"]  → member_tags.tag_name IN (...)
          - rfm_segment: ["champion", "loyal"] → members.rfm_segment IN (...)
          - min_total_spend_fen: 100000       → members.total_spend_fen >= N
          - last_visit_days: 30              → members.last_visit_at >= NOW() - N days
        """
        try:
            # 基础会员信息检查
            member_result = await self.db.execute(
                text("""
                    SELECT level, rfm_segment, total_spend_fen, last_visit_at
                    FROM members
                    WHERE id = :cid AND tenant_id = :tid AND is_deleted = FALSE
                """),
                {"cid": customer_id, "tid": tenant_id},
            )
            member = member_result.fetchone()
            if member is None:
                logger.debug(
                    "customer_journey.audience_filter.member_not_found",
                    customer_id=str(customer_id),
                )
                return False

            # member_level 检查
            if "member_level" in criteria:
                allowed_levels = criteria["member_level"]
                if member.level not in allowed_levels:
                    return False

            # rfm_segment 检查
            if "rfm_segment" in criteria:
                allowed_segments = criteria["rfm_segment"]
                if member.rfm_segment not in allowed_segments:
                    return False

            # min_total_spend_fen 检查(金额用分)
            if "min_total_spend_fen" in criteria:
                min_spend = int(criteria["min_total_spend_fen"])
                if (member.total_spend_fen or 0) < min_spend:
                    return False

            # last_visit_days 检查
            if "last_visit_days" in criteria:
                max_days = int(criteria["last_visit_days"])
                if member.last_visit_at is None:
                    return False
                cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
                if member.last_visit_at < cutoff:
                    return False

            # tags 检查 — 需要查 member_tags 表
            if "tags" in criteria:
                required_tags = criteria["tags"]
                tag_result = await self.db.execute(
                    text("""
                        SELECT tag_name FROM member_tags
                        WHERE member_id = :cid
                          AND tenant_id = :tid
                          AND tag_name = ANY(:tags)
                          AND is_deleted = FALSE
                    """),
                    {
                        "cid": customer_id,
                        "tid": tenant_id,
                        "tags": required_tags,
                    },
                )
                matched_tags = [row.tag_name for row in tag_result.fetchall()]
                if not matched_tags:
                    return False

            return True

        except SQLAlchemyError:
            logger.exception(
                "customer_journey.audience_filter.db_error",
                customer_id=str(customer_id),
                tenant_id=str(tenant_id),
            )
            # graceful degradation: 查询失败时放行，避免阻断旅程
            return True

    async def _send_message(
        self,
        channel: str,
        customer_id: str,
        content: dict,
        tenant_id: str = "",
    ) -> bool:
        """通过IM推送网关发送消息，返回是否发送成功

        支持渠道:
        - wecom_private: 企微私聊API
        - wecom_group: 企微群发API
        - sms: 短信网关
        - push: 小程序推送
        - wechat_template: 微信模板消息
        """
        logger.info(
            "customer_journey.send_message",
            channel=channel,
            customer_id=customer_id,
            tenant_id=tenant_id,
            content_keys=list(content.keys()),
        )
        import httpx
        import os

        gateway_url = os.getenv("GATEWAY_URL", "http://gateway:8000") + "/api/v1/bff/im/push"
        payload = {
            "tenant_id": tenant_id,
            "member_id": customer_id,
            "channel": channel,
            "content": content,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(gateway_url, json=payload)
                if resp.status_code >= 400:
                    logger.warning(
                        "customer_journey.send_message.gateway_error",
                        status_code=resp.status_code,
                        body=resp.text[:500],
                        channel=channel,
                        customer_id=customer_id,
                    )
                    return False
                logger.info(
                    "customer_journey.send_message.sent",
                    channel=channel,
                    customer_id=customer_id,
                    status_code=resp.status_code,
                )
                return True
        except httpx.HTTPError as exc:
            logger.warning(
                "customer_journey.send_message.http_error",
                error=str(exc),
                channel=channel,
                customer_id=customer_id,
            )
            return False

    # ══════════════════════════════════════════════
    # 手动操作: 暂停/恢复/取消
    # ══════════════════════════════════════════════

    async def pause_enrollment(
        self,
        tenant_id: str,
        enrollment_id: str,
    ) -> dict:
        """暂停旅程实例"""
        tid = UUID(tenant_id)
        eid = UUID(enrollment_id)

        result = await self.db.execute(
            text("""
                UPDATE customer_journey_enrollments
                SET status = 'paused', updated_at = NOW()
                WHERE id = :enrollment_id
                  AND tenant_id = :tenant_id
                  AND status = 'active'
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {"enrollment_id": eid, "tenant_id": tid},
        )
        if result.fetchone() is None:
            raise ValueError(f"旅程实例不存在或状态不允许暂停: {enrollment_id}")

        await self.db.flush()
        logger.info(
            "customer_journey.pause",
            enrollment_id=enrollment_id,
        )
        return {"enrollment_id": enrollment_id, "status": "paused"}

    async def resume_enrollment(
        self,
        tenant_id: str,
        enrollment_id: str,
    ) -> dict:
        """恢复旅程实例"""
        tid = UUID(tenant_id)
        eid = UUID(enrollment_id)
        now = datetime.now(timezone.utc)

        result = await self.db.execute(
            text("""
                UPDATE customer_journey_enrollments
                SET status = 'active',
                    next_action_at = :now,
                    updated_at = :now
                WHERE id = :enrollment_id
                  AND tenant_id = :tenant_id
                  AND status = 'paused'
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {"enrollment_id": eid, "tenant_id": tid, "now": now},
        )
        if result.fetchone() is None:
            raise ValueError(f"旅程实例不存在或状态不允许恢复: {enrollment_id}")

        await self.db.flush()
        logger.info(
            "customer_journey.resume",
            enrollment_id=enrollment_id,
        )
        return {"enrollment_id": enrollment_id, "status": "active"}

    async def cancel_enrollment(
        self,
        tenant_id: str,
        enrollment_id: str,
    ) -> dict:
        """取消旅程实例"""
        tid = UUID(tenant_id)
        eid = UUID(enrollment_id)

        result = await self.db.execute(
            text("""
                UPDATE customer_journey_enrollments
                SET status = 'cancelled',
                    next_action_at = NULL,
                    updated_at = NOW()
                WHERE id = :enrollment_id
                  AND tenant_id = :tenant_id
                  AND status IN ('active', 'paused')
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {"enrollment_id": eid, "tenant_id": tid},
        )
        if result.fetchone() is None:
            raise ValueError(f"旅程实例不存在或状态不允许取消: {enrollment_id}")

        await self.db.flush()
        logger.info(
            "customer_journey.cancel",
            enrollment_id=enrollment_id,
        )
        return {"enrollment_id": enrollment_id, "status": "cancelled"}

    # ══════════════════════════════════════════════
    # 查询: 实例列表/详情
    # ══════════════════════════════════════════════

    async def list_enrollments(
        self,
        tenant_id: str,
        *,
        template_id: str | None = None,
        customer_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页列出旅程实例"""
        tid = UUID(tenant_id)
        params: dict = {
            "tenant_id": tid,
            "limit": size,
            "offset": (page - 1) * size,
        }

        filters = ""
        if template_id is not None:
            filters += " AND e.template_id = :template_id"
            params["template_id"] = UUID(template_id)
        if customer_id is not None:
            filters += " AND e.customer_id = :customer_id"
            params["customer_id"] = UUID(customer_id)
        if status is not None:
            filters += " AND e.status = :status"
            params["status"] = status

        count_result = await self.db.execute(
            text(f"""
                SELECT COUNT(*) AS total
                FROM customer_journey_enrollments e
                WHERE e.tenant_id = :tenant_id
                  AND e.is_deleted = FALSE
                  {filters}
            """),
            params,
        )
        total = count_result.scalar() or 0

        result = await self.db.execute(
            text(f"""
                SELECT e.id, e.template_id, e.customer_id, e.store_id,
                       e.status, e.next_action_at, e.started_at, e.completed_at,
                       t.template_name, t.trigger_type
                FROM customer_journey_enrollments e
                JOIN customer_journey_templates t ON t.id = e.template_id
                WHERE e.tenant_id = :tenant_id
                  AND e.is_deleted = FALSE
                  {filters}
                ORDER BY e.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [
            {
                "enrollment_id": str(r.id),
                "template_id": str(r.template_id),
                "template_name": r.template_name,
                "trigger_type": r.trigger_type,
                "customer_id": str(r.customer_id),
                "store_id": str(r.store_id),
                "status": r.status,
                "next_action_at": r.next_action_at.isoformat() if r.next_action_at else None,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in result.fetchall()
        ]

        return {"items": items, "total": total}

    async def get_enrollment(
        self,
        tenant_id: str,
        enrollment_id: str,
    ) -> dict | None:
        """获取旅程实例详情(含步骤日志)"""
        tid = UUID(tenant_id)
        eid = UUID(enrollment_id)

        # 基础信息
        e_result = await self.db.execute(
            text("""
                SELECT e.id, e.template_id, e.customer_id, e.store_id,
                       e.trigger_event, e.current_step_id, e.status,
                       e.next_action_at, e.started_at, e.completed_at,
                       t.template_name, t.trigger_type
                FROM customer_journey_enrollments e
                JOIN customer_journey_templates t ON t.id = e.template_id
                WHERE e.id = :enrollment_id
                  AND e.tenant_id = :tenant_id
                  AND e.is_deleted = FALSE
            """),
            {"enrollment_id": eid, "tenant_id": tid},
        )
        e = e_result.fetchone()
        if e is None:
            return None

        # 步骤日志
        logs_result = await self.db.execute(
            text("""
                SELECT l.id, l.step_id, l.channel, l.content_sent,
                       l.send_status, l.failure_reason,
                       l.sent_at, l.delivered_at, l.read_at, l.responded_at,
                       s.step_name, s.step_order
                FROM customer_journey_step_logs l
                JOIN customer_journey_steps s ON s.id = l.step_id
                WHERE l.enrollment_id = :enrollment_id
                  AND l.tenant_id = :tenant_id
                  AND l.is_deleted = FALSE
                ORDER BY s.step_order, l.created_at
            """),
            {"enrollment_id": eid, "tenant_id": tid},
        )
        logs = [
            {
                "log_id": str(lg.id),
                "step_id": str(lg.step_id),
                "step_name": lg.step_name,
                "step_order": lg.step_order,
                "channel": lg.channel,
                "content_sent": lg.content_sent,
                "send_status": lg.send_status,
                "failure_reason": lg.failure_reason,
                "sent_at": lg.sent_at.isoformat() if lg.sent_at else None,
                "delivered_at": lg.delivered_at.isoformat() if lg.delivered_at else None,
                "read_at": lg.read_at.isoformat() if lg.read_at else None,
                "responded_at": lg.responded_at.isoformat() if lg.responded_at else None,
            }
            for lg in logs_result.fetchall()
        ]

        return {
            "enrollment_id": str(e.id),
            "template_id": str(e.template_id),
            "template_name": e.template_name,
            "trigger_type": e.trigger_type,
            "customer_id": str(e.customer_id),
            "store_id": str(e.store_id),
            "trigger_event": e.trigger_event,
            "current_step_id": str(e.current_step_id) if e.current_step_id else None,
            "status": e.status,
            "next_action_at": e.next_action_at.isoformat() if e.next_action_at else None,
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "completed_at": e.completed_at.isoformat() if e.completed_at else None,
            "step_logs": logs,
        }

    # ══════════════════════════════════════════════
    # 统计
    # ══════════════════════════════════════════════

    async def get_template_stats(
        self,
        tenant_id: str,
        template_id: str,
    ) -> dict:
        """获取模板统计: 总触发/进行中/完成/各步骤转化率"""
        tid = UUID(tenant_id)
        tpl_id = UUID(template_id)

        # 总体统计
        overall_result = await self.db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'active') AS active,
                    COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE status = 'paused') AS paused,
                    COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled,
                    COUNT(*) FILTER (WHERE status = 'expired') AS expired
                FROM customer_journey_enrollments
                WHERE tenant_id = :tenant_id
                  AND template_id = :template_id
                  AND is_deleted = FALSE
            """),
            {"tenant_id": tid, "template_id": tpl_id},
        )
        overall = overall_result.fetchone()

        total = overall.total if overall else 0
        completed = overall.completed if overall else 0
        completion_rate = (completed / total * 100) if total > 0 else 0.0

        # 各步骤执行统计
        step_stats_result = await self.db.execute(
            text("""
                SELECT
                    s.id AS step_id,
                    s.step_name,
                    s.step_order,
                    COUNT(l.id) AS total_executions,
                    COUNT(l.id) FILTER (WHERE l.send_status = 'sent') AS sent,
                    COUNT(l.id) FILTER (WHERE l.send_status = 'delivered') AS delivered,
                    COUNT(l.id) FILTER (WHERE l.send_status = 'read') AS read_count,
                    COUNT(l.id) FILTER (WHERE l.send_status = 'responded') AS responded,
                    COUNT(l.id) FILTER (WHERE l.send_status = 'failed') AS failed,
                    COUNT(l.id) FILTER (WHERE l.send_status = 'skipped') AS skipped
                FROM customer_journey_steps s
                LEFT JOIN customer_journey_step_logs l
                    ON l.step_id = s.id AND l.is_deleted = FALSE
                    AND l.tenant_id = :tenant_id
                WHERE s.template_id = :template_id
                  AND s.tenant_id = :tenant_id
                  AND s.is_deleted = FALSE
                GROUP BY s.id, s.step_name, s.step_order
                ORDER BY s.step_order
            """),
            {"tenant_id": tid, "template_id": tpl_id},
        )
        step_stats = [
            {
                "step_id": str(r.step_id),
                "step_name": r.step_name,
                "step_order": r.step_order,
                "total_executions": r.total_executions,
                "sent": r.sent,
                "delivered": r.delivered,
                "read": r.read_count,
                "responded": r.responded,
                "failed": r.failed,
                "skipped": r.skipped,
            }
            for r in step_stats_result.fetchall()
        ]

        return {
            "template_id": template_id,
            "total_triggered": total,
            "active": overall.active if overall else 0,
            "completed": completed,
            "paused": overall.paused if overall else 0,
            "cancelled": overall.cancelled if overall else 0,
            "expired": overall.expired if overall else 0,
            "completion_rate": round(completion_rate, 1),
            "step_stats": step_stats,
        }

    # ══════════════════════════════════════════════
    # 预设旅程初始化
    # ══════════════════════════════════════════════

    async def create_preset_journeys(
        self,
        tenant_id: str,
        created_by: str | None = None,
    ) -> dict:
        """初始化3个预设旅程模板"""
        created_templates: list[dict] = []

        for preset in PRESET_JOURNEYS:
            # 创建模板
            result = await self.create_template(
                tenant_id=tenant_id,
                template_name=preset["name"],
                trigger_type=preset["trigger_type"],
                description=f"系统预设: {preset['name']}",
                trigger_config=preset.get("trigger_config"),
                created_by=created_by,
            )
            template_id = result["template_id"]

            # 创建步骤
            for idx, step_def in enumerate(preset["steps"]):
                await self.add_step(
                    tenant_id=tenant_id,
                    template_id=template_id,
                    step_name=step_def["name"],
                    channel=step_def["channel"],
                    step_order=idx,
                    delay_minutes=step_def["delay_minutes"],
                    content_template=step_def["content"],
                )

            created_templates.append(
                {
                    "template_id": template_id,
                    "template_name": preset["name"],
                    "trigger_type": preset["trigger_type"],
                    "steps_count": len(preset["steps"]),
                }
            )

        logger.info(
            "customer_journey.presets_created",
            tenant_id=tenant_id,
            count=len(created_templates),
        )

        return {
            "created": len(created_templates),
            "templates": created_templates,
        }
