"""人效指标体系测试 -- >=15 个测试用例

覆盖:
- 5 个指标各自的计算 + 基准对比
- 综合评分
- 多门店排名
- 预警生成
- 4 种角色看板
"""

import sys
import os

# 确保 src 目录在 import path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.labor_efficiency_service import (
    INDUSTRY_BENCHMARKS,
    compute_labor_cost_ratio,
    compute_revenue_per_capita,
    compute_revenue_per_hour,
    compute_guests_per_hour,
    compute_work_effectiveness,
    compute_store_efficiency,
    compare_stores,
    generate_efficiency_alerts,
    get_boss_view,
    get_hr_view,
    get_manager_view,
    get_staff_view,
)


# ── 辅助：构造门店数据 ────────────────────────────────────────

def _make_store(
    store_id: str = "s1",
    store_name: str = "测试门店",
    total_labor_fen: int = 250_000_00,
    total_revenue_fen: int = 1_000_000_00,
    headcount: int = 15,
    total_work_hours: float = 2400.0,
    total_guests: int = 3600,
    productive_hours: float = 2000.0,
    total_hours: float = 2400.0,
    **kwargs,
) -> dict:
    data = {
        "store_id": store_id,
        "store_name": store_name,
        "total_labor_fen": total_labor_fen,
        "total_revenue_fen": total_revenue_fen,
        "headcount": headcount,
        "total_work_hours": total_work_hours,
        "total_guests": total_guests,
        "productive_hours": productive_hours,
        "total_hours": total_hours,
    }
    data.update(kwargs)
    return data


# ── 1. 人力成本占比 ───────────────────────────────────────────

def test_labor_cost_ratio_excellent():
    """成本占比 20% -> excellent"""
    result = compute_labor_cost_ratio(200_000, 1_000_000)
    assert result["value"] == 0.2
    assert result["status"] == "excellent"
    assert result["gap"] < 0  # 低于目标是好事


def test_labor_cost_ratio_critical():
    """成本占比 50% -> critical"""
    result = compute_labor_cost_ratio(500_000, 1_000_000)
    assert result["value"] == 0.5
    assert result["status"] == "critical"


def test_labor_cost_ratio_zero_revenue():
    """营收为0时不崩溃"""
    result = compute_labor_cost_ratio(100_000, 0)
    assert result["status"] == "critical"
    assert result["value"] == 0.0


# ── 2. 人均贡献产值 ───────────────────────────────────────────

def test_revenue_per_capita_excellent():
    """人均 400万分 > 目标 350万分 -> excellent"""
    result = compute_revenue_per_capita(40_000_000, 10)
    assert result["value"] == 4_000_000
    assert result["status"] == "excellent"
    assert result["gap"] > 0


def test_revenue_per_capita_zero_headcount():
    """人数为0不崩溃"""
    result = compute_revenue_per_capita(10_000_000, 0)
    assert result["status"] == "critical"


# ── 3. 人时营业额 ─────────────────────────────────────────────

def test_revenue_per_hour_good():
    """人时 12500分 在 min-target 之间 -> good"""
    result = compute_revenue_per_hour(12_500_000, 1000.0)
    assert result["value"] == 12_500
    assert result["status"] == "good"


def test_revenue_per_hour_zero_hours():
    """工时为0不崩溃"""
    result = compute_revenue_per_hour(1_000_000, 0)
    assert result["status"] == "critical"


# ── 4. 人时待客数 ─────────────────────────────────────────────

def test_guests_per_hour_excellent():
    """2.0 人/小时 > 目标 1.5 -> excellent"""
    result = compute_guests_per_hour(2000, 1000.0)
    assert result["value"] == 2.0
    assert result["status"] == "excellent"


def test_guests_per_hour_warning():
    """1.1 人/小时 在 min(1.0) 和中间值(1.25) 之间 -> warning"""
    result = compute_guests_per_hour(1100, 1000.0)
    assert result["value"] == 1.1
    assert result["status"] == "warning"


# ── 5. 工作有效性 ─────────────────────────────────────────────

def test_work_effectiveness_excellent():
    """85% > 目标 80% -> excellent"""
    result = compute_work_effectiveness(85.0, 100.0)
    assert result["value"] == 85.0
    assert result["status"] == "excellent"


def test_work_effectiveness_critical():
    """50% < min 70% -> critical"""
    result = compute_work_effectiveness(50.0, 100.0)
    assert result["value"] == 50.0
    assert result["status"] == "critical"


# ── 6. 综合评分 ───────────────────────────────────────────────

def test_store_efficiency_overall_score():
    """综合评分应在 0-100 范围"""
    sd = _make_store()
    report = compute_store_efficiency(sd)
    assert 0 <= report["overall_score"] <= 100
    assert report["overall_status"] in ("excellent", "good", "warning", "critical")
    assert "indicators" in report
    assert len(report["indicators"]) == 5


def test_store_efficiency_excellent_store():
    """优秀门店综合评分应较高"""
    sd = _make_store(
        total_labor_fen=200_000_00,
        total_revenue_fen=1_500_000_00,
        headcount=10,
        total_work_hours=1600.0,
        total_guests=2800,
        productive_hours=1400.0,
        total_hours=1600.0,
    )
    report = compute_store_efficiency(sd)
    assert report["overall_score"] >= 70


# ── 7. 多门店排名 ─────────────────────────────────────────────

def test_compare_stores_ranking():
    """多门店排名按评分降序"""
    stores = [
        _make_store("s1", "差店", total_labor_fen=500_000_00, total_revenue_fen=500_000_00),
        _make_store("s2", "优店", total_labor_fen=100_000_00, total_revenue_fen=2_000_000_00),
        _make_store("s3", "中店", total_labor_fen=250_000_00, total_revenue_fen=1_000_000_00),
    ]
    result = compare_stores(stores)
    assert result["total_stores"] == 3
    rankings = result["rankings"]
    assert rankings[0]["rank"] == 1
    assert rankings[-1]["rank"] == 3
    # 分数降序
    scores = [r["overall_score"] for r in rankings]
    assert scores == sorted(scores, reverse=True)


# ── 8. 预警生成 ───────────────────────────────────────────────

def test_generate_alerts_for_critical_store():
    """差门店应生成预警"""
    sd = _make_store(
        total_labor_fen=500_000_00,
        total_revenue_fen=500_000_00,
        headcount=30,
        total_work_hours=4800.0,
        total_guests=2000,
        productive_hours=2400.0,
        total_hours=4800.0,
    )
    report = compute_store_efficiency(sd)
    alerts = report["alerts"]
    assert len(alerts) > 0
    # 预警应按严重程度排序
    levels = [a["level"] for a in alerts]
    if "high" in levels and "medium" in levels:
        assert levels.index("high") < levels.index("medium")


def test_generate_alerts_empty_for_excellent():
    """优秀门店不应有预警"""
    sd = _make_store(
        total_labor_fen=150_000_00,
        total_revenue_fen=2_000_000_00,
        headcount=5,
        total_work_hours=800.0,
        total_guests=1500,
        productive_hours=700.0,
        total_hours=800.0,
    )
    report = compute_store_efficiency(sd)
    alerts = report["alerts"]
    assert len(alerts) == 0


# ── 9-12. 四种角色看板 ────────────────────────────────────────

def test_boss_view():
    """老板看板包含品牌汇总、门店排名、成本趋势"""
    brand = {
        "brand_id": "b1",
        "brand_name": "测试品牌",
        "stores": [_make_store(f"s{i}", f"门店{i}") for i in range(3)],
        "monthly_labor_fen": [240_000_00, 250_000_00, 260_000_00],
        "monthly_revenue_fen": [950_000_00, 1_000_000_00, 1_050_000_00],
    }
    view = get_boss_view(brand)
    assert view["role"] == "boss"
    assert "brand_summary" in view
    assert "store_rankings" in view
    assert len(view["store_rankings"]) == 3
    assert "cost_trend" in view
    assert len(view["cost_trend"]) == 3


def test_hr_view():
    """HR看板包含编制、离职率、预警"""
    brand = {
        "brand_id": "b1",
        "brand_name": "测试品牌",
        "stores": [_make_store(f"s{i}", f"门店{i}") for i in range(2)],
        "total_headcount": 30,
        "total_positions": 35,
        "resignations_this_month": 2,
        "avg_tenure_months": 18,
        "open_positions": 5,
        "avg_salary_fen": 550_000,
    }
    view = get_hr_view(brand)
    assert view["role"] == "hr"
    assert view["staffing"]["fill_rate"] > 0
    assert view["turnover"]["turnover_rate"] > 0
    assert "compensation" in view


def test_manager_view():
    """店长看板包含人效报告、排班建议、员工绩效"""
    sd = _make_store(
        employees=[
            {"emp_id": "e1", "emp_name": "张三", "hours": 176, "revenue_fen": 3_000_000, "guests": 300},
            {"emp_id": "e2", "emp_name": "李四", "hours": 160, "revenue_fen": 2_000_000, "guests": 200},
        ],
        peak_hours=[11, 12, 18, 19],
        scheduled_hours=2400.0,
        required_hours=2000.0,
    )
    view = get_manager_view(sd)
    assert view["role"] == "manager"
    assert "efficiency_report" in view
    assert len(view["employee_performance"]) == 2
    # 员工按人时营业额降序
    perfs = view["employee_performance"]
    assert perfs[0]["revenue_per_hour_fen"] >= perfs[1]["revenue_per_hour_fen"]
    # 排班工时超出需求应有建议
    assert len(view["scheduling"]["suggestions"]) > 0


def test_staff_view():
    """员工看板包含绩效、考勤、工资"""
    emp = {
        "emp_id": "e1",
        "emp_name": "张三",
        "hours_worked": 176.0,
        "revenue_fen": 2_800_000,
        "guests_served": 280,
        "attendance": {"present_days": 22, "absent_days": 0, "late_count": 1, "early_leave_count": 0},
        "salary": {"base_fen": 400_000, "commission_fen": 80_000, "bonus_fen": 30_000, "deduction_fen": 5_000, "net_fen": 505_000},
    }
    view = get_staff_view(emp)
    assert view["role"] == "staff"
    assert view["performance"]["revenue_per_hour_fen"] > 0
    assert view["performance"]["guests_per_hour"] > 0
    assert view["attendance"]["present_days"] == 22
    assert view["salary"]["net_fen"] == 505_000
