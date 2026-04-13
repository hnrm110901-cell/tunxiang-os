"""屯象OS tx-agent 排班优化 Agent：基于历史客流与当前排班，生成下周排班优化建议。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger(__name__)

# ── 时段定义 ─────────────────────────────────────────────────────────────────

_TIME_SLOTS = [
    ("morning", "09:00-11:00", "早班"),
    ("lunch_peak", "11:00-14:00", "午高峰"),
    ("afternoon", "14:00-17:00", "下午班"),
    ("dinner_peak", "17:00-21:00", "晚高峰"),
    ("night", "21:00-23:00", "夜班"),
]

# 默认各时段人力基准（可被门店配置覆盖）
_DEFAULT_STAFF_BASELINE: dict[str, int] = {
    "morning": 3,
    "lunch_peak": 6,
    "afternoon": 3,
    "dinner_peak": 7,
    "night": 2,
}


# ── 辅助函数 ─────────────────────────────────────────────────────────────────


def _week_range(ref_date: date | None = None) -> tuple[date, date]:
    """返回下周一到下周日的日期范围。"""
    today = ref_date or date.today()
    days_to_next_monday = (7 - today.weekday()) % 7 or 7
    start = today + timedelta(days=days_to_next_monday)
    end = start + timedelta(days=6)
    return start, end


def _efficiency_score(staff_count: int, revenue_fen: int) -> float:
    """人效分：每人每时段产出（分）。"""
    if staff_count <= 0:
        return 0.0
    return round(revenue_fen / staff_count, 2)


def _suggest_action(
    slot: str,
    current_staff: int,
    ideal_staff: int,
) -> dict[str, Any] | None:
    """对比当前与理想配置，生成调整建议。"""
    diff = current_staff - ideal_staff
    if abs(diff) < 1:
        return None
    if diff > 0:
        return {
            "slot": slot,
            "action": "reduce",
            "current": current_staff,
            "suggested": ideal_staff,
            "delta": -diff,
            "reason": f"该时段人力富余{diff}人，建议减班",
        }
    return {
        "slot": slot,
        "action": "increase",
        "current": current_staff,
        "suggested": ideal_staff,
        "delta": -diff,
        "reason": f"该时段人力不足{-diff}人，建议加班",
    }


# ── 数据查询 ─────────────────────────────────────────────────────────────────


async def _load_current_schedules(
    db: Any,
    tenant_id: str,
    store_id: str,
    week_start: date,
    week_end: date,
) -> list[dict[str, Any]]:
    """从 unified_schedules 查当前排班。"""
    q = text("""
        SELECT us.id::text, us.employee_id::text, us.schedule_date AS shift_date,
               us.start_time, us.end_time, us.role,
               e.emp_name
        FROM unified_schedules us
        LEFT JOIN employees e
          ON e.id = us.employee_id AND e.tenant_id = us.tenant_id
        WHERE us.tenant_id = CAST(:tenant_id AS uuid)
          AND us.store_id = CAST(:store_id AS uuid)
          AND us.schedule_date BETWEEN :week_start AND :week_end
          AND COALESCE(us.is_deleted, false) = false
        ORDER BY us.schedule_date, us.start_time
    """)
    try:
        result = await db.execute(q, {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "week_start": week_start,
            "week_end": week_end,
        })
        return [dict(r) for r in result.mappings()]
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("workforce_load_schedules_failed", error=str(exc))
        return []


async def _load_revenue_by_slot(
    db: Any,
    tenant_id: str,
    store_id: str,
    lookback_days: int = 28,
) -> dict[str, int]:
    """从历史订单聚合各时段营收（降级为mock）。

    TODO: 接入 tx-trade 订单表后替换为真实查询。
    """
    # 尝试从 mv_store_pnl 或 orders 聚合，失败则降级
    try:
        q = text("""
            SELECT
              CASE
                WHEN EXTRACT(HOUR FROM o.created_at) BETWEEN 9 AND 10 THEN 'morning'
                WHEN EXTRACT(HOUR FROM o.created_at) BETWEEN 11 AND 13 THEN 'lunch_peak'
                WHEN EXTRACT(HOUR FROM o.created_at) BETWEEN 14 AND 16 THEN 'afternoon'
                WHEN EXTRACT(HOUR FROM o.created_at) BETWEEN 17 AND 20 THEN 'dinner_peak'
                ELSE 'night'
              END AS slot,
              COALESCE(SUM(o.total_fen), 0)::bigint AS revenue_fen
            FROM orders o
            WHERE o.tenant_id = CAST(:tenant_id AS uuid)
              AND o.store_id = CAST(:store_id AS uuid)
              AND o.created_at >= CURRENT_DATE - :lookback_days * INTERVAL '1 day'
              AND o.status = 'paid'
            GROUP BY slot
        """)
        result = await db.execute(q, {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "lookback_days": lookback_days,
        })
        rows = {str(r["slot"]): int(r["revenue_fen"]) for r in result.mappings()}
        if rows:
            return rows
    except (OperationalError, ProgrammingError):
        pass
    # 降级 mock
    return _mock_revenue_by_slot()


def _mock_revenue_by_slot() -> dict[str, int]:
    return {
        "morning": 280000,
        "lunch_peak": 980000,
        "afternoon": 180000,
        "dinner_peak": 1200000,
        "night": 120000,
    }


async def _load_labor_forecast(
    db: Any,
    tenant_id: str,
    store_id: str,
) -> dict[str, int]:
    """基于历史客流预测各时段理想人数。简化版：营收/人效基准。"""
    revenue = await _load_revenue_by_slot(db, tenant_id, store_id)
    # 假设人效基准：每人每时段应产出 15万分（1500元）
    per_person_target = 150000
    ideal: dict[str, int] = {}
    for slot in _DEFAULT_STAFF_BASELINE:
        rev = revenue.get(slot, 0)
        needed = max(1, round(rev / per_person_target))
        ideal[slot] = needed
    return ideal


def _mock_schedules() -> list[dict[str, Any]]:
    today = date.today()
    start, _ = _week_range(today)
    return [
        {
            "id": f"mock-sched-{i}",
            "employee_id": f"mock-emp-{i:03d}",
            "emp_name": name,
            "shift_date": (start + timedelta(days=d)).isoformat(),
            "start_time": st,
            "end_time": et,
            "role": role,
        }
        for i, (name, d, st, et, role) in enumerate([
            ("张三", 0, "09:00", "14:00", "waiter"),
            ("李四", 0, "09:00", "14:00", "waiter"),
            ("王五", 0, "11:00", "21:00", "chef"),
            ("赵六", 0, "11:00", "21:00", "chef"),
            ("钱七", 0, "14:00", "21:00", "waiter"),
            ("孙八", 0, "17:00", "23:00", "waiter"),
            ("周九", 0, "17:00", "23:00", "waiter"),
        ])
    ]


def _mock_optimization() -> dict[str, Any]:
    return {
        "suggestions": [
            {
                "slot": "morning",
                "slot_label": "早班",
                "action": "reduce",
                "current": 3,
                "suggested": 2,
                "delta": -1,
                "reason": "早班客流偏低，人力富余1人，建议减班",
                "estimated_saving_fen": 18000,
            },
            {
                "slot": "dinner_peak",
                "slot_label": "晚高峰",
                "action": "increase",
                "current": 3,
                "suggested": 5,
                "delta": 2,
                "reason": "晚高峰营收占比最高，建议增加2人保障服务",
                "estimated_saving_fen": -36000,
            },
            {
                "slot": "afternoon",
                "slot_label": "下午班",
                "action": "reduce",
                "current": 3,
                "suggested": 2,
                "delta": -1,
                "reason": "下午客流低谷，可减1人或调为弹性班",
                "estimated_saving_fen": 18000,
            },
        ],
        "summary": {
            "total_suggestions": 3,
            "estimated_net_saving_fen": 0,
            "optimization_rate": 0.15,
        },
        "efficiency_before": {
            "morning": 93333,
            "lunch_peak": 163333,
            "afternoon": 60000,
            "dinner_peak": 400000,
            "night": 60000,
        },
        "efficiency_after": {
            "morning": 140000,
            "lunch_peak": 163333,
            "afternoon": 90000,
            "dinner_peak": 240000,
            "night": 60000,
        },
    }


# ── Agent 类 ─────────────────────────────────────────────────────────────────


class WorkforcePlannerAgent(SkillAgent):
    """排班优化 Skill：分析排班效率、生成优化建议、预测劳动力需求、营收驱动排班。"""

    agent_id = "workforce_planner"
    agent_name = "排班优化"
    description = "基于历史客流与POS营收数据，分析人力配置合理性并生成最优排班方案"
    priority = "P1"
    run_location = "cloud"
    agent_level = 2  # 自动生成draft排班 + 30分钟回滚窗口

    def get_supported_actions(self) -> list[str]:
        return [
            "analyze_schedule_efficiency",
            "suggest_optimization",
            "get_labor_forecast",
            "analyze_revenue_schedule",
            "apply_optimal_plan",
        ]

    def _store_scope(self, params: dict[str, Any]) -> Optional[str]:
        sid = params.get("store_id")
        if sid is not None and str(sid).strip():
            return str(sid).strip()
        if self.store_id is not None and str(self.store_id).strip():
            return str(self.store_id).strip()
        return None

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch: dict[str, Any] = {
            "analyze_schedule_efficiency": self._analyze_efficiency,
            "suggest_optimization": self._suggest_optimization,
            "get_labor_forecast": self._get_labor_forecast,
            "analyze_revenue_schedule": self._analyze_revenue_schedule,
            "apply_optimal_plan": self._apply_optimal_plan,
        }
        handler = dispatch.get(action)
        if handler is None:
            return AgentResult(
                success=False,
                action=action,
                error=f"不支持的操作: {action}",
            )
        return await handler(params)

    async def _analyze_efficiency(self, params: dict[str, Any]) -> AgentResult:
        """分析当前排班的各时段人效。"""
        store_id = self._store_scope(params)
        if not store_id:
            return AgentResult(success=False, action="analyze_schedule_efficiency",
                               error="缺少 store_id")
        week_start, week_end = _week_range()

        if self._db:
            schedules = await _load_current_schedules(
                self._db, self.tenant_id, store_id, week_start, week_end
            )
            revenue = await _load_revenue_by_slot(self._db, self.tenant_id, store_id)
        else:
            logger.info("workforce_analyze_mock", tenant_id=self.tenant_id)
            schedules = _mock_schedules()
            revenue = _mock_revenue_by_slot()

        # 统计各时段排班人数（简化：按 start_time 归时段）
        slot_counts: dict[str, int] = {s: 0 for s, _, _ in _TIME_SLOTS}
        for sch in schedules:
            st = str(sch.get("start_time") or "09:00")
            hour = int(st.split(":")[0]) if ":" in st else 9
            if hour < 11:
                slot_counts["morning"] += 1
            elif hour < 14:
                slot_counts["lunch_peak"] += 1
            elif hour < 17:
                slot_counts["afternoon"] += 1
            elif hour < 21:
                slot_counts["dinner_peak"] += 1
            else:
                slot_counts["night"] += 1

        efficiency: dict[str, float] = {}
        for slot, _, _ in _TIME_SLOTS:
            efficiency[slot] = _efficiency_score(
                slot_counts.get(slot, 0), revenue.get(slot, 0)
            )

        return AgentResult(
            success=True,
            action="analyze_schedule_efficiency",
            data={
                "week_range": {"start": week_start.isoformat(), "end": week_end.isoformat()},
                "slot_staff_counts": slot_counts,
                "slot_revenue_fen": revenue,
                "slot_efficiency": efficiency,
                "schedule_count": len(schedules),
            },
            reasoning=f"排班效率分析完成：{len(schedules)}条排班，覆盖{sum(1 for v in slot_counts.values() if v > 0)}个时段",
            confidence=0.85,
        )

    async def _suggest_optimization(self, params: dict[str, Any]) -> AgentResult:
        """生成排班优化建议。"""
        store_id = self._store_scope(params)
        if not store_id:
            return AgentResult(success=False, action="suggest_optimization",
                               error="缺少 store_id")

        if not self._db:
            logger.info("workforce_suggest_mock", tenant_id=self.tenant_id)
            data = _mock_optimization()
            return AgentResult(
                success=True,
                action="suggest_optimization",
                data=data,
                reasoning=f"排班优化建议生成完成（mock），共{data['summary']['total_suggestions']}条建议",
                confidence=0.80,
            )

        # 真实逻辑：对比当前排班 vs 理想配置
        week_start, week_end = _week_range()
        schedules = await _load_current_schedules(
            self._db, self.tenant_id, store_id, week_start, week_end
        )
        ideal = await _load_labor_forecast(self._db, self.tenant_id, store_id)
        revenue = await _load_revenue_by_slot(self._db, self.tenant_id, store_id)

        # 当前各时段人数
        slot_counts: dict[str, int] = {s: 0 for s, _, _ in _TIME_SLOTS}
        for sch in schedules:
            st = str(sch.get("start_time") or "09:00")
            hour = int(st.split(":")[0]) if ":" in st else 9
            if hour < 11:
                slot_counts["morning"] += 1
            elif hour < 14:
                slot_counts["lunch_peak"] += 1
            elif hour < 17:
                slot_counts["afternoon"] += 1
            elif hour < 21:
                slot_counts["dinner_peak"] += 1
            else:
                slot_counts["night"] += 1

        suggestions: list[dict[str, Any]] = []
        daily_wage_fen = 18000  # 假设日均人工成本180元
        slot_labels = {s: label for s, _, label in _TIME_SLOTS}

        for slot, _, label in _TIME_SLOTS:
            current = slot_counts.get(slot, 0)
            target = ideal.get(slot, _DEFAULT_STAFF_BASELINE.get(slot, 3))
            s = _suggest_action(slot, current, target)
            if s:
                s["slot_label"] = label
                s["estimated_saving_fen"] = s["delta"] * daily_wage_fen
                suggestions.append(s)

        net_saving = sum(s.get("estimated_saving_fen", 0) for s in suggestions)
        total_staff = sum(slot_counts.values()) or 1

        # 计算优化前后人效
        eff_before: dict[str, float] = {}
        eff_after: dict[str, float] = {}
        for slot, _, _ in _TIME_SLOTS:
            rev = revenue.get(slot, 0)
            cur = slot_counts.get(slot, 0)
            tgt = ideal.get(slot, cur)
            eff_before[slot] = _efficiency_score(cur, rev)
            eff_after[slot] = _efficiency_score(tgt, rev)

        return AgentResult(
            success=True,
            action="suggest_optimization",
            data={
                "suggestions": suggestions,
                "summary": {
                    "total_suggestions": len(suggestions),
                    "estimated_net_saving_fen": net_saving,
                    "optimization_rate": round(len(suggestions) / max(1, len(_TIME_SLOTS)), 2),
                },
                "efficiency_before": eff_before,
                "efficiency_after": eff_after,
            },
            reasoning=f"排班优化分析完成，共{len(suggestions)}条建议，预计净节省{net_saving}分",
            confidence=0.82,
        )

    async def _get_labor_forecast(self, params: dict[str, Any]) -> AgentResult:
        """获取劳动力需求预测。"""
        store_id = self._store_scope(params)
        if not store_id:
            return AgentResult(success=False, action="get_labor_forecast",
                               error="缺少 store_id")

        if self._db:
            forecast = await _load_labor_forecast(self._db, self.tenant_id, store_id)
        else:
            logger.info("workforce_forecast_mock", tenant_id=self.tenant_id)
            forecast = {s: _DEFAULT_STAFF_BASELINE[s] for s, _, _ in _TIME_SLOTS}

        total = sum(forecast.values())
        slot_details = [
            {"slot": s, "label": label, "ideal_staff": forecast.get(s, 0)}
            for s, _, label in _TIME_SLOTS
        ]

        return AgentResult(
            success=True,
            action="get_labor_forecast",
            data={
                "forecast": forecast,
                "slot_details": slot_details,
                "total_ideal_staff": total,
            },
            reasoning=f"劳动力需求预测完成，理想总人力{total}人",
            confidence=0.78,
        )

    # ── 营收驱动排班（新增 action） ──────────────────────────────────────────────

    async def _analyze_revenue_schedule(self, params: dict[str, Any]) -> AgentResult:
        """营收驱动排班分析：基于POS交易数据推导最优人力配置。

        调用 RevenueScheduleService，从 mv_store_pnl / orders 表读取
        历史营收数据，自动计算各时段最优排班。

        这是屯象OS vs i人事/乐才的核心差异化——它们没有POS数据。
        """
        store_id = self._store_scope(params)
        if not store_id:
            return AgentResult(
                success=False,
                action="analyze_revenue_schedule",
                error="缺少 store_id",
            )

        week_start_str = params.get("week_start")
        if week_start_str:
            try:
                week_start = date.fromisoformat(str(week_start_str))
            except ValueError:
                return AgentResult(
                    success=False,
                    action="analyze_revenue_schedule",
                    error=f"无效的 week_start: {week_start_str}",
                )
        else:
            # 默认下周一
            today = date.today()
            days_to_monday = (7 - today.weekday()) % 7 or 7
            week_start = today + timedelta(days=days_to_monday)

        if not self._db:
            logger.info("workforce_revenue_schedule_mock", tenant_id=self.tenant_id)
            return AgentResult(
                success=True,
                action="analyze_revenue_schedule",
                data=_mock_revenue_schedule(store_id, week_start),
                reasoning="营收驱动排班分析完成（mock数据，未连接数据库）",
                confidence=0.70,
                agent_level=2,
                rollback_window_min=30,
            )

        # 真实逻辑：调用 RevenueScheduleService
        from services.revenue_schedule_service import RevenueScheduleService

        svc = RevenueScheduleService()
        try:
            plan = await svc.generate_weekly_plan(
                self._db, self.tenant_id, store_id, week_start
            )
        except (OperationalError, ProgrammingError) as exc:
            logger.warning(
                "workforce_revenue_schedule_db_error",
                error=str(exc),
                tenant_id=self.tenant_id,
            )
            return AgentResult(
                success=True,
                action="analyze_revenue_schedule",
                data=_mock_revenue_schedule(store_id, week_start),
                reasoning=f"数据库查询失败，降级为mock数据: {exc}",
                confidence=0.60,
                agent_level=2,
                rollback_window_min=30,
            )

        savings = plan["summary"]
        return AgentResult(
            success=True,
            action="analyze_revenue_schedule",
            data=plan,
            reasoning=(
                f"营收驱动排班分析完成，"
                f"周期{plan['week_start']}~{plan['week_end']}，"
                f"预计节省{savings['savings_fen']}分（{savings['savings_pct']}%）"
            ),
            confidence=0.85,
            agent_level=2,
            rollback_window_min=30,
        )

    async def _apply_optimal_plan(self, params: dict[str, Any]) -> AgentResult:
        """将营收驱动最优排班写入 unified_schedules（status=draft）。

        Level 2 自治：自动生成draft排班 + 30分钟回滚窗口。
        """
        store_id = self._store_scope(params)
        if not store_id:
            return AgentResult(
                success=False,
                action="apply_optimal_plan",
                error="缺少 store_id",
            )

        operator_id = params.get("operator_id", "agent:workforce_planner")
        week_start_str = params.get("week_start")
        if week_start_str:
            try:
                week_start = date.fromisoformat(str(week_start_str))
            except ValueError:
                return AgentResult(
                    success=False,
                    action="apply_optimal_plan",
                    error=f"无效的 week_start: {week_start_str}",
                )
        else:
            today = date.today()
            days_to_monday = (7 - today.weekday()) % 7 or 7
            week_start = today + timedelta(days=days_to_monday)

        if not self._db:
            return AgentResult(
                success=False,
                action="apply_optimal_plan",
                error="无数据库连接，无法写入排班草稿",
            )

        from services.revenue_schedule_service import RevenueScheduleService

        svc = RevenueScheduleService()
        try:
            result = await svc.apply_plan_as_draft(
                self._db,
                self.tenant_id,
                store_id,
                week_start,
                operator_id,
            )
        except (OperationalError, ProgrammingError) as exc:
            logger.error(
                "workforce_apply_plan_failed",
                error=str(exc),
                tenant_id=self.tenant_id,
                exc_info=True,
            )
            return AgentResult(
                success=False,
                action="apply_optimal_plan",
                error=f"写入排班草稿失败: {exc}",
            )

        rollback_id = f"rev-sched-{store_id}-{week_start.isoformat()}"
        return AgentResult(
            success=True,
            action="apply_optimal_plan",
            data=result,
            reasoning=(
                f"已写入{result['inserted_count']}条排班草稿，"
                f"状态=draft，30分钟内可回滚"
            ),
            confidence=0.88,
            agent_level=2,
            rollback_window_min=30,
            rollback_id=rollback_id,
        )


# ── 营收驱动排班 mock 数据 ──────────────────────────────────────────────────────


def _mock_revenue_schedule(store_id: str, week_start: date) -> dict[str, Any]:
    """营收驱动排班 mock 数据（基于长沙中型门店典型值）。"""
    daily_plans = []
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    mock_slots_base = [
        ("early_morning", "早班前", "06:00", "09:00", 15000),
        ("lunch_peak", "午高峰", "11:00", "13:30", 120000),
        ("lunch_valley", "午低谷", "13:30", "17:00", 25000),
        ("dinner_peak", "晚高峰", "17:00", "20:30", 145000),
        ("dinner_valley", "晚低谷", "20:30", "22:00", 28000),
        ("night", "夜班", "22:00", "02:00", 12000),
    ]
    weekday_factors = [1.0, 0.95, 0.95, 1.0, 1.15, 1.30, 1.25]

    for d in range(7):
        target = week_start + timedelta(days=d)
        factor = weekday_factors[d]
        slots = []
        for key, name, st, et, base_rev in mock_slots_base:
            rev = int(base_rev * factor)
            # 简化：每4万营收需1人（前厅）
            optimal = {
                "前厅": max(1, round(rev / 40000)),
                "后厨": max(1, round(rev / 50000)),
                "收银": 1,
                "清洁": 1 if key in ("lunch_peak", "dinner_peak") else 0,
            }
            current = {
                "前厅": max(1, optimal["前厅"] - (1 if d % 3 == 0 else 0)),
                "后厨": optimal["后厨"],
                "收银": 1,
                "清洁": 0,
            }
            delta = {}
            for pos in optimal:
                diff = optimal[pos] - current.get(pos, 0)
                if diff != 0:
                    delta[pos] = diff
            slots.append({
                "slot_key": key,
                "slot_name": name,
                "start_time": st,
                "end_time": et,
                "predicted_revenue_fen": rev,
                "optimal_staff": optimal,
                "current_staff": current,
                "delta": delta,
                "suggested_employees": [],
            })
        daily_plans.append({
            "date": target.isoformat(),
            "weekday": d,
            "weekday_name": weekday_names[d],
            "slots": slots,
        })

    return {
        "store_id": store_id,
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "daily_plans": daily_plans,
        "summary": {
            "total_labor_cost_current_fen": 320000,
            "total_labor_cost_optimal_fen": 295000,
            "savings_fen": 25000,
            "savings_pct": 7.8,
        },
        "employee_count": 10,
    }
