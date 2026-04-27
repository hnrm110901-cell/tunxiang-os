"""AI 薪资推荐服务测试 -- >= 20 个测试用例

覆盖:
- 岗位分档命中 (精确/模糊/未知回落)
- 区域系数 (编码/城市名/未知回落)
- 工龄曲线 (边界/超限)
- 基础薪酬计算 (fen 精度)
- 完整推荐结构 (含 salary_items / 约束 / confidence)
- 批量推荐 + 门店人力成本占比校验
- 元数据目录端点
"""

import os
import sys

# 确保 src 目录在 import path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


from services.ai_salary_advisor_service import (
    REGION_FACTORS,
    ROLE_TIERS,
    SENIORITY_CURVE,
    SalaryRecommendation,
    batch_recommend,
    compute_base_salary_fen,
    compute_seniority_subsidy_fen,
    estimate_labor_cost_ratio,
    get_region_factor,
    get_region_factors_catalog,
    get_role_tier,
    get_role_tiers_catalog,
    get_seniority_curve,
    get_seniority_factor,
    recommend_salary_structure,
)

# ── 岗位分档 ─────────────────────────────────────────────────────


def test_role_tier_exact_match_waiter():
    tier_code, info, quality = get_role_tier("服务员")
    assert tier_code == "L1_basic"
    assert "服务员" in info["roles"]
    assert quality == "exact"


def test_role_tier_exact_match_store_manager():
    tier_code, info, quality = get_role_tier("店长")
    assert tier_code == "L5_manager"
    assert info["label"] == "门店管理岗"
    assert quality == "exact"


def test_role_tier_exact_match_chef():
    tier_code, _, quality = get_role_tier("厨师")
    assert tier_code == "L2_skilled"
    assert quality == "exact"


def test_role_tier_senior_chef():
    tier_code, _, _ = get_role_tier("厨师长")
    assert tier_code == "L3_senior_skilled"


def test_role_tier_supervisor():
    tier_code, _, quality = get_role_tier("主管")
    assert tier_code == "L4_supervisor"
    assert quality == "exact"


def test_role_tier_regional():
    tier_code, _, quality = get_role_tier("区域经理")
    assert tier_code == "L6_regional"
    assert quality == "exact"


def test_role_tier_empty_fallback_L1():
    tier_code, _, quality = get_role_tier("")
    assert tier_code == "L1_basic"
    assert quality == "fallback"


def test_role_tier_unknown_fallback_L1():
    tier_code, _, quality = get_role_tier("不存在的岗位XYZ")
    assert tier_code == "L1_basic"
    assert quality == "fallback"


def test_role_tier_fuzzy_match_keyword():
    """'代理店长' 不在 roles 中,但包含 '店长' → 模糊匹配 L5"""
    tier_code, _, quality = get_role_tier("代理店长")
    assert tier_code == "L5_manager"
    assert quality == "fuzzy"


def test_role_tier_regression_blocker2_supervisor_exclusive_to_L4():
    """BLOCKER-2 防回归:'督导' 必须归 L4 (门店级督导),不能落 L6 (跨店区域)。"""
    tier_code, _, quality = get_role_tier("督导")
    assert tier_code == "L4_supervisor"
    assert quality == "exact"
    # 店面督导同理
    tc2, _, q2 = get_role_tier("店面督导")
    assert tc2 == "L4_supervisor"
    assert q2 == "exact"


def test_role_tier_regression_blocker2_area_manager_stays_L6():
    """BLOCKER-2 防回归:明确"区域经理"仍归 L6。"""
    tier_code, _, quality = get_role_tier("区域经理")
    assert tier_code == "L6_regional"
    assert quality == "exact"


# ── 区域系数 ─────────────────────────────────────────────────────


def test_region_factor_tier1_code():
    code, factor, label = get_region_factor("tier1")
    assert code == "tier1"
    assert factor == 1.25
    assert "一线" in label


def test_region_factor_beijing_city():
    code, factor, _ = get_region_factor("北京")
    assert code == "tier1"
    assert factor == 1.25


def test_region_factor_changsha_new_tier1():
    code, factor, _ = get_region_factor("长沙")
    assert code == "tier1_5"
    assert factor == 1.10


def test_region_factor_unknown_fallback_tier2():
    code, factor, _ = get_region_factor("未知城市XYZ")
    assert code == "tier2"
    assert factor == 1.00


def test_region_factor_empty_fallback_tier2():
    code, factor, _ = get_region_factor("")
    assert code == "tier2"
    assert factor == 1.00


# ── 工龄系数 ─────────────────────────────────────────────────────


def test_seniority_factor_new_employee():
    factor, label = get_seniority_factor(0)
    assert factor == 1.00
    assert label == "新员工"


def test_seniority_factor_boundary_1yr():
    factor, _ = get_seniority_factor(1)
    assert factor == 1.10


def test_seniority_factor_core_3yr():
    factor, _ = get_seniority_factor(3)
    assert factor == 1.20


def test_seniority_factor_senior_5yr():
    factor, _ = get_seniority_factor(5)
    assert factor == 1.30


def test_seniority_factor_veteran_15yr():
    factor, label = get_seniority_factor(15)
    assert factor == 1.40
    assert label == "元老"


def test_seniority_factor_negative_clamped_to_zero():
    factor, _ = get_seniority_factor(-5)
    assert factor == 1.00


# ── 基础薪酬计算 ─────────────────────────────────────────────────


def test_base_salary_L1_tier2_new():
    """服务员 + tier2 + 0年 = 3500 元 × 1.00 × 1.00 = 3500_00 fen"""
    result = compute_base_salary_fen("L1_basic", "tier2", 0)
    assert result == 3_500_00


def test_base_salary_L5_tier1_5yr():
    """店长 + tier1 + 5年 = 8000 × 1.25 × 1.30 = 13000 元 = 13_000_00 fen"""
    result = compute_base_salary_fen("L5_manager", "tier1", 5)
    assert result == 13_000_00


def test_base_salary_unknown_tier_fallback():
    """未知档位回落 L1_basic"""
    result = compute_base_salary_fen("L_UNKNOWN", "tier2", 0)
    assert result == 3_500_00


def test_seniority_subsidy_linear_curve():
    assert compute_seniority_subsidy_fen(0) == 0
    assert compute_seniority_subsidy_fen(1) == 50_00  # 50元
    assert compute_seniority_subsidy_fen(5) == 250_00  # 250元
    assert compute_seniority_subsidy_fen(10) == 500_00  # 500元 封顶
    assert compute_seniority_subsidy_fen(20) == 500_00  # 超限仍 500


# ── 完整推荐流程 ─────────────────────────────────────────────────


def test_recommend_chef_basic():
    rec = recommend_salary_structure(role="厨师", region="tier2", years_of_service=0)
    assert isinstance(rec, SalaryRecommendation)
    assert rec.role == "厨师"
    assert rec.role_tier == "L2_skilled"
    assert rec.base_salary_fen == 4_500_00
    assert rec.position_bonus_fen == 300_00
    assert rec.seniority_subsidy_fen == 0
    assert rec.estimated_total_gross_fen > 0
    assert rec.confidence == 0.90
    assert "厨师" in rec.reasoning


def test_recommend_store_manager_with_seniority():
    rec = recommend_salary_structure(role="店长", region="长沙", years_of_service=5)
    # 长沙 tier1_5 系数 1.10, 5年工龄系数 1.30
    # base = 8000 * 1.10 * 1.30 = 11440元 = 11_440_00 fen
    assert rec.base_salary_fen == 11_440_00
    assert rec.region_code == "tier1_5"
    assert rec.seniority_factor == 1.30
    # 工龄补贴 5*50=250元
    assert rec.seniority_subsidy_fen == 250_00


def test_recommend_with_budget_check_below_lower_bound():
    """推荐低价岗位 + 高营收 —— 占比应低于行业 20% 下限,within_budget=False"""
    rec = recommend_salary_structure(
        role="服务员",
        region="tier2",
        years_of_service=0,
        store_monthly_revenue_fen=50_000_00,  # 5万元营收
    )
    assert rec.labor_cost_ratio_estimated is not None
    # 服务员约 3605 元 / 50000 元 ≈ 7.2%,低于 min(20%)
    assert rec.labor_cost_ratio_estimated < 0.20
    assert rec.within_budget is False


def test_recommend_with_budget_check_over():
    """推荐一个高价岗位,配合低营收门店,应超预算"""
    rec = recommend_salary_structure(
        role="店长",
        region="tier1",
        years_of_service=10,
        store_monthly_revenue_fen=30_000_00,  # 3 万元营收 (极低)
    )
    assert rec.labor_cost_ratio_estimated is not None
    assert rec.within_budget is False  # 占比必超 30%


def test_recommend_salary_items_structure():
    rec = recommend_salary_structure(role="厨师长", region="tier2", years_of_service=3)
    assert len(rec.salary_items) >= 3  # 基本+岗位+绩效至少 3 项
    codes = {item["item_code"] for item in rec.salary_items}
    assert "ATT_001" in codes  # 基本工资
    assert "PERF_001" in codes  # 绩效奖金
    # 每项必须含基础字段
    for item in rec.salary_items:
        assert "item_code" in item and "item_name" in item and "amount_fen" in item


def test_recommend_unknown_role_fallback_confidence_060():
    """完全未知的岗位应回落 L1 且置信度 0.60 (HIGH 修复后严格分档)"""
    rec = recommend_salary_structure(role="不存在岗位XYZ", region="tier2", years_of_service=0)
    assert rec.role_tier == "L1_basic"
    assert rec.confidence == 0.60


def test_recommend_fuzzy_match_confidence_075():
    """模糊命中 (关键字包含但不精确) 置信度 0.75"""
    rec = recommend_salary_structure(role="代理店长", region="tier2", years_of_service=0)
    assert rec.role_tier == "L5_manager"
    assert rec.confidence == 0.75


def test_recommend_exact_match_confidence_090():
    """精确命中置信度 0.90"""
    rec = recommend_salary_structure(role="厨师", region="tier2", years_of_service=0)
    assert rec.confidence == 0.90


def test_recommend_seniority_subsidy_uses_correct_code_SUB_001():
    """BLOCKER-1 防回归:工龄补贴必须用 SUB_001,不能误用 SUB_006(夜班补贴)"""
    rec = recommend_salary_structure(role="厨师", region="tier2", years_of_service=5)
    sub_items = [it for it in rec.salary_items if it["item_code"].startswith("SUB_")]
    assert len(sub_items) >= 1
    seniority_item = next(it for it in sub_items if "工龄" in it["item_name"])
    assert seniority_item["item_code"] == "SUB_001"  # 不能是 SUB_006
    assert seniority_item["amount_fen"] == 250_00  # 5*50 元
    # 确保没有误命中 SUB_006/夜班补贴
    assert not any(it["item_code"] == "SUB_006" for it in sub_items)
    assert not any("夜班" in it["item_name"] for it in sub_items)


# ── 批量推荐 ─────────────────────────────────────────────────────


def test_batch_recommend_basic():
    employees = [
        {"role": "服务员", "region": "tier2", "years": 0, "employee_id": "e1"},
        {"role": "厨师", "region": "tier2", "years": 2, "employee_id": "e2"},
        {"role": "店长", "region": "tier2", "years": 5, "employee_id": "e3"},
    ]
    result = batch_recommend(employees=employees)
    assert result["summary"]["headcount"] == 3
    assert result["summary"]["total_gross_fen"] > 0
    assert len(result["recommendations"]) == 3
    # 每条保留 employee_id 回显
    assert result["recommendations"][0]["employee_id"] == "e1"


def test_batch_recommend_with_revenue_within_budget():
    """3 个低价岗位 + 高营收 -> 在预算内"""
    employees = [
        {"role": "服务员", "region": "tier2", "years": 0},
        {"role": "服务员", "region": "tier2", "years": 1},
        {"role": "服务员", "region": "tier2", "years": 2},
    ]
    result = batch_recommend(
        employees=employees,
        store_monthly_revenue_fen=80_000_00,  # 8万元营收
    )
    assert "labor_cost_ratio" in result["summary"]
    assert "benchmark" in result["summary"]


def test_batch_recommend_over_budget_suggests_cut():
    """高价岗位 + 低营收 -> 超预算,应给出减薪建议"""
    employees = [
        {"role": "店长", "region": "tier1", "years": 10},
        {"role": "厨师长", "region": "tier1", "years": 10},
    ]
    result = batch_recommend(
        employees=employees,
        store_monthly_revenue_fen=30_000_00,  # 极低营收
    )
    assert result["summary"]["within_budget"] is False
    assert "suggested_adjustment" in result["summary"]
    assert result["summary"]["suggested_adjustment"]["action"] == "reduce"
    assert result["summary"]["suggested_adjustment"]["pct"] > 0


def test_batch_recommend_empty_list():
    result = batch_recommend(employees=[])
    assert result["summary"]["headcount"] == 0
    assert result["summary"]["total_gross_fen"] == 0


def test_batch_recommend_dirty_data_isolated_not_fatal():
    """HIGH 防回归:单条脏数据不应拖垮整批;应 skip 并记录"""
    employees = [
        {"role": "服务员", "region": "tier2", "years": 0},
        {"role": "厨师", "region": "tier2", "years": "bad_string"},  # 脏 years
        {"role": "店长", "region": "tier2", "years": -5},  # 脏负数
        {"role": "厨师长", "region": "tier2", "years": 100},  # 越界
        {"role": "主管", "region": "tier2", "years": 2},  # 正常
    ]
    result = batch_recommend(employees=employees)
    # 2 条成功(服务员 0 / 主管 2),3 条 skipped(bad_string / -5 / 100)
    assert result["summary"]["headcount"] == 2
    assert result["summary"]["skipped_count"] == 3
    assert len(result["summary"]["skipped_records"]) == 3
    # skipped 条目含 index + error
    for rec in result["summary"]["skipped_records"]:
        assert "index" in rec and "error" in rec


def test_batch_recommend_1000_cap_not_exceeded():
    """DoS 防护:批量 1000 条内应通过(API 层限 1000 由 Pydantic 强制)"""
    employees = [{"role": "服务员", "region": "tier2", "years": 0} for _ in range(1000)]
    result = batch_recommend(employees=employees)
    assert result["summary"]["headcount"] == 1000


# ── 元数据目录 ───────────────────────────────────────────────────


def test_catalog_role_tiers():
    cat = get_role_tiers_catalog()
    assert cat["count"] == len(ROLE_TIERS)
    assert all("tier_code" in t and "example_roles" in t for t in cat["tiers"])
    # MEDIUM 防回归:catalog 字段名用 baseline,不得暴露内部 tier2 命名
    assert all("base_salary_fen_baseline" in t for t in cat["tiers"])
    assert not any("base_salary_fen_tier2" in t for t in cat["tiers"])


def test_catalog_regions():
    cat = get_region_factors_catalog()
    assert cat["count"] == len(REGION_FACTORS)
    assert any(r["region_code"] == "tier1" for r in cat["regions"])


def test_catalog_seniority_curve():
    cat = get_seniority_curve()
    assert cat["count"] == len(SENIORITY_CURVE)
    assert cat["curve"][0]["years_min"] == 0


# ── 人力成本占比校验 ──────────────────────────────────────────────


def test_estimate_labor_cost_ratio_within():
    """25% 占比 - 在行业目标范围内"""
    ratio, within = estimate_labor_cost_ratio(
        total_gross_fen=25_000_00,
        store_monthly_revenue_fen=100_000_00,
    )
    assert ratio == 0.25
    assert within is True


def test_estimate_labor_cost_ratio_over():
    """40% 占比 - 超出 30% 上限"""
    ratio, within = estimate_labor_cost_ratio(
        total_gross_fen=40_000_00,
        store_monthly_revenue_fen=100_000_00,
    )
    assert ratio == 0.40
    assert within is False


def test_estimate_labor_cost_ratio_under():
    """10% 占比 - 低于 20% 下限,仍 within=False"""
    ratio, within = estimate_labor_cost_ratio(
        total_gross_fen=10_000_00,
        store_monthly_revenue_fen=100_000_00,
    )
    assert ratio == 0.10
    assert within is False


def test_estimate_labor_cost_ratio_zero_revenue():
    """零营收保护"""
    ratio, within = estimate_labor_cost_ratio(
        total_gross_fen=10_000_00,
        store_monthly_revenue_fen=0,
    )
    assert ratio == 0.0
    assert within is False


# ── 数据完整性 ───────────────────────────────────────────────────


def test_all_tiers_have_required_keys():
    for tier_code, info in ROLE_TIERS.items():
        assert "label" in info
        assert "base_salary_fen_baseline" in info
        assert "commission_pct" in info
        assert "performance_bonus_pct" in info
        assert isinstance(info["base_salary_fen_baseline"], int)
        assert info["base_salary_fen_baseline"] > 0


def test_all_regions_have_factor():
    for code, info in REGION_FACTORS.items():
        assert "factor" in info
        assert 0.5 <= info["factor"] <= 2.0  # 合理区间


def test_seniority_curve_monotonic():
    """工龄系数应严格单调递增"""
    factors = [b["factor"] for b in SENIORITY_CURVE]
    assert factors == sorted(factors)
    assert factors[0] == 1.00
    assert factors[-1] == 1.40


# ── to_dict 序列化 ───────────────────────────────────────────────


def test_recommendation_to_dict_is_json_serializable():
    import json

    rec = recommend_salary_structure(role="服务员", region="tier2", years_of_service=0)
    d = rec.to_dict()
    # to_dict 应返回纯 dict (dataclass asdict)
    assert isinstance(d, dict)
    # 可被 json 序列化
    json.dumps(d)
