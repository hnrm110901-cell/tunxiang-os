"""宴会排产引擎 — 菜单→排产计划→任务分配→进度追踪

核心流程: 宴会菜单 → 按出菜序分组 → 分配档口/厨师 → 时间轴排布 → 进度追踪。
对接KDS: 排产任务可推送到KDS系统。
金额单位: 分(fen)。
"""

import json
import uuid
from datetime import datetime, time, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# 出菜序配置
COURSE_CONFIG = {
    "cold_dish":    {"name": "凉菜",     "order": 1, "offset_min": 0},
    "hot_dish":     {"name": "热菜",     "order": 2, "offset_min": 15},
    "main_course":  {"name": "大菜",     "order": 3, "offset_min": 30},
    "staple":       {"name": "主食",     "order": 4, "offset_min": 50},
    "soup":         {"name": "汤",       "order": 5, "offset_min": 55},
    "dessert":      {"name": "甜品/水果", "order": 6, "offset_min": 65},
}

# 时段→开餐时间
TIME_SLOT_START = {
    "breakfast": time(7, 30),
    "lunch": time(11, 30),
    "dinner": time(18, 0),
    "full_day": time(11, 30),
}


class BanquetProductionService:
    """宴会排产引擎"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def generate_plan(self, banquet_id: str) -> dict:
        """从宴会菜单自动生成排产计划"""
        # 获取宴会
        row = await self.db.execute(
            text("""
                SELECT id, store_id, event_date, time_slot, table_count, menu_json
                FROM banquets
                WHERE id = :bid AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"bid": banquet_id, "tid": self.tenant_id},
        )
        banquet = row.mappings().first()
        if not banquet:
            raise ValueError(f"宴会不存在: {banquet_id}")

        menu = banquet["menu_json"] or []
        if not menu:
            raise ValueError("菜单为空，无法生成排产计划")

        table_count = banquet["table_count"]
        store_id = str(banquet["store_id"])
        event_date = banquet["event_date"]
        time_slot = banquet["time_slot"]
        service_start = TIME_SLOT_START.get(time_slot, time(11, 30))

        # 创建排产主计划
        plan_id = str(uuid.uuid4())
        total_dishes = len(menu)
        total_servings = total_dishes * table_count

        # 按出菜序分组并生成任务
        course_timeline = []
        tasks_to_insert = []

        for idx, dish in enumerate(menu):
            course_type = dish.get("course_type", "hot_dish")
            config = COURSE_CONFIG.get(course_type, COURSE_CONFIG["hot_dish"])
            course_no = config["order"] * 100 + idx
            offset = config["offset_min"]

            # 计算目标上菜时间
            base_minutes = service_start.hour * 60 + service_start.minute + offset
            target_h, target_m = divmod(base_minutes, 60)
            target_time = time(min(target_h, 23), target_m)

            task_id = str(uuid.uuid4())
            tasks_to_insert.append({
                "id": task_id,
                "tid": self.tenant_id,
                "plan_id": plan_id,
                "course_no": course_no,
                "course_name": config["name"],
                "dish_id": dish.get("product_id") or dish.get("dish_id"),
                "dish_name": dish.get("dish_name", dish.get("name", "未知菜品")),
                "quantity": table_count,
                "prep_time_min": dish.get("prep_time_min", 15),
                "cook_time_min": dish.get("cook_time_min", 10),
                "target_serve_time": target_time.isoformat(),
            })

        # 计算备菜开始时间(最早任务的prep_time_min之前)
        if tasks_to_insert:
            max_prep = max(t["prep_time_min"] + t["cook_time_min"] for t in tasks_to_insert)
            prep_minutes = service_start.hour * 60 + service_start.minute - max_prep - 30
            prep_h, prep_m = divmod(max(prep_minutes, 360), 60)  # 至少6:00
            prep_start = time(prep_h, prep_m)
        else:
            prep_start = time(9, 0)

        # 生成时间轴
        course_groups = {}
        for t in tasks_to_insert:
            cn = t["course_name"]
            if cn not in course_groups:
                course_groups[cn] = {"course_name": cn, "target_time": t["target_serve_time"], "dishes": []}
            course_groups[cn]["dishes"].append({"dish_name": t["dish_name"], "quantity": t["quantity"]})
        course_timeline = list(course_groups.values())

        # 人员需求估算
        staff_required = {
            "chef": max(2, total_dishes // 5),
            "sous_chef": max(1, total_dishes // 8),
            "runner": max(2, table_count // 5),
            "server": max(3, table_count // 3),
        }

        # 插入计划
        await self.db.execute(
            text("""
                INSERT INTO banquet_production_plans
                    (id, tenant_id, banquet_id, store_id, plan_date, total_dishes,
                     total_servings, prep_start_time, service_start_time,
                     course_timeline_json, staff_required_json, status)
                VALUES (:id, :tid, :bid, :sid, :pdate, :dishes,
                    :servings, :prep, :svc,
                    :timeline::jsonb, :staff::jsonb, 'planned')
            """),
            {
                "id": plan_id, "tid": self.tenant_id, "bid": banquet_id,
                "sid": store_id, "pdate": event_date,
                "dishes": total_dishes, "servings": total_servings,
                "prep": prep_start.isoformat(), "svc": service_start.isoformat(),
                "timeline": json.dumps(course_timeline, ensure_ascii=False),
                "staff": json.dumps(staff_required),
            },
        )

        # 插入任务
        for t in tasks_to_insert:
            await self.db.execute(
                text("""
                    INSERT INTO banquet_production_tasks
                        (id, tenant_id, plan_id, course_no, course_name, dish_id,
                         dish_name, quantity, prep_time_min, cook_time_min,
                         target_serve_time, status)
                    VALUES (:id, :tid, :plan_id, :course_no, :course_name, :dish_id,
                        :dish_name, :quantity, :prep_time_min, :cook_time_min,
                        :target_serve_time, 'pending')
                """),
                t,
            )

        await self.db.flush()
        logger.info("banquet_production_plan_generated", plan_id=plan_id, banquet_id=banquet_id,
                     dishes=total_dishes, servings=total_servings)

        return {
            "id": plan_id, "banquet_id": banquet_id, "plan_date": event_date.isoformat(),
            "total_dishes": total_dishes, "total_servings": total_servings,
            "prep_start_time": prep_start.isoformat(),
            "service_start_time": service_start.isoformat(),
            "staff_required": staff_required,
            "course_timeline": course_timeline,
            "tasks_count": len(tasks_to_insert),
            "status": "planned",
        }

    async def assign_tasks(self, plan_id: str, assignments: list[dict]) -> dict:
        """批量分配厨师和档口"""
        updated = 0
        for a in assignments:
            result = await self.db.execute(
                text("""
                    UPDATE banquet_production_tasks
                    SET assigned_chef_id = :chef_id, assigned_chef_name = :chef_name,
                        station_id = :station_id, station_name = :station_name, updated_at = NOW()
                    WHERE id = :task_id AND tenant_id = :tid AND is_deleted = FALSE
                    RETURNING id
                """),
                {
                    "task_id": a["task_id"], "tid": self.tenant_id,
                    "chef_id": a.get("chef_id"), "chef_name": a.get("chef_name"),
                    "station_id": a.get("station_id"), "station_name": a.get("station_name"),
                },
            )
            if result.mappings().first():
                updated += 1

        await self.db.flush()
        logger.info("banquet_tasks_assigned", plan_id=plan_id, updated=updated)
        return {"plan_id": plan_id, "assigned": updated, "total": len(assignments)}

    async def update_task_status(self, task_id: str, new_status: str) -> dict:
        """更新任务状态"""
        valid_transitions = {
            "pending": ["prepping", "cancelled"],
            "prepping": ["cooking", "cancelled"],
            "cooking": ["plated", "cancelled"],
            "plated": ["served"],
            "served": [],
            "cancelled": [],
        }

        row = await self.db.execute(
            text("SELECT status FROM banquet_production_tasks WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE"),
            {"id": task_id, "tid": self.tenant_id},
        )
        current = row.scalar_one_or_none()
        if not current:
            raise ValueError(f"任务不存在: {task_id}")
        if new_status not in valid_transitions.get(current, []):
            raise ValueError(f"状态转换不允许: {current} → {new_status}")

        now = datetime.now(timezone.utc)
        extra_sql = ""
        if new_status == "prepping":
            extra_sql = ", started_at = :now"
        elif new_status in ("served", "cancelled"):
            extra_sql = ", completed_at = :now"

        await self.db.execute(
            text(f"UPDATE banquet_production_tasks SET status = :status, updated_at = :now {extra_sql} WHERE id = :id AND tenant_id = :tid"),
            {"id": task_id, "tid": self.tenant_id, "status": new_status, "now": now},
        )
        await self.db.flush()
        logger.info("banquet_task_status_updated", task_id=task_id, status=new_status)
        return {"id": task_id, "status": new_status}

    async def get_plan(self, plan_id: str) -> dict:
        """获取排产计划含所有任务"""
        row = await self.db.execute(
            text("SELECT * FROM banquet_production_plans WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE"),
            {"id": plan_id, "tid": self.tenant_id},
        )
        plan = row.mappings().first()
        if not plan:
            raise ValueError(f"排产计划不存在: {plan_id}")

        tasks_row = await self.db.execute(
            text("SELECT * FROM banquet_production_tasks WHERE plan_id = :pid AND tenant_id = :tid AND is_deleted = FALSE ORDER BY course_no"),
            {"pid": plan_id, "tid": self.tenant_id},
        )
        tasks = [dict(t) for t in tasks_row.mappings().all()]

        result = dict(plan)
        result["tasks"] = tasks
        return result

    async def get_plan_by_banquet(self, banquet_id: str) -> dict | None:
        """按宴会ID获取排产计划"""
        row = await self.db.execute(
            text("SELECT id FROM banquet_production_plans WHERE banquet_id = :bid AND tenant_id = :tid AND is_deleted = FALSE ORDER BY created_at DESC LIMIT 1"),
            {"bid": banquet_id, "tid": self.tenant_id},
        )
        plan_id = row.scalar_one_or_none()
        if not plan_id:
            return None
        return await self.get_plan(str(plan_id))

    async def confirm_plan(self, plan_id: str, confirmed_by: str) -> dict:
        """确认排产 planned→confirmed"""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            text("""
                UPDATE banquet_production_plans
                SET status = 'confirmed', confirmed_by = :by, confirmed_at = :now, updated_at = :now
                WHERE id = :id AND tenant_id = :tid AND status = 'planned' AND is_deleted = FALSE
                RETURNING id
            """),
            {"id": plan_id, "tid": self.tenant_id, "by": confirmed_by, "now": now},
        )
        if not result.mappings().first():
            raise ValueError(f"排产计划不存在或状态不允许确认: {plan_id}")
        await self.db.flush()
        return {"id": plan_id, "status": "confirmed"}

    async def start_execution(self, plan_id: str) -> dict:
        """开始执行 confirmed→in_progress"""
        result = await self.db.execute(
            text("""
                UPDATE banquet_production_plans SET status = 'in_progress', updated_at = NOW()
                WHERE id = :id AND tenant_id = :tid AND status = 'confirmed' AND is_deleted = FALSE
                RETURNING id
            """),
            {"id": plan_id, "tid": self.tenant_id},
        )
        if not result.mappings().first():
            raise ValueError(f"排产计划不存在或未确认: {plan_id}")
        await self.db.flush()
        return {"id": plan_id, "status": "in_progress"}

    async def complete_plan(self, plan_id: str) -> dict:
        """完成排产"""
        result = await self.db.execute(
            text("""
                UPDATE banquet_production_plans SET status = 'completed', updated_at = NOW()
                WHERE id = :id AND tenant_id = :tid AND status = 'in_progress' AND is_deleted = FALSE
                RETURNING id
            """),
            {"id": plan_id, "tid": self.tenant_id},
        )
        if not result.mappings().first():
            raise ValueError(f"排产计划不存在或未在执行中: {plan_id}")
        await self.db.flush()
        return {"id": plan_id, "status": "completed"}

    async def get_course_progress(self, plan_id: str) -> list:
        """按出菜序统计进度"""
        rows = await self.db.execute(
            text("""
                SELECT course_name,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                       SUM(CASE WHEN status = 'prepping' THEN 1 ELSE 0 END) AS prepping,
                       SUM(CASE WHEN status = 'cooking' THEN 1 ELSE 0 END) AS cooking,
                       SUM(CASE WHEN status = 'plated' THEN 1 ELSE 0 END) AS plated,
                       SUM(CASE WHEN status = 'served' THEN 1 ELSE 0 END) AS served
                FROM banquet_production_tasks
                WHERE plan_id = :pid AND tenant_id = :tid AND is_deleted = FALSE
                GROUP BY course_name
                ORDER BY MIN(course_no)
            """),
            {"pid": plan_id, "tid": self.tenant_id},
        )
        result = []
        for r in rows.mappings().all():
            d = dict(r)
            total = d["total"]
            d["progress_pct"] = round(d["served"] / total * 100, 1) if total > 0 else 0
            result.append(d)
        return result

    async def get_kitchen_timeline(self, plan_id: str) -> list:
        """获取厨房时间轴视图"""
        rows = await self.db.execute(
            text("""
                SELECT target_serve_time, course_name, dish_name, quantity,
                       station_name, assigned_chef_name, status
                FROM banquet_production_tasks
                WHERE plan_id = :pid AND tenant_id = :tid AND is_deleted = FALSE
                ORDER BY target_serve_time, course_no
            """),
            {"pid": plan_id, "tid": self.tenant_id},
        )
        return [dict(r) for r in rows.mappings().all()]
