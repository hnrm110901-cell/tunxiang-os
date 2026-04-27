"""宴会日调度服务 — 当日多场宴会统筹编排

核心: 聚合当日所有宴会 → 场地分配 → 人员排布 → 厨房负载 → 时间轴生成。
"""

import json
import uuid
from datetime import date, datetime, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class BanquetSchedulerService:
    """宴会日调度"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def generate_daily_schedule(self, store_id: str, schedule_date: date) -> dict:
        """生成/更新当日调度"""
        # 获取当日所有宴会
        rows = await self.db.execute(
            text("""
                SELECT b.id, b.banquet_no, b.event_name, b.event_type, b.time_slot,
                       b.guest_count, b.table_count, b.venue_id, b.status,
                       bv.venue_name
                FROM banquets b
                LEFT JOIN banquet_venues bv ON bv.id = b.venue_id AND bv.tenant_id = b.tenant_id
                WHERE b.store_id = :sid AND b.event_date = :d AND b.tenant_id = :tid
                  AND b.status IN ('confirmed','preparing','ready','in_progress') AND b.is_deleted = FALSE
                ORDER BY b.time_slot, b.created_at
            """),
            {"sid": store_id, "d": schedule_date, "tid": self.tenant_id},
        )
        banquets = rows.mappings().all()

        banquet_ids = [str(b["id"]) for b in banquets]
        total_guests = sum(b["guest_count"] for b in banquets)
        total_tables = sum(b["table_count"] for b in banquets)

        # 场地分配
        venue_allocation = {}
        for b in banquets:
            vid = str(b["venue_id"]) if b["venue_id"] else "unassigned"
            venue_allocation[vid] = {
                "banquet_id": str(b["id"]),
                "banquet_no": b["banquet_no"],
                "venue_name": b["venue_name"] or "未分配",
                "time_slot": b["time_slot"],
                "table_count": b["table_count"],
                "guest_count": b["guest_count"],
            }

        # 时间轴
        timeline = []
        for b in banquets:
            timeline.append(
                {
                    "time": b["time_slot"],
                    "event": "banquet_start",
                    "banquet_id": str(b["id"]),
                    "description": f"{b['event_name'] or b['banquet_no']} - {b['guest_count']}人{b['table_count']}桌",
                }
            )

        # 厨房负载(从产能表获取)
        cap_rows = await self.db.execute(
            text("""
                SELECT time_slot, current_load_dishes, available_capacity_dishes
                FROM kitchen_capacity_slots
                WHERE store_id = :sid AND slot_date = :d AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"sid": store_id, "d": schedule_date, "tid": self.tenant_id},
        )
        kitchen_load = {}
        for c in cap_rows.mappings().all():
            cap = max(c["available_capacity_dishes"], 1)
            kitchen_load[c["time_slot"]] = {
                "dishes": c["current_load_dishes"],
                "capacity_pct": round(c["current_load_dishes"] / cap * 100, 1),
            }

        # Upsert
        schedule_id = str(uuid.uuid4())
        await self.db.execute(
            text("""
                INSERT INTO banquet_day_schedules
                    (id, tenant_id, store_id, schedule_date, banquet_ids, banquet_count,
                     total_guests, total_tables, venue_allocation_json,
                     timeline_json, kitchen_load_json, status)
                VALUES (:id, :tid, :sid, :d, :bids::jsonb, :cnt,
                    :guests, :tables, :venue::jsonb,
                    :timeline::jsonb, :kitchen::jsonb, 'planned')
                ON CONFLICT (tenant_id, store_id, schedule_date) WHERE is_deleted = FALSE
                DO UPDATE SET
                    banquet_ids = EXCLUDED.banquet_ids,
                    banquet_count = EXCLUDED.banquet_count,
                    total_guests = EXCLUDED.total_guests,
                    total_tables = EXCLUDED.total_tables,
                    venue_allocation_json = EXCLUDED.venue_allocation_json,
                    timeline_json = EXCLUDED.timeline_json,
                    kitchen_load_json = EXCLUDED.kitchen_load_json,
                    updated_at = NOW()
                RETURNING id
            """),
            {
                "id": schedule_id,
                "tid": self.tenant_id,
                "sid": store_id,
                "d": schedule_date,
                "bids": json.dumps(banquet_ids),
                "cnt": len(banquets),
                "guests": total_guests,
                "tables": total_tables,
                "venue": json.dumps(venue_allocation, ensure_ascii=False),
                "timeline": json.dumps(timeline, ensure_ascii=False),
                "kitchen": json.dumps(kitchen_load),
            },
        )
        row = (
            await self.db.execute(
                text(
                    "SELECT id FROM banquet_day_schedules WHERE store_id = :sid AND schedule_date = :d AND tenant_id = :tid AND is_deleted = FALSE"
                ),
                {"sid": store_id, "d": schedule_date, "tid": self.tenant_id},
            )
        ).scalar_one()

        await self.db.flush()
        logger.info(
            "banquet_daily_schedule_generated",
            store_id=store_id,
            date=schedule_date.isoformat(),
            banquets=len(banquets),
            guests=total_guests,
        )

        return {
            "id": str(row),
            "store_id": store_id,
            "date": schedule_date.isoformat(),
            "banquet_count": len(banquets),
            "total_guests": total_guests,
            "total_tables": total_tables,
            "venue_allocation": venue_allocation,
            "timeline": timeline,
            "kitchen_load": kitchen_load,
            "status": "planned",
        }

    async def get_schedule(self, store_id: str, schedule_date: date) -> dict | None:
        """获取调度"""
        row = await self.db.execute(
            text(
                "SELECT * FROM banquet_day_schedules WHERE store_id = :sid AND schedule_date = :d AND tenant_id = :tid AND is_deleted = FALSE"
            ),
            {"sid": store_id, "d": schedule_date, "tid": self.tenant_id},
        )
        result = row.mappings().first()
        return dict(result) if result else None

    async def confirm_schedule(self, schedule_id: str, confirmed_by: str) -> dict:
        """确认调度"""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            text("""
                UPDATE banquet_day_schedules SET status = 'confirmed', confirmed_by = :by, confirmed_at = :now, updated_at = :now
                WHERE id = :id AND tenant_id = :tid AND status = 'planned' AND is_deleted = FALSE RETURNING id
            """),
            {"id": schedule_id, "tid": self.tenant_id, "by": confirmed_by, "now": now},
        )
        if not result.mappings().first():
            raise ValueError(f"调度不存在或状态不允许: {schedule_id}")
        await self.db.flush()
        return {"id": schedule_id, "status": "confirmed"}

    async def start_execution(self, schedule_id: str) -> dict:
        """开始执行"""
        result = await self.db.execute(
            text(
                "UPDATE banquet_day_schedules SET status = 'executing', updated_at = NOW() WHERE id = :id AND tenant_id = :tid AND status = 'confirmed' AND is_deleted = FALSE RETURNING id"
            ),
            {"id": schedule_id, "tid": self.tenant_id},
        )
        if not result.mappings().first():
            raise ValueError(f"调度不存在或未确认: {schedule_id}")
        await self.db.flush()
        return {"id": schedule_id, "status": "executing"}

    async def complete_schedule(self, schedule_id: str) -> dict:
        """完成调度"""
        result = await self.db.execute(
            text(
                "UPDATE banquet_day_schedules SET status = 'completed', updated_at = NOW() WHERE id = :id AND tenant_id = :tid AND status = 'executing' AND is_deleted = FALSE RETURNING id"
            ),
            {"id": schedule_id, "tid": self.tenant_id},
        )
        if not result.mappings().first():
            raise ValueError(f"调度不存在或未在执行中: {schedule_id}")
        await self.db.flush()
        return {"id": schedule_id, "status": "completed"}

    async def allocate_staff(self, schedule_id: str, staff_assignments: list[dict]) -> dict:
        """分配人员到各宴会"""
        import json as json_mod

        staff_json = json_mod.dumps(staff_assignments, ensure_ascii=False)
        await self.db.execute(
            text(
                "UPDATE banquet_day_schedules SET staff_allocation_json = :staff::jsonb, updated_at = NOW() WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE"
            ),
            {"id": schedule_id, "tid": self.tenant_id, "staff": staff_json},
        )
        await self.db.flush()
        return {"id": schedule_id, "staff_count": len(staff_assignments)}

    async def get_timeline(self, store_id: str, schedule_date: date) -> list:
        """获取当日统一时间轴"""
        schedule = await self.get_schedule(store_id, schedule_date)
        if not schedule:
            return []
        return schedule.get("timeline_json", [])

    async def get_resource_summary(self, store_id: str, schedule_date: date) -> dict:
        """资源汇总"""
        schedule = await self.get_schedule(store_id, schedule_date)
        if not schedule:
            return {"date": schedule_date.isoformat(), "banquets": 0}
        return {
            "date": schedule_date.isoformat(),
            "banquets": schedule.get("banquet_count", 0),
            "guests": schedule.get("total_guests", 0),
            "tables": schedule.get("total_tables", 0),
            "venues": schedule.get("venue_allocation_json", {}),
            "staff": schedule.get("staff_allocation_json", {}),
            "kitchen": schedule.get("kitchen_load_json", {}),
        }

    async def list_schedules(self, store_id: str, date_from: date, date_to: date) -> list:
        """列出调度"""
        rows = await self.db.execute(
            text("""
                SELECT id, schedule_date, banquet_count, total_guests, total_tables, status
                FROM banquet_day_schedules
                WHERE store_id = :sid AND tenant_id = :tid AND is_deleted = FALSE
                  AND schedule_date BETWEEN :df AND :dt
                ORDER BY schedule_date
            """),
            {"sid": store_id, "tid": self.tenant_id, "df": date_from, "dt": date_to},
        )
        return [dict(r) for r in rows.mappings().all()]
