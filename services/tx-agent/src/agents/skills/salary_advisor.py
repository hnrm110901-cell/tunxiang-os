"""屯象OS tx-agent AI 薪酬顾问 Agent：薪资推荐、离职风险预测、调薪方案优化。"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger(__name__)

SALARY_BENCHMARKS: dict[tuple[str, str], dict[str, int]] = {
    ("changsha", "waiter"): {"p25": 350000, "p50": 420000, "p75": 500000},
    ("changsha", "chef"): {"p25": 500000, "p50": 650000, "p75": 800000},
    ("changsha", "manager"): {"p25": 600000, "p50": 800000, "p75": 1000000},
    ("changsha", "cashier"): {"p25": 330000, "p50": 400000, "p75": 480000},
    ("beijing", "waiter"): {"p25": 450000, "p50": 550000, "p75": 680000},
    ("beijing", "chef"): {"p25": 650000, "p50": 850000, "p75": 1050000},
    ("beijing", "manager"): {"p25": 800000, "p50": 1050000, "p75": 1300000},
    ("shanghai", "waiter"): {"p25": 480000, "p50": 580000, "p75": 700000},
    ("shanghai", "chef"): {"p25": 680000, "p50": 880000, "p75": 1100000},
    ("shanghai", "manager"): {"p25": 850000, "p50": 1100000, "p75": 1350000},
}

_CITY_ALIASES: dict[str, str] = {
    "长沙": "changsha",
    "changsha": "changsha",
    "北京": "beijing",
    "beijing": "beijing",
    "上海": "shanghai",
    "shanghai": "shanghai",
}

_POSITION_ALIASES: dict[str, str] = {
    "waiter": "waiter",
    "服务员": "waiter",
    "chef": "chef",
    "厨师": "chef",
    "manager": "manager",
    "店长": "manager",
    "经理": "manager",
    "cashier": "cashier",
    "收银": "cashier",
    "收银员": "cashier",
}

_CITY_LABEL: dict[str, str] = {
    "changsha": "长沙",
    "beijing": "北京",
    "shanghai": "上海",
}

_POSITION_LABEL: dict[str, str] = {
    "waiter": "服务员",
    "chef": "厨师",
    "manager": "店长",
    "cashier": "收银员",
}


def _normalize_city(raw: str) -> str:
    s = str(raw).strip()
    if s.lower() in _CITY_ALIASES:
        return _CITY_ALIASES[s.lower()]
    return _CITY_ALIASES.get(s, "changsha")


def _normalize_position(raw: str) -> str:
    s = str(raw).strip().lower()
    if s in _POSITION_ALIASES:
        return _POSITION_ALIASES[s]
    return _POSITION_ALIASES.get(str(raw).strip(), "waiter")


def _benchmark_for(city_key: str, pos_key: str) -> dict[str, int]:
    key = (city_key, pos_key)
    if key in SALARY_BENCHMARKS:
        return SALARY_BENCHMARKS[key]
    fallback = (city_key, "waiter")
    if fallback in SALARY_BENCHMARKS:
        return SALARY_BENCHMARKS[fallback]
    return SALARY_BENCHMARKS[("changsha", "waiter")]


def _seniority_factor(months: int) -> float:
    if months <= 12:
        return 0.90
    if months <= 36:
        return 1.00
    if months <= 60:
        return 1.10
    return 1.15


def _performance_factor(avg_score: float) -> float:
    if avg_score < 60:
        return 0.90
    if avg_score < 80:
        return 1.00
    if avg_score < 90:
        return 1.05
    return 1.10


def _risk_level(score: int) -> str:
    if score <= 30:
        return "low"
    if score <= 60:
        return "medium"
    if score <= 80:
        return "high"
    return "critical"


def _weighted_risk(dimensions: dict[str, int]) -> int:
    w = (
        0.30 * dimensions["salary_competitiveness"]
        + 0.20 * dimensions["performance_trend"]
        + 0.20 * dimensions["attendance_stability"]
        + 0.15 * dimensions["seniority"]
        + 0.15 * dimensions["growth_potential"]
    )
    return int(round(min(100, max(0, w))))


def _parse_perf_score(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(str(raw).strip())
    except ValueError:
        return None


async def _load_employee_for_turnover(
    db: Any,
    tenant_id: str,
    employee_id: str,
) -> Optional[dict[str, Any]]:
    q = text("""
        SELECT e.id::text AS employee_id, e.emp_name, e.role,
               e.seniority_months, e.daily_wage_standard_fen, e.performance_score,
               e.grade_level, e.training_completed, e.hire_date,
               COALESCE(NULLIF(TRIM(LOWER(s.city)), ''), 'changsha') AS store_city,
               ps.total_salary_fen AS payroll_salary_fen,
               COALESCE(att.avg_work_hours, 0.0) AS avg_daily_work_hours,
               COALESCE(att.present_days, 0) AS attendance_present_days,
               COALESCE(att.total_days, 0) AS attendance_total_days
        FROM employees e
        JOIN stores s ON s.id = e.store_id AND s.tenant_id = e.tenant_id
        LEFT JOIN LATERAL (
            SELECT total_salary_fen
            FROM payroll_summaries ps2
            WHERE ps2.tenant_id = e.tenant_id
              AND ps2.employee_id = e.id
            ORDER BY ps2.period_year DESC, ps2.period_month DESC
            LIMIT 1
        ) ps ON true
        LEFT JOIN LATERAL (
            SELECT
                AVG(work_hours) AS avg_work_hours,
                COUNT(*) FILTER (WHERE status = 'present') AS present_days,
                COUNT(*) AS total_days
            FROM daily_attendance da
            WHERE da.tenant_id = e.tenant_id
              AND da.employee_id = e.id
              AND da.date >= CURRENT_DATE - INTERVAL '90 days'
        ) att ON true
        WHERE e.tenant_id = CAST(:tenant_id AS uuid)
          AND e.id = CAST(:employee_id AS uuid)
          AND e.is_deleted = false
          AND COALESCE(e.is_active, true) = true
        LIMIT 1
    """)
    try:
        result = await db.execute(q, {"tenant_id": tenant_id, "employee_id": employee_id})
        row = result.mappings().first()
        return dict(row) if row else None
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(
            "salary_advisor_turnover_db_failed",
            employee_id=employee_id,
            error=str(exc),
        )
        return None


def _build_turnover_from_row(row: dict[str, Any]) -> dict[str, Any]:
    city_key = _normalize_city(row.get("store_city") or "changsha")
    role_key = _normalize_position(row.get("role") or "waiter")
    bench = _benchmark_for(city_key, role_key)
    p50 = bench["p50"]

    # Prefer payroll_summaries total_salary_fen; fall back to daily_wage * 26
    payroll_sal = row.get("payroll_salary_fen")
    daily = row.get("daily_wage_standard_fen")
    monthly_est: Optional[int] = None
    if payroll_sal is not None and int(payroll_sal) > 0:
        monthly_est = int(payroll_sal)
    elif daily is not None and int(daily) > 0:
        monthly_est = int(daily) * 26

    if monthly_est is None:
        sal_score = 55
        sal_detail = "缺少薪资记录，按中等竞争力估算"
    else:
        ratio = monthly_est / max(1, p50)
        if ratio < 0.85:
            sal_score = 78
            sal_detail = f"月薪低于市场P50约 {int((1 - ratio) * 100)}%"
        elif ratio < 1.0:
            sal_score = 62
            sal_detail = "略低于市场P50"
        elif ratio <= 1.15:
            sal_score = 38
            sal_detail = "接近或略高于市场P50"
        else:
            sal_score = 22
            sal_detail = "薪酬竞争力较好"

    perf_val = _parse_perf_score(row.get("performance_score"))
    if perf_val is None:
        perf_score = 45
        perf_detail = "无有效绩效分，按稳定处理"
    elif perf_val < 60:
        perf_score = 82
        perf_detail = "绩效偏低，流失风险上升"
    elif perf_val < 75:
        perf_score = 58
        perf_detail = "绩效中等波动"
    else:
        perf_score = 36
        perf_detail = "近周期绩效稳定"

    # Derive attendance stability from real daily_attendance aggregates
    present_days = int(row.get("attendance_present_days") or 0)
    total_days = int(row.get("attendance_total_days") or 0)
    if total_days >= 10:
        att_rate = present_days / total_days
        if att_rate >= 0.95:
            attend_score = 18
            attend_detail = f"近90天出勤率{att_rate:.0%}，出勤优秀"
        elif att_rate >= 0.85:
            attend_score = 32
            attend_detail = f"近90天出勤率{att_rate:.0%}，出勤正常"
        elif att_rate >= 0.70:
            attend_score = 52
            attend_detail = f"近90天出勤率{att_rate:.0%}，出勤偏低"
        else:
            attend_score = 72
            attend_detail = f"近90天出勤率{att_rate:.0%}，出勤异常，流失风险上升"
    else:
        attend_score = 32
        attend_detail = "无足够考勤记录，按默认稳定度"

    sm = row.get("seniority_months")
    if sm is not None:
        months = int(sm)
    else:
        hd = row.get("hire_date")
        if hd is None:
            months = 12
        elif isinstance(hd, datetime):
            delta = date.today() - hd.date()
            months = max(0, delta.days // 30)
        elif isinstance(hd, date):
            delta = date.today() - hd
            months = max(0, delta.days // 30)
        else:
            months = 12

    if months < 6:
        sen_score = 72
        sen_detail = "工龄较短，稳定性风险偏高"
    elif months < 18:
        sen_score = 50
        sen_detail = f"工龄{months}个月，中等"
    elif months < 48:
        sen_score = 38
        sen_detail = f"工龄{months}个月，较稳定"
    else:
        sen_score = 28
        sen_detail = f"工龄{months}个月，相对稳定"

    training = row.get("training_completed") or []
    grade = row.get("grade_level")
    if grade and str(grade).strip():
        gr_score = 42
        gr_detail = "有职级记录，成长通道可见"
    elif training and len(training) > 0:
        gr_score = 48
        gr_detail = "有培训记录"
    else:
        gr_score = 64
        gr_detail = "最近无晋升/培训"

    dimension_scores = {
        "salary_competitiveness": {"score": sal_score, "detail": sal_detail},
        "performance_trend": {"score": perf_score, "detail": perf_detail},
        "attendance_stability": {"score": attend_score, "detail": attend_detail},
        "seniority": {"score": sen_score, "detail": sen_detail},
        "growth_potential": {"score": gr_score, "detail": gr_detail},
    }
    dims = {k: v["score"] for k, v in dimension_scores.items()}
    risk_score = _weighted_risk(dims)
    suggestions: list[str] = []
    if sal_score >= 55:
        suggestions.append("建议调薪至市场P50水平")
    if gr_score >= 55:
        suggestions.append("安排技能培训提升成长感")
    if sen_score >= 55 or perf_score >= 55:
        suggestions.append("考虑岗位晋升或横向调动")
    if not suggestions:
        suggestions.append("保持现有激励节奏，定期回顾薪酬竞争力")

    return {
        "risk_score": risk_score,
        "risk_level": _risk_level(risk_score),
        "dimension_scores": dimension_scores,
        "retention_suggestions": suggestions,
    }


async def _load_store_employees(
    db: Any,
    tenant_id: str,
    store_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    q = text("""
        SELECT e.id::text AS employee_id, e.emp_name, e.daily_wage_standard_fen,
               e.role, e.performance_score, e.seniority_months,
               ps.total_salary_fen AS payroll_salary_fen
        FROM employees e
        LEFT JOIN LATERAL (
            SELECT total_salary_fen
            FROM payroll_summaries ps2
            WHERE ps2.tenant_id = e.tenant_id
              AND ps2.employee_id = e.id
            ORDER BY ps2.period_year DESC, ps2.period_month DESC
            LIMIT 1
        ) ps ON true
        WHERE e.tenant_id = CAST(:tenant_id AS uuid)
          AND e.store_id = CAST(:store_id AS uuid)
          AND e.is_deleted = false
          AND COALESCE(e.is_active, true) = true
        ORDER BY e.updated_at DESC NULLS LAST
        LIMIT :lim
    """)
    try:
        result = await db.execute(
            q,
            {"tenant_id": tenant_id, "store_id": store_id, "lim": limit},
        )
        return [dict(r) for r in result.mappings()]
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(
            "salary_advisor_raise_plan_db_failed",
            store_id=store_id,
            error=str(exc),
        )
        return []


def _priority_for_raise_row(row: dict[str, Any]) -> tuple[str, float]:
    perf = _parse_perf_score(row.get("performance_score")) or 70.0
    months = int(row.get("seniority_months") or 18)
    score = 0.0
    if perf < 65:
        score += 2.0
    if months < 12:
        score += 1.5
    if months < 24:
        score += 0.5
    if perf >= 85:
        score += 1.0
    if score >= 2.5:
        return "high", score
    if score >= 1.2:
        return "medium", score
    return "low", score


def _allocate_raise_plans(
    budget_fen: int,
    candidates: list[dict[str, Any]],
) -> tuple[int, list[dict[str, Any]]]:
    total_w = sum(float(c["weight"]) for c in candidates)
    plans: list[dict[str, Any]] = []
    raw_parts: list[int] = []
    for c in candidates:
        part = int((budget_fen * float(c["weight"]) / total_w) // 1)
        raw_parts.append(part)
    drift = budget_fen - sum(raw_parts)
    if raw_parts:
        raw_parts[-1] += drift
    allocated = 0
    for c, raise_fen in zip(candidates, raw_parts, strict=True):
        raise_fen = max(0, raise_fen)
        cur = int(c["current_salary_fen"])
        plans.append(
            {
                "employee_id": str(c["employee_id"]),
                "emp_name": str(c["emp_name"]),
                "current_salary_fen": cur,
                "suggested_raise_fen": raise_fen,
                "new_salary_fen": cur + raise_fen,
                "priority": str(c["priority"]),
                "reason": str(c["reason"]),
            }
        )
        allocated += raise_fen
    return allocated, plans


class SalaryAdvisorAgent(SkillAgent):
    """基于岗位、区域、工龄与绩效输出薪酬建议与人力风险辅助决策。"""

    agent_id = "salary_advisor"
    agent_name = "AI薪酬顾问"
    description = "基于岗位/区域/工龄/绩效的AI薪酬建议、离职风险预测、调薪方案优化"
    priority = "P2"
    run_location = "cloud"

    # Sprint D1 / PR 批次 6：纯薪酬建议，HRD 最终决策，不直接操作三约束，豁免
    constraint_scope = set()
    constraint_waived_reason = (
        "AI 薪酬顾问输出建议和风险预测供 HRD 参考，由人工最终决策调薪，"
        "不直接操作毛利/食安/客户体验三条业务约束维度"
    )

    def get_supported_actions(self) -> list[str]:
        return [
            "recommend_salary",
            "predict_turnover_risk",
            "optimize_raise_plan",
            "budget_recommendation",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        if action == "recommend_salary":
            return await self._recommend_salary(params)
        if action == "predict_turnover_risk":
            return await self._predict_turnover_risk(params)
        if action == "optimize_raise_plan":
            return await self._optimize_raise_plan(params)
        if action == "budget_recommendation":
            return await self._budget_recommendation(params)
        return AgentResult(
            success=False,
            action=action,
            error=f"不支持的操作: {action}",
        )

    async def _recommend_salary(self, params: dict[str, Any]) -> AgentResult:
        required = ("employee_id", "position", "city", "seniority_months", "performance_avg")
        for key in required:
            if params.get(key) is None:
                return AgentResult(
                    success=False,
                    action="recommend_salary",
                    error=f"缺少参数: {key}",
                )
        try:
            seniority_months = int(params["seniority_months"])
        except (TypeError, ValueError):
            return AgentResult(
                success=False,
                action="recommend_salary",
                error="seniority_months 无效",
            )
        try:
            performance_avg = float(params["performance_avg"])
        except (TypeError, ValueError):
            return AgentResult(
                success=False,
                action="recommend_salary",
                error="performance_avg 无效",
            )

        city_key = _normalize_city(str(params["city"]))
        pos_key = _normalize_position(str(params["position"]))
        bench = _benchmark_for(city_key, pos_key)
        sf = _seniority_factor(seniority_months)
        pf = _performance_factor(performance_avg)
        p25, p50, p75 = bench["p25"], bench["p50"], bench["p75"]
        recommended = int(round(p50 * sf * pf))
        min_fen = int(round(p25 * sf * pf))
        max_fen = int(round(p75 * sf * pf))

        city_cn = _CITY_LABEL.get(city_key, city_key)
        pos_cn = _POSITION_LABEL.get(pos_key, pos_key)
        reasoning_text = (
            f"基于{city_cn}地区{pos_cn}岗位P50基准{p50}分/月，"
            f"工龄{seniority_months}个月调整系数{sf}，"
            f"绩效{performance_avg:g}分调整系数{pf}，建议月薪{recommended}分"
        )

        data = {
            "recommended_salary_fen": recommended,
            "salary_range": {"min_fen": min_fen, "max_fen": max_fen},
            "benchmark": {"p25": p25, "p50": p50, "p75": p75},
            "adjustments": {"seniority_factor": sf, "performance_factor": pf},
            "reasoning": reasoning_text,
        }
        return AgentResult(
            success=True,
            action="recommend_salary",
            data=data,
            reasoning=reasoning_text,
            confidence=0.78,
        )

    async def _predict_turnover_risk(self, params: dict[str, Any]) -> AgentResult:
        employee_id = params.get("employee_id")
        if not employee_id:
            return AgentResult(
                success=False,
                action="predict_turnover_risk",
                error="缺少参数: employee_id",
            )

        payload: dict[str, Any]
        if self._db is not None:
            try:
                uuid.UUID(str(employee_id))
            except ValueError:
                return AgentResult(
                    success=False,
                    action="predict_turnover_risk",
                    error="employee_id 不是合法 UUID",
                )
            row = await _load_employee_for_turnover(self._db, self.tenant_id, str(employee_id))
            if row:
                payload = _build_turnover_from_row(row)
                logger.info(
                    "salary_advisor_turnover_db",
                    employee_id=str(employee_id),
                    risk_level=payload["risk_level"],
                )
            else:
                return AgentResult(
                    success=False,
                    action="predict_turnover_risk",
                    error=f"未找到员工记录: {employee_id}",
                )
        else:
            return AgentResult(
                success=False,
                action="predict_turnover_risk",
                error="数据库连接不可用",
            )

        return AgentResult(
            success=True,
            action="predict_turnover_risk",
            data=payload,
            reasoning=f"离职风险 {payload['risk_level']}（{payload['risk_score']} 分）",
            confidence=0.72,
        )

    async def _optimize_raise_plan(self, params: dict[str, Any]) -> AgentResult:
        store_id = params.get("store_id")
        budget_raw = params.get("budget_fen")
        month = params.get("month")
        if store_id is None or budget_raw is None or month is None:
            return AgentResult(
                success=False,
                action="optimize_raise_plan",
                error="缺少参数: store_id / budget_fen / month",
            )
        try:
            budget_fen = int(budget_raw)
        except (TypeError, ValueError):
            return AgentResult(
                success=False,
                action="optimize_raise_plan",
                error="budget_fen 无效",
            )
        if budget_fen <= 0:
            return AgentResult(
                success=False,
                action="optimize_raise_plan",
                error="budget_fen 必须为正整数",
            )

        if self._db is None:
            return AgentResult(
                success=False,
                action="optimize_raise_plan",
                error="数据库连接不可用",
            )

        try:
            uuid.UUID(str(store_id))
        except ValueError:
            return AgentResult(
                success=False,
                action="optimize_raise_plan",
                error="store_id 不是合法 UUID",
            )

        candidates: list[dict[str, Any]] = []
        rows = await _load_store_employees(self._db, self.tenant_id, str(store_id), 5)
        for r in rows:
            pr, wt = _priority_for_raise_row(r)
            # Prefer actual payroll record; fall back to daily_wage * 26
            payroll_sal = r.get("payroll_salary_fen")
            daily = r.get("daily_wage_standard_fen") or 0
            if payroll_sal is not None and int(payroll_sal) > 0:
                base_monthly = int(payroll_sal)
            elif int(daily) > 0:
                base_monthly = int(daily) * 26
            else:
                base_monthly = 400000
            candidates.append(
                {
                    "employee_id": r["employee_id"],
                    "emp_name": r.get("emp_name") or "员工",
                    "current_salary_fen": base_monthly,
                    "priority": pr,
                    "weight": 3.0 if pr == "high" else 2.0 if pr == "medium" else 1.0,
                    "reason": "按门店员工绩效与司龄综合排序分配预算",
                }
            )

        if not candidates:
            return AgentResult(
                success=False,
                action="optimize_raise_plan",
                error="未查询到门店员工数据",
            )

        candidates = candidates[:5]
        prio_order = {"high": 0, "medium": 1, "low": 2}
        candidates.sort(key=lambda x: (prio_order.get(str(x["priority"]), 9), -float(x["weight"])))

        allocated, plans = _allocate_raise_plans(budget_fen, candidates)
        data = {
            "budget_fen": budget_fen,
            "allocated_fen": allocated,
            "plans": plans,
        }
        return AgentResult(
            success=True,
            action="optimize_raise_plan",
            data=data,
            reasoning=f"{month} 在预算 {budget_fen} 分内完成 {len(plans)} 人调薪分配，已用 {allocated} 分",
            confidence=0.70,
        )

    # ── 功能6：门店健康度人力预算建议 ─────────────────────────────────────────

    # 行业基准：不同业态的人力成本率范围
    _LABOR_RATE_BENCHMARKS: dict[str, dict[str, float]] = {
        "正餐": {"p25": 0.25, "p50": 0.28, "p75": 0.30},
        "快餐": {"p25": 0.20, "p50": 0.22, "p75": 0.25},
        "火锅": {"p25": 0.22, "p50": 0.25, "p75": 0.28},
        "宴会": {"p25": 0.28, "p50": 0.30, "p75": 0.35},
        "default": {"p25": 0.23, "p50": 0.27, "p75": 0.32},
    }

    _POSITION_SALARY_BASELINE: dict[str, int] = {
        "manager": 800000,  # 8000元/月
        "chef": 650000,  # 6500元/月
        "waiter": 420000,  # 4200元/月
        "cashier": 400000,  # 4000元/月
        "head_chef": 1000000,  # 10000元/月
        "cleaner": 350000,  # 3500元/月
    }

    async def _budget_recommendation(self, params: dict[str, Any]) -> AgentResult:
        """门店人力预算建议

        基于门店P&L健康度自动计算最优人力预算：
        1. 从mv_store_pnl读取门店月P&L趋势
        2. 计算当前人力成本率 vs 行业基准
        3. 结合营收趋势预测下月人力预算
        4. 输出建议编制、薪资总额上限、差异与理由
        """
        store_id = params.get("store_id")
        month = params.get("month")
        cuisine_type = params.get("cuisine_type", "default")
        if not store_id or not month:
            return AgentResult(
                success=False,
                action="budget_recommendation",
                error="缺少参数: store_id / month",
            )

        # 读取P&L数据
        pnl_data = await self._load_store_pnl(store_id, month)
        current_staff = await self._load_current_staffing(store_id)

        # 行业基准
        bench = self._LABOR_RATE_BENCHMARKS.get(cuisine_type, self._LABOR_RATE_BENCHMARKS["default"])

        # 计算当前人力成本率
        current_revenue = pnl_data.get("avg_monthly_revenue_fen", 0)
        current_labor = pnl_data.get("avg_monthly_labor_fen", 0)
        current_rate = current_labor / current_revenue if current_revenue > 0 else 0.0
        revenue_trend = pnl_data.get("revenue_trend", "stable")

        # 预测下月营收
        if revenue_trend == "rising":
            predicted_revenue = int(current_revenue * 1.05)
        elif revenue_trend == "declining":
            predicted_revenue = int(current_revenue * 0.95)
        else:
            predicted_revenue = current_revenue

        # 计算建议人力预算上限（按P50基准）
        target_rate = bench["p50"]
        suggested_budget_fen = int(predicted_revenue * target_rate)

        # 按岗位分解建议编制
        position_plan = self._compute_position_plan(suggested_budget_fen, current_staff, predicted_revenue)

        # 生成差异和理由
        budget_diff = suggested_budget_fen - current_labor
        headcount_diff = sum(p["suggested_count"] for p in position_plan) - sum(
            p["current_count"] for p in position_plan
        )

        reasons: list[str] = []
        if current_rate > bench["p75"]:
            reasons.append(f"当前人力成本率{current_rate:.1%}超过行业P75({bench['p75']:.1%})，建议控制人力支出")
        elif current_rate < bench["p25"]:
            reasons.append(f"当前人力成本率{current_rate:.1%}低于行业P25({bench['p25']:.1%})，可能存在人手不足风险")
        else:
            reasons.append(f"当前人力成本率{current_rate:.1%}处于行业合理区间({bench['p25']:.1%}-{bench['p75']:.1%})")

        if revenue_trend == "rising":
            reasons.append("营收呈上升趋势，建议适当增加编制以保障服务质量")
        elif revenue_trend == "declining":
            reasons.append("营收呈下降趋势，建议优化排班减少闲时人力")

        data = {
            "store_id": store_id,
            "month": month,
            "cuisine_type": cuisine_type,
            "current_status": {
                "monthly_revenue_fen": current_revenue,
                "monthly_labor_fen": current_labor,
                "labor_cost_rate": round(current_rate, 4),
                "revenue_trend": revenue_trend,
            },
            "industry_benchmark": bench,
            "suggestion": {
                "target_labor_rate": target_rate,
                "suggested_budget_fen": suggested_budget_fen,
                "predicted_revenue_fen": predicted_revenue,
                "budget_diff_fen": budget_diff,
                "headcount_diff": headcount_diff,
                "action": "增编" if headcount_diff > 0 else "减编" if headcount_diff < 0 else "持平",
            },
            "position_plan": position_plan,
            "reasons": reasons,
            "ai_tag": "AI建议",
        }

        return AgentResult(
            success=True,
            action="budget_recommendation",
            data=data,
            reasoning="；".join(reasons),
            confidence=0.72,
        )

    async def _load_store_pnl(self, store_id: str, month: str) -> dict[str, Any]:
        """从mv_store_pnl加载P&L数据，降级为mock"""
        if self._db is not None:
            q = text("""
                SELECT COALESCE(AVG(revenue_fen), 0)::bigint AS avg_monthly_revenue_fen,
                       COALESCE(AVG(labor_cost_fen), 0)::bigint AS avg_monthly_labor_fen,
                       CASE
                         WHEN COUNT(*) >= 2 THEN
                           CASE WHEN (ARRAY_AGG(revenue_fen ORDER BY pnl_date DESC))[1]
                                   > (ARRAY_AGG(revenue_fen ORDER BY pnl_date DESC))[2]
                                THEN 'rising' ELSE 'declining' END
                         ELSE 'stable'
                       END AS revenue_trend
                FROM mv_store_pnl
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND store_id = CAST(:store_id AS uuid)
                  AND to_char(pnl_date, 'YYYY-MM') <= :month
                ORDER BY pnl_date DESC
                LIMIT 3
            """)
            try:
                result = await self._db.execute(
                    q,
                    {
                        "tenant_id": self.tenant_id,
                        "store_id": store_id,
                        "month": month,
                    },
                )
                row = result.mappings().first()
                if row:
                    return dict(row)
            except (OperationalError, ProgrammingError) as exc:
                logger.warning("budget_pnl_fallback", error=str(exc))

        # Mock降级
        return {
            "avg_monthly_revenue_fen": 35000000,  # 35万元
            "avg_monthly_labor_fen": 9800000,  # 9.8万元
            "revenue_trend": "stable",
        }

    async def _load_current_staffing(self, store_id: str) -> list[dict[str, Any]]:
        """加载当前门店编制情况，降级为mock"""
        if self._db is not None:
            q = text("""
                SELECT LOWER(COALESCE(role, 'waiter')) AS role,
                       COUNT(*) AS count
                FROM employees
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND store_id = CAST(:store_id AS uuid)
                  AND is_deleted = false
                  AND COALESCE(is_active, true) = true
                GROUP BY LOWER(COALESCE(role, 'waiter'))
            """)
            try:
                result = await self._db.execute(
                    q,
                    {
                        "tenant_id": self.tenant_id,
                        "store_id": store_id,
                    },
                )
                return [dict(r) for r in result.mappings()]
            except (OperationalError, ProgrammingError) as exc:
                logger.warning("budget_staffing_fallback", error=str(exc))

        return [
            {"role": "manager", "count": 1},
            {"role": "chef", "count": 4},
            {"role": "waiter", "count": 6},
            {"role": "cashier", "count": 2},
        ]

    def _compute_position_plan(
        self,
        budget_fen: int,
        current_staff: list[dict[str, Any]],
        predicted_revenue: int,
    ) -> list[dict[str, Any]]:
        """根据预算计算各岗位建议编制"""
        current_map: dict[str, int] = {}
        for s in current_staff:
            role = str(s.get("role", "waiter")).lower()
            current_map[role] = int(s.get("count", 0))

        # 按岗位比例分配预算
        role_weights = {
            "manager": 0.12,
            "head_chef": 0.15,
            "chef": 0.30,
            "waiter": 0.28,
            "cashier": 0.10,
            "cleaner": 0.05,
        }

        plan: list[dict[str, Any]] = []
        for role, weight in role_weights.items():
            role_budget = int(budget_fen * weight)
            baseline = self._POSITION_SALARY_BASELINE.get(role, 420000)
            suggested_count = max(1, role_budget // baseline) if role_budget > 0 else 0
            current_count = current_map.get(role, 0)
            diff = suggested_count - current_count

            plan.append(
                {
                    "role": role,
                    "role_label": _POSITION_LABEL.get(role, role),
                    "current_count": current_count,
                    "suggested_count": suggested_count,
                    "current_salary_fen": current_count * baseline,
                    "suggested_salary_fen": suggested_count * baseline,
                    "diff": diff,
                    "action": "增编" if diff > 0 else "减编" if diff < 0 else "持平",
                }
            )
        return plan
