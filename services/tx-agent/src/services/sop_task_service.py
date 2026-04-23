"""SOP任务服务 — 模板CRUD + 任务实例操作

提供：
- 模板管理（创建/列表/详情/初始化默认）
- 时段管理（添加时段）
- 任务定义管理（添加任务）
- 任务实例操作（开始/完成/跳过/列表/详情）
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ── 默认SOP模板定义 ──

DEFAULT_TIME_SLOTS: dict[str, list[dict]] = {
    "full_service": [
        {"slot_code": "morning_prep", "slot_name": "早间准备", "start_time": "06:00", "end_time": "09:30", "sort_order": 0},
        {"slot_code": "lunch_buildup", "slot_name": "午市预备", "start_time": "09:30", "end_time": "11:00", "sort_order": 1},
        {"slot_code": "lunch_peak", "slot_name": "午市高峰", "start_time": "11:00", "end_time": "14:00", "sort_order": 2},
        {"slot_code": "afternoon_lull", "slot_name": "午后低峰", "start_time": "14:00", "end_time": "17:00", "sort_order": 3},
        {"slot_code": "dinner_buildup", "slot_name": "晚市预备", "start_time": "17:00", "end_time": "18:00", "sort_order": 4},
        {"slot_code": "dinner_peak", "slot_name": "晚市高峰", "start_time": "18:00", "end_time": "21:00", "sort_order": 5},
        {"slot_code": "closing", "slot_name": "闭店收尾", "start_time": "21:00", "end_time": "23:00", "sort_order": 6},
    ],
    "qsr": [
        {"slot_code": "morning_prep", "slot_name": "早间准备", "start_time": "06:00", "end_time": "08:00", "sort_order": 0},
        {"slot_code": "morning_peak", "slot_name": "早餐高峰", "start_time": "08:00", "end_time": "10:00", "sort_order": 1},
        {"slot_code": "lunch_peak", "slot_name": "午餐高峰", "start_time": "10:00", "end_time": "14:00", "sort_order": 2},
        {"slot_code": "afternoon", "slot_name": "下午时段", "start_time": "14:00", "end_time": "17:00", "sort_order": 3},
        {"slot_code": "dinner_peak", "slot_name": "晚餐高峰", "start_time": "17:00", "end_time": "21:00", "sort_order": 4},
        {"slot_code": "closing", "slot_name": "闭店收尾", "start_time": "21:00", "end_time": "23:00", "sort_order": 5},
    ],
}

DEFAULT_TASKS: dict[str, list[dict]] = {
    "morning_prep": [
        {"task_code": "morning_prep_equipment_startup", "task_name": "设备开机检查", "task_type": "checklist", "target_role": "kitchen_lead", "priority": "high", "duration_min": 15, "sort_order": 0},
        {"task_code": "morning_prep_cold_storage_check", "task_name": "冷库验温", "task_type": "inspection", "target_role": "kitchen_lead", "priority": "critical", "duration_min": 10, "sort_order": 1},
        {"task_code": "morning_prep_hygiene_check", "task_name": "卫生检查", "task_type": "checklist", "target_role": "store_manager", "priority": "high", "duration_min": 20, "sort_order": 2},
    ],
    "lunch_buildup": [
        {"task_code": "lunch_buildup_prep_level_check", "task_name": "备料充足度检查", "task_type": "inspection", "target_role": "kitchen_lead", "priority": "high", "duration_min": 10, "sort_order": 0},
        {"task_code": "lunch_buildup_table_setup", "task_name": "台面布置", "task_type": "checklist", "target_role": "floor_lead", "priority": "normal", "duration_min": 15, "sort_order": 1},
    ],
    "closing": [
        {"task_code": "closing_daily_settlement", "task_name": "日结对账", "task_type": "report", "target_role": "cashier", "priority": "critical", "duration_min": 30, "sort_order": 0},
        {"task_code": "closing_inventory_check", "task_name": "收尾盘点", "task_type": "checklist", "target_role": "kitchen_lead", "priority": "high", "duration_min": 20, "sort_order": 1},
        {"task_code": "closing_equipment_shutdown", "task_name": "设备关闭", "task_type": "checklist", "target_role": "kitchen_lead", "priority": "normal", "duration_min": 10, "sort_order": 2},
    ],
}


class SOPTaskService:
    """SOP模板CRUD + 任务实例操作"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ──────────────────────────────────────────────
    # 模板管理
    # ──────────────────────────────────────────────

    async def create_template(
        self,
        tenant_id: str,
        template_name: str,
        store_format: str,
        *,
        description: str | None = None,
        is_default: bool = False,
    ) -> dict:
        """创建SOP模板"""
        tid = UUID(tenant_id)
        template_id = uuid4()

        await self.db.execute(
            text("""
                INSERT INTO sop_templates (
                    id, tenant_id, template_name, store_format,
                    description, is_default, version
                ) VALUES (
                    :id, :tenant_id, :template_name, :store_format,
                    :description, :is_default, 1
                )
            """),
            {
                "id": template_id,
                "tenant_id": tid,
                "template_name": template_name,
                "store_format": store_format,
                "description": description or "",
                "is_default": is_default,
            },
        )
        await self.db.flush()

        logger.info(
            "sop_task.create_template",
            tenant_id=tenant_id,
            template_id=str(template_id),
            template_name=template_name,
            store_format=store_format,
        )

        return {
            "template_id": str(template_id),
            "template_name": template_name,
            "store_format": store_format,
            "description": description,
            "is_default": is_default,
            "version": 1,
        }

    async def list_templates(
        self, tenant_id: str,
        *, store_format: str | None = None,
    ) -> list[dict]:
        """列出租户的所有SOP模板"""
        tid = UUID(tenant_id)
        params: dict = {"tenant_id": tid}
        format_filter = ""
        if store_format is not None:
            format_filter = "AND store_format = :store_format"
            params["store_format"] = store_format

        result = await self.db.execute(
            text(f"""
                SELECT
                    id, template_name, store_format, description,
                    is_default, version, created_at, updated_at
                FROM sop_templates
                WHERE tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  {format_filter}
                ORDER BY is_default DESC, created_at DESC
            """),
            params,
        )
        rows = result.fetchall()
        return [
            {
                "template_id": str(r.id),
                "template_name": r.template_name,
                "store_format": r.store_format,
                "description": r.description,
                "is_default": r.is_default,
                "version": r.version,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]

    async def get_template(self, tenant_id: str, template_id: str) -> dict | None:
        """获取模板详情（含时段+任务列表）"""
        tid = UUID(tenant_id)
        tpl_id = UUID(template_id)

        # 模板基础信息
        tpl_result = await self.db.execute(
            text("""
                SELECT id, template_name, store_format, description,
                       is_default, version, created_at, updated_at
                FROM sop_templates
                WHERE id = :template_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {"template_id": tpl_id, "tenant_id": tid},
        )
        tpl = tpl_result.fetchone()
        if tpl is None:
            return None

        # 时段列表
        slots_result = await self.db.execute(
            text("""
                SELECT id, slot_code, slot_name, start_time, end_time, sort_order
                FROM sop_time_slots
                WHERE template_id = :template_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND is_active = TRUE
                ORDER BY sort_order
            """),
            {"template_id": tpl_id, "tenant_id": tid},
        )
        slots = [
            {
                "slot_id": str(s.id),
                "slot_code": s.slot_code,
                "slot_name": s.slot_name,
                "start_time": s.start_time.isoformat() if s.start_time else None,
                "end_time": s.end_time.isoformat() if s.end_time else None,
                "sort_order": s.sort_order,
            }
            for s in slots_result.fetchall()
        ]

        # 任务列表
        tasks_result = await self.db.execute(
            text("""
                SELECT
                    id, slot_id, task_code, task_name, task_type,
                    target_role, priority, duration_min, instructions,
                    checklist_items, condition_logic, auto_complete, sort_order
                FROM sop_tasks
                WHERE template_id = :template_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND is_active = TRUE
                ORDER BY sort_order
            """),
            {"template_id": tpl_id, "tenant_id": tid},
        )
        tasks = [
            {
                "task_id": str(t.id),
                "slot_id": str(t.slot_id),
                "task_code": t.task_code,
                "task_name": t.task_name,
                "task_type": t.task_type,
                "target_role": t.target_role,
                "priority": t.priority,
                "duration_min": t.duration_min,
                "instructions": t.instructions,
                "checklist_items": t.checklist_items,
                "condition_logic": t.condition_logic,
                "auto_complete": t.auto_complete,
                "sort_order": t.sort_order,
            }
            for t in tasks_result.fetchall()
        ]

        return {
            "template_id": str(tpl.id),
            "template_name": tpl.template_name,
            "store_format": tpl.store_format,
            "description": tpl.description,
            "is_default": tpl.is_default,
            "version": tpl.version,
            "created_at": tpl.created_at.isoformat() if tpl.created_at else None,
            "updated_at": tpl.updated_at.isoformat() if tpl.updated_at else None,
            "time_slots": slots,
            "tasks": tasks,
        }

    async def init_default_template(
        self, tenant_id: str, store_format: str = "full_service",
    ) -> dict:
        """初始化默认SOP模板（含时段和任务）"""
        # 创建模板
        format_names = {
            "full_service": "标准正餐店SOP",
            "qsr": "快餐店SOP",
            "hotpot": "火锅店SOP",
            "bakery": "烘焙店SOP",
        }
        template_name = format_names.get(store_format, f"{store_format}SOP")
        result = await self.create_template(
            tenant_id=tenant_id,
            template_name=template_name,
            store_format=store_format,
            description=f"系统默认{template_name}模板",
            is_default=True,
        )
        template_id = result["template_id"]

        # 创建时段
        time_slots = DEFAULT_TIME_SLOTS.get(store_format, DEFAULT_TIME_SLOTS["full_service"])
        slot_map: dict[str, str] = {}  # slot_code -> slot_id
        for slot_def in time_slots:
            slot_result = await self.add_time_slot(
                tenant_id=tenant_id,
                template_id=template_id,
                slot_code=slot_def["slot_code"],
                slot_name=slot_def["slot_name"],
                start_time=slot_def["start_time"],
                end_time=slot_def["end_time"],
                sort_order=slot_def["sort_order"],
            )
            slot_map[slot_def["slot_code"]] = slot_result["slot_id"]

        # 创建任务
        task_count = 0
        for slot_code, tasks in DEFAULT_TASKS.items():
            if slot_code not in slot_map:
                continue
            slot_id = slot_map[slot_code]
            for task_def in tasks:
                await self.add_task(
                    tenant_id=tenant_id,
                    template_id=template_id,
                    slot_id=slot_id,
                    task_code=task_def["task_code"],
                    task_name=task_def["task_name"],
                    task_type=task_def["task_type"],
                    target_role=task_def["target_role"],
                    priority=task_def["priority"],
                    duration_min=task_def.get("duration_min"),
                    sort_order=task_def["sort_order"],
                )
                task_count += 1

        logger.info(
            "sop_task.init_default_template",
            tenant_id=tenant_id,
            template_id=template_id,
            store_format=store_format,
            slots=len(time_slots),
            tasks=task_count,
        )

        return {
            "template_id": template_id,
            "template_name": template_name,
            "store_format": store_format,
            "time_slots_created": len(time_slots),
            "tasks_created": task_count,
        }

    # ──────────────────────────────────────────────
    # 时段管理
    # ──────────────────────────────────────────────

    async def add_time_slot(
        self,
        tenant_id: str,
        template_id: str,
        slot_code: str,
        slot_name: str,
        start_time: str,
        end_time: str,
        sort_order: int,
    ) -> dict:
        """向模板添加时段"""
        tid = UUID(tenant_id)
        tpl_id = UUID(template_id)
        slot_id = uuid4()

        await self.db.execute(
            text("""
                INSERT INTO sop_time_slots (
                    id, tenant_id, template_id, slot_code, slot_name,
                    start_time, end_time, sort_order
                ) VALUES (
                    :id, :tenant_id, :template_id, :slot_code, :slot_name,
                    :start_time, :end_time, :sort_order
                )
            """),
            {
                "id": slot_id,
                "tenant_id": tid,
                "template_id": tpl_id,
                "slot_code": slot_code,
                "slot_name": slot_name,
                "start_time": start_time,
                "end_time": end_time,
                "sort_order": sort_order,
            },
        )
        await self.db.flush()

        return {
            "slot_id": str(slot_id),
            "template_id": template_id,
            "slot_code": slot_code,
            "slot_name": slot_name,
            "start_time": start_time,
            "end_time": end_time,
            "sort_order": sort_order,
        }

    # ──────────────────────────────────────────────
    # 任务定义管理
    # ──────────────────────────────────────────────

    async def add_task(
        self,
        tenant_id: str,
        template_id: str,
        slot_id: str,
        task_code: str,
        task_name: str,
        task_type: str,
        target_role: str,
        *,
        priority: str = "normal",
        duration_min: int | None = None,
        instructions: str | None = None,
        checklist_items: list[dict] | None = None,
        condition_logic: dict | None = None,
        auto_complete: dict | None = None,
        sort_order: int = 0,
    ) -> dict:
        """向模板添加任务定义"""
        tid = UUID(tenant_id)
        tpl_id = UUID(template_id)
        s_id = UUID(slot_id)
        task_id = uuid4()

        await self.db.execute(
            text("""
                INSERT INTO sop_tasks (
                    id, tenant_id, template_id, slot_id,
                    task_code, task_name, task_type, target_role,
                    priority, duration_min, instructions,
                    checklist_items, condition_logic, auto_complete,
                    sort_order
                ) VALUES (
                    :id, :tenant_id, :template_id, :slot_id,
                    :task_code, :task_name, :task_type, :target_role,
                    :priority, :duration_min, :instructions,
                    :checklist_items, :condition_logic, :auto_complete,
                    :sort_order
                )
            """),
            {
                "id": task_id,
                "tenant_id": tid,
                "template_id": tpl_id,
                "slot_id": s_id,
                "task_code": task_code,
                "task_name": task_name,
                "task_type": task_type,
                "target_role": target_role,
                "priority": priority,
                "duration_min": duration_min,
                "instructions": instructions,
                "checklist_items": checklist_items,
                "condition_logic": condition_logic,
                "auto_complete": auto_complete,
                "sort_order": sort_order,
            },
        )
        await self.db.flush()

        logger.info(
            "sop_task.add_task",
            tenant_id=tenant_id,
            template_id=template_id,
            task_code=task_code,
        )

        return {
            "task_id": str(task_id),
            "template_id": template_id,
            "slot_id": slot_id,
            "task_code": task_code,
            "task_name": task_name,
            "task_type": task_type,
            "target_role": target_role,
            "priority": priority,
            "duration_min": duration_min,
            "sort_order": sort_order,
        }

    # ──────────────────────────────────────────────
    # 任务实例操作
    # ──────────────────────────────────────────────

    async def list_task_instances(
        self,
        tenant_id: str,
        store_id: str,
        *,
        page: int = 1,
        size: int = 20,
        target_date: str | None = None,
        slot_code: str | None = None,
        status: str | None = None,
        role: str | None = None,
    ) -> dict:
        """分页列出门店任务实例"""
        tid = UUID(tenant_id)
        sid = UUID(store_id)
        params: dict = {
            "tenant_id": tid,
            "store_id": sid,
            "limit": size,
            "offset": (page - 1) * size,
        }

        filters = ""
        if target_date is not None:
            filters += " AND ti.instance_date = :target_date"
            params["target_date"] = target_date
        if slot_code is not None:
            filters += " AND ti.slot_code = :slot_code"
            params["slot_code"] = slot_code
        if status is not None:
            filters += " AND ti.status = :status"
            params["status"] = status
        if role is not None:
            filters += " AND ti.target_role = :role"
            params["role"] = role

        # 总数
        count_result = await self.db.execute(
            text(f"""
                SELECT COUNT(*) AS total
                FROM sop_task_instances ti
                WHERE ti.tenant_id = :tenant_id
                  AND ti.store_id = :store_id
                  AND ti.is_deleted = FALSE
                  {filters}
            """),
            params,
        )
        total = count_result.scalar() or 0

        # 数据
        result = await self.db.execute(
            text(f"""
                SELECT
                    ti.id AS instance_id,
                    ti.task_id,
                    ti.instance_date,
                    ti.slot_code,
                    ti.target_role,
                    ti.status,
                    ti.started_at,
                    ti.completed_at,
                    ti.due_at,
                    ti.assignee_id,
                    ti.result,
                    ti.compliance,
                    ti.ai_suggestion,
                    td.task_code,
                    td.task_name,
                    td.task_type,
                    td.priority,
                    td.duration_min
                FROM sop_task_instances ti
                JOIN sop_tasks td ON td.id = ti.task_id
                WHERE ti.tenant_id = :tenant_id
                  AND ti.store_id = :store_id
                  AND ti.is_deleted = FALSE
                  {filters}
                ORDER BY ti.instance_date DESC, td.sort_order
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.fetchall()

        items = [
            {
                "instance_id": str(r.instance_id),
                "task_id": str(r.task_id),
                "task_code": r.task_code,
                "task_name": r.task_name,
                "task_type": r.task_type,
                "priority": r.priority,
                "instance_date": r.instance_date.isoformat() if r.instance_date else None,
                "slot_code": r.slot_code,
                "target_role": r.target_role,
                "status": r.status,
                "duration_min": r.duration_min,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "due_at": r.due_at.isoformat() if r.due_at else None,
                "assignee_id": str(r.assignee_id) if r.assignee_id else None,
                "compliance": r.compliance,
                "ai_suggestion": r.ai_suggestion,
            }
            for r in rows
        ]

        return {"items": items, "total": total}

    async def get_task_instance(
        self, tenant_id: str, instance_id: str,
    ) -> dict | None:
        """获取单个任务实例详情"""
        tid = UUID(tenant_id)
        iid = UUID(instance_id)

        result = await self.db.execute(
            text("""
                SELECT
                    ti.id AS instance_id,
                    ti.task_id,
                    ti.store_id,
                    ti.instance_date,
                    ti.slot_code,
                    ti.target_role,
                    ti.status,
                    ti.started_at,
                    ti.completed_at,
                    ti.due_at,
                    ti.assignee_id,
                    ti.result,
                    ti.compliance,
                    ti.skip_reason,
                    ti.ai_suggestion,
                    td.task_code,
                    td.task_name,
                    td.task_type,
                    td.priority,
                    td.duration_min,
                    td.instructions,
                    td.checklist_items,
                    td.condition_logic,
                    td.auto_complete
                FROM sop_task_instances ti
                JOIN sop_tasks td ON td.id = ti.task_id
                WHERE ti.id = :instance_id
                  AND ti.tenant_id = :tenant_id
                  AND ti.is_deleted = FALSE
            """),
            {"instance_id": iid, "tenant_id": tid},
        )
        row = result.fetchone()
        if row is None:
            return None

        return {
            "instance_id": str(row.instance_id),
            "task_id": str(row.task_id),
            "store_id": str(row.store_id),
            "task_code": row.task_code,
            "task_name": row.task_name,
            "task_type": row.task_type,
            "priority": row.priority,
            "instance_date": row.instance_date.isoformat() if row.instance_date else None,
            "slot_code": row.slot_code,
            "target_role": row.target_role,
            "status": row.status,
            "duration_min": row.duration_min,
            "instructions": row.instructions,
            "checklist_items": row.checklist_items,
            "condition_logic": row.condition_logic,
            "auto_complete": row.auto_complete,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "due_at": row.due_at.isoformat() if row.due_at else None,
            "assignee_id": str(row.assignee_id) if row.assignee_id else None,
            "result": row.result,
            "compliance": row.compliance,
            "skip_reason": row.skip_reason,
            "ai_suggestion": row.ai_suggestion,
        }

    async def start_task(
        self, tenant_id: str, instance_id: str, assignee_id: str,
    ) -> dict:
        """开始任务（pending → in_progress）"""
        tid = UUID(tenant_id)
        iid = UUID(instance_id)
        now = datetime.now(timezone.utc)

        # 原子状态转换：WHERE 同时校验旧状态，防止并发竞态
        result = await self.db.execute(
            text("""
                UPDATE sop_task_instances
                SET status = 'in_progress',
                    assignee_id = :assignee_id,
                    started_at = :now,
                    updated_at = :now
                WHERE id = :instance_id
                  AND tenant_id = :tenant_id
                  AND status = 'pending'
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {
                "instance_id": iid,
                "tenant_id": tid,
                "assignee_id": UUID(assignee_id),
                "now": now,
            },
        )
        if result.fetchone() is None:
            check = await self.db.execute(
                text("SELECT status FROM sop_task_instances WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE"),
                {"id": iid, "tid": tid},
            )
            row = check.fetchone()
            if row is None:
                raise ValueError(f"任务实例不存在: {instance_id}")
            raise ValueError(f"任务状态不允许开始: {row.status}")
        await self.db.flush()

        logger.info(
            "sop_task.start_task",
            instance_id=instance_id,
            assignee_id=assignee_id,
        )

        return {
            "instance_id": instance_id,
            "status": "in_progress",
            "assignee_id": assignee_id,
            "started_at": now.isoformat(),
        }

    async def complete_task(
        self,
        tenant_id: str,
        instance_id: str,
        result_data: dict,
        compliance: str = "pass",
    ) -> dict:
        """完成任务（in_progress → completed）"""
        tid = UUID(tenant_id)
        iid = UUID(instance_id)
        now = datetime.now(timezone.utc)

        # 原子状态转换：WHERE 同时校验旧状态
        result = await self.db.execute(
            text("""
                UPDATE sop_task_instances
                SET status = 'completed',
                    completed_at = :now,
                    result = :result,
                    compliance = :compliance,
                    updated_at = :now
                WHERE id = :instance_id
                  AND tenant_id = :tenant_id
                  AND status IN ('in_progress', 'pending')
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {
                "instance_id": iid,
                "tenant_id": tid,
                "now": now,
                "result": result_data,
                "compliance": compliance,
            },
        )
        if result.fetchone() is None:
            check = await self.db.execute(
                text("SELECT status FROM sop_task_instances WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE"),
                {"id": iid, "tid": tid},
            )
            row = check.fetchone()
            if row is None:
                raise ValueError(f"任务实例不存在: {instance_id}")
            raise ValueError(f"任务状态不允许完成: {row.status}")
        await self.db.flush()

        logger.info(
            "sop_task.complete_task",
            instance_id=instance_id,
            compliance=compliance,
        )

        return {
            "instance_id": instance_id,
            "status": "completed",
            "completed_at": now.isoformat(),
            "compliance": compliance,
        }

    async def skip_task(
        self, tenant_id: str, instance_id: str, reason: str,
    ) -> dict:
        """跳过任务（pending/in_progress → skipped）"""
        tid = UUID(tenant_id)
        iid = UUID(instance_id)
        now = datetime.now(timezone.utc)

        # 检查当前状态
        result = await self.db.execute(
            text("""
                SELECT status FROM sop_task_instances
                WHERE id = :instance_id AND tenant_id = :tenant_id AND is_deleted = FALSE
            """),
            {"instance_id": iid, "tenant_id": tid},
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"任务实例不存在: {instance_id}")
        if row.status not in ("pending", "in_progress"):
            raise ValueError(f"任务状态不允许跳过: {row.status}")

        await self.db.execute(
            text("""
                UPDATE sop_task_instances
                SET status = 'skipped',
                    skip_reason = :reason,
                    updated_at = :now
                WHERE id = :instance_id AND tenant_id = :tenant_id
            """),
            {
                "instance_id": iid,
                "tenant_id": tid,
                "reason": reason,
                "now": now,
            },
        )
        await self.db.flush()

        logger.info(
            "sop_task.skip_task",
            instance_id=instance_id,
            reason=reason,
        )

        return {
            "instance_id": instance_id,
            "status": "skipped",
            "skip_reason": reason,
        }
