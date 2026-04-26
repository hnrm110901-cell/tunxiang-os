"""SOP时段调度引擎 — 三层驱动：时间触发 + 事件触发 + AI增强

参考标杆：
- McDonald's 15分钟粒度预测
- Crunchtime AI Actions纠正链
- Byte Coach智能决策建议

核心循环（tick）：
  每15分钟 → 判断时段 → 懒生成任务 → 检查超时 → 返回概况

表依赖（v270-v272）：
  sop_templates / sop_time_slots / sop_tasks / sop_task_instances
  sop_corrective_actions / sop_store_configs
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ── 状态常量 ──

TASK_STATUS_PENDING = "pending"
TASK_STATUS_IN_PROGRESS = "in_progress"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_OVERDUE = "overdue"
TASK_STATUS_SKIPPED = "skipped"
TASK_STATUS_AUTO_COMPLETED = "auto_completed"

CORRECTIVE_STATUS_OPEN = "open"

# ── 事件 → 时段/任务映射 ──

EVENT_SLOT_MAP: dict[str, list[str]] = {
    "ops.daily_close.completed": ["closing"],
    "supply.temperature.abnormal": ["morning_prep"],
    "trade.peak.detected": ["lunch_buildup", "dinner_buildup"],
    "org.shift.started": ["morning_prep", "lunch_buildup", "dinner_buildup"],
}

EVENT_TASK_MAP: dict[str, list[str]] = {
    "ops.daily_close.completed": [
        "closing_daily_settlement",
        "closing_inventory_check",
    ],
    "supply.temperature.abnormal": [
        "morning_prep_cold_storage_check",
    ],
    "trade.peak.detected": [
        "lunch_buildup_prep_level_check",
        "dinner_buildup_prep_restock",
    ],
    "org.shift.started": [
        "morning_prep_equipment_startup",
    ],
}


class SOPSchedulerService:
    """一天节奏SOP调度引擎

    参考标杆：
    - McDonald's 15分钟粒度预测
    - Crunchtime AI Actions纠正链
    - Byte Coach智能决策建议
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ──────────────────────────────────────────────
    # 核心调度循环
    # ──────────────────────────────────────────────

    async def tick(self, tenant_id: str, store_id: str) -> dict:
        """每15分钟触发 — 核心调度循环

        1. 判断当前时段（根据门店配置的SOP模板）
        2. 生成/获取当天的任务实例（懒生成：首次tick该时段时批量创建）
        3. 检查超时任务 → 标记overdue + 创建纠正动作
        4. 检查自动完成条件（IoT/POS/事件数据）
        5. 返回当前时段任务概况
        """
        tid = UUID(tenant_id)
        sid = UUID(store_id)
        now = datetime.now(timezone.utc)
        today = now.date()

        logger.info(
            "sop_scheduler.tick",
            tenant_id=tenant_id,
            store_id=store_id,
            now=now.isoformat(),
        )

        # 1. 获取门店SOP配置
        config = await self.get_store_sop_config(tenant_id, store_id)
        if config is None:
            logger.warning(
                "sop_scheduler.tick.no_config",
                tenant_id=tenant_id,
                store_id=store_id,
            )
            return {
                "status": "no_config",
                "message": "门店未绑定SOP模板",
                "store_id": store_id,
            }

        # 2. 懒生成今日任务实例
        generated = await self.generate_daily_instances(
            tenant_id,
            store_id,
            today,
        )
        if generated > 0:
            logger.info(
                "sop_scheduler.tick.generated",
                tenant_id=tenant_id,
                store_id=store_id,
                count=generated,
            )

        # 3. 判断当前时段
        # 门店时区偏移：默认 Asia/Shanghai = UTC+8
        store_tz_offset = timedelta(hours=8)
        local_now = now + store_tz_offset
        current_time = local_now.time()
        current_slot = await self.get_current_slot(
            tenant_id,
            store_id,
            current_time,
        )

        # 4. 检查超时任务
        overdue_tasks = await self.check_overdue_tasks(tenant_id, store_id)

        # 5. 获取当前时段任务列表
        slot_tasks: list[dict] = []
        slot_info: dict | None = None
        if current_slot is not None:
            slot_info = current_slot
            slot_tasks = await self.get_slot_tasks(
                tenant_id,
                store_id,
                today,
                current_slot["slot_code"],
            )

        # 6. 汇总概况
        summary = await self._get_tick_summary(tid, sid, today)

        return {
            "status": "ok",
            "tick_at": now.isoformat(),
            "store_id": store_id,
            "date": today.isoformat(),
            "current_slot": slot_info,
            "slot_tasks": slot_tasks,
            "overdue_count": len(overdue_tasks),
            "overdue_tasks": overdue_tasks,
            "generated_count": generated,
            "summary": summary,
        }

    # ──────────────────────────────────────────────
    # 每日任务实例生成
    # ──────────────────────────────────────────────

    async def generate_daily_instances(
        self,
        tenant_id: str,
        store_id: str,
        target_date: date,
    ) -> int:
        """为指定门店生成一天的任务实例

        1. 查找门店绑定的SOP模板（sop_store_configs）
        2. 获取模板的所有任务定义
        3. 批量创建task_instances（跳过已存在的，用UNIQUE约束防重）
        4. 计算due_at = target_date + slot.end_time
        返回: 创建的实例数
        """
        tid = UUID(tenant_id)
        sid = UUID(store_id)

        # 获取门店配置
        config_row = await self._get_store_config_row(tid, sid)
        if config_row is None:
            return 0

        template_id = config_row.template_id

        # 获取模板的所有时段
        slots_result = await self.db.execute(
            text("""
                SELECT id, slot_code, start_time, end_time
                FROM sop_time_slots
                WHERE template_id = :template_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND is_active = TRUE
                ORDER BY sort_order
            """),
            {"template_id": template_id, "tenant_id": tid},
        )
        slots = slots_result.fetchall()

        if not slots:
            return 0

        slot_map = {row.id: row for row in slots}
        slot_code_map = {row.id: row.slot_code for row in slots}
        slot_end_map = {row.id: row.end_time for row in slots}

        # 获取模板的所有活跃任务定义
        tasks_result = await self.db.execute(
            text("""
                SELECT id, slot_id, task_code, target_role
                FROM sop_tasks
                WHERE template_id = :template_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND is_active = TRUE
                ORDER BY sort_order
            """),
            {"template_id": template_id, "tenant_id": tid},
        )
        task_defs = tasks_result.fetchall()

        if not task_defs:
            return 0

        # 查询已存在的实例（防重）
        existing_result = await self.db.execute(
            text("""
                SELECT task_id
                FROM sop_task_instances
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND instance_date = :target_date
                  AND is_deleted = FALSE
            """),
            {
                "tenant_id": tid,
                "store_id": sid,
                "target_date": target_date,
            },
        )
        existing_task_ids = {row.task_id for row in existing_result.fetchall()}

        # 批量创建缺失的实例
        created_count = 0
        for task_def in task_defs:
            if task_def.id in existing_task_ids:
                continue

            slot_code = slot_code_map.get(task_def.slot_id, "unknown")
            end_time = slot_end_map.get(task_def.slot_id)

            # due_at = target_date + slot.end_time（UTC+8 → UTC）
            if end_time is not None:
                local_due = datetime.combine(target_date, end_time)
                due_at = local_due - timedelta(hours=8)
                due_at = due_at.replace(tzinfo=timezone.utc)
            else:
                due_at = datetime.combine(
                    target_date,
                    time(23, 0),
                ).replace(tzinfo=timezone.utc)

            instance_id = uuid4()
            await self.db.execute(
                text("""
                    INSERT INTO sop_task_instances (
                        id, tenant_id, store_id, task_id, instance_date,
                        slot_code, target_role, status, due_at
                    ) VALUES (
                        :id, :tenant_id, :store_id, :task_id, :instance_date,
                        :slot_code, :target_role, :status, :due_at
                    )
                    ON CONFLICT DO NOTHING
                """),
                {
                    "id": instance_id,
                    "tenant_id": tid,
                    "store_id": sid,
                    "task_id": task_def.id,
                    "instance_date": target_date,
                    "slot_code": slot_code,
                    "target_role": task_def.target_role,
                    "status": TASK_STATUS_PENDING,
                    "due_at": due_at,
                },
            )
            created_count += 1

        if created_count > 0:
            await self.db.flush()
            logger.info(
                "sop_scheduler.generate_daily_instances",
                tenant_id=tenant_id,
                store_id=store_id,
                date=target_date.isoformat(),
                created=created_count,
                total_defs=len(task_defs),
                skipped=len(existing_task_ids),
            )

        return created_count

    # ──────────────────────────────────────────────
    # 时段查询
    # ──────────────────────────────────────────────

    async def get_current_slot(
        self,
        tenant_id: str,
        store_id: str,
        current_time: time,
    ) -> dict | None:
        """获取当前时段信息

        查找门店SOP模板中，start_time <= current_time < end_time 的时段。
        """
        tid = UUID(tenant_id)
        sid = UUID(store_id)

        config_row = await self._get_store_config_row(tid, sid)
        if config_row is None:
            return None

        result = await self.db.execute(
            text("""
                SELECT
                    ts.id, ts.slot_code, ts.slot_name,
                    ts.start_time, ts.end_time, ts.sort_order
                FROM sop_time_slots ts
                WHERE ts.template_id = :template_id
                  AND ts.tenant_id = :tenant_id
                  AND ts.is_deleted = FALSE
                  AND ts.is_active = TRUE
                  AND ts.start_time <= :current_time
                  AND ts.end_time > :current_time
                ORDER BY ts.sort_order
                LIMIT 1
            """),
            {
                "template_id": config_row.template_id,
                "tenant_id": tid,
                "current_time": current_time,
            },
        )
        row = result.fetchone()
        if row is None:
            return None

        return {
            "id": str(row.id),
            "slot_code": row.slot_code,
            "slot_name": row.slot_name,
            "start_time": row.start_time.isoformat(),
            "end_time": row.end_time.isoformat(),
            "sort_order": row.sort_order,
        }

    async def get_slot_tasks(
        self,
        tenant_id: str,
        store_id: str,
        target_date: date,
        slot_code: str,
        *,
        role: str | None = None,
    ) -> list[dict]:
        """获取指定时段的任务列表（可按角色过滤）

        包含：任务定义 + 实例状态 + AI建议
        """
        tid = UUID(tenant_id)
        sid = UUID(store_id)

        params: dict = {
            "tenant_id": tid,
            "store_id": sid,
            "instance_date": target_date,
            "slot_code": slot_code,
        }

        role_filter = ""
        if role is not None:
            role_filter = "AND ti.target_role = :role"
            params["role"] = role

        result = await self.db.execute(
            text(f"""
                SELECT
                    ti.id AS instance_id,
                    ti.status,
                    ti.started_at,
                    ti.completed_at,
                    ti.due_at,
                    ti.assignee_id,
                    ti.target_role,
                    ti.result,
                    ti.compliance,
                    ti.ai_suggestion,
                    td.id AS task_id,
                    td.task_code,
                    td.task_name,
                    td.task_type,
                    td.priority,
                    td.duration_min,
                    td.instructions,
                    td.checklist_items
                FROM sop_task_instances ti
                JOIN sop_tasks td ON td.id = ti.task_id
                WHERE ti.tenant_id = :tenant_id
                  AND ti.store_id = :store_id
                  AND ti.instance_date = :instance_date
                  AND ti.slot_code = :slot_code
                  AND ti.is_deleted = FALSE
                  {role_filter}
                ORDER BY td.sort_order, td.priority
            """),
            params,
        )
        rows = result.fetchall()

        tasks: list[dict] = []
        for row in rows:
            tasks.append(
                {
                    "instance_id": str(row.instance_id),
                    "task_id": str(row.task_id),
                    "task_code": row.task_code,
                    "task_name": row.task_name,
                    "task_type": row.task_type,
                    "priority": row.priority,
                    "target_role": row.target_role,
                    "status": row.status,
                    "duration_min": row.duration_min,
                    "instructions": row.instructions,
                    "checklist_items": row.checklist_items,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                    "due_at": row.due_at.isoformat() if row.due_at else None,
                    "assignee_id": str(row.assignee_id) if row.assignee_id else None,
                    "result": row.result,
                    "compliance": row.compliance,
                    "ai_suggestion": row.ai_suggestion,
                }
            )

        return tasks

    # ──────────────────────────────────────────────
    # 超时检查
    # ──────────────────────────────────────────────

    async def check_overdue_tasks(
        self,
        tenant_id: str,
        store_id: str,
    ) -> list[dict]:
        """检查超时任务，标记为overdue并创建纠正动作

        条件：status='pending' AND due_at < now()
        """
        tid = UUID(tenant_id)
        sid = UUID(store_id)
        now = datetime.now(timezone.utc)

        # 查找超时的pending任务
        result = await self.db.execute(
            text("""
                SELECT
                    ti.id, ti.task_id, ti.slot_code,
                    ti.target_role, ti.due_at, ti.instance_date,
                    td.task_code, td.task_name, td.priority
                FROM sop_task_instances ti
                JOIN sop_tasks td ON td.id = ti.task_id
                WHERE ti.tenant_id = :tenant_id
                  AND ti.store_id = :store_id
                  AND ti.status = :status_pending
                  AND ti.due_at < :now
                  AND ti.is_deleted = FALSE
            """),
            {
                "tenant_id": tid,
                "store_id": sid,
                "status_pending": TASK_STATUS_PENDING,
                "now": now,
            },
        )
        overdue_rows = result.fetchall()

        if not overdue_rows:
            return []

        overdue_list: list[dict] = []

        for row in overdue_rows:
            # 标记为overdue
            await self.db.execute(
                text("""
                    UPDATE sop_task_instances
                    SET status = :status_overdue,
                        updated_at = NOW()
                    WHERE id = :instance_id
                      AND tenant_id = :tenant_id
                """),
                {
                    "status_overdue": TASK_STATUS_OVERDUE,
                    "instance_id": row.id,
                    "tenant_id": tid,
                },
            )

            # 根据任务优先级决定纠正动作严重程度
            severity = "warning"
            if row.priority == "critical":
                severity = "critical"
            elif row.priority == "high":
                severity = "warning"

            # 创建纠正动作
            action_id = uuid4()
            corrective_due_at = now + timedelta(hours=1)
            await self.db.execute(
                text("""
                    INSERT INTO sop_corrective_actions (
                        id, tenant_id, store_id, source_instance_id,
                        action_type, severity, title, description,
                        assignee_id, due_at, status
                    ) VALUES (
                        :id, :tenant_id, :store_id, :source_instance_id,
                        :action_type, :severity, :title, :description,
                        :assignee_id, :due_at, :status
                    )
                """),
                {
                    "id": action_id,
                    "tenant_id": tid,
                    "store_id": sid,
                    "source_instance_id": row.id,
                    "action_type": "follow_up",
                    "severity": severity,
                    "title": f"任务超时：{row.task_name}",
                    "description": (
                        f"时段 {row.slot_code} 的任务 [{row.task_code}] "
                        f"{row.task_name} 已超时未完成，截止时间为 "
                        f"{row.due_at.isoformat()}"
                    ),
                    # 超时任务纠正动作分配给对应角色的负责人
                    # 实际应查组织表，此处先用占位UUID
                    "assignee_id": tid,
                    "due_at": corrective_due_at,
                    "status": CORRECTIVE_STATUS_OPEN,
                },
            )

            overdue_list.append(
                {
                    "instance_id": str(row.id),
                    "task_code": row.task_code,
                    "task_name": row.task_name,
                    "slot_code": row.slot_code,
                    "priority": row.priority,
                    "due_at": row.due_at.isoformat(),
                    "corrective_action_id": str(action_id),
                    "severity": severity,
                }
            )

        await self.db.flush()

        logger.warning(
            "sop_scheduler.overdue_detected",
            tenant_id=tenant_id,
            store_id=store_id,
            count=len(overdue_list),
            tasks=[t["task_code"] for t in overdue_list],
        )

        return overdue_list

    # ──────────────────────────────────────────────
    # 事件触发
    # ──────────────────────────────────────────────

    async def on_business_event(
        self,
        tenant_id: str,
        event_type: str,
        payload: dict,
    ) -> list[str]:
        """事件触发的SOP任务

        事件映射：
        - ops.daily_close.completed → 触发closing时段的日结相关任务
        - supply.temperature.abnormal → 创建critical纠正动作
        - trade.peak.detected → 触发peak预备任务
        - org.shift.started → 触发当班任务生成

        返回: 触发的任务ID列表
        """
        tid = UUID(tenant_id)
        store_id = payload.get("store_id")
        if store_id is None:
            logger.warning(
                "sop_scheduler.event.no_store_id",
                event_type=event_type,
            )
            return []

        sid = UUID(store_id)
        today = datetime.now(timezone.utc).date()
        triggered_ids: list[str] = []

        logger.info(
            "sop_scheduler.event_received",
            tenant_id=tenant_id,
            event_type=event_type,
            store_id=store_id,
        )

        # ── 温度异常：创建critical纠正动作 ──
        if event_type == "supply.temperature.abnormal":
            await self._handle_temperature_abnormal(
                tid,
                sid,
                payload,
                triggered_ids,
            )
            return triggered_ids

        # ── 通用事件 → 任务映射 ──
        mapped_task_codes = EVENT_TASK_MAP.get(event_type, [])
        if not mapped_task_codes:
            logger.debug(
                "sop_scheduler.event.no_mapping",
                event_type=event_type,
            )
            return []

        for task_code in mapped_task_codes:
            # 查找今日该门店对应task_code的pending实例
            result = await self.db.execute(
                text("""
                    SELECT ti.id
                    FROM sop_task_instances ti
                    JOIN sop_tasks td ON td.id = ti.task_id
                    WHERE ti.tenant_id = :tenant_id
                      AND ti.store_id = :store_id
                      AND ti.instance_date = :today
                      AND td.task_code = :task_code
                      AND ti.status = :status_pending
                      AND ti.is_deleted = FALSE
                    LIMIT 1
                """),
                {
                    "tenant_id": tid,
                    "store_id": sid,
                    "today": today,
                    "task_code": task_code,
                    "status_pending": TASK_STATUS_PENDING,
                },
            )
            row = result.fetchone()
            if row is not None:
                triggered_ids.append(str(row.id))

        if triggered_ids:
            logger.info(
                "sop_scheduler.event.triggered",
                event_type=event_type,
                store_id=store_id,
                triggered_count=len(triggered_ids),
            )

        return triggered_ids

    async def _handle_temperature_abnormal(
        self,
        tid: UUID,
        sid: UUID,
        payload: dict,
        triggered_ids: list[str],
    ) -> None:
        """处理温度异常事件：创建critical纠正动作"""
        now = datetime.now(timezone.utc)
        today = now.date()

        # 查找今日冷库验温任务实例
        result = await self.db.execute(
            text("""
                SELECT ti.id
                FROM sop_task_instances ti
                JOIN sop_tasks td ON td.id = ti.task_id
                WHERE ti.tenant_id = :tenant_id
                  AND ti.store_id = :store_id
                  AND ti.instance_date = :today
                  AND td.task_code LIKE '%cold_storage%'
                  AND ti.is_deleted = FALSE
                LIMIT 1
            """),
            {
                "tenant_id": tid,
                "store_id": sid,
                "today": today,
            },
        )
        instance_row = result.fetchone()

        if instance_row is None:
            logger.warning(
                "sop_scheduler.temp_abnormal.no_instance",
                store_id=str(sid),
            )
            return

        source_instance_id = instance_row.id
        triggered_ids.append(str(source_instance_id))

        # 创建critical纠正动作
        action_id = uuid4()
        temperature = payload.get("temperature", "N/A")
        equipment = payload.get("equipment_name", "未知设备")

        await self.db.execute(
            text("""
                INSERT INTO sop_corrective_actions (
                    id, tenant_id, store_id, source_instance_id,
                    action_type, severity, title, description,
                    assignee_id, due_at, status
                ) VALUES (
                    :id, :tenant_id, :store_id, :source_instance_id,
                    :action_type, :severity, :title, :description,
                    :assignee_id, :due_at, :status
                )
            """),
            {
                "id": action_id,
                "tenant_id": tid,
                "store_id": sid,
                "source_instance_id": source_instance_id,
                "action_type": "immediate",
                "severity": "critical",
                "title": f"温度异常警报：{equipment}",
                "description": (f"设备 {equipment} 温度异常，当前温度 {temperature}。需立即检查并处理，防止食材变质。"),
                "assignee_id": tid,  # 占位，实际应查组织表
                "due_at": now + timedelta(minutes=30),
                "status": CORRECTIVE_STATUS_OPEN,
            },
        )

        await self.db.flush()
        logger.warning(
            "sop_scheduler.temp_abnormal.action_created",
            store_id=str(sid),
            action_id=str(action_id),
            temperature=temperature,
            equipment=equipment,
        )

    # ──────────────────────────────────────────────
    # 每日概况
    # ──────────────────────────────────────────────

    async def get_daily_summary(
        self,
        tenant_id: str,
        store_id: str,
        target_date: date,
    ) -> dict:
        """获取每日SOP执行概况

        返回：{
            total_tasks, completed, pending, overdue, auto_completed,
            completion_rate, by_slot, by_role, corrective_actions
        }
        """
        tid = UUID(tenant_id)
        sid = UUID(store_id)

        # 总体统计
        result = await self.db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                    COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress,
                    COUNT(*) FILTER (WHERE status = 'overdue') AS overdue,
                    COUNT(*) FILTER (WHERE status = 'skipped') AS skipped,
                    COUNT(*) FILTER (WHERE status = 'auto_completed') AS auto_completed
                FROM sop_task_instances
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND instance_date = :target_date
                  AND is_deleted = FALSE
            """),
            {"tenant_id": tid, "store_id": sid, "target_date": target_date},
        )
        overall = result.fetchone()

        total = overall.total if overall else 0
        completed = (overall.completed if overall else 0) + (overall.auto_completed if overall else 0)
        completion_rate = (completed / total * 100) if total > 0 else 0.0

        # 按时段统计
        slot_result = await self.db.execute(
            text("""
                SELECT
                    slot_code,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                    COUNT(*) FILTER (WHERE status = 'overdue') AS overdue,
                    COUNT(*) FILTER (WHERE status = 'auto_completed') AS auto_completed
                FROM sop_task_instances
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND instance_date = :target_date
                  AND is_deleted = FALSE
                GROUP BY slot_code
                ORDER BY slot_code
            """),
            {"tenant_id": tid, "store_id": sid, "target_date": target_date},
        )
        by_slot = [
            {
                "slot_code": row.slot_code,
                "total": row.total,
                "completed": row.completed + row.auto_completed,
                "pending": row.pending,
                "overdue": row.overdue,
            }
            for row in slot_result.fetchall()
        ]

        # 按角色统计
        role_result = await self.db.execute(
            text("""
                SELECT
                    target_role,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                    COUNT(*) FILTER (WHERE status = 'overdue') AS overdue,
                    COUNT(*) FILTER (WHERE status = 'auto_completed') AS auto_completed
                FROM sop_task_instances
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND instance_date = :target_date
                  AND is_deleted = FALSE
                GROUP BY target_role
                ORDER BY target_role
            """),
            {"tenant_id": tid, "store_id": sid, "target_date": target_date},
        )
        by_role = [
            {
                "role": row.target_role,
                "total": row.total,
                "completed": row.completed + row.auto_completed,
                "pending": row.pending,
                "overdue": row.overdue,
            }
            for row in role_result.fetchall()
        ]

        # 纠正动作统计
        ca_result = await self.db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE ca.status = 'open') AS open_count,
                    COUNT(*) FILTER (WHERE ca.status = 'resolved') AS resolved_count,
                    COUNT(*) FILTER (WHERE ca.status = 'escalated') AS escalated_count
                FROM sop_corrective_actions ca
                JOIN sop_task_instances ti ON ti.id = ca.source_instance_id
                WHERE ca.tenant_id = :tenant_id
                  AND ca.store_id = :store_id
                  AND ti.instance_date = :target_date
                  AND ca.is_deleted = FALSE
            """),
            {"tenant_id": tid, "store_id": sid, "target_date": target_date},
        )
        ca_row = ca_result.fetchone()

        return {
            "date": target_date.isoformat(),
            "store_id": store_id,
            "total_tasks": total,
            "completed": overall.completed if overall else 0,
            "pending": overall.pending if overall else 0,
            "in_progress": overall.in_progress if overall else 0,
            "overdue": overall.overdue if overall else 0,
            "skipped": overall.skipped if overall else 0,
            "auto_completed": overall.auto_completed if overall else 0,
            "completion_rate": round(completion_rate, 1),
            "by_slot": by_slot,
            "by_role": by_role,
            "corrective_actions": {
                "open": ca_row.open_count if ca_row else 0,
                "resolved": ca_row.resolved_count if ca_row else 0,
                "escalated": ca_row.escalated_count if ca_row else 0,
            },
        }

    # ──────────────────────────────────────────────
    # 门店SOP配置
    # ──────────────────────────────────────────────

    async def get_store_sop_config(
        self,
        tenant_id: str,
        store_id: str,
    ) -> dict | None:
        """获取门店SOP配置（模板+时段+任务数量）"""
        tid = UUID(tenant_id)
        sid = UUID(store_id)

        result = await self.db.execute(
            text("""
                SELECT
                    sc.id AS config_id,
                    sc.template_id,
                    sc.timezone,
                    sc.custom_overrides,
                    sc.is_active,
                    t.template_name,
                    t.store_format,
                    t.version,
                    (SELECT COUNT(*) FROM sop_time_slots ts
                     WHERE ts.template_id = t.id
                       AND ts.is_deleted = FALSE
                       AND ts.is_active = TRUE) AS slot_count,
                    (SELECT COUNT(*) FROM sop_tasks tk
                     WHERE tk.template_id = t.id
                       AND tk.is_deleted = FALSE
                       AND tk.is_active = TRUE) AS task_count
                FROM sop_store_configs sc
                JOIN sop_templates t ON t.id = sc.template_id
                WHERE sc.tenant_id = :tenant_id
                  AND sc.store_id = :store_id
                  AND sc.is_deleted = FALSE
                  AND sc.is_active = TRUE
                LIMIT 1
            """),
            {"tenant_id": tid, "store_id": sid},
        )
        row = result.fetchone()
        if row is None:
            return None

        return {
            "config_id": str(row.config_id),
            "template_id": str(row.template_id),
            "template_name": row.template_name,
            "store_format": row.store_format,
            "version": row.version,
            "timezone": row.timezone,
            "custom_overrides": row.custom_overrides,
            "slot_count": row.slot_count,
            "task_count": row.task_count,
        }

    async def bind_store_template(
        self,
        tenant_id: str,
        store_id: str,
        template_id: str,
        *,
        timezone: str = "Asia/Shanghai",
        custom_overrides: dict | None = None,
    ) -> dict:
        """绑定门店到SOP模板"""
        tid = UUID(tenant_id)
        sid = UUID(store_id)
        tpl_id = UUID(template_id)

        # 检查模板是否存在
        tpl_result = await self.db.execute(
            text("""
                SELECT id, template_name, store_format
                FROM sop_templates
                WHERE id = :template_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {"template_id": tpl_id, "tenant_id": tid},
        )
        tpl_row = tpl_result.fetchone()
        if tpl_row is None:
            raise ValueError(f"模板不存在: {template_id}")

        # 检查是否已绑定（upsert）
        existing = await self._get_store_config_row(tid, sid)

        config_id = uuid4()
        if existing is not None:
            # 更新现有配置
            await self.db.execute(
                text("""
                    UPDATE sop_store_configs
                    SET template_id = :template_id,
                        timezone = :timezone,
                        custom_overrides = :custom_overrides,
                        is_active = TRUE,
                        updated_at = NOW()
                    WHERE id = :config_id
                      AND tenant_id = :tenant_id
                """),
                {
                    "template_id": tpl_id,
                    "timezone": timezone,
                    "custom_overrides": custom_overrides or {},
                    "config_id": existing.id,
                    "tenant_id": tid,
                },
            )
            config_id = existing.id
            logger.info(
                "sop_scheduler.bind_store.updated",
                tenant_id=tenant_id,
                store_id=store_id,
                template_id=template_id,
            )
        else:
            # 创建新配置
            await self.db.execute(
                text("""
                    INSERT INTO sop_store_configs (
                        id, tenant_id, store_id, template_id,
                        timezone, custom_overrides, is_active
                    ) VALUES (
                        :id, :tenant_id, :store_id, :template_id,
                        :timezone, :custom_overrides, TRUE
                    )
                """),
                {
                    "id": config_id,
                    "tenant_id": tid,
                    "store_id": sid,
                    "template_id": tpl_id,
                    "timezone": timezone,
                    "custom_overrides": custom_overrides or {},
                },
            )
            logger.info(
                "sop_scheduler.bind_store.created",
                tenant_id=tenant_id,
                store_id=store_id,
                template_id=template_id,
            )

        await self.db.flush()

        return {
            "config_id": str(config_id),
            "store_id": store_id,
            "template_id": template_id,
            "template_name": tpl_row.template_name,
            "store_format": tpl_row.store_format,
            "timezone": timezone,
        }

    # ──────────────────────────────────────────────
    # 内部辅助
    # ──────────────────────────────────────────────

    async def _get_store_config_row(self, tid: UUID, sid: UUID):
        """获取门店SOP配置行"""
        result = await self.db.execute(
            text("""
                SELECT id, template_id, timezone, custom_overrides
                FROM sop_store_configs
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND is_deleted = FALSE
                  AND is_active = TRUE
                LIMIT 1
            """),
            {"tenant_id": tid, "store_id": sid},
        )
        return result.fetchone()

    async def _get_tick_summary(
        self,
        tid: UUID,
        sid: UUID,
        target_date: date,
    ) -> dict:
        """获取tick时的快速概况"""
        result = await self.db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status IN ('completed', 'auto_completed')) AS done,
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                    COUNT(*) FILTER (WHERE status = 'overdue') AS overdue,
                    COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress
                FROM sop_task_instances
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND instance_date = :target_date
                  AND is_deleted = FALSE
            """),
            {"tenant_id": tid, "store_id": sid, "target_date": target_date},
        )
        row = result.fetchone()
        if row is None or row.total == 0:
            return {
                "total": 0,
                "done": 0,
                "pending": 0,
                "overdue": 0,
                "in_progress": 0,
                "completion_rate": 0.0,
            }

        return {
            "total": row.total,
            "done": row.done,
            "pending": row.pending,
            "overdue": row.overdue,
            "in_progress": row.in_progress,
            "completion_rate": round(row.done / row.total * 100, 1),
        }
