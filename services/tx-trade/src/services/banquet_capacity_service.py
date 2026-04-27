"""宴会产能管理服务 — 厨房产能查询/冲突检测/排班建议

核心: 按时段管理厨房产能 → 多场宴会并行检测冲突 → 给出排班建议。
"""

import json
import uuid
from datetime import date, datetime, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

DEFAULT_SLOTS = [
    {"time_slot": "morning", "start": "06:00", "end": "09:00"},
    {"time_slot": "lunch_prep", "start": "09:00", "end": "11:00"},
    {"time_slot": "lunch_service", "start": "11:00", "end": "14:00"},
    {"time_slot": "afternoon", "start": "14:00", "end": "16:00"},
    {"time_slot": "dinner_prep", "start": "16:00", "end": "17:30"},
    {"time_slot": "dinner_service", "start": "17:30", "end": "21:00"},
    {"time_slot": "late_night", "start": "21:00", "end": "23:00"},
]


class BanquetCapacityService:
    """宴会产能管理"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def init_daily_capacity(self, store_id: str, slot_date: date) -> list:
        """初始化一天的产能时段"""
        created = []
        for s in DEFAULT_SLOTS:
            sid = str(uuid.uuid4())
            await self.db.execute(
                text("""
                    INSERT INTO kitchen_capacity_slots
                        (id, tenant_id, store_id, slot_date, time_slot, start_time, end_time)
                    VALUES (:id, :tid, :sid, :d, :slot, :st, :et)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "id": sid,
                    "tid": self.tenant_id,
                    "sid": store_id,
                    "d": slot_date,
                    "slot": s["time_slot"],
                    "st": s["start"],
                    "et": s["end"],
                },
            )
            created.append(s["time_slot"])
        await self.db.flush()
        return created

    async def check_capacity(self, store_id: str, slot_date: date, time_slot: str, required_dishes: int) -> dict:
        """检查产能是否充足"""
        row = await self.db.execute(
            text("""
                SELECT * FROM kitchen_capacity_slots
                WHERE store_id = :sid AND slot_date = :d AND time_slot = :slot
                  AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"sid": store_id, "d": slot_date, "slot": time_slot, "tid": self.tenant_id},
        )
        slot = row.mappings().first()
        if not slot:
            # 自动初始化
            await self.init_daily_capacity(store_id, slot_date)
            return await self.check_capacity(store_id, slot_date, time_slot, required_dishes)

        remaining = slot["available_capacity_dishes"] - slot["current_load_dishes"]
        return {
            "available": remaining >= required_dishes and not slot["is_blocked"],
            "current_load": slot["current_load_dishes"],
            "max_capacity": slot["available_capacity_dishes"],
            "remaining": max(0, remaining),
            "utilization_pct": round(slot["current_load_dishes"] / max(slot["available_capacity_dishes"], 1) * 100, 1),
            "is_blocked": slot["is_blocked"],
        }

    async def allocate_capacity(
        self, store_id: str, slot_date: date, time_slot: str, banquet_id: str, dish_count: int
    ) -> dict:
        """分配产能"""
        result = await self.db.execute(
            text("""
                UPDATE kitchen_capacity_slots
                SET current_load_dishes = current_load_dishes + :dishes,
                    current_banquet_count = current_banquet_count + 1,
                    updated_at = NOW()
                WHERE store_id = :sid AND slot_date = :d AND time_slot = :slot
                  AND tenant_id = :tid AND is_deleted = FALSE
                RETURNING current_load_dishes, available_capacity_dishes, max_concurrent_banquets, current_banquet_count
            """),
            {"sid": store_id, "d": slot_date, "slot": time_slot, "tid": self.tenant_id, "dishes": dish_count},
        )
        row = result.mappings().first()
        if not row:
            raise ValueError(f"产能时段不存在: {slot_date} {time_slot}")

        # 检测冲突
        conflicts = []
        if row["current_load_dishes"] > row["available_capacity_dishes"]:
            conflicts.append("dish_overload")
        if row["current_banquet_count"] > row["max_concurrent_banquets"]:
            conflicts.append("banquet_overload")

        for ct in conflicts:
            cid = str(uuid.uuid4())
            await self.db.execute(
                text("""
                    INSERT INTO banquet_capacity_conflicts
                        (id, tenant_id, store_id, conflict_date, time_slot, conflict_type,
                         severity, description, affected_banquet_ids, status)
                    VALUES (:id, :tid, :sid, :d, :slot, :ctype,
                        'critical', :desc, :bids::jsonb, 'open')
                """),
                {
                    "id": cid,
                    "tid": self.tenant_id,
                    "sid": store_id,
                    "d": slot_date,
                    "slot": time_slot,
                    "ctype": ct,
                    "desc": f"{ct}: 当前负载超出产能",
                    "bids": json.dumps([banquet_id]),
                },
            )

        await self.db.flush()
        return {"allocated": True, "conflicts": conflicts}

    async def release_capacity(self, store_id: str, slot_date: date, time_slot: str, dish_count: int) -> dict:
        """释放产能"""
        await self.db.execute(
            text("""
                UPDATE kitchen_capacity_slots
                SET current_load_dishes = GREATEST(0, current_load_dishes - :dishes),
                    current_banquet_count = GREATEST(0, current_banquet_count - 1),
                    updated_at = NOW()
                WHERE store_id = :sid AND slot_date = :d AND time_slot = :slot
                  AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"sid": store_id, "d": slot_date, "slot": time_slot, "tid": self.tenant_id, "dishes": dish_count},
        )
        await self.db.flush()
        return {"released": True}

    async def detect_conflicts(self, store_id: str, slot_date: date) -> list:
        """检测所有时段冲突"""
        rows = await self.db.execute(
            text("""
                SELECT * FROM kitchen_capacity_slots
                WHERE store_id = :sid AND slot_date = :d AND tenant_id = :tid AND is_deleted = FALSE
                ORDER BY start_time
            """),
            {"sid": store_id, "d": slot_date, "tid": self.tenant_id},
        )
        conflicts = []
        for s in rows.mappings().all():
            if s["current_load_dishes"] > s["available_capacity_dishes"]:
                conflicts.append(
                    {
                        "time_slot": s["time_slot"],
                        "type": "dish_overload",
                        "severity": "critical",
                        "load": s["current_load_dishes"],
                        "capacity": s["available_capacity_dishes"],
                    }
                )
            if s["current_banquet_count"] > s["max_concurrent_banquets"]:
                conflicts.append(
                    {
                        "time_slot": s["time_slot"],
                        "type": "banquet_overload",
                        "severity": "warning",
                        "count": s["current_banquet_count"],
                        "max": s["max_concurrent_banquets"],
                    }
                )
        return conflicts

    async def get_daily_overview(self, store_id: str, slot_date: date) -> dict:
        """日产能概览"""
        rows = await self.db.execute(
            text("""
                SELECT * FROM kitchen_capacity_slots
                WHERE store_id = :sid AND slot_date = :d AND tenant_id = :tid AND is_deleted = FALSE
                ORDER BY start_time
            """),
            {"sid": store_id, "d": slot_date, "tid": self.tenant_id},
        )
        slots = []
        peak_slot = None
        peak_pct = 0
        total_pct = 0
        count = 0

        for s in rows.mappings().all():
            cap = max(s["available_capacity_dishes"], 1)
            pct = round(s["current_load_dishes"] / cap * 100, 1)
            slot_info = {
                "time_slot": s["time_slot"],
                "start_time": str(s["start_time"]),
                "end_time": str(s["end_time"]),
                "load": s["current_load_dishes"],
                "capacity": s["available_capacity_dishes"],
                "utilization_pct": pct,
                "banquet_count": s["current_banquet_count"],
                "is_blocked": s["is_blocked"],
            }
            slots.append(slot_info)
            total_pct += pct
            count += 1
            if pct > peak_pct:
                peak_pct = pct
                peak_slot = s["time_slot"]

        return {
            "store_id": store_id,
            "date": slot_date.isoformat(),
            "slots": slots,
            "summary": {
                "peak_slot": peak_slot,
                "peak_utilization_pct": peak_pct,
                "avg_utilization_pct": round(total_pct / max(count, 1), 1),
            },
        }

    async def suggest_staff_requirement(self, store_id: str, slot_date: date) -> dict:
        """基于当日宴会建议排班人数"""
        rows = await self.db.execute(
            text("""
                SELECT COUNT(*) AS banquet_count, SUM(table_count) AS total_tables, SUM(guest_count) AS total_guests
                FROM banquets
                WHERE store_id = :sid AND event_date = :d AND tenant_id = :tid
                  AND status IN ('confirmed','preparing','ready') AND is_deleted = FALSE
            """),
            {"sid": store_id, "d": slot_date, "tid": self.tenant_id},
        )
        r = rows.mappings().first()
        tables = r["total_tables"] or 0
        guests = r["total_guests"] or 0
        return {
            "date": slot_date.isoformat(),
            "banquet_count": r["banquet_count"] or 0,
            "total_tables": tables,
            "total_guests": guests,
            "suggested_staff": {
                "chef": max(2, tables // 4),
                "sous_chef": max(1, tables // 6),
                "cold_station": max(1, tables // 8),
                "hot_station": max(2, tables // 5),
                "pastry": 1 if tables > 0 else 0,
                "runner": max(2, tables // 4),
                "server": max(3, tables // 3),
                "greeter": max(1, r["banquet_count"] or 0),
            },
        }

    async def resolve_conflict(self, conflict_id: str, resolution: str, resolved_by: str) -> dict:
        """解决冲突"""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            text("""
                UPDATE banquet_capacity_conflicts
                SET status = 'resolved', resolution = :res, resolved_by = :by, resolved_at = :now, updated_at = :now
                WHERE id = :id AND tenant_id = :tid AND status IN ('open','acknowledged') AND is_deleted = FALSE
                RETURNING id
            """),
            {"id": conflict_id, "tid": self.tenant_id, "res": resolution, "by": resolved_by, "now": now},
        )
        if not result.mappings().first():
            raise ValueError(f"冲突不存在或已处理: {conflict_id}")
        await self.db.flush()
        return {"id": conflict_id, "status": "resolved"}

    async def list_conflicts(self, store_id: str, date_from: date, date_to: date, status: str | None = None) -> list:
        """列出冲突"""
        sql = """
            SELECT * FROM banquet_capacity_conflicts
            WHERE store_id = :sid AND tenant_id = :tid AND is_deleted = FALSE
              AND conflict_date BETWEEN :df AND :dt
        """
        params: dict = {"sid": store_id, "tid": self.tenant_id, "df": date_from, "dt": date_to}
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY conflict_date, time_slot"

        rows = await self.db.execute(text(sql), params)
        return [dict(r) for r in rows.mappings().all()]
