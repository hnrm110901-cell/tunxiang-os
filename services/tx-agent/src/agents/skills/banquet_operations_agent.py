"""宴会运营优化Agent — 排产优化/产能预警/采购建议/排班"""
import json
import uuid
from datetime import date

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

class BanquetOperationsAgent:
    agent_id = "banquet_operations"
    agent_name = "宴会运营优化"

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def pre_event_check(self, banquet_id: str) -> dict:
        """T-1/T-3 宴会前检查"""
        checks = []
        # 1. 排产计划确认
        plan = await self.db.execute(text("SELECT status FROM banquet_production_plans WHERE banquet_id = :bid AND tenant_id = :tid AND is_deleted = FALSE"), {"bid": banquet_id, "tid": self.tenant_id})
        p = plan.scalar_one_or_none()
        checks.append({"item": "排产计划", "status": "pass" if p == "confirmed" else "fail", "detail": f"当前状态: {p or '未创建'}"})
        # 2. 原料采购到位
        mat = await self.db.execute(text("SELECT COUNT(*) AS total, SUM(CASE WHEN status IN ('received','fulfilled') THEN 1 ELSE 0 END) AS ready FROM banquet_material_requirements WHERE banquet_id = :bid AND tenant_id = :tid AND is_deleted = FALSE"), {"bid": banquet_id, "tid": self.tenant_id})
        m = mat.mappings().first()
        total_mat = m["total"] or 0
        ready_mat = m["ready"] or 0
        checks.append({"item": "原料到位", "status": "pass" if ready_mat >= total_mat else "warning", "detail": f"{ready_mat}/{total_mat}项已到位"})
        # 3. 合同签署
        contract = await self.db.execute(text("SELECT status FROM banquet_contracts WHERE banquet_id = :bid AND tenant_id = :tid AND is_deleted = FALSE"), {"bid": banquet_id, "tid": self.tenant_id})
        c = contract.scalar_one_or_none()
        checks.append({"item": "合同签署", "status": "pass" if c == "signed" else "fail", "detail": f"当前状态: {c or '未创建'}"})
        # 4. 执行SOP
        exec_plan = await self.db.execute(text("SELECT status FROM banquet_execution_plans WHERE banquet_id = :bid AND tenant_id = :tid AND is_deleted = FALSE"), {"bid": banquet_id, "tid": self.tenant_id})
        e = exec_plan.scalar_one_or_none()
        checks.append({"item": "执行计划", "status": "pass" if e else "warning", "detail": f"{'已创建' if e else '未创建'}"})

        all_pass = all(c["status"] == "pass" for c in checks)
        has_fail = any(c["status"] == "fail" for c in checks)
        overall = "ready" if all_pass else ("blocked" if has_fail else "warning")

        await self.db.execute(text("""
            INSERT INTO banquet_ai_decisions (id, tenant_id, banquet_id, agent_type, decision_type, recommendation_json, confidence)
            VALUES (:id, :tid, :bid, 'operations', 'capacity_optimization', :rec::jsonb, :conf)
        """), {"id": str(uuid.uuid4()), "tid": self.tenant_id, "bid": banquet_id, "rec": json.dumps({"overall": overall, "checks": checks}, ensure_ascii=False, default=str), "conf": 0.9 if all_pass else 0.6})
        await self.db.flush()
        logger.info("banquet_pre_event_check", banquet_id=banquet_id, overall=overall)
        return {"banquet_id": banquet_id, "overall": overall, "checks": checks}

    async def optimize_daily_schedule(self, store_id: str, target_date: date) -> dict:
        """当日多场宴会排布优化建议"""
        rows = await self.db.execute(text("""
            SELECT id, banquet_no, event_type, time_slot, table_count, guest_count
            FROM banquets WHERE store_id = :sid AND event_date = :d AND tenant_id = :tid
              AND status IN ('confirmed','preparing','ready') AND is_deleted = FALSE
            ORDER BY time_slot
        """), {"sid": store_id, "d": target_date, "tid": self.tenant_id})
        banquets = [dict(r) for r in rows.mappings().all()]
        suggestions = []
        if len(banquets) > 1:
            lunch = [b for b in banquets if b["time_slot"] in ("lunch", "full_day")]
            dinner = [b for b in banquets if b["time_slot"] in ("dinner", "full_day")]
            if len(lunch) > 2:
                suggestions.append({"type": "warning", "message": f"午市{len(lunch)}场宴会并行，建议错开30分钟开餐"})
            if len(dinner) > 2:
                suggestions.append({"type": "warning", "message": f"晚市{len(dinner)}场宴会并行，建议增加厨房人手"})
            total_tables = sum(b["table_count"] for b in banquets)
            if total_tables > 50:
                suggestions.append({"type": "critical", "message": f"当日共{total_tables}桌，建议启用所有厅房并增配传菜员"})
        if not suggestions:
            suggestions.append({"type": "info", "message": "当日宴会安排合理，无需调整"})
        return {"date": target_date.isoformat(), "banquet_count": len(banquets), "suggestions": suggestions}
