"""智能排班引擎 — V1最大单文件迁移(1,993行) → V3

三大核心：客流预测驱动 + 员工技能匹配 + 劳动法约束

核心流程：
1. predict_traffic → 基于历史/天气/节假日预测每小时客流
2. calculate_staffing_need → 客流 → 各岗位人力需求
3. generate_schedule → 贪心+约束满足自动排班（7天）
4. validate_schedule → 劳动法合规校验
5. match_skills → 可用员工技能匹配

金额单位统一为"分"(fen)。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  员工技能数据库 — 10名长沙餐厅员工
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EMPLOYEE_DATABASE: List[Dict[str, Any]] = [
    {
        "employee_id": "EMP001",
        "name": "张伟",
        "position": "店长",
        "skills": ["manager", "cashier", "waiter", "host"],
        "hourly_rate_fen": 4500,
        "base_salary_fen": 800_000,
        "max_hours_week": 44,
        "preferred_shifts": ["morning", "middle"],
        "is_minor": False,
        "hire_date": "2023-06-01",
        "phone": "138xxxx0001",
    },
    {
        "employee_id": "EMP002",
        "name": "李娜",
        "position": "副店长",
        "skills": ["manager", "cashier", "waiter", "host"],
        "hourly_rate_fen": 3800,
        "base_salary_fen": 700_000,
        "max_hours_week": 44,
        "preferred_shifts": ["middle", "evening"],
        "is_minor": False,
        "hire_date": "2023-09-15",
        "phone": "139xxxx0002",
    },
    {
        "employee_id": "EMP003",
        "name": "王强",
        "position": "主厨",
        "skills": ["chef_hot", "chef_cold", "chef_dim_sum"],
        "hourly_rate_fen": 5000,
        "base_salary_fen": 900_000,
        "max_hours_week": 44,
        "preferred_shifts": ["morning", "middle"],
        "is_minor": False,
        "hire_date": "2022-03-01",
        "phone": "137xxxx0003",
    },
    {
        "employee_id": "EMP004",
        "name": "刘洋",
        "position": "厨师",
        "skills": ["chef_hot", "chef_cold"],
        "hourly_rate_fen": 3500,
        "base_salary_fen": 650_000,
        "max_hours_week": 44,
        "preferred_shifts": ["morning"],
        "is_minor": False,
        "hire_date": "2024-01-10",
        "phone": "136xxxx0004",
    },
    {
        "employee_id": "EMP005",
        "name": "陈静",
        "position": "厨师",
        "skills": ["chef_cold", "chef_dim_sum"],
        "hourly_rate_fen": 3200,
        "base_salary_fen": 600_000,
        "max_hours_week": 44,
        "preferred_shifts": ["morning", "middle"],
        "is_minor": False,
        "hire_date": "2024-05-20",
        "phone": "135xxxx0005",
    },
    {
        "employee_id": "EMP006",
        "name": "赵敏",
        "position": "收银员",
        "skills": ["cashier", "host"],
        "hourly_rate_fen": 2500,
        "base_salary_fen": 450_000,
        "max_hours_week": 40,
        "preferred_shifts": ["morning", "middle"],
        "is_minor": False,
        "hire_date": "2025-02-01",
        "phone": "134xxxx0006",
    },
    {
        "employee_id": "EMP007",
        "name": "周磊",
        "position": "服务员",
        "skills": ["waiter", "host"],
        "hourly_rate_fen": 2200,
        "base_salary_fen": 400_000,
        "max_hours_week": 40,
        "preferred_shifts": ["middle", "evening"],
        "is_minor": False,
        "hire_date": "2025-06-01",
        "phone": "133xxxx0007",
    },
    {
        "employee_id": "EMP008",
        "name": "孙丽",
        "position": "服务员",
        "skills": ["waiter", "cashier"],
        "hourly_rate_fen": 2200,
        "base_salary_fen": 400_000,
        "max_hours_week": 40,
        "preferred_shifts": ["morning", "evening"],
        "is_minor": False,
        "hire_date": "2025-08-15",
        "phone": "132xxxx0008",
    },
    {
        "employee_id": "EMP009",
        "name": "吴浩",
        "position": "服务员",
        "skills": ["waiter"],
        "hourly_rate_fen": 2000,
        "base_salary_fen": 380_000,
        "max_hours_week": 40,
        "preferred_shifts": ["evening"],
        "is_minor": True,  # 未成年暑期工
        "hire_date": "2026-01-10",
        "phone": "131xxxx0009",
    },
    {
        "employee_id": "EMP010",
        "name": "黄芳",
        "position": "迎宾",
        "skills": ["host", "waiter", "cashier"],
        "hourly_rate_fen": 2300,
        "base_salary_fen": 420_000,
        "max_hours_week": 40,
        "preferred_shifts": ["middle"],
        "is_minor": False,
        "hire_date": "2025-10-01",
        "phone": "130xxxx0010",
    },
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  班次定义
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SHIFT_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "morning": {
        "label": "早班",
        "start_hour": 8,
        "end_hour": 15,
        "duration_hours": 7,
        "covers_peak": ["lunch"],
    },
    "middle": {
        "label": "中班",
        "start_hour": 11,
        "end_hour": 19,
        "duration_hours": 8,
        "covers_peak": ["lunch", "dinner_early"],
    },
    "evening": {
        "label": "晚班",
        "start_hour": 15,
        "end_hour": 22,
        "duration_hours": 7,
        "covers_peak": ["dinner"],
    },
    "full": {
        "label": "全天班",
        "start_hour": 9,
        "end_hour": 21,
        "duration_hours": 10,  # 含1h午休+1h晚休
        "covers_peak": ["lunch", "dinner"],
    },
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  劳动法约束常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MAX_HOURS_WEEK_STANDARD = 40  # 标准工时制
MAX_HOURS_WEEK_COMPREHENSIVE = 44  # 综合工时制
MIN_REST_BETWEEN_SHIFTS_HOURS = 11  # 班次间最少休息
MAX_CONSECUTIVE_DAYS = 6  # 最多连续工作天数
MAX_OVERTIME_MONTH_HOURS = 36  # 月加班上限
MAX_HOURS_DAY_MINOR = 8  # 未成年日工时上限
MINOR_NIGHT_SHIFT_CUTOFF = 22  # 未成年不得夜班（22:00后）

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  客流系数（基于长沙餐饮经验）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 星期系数（周一=0 ~ 周日=6）
DAY_OF_WEEK_FACTOR: Dict[int, float] = {
    0: 0.85,  # 周一
    1: 0.90,  # 周二
    2: 0.90,  # 周三
    3: 0.95,  # 周四
    4: 1.10,  # 周五
    5: 1.30,  # 周六
    6: 1.25,  # 周日
}

# 小时分布（每小时占全天客流比例）— 典型湘菜馆
HOURLY_DISTRIBUTION: Dict[int, float] = {
    8: 0.005,
    9: 0.01,
    10: 0.03,
    11: 0.10,
    12: 0.18,
    13: 0.12,
    14: 0.05,
    15: 0.02,
    16: 0.03,
    17: 0.08,
    18: 0.15,
    19: 0.10,
    20: 0.06,
    21: 0.02,
    22: 0.005,
}

# 天气系数
WEATHER_FACTOR: Dict[str, float] = {
    "sunny": 1.0,
    "cloudy": 0.98,
    "rainy": 0.80,
    "heavy_rain": 0.60,
    "snow": 0.55,
    "hot": 0.90,  # 长沙酷暑
}

# 节假日系数
HOLIDAY_FACTOR: Dict[str, float] = {
    "normal": 1.0,
    "holiday": 1.50,  # 法定节假日
    "holiday_eve": 1.20,  # 节前一天
    "spring_festival": 0.40,  # 春节（长沙人回乡多，市区冷清）
    "national_day": 1.60,  # 国庆（旅游旺季）
    "valentines": 1.35,  # 情人节等
}

# 岗位服务标准
STAFFING_STANDARD: Dict[str, Any] = {
    "waiter": {"tables_per_person": 4, "label": "服务员"},
    "chef_hot": {"covers_per_hour": 25, "label": "炒菜厨师"},
    "chef_cold": {"covers_per_hour": 40, "label": "冷菜厨师"},
    "chef_dim_sum": {"covers_per_hour": 30, "label": "点心厨师"},
    "cashier": {"min_per_shift": 1, "label": "收银员"},
    "host": {"min_per_shift": 1, "label": "迎宾"},
    "manager": {"min_per_shift": 1, "label": "值班经理"},
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SmartScheduleService
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class SmartScheduleService:
    """智能排班引擎 — V1最大单文件迁移(1,993行)

    三大核心：客流预测驱动 + 员工技能匹配 + 劳动法约束
    """

    def __init__(
        self,
        employees: Optional[List[Dict[str, Any]]] = None,
        store_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.employees = employees or EMPLOYEE_DATABASE
        self.store_config = store_config or {
            "store_id": "STORE_CS_001",
            "store_name": "屯象·尝在一起(五一广场店)",
            "total_tables": 30,
            "open_hour": 10,
            "close_hour": 22,
            "base_daily_traffic": 280,  # 工作日日均客流
            "city": "changsha",
        }
        self._schedules: Dict[str, Dict] = {}  # schedule_id -> schedule
        self._schedule_counter = 0

    # ──────────────────────────────────────────────────────
    #  1. Traffic Forecast (客流预测)
    # ──────────────────────────────────────────────────────

    def predict_traffic(
        self,
        store_id: str,
        target_date: date,
        granularity: str = "hour",
        weather: str = "sunny",
        holiday_type: str = "normal",
        nearby_events: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """预测指定日期每小时客流量

        Factors: day_of_week, weather, holiday, historical, nearby_events
        Returns: hourly customer count prediction with peak detection

        Args:
            store_id: 门店ID
            target_date: 预测日期
            granularity: 粒度 "hour" | "shift"
            weather: 天气 sunny/cloudy/rainy/heavy_rain/snow/hot
            holiday_type: 节日类型 normal/holiday/holiday_eve/spring_festival/national_day/valentines
            nearby_events: 附近活动 [{"name": "演唱会", "impact_factor": 1.15}]
        """
        base_traffic = self.store_config.get("base_daily_traffic", 280)

        # 组合系数
        dow_factor = DAY_OF_WEEK_FACTOR.get(target_date.weekday(), 1.0)
        w_factor = WEATHER_FACTOR.get(weather, 1.0)
        h_factor = HOLIDAY_FACTOR.get(holiday_type, 1.0)

        event_factor = 1.0
        if nearby_events:
            for evt in nearby_events:
                event_factor *= evt.get("impact_factor", 1.0)

        daily_total = int(base_traffic * dow_factor * w_factor * h_factor * event_factor)

        # 生成小时级预测
        hourly_predictions: List[Dict[str, Any]] = []
        predicted_sum = 0

        open_h = self.store_config.get("open_hour", 10)
        close_h = self.store_config.get("close_hour", 22)

        for hour in range(open_h, close_h + 1):
            dist_ratio = HOURLY_DISTRIBUTION.get(hour, 0.01)
            count = max(1, int(daily_total * dist_ratio))
            predicted_sum += count

            # 高峰检测
            is_peak = False
            peak_type = None
            if 11 <= hour <= 13:
                is_peak = True
                peak_type = "lunch"
            elif 17 <= hour <= 20:
                is_peak = True
                peak_type = "dinner"

            hourly_predictions.append(
                {
                    "hour": hour,
                    "predicted_customers": count,
                    "is_peak": is_peak,
                    "peak_type": peak_type,
                    "factors": {
                        "day_of_week": dow_factor,
                        "weather": w_factor,
                        "holiday": h_factor,
                        "event": event_factor,
                    },
                }
            )

        # 如果按班次粒度聚合
        if granularity == "shift":
            return self._aggregate_to_shifts(hourly_predictions, target_date)

        return hourly_predictions

    def _aggregate_to_shifts(
        self,
        hourly: List[Dict[str, Any]],
        target_date: date,
    ) -> List[Dict[str, Any]]:
        """将小时预测聚合为班次级"""
        shift_data: List[Dict[str, Any]] = []
        for shift_name, shift_def in SHIFT_DEFINITIONS.items():
            start = shift_def["start_hour"]
            end = shift_def["end_hour"]
            total_customers = sum(h["predicted_customers"] for h in hourly if start <= h["hour"] < end)
            peak_hours = [h["hour"] for h in hourly if start <= h["hour"] < end and h["is_peak"]]
            shift_data.append(
                {
                    "shift": shift_name,
                    "label": shift_def["label"],
                    "start_hour": start,
                    "end_hour": end,
                    "predicted_customers": total_customers,
                    "peak_hours": peak_hours,
                    "date": target_date.isoformat(),
                }
            )
        return shift_data

    # ──────────────────────────────────────────────────────
    #  2. Demand Calculation (人力需求)
    # ──────────────────────────────────────────────────────

    def calculate_staffing_need(
        self,
        store_id: str,
        target_date: date,
        weather: str = "sunny",
        holiday_type: str = "normal",
    ) -> Dict[str, Any]:
        """基于客流预测计算各小时各岗位人力需求

        Based on traffic forecast + service standard (1 waiter per 4 tables)
        Returns: {hour: {waiter, chef, cashier, host}, total_shifts}
        Consider: kitchen prep (before open), cleanup (after close)
        """
        hourly_traffic = self.predict_traffic(store_id, target_date, "hour", weather, holiday_type)
        total_tables = self.store_config.get("total_tables", 30)
        open_h = self.store_config.get("open_hour", 10)
        close_h = self.store_config.get("close_hour", 22)

        hourly_needs: Dict[int, Dict[str, int]] = {}
        total_person_hours: Dict[str, float] = {
            "waiter": 0,
            "chef_hot": 0,
            "chef_cold": 0,
            "chef_dim_sum": 0,
            "cashier": 0,
            "host": 0,
            "manager": 0,
        }

        # Kitchen prep: 2 hours before open
        for prep_hour in range(max(8, open_h - 2), open_h):
            hourly_needs[prep_hour] = {
                "waiter": 0,
                "chef_hot": 1,
                "chef_cold": 1,
                "chef_dim_sum": 0,
                "cashier": 0,
                "host": 0,
                "manager": 1,
            }
            for role, cnt in hourly_needs[prep_hour].items():
                total_person_hours[role] += cnt

        # Operating hours
        for h_data in hourly_traffic:
            hour = h_data["hour"]
            cust = h_data["predicted_customers"]

            # 服务员：每4桌1人，按同时在场率50%
            active_tables = min(total_tables, math.ceil(cust * 0.5))
            waiter_need = max(1, math.ceil(active_tables / 4))

            # 厨师：按出餐能力
            chef_hot_need = max(1, math.ceil(cust / STAFFING_STANDARD["chef_hot"]["covers_per_hour"]))
            chef_cold_need = max(0, math.ceil(cust * 0.3 / STAFFING_STANDARD["chef_cold"]["covers_per_hour"]))
            chef_dim_sum_need = 0
            if cust > 15:
                chef_dim_sum_need = max(0, math.ceil(cust * 0.2 / STAFFING_STANDARD["chef_dim_sum"]["covers_per_hour"]))

            # 固定岗位
            cashier_need = STAFFING_STANDARD["cashier"]["min_per_shift"]
            host_need = STAFFING_STANDARD["host"]["min_per_shift"] if h_data["is_peak"] else 0
            manager_need = STAFFING_STANDARD["manager"]["min_per_shift"]

            hourly_needs[hour] = {
                "waiter": waiter_need,
                "chef_hot": chef_hot_need,
                "chef_cold": chef_cold_need,
                "chef_dim_sum": chef_dim_sum_need,
                "cashier": cashier_need,
                "host": host_need,
                "manager": manager_need,
            }
            for role, cnt in hourly_needs[hour].items():
                total_person_hours[role] += cnt

        # Cleanup: 1 hour after close
        hourly_needs[close_h + 1] = {
            "waiter": 1,
            "chef_hot": 0,
            "chef_cold": 0,
            "chef_dim_sum": 0,
            "cashier": 0,
            "host": 0,
            "manager": 0,
        }
        total_person_hours["waiter"] += 1

        # Calculate total shifts needed
        total_shifts = 0
        for role, hours in total_person_hours.items():
            # Each shift is ~8 hours
            total_shifts += math.ceil(hours / 8)

        return {
            "store_id": store_id,
            "date": target_date.isoformat(),
            "hourly_needs": hourly_needs,
            "total_person_hours": total_person_hours,
            "total_shifts": total_shifts,
            "peak_staffing": {
                "lunch_peak": hourly_needs.get(12, {}),
                "dinner_peak": hourly_needs.get(18, {}),
            },
        }

    # ──────────────────────────────────────────────────────
    #  3. Auto Schedule Generation (自动排班)
    # ──────────────────────────────────────────────────────

    def generate_schedule(
        self,
        store_id: str,
        week_start_date: date,
        weather_forecast: Optional[Dict[str, str]] = None,
        holiday_map: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """自动生成7天排班表

        Input: available employees + skills + preferences + constraints
        Algorithm: greedy assignment with constraint satisfaction
        Returns: {date: {shift: [employee_ids]}} for 7 days
        """
        weather_forecast = weather_forecast or {}
        holiday_map = holiday_map or {}

        schedule: Dict[str, Dict[str, List[str]]] = {}
        employee_hours: Dict[str, float] = {e["employee_id"]: 0.0 for e in self.employees}
        employee_consecutive_days: Dict[str, int] = {e["employee_id"]: 0 for e in self.employees}
        employee_last_shift_end: Dict[str, Optional[int]] = {e["employee_id"]: None for e in self.employees}
        employee_day_assignments: Dict[str, List[str]] = {e["employee_id"]: [] for e in self.employees}

        for day_offset in range(7):
            current_date = week_start_date + timedelta(days=day_offset)
            date_str = current_date.isoformat()
            weather = weather_forecast.get(date_str, "sunny")
            holiday = holiday_map.get(date_str, "normal")

            # Get staffing needs
            needs = self.calculate_staffing_need(store_id, current_date, weather, holiday)

            # Determine which shifts are needed based on the day
            day_schedule: Dict[str, List[str]] = {}

            for shift_name in ["morning", "middle", "evening"]:
                shift_def = SHIFT_DEFINITIONS[shift_name]
                shift_start = shift_def["start_hour"]
                shift_end = shift_def["end_hour"]
                shift_duration = shift_def["duration_hours"]

                # Aggregate skill needs over shift hours
                shift_skill_needs: Dict[str, int] = {}
                for hour in range(shift_start, shift_end):
                    hour_need = needs["hourly_needs"].get(hour, {})
                    for role, cnt in hour_need.items():
                        shift_skill_needs[role] = max(shift_skill_needs.get(role, 0), cnt)

                assigned: List[str] = []

                # Greedy assignment: for each needed role, find best available employee
                for role, count_needed in sorted(shift_skill_needs.items(), key=lambda x: x[1], reverse=True):
                    if count_needed <= 0:
                        continue

                    # Find matching skill name
                    skill_name = role  # role names match skill names

                    candidates = self._get_eligible_candidates(
                        skill_name,
                        shift_name,
                        current_date,
                        date_str,
                        shift_def,
                        employee_hours,
                        employee_consecutive_days,
                        employee_last_shift_end,
                        employee_day_assignments,
                        assigned,
                    )

                    for _ in range(count_needed):
                        if not candidates:
                            break
                        # Pick best candidate: prefer matching preferred shift, then fewest hours
                        best = self._pick_best_candidate(candidates, shift_name, employee_hours)
                        if best:
                            assigned.append(best)
                            candidates.remove(best)

                # Update tracking
                for emp_id in set(assigned):
                    shift_def_item = SHIFT_DEFINITIONS[shift_name]
                    employee_hours[emp_id] += shift_def_item["duration_hours"]
                    employee_last_shift_end[emp_id] = shift_def_item["end_hour"]
                    if date_str not in employee_day_assignments[emp_id]:
                        employee_day_assignments[emp_id].append(date_str)

                day_schedule[shift_name] = list(set(assigned))

            schedule[date_str] = day_schedule

            # Update consecutive days
            for emp_id in employee_consecutive_days:
                if any(emp_id in emps for emps in day_schedule.values()):
                    employee_consecutive_days[emp_id] += 1
                else:
                    employee_consecutive_days[emp_id] = 0

        # Build result
        self._schedule_counter += 1
        schedule_id = f"SCH-{store_id}-{week_start_date.isoformat()}-{self._schedule_counter:04d}"

        result = {
            "schedule_id": schedule_id,
            "store_id": store_id,
            "week_start": week_start_date.isoformat(),
            "week_end": (week_start_date + timedelta(days=6)).isoformat(),
            "schedule": schedule,
            "employee_hours_summary": employee_hours,
            "created_at": datetime.now().isoformat(),
        }

        # Validate
        validation = self.validate_schedule(result)
        result["validation"] = validation

        # Store schedule
        self._schedules[schedule_id] = result

        return result

    def _get_eligible_candidates(
        self,
        skill_name: str,
        shift_name: str,
        current_date: date,
        date_str: str,
        shift_def: Dict[str, Any],
        employee_hours: Dict[str, float],
        employee_consecutive_days: Dict[str, int],
        employee_last_shift_end: Dict[str, Optional[int]],
        employee_day_assignments: Dict[str, List[str]],
        already_assigned: List[str],
    ) -> List[str]:
        """获取符合条件的候选员工"""
        candidates: List[str] = []

        for emp in self.employees:
            emp_id = emp["employee_id"]

            # Already assigned in this shift
            if emp_id in already_assigned:
                continue

            # Skill check
            if skill_name not in emp.get("skills", []):
                continue

            # Weekly hours cap
            max_week = emp.get("max_hours_week", MAX_HOURS_WEEK_STANDARD)
            if employee_hours.get(emp_id, 0) + shift_def["duration_hours"] > max_week:
                continue

            # Consecutive days check
            if employee_consecutive_days.get(emp_id, 0) >= MAX_CONSECUTIVE_DAYS:
                continue

            # Rest between shifts
            last_end = employee_last_shift_end.get(emp_id)
            if last_end is not None:
                # If same day, calculate rest
                hours_rest = shift_def["start_hour"] + 24 - last_end  # approximate
                if date_str in employee_day_assignments.get(emp_id, []):
                    hours_rest = shift_def["start_hour"] - last_end
                if hours_rest < MIN_REST_BETWEEN_SHIFTS_HOURS and hours_rest > 0:
                    continue

            # Minor restrictions
            if emp.get("is_minor", False):
                if shift_def["end_hour"] > MINOR_NIGHT_SHIFT_CUTOFF:
                    continue
                if shift_def["duration_hours"] > MAX_HOURS_DAY_MINOR:
                    continue

            candidates.append(emp_id)

        return candidates

    def _pick_best_candidate(
        self,
        candidates: List[str],
        shift_name: str,
        employee_hours: Dict[str, float],
    ) -> Optional[str]:
        """从候选中选最优（偏好匹配 + 均衡工时）"""
        if not candidates:
            return None

        emp_lookup = {e["employee_id"]: e for e in self.employees}

        scored: List[Tuple[str, float]] = []
        for cid in candidates:
            emp = emp_lookup.get(cid)
            if not emp:
                continue
            score = 0.0
            # Preference bonus
            if shift_name in emp.get("preferred_shifts", []):
                score += 10.0
            # Fewer hours = higher priority (load balancing)
            score += max(0, 44 - employee_hours.get(cid, 0))
            scored.append((cid, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0] if scored else None

    # ──────────────────────────────────────────────────────
    #  Schedule CRUD
    # ──────────────────────────────────────────────────────

    def get_schedule(
        self,
        store_id: str,
        date_range: Tuple[date, date],
    ) -> List[Dict[str, Any]]:
        """查询指定日期范围的排班"""
        results: List[Dict[str, Any]] = []
        start_str = date_range[0].isoformat()
        end_str = date_range[1].isoformat()

        for sch_id, sch in self._schedules.items():
            if sch["store_id"] != store_id:
                continue
            if sch["week_start"] <= end_str and sch["week_end"] >= start_str:
                results.append(sch)

        return results

    def update_shift(
        self,
        schedule_id: str,
        employee_id: str,
        new_shift: str,
        target_date: str,
    ) -> Dict[str, Any]:
        """更新员工班次

        Args:
            schedule_id: 排班表ID
            employee_id: 员工ID
            new_shift: 新班次 morning/middle/evening
            target_date: 目标日期 YYYY-MM-DD
        """
        sch = self._schedules.get(schedule_id)
        if not sch:
            return {"ok": False, "error": f"Schedule {schedule_id} not found"}

        if target_date not in sch["schedule"]:
            return {"ok": False, "error": f"Date {target_date} not in schedule"}

        if new_shift not in SHIFT_DEFINITIONS:
            return {"ok": False, "error": f"Invalid shift: {new_shift}"}

        day_sch = sch["schedule"][target_date]

        # Remove from old shift
        old_shift = None
        for shift_name, emp_list in day_sch.items():
            if employee_id in emp_list:
                emp_list.remove(employee_id)
                old_shift = shift_name
                break

        # Add to new shift
        if new_shift not in day_sch:
            day_sch[new_shift] = []
        day_sch[new_shift].append(employee_id)

        # Update hours
        if old_shift:
            sch["employee_hours_summary"][employee_id] -= SHIFT_DEFINITIONS[old_shift]["duration_hours"]
        sch["employee_hours_summary"][employee_id] = (
            sch["employee_hours_summary"].get(employee_id, 0) + SHIFT_DEFINITIONS[new_shift]["duration_hours"]
        )

        # Re-validate
        sch["validation"] = self.validate_schedule(sch)

        return {
            "ok": True,
            "schedule_id": schedule_id,
            "employee_id": employee_id,
            "date": target_date,
            "old_shift": old_shift,
            "new_shift": new_shift,
        }

    def swap_shift(
        self,
        schedule_id: str,
        employee_a: str,
        employee_b: str,
        target_date: str,
    ) -> Dict[str, Any]:
        """两位员工互换班次

        Args:
            schedule_id: 排班表ID
            employee_a: 员工A ID
            employee_b: 员工B ID
            target_date: 目标日期
        """
        sch = self._schedules.get(schedule_id)
        if not sch:
            return {"ok": False, "error": f"Schedule {schedule_id} not found"}

        if target_date not in sch["schedule"]:
            return {"ok": False, "error": f"Date {target_date} not in schedule"}

        day_sch = sch["schedule"][target_date]

        shift_a = None
        shift_b = None
        for shift_name, emp_list in day_sch.items():
            if employee_a in emp_list:
                shift_a = shift_name
            if employee_b in emp_list:
                shift_b = shift_name

        if shift_a is None:
            return {"ok": False, "error": f"Employee {employee_a} not scheduled on {target_date}"}
        if shift_b is None:
            return {"ok": False, "error": f"Employee {employee_b} not scheduled on {target_date}"}

        if shift_a == shift_b:
            return {"ok": True, "message": "Same shift, no swap needed"}

        # Swap
        day_sch[shift_a].remove(employee_a)
        day_sch[shift_b].remove(employee_b)
        day_sch[shift_a].append(employee_b)
        day_sch[shift_b].append(employee_a)

        # Update hours
        hours_a = SHIFT_DEFINITIONS[shift_a]["duration_hours"]
        hours_b = SHIFT_DEFINITIONS[shift_b]["duration_hours"]
        sch["employee_hours_summary"][employee_a] += hours_b - hours_a
        sch["employee_hours_summary"][employee_b] += hours_a - hours_b

        sch["validation"] = self.validate_schedule(sch)

        return {
            "ok": True,
            "schedule_id": schedule_id,
            "date": target_date,
            "employee_a": {"id": employee_a, "old_shift": shift_a, "new_shift": shift_b},
            "employee_b": {"id": employee_b, "old_shift": shift_b, "new_shift": shift_a},
        }

    # ──────────────────────────────────────────────────────
    #  4. Constraint Validation (法规约束)
    # ──────────────────────────────────────────────────────

    def validate_schedule(self, schedule_data: Dict[str, Any]) -> Dict[str, Any]:
        """校验排班合规性

        Rules:
        - Max 40h/week (standard), 44h/week (comprehensive)
        - Min 11h rest between shifts
        - Max 6 consecutive days
        - Minors: no night shifts, max 8h/day
        - Overtime cap: 36h/month

        Returns: {valid, violations: [{employee, rule, detail}]}
        """
        violations: List[Dict[str, Any]] = []
        emp_lookup = {e["employee_id"]: e for e in self.employees}
        schedule = schedule_data.get("schedule", {})
        hours_summary = schedule_data.get("employee_hours_summary", {})

        # --- Rule 1: Weekly hours cap ---
        for emp_id, total_hours in hours_summary.items():
            emp = emp_lookup.get(emp_id, {})
            max_week = emp.get("max_hours_week", MAX_HOURS_WEEK_STANDARD)
            if total_hours > max_week:
                violations.append(
                    {
                        "employee_id": emp_id,
                        "employee_name": emp.get("name", "unknown"),
                        "rule": "weekly_hours_cap",
                        "detail": f"周工时 {total_hours}h 超出上限 {max_week}h",
                        "severity": "error",
                    }
                )

        # --- Rule 2: Consecutive days ---
        emp_work_dates: Dict[str, List[str]] = {}
        for date_str, day_sch in sorted(schedule.items()):
            for shift_name, emp_list in day_sch.items():
                for emp_id in emp_list:
                    if emp_id not in emp_work_dates:
                        emp_work_dates[emp_id] = []
                    if date_str not in emp_work_dates[emp_id]:
                        emp_work_dates[emp_id].append(date_str)

        for emp_id, dates in emp_work_dates.items():
            sorted_dates = sorted(dates)
            consecutive = 1
            max_consecutive = 1
            for i in range(1, len(sorted_dates)):
                d1 = date.fromisoformat(sorted_dates[i - 1])
                d2 = date.fromisoformat(sorted_dates[i])
                if (d2 - d1).days == 1:
                    consecutive += 1
                    max_consecutive = max(max_consecutive, consecutive)
                else:
                    consecutive = 1

            if max_consecutive > MAX_CONSECUTIVE_DAYS:
                emp = emp_lookup.get(emp_id, {})
                violations.append(
                    {
                        "employee_id": emp_id,
                        "employee_name": emp.get("name", "unknown"),
                        "rule": "max_consecutive_days",
                        "detail": f"连续工作 {max_consecutive} 天，超出上限 {MAX_CONSECUTIVE_DAYS} 天",
                        "severity": "error",
                    }
                )

        # --- Rule 3: Minor restrictions ---
        for date_str, day_sch in schedule.items():
            for shift_name, emp_list in day_sch.items():
                shift_def = SHIFT_DEFINITIONS.get(shift_name, {})
                for emp_id in emp_list:
                    emp = emp_lookup.get(emp_id, {})
                    if emp.get("is_minor", False):
                        if shift_def.get("end_hour", 0) > MINOR_NIGHT_SHIFT_CUTOFF:
                            violations.append(
                                {
                                    "employee_id": emp_id,
                                    "employee_name": emp.get("name", "unknown"),
                                    "rule": "minor_night_shift",
                                    "detail": f"未成年人 {date_str} 排到夜班（结束于 {shift_def['end_hour']}:00 > {MINOR_NIGHT_SHIFT_CUTOFF}:00）",
                                    "severity": "error",
                                }
                            )
                        if shift_def.get("duration_hours", 0) > MAX_HOURS_DAY_MINOR:
                            violations.append(
                                {
                                    "employee_id": emp_id,
                                    "employee_name": emp.get("name", "unknown"),
                                    "rule": "minor_daily_hours",
                                    "detail": f"未成年人 {date_str} 工时 {shift_def['duration_hours']}h > {MAX_HOURS_DAY_MINOR}h 上限",
                                    "severity": "error",
                                }
                            )

        # --- Rule 4: Rest between shifts ---
        for emp_id, dates in emp_work_dates.items():
            sorted_dates = sorted(dates)
            for i in range(1, len(sorted_dates)):
                d1 = date.fromisoformat(sorted_dates[i - 1])
                d2 = date.fromisoformat(sorted_dates[i])
                if (d2 - d1).days == 1:
                    # Find the employee's last shift on d1
                    d1_sch = schedule.get(sorted_dates[i - 1], {})
                    last_end = 0
                    for sn, elist in d1_sch.items():
                        if emp_id in elist:
                            se = SHIFT_DEFINITIONS.get(sn, {}).get("end_hour", 0)
                            last_end = max(last_end, se)

                    # Find the employee's first shift on d2
                    d2_sch = schedule.get(sorted_dates[i], {})
                    first_start = 24
                    for sn, elist in d2_sch.items():
                        if emp_id in elist:
                            ss = SHIFT_DEFINITIONS.get(sn, {}).get("start_hour", 24)
                            first_start = min(first_start, ss)

                    rest_hours = (24 - last_end) + first_start
                    if rest_hours < MIN_REST_BETWEEN_SHIFTS_HOURS:
                        emp = emp_lookup.get(emp_id, {})
                        violations.append(
                            {
                                "employee_id": emp_id,
                                "employee_name": emp.get("name", "unknown"),
                                "rule": "min_rest_between_shifts",
                                "detail": f"{sorted_dates[i - 1]}→{sorted_dates[i]} 休息仅 {rest_hours}h < {MIN_REST_BETWEEN_SHIFTS_HOURS}h",
                                "severity": "warning",
                            }
                        )

        # --- Rule 5: Overtime estimate (monthly projection) ---
        standard_weekly = MAX_HOURS_WEEK_STANDARD
        for emp_id, week_hours in hours_summary.items():
            overtime_week = max(0, week_hours - standard_weekly)
            # Project to monthly
            overtime_month_est = overtime_week * 4.33
            if overtime_month_est > MAX_OVERTIME_MONTH_HOURS:
                emp = emp_lookup.get(emp_id, {})
                violations.append(
                    {
                        "employee_id": emp_id,
                        "employee_name": emp.get("name", "unknown"),
                        "rule": "monthly_overtime_cap",
                        "detail": f"预估月加班 {overtime_month_est:.0f}h 超出 {MAX_OVERTIME_MONTH_HOURS}h 上限",
                        "severity": "warning",
                    }
                )

        is_valid = not any(v["severity"] == "error" for v in violations)

        return {
            "valid": is_valid,
            "violations": violations,
            "total_violations": len(violations),
            "error_count": sum(1 for v in violations if v["severity"] == "error"),
            "warning_count": sum(1 for v in violations if v["severity"] == "warning"),
        }

    # ──────────────────────────────────────────────────────
    #  5. Skill Matching (技能匹配)
    # ──────────────────────────────────────────────────────

    def match_skills(
        self,
        store_id: str,
        shift_name: str,
        required_skills: List[str],
        target_date: Optional[date] = None,
        exclude_employee_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """匹配可用员工技能

        Match available employees to required skills
        Skills: cashier, waiter, chef_cold, chef_hot, chef_dim_sum, host, manager

        Returns: list of matching employees with match_score
        """
        exclude = set(exclude_employee_ids or [])
        results: List[Dict[str, Any]] = []

        for emp in self.employees:
            if emp["employee_id"] in exclude:
                continue

            emp_skills = set(emp.get("skills", []))
            required_set = set(required_skills)
            matched_skills = emp_skills & required_set
            match_score = len(matched_skills) / len(required_set) if required_set else 0

            if match_score == 0:
                continue

            # Preference bonus
            preference_bonus = 0.1 if shift_name in emp.get("preferred_shifts", []) else 0

            results.append(
                {
                    "employee_id": emp["employee_id"],
                    "name": emp["name"],
                    "position": emp["position"],
                    "skills": list(emp_skills),
                    "matched_skills": list(matched_skills),
                    "match_score": round(match_score + preference_bonus, 2),
                    "preferred_shift": shift_name in emp.get("preferred_shifts", []),
                    "hourly_rate_fen": emp["hourly_rate_fen"],
                }
            )

        results.sort(key=lambda x: x["match_score"], reverse=True)
        return results

    # ──────────────────────────────────────────────────────
    #  6. Analytics
    # ──────────────────────────────────────────────────────

    def get_schedule_efficiency(
        self,
        store_id: str,
        date_range: Tuple[date, date],
        actual_traffic: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """排班效率分析

        Actual vs predicted traffic, over/understaffing hours, labor cost

        Args:
            store_id: 门店ID
            date_range: (start_date, end_date)
            actual_traffic: {date_iso: actual_daily_customers}
        """
        actual_traffic = actual_traffic or {}
        schedules = self.get_schedule(store_id, date_range)

        total_scheduled_hours = 0.0
        total_predicted_customers = 0
        total_actual_customers = 0
        total_labor_cost_fen = 0
        overstaffed_hours = 0.0
        understaffed_hours = 0.0

        emp_lookup = {e["employee_id"]: e for e in self.employees}

        for sch in schedules:
            for date_str, day_sch in sch.get("schedule", {}).items():
                d = date.fromisoformat(date_str)
                if d < date_range[0] or d > date_range[1]:
                    continue

                # Predicted traffic for this day
                hourly_pred = self.predict_traffic(store_id, d)
                day_predicted = sum(h["predicted_customers"] for h in hourly_pred)
                total_predicted_customers += day_predicted

                day_actual = actual_traffic.get(date_str, day_predicted)
                total_actual_customers += day_actual

                # Scheduled hours and cost
                for shift_name, emp_list in day_sch.items():
                    shift_hours = SHIFT_DEFINITIONS.get(shift_name, {}).get("duration_hours", 8)
                    for emp_id in emp_list:
                        total_scheduled_hours += shift_hours
                        emp = emp_lookup.get(emp_id, {})
                        total_labor_cost_fen += emp.get("hourly_rate_fen", 2500) * shift_hours

                # Over/understaffing estimate
                traffic_ratio = day_actual / day_predicted if day_predicted > 0 else 1.0
                if traffic_ratio < 0.85:
                    # Overstaffed
                    overstaffed_hours += (
                        sum(
                            SHIFT_DEFINITIONS.get(sn, {}).get("duration_hours", 0) * len(el)
                            for sn, el in day_sch.items()
                        )
                        * (1 - traffic_ratio)
                        * 0.5
                    )
                elif traffic_ratio > 1.15:
                    understaffed_hours += (traffic_ratio - 1) * 8  # approximate

        prediction_accuracy = 0.0
        if total_predicted_customers > 0:
            prediction_accuracy = round(
                (1 - abs(total_actual_customers - total_predicted_customers) / total_predicted_customers) * 100, 1
            )

        return {
            "store_id": store_id,
            "date_range": {
                "start": date_range[0].isoformat(),
                "end": date_range[1].isoformat(),
            },
            "total_scheduled_hours": round(total_scheduled_hours, 1),
            "total_labor_cost_fen": total_labor_cost_fen,
            "total_labor_cost_yuan": round(total_labor_cost_fen / 100, 2),
            "predicted_customers": total_predicted_customers,
            "actual_customers": total_actual_customers,
            "prediction_accuracy_pct": prediction_accuracy,
            "overstaffed_hours": round(overstaffed_hours, 1),
            "understaffed_hours": round(understaffed_hours, 1),
            "efficiency_score": round(max(0, 100 - overstaffed_hours - understaffed_hours * 2), 1),
        }

    def get_overtime_report(
        self,
        store_id: str,
        month: str,
    ) -> List[Dict[str, Any]]:
        """加班报表

        Args:
            store_id: 门店ID
            month: 月份 "YYYY-MM"
        """
        emp_lookup = {e["employee_id"]: e for e in self.employees}
        report: List[Dict[str, Any]] = []

        # Aggregate from schedules
        emp_monthly_hours: Dict[str, float] = {}
        emp_work_days: Dict[str, int] = {}

        for sch_id, sch in self._schedules.items():
            if sch["store_id"] != store_id:
                continue
            for date_str, day_sch in sch.get("schedule", {}).items():
                if not date_str.startswith(month):
                    continue
                for shift_name, emp_list in day_sch.items():
                    duration = SHIFT_DEFINITIONS.get(shift_name, {}).get("duration_hours", 8)
                    for emp_id in emp_list:
                        emp_monthly_hours[emp_id] = emp_monthly_hours.get(emp_id, 0) + duration
                        emp_work_days[emp_id] = emp_work_days.get(emp_id, 0) + 1

        # Calculate overtime
        # Standard: 21.75 days * 8h = 174h / month
        standard_monthly_hours = 174.0

        for emp_id, total_hours in emp_monthly_hours.items():
            emp = emp_lookup.get(emp_id, {})
            overtime_hours = max(0, total_hours - standard_monthly_hours)
            overtime_cost_fen = int(overtime_hours * emp.get("hourly_rate_fen", 2500) * 1.5)
            exceeds_cap = overtime_hours > MAX_OVERTIME_MONTH_HOURS

            report.append(
                {
                    "employee_id": emp_id,
                    "employee_name": emp.get("name", "unknown"),
                    "position": emp.get("position", "unknown"),
                    "work_days": emp_work_days.get(emp_id, 0),
                    "total_hours": round(total_hours, 1),
                    "standard_hours": standard_monthly_hours,
                    "overtime_hours": round(overtime_hours, 1),
                    "overtime_cost_fen": overtime_cost_fen,
                    "overtime_cost_yuan": round(overtime_cost_fen / 100, 2),
                    "exceeds_monthly_cap": exceeds_cap,
                    "cap_hours": MAX_OVERTIME_MONTH_HOURS,
                }
            )

        report.sort(key=lambda x: x["overtime_hours"], reverse=True)
        return report
