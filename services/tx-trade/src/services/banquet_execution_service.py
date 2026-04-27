"""宴会执行SOP服务 — 当日执行计划/检查点打卡/延迟处理/升级"""
import json
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

WEDDING_SOP = [
    {"name": "迎宾台搭建", "type": "setup", "time": "16:00", "role": "greeter"},
    {"name": "厅房布置检查", "type": "inspection", "time": "16:30", "role": "manager"},
    {"name": "音响/灯光测试", "type": "inspection", "time": "17:00", "role": "av_tech"},
    {"name": "冷菜摆盘", "type": "kitchen", "time": "17:30", "role": "cold_chef"},
    {"name": "酒水到位", "type": "task", "time": "17:40", "role": "server"},
    {"name": "迎宾开始", "type": "milestone", "time": "18:00", "role": "greeter"},
    {"name": "冷菜上桌", "type": "kitchen", "time": "18:10", "role": "runner"},
    {"name": "热菜第一轮", "type": "kitchen", "time": "18:25", "role": "hot_chef"},
    {"name": "热菜第二轮", "type": "kitchen", "time": "18:45", "role": "hot_chef"},
    {"name": "主食上桌", "type": "kitchen", "time": "19:05", "role": "runner"},
    {"name": "甜品/水果", "type": "kitchen", "time": "19:15", "role": "pastry"},
    {"name": "结算准备", "type": "task", "time": "19:30", "role": "cashier"},
    {"name": "宾客送别", "type": "milestone", "time": "20:00", "role": "manager"},
    {"name": "场地清理", "type": "cleanup", "time": "20:15", "role": "server"},
]
TOUR_GROUP_SOP = [
    {"name": "桌位摆设+茶水", "type": "setup", "time": "10:30", "role": "server"},
    {"name": "导游对接", "type": "milestone", "time": "11:00", "role": "manager"},
    {"name": "冷菜上桌", "type": "kitchen", "time": "11:05", "role": "runner"},
    {"name": "热菜连续上", "type": "kitchen", "time": "11:10", "role": "hot_chef"},
    {"name": "主食/汤", "type": "kitchen", "time": "11:35", "role": "runner"},
    {"name": "旅行社对账", "type": "task", "time": "11:50", "role": "cashier"},
]
CONFERENCE_SOP = [
    {"name": "茶歇台搭建", "type": "setup", "time": "08:00", "role": "server"},
    {"name": "茶歇第一轮补充", "type": "task", "time": "10:00", "role": "server"},
    {"name": "工作餐准备", "type": "kitchen", "time": "11:30", "role": "chef"},
    {"name": "工作餐送达", "type": "milestone", "time": "12:00", "role": "runner"},
    {"name": "茶歇第二轮补充", "type": "task", "time": "14:00", "role": "server"},
    {"name": "场地恢复+结算", "type": "cleanup", "time": "17:00", "role": "manager"},
]
SOP_TEMPLATES = {
    "wedding": WEDDING_SOP,
    "birthday": WEDDING_SOP,
    "business": WEDDING_SOP,
    "tour_group": TOUR_GROUP_SOP,
    "conference": CONFERENCE_SOP,
    "annual_party": WEDDING_SOP,
}


class BanquetExecutionService:
    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def create_plan(self, banquet_id: str) -> dict:
        row = await self.db.execute(
            text(
                "SELECT id, store_id, event_type FROM banquets WHERE id = :bid AND tenant_id = :tid AND is_deleted = FALSE"
            ),
            {"bid": banquet_id, "tid": self.tenant_id},
        )
        banquet = row.mappings().first()
        if not banquet:
            raise ValueError(f"宴会不存在: {banquet_id}")
        checkpoints = SOP_TEMPLATES.get(banquet["event_type"], WEDDING_SOP)
        plan_id = str(uuid.uuid4())
        await self.db.execute(
            text("""
            INSERT INTO banquet_execution_plans (id, tenant_id, banquet_id, store_id, checkpoints_json, total_checkpoints, status)
            VALUES (:id, :tid, :bid, :sid, :cp::jsonb, :total, 'planned')
        """),
            {
                "id": plan_id,
                "tid": self.tenant_id,
                "bid": banquet_id,
                "sid": str(banquet["store_id"]),
                "cp": json.dumps(checkpoints, ensure_ascii=False),
                "total": len(checkpoints),
            },
        )
        for i, cp in enumerate(checkpoints):
            await self.db.execute(
                text("""
                INSERT INTO banquet_execution_logs (id, tenant_id, plan_id, checkpoint_index, checkpoint_name, checkpoint_type, scheduled_time, status)
                VALUES (:id, :tid, :pid, :idx, :name, :ctype, :stime, 'pending')
            """),
                {
                    "id": str(uuid.uuid4()),
                    "tid": self.tenant_id,
                    "pid": plan_id,
                    "idx": i,
                    "name": cp["name"],
                    "ctype": cp["type"],
                    "stime": cp.get("time"),
                },
            )
        await self.db.flush()
        logger.info("banquet_execution_plan_created", plan_id=plan_id, checkpoints=len(checkpoints))
        return {"id": plan_id, "banquet_id": banquet_id, "total_checkpoints": len(checkpoints), "status": "planned"}

    async def start_execution(self, plan_id: str) -> dict:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            text(
                "UPDATE banquet_execution_plans SET status = 'executing', started_at = :now, updated_at = :now WHERE id = :id AND tenant_id = :tid AND status = 'planned' AND is_deleted = FALSE RETURNING id"
            ),
            {"id": plan_id, "tid": self.tenant_id, "now": now},
        )
        if not result.mappings().first():
            raise ValueError(f"计划不存在或状态不允许: {plan_id}")
        await self.db.flush()
        return {"id": plan_id, "status": "executing"}

    async def complete_checkpoint(
        self, log_id: str, executor_id: str = None, executor_name: str = None, issue_note: str = None
    ) -> dict:
        now = datetime.now(timezone.utc)
        row = await self.db.execute(
            text(
                "SELECT plan_id, scheduled_time FROM banquet_execution_logs WHERE id = :id AND tenant_id = :tid AND status IN ('pending','in_progress') AND is_deleted = FALSE"
            ),
            {"id": log_id, "tid": self.tenant_id},
        )
        log = row.mappings().first()
        if not log:
            raise ValueError(f"检查点不存在或已完成: {log_id}")
        delay_min = 0
        if log["scheduled_time"]:
            local_now = now.replace(tzinfo=None)
            sched = datetime.combine(local_now.date(), log["scheduled_time"])
            delay_min = max(0, int((local_now - sched).total_seconds() / 60))
        await self.db.execute(
            text("""
            UPDATE banquet_execution_logs SET status = 'completed', actual_time = :now, delay_min = :delay,
                executor_id = :eid, executor_name = :ename, issue_note = :note, updated_at = :now
            WHERE id = :id AND tenant_id = :tid
        """),
            {
                "id": log_id,
                "tid": self.tenant_id,
                "now": now,
                "delay": delay_min,
                "eid": executor_id,
                "ename": executor_name,
                "note": issue_note,
            },
        )
        await self.db.execute(
            text(
                "UPDATE banquet_execution_plans SET completed_checkpoints = completed_checkpoints + 1, updated_at = :now WHERE id = :pid AND tenant_id = :tid"
            ),
            {"pid": str(log["plan_id"]), "tid": self.tenant_id, "now": now},
        )
        await self.db.flush()
        return {"id": log_id, "status": "completed", "delay_min": delay_min}

    async def get_progress(self, plan_id: str) -> dict:
        plan = await self.db.execute(
            text("SELECT * FROM banquet_execution_plans WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE"),
            {"id": plan_id, "tid": self.tenant_id},
        )
        p = plan.mappings().first()
        if not p:
            raise ValueError(f"计划不存在: {plan_id}")
        logs = await self.db.execute(
            text(
                "SELECT * FROM banquet_execution_logs WHERE plan_id = :pid AND tenant_id = :tid AND is_deleted = FALSE ORDER BY checkpoint_index"
            ),
            {"pid": plan_id, "tid": self.tenant_id},
        )
        return {
            "plan": dict(p),
            "logs": [dict(l) for l in logs.mappings().all()],
            "progress_pct": round(p["completed_checkpoints"] / max(p["total_checkpoints"], 1) * 100, 1),
        }

    async def escalate_checkpoint(self, log_id: str, issue_note: str) -> dict:
        await self.db.execute(
            text(
                "UPDATE banquet_execution_logs SET status = 'escalated', issue_note = :note, updated_at = NOW() WHERE id = :id AND tenant_id = :tid AND status IN ('pending','in_progress') AND is_deleted = FALSE"
            ),
            {"id": log_id, "tid": self.tenant_id, "note": issue_note},
        )
        await self.db.flush()
        return {"id": log_id, "status": "escalated"}
