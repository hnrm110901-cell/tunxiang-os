"""宴会厅房管理服务 — 场地CRUD/档期日历/冲突检测/自动释放

可视化档期管理: 按日期查看所有厅房状态 → 冲突检测 → 自动hold(24h) → 确认/释放。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


# ─── 常量 ───────────────────────────────────────────────────────────────────

VENUE_TYPES = ("grand_hall", "private_room", "outdoor", "multi_function")

BOOKING_STATUSES = ("held", "confirmed", "released")

TIME_SLOTS = ("lunch", "dinner", "full_day")


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _safe_json(val: object) -> str:
    if isinstance(val, str):
        return val
    return json.dumps(val, ensure_ascii=False, default=str)


def _parse_json(val: object) -> object:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        return json.loads(val)
    return val


# ─── Service ────────────────────────────────────────────────────────────────


class BanquetVenueService:
    """宴会厅房与档期管理"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id

    # ── 厅房 CRUD ─────────────────────────────────────────────────────────

    async def create_venue(
        self,
        store_id: str,
        venue_name: str,
        venue_type: str,
        floor: Optional[int] = None,
        max_tables: Optional[int] = None,
        max_guests: Optional[int] = None,
        base_fee_fen: int = 0,
        facilities_json: Optional[list[str]] = None,
        description: Optional[str] = None,
        photos_json: Optional[list[str]] = None,
    ) -> dict:
        """创建宴会厅房。

        Args:
            store_id: 门店ID
            venue_name: 厅房名称
            venue_type: 厅房类型 (grand_hall/private_room/outdoor/multi_function)
            floor: 楼层
            max_tables: 最大桌数
            max_guests: 最大容客数
            base_fee_fen: 场地费（分）
            facilities_json: 设施列表 ["LED屏", "音响", ...]
            description: 描述
            photos_json: 图片URL列表
        """
        if not venue_name or not venue_name.strip():
            raise ValueError("厅房名称不能为空")
        if venue_type not in VENUE_TYPES:
            raise ValueError(f"无效厅房类型: {venue_type}，可选: {VENUE_TYPES}")
        if base_fee_fen < 0:
            raise ValueError("场地费不能为负数")

        venue_id = str(uuid.uuid4())
        now = _now_utc()

        await self._db.execute(
            text("""
                INSERT INTO banquet_venues (
                    id, tenant_id, store_id, venue_name, venue_type,
                    floor, max_tables, max_guests, base_fee_fen,
                    facilities_json, description, photos_json,
                    is_active, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :store_id, :venue_name, :venue_type,
                    :floor, :max_tables, :max_guests, :base_fee_fen,
                    :facilities_json, :description, :photos_json,
                    TRUE, :now, :now
                )
            """),
            {
                "id": venue_id,
                "tenant_id": self._tenant_id,
                "store_id": store_id,
                "venue_name": venue_name.strip(),
                "venue_type": venue_type,
                "floor": floor,
                "max_tables": max_tables,
                "max_guests": max_guests,
                "base_fee_fen": base_fee_fen,
                "facilities_json": _safe_json(facilities_json) if facilities_json else None,
                "description": description,
                "photos_json": _safe_json(photos_json) if photos_json else None,
                "now": now,
            },
        )
        await self._db.flush()

        logger.info(
            "banquet_venue_created",
            tenant_id=self._tenant_id,
            venue_id=venue_id,
            store_id=store_id,
            venue_name=venue_name,
            venue_type=venue_type,
        )

        return {
            "id": venue_id,
            "store_id": store_id,
            "venue_name": venue_name.strip(),
            "venue_type": venue_type,
            "floor": floor,
            "max_tables": max_tables,
            "max_guests": max_guests,
            "base_fee_fen": base_fee_fen,
            "facilities_json": facilities_json,
            "description": description,
            "photos_json": photos_json,
            "is_active": True,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

    async def list_venues(
        self,
        store_id: Optional[str] = None,
        venue_type: Optional[str] = None,
        is_active: Optional[bool] = True,
    ) -> list:
        """查询厅房列表。"""
        conditions = ["tenant_id = :tenant_id"]
        params: dict = {"tenant_id": self._tenant_id}

        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id
        if venue_type:
            conditions.append("venue_type = :venue_type")
            params["venue_type"] = venue_type
        if is_active is not None:
            conditions.append("is_active = :is_active")
            params["is_active"] = is_active

        where = " AND ".join(conditions)

        result = await self._db.execute(
            text(f"""
                SELECT id, store_id, venue_name, venue_type, floor,
                       max_tables, max_guests, base_fee_fen,
                       facilities_json, description, is_active,
                       created_at, updated_at
                FROM banquet_venues
                WHERE {where}
                ORDER BY floor ASC NULLS LAST, venue_name ASC
            """),
            params,
        )
        rows = result.mappings().all()

        return [
            {
                "id": str(r["id"]),
                "store_id": str(r["store_id"]),
                "venue_name": r["venue_name"],
                "venue_type": r["venue_type"],
                "floor": r["floor"],
                "max_tables": r["max_tables"],
                "max_guests": r["max_guests"],
                "base_fee_fen": r["base_fee_fen"],
                "facilities_json": _parse_json(r["facilities_json"]),
                "description": r["description"],
                "is_active": r["is_active"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows
        ]

    async def get_venue(self, venue_id: str) -> dict:
        """获取单个厅房详情。"""
        result = await self._db.execute(
            text("""
                SELECT * FROM banquet_venues
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": venue_id, "tenant_id": self._tenant_id},
        )
        row = result.mappings().first()
        if not row:
            raise ValueError(f"厅房不存在: {venue_id}")

        return {
            "id": str(row["id"]),
            "store_id": str(row["store_id"]),
            "venue_name": row["venue_name"],
            "venue_type": row["venue_type"],
            "floor": row["floor"],
            "max_tables": row["max_tables"],
            "max_guests": row["max_guests"],
            "base_fee_fen": row["base_fee_fen"],
            "facilities_json": _parse_json(row["facilities_json"]),
            "description": row["description"],
            "photos_json": _parse_json(row["photos_json"]),
            "is_active": row["is_active"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    async def update_venue(self, venue_id: str, **kwargs: object) -> dict:
        """更新厅房信息。"""
        allowed = {
            "venue_name",
            "venue_type",
            "floor",
            "max_tables",
            "max_guests",
            "base_fee_fen",
            "facilities_json",
            "description",
            "photos_json",
            "is_active",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            raise ValueError("没有有效的更新字段")

        check = await self._db.execute(
            text("SELECT id FROM banquet_venues WHERE id = :id AND tenant_id = :tenant_id"),
            {"id": venue_id, "tenant_id": self._tenant_id},
        )
        if not check.first():
            raise ValueError(f"厅房不存在: {venue_id}")

        # JSON 字段序列化
        for jf in ("facilities_json", "photos_json"):
            if jf in updates and not isinstance(updates[jf], str):
                updates[jf] = _safe_json(updates[jf])

        set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
        updates["updated_at"] = _now_utc()
        set_clauses += ", updated_at = :updated_at"
        updates["id"] = venue_id
        updates["tenant_id"] = self._tenant_id

        await self._db.execute(
            text(f"""
                UPDATE banquet_venues
                SET {set_clauses}
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            updates,
        )
        await self._db.flush()

        logger.info(
            "banquet_venue_updated",
            tenant_id=self._tenant_id,
            venue_id=venue_id,
            fields=list(kwargs.keys()),
        )

        return await self.get_venue(venue_id)

    # ── 档期管理 ──────────────────────────────────────────────────────────

    async def check_availability(
        self,
        venue_id: str,
        booking_date: str,
        time_slot: str,
    ) -> dict:
        """检查厅房在指定日期时段的可用性。

        Args:
            venue_id: 厅房ID
            booking_date: 预订日期 (YYYY-MM-DD)
            time_slot: 时段 (lunch/dinner/full_day)

        Returns:
            {available: bool, conflicts: [...]}
        """
        if time_slot not in TIME_SLOTS:
            raise ValueError(f"无效时段: {time_slot}，可选: {TIME_SLOTS}")

        # full_day 与 lunch/dinner 都冲突; lunch 和 dinner 互不冲突
        slot_condition = self._build_slot_conflict_condition(time_slot)

        result = await self._db.execute(
            text(f"""
                SELECT id, lead_id, booking_date, time_slot, status, held_until
                FROM banquet_venue_bookings
                WHERE venue_id = :venue_id
                  AND tenant_id = :tenant_id
                  AND booking_date = :booking_date
                  AND status IN ('held', 'confirmed')
                  AND ({slot_condition})
            """),
            {
                "venue_id": venue_id,
                "tenant_id": self._tenant_id,
                "booking_date": booking_date,
            },
        )
        conflicts_rows = result.mappings().all()

        conflicts = [
            {
                "booking_id": str(r["id"]),
                "lead_id": str(r["lead_id"]) if r["lead_id"] else None,
                "time_slot": r["time_slot"],
                "status": r["status"],
                "held_until": r["held_until"].isoformat() if r["held_until"] else None,
            }
            for r in conflicts_rows
        ]

        return {"available": len(conflicts) == 0, "conflicts": conflicts}

    def _build_slot_conflict_condition(self, time_slot: str) -> str:
        """构建时段冲突 SQL 条件。"""
        if time_slot == "full_day":
            # full_day 与所有时段冲突
            return "time_slot IN ('lunch', 'dinner', 'full_day')"
        # lunch / dinner 与同时段或 full_day 冲突
        return f"time_slot IN ('{time_slot}', 'full_day')"

    async def hold_venue(
        self,
        venue_id: str,
        lead_id: str,
        booking_date: str,
        time_slot: str,
        hold_hours: int = 24,
    ) -> dict:
        """预留厅房档期（hold），默认24小时自动释放。"""
        if time_slot not in TIME_SLOTS:
            raise ValueError(f"无效时段: {time_slot}，可选: {TIME_SLOTS}")
        if hold_hours <= 0 or hold_hours > 168:
            raise ValueError("预留时长必须在 1~168 小时之间")

        # 检查厅房存在
        venue = await self.get_venue(venue_id)
        if not venue["is_active"]:
            raise ValueError("厅房已停用")

        # 冲突检测
        availability = await self.check_availability(venue_id, booking_date, time_slot)
        if not availability["available"]:
            raise ValueError(
                f"厅房 {venue['venue_name']} 在 {booking_date} {time_slot} "
                f"已有预订，冲突数: {len(availability['conflicts'])}"
            )

        booking_id = str(uuid.uuid4())
        now = _now_utc()
        held_until = now + timedelta(hours=hold_hours)

        await self._db.execute(
            text("""
                INSERT INTO banquet_venue_bookings (
                    id, tenant_id, venue_id, lead_id, booking_date,
                    time_slot, status, held_until, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :venue_id, :lead_id, :booking_date,
                    :time_slot, 'held', :held_until, :now, :now
                )
            """),
            {
                "id": booking_id,
                "tenant_id": self._tenant_id,
                "venue_id": venue_id,
                "lead_id": lead_id,
                "booking_date": booking_date,
                "time_slot": time_slot,
                "held_until": held_until,
                "now": now,
            },
        )
        await self._db.flush()

        logger.info(
            "banquet_venue_held",
            tenant_id=self._tenant_id,
            booking_id=booking_id,
            venue_id=venue_id,
            lead_id=lead_id,
            booking_date=booking_date,
            time_slot=time_slot,
            held_until=held_until.isoformat(),
        )

        return {
            "booking_id": booking_id,
            "venue_id": venue_id,
            "venue_name": venue["venue_name"],
            "lead_id": lead_id,
            "booking_date": booking_date,
            "time_slot": time_slot,
            "status": "held",
            "held_until": held_until.isoformat(),
            "created_at": now.isoformat(),
        }

    async def confirm_booking(self, booking_id: str) -> dict:
        """确认预订：held → confirmed。"""
        row = await self._db.execute(
            text("""
                SELECT id, venue_id, lead_id, booking_date, time_slot, status
                FROM banquet_venue_bookings
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": booking_id, "tenant_id": self._tenant_id},
        )
        booking = row.mappings().first()
        if not booking:
            raise ValueError(f"预订不存在: {booking_id}")
        if booking["status"] != "held":
            raise ValueError(f"仅 held 状态可确认，当前: {booking['status']}")

        now = _now_utc()
        await self._db.execute(
            text("""
                UPDATE banquet_venue_bookings
                SET status = 'confirmed', held_until = NULL, updated_at = :now
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": booking_id, "tenant_id": self._tenant_id, "now": now},
        )
        await self._db.flush()

        logger.info(
            "banquet_venue_booking_confirmed",
            tenant_id=self._tenant_id,
            booking_id=booking_id,
            venue_id=str(booking["venue_id"]),
        )

        return {
            "booking_id": booking_id,
            "venue_id": str(booking["venue_id"]),
            "lead_id": str(booking["lead_id"]) if booking["lead_id"] else None,
            "booking_date": str(booking["booking_date"]),
            "time_slot": booking["time_slot"],
            "status": "confirmed",
            "updated_at": now.isoformat(),
        }

    async def release_booking(
        self,
        booking_id: str,
        reason: Optional[str] = None,
    ) -> dict:
        """释放预订：held/confirmed → released。"""
        row = await self._db.execute(
            text("""
                SELECT id, venue_id, lead_id, booking_date, time_slot, status
                FROM banquet_venue_bookings
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": booking_id, "tenant_id": self._tenant_id},
        )
        booking = row.mappings().first()
        if not booking:
            raise ValueError(f"预订不存在: {booking_id}")
        if booking["status"] not in ("held", "confirmed"):
            raise ValueError(f"仅 held/confirmed 状态可释放，当前: {booking['status']}")

        now = _now_utc()
        await self._db.execute(
            text("""
                UPDATE banquet_venue_bookings
                SET status = 'released', release_reason = :reason, updated_at = :now
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {
                "id": booking_id,
                "tenant_id": self._tenant_id,
                "reason": reason,
                "now": now,
            },
        )
        await self._db.flush()

        logger.info(
            "banquet_venue_booking_released",
            tenant_id=self._tenant_id,
            booking_id=booking_id,
            venue_id=str(booking["venue_id"]),
            reason=reason,
        )

        return {
            "booking_id": booking_id,
            "venue_id": str(booking["venue_id"]),
            "lead_id": str(booking["lead_id"]) if booking["lead_id"] else None,
            "booking_date": str(booking["booking_date"]),
            "time_slot": booking["time_slot"],
            "status": "released",
            "release_reason": reason,
            "updated_at": now.isoformat(),
        }

    # ── 日历与利用率 ──────────────────────────────────────────────────────

    async def calendar_view(
        self,
        store_id: str,
        date_from: str,
        date_to: str,
    ) -> list:
        """按日期范围查看所有厅房档期日历。

        Returns:
            [{venue_id, venue_name, dates: [{date, lunch: status|null, dinner: status|null}]}]
        """
        # 获取门店所有活跃厅房
        venues = await self.list_venues(store_id=store_id, is_active=True)

        if not venues:
            return []

        venue_ids = [v["id"] for v in venues]
        venue_map = {v["id"]: v["venue_name"] for v in venues}

        # 查询日期范围内所有预订
        # 用 ANY 数组绑定避免 SQL 注入
        result = await self._db.execute(
            text("""
                SELECT venue_id, booking_date, time_slot, status
                FROM banquet_venue_bookings
                WHERE tenant_id = :tenant_id
                  AND venue_id = ANY(:venue_ids)
                  AND booking_date >= :date_from
                  AND booking_date <= :date_to
                  AND status IN ('held', 'confirmed')
                ORDER BY venue_id, booking_date, time_slot
            """),
            {
                "tenant_id": self._tenant_id,
                "venue_ids": venue_ids,
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        bookings = result.mappings().all()

        # 组装数据: venue_id -> date -> slot -> status
        booking_map: dict[str, dict[str, dict[str, str]]] = {}
        for b in bookings:
            vid = str(b["venue_id"])
            d = str(b["booking_date"])
            slot = b["time_slot"]
            status = b["status"]

            booking_map.setdefault(vid, {})
            booking_map[vid].setdefault(d, {})

            if slot == "full_day":
                booking_map[vid][d]["lunch"] = status
                booking_map[vid][d]["dinner"] = status
            else:
                booking_map[vid][d][slot] = status

        # 生成日期序列
        from datetime import date as date_type

        d_from = date_type.fromisoformat(date_from)
        d_to = date_type.fromisoformat(date_to)
        date_list = []
        current = d_from
        while current <= d_to:
            date_list.append(current.isoformat())
            current += timedelta(days=1)

        # 组装结果
        calendar = []
        for vid in venue_ids:
            dates = []
            for d in date_list:
                vm = booking_map.get(vid, {}).get(d, {})
                dates.append(
                    {
                        "date": d,
                        "lunch": vm.get("lunch"),
                        "dinner": vm.get("dinner"),
                    }
                )
            calendar.append(
                {
                    "venue_id": vid,
                    "venue_name": venue_map[vid],
                    "dates": dates,
                }
            )

        return calendar

    async def auto_release_expired_holds(self) -> int:
        """自动释放过期的 held 预订。返回释放数量。"""
        now = _now_utc()

        result = await self._db.execute(
            text("""
                UPDATE banquet_venue_bookings
                SET status = 'released',
                    release_reason = 'auto_expired',
                    updated_at = :now
                WHERE tenant_id = :tenant_id
                  AND status = 'held'
                  AND held_until < :now
                RETURNING id
            """),
            {"tenant_id": self._tenant_id, "now": now},
        )
        released = result.fetchall()
        count = len(released)

        if count > 0:
            await self._db.flush()

        logger.info(
            "banquet_venue_auto_released",
            tenant_id=self._tenant_id,
            count=count,
        )

        return count

    async def get_venue_utilization(
        self,
        store_id: str,
        date_from: str,
        date_to: str,
    ) -> dict:
        """计算各厅房在日期范围内的利用率。

        利用率 = 已确认档期数 / (日期天数 * 2个时段)
        """
        from datetime import date as date_type

        d_from = date_type.fromisoformat(date_from)
        d_to = date_type.fromisoformat(date_to)
        total_days = (d_to - d_from).days + 1
        total_slots = total_days * 2  # lunch + dinner

        if total_slots <= 0:
            raise ValueError("日期范围无效")

        venues = await self.list_venues(store_id=store_id, is_active=True)
        if not venues:
            return {"venues": [], "overall_utilization": 0.0}

        venue_ids = [v["id"] for v in venues]

        result = await self._db.execute(
            text("""
                SELECT venue_id, time_slot, COUNT(*) AS cnt
                FROM banquet_venue_bookings
                WHERE tenant_id = :tenant_id
                  AND venue_id = ANY(:venue_ids)
                  AND booking_date >= :date_from
                  AND booking_date <= :date_to
                  AND status = 'confirmed'
                GROUP BY venue_id, time_slot
            """),
            {
                "tenant_id": self._tenant_id,
                "venue_ids": venue_ids,
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        rows = result.mappings().all()

        # 统计每个厅房占用时段数
        usage: dict[str, int] = {}
        for r in rows:
            vid = str(r["venue_id"])
            slot = r["time_slot"]
            cnt = r["cnt"]
            # full_day 算2个时段
            multiplier = 2 if slot == "full_day" else 1
            usage[vid] = usage.get(vid, 0) + cnt * multiplier

        venue_utils = []
        total_used = 0
        for v in venues:
            used = usage.get(v["id"], 0)
            total_used += used
            rate = round(used / total_slots * 100, 2) if total_slots > 0 else 0.0
            venue_utils.append(
                {
                    "venue_id": v["id"],
                    "venue_name": v["venue_name"],
                    "confirmed_slots": used,
                    "total_slots": total_slots,
                    "utilization_rate": rate,
                }
            )

        overall = round(total_used / (total_slots * len(venues)) * 100, 2) if venues else 0.0

        return {
            "venues": venue_utils,
            "overall_utilization": overall,
            "date_from": date_from,
            "date_to": date_to,
            "total_days": total_days,
        }
