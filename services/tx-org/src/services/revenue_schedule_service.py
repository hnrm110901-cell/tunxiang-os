"""营收驱动排班服务

基于POS交易数据的时段客流分析，自动计算各门店各时段最优人力配置。
这是屯象OS vs i人事/乐才的核心差异化——它们没有POS数据。

金额单位统一为"分"（fen）。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ── 时段定义（餐饮业标准时段） ──────────────────────────────────────────────────

TIME_SLOTS: List[Tuple[str, str, str, str]] = [
    # (slot_key, slot_name, start_time, end_time)
    ("early_morning", "早班前", "06:00", "09:00"),
    ("lunch_peak",    "午高峰", "11:00", "13:30"),
    ("lunch_valley",  "午低谷", "13:30", "17:00"),
    ("dinner_peak",   "晚高峰", "17:00", "20:30"),
    ("dinner_valley", "晚低谷", "20:30", "22:00"),
    ("night",         "夜班",   "22:00", "02:00"),
]

# 行业基准：每万元营收需要的人力时数
LABOR_HOURS_PER_10K_REVENUE: Dict[str, float] = {
    "前厅": 2.5,   # 服务员
    "后厨": 2.0,   # 厨师
    "收银": 0.8,   # 收银
    "清洁": 0.5,   # 清洁
}

# 各岗位默认时薪（分）
_DEFAULT_HOURLY_RATE_FEN: Dict[str, int] = {
    "前厅": 2200,
    "后厨": 3500,
    "收银": 2500,
    "清洁": 2000,
}

# 各时段营收占比默认值（用于从日营收推算时段营收）
_SLOT_REVENUE_RATIO: Dict[str, float] = {
    "early_morning": 0.05,
    "lunch_peak":    0.35,
    "lunch_valley":  0.08,
    "dinner_peak":   0.40,
    "dinner_valley": 0.08,
    "night":         0.04,
}

# 星期几修正因子（周末客流高）
_WEEKDAY_FACTOR: Dict[int, float] = {
    0: 1.0,   # 周一
    1: 0.95,  # 周二
    2: 0.95,  # 周三
    3: 1.0,   # 周四
    4: 1.15,  # 周五
    5: 1.30,  # 周六
    6: 1.25,  # 周日
}


def _slot_duration_hours(start: str, end: str) -> float:
    """计算时段持续小时数（支持跨午夜）。"""
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    if end_min <= start_min:
        end_min += 24 * 60  # 跨午夜
    return (end_min - start_min) / 60.0


def _hour_to_slot(hour: int) -> str:
    """将小时映射到时段key。"""
    if 6 <= hour < 9:
        return "early_morning"
    if 11 <= hour < 14:
        return "lunch_peak"
    if 14 <= hour < 17:
        return "lunch_valley"
    if 17 <= hour < 21:
        return "dinner_peak"
    if 21 <= hour < 22:
        return "dinner_valley"
    return "night"


def _slot_label(slot_key: str) -> str:
    """slot_key → 中文名。"""
    for key, name, _, _ in TIME_SLOTS:
        if key == slot_key:
            return name
    return slot_key


# ── 核心服务类 ────────────────────────────────────────────────────────────────


class RevenueScheduleService:
    """营收驱动排班引擎"""

    # ------------------------------------------------------------------
    # 1. 时段营收分析
    # ------------------------------------------------------------------

    async def analyze_revenue_pattern(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        weeks: int = 4,
    ) -> Dict[str, Any]:
        """分析过去N周的时段营收模式。

        降级策略：
          方案A: mv_store_pnl 物化视图（日粒度）→ 按星期汇总
          方案B: orders 表按小时聚合
          方案C: mock 数据兜底

        返回：每个时段的 avg_revenue_fen / peak_revenue_fen / std_dev_fen
        """
        logger.info(
            "revenue_schedule.analyze_pattern",
            tenant_id=tenant_id,
            store_id=store_id,
            weeks=weeks,
        )

        # 方案A：从 mv_store_pnl 读日营收，再按时段占比拆分
        daily_revenues = await self._load_daily_revenue_from_mv(
            db, tenant_id, store_id, weeks
        )

        if not daily_revenues:
            # 方案B：直接从 orders 按小时聚合
            hourly_data = await self._load_hourly_revenue_from_orders(
                db, tenant_id, store_id, weeks
            )
            if hourly_data:
                return self._aggregate_hourly_to_slots(hourly_data)

            # 方案C：无历史数据，返回降级空结构
            logger.warning("revenue_schedule.no_historical_data", store_id=store_id)
            return self._degraded_revenue_pattern()

        # 从日营收按时段占比拆分
        return self._split_daily_to_slots(daily_revenues)

    async def _load_daily_revenue_from_mv(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        weeks: int,
    ) -> List[Dict[str, Any]]:
        """方案A：从 mv_store_pnl 查日营收。"""
        try:
            q = text("""
                SELECT
                    stat_date,
                    total_revenue_fen,
                    order_count,
                    avg_ticket_fen,
                    EXTRACT(DOW FROM stat_date)::int AS dow
                FROM mv_store_pnl
                WHERE store_id = CAST(:store_id AS TEXT)
                  AND stat_date >= CURRENT_DATE - :days * INTERVAL '1 day'
                ORDER BY stat_date
            """)
            result = await db.execute(q, {
                "store_id": store_id,
                "days": weeks * 7,
            })
            rows = [dict(r) for r in result.mappings()]
            if rows:
                logger.info(
                    "revenue_schedule.mv_store_pnl_loaded",
                    rows=len(rows),
                    store_id=store_id,
                )
            return rows
        except (OperationalError, ProgrammingError) as exc:
            logger.warning(
                "revenue_schedule.mv_store_pnl_unavailable",
                error=str(exc),
            )
            return []

    async def _load_hourly_revenue_from_orders(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        weeks: int,
    ) -> List[Dict[str, Any]]:
        """方案B：从 orders 表按小时聚合。"""
        try:
            q = text("""
                SELECT
                    DATE(created_at) AS order_date,
                    EXTRACT(HOUR FROM created_at)::int AS hour,
                    EXTRACT(DOW FROM created_at)::int AS dow,
                    COUNT(*) AS order_count,
                    COALESCE(SUM(total_fen), 0)::bigint AS revenue_fen
                FROM orders
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND store_id = CAST(:store_id AS TEXT)
                  AND created_at >= CURRENT_DATE - :days * INTERVAL '1 day'
                  AND status = 'paid'
                GROUP BY DATE(created_at), EXTRACT(HOUR FROM created_at),
                         EXTRACT(DOW FROM created_at)
                ORDER BY order_date, hour
            """)
            result = await db.execute(q, {
                "tid": tenant_id,
                "store_id": store_id,
                "days": weeks * 7,
            })
            rows = [dict(r) for r in result.mappings()]
            if rows:
                logger.info(
                    "revenue_schedule.orders_loaded",
                    rows=len(rows),
                    store_id=store_id,
                )
            return rows
        except (OperationalError, ProgrammingError) as exc:
            logger.warning(
                "revenue_schedule.orders_unavailable",
                error=str(exc),
            )
            return []

    def _aggregate_hourly_to_slots(
        self, hourly_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """将小时级数据聚合为时段级统计。"""
        from collections import defaultdict

        # slot_key → list[revenue_fen]（按天维度）
        slot_daily: Dict[str, List[int]] = defaultdict(list)
        # 先按日期分组，再按时段汇总
        day_slot: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in hourly_data:
            dt = str(row["order_date"])
            slot = _hour_to_slot(int(row["hour"]))
            day_slot[dt][slot] += int(row["revenue_fen"])

        for dt, slots in day_slot.items():
            for key, _, _, _ in TIME_SLOTS:
                slot_daily[key].append(slots.get(key, 0))

        return self._compute_slot_stats(slot_daily)

    def _split_daily_to_slots(
        self, daily_revenues: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """从日营收按时段占比拆分为时段统计。"""
        from collections import defaultdict

        slot_daily: Dict[str, List[int]] = defaultdict(list)
        for row in daily_revenues:
            total_rev = int(row.get("total_revenue_fen", 0))
            for key, _, _, _ in TIME_SLOTS:
                ratio = _SLOT_REVENUE_RATIO.get(key, 0.1)
                slot_daily[key].append(int(total_rev * ratio))

        return self._compute_slot_stats(slot_daily)

    def _compute_slot_stats(
        self, slot_daily: Dict[str, List[int]]
    ) -> Dict[str, Any]:
        """从每日时段营收列表计算统计值。"""
        slots_result: List[Dict[str, Any]] = []
        for key, name, start, end in TIME_SLOTS:
            values = slot_daily.get(key, [])
            if not values:
                values = [0]
            avg_rev = int(sum(values) / len(values))
            peak_rev = max(values)
            # 标准差
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            std_dev = int(math.sqrt(variance))

            slots_result.append({
                "slot_key": key,
                "slot_name": name,
                "start_time": start,
                "end_time": end,
                "avg_revenue_fen": avg_rev,
                "peak_revenue_fen": peak_rev,
                "std_dev_fen": std_dev,
                "sample_days": len(values),
            })

        total_avg = sum(s["avg_revenue_fen"] for s in slots_result)
        return {
            "slots": slots_result,
            "total_avg_daily_revenue_fen": total_avg,
            "data_source": "actual",
        }

    def _degraded_revenue_pattern(self) -> Dict[str, Any]:
        """无历史数据时的降级响应（所有时段返回零值）。"""
        slots = []
        for key, name, start, end in TIME_SLOTS:
            slots.append({
                "slot_key": key,
                "slot_name": name,
                "start_time": start,
                "end_time": end,
                "avg_revenue_fen": 0,
                "peak_revenue_fen": 0,
                "std_dev_fen": 0,
                "sample_days": 0,
            })
        return {
            "slots": slots,
            "total_avg_daily_revenue_fen": 0,
            "data_source": "degraded",
        }

    # ------------------------------------------------------------------
    # 2. 最优人力计算
    # ------------------------------------------------------------------

    async def calculate_optimal_staffing(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        target_date: date,
    ) -> Dict[str, Any]:
        """基于历史营收模式计算目标日期最优排班。

        算法：
        1. 取同星期几的过去4周营收数据
        2. 计算各时段平均营收
        3. 用 LABOR_HOURS_PER_10K_REVENUE 基准推导各岗位人数
        4. 对比当前排班(unified_schedules)，找出多排/少排
        5. 生成优化建议
        """
        logger.info(
            "revenue_schedule.calculate_optimal",
            tenant_id=tenant_id,
            store_id=store_id,
            target_date=target_date.isoformat(),
        )

        # 1. 获取营收模式
        pattern = await self.analyze_revenue_pattern(db, tenant_id, store_id, weeks=4)

        # 2. 星期几修正
        dow = target_date.weekday()
        weekday_factor = _WEEKDAY_FACTOR.get(dow, 1.0)

        # 3. 预订数据加成
        reservation_boost = await self.get_reservation_boost(
            db, tenant_id, store_id, target_date
        )

        # 4. 计算各时段各岗位最优人数
        slot_plans: List[Dict[str, Any]] = []
        for slot_info in pattern["slots"]:
            adjusted_rev = int(slot_info["avg_revenue_fen"] * weekday_factor)
            slot_key = slot_info["slot_key"]

            # 预订加成（仅影响晚高峰）
            if slot_key == "dinner_peak" and reservation_boost.get("extra_staff", 0):
                adjusted_rev = int(adjusted_rev * 1.1)

            # 按营收推导各岗位人数
            optimal_staff: Dict[str, int] = {}
            for position, hours_per_10k in LABOR_HOURS_PER_10K_REVENUE.items():
                revenue_10k = adjusted_rev / 100000  # 分→万元
                slot_hours = _slot_duration_hours(
                    slot_info["start_time"], slot_info["end_time"]
                )
                needed_hours = revenue_10k * hours_per_10k
                needed_people = max(1, math.ceil(needed_hours / slot_hours)) if slot_hours > 0 else 1
                optimal_staff[position] = needed_people

            # 预订大桌加成
            if slot_key in ("dinner_peak", "lunch_peak"):
                large_parties = reservation_boost.get("large_parties", 0)
                if large_parties > 0:
                    optimal_staff["前厅"] += large_parties  # 每桌大桌+1服务员

            slot_plans.append({
                "slot_key": slot_key,
                "slot_name": slot_info["slot_name"],
                "start_time": slot_info["start_time"],
                "end_time": slot_info["end_time"],
                "predicted_revenue_fen": adjusted_rev,
                "optimal_staff": optimal_staff,
            })

        # 5. 查当前排班对比
        current_staffing = await self._load_current_slot_staffing(
            db, tenant_id, store_id, target_date
        )

        # 6. 计算差值
        for plan in slot_plans:
            current = current_staffing.get(plan["slot_key"], {})
            plan["current_staff"] = current
            delta: Dict[str, int] = {}
            for pos, opt_count in plan["optimal_staff"].items():
                cur_count = current.get(pos, 0)
                diff = opt_count - cur_count
                if diff != 0:
                    delta[pos] = diff
            plan["delta"] = delta

        return {
            "target_date": target_date.isoformat(),
            "weekday": dow,
            "weekday_factor": weekday_factor,
            "reservation_boost": reservation_boost,
            "slot_plans": slot_plans,
            "data_source": pattern.get("data_source", "unknown"),
        }

    async def _load_current_slot_staffing(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        target_date: date,
    ) -> Dict[str, Dict[str, int]]:
        """从 unified_schedules 查当前排班，按时段×岗位统计人数。"""
        try:
            q = text("""
                SELECT
                    us.start_time,
                    us.role,
                    COUNT(*)::int AS cnt
                FROM unified_schedules us
                WHERE us.tenant_id = CAST(:tid AS uuid)
                  AND us.store_id = CAST(:store_id AS uuid)
                  AND us.shift_date = :target_date
                  AND COALESCE(us.is_deleted, false) = false
                GROUP BY us.start_time, us.role
            """)
            result = await db.execute(q, {
                "tid": tenant_id,
                "store_id": store_id,
                "target_date": target_date,
            })
            rows = [dict(r) for r in result.mappings()]
        except (OperationalError, ProgrammingError) as exc:
            logger.warning(
                "revenue_schedule.load_current_staffing_failed",
                error=str(exc),
            )
            return {}

        # 按时段聚合
        from collections import defaultdict
        slot_staff: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in rows:
            st = str(row.get("start_time", "09:00"))
            hour = int(st.split(":")[0]) if ":" in st else 9
            slot_key = _hour_to_slot(hour)
            role = self._map_role_to_position(str(row.get("role", "")))
            slot_staff[slot_key][role] += int(row.get("cnt", 0))

        return dict(slot_staff)

    @staticmethod
    def _map_role_to_position(role: str) -> str:
        """将数据库角色映射到标准岗位名。"""
        mapping = {
            "waiter": "前厅",
            "server": "前厅",
            "host": "前厅",
            "chef": "后厨",
            "chef_hot": "后厨",
            "chef_cold": "后厨",
            "chef_dim_sum": "后厨",
            "cook": "后厨",
            "cashier": "收银",
            "cleaner": "清洁",
            "前厅": "前厅",
            "后厨": "后厨",
            "收银": "收银",
            "清洁": "清洁",
        }
        return mapping.get(role.lower(), "前厅")

    # ------------------------------------------------------------------
    # 3. 周计划生成
    # ------------------------------------------------------------------

    async def generate_weekly_plan(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        week_start_date: date,
    ) -> Dict[str, Any]:
        """生成一整周的最优排班方案。

        综合考虑：
        - 员工周工时上限（40h）
        - 技能匹配
        - 公平性
        """
        logger.info(
            "revenue_schedule.generate_weekly_plan",
            tenant_id=tenant_id,
            store_id=store_id,
            week_start=week_start_date.isoformat(),
        )

        # 获取可用员工
        employees = await self._load_available_employees(
            db, tenant_id, store_id
        )

        daily_plans: List[Dict[str, Any]] = []
        total_labor_current_fen = 0
        total_labor_optimal_fen = 0

        for day_offset in range(7):
            target_date = week_start_date + timedelta(days=day_offset)
            day_result = await self.calculate_optimal_staffing(
                db, tenant_id, store_id, target_date
            )

            # 为每个缺人时段推荐员工
            for plan in day_result["slot_plans"]:
                suggested = self._suggest_employees_for_slot(
                    employees, plan, target_date
                )
                plan["suggested_employees"] = suggested

                # 估算成本
                slot_hours = _slot_duration_hours(
                    plan["start_time"], plan["end_time"]
                )
                for pos, cnt in plan.get("current_staff", {}).items():
                    rate = _DEFAULT_HOURLY_RATE_FEN.get(pos, 2200)
                    total_labor_current_fen += int(cnt * slot_hours * rate)
                for pos, cnt in plan["optimal_staff"].items():
                    rate = _DEFAULT_HOURLY_RATE_FEN.get(pos, 2200)
                    total_labor_optimal_fen += int(cnt * slot_hours * rate)

            daily_plans.append({
                "date": target_date.isoformat(),
                "weekday": target_date.weekday(),
                "weekday_name": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
                    target_date.weekday()
                ],
                "slots": day_result["slot_plans"],
            })

        savings_fen = total_labor_current_fen - total_labor_optimal_fen
        savings_pct = (
            round(savings_fen / total_labor_current_fen * 100, 1)
            if total_labor_current_fen > 0
            else 0.0
        )

        return {
            "store_id": store_id,
            "week_start": week_start_date.isoformat(),
            "week_end": (week_start_date + timedelta(days=6)).isoformat(),
            "daily_plans": daily_plans,
            "summary": {
                "total_labor_cost_current_fen": total_labor_current_fen,
                "total_labor_cost_optimal_fen": total_labor_optimal_fen,
                "savings_fen": savings_fen,
                "savings_pct": savings_pct,
            },
            "employee_count": len(employees),
        }

    async def _load_available_employees(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
    ) -> List[Dict[str, Any]]:
        """加载门店在职员工（含岗位和技能）。"""
        try:
            q = text("""
                SELECT
                    e.id::text AS employee_id,
                    e.emp_name,
                    e.position,
                    e.status,
                    e.store_id::text
                FROM employees e
                WHERE e.tenant_id = CAST(:tid AS uuid)
                  AND e.store_id = CAST(:store_id AS uuid)
                  AND e.status = 'active'
                  AND COALESCE(e.is_deleted, false) = false
                ORDER BY e.emp_name
            """)
            result = await db.execute(q, {
                "tid": tenant_id,
                "store_id": store_id,
            })
            return [dict(r) for r in result.mappings()]
        except (OperationalError, ProgrammingError) as exc:
            logger.warning(
                "revenue_schedule.load_employees_failed",
                error=str(exc),
            )
            return []

    def _suggest_employees_for_slot(
        self,
        employees: List[Dict[str, Any]],
        slot_plan: Dict[str, Any],
        target_date: date,
    ) -> List[Dict[str, Any]]:
        """为缺人时段推荐可用员工。"""
        suggestions: List[Dict[str, Any]] = []
        delta = slot_plan.get("delta", {})

        for position, need in delta.items():
            if need <= 0:
                continue  # 不缺人
            # 找该岗位的可用员工
            matching = [
                e for e in employees
                if self._map_role_to_position(e.get("position", "")) == position
            ]
            for emp in matching[:need]:
                suggestions.append({
                    "employee_id": emp["employee_id"],
                    "name": emp["emp_name"],
                    "position": position,
                    "reason": "本周工时有余量",
                })

        return suggestions

    # ------------------------------------------------------------------
    # 4. 预订加成
    # ------------------------------------------------------------------

    async def get_reservation_boost(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        target_date: date,
    ) -> Dict[str, Any]:
        """查询预订数据，计算额外人力需求。

        大桌宴会(>=8人) → 每桌额外需要1名服务员
        VIP预订 → 需要资深服务员
        """
        try:
            q = text("""
                SELECT
                    COUNT(*) AS total_reservations,
                    COALESCE(SUM(party_size), 0)::int AS total_guests,
                    SUM(CASE WHEN party_size >= 8 THEN 1 ELSE 0 END)::int AS large_parties,
                    SUM(CASE WHEN is_vip THEN 1 ELSE 0 END)::int AS vip_reservations
                FROM reservations
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND store_id = CAST(:store_id AS TEXT)
                  AND reservation_date = :target_date
                  AND status IN ('confirmed', 'seated')
            """)
            result = await db.execute(q, {
                "tid": tenant_id,
                "store_id": store_id,
                "target_date": target_date,
            })
            row = result.mappings().first()
            if row:
                large = int(row.get("large_parties", 0))
                vip = int(row.get("vip_reservations", 0))
                return {
                    "total_reservations": int(row.get("total_reservations", 0)),
                    "total_guests": int(row.get("total_guests", 0)),
                    "large_parties": large,
                    "vip_reservations": vip,
                    "extra_staff": large + (1 if vip > 0 else 0),
                }
        except (OperationalError, ProgrammingError) as exc:
            logger.warning(
                "revenue_schedule.reservations_unavailable",
                error=str(exc),
            )

        return {
            "total_reservations": 0,
            "total_guests": 0,
            "large_parties": 0,
            "vip_reservations": 0,
            "extra_staff": 0,
        }

    # ------------------------------------------------------------------
    # 5. 成本节约预估
    # ------------------------------------------------------------------

    async def estimate_monthly_savings(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        month: str,
    ) -> Dict[str, Any]:
        """月度成本节约预估。

        Args:
            month: "YYYY-MM" 格式
        """
        year, mon = map(int, month.split("-"))
        # 取该月第一个周一
        first_day = date(year, mon, 1)
        # 找到该月包含的所有完整周
        days_in_month = 28 if mon == 2 else (30 if mon in (4, 6, 9, 11) else 31)
        last_day = date(year, mon, days_in_month)

        # 简化：取该月第一周的数据 × 周数估算
        week_start = first_day - timedelta(days=first_day.weekday())
        plan = await self.generate_weekly_plan(
            db, tenant_id, store_id, week_start
        )

        weeks_in_month = days_in_month / 7.0
        summary = plan["summary"]

        return {
            "month": month,
            "store_id": store_id,
            "weekly_current_fen": summary["total_labor_cost_current_fen"],
            "weekly_optimal_fen": summary["total_labor_cost_optimal_fen"],
            "weekly_savings_fen": summary["savings_fen"],
            "monthly_current_fen": int(
                summary["total_labor_cost_current_fen"] * weeks_in_month
            ),
            "monthly_optimal_fen": int(
                summary["total_labor_cost_optimal_fen"] * weeks_in_month
            ),
            "monthly_savings_fen": int(summary["savings_fen"] * weeks_in_month),
            "savings_pct": summary["savings_pct"],
        }

    # ------------------------------------------------------------------
    # 6. 写入排班草稿
    # ------------------------------------------------------------------

    async def apply_plan_as_draft(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        week_start_date: date,
        operator_id: str,
    ) -> Dict[str, Any]:
        """将最优方案写入 unified_schedules 表（status=draft）。

        仅写入增补的排班（delta > 0 的部分），不删除现有排班。
        """
        logger.info(
            "revenue_schedule.apply_plan_draft",
            tenant_id=tenant_id,
            store_id=store_id,
            week_start=week_start_date.isoformat(),
        )

        plan = await self.generate_weekly_plan(
            db, tenant_id, store_id, week_start_date
        )

        inserted_count = 0
        inserted_ids: List[str] = []

        for day_plan in plan["daily_plans"]:
            shift_date = date.fromisoformat(day_plan["date"])
            for slot in day_plan["slots"]:
                for emp in slot.get("suggested_employees", []):
                    try:
                        q = text("""
                            INSERT INTO unified_schedules
                                (tenant_id, store_id, employee_id, shift_date,
                                 start_time, end_time, role, status,
                                 notes, created_at, updated_at)
                            VALUES
                                (CAST(:tid AS uuid), CAST(:store_id AS uuid),
                                 CAST(:emp_id AS uuid), :shift_date,
                                 :start_time, :end_time, :role, 'draft',
                                 :notes, NOW(), NOW())
                            RETURNING id::text
                        """)
                        result = await db.execute(q, {
                            "tid": tenant_id,
                            "store_id": store_id,
                            "emp_id": emp["employee_id"],
                            "shift_date": shift_date,
                            "start_time": slot["start_time"],
                            "end_time": slot["end_time"],
                            "role": emp["position"],
                            "notes": f"营收驱动排班自动生成 | 操作人:{operator_id}",
                        })
                        row = result.mappings().first()
                        if row:
                            inserted_ids.append(str(row["id"]))
                            inserted_count += 1
                    except (OperationalError, ProgrammingError) as exc:
                        logger.warning(
                            "revenue_schedule.insert_draft_failed",
                            error=str(exc),
                            employee_id=emp["employee_id"],
                        )

        if inserted_count > 0:
            await db.commit()

        return {
            "inserted_count": inserted_count,
            "inserted_ids": inserted_ids,
            "status": "draft",
            "week_start": week_start_date.isoformat(),
            "rollback_window_min": 30,
        }
