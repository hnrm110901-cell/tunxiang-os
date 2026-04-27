"""
人效指标体系 -- 纯函数实现（无 DB 依赖）

参考商龙i人事5大核心人效指标，面向餐饮连锁行业：
1. 人力成本占比 (labor_cost_ratio)
2. 人均贡献产值 (revenue_per_capita)
3. 人时营业额 (revenue_per_hour)
4. 人时待客数 (guests_per_hour)
5. 工作有效性 (work_effectiveness)

金额单位统一为"分"（fen），与项目其余部分保持一致。
"""

from __future__ import annotations

from typing import Any, Dict, List

# ── 行业基准值（餐饮行业标准） ─────────────────────────────────
INDUSTRY_BENCHMARKS: Dict[str, Dict[str, Any]] = {
    "labor_cost_ratio": {
        "min": 0.20,
        "max": 0.30,
        "target": 0.25,
        "unit": "ratio",
        "label": "人力成本占比",
    },
    "revenue_per_capita_fen": {
        "min": 2_500_000,
        "target": 3_500_000,
        "unit": "fen/month",
        "label": "人均贡献产值",
    },
    "revenue_per_hour_fen": {
        "min": 10_000,
        "target": 15_000,
        "unit": "fen/hour",
        "label": "人时营业额",
    },
    "guests_per_hour": {
        "min": 1.0,
        "target": 1.5,
        "unit": "人/hour",
        "label": "人时待客数",
    },
    "work_effectiveness_pct": {
        "min": 70,
        "target": 80,
        "unit": "%",
        "label": "工作有效性",
    },
}


# ── 状态判定工具 ───────────────────────────────────────────────


def _rate_status_higher_better(value: float, benchmark: Dict[str, Any]) -> str:
    """值越高越好的指标状态判定（人均产值、人时营业额、人时待客数、工作有效性）。"""
    target = benchmark["target"]
    low = benchmark["min"]
    if value >= target:
        return "excellent"
    if value >= (target + low) / 2:
        return "good"
    if value >= low:
        return "warning"
    return "critical"


def _rate_status_ratio(value: float, benchmark: Dict[str, Any]) -> str:
    """人力成本占比状态判定：越低越好，但不能低得不合理（可能人手不足）。"""
    target = benchmark["target"]
    upper = benchmark["max"]
    lower = benchmark["min"]
    if value <= target:
        return "excellent"
    if value <= (target + upper) / 2:
        return "good"
    if value <= upper:
        return "warning"
    return "critical"


# ── 五大指标计算 ───────────────────────────────────────────────


def compute_labor_cost_ratio(total_labor_fen: int, total_revenue_fen: int) -> dict:
    """人力成本占比 = 人力总成本 / 总营收。"""
    if total_revenue_fen <= 0:
        return {
            "value": 0.0,
            "benchmark": {
                "min": INDUSTRY_BENCHMARKS["labor_cost_ratio"]["min"],
                "target": INDUSTRY_BENCHMARKS["labor_cost_ratio"]["target"],
                "max": INDUSTRY_BENCHMARKS["labor_cost_ratio"]["max"],
            },
            "status": "critical",
            "gap": 0.0,
        }
    value = total_labor_fen / total_revenue_fen
    bench = INDUSTRY_BENCHMARKS["labor_cost_ratio"]
    status = _rate_status_ratio(value, bench)
    gap = round(value - bench["target"], 4)
    return {
        "value": round(value, 4),
        "benchmark": {"min": bench["min"], "target": bench["target"], "max": bench["max"]},
        "status": status,
        "gap": gap,
    }


def compute_revenue_per_capita(total_revenue_fen: int, headcount: int) -> dict:
    """人均贡献产值 = 总营收 / 人数（fen/month）。"""
    if headcount <= 0:
        return {
            "value": 0,
            "benchmark": {
                "min": INDUSTRY_BENCHMARKS["revenue_per_capita_fen"]["min"],
                "target": INDUSTRY_BENCHMARKS["revenue_per_capita_fen"]["target"],
            },
            "status": "critical",
            "gap": 0,
        }
    value = total_revenue_fen / headcount
    bench = INDUSTRY_BENCHMARKS["revenue_per_capita_fen"]
    status = _rate_status_higher_better(value, bench)
    gap = round(value - bench["target"])
    return {
        "value": round(value),
        "benchmark": {"min": bench["min"], "target": bench["target"]},
        "status": status,
        "gap": gap,
    }


def compute_revenue_per_hour(total_revenue_fen: int, total_work_hours: float) -> dict:
    """人时营业额 = 总营收 / 总工时（fen/hour）。"""
    if total_work_hours <= 0:
        return {
            "value": 0,
            "benchmark": {
                "min": INDUSTRY_BENCHMARKS["revenue_per_hour_fen"]["min"],
                "target": INDUSTRY_BENCHMARKS["revenue_per_hour_fen"]["target"],
            },
            "status": "critical",
            "gap": 0,
        }
    value = total_revenue_fen / total_work_hours
    bench = INDUSTRY_BENCHMARKS["revenue_per_hour_fen"]
    status = _rate_status_higher_better(value, bench)
    gap = round(value - bench["target"])
    return {
        "value": round(value),
        "benchmark": {"min": bench["min"], "target": bench["target"]},
        "status": status,
        "gap": gap,
    }


def compute_guests_per_hour(total_guests: int, total_work_hours: float) -> dict:
    """人时待客数 = 接待顾客总数 / 总工时（人/hour）。"""
    if total_work_hours <= 0:
        return {
            "value": 0.0,
            "benchmark": {
                "min": INDUSTRY_BENCHMARKS["guests_per_hour"]["min"],
                "target": INDUSTRY_BENCHMARKS["guests_per_hour"]["target"],
            },
            "status": "critical",
            "gap": 0.0,
        }
    value = total_guests / total_work_hours
    bench = INDUSTRY_BENCHMARKS["guests_per_hour"]
    status = _rate_status_higher_better(value, bench)
    gap = round(value - bench["target"], 2)
    return {
        "value": round(value, 2),
        "benchmark": {"min": bench["min"], "target": bench["target"]},
        "status": status,
        "gap": gap,
    }


def compute_work_effectiveness(productive_hours: float, total_hours: float) -> dict:
    """工作有效性 = 有效工时 / 总工时 * 100（%）。"""
    if total_hours <= 0:
        return {
            "value": 0.0,
            "benchmark": {
                "min": INDUSTRY_BENCHMARKS["work_effectiveness_pct"]["min"],
                "target": INDUSTRY_BENCHMARKS["work_effectiveness_pct"]["target"],
            },
            "status": "critical",
            "gap": 0.0,
        }
    value = (productive_hours / total_hours) * 100
    bench = INDUSTRY_BENCHMARKS["work_effectiveness_pct"]
    status = _rate_status_higher_better(value, bench)
    gap = round(value - bench["target"], 2)
    return {
        "value": round(value, 2),
        "benchmark": {"min": bench["min"], "target": bench["target"]},
        "status": status,
        "gap": gap,
    }


# ── 综合评分 ───────────────────────────────────────────────────

_STATUS_SCORES = {"excellent": 100, "good": 75, "warning": 50, "critical": 25}


def compute_store_efficiency(store_data: dict) -> dict:
    """计算门店完整人效报告（5指标 + 综合评分 + 预警）。

    store_data 字段:
        store_id, store_name,
        total_labor_fen, total_revenue_fen, headcount,
        total_work_hours, total_guests,
        productive_hours, total_hours
    """
    indicators = {
        "labor_cost_ratio": compute_labor_cost_ratio(
            store_data.get("total_labor_fen", 0),
            store_data.get("total_revenue_fen", 0),
        ),
        "revenue_per_capita": compute_revenue_per_capita(
            store_data.get("total_revenue_fen", 0),
            store_data.get("headcount", 0),
        ),
        "revenue_per_hour": compute_revenue_per_hour(
            store_data.get("total_revenue_fen", 0),
            store_data.get("total_work_hours", 0),
        ),
        "guests_per_hour": compute_guests_per_hour(
            store_data.get("total_guests", 0),
            store_data.get("total_work_hours", 0),
        ),
        "work_effectiveness": compute_work_effectiveness(
            store_data.get("productive_hours", 0),
            store_data.get("total_hours", 0),
        ),
    }

    # 综合评分：5 个指标状态得分的加权平均（当前等权）
    weights = {
        "labor_cost_ratio": 0.25,
        "revenue_per_capita": 0.20,
        "revenue_per_hour": 0.20,
        "guests_per_hour": 0.15,
        "work_effectiveness": 0.20,
    }
    total_score = sum(_STATUS_SCORES[ind["status"]] * weights[key] for key, ind in indicators.items())
    total_score = round(total_score, 1)

    if total_score >= 90:
        overall_status = "excellent"
    elif total_score >= 70:
        overall_status = "good"
    elif total_score >= 50:
        overall_status = "warning"
    else:
        overall_status = "critical"

    alerts = generate_efficiency_alerts(indicators)

    return {
        "store_id": store_data.get("store_id", ""),
        "store_name": store_data.get("store_name", ""),
        "indicators": indicators,
        "overall_score": total_score,
        "overall_status": overall_status,
        "alerts": alerts,
    }


# ── 多门店对比 ─────────────────────────────────────────────────


def compare_stores(stores_data: List[dict]) -> dict:
    """多门店人效对比排名。返回按综合评分降序的排名列表。"""
    results: List[dict] = []
    for sd in stores_data:
        report = compute_store_efficiency(sd)
        results.append(
            {
                "store_id": report["store_id"],
                "store_name": report["store_name"],
                "overall_score": report["overall_score"],
                "overall_status": report["overall_status"],
                "indicators": report["indicators"],
            }
        )
    results.sort(key=lambda r: r["overall_score"], reverse=True)
    for rank, r in enumerate(results, 1):
        r["rank"] = rank
    return {
        "total_stores": len(results),
        "rankings": results,
    }


# ── 预警生成 ───────────────────────────────────────────────────

_INDICATOR_LABELS: Dict[str, str] = {
    "labor_cost_ratio": "人力成本占比",
    "revenue_per_capita": "人均贡献产值",
    "revenue_per_hour": "人时营业额",
    "guests_per_hour": "人时待客数",
    "work_effectiveness": "工作有效性",
}


def generate_efficiency_alerts(indicators_or_store: dict) -> List[dict]:
    """生成人效预警列表。

    接受 indicators dict 或完整的 store_efficiency dict（含 indicators 字段）。
    """
    # 兼容两种入参
    if "indicators" in indicators_or_store:
        indicators = indicators_or_store["indicators"]
    else:
        indicators = indicators_or_store

    alerts: List[dict] = []
    for key, ind in indicators.items():
        if ind["status"] in ("warning", "critical"):
            level = "high" if ind["status"] == "critical" else "medium"
            label = _INDICATOR_LABELS.get(key, key)
            alerts.append(
                {
                    "indicator": key,
                    "label": label,
                    "level": level,
                    "status": ind["status"],
                    "value": ind["value"],
                    "gap": ind["gap"],
                    "message": f"{label}{'严重不达标' if level == 'high' else '需要关注'}，"
                    f"当前值 {ind['value']}，与目标差距 {ind['gap']}",
                }
            )
    # 按严重程度排序
    priority = {"high": 0, "medium": 1}
    alerts.sort(key=lambda a: priority.get(a["level"], 9))
    return alerts


# ── 多角色看板 ─────────────────────────────────────────────────


def get_boss_view(brand_data: dict) -> dict:
    """老板看：品牌整体人效 + 门店排名 + 成本趋势。

    brand_data 字段:
        brand_id, brand_name,
        stores: list[store_data],          # 各门店的原始数据
        monthly_labor_fen: list[int],       # 最近N月人力成本（用于趋势）
        monthly_revenue_fen: list[int],     # 最近N月营收（用于趋势）
    """
    stores = brand_data.get("stores", [])
    comparison = compare_stores(stores)

    # 品牌汇总
    total_labor = sum(s.get("total_labor_fen", 0) for s in stores)
    total_revenue = sum(s.get("total_revenue_fen", 0) for s in stores)
    total_headcount = sum(s.get("headcount", 0) for s in stores)

    brand_ratio = compute_labor_cost_ratio(total_labor, total_revenue)
    brand_per_capita = compute_revenue_per_capita(total_revenue, total_headcount)

    # 成本趋势
    monthly_labor = brand_data.get("monthly_labor_fen", [])
    monthly_revenue = brand_data.get("monthly_revenue_fen", [])
    cost_trend: List[dict] = []
    for i in range(min(len(monthly_labor), len(monthly_revenue))):
        ratio = monthly_labor[i] / monthly_revenue[i] if monthly_revenue[i] > 0 else 0.0
        cost_trend.append(
            {
                "month_index": i,
                "labor_fen": monthly_labor[i],
                "revenue_fen": monthly_revenue[i],
                "ratio": round(ratio, 4),
            }
        )

    return {
        "role": "boss",
        "brand_id": brand_data.get("brand_id", ""),
        "brand_name": brand_data.get("brand_name", ""),
        "brand_summary": {
            "total_labor_fen": total_labor,
            "total_revenue_fen": total_revenue,
            "total_headcount": total_headcount,
            "labor_cost_ratio": brand_ratio,
            "revenue_per_capita": brand_per_capita,
        },
        "store_rankings": comparison["rankings"],
        "cost_trend": cost_trend,
    }


def get_hr_view(brand_data: dict) -> dict:
    """HR看：人员编制 + 离职率 + 招聘需求 + 薪酬分析。

    brand_data 额外字段:
        total_headcount, total_positions,
        resignations_this_month, avg_tenure_months,
        open_positions, avg_salary_fen,
        stores: list[store_data]
    """
    stores = brand_data.get("stores", [])
    total_hc = brand_data.get("total_headcount", 0)
    total_pos = brand_data.get("total_positions", 0)
    resignations = brand_data.get("resignations_this_month", 0)

    fill_rate = total_hc / total_pos if total_pos > 0 else 0.0
    turnover_rate = resignations / total_hc if total_hc > 0 else 0.0

    # 各门店人效预警汇总
    all_alerts: List[dict] = []
    for sd in stores:
        report = compute_store_efficiency(sd)
        for alert in report["alerts"]:
            alert["store_id"] = sd.get("store_id", "")
            alert["store_name"] = sd.get("store_name", "")
            all_alerts.append(alert)

    return {
        "role": "hr",
        "staffing": {
            "total_headcount": total_hc,
            "total_positions": total_pos,
            "fill_rate": round(fill_rate, 4),
            "open_positions": brand_data.get("open_positions", total_pos - total_hc),
        },
        "turnover": {
            "resignations_this_month": resignations,
            "turnover_rate": round(turnover_rate, 4),
            "avg_tenure_months": brand_data.get("avg_tenure_months", 0),
        },
        "compensation": {
            "avg_salary_fen": brand_data.get("avg_salary_fen", 0),
        },
        "alerts": all_alerts,
    }


def get_manager_view(store_data: dict) -> dict:
    """店长看：本店人效 + 排班优化建议 + 员工绩效。

    store_data 额外字段:
        employees: list[dict]   # 员工绩效列表 {emp_id, emp_name, hours, revenue_fen, guests}
        peak_hours: list[int]   # 高峰时段 (0-23)
        scheduled_hours: float  # 已排班总工时
        required_hours: float   # 需求总工时
    """
    report = compute_store_efficiency(store_data)

    # 排班优化建议
    scheduled = store_data.get("scheduled_hours", 0)
    required = store_data.get("required_hours", 0)
    scheduling_suggestions: List[str] = []
    if required > 0:
        utilization = scheduled / required
        if utilization > 1.1:
            scheduling_suggestions.append(f"排班工时超出需求 {round((utilization - 1) * 100)}%，建议精简排班")
        elif utilization < 0.9:
            scheduling_suggestions.append(f"排班工时不足需求 {round((1 - utilization) * 100)}%，建议增加人手")

    peak_hours = store_data.get("peak_hours", [])
    if peak_hours:
        scheduling_suggestions.append(f"高峰时段 {peak_hours}，建议集中排班")

    # 员工绩效排名
    employees = store_data.get("employees", [])
    emp_performance: List[dict] = []
    for emp in employees:
        hours = emp.get("hours", 0)
        rev = emp.get("revenue_fen", 0)
        rph = round(rev / hours) if hours > 0 else 0
        emp_performance.append(
            {
                "emp_id": emp.get("emp_id", ""),
                "emp_name": emp.get("emp_name", ""),
                "hours": hours,
                "revenue_fen": rev,
                "revenue_per_hour_fen": rph,
                "guests": emp.get("guests", 0),
            }
        )
    emp_performance.sort(key=lambda e: e["revenue_per_hour_fen"], reverse=True)

    return {
        "role": "manager",
        "store_id": report["store_id"],
        "store_name": report["store_name"],
        "efficiency_report": report,
        "scheduling": {
            "scheduled_hours": scheduled,
            "required_hours": required,
            "suggestions": scheduling_suggestions,
        },
        "employee_performance": emp_performance,
    }


def get_staff_view(employee_data: dict) -> dict:
    """员工看：我的绩效 + 我的考勤 + 我的工资。

    employee_data 字段:
        emp_id, emp_name,
        hours_worked, revenue_fen, guests_served,
        attendance: {present_days, absent_days, late_count, early_leave_count},
        salary: {base_fen, commission_fen, bonus_fen, deduction_fen, net_fen}
    """
    hours = employee_data.get("hours_worked", 0)
    revenue = employee_data.get("revenue_fen", 0)
    guests = employee_data.get("guests_served", 0)

    my_rph = round(revenue / hours) if hours > 0 else 0
    my_gph = round(guests / hours, 2) if hours > 0 else 0.0

    bench_rph = INDUSTRY_BENCHMARKS["revenue_per_hour_fen"]
    bench_gph = INDUSTRY_BENCHMARKS["guests_per_hour"]

    rph_status = _rate_status_higher_better(my_rph, bench_rph)
    gph_status = _rate_status_higher_better(my_gph, bench_gph)

    attendance = employee_data.get("attendance", {})
    salary = employee_data.get("salary", {})

    return {
        "role": "staff",
        "emp_id": employee_data.get("emp_id", ""),
        "emp_name": employee_data.get("emp_name", ""),
        "performance": {
            "hours_worked": hours,
            "revenue_fen": revenue,
            "guests_served": guests,
            "revenue_per_hour_fen": my_rph,
            "revenue_per_hour_status": rph_status,
            "guests_per_hour": my_gph,
            "guests_per_hour_status": gph_status,
        },
        "attendance": {
            "present_days": attendance.get("present_days", 0),
            "absent_days": attendance.get("absent_days", 0),
            "late_count": attendance.get("late_count", 0),
            "early_leave_count": attendance.get("early_leave_count", 0),
        },
        "salary": {
            "base_fen": salary.get("base_fen", 0),
            "commission_fen": salary.get("commission_fen", 0),
            "bonus_fen": salary.get("bonus_fen", 0),
            "deduction_fen": salary.get("deduction_fen", 0),
            "net_fen": salary.get("net_fen", 0),
        },
    }
