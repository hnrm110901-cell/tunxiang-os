"""
AI 薪资项目推荐服务 -- 餐饮连锁行业智能薪酬建议（v257）

核心能力:
1. 岗位分档 (6 档: L1 基础 / L2 技能 / L3 高阶技能 / L4 督导 / L5 店长 / L6 区域)
2. 区域差异化系数 (tier1 一线 / tier1_5 新一线 / tier2 省会 / tier3 地级市 / tier4 县级)
3. 工龄阶梯系数 (0-1yr / 1-3yr / 3-5yr / 5-10yr / 10+yr)
4. 综合薪酬结构推荐 (基本+岗位+工龄+提成比例+绩效奖金)
5. 人力成本约束校验 (复用 labor_efficiency_service 的 labor_cost_ratio 目标)
6. 批量推荐 + 批次成本预算
7. 可选 LLM 推理增强 (feature flag 控制,默认关闭)

设计原则 (第一性原理):
- 纯函数优先,无副作用,便于单测
- 金额单位统一为 "分" (fen),整数运算零浮点误差
- 与 salary_item_library (71 项字典) + labor_efficiency_service (5 指标基准)
  深度耦合,复用既有项目编码
- 可选 AI 推理层作为装饰,核心不依赖 LLM 可用性
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional

import structlog

from services.labor_efficiency_service import INDUSTRY_BENCHMARKS
from services.salary_item_library import SalaryItem, get_item_by_code

logger = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  岗位分档表 (6 档 × 典型岗位映射)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ROLE_TIERS: Dict[str, Dict[str, Any]] = {
    "L1_basic": {
        "label": "基础服务岗",
        "base_salary_fen_baseline": 3_500_00,  # tier2 基准 3500元
        "position_bonus_fen": 0,
        "commission_pct": 0.005,
        "performance_bonus_pct": 0.03,
        "roles": ["服务员", "传菜员", "保洁员", "迎宾员", "实习生"],
    },
    "L2_skilled": {
        "label": "技能岗",
        "base_salary_fen_baseline": 4_500_00,  # 4500元
        "position_bonus_fen": 300_00,
        "commission_pct": 0.010,
        "performance_bonus_pct": 0.05,
        "roles": ["厨师", "收银员", "吧员", "打荷", "切配", "凉菜师"],
    },
    "L3_senior_skilled": {
        "label": "高阶技能岗",
        "base_salary_fen_baseline": 6_500_00,  # 6500元
        "position_bonus_fen": 800_00,
        "commission_pct": 0.015,
        "performance_bonus_pct": 0.08,
        "roles": ["厨师长", "主厨", "面点师傅", "烧腊师傅", "红案师傅"],
    },
    "L4_supervisor": {
        "label": "督导岗",
        "base_salary_fen_baseline": 5_500_00,  # 5500元
        "position_bonus_fen": 1_000_00,
        "commission_pct": 0.020,
        "performance_bonus_pct": 0.10,
        # 注意:"督导" 属于 L4(门店级督导/楼面督导),L6 是跨店区域经理,
        # 不应再让"督导"出现在 L6.roles 中,避免双重归档(BLOCKER-2 修复)。
        "roles": ["领班", "主管", "楼面主管", "吧台主管", "出品主管", "督导", "店面督导"],
    },
    "L5_manager": {
        "label": "门店管理岗",
        "base_salary_fen_baseline": 8_000_00,  # 8000元
        "position_bonus_fen": 2_000_00,
        "commission_pct": 0.010,           # 营收分成比例较低但基数大
        "performance_bonus_pct": 0.15,
        "roles": ["店长", "副店长", "营运经理"],
    },
    "L6_regional": {
        "label": "区域管理岗",
        "base_salary_fen_baseline": 15_000_00,  # 15000元 (tier2 基准)
        "position_bonus_fen": 3_000_00,
        "commission_pct": 0.003,             # 多店分成比例
        "performance_bonus_pct": 0.20,
        # 注意:"督导" 专属 L4_supervisor,此档仅限纯区域/片区管理岗,
        # 避免与 L4 语义冲突(参见 code-review 审计 BLOCKER-2)。
        "roles": ["区域经理", "区域总监", "片区经理", "运营总监"],
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  区域系数表 (中国主要城市分级,2025 统计口径)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REGION_FACTORS: Dict[str, Dict[str, Any]] = {
    "tier1": {
        "factor": 1.25,
        "label": "一线城市",
        "cities": ["北京", "上海", "广州", "深圳"],
    },
    "tier1_5": {
        "factor": 1.10,
        "label": "新一线城市",
        "cities": ["杭州", "成都", "武汉", "西安", "南京", "苏州", "重庆", "天津", "长沙", "青岛"],
    },
    "tier2": {
        "factor": 1.00,
        "label": "省会/副省级城市",
        "cities": ["合肥", "郑州", "济南", "福州", "南昌", "昆明", "南宁", "贵阳", "石家庄"],
    },
    "tier3": {
        "factor": 0.85,
        "label": "地级市",
        "cities": ["衡阳", "岳阳", "湘潭", "株洲", "常德"],
    },
    "tier4": {
        "factor": 0.75,
        "label": "县级市及以下",
        "cities": [],
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  工龄系数曲线 (餐饮连锁岗位真实分布)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SENIORITY_CURVE: List[Dict[str, Any]] = [
    {"years_min": 0, "years_max": 1,  "factor": 1.00, "label": "新员工"},
    {"years_min": 1, "years_max": 3,  "factor": 1.10, "label": "熟练"},
    {"years_min": 3, "years_max": 5,  "factor": 1.20, "label": "骨干"},
    {"years_min": 5, "years_max": 10, "factor": 1.30, "label": "资深"},
    {"years_min": 10, "years_max": 99,"factor": 1.40, "label": "元老"},  # 上限 1.40x
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  推荐结果数据结构
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class SalaryRecommendation:
    """单员工薪酬推荐结果"""

    # 输入回显
    role: str
    role_tier: str
    tier_label: str
    region_code: str
    region_factor: float
    years_of_service: int
    seniority_factor: float

    # 推荐金额 (fen)
    base_salary_fen: int
    position_bonus_fen: int
    seniority_subsidy_fen: int
    commission_pct: float
    performance_bonus_pct: float
    estimated_total_gross_fen: int

    # 项目级分配 (复用 salary_item_library 编码)
    salary_items: List[Dict[str, Any]] = field(default_factory=list)

    # 约束校验
    labor_cost_ratio_estimated: Optional[float] = None
    within_budget: Optional[bool] = None

    # 可解释性
    reasoning: str = ""
    confidence: float = 0.85  # 0-1, 数据驱动的置信度

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  岗位分档工具
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_role_tier(role: str) -> tuple[str, Dict[str, Any], str]:
    """
    根据岗位名称匹配档位。
    Returns: (tier_code, tier_info, match_quality)
    match_quality: "exact" / "fuzzy" / "fallback"
    无匹配时回落到 L1_basic 并记日志。
    """

    if not role:
        return "L1_basic", ROLE_TIERS["L1_basic"], "fallback"

    normalized = role.strip()

    # 精确匹配优先:遍历所有档位,只要 roles 列表包含该岗位就返回
    for tier_code, tier_info in ROLE_TIERS.items():
        if normalized in tier_info["roles"]:
            return tier_code, tier_info, "exact"

    # 模糊匹配兜底:关键字包含。
    # 按从高到低档位顺序遍历,防止"店面督导"先匹配到 L4 前被 L1 抢占。
    # 注意:由于 ROLE_TIERS 以 L1→L6 插入,这里反转以优先高档位模糊匹配,
    # 避免"店长助理" 先被 L1 "实习生" 的"生"字截胡。
    for tier_code in reversed(list(ROLE_TIERS.keys())):
        tier_info = ROLE_TIERS[tier_code]
        for known_role in tier_info["roles"]:
            if known_role in normalized or normalized in known_role:
                logger.info("ai_salary_advisor.fuzzy_match",
                            input_role=normalized, matched=known_role, tier=tier_code)
                return tier_code, tier_info, "fuzzy"

    logger.warning("ai_salary_advisor.role_unknown_fallback_L1", role=normalized)
    return "L1_basic", ROLE_TIERS["L1_basic"], "fallback"


def get_region_factor(region_code_or_city: str) -> tuple[str, float, str]:
    """
    根据区域编码或城市名返回 (tier_code, factor, label)。
    支持直接传 tier1/tier1_5/tier2/tier3/tier4,
    也支持城市名自动分档 (如 "长沙" -> tier1_5)。
    默认回落 tier2 (1.00x)。
    """

    if not region_code_or_city:
        return "tier2", 1.00, "省会/副省级城市"

    s = region_code_or_city.strip()

    # 直接 tier 编码
    if s in REGION_FACTORS:
        info = REGION_FACTORS[s]
        return s, info["factor"], info["label"]

    # 城市名匹配
    for tier_code, info in REGION_FACTORS.items():
        if s in info["cities"]:
            return tier_code, info["factor"], info["label"]

    logger.info("ai_salary_advisor.region_unknown_fallback_tier2", input=s)
    return "tier2", 1.00, "省会/副省级城市"


def get_seniority_factor(years_of_service: int) -> tuple[float, str]:
    """根据工龄 (年) 返回 (系数, 档位标签)。负数按 0 处理,超过 10 年按 10+ 上限。"""

    y = max(0, years_of_service)
    for band in SENIORITY_CURVE:
        if band["years_min"] <= y < band["years_max"]:
            return band["factor"], band["label"]
    return 1.40, "元老"  # 10+ 上限


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  基础薪酬计算 (纯函数)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_base_salary_fen(
    tier_code: str,
    region_code: str,
    years_of_service: int,
) -> int:
    """
    计算推荐基本工资 (fen,整数)。

    公式: baseline_fen * region_factor * seniority_factor
    结果四舍五入到整数分,保证金额单位精度。
    """

    tier_info = ROLE_TIERS.get(tier_code) or ROLE_TIERS["L1_basic"]
    _, region_factor, _ = get_region_factor(region_code)
    seniority_factor, _ = get_seniority_factor(years_of_service)

    baseline = int(tier_info["base_salary_fen_baseline"])
    result_fen = int(round(baseline * region_factor * seniority_factor))
    return result_fen


def compute_seniority_subsidy_fen(years_of_service: int) -> int:
    """
    工龄补贴独立项 (与基本工资叠加系数解耦)。
    标准: 每满 1 年补贴 50 元/月,上限 500 元/月 (10 年封顶)。
    """

    y = max(0, min(int(years_of_service), 10))
    return y * 50_00  # 50 元/年,单位分


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  项目级薪酬结构组装 (复用 salary_item_library)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _compose_salary_items(
    tier_code: str,
    base_salary_fen: int,
    position_bonus_fen: int,
    seniority_subsidy_fen: int,
    commission_pct: float,
    performance_bonus_pct: float,
) -> List[Dict[str, Any]]:
    """
    根据岗位档位组装薪酬项列表,项目编码来自 salary_item_library。

    返回结构统一为:
      [{"item_code": ..., "item_name": ..., "amount_fen": int, "note": ...}, ...]
    """

    items: List[Dict[str, Any]] = []

    # 基本工资 ATT_001
    items.append(_build_item("ATT_001", base_salary_fen, "推荐基础,区域+工龄系数已计入"))
    # 岗位工资 ATT_002
    if position_bonus_fen > 0:
        items.append(_build_item("ATT_002", position_bonus_fen, "对应岗位档位固定补充"))
    # 工龄补贴 SUB_001 (salary_item_library 中"工龄补贴"的正确编码)
    # 注意:切勿使用 SUB_006,该编码在 salary_item_library 中是"夜班补贴"。
    # 通过 _build_item 走库查名,确保台账字段一致,防止数据污染。
    if seniority_subsidy_fen > 0:
        items.append(_build_item(
            "SUB_001",
            seniority_subsidy_fen,
            "每满 1 年 50 元,10 年封顶",
        ))
    # 提成类 COM_001 (按比例,实际发放需结合营收)
    if commission_pct > 0:
        items.append({
            "item_code": "COM_001",
            "item_name": "营业额提成",
            "amount_fen": 0,  # 按实际营收计算,此处占位
            "note": f"建议比例 {commission_pct*100:.1f}% (按门店营业额计)",
        })
    # 绩效奖金 PERF_001 (按比例,按季度/月度考核发放)
    if performance_bonus_pct > 0:
        gross_base = base_salary_fen + position_bonus_fen
        perf_budget = int(round(gross_base * performance_bonus_pct))
        items.append({
            "item_code": "PERF_001",
            "item_name": "绩效奖金",
            "amount_fen": perf_budget,
            "note": f"基数 {gross_base} 分 × 比例 {performance_bonus_pct*100:.0f}%",
        })

    return items


def _build_item(item_code: str, amount_fen: int, note: str) -> Dict[str, Any]:
    """从 salary_item_library 查编码对应的名称,失败则 item_code 即名称。"""

    lib_item: Optional[SalaryItem] = get_item_by_code(item_code)
    name = lib_item.item_name if lib_item else item_code
    return {
        "item_code": item_code,
        "item_name": name,
        "amount_fen": int(amount_fen),
        "note": note,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  人力成本约束校验 (复用 labor_efficiency INDUSTRY_BENCHMARKS)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def estimate_labor_cost_ratio(
    total_gross_fen: int,
    store_monthly_revenue_fen: int,
) -> tuple[float, bool]:
    """
    估算人力成本占比并判断是否在行业基准范围内。

    Returns:
        (ratio_estimated, within_budget)
    """

    if store_monthly_revenue_fen <= 0:
        return 0.0, False

    ratio = total_gross_fen / store_monthly_revenue_fen
    benchmark = INDUSTRY_BENCHMARKS["labor_cost_ratio"]
    within = benchmark["min"] <= ratio <= benchmark["max"]
    return round(ratio, 4), within


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  可解释性:生成推荐说明
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _generate_reasoning(
    role: str,
    tier_info: Dict[str, Any],
    region_label: str,
    region_factor: float,
    seniority_factor: float,
    seniority_label: str,
    estimated_total_fen: int,
) -> str:
    """拼装人类可读的推荐理由 (纯文本,默认无 LLM)。"""

    fen_to_yuan = f"{estimated_total_fen / 100:.2f}"
    return (
        f"岗位「{role}」归入 {tier_info['label']} ({tier_info['base_salary_fen_baseline']/100:.0f}元基准) | "
        f"区域「{region_label}」应用系数 {region_factor:.2f}× | "
        f"工龄 {seniority_label} 系数 {seniority_factor:.2f}× | "
        f"综合推荐月薪约 {fen_to_yuan} 元 (不含营收提成,按行业基准估算)"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  主入口:单员工推荐
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def recommend_salary_structure(
    role: str,
    region: str,
    years_of_service: int,
    store_monthly_revenue_fen: Optional[int] = None,
) -> SalaryRecommendation:
    """
    综合推荐单员工薪酬结构。

    Args:
        role: 岗位名 (如 "店长" / "厨师" / "服务员")
        region: 区域编码或城市名 (如 "tier1" / "长沙" / "北京")
        years_of_service: 工龄 (整数年)
        store_monthly_revenue_fen: 门店月营业额 (分),可选;
            若提供则会做人力成本占比约束校验。

    Returns:
        SalaryRecommendation 包含:
          - 档位/区域/工龄元信息
          - 基本+岗位+工龄+提成+绩效 各项金额
          - salary_items 详细项目列表
          - 人力成本占比估算 + within_budget 布尔
          - reasoning 说明 + confidence 置信度
    """

    tier_code, tier_info, match_quality = get_role_tier(role)
    region_code, region_factor, region_label = get_region_factor(region)
    seniority_factor, seniority_label = get_seniority_factor(years_of_service)

    base_fen = compute_base_salary_fen(tier_code, region_code, years_of_service)
    position_fen = int(round(tier_info["position_bonus_fen"] * region_factor))
    seniority_sub_fen = compute_seniority_subsidy_fen(years_of_service)

    # 估算总应发 (含绩效,不含提成因其依赖营收)
    gross_base = base_fen + position_fen
    perf_budget_fen = int(round(gross_base * float(tier_info["performance_bonus_pct"])))
    total_gross_fen = base_fen + position_fen + seniority_sub_fen + perf_budget_fen

    items = _compose_salary_items(
        tier_code=tier_code,
        base_salary_fen=base_fen,
        position_bonus_fen=position_fen,
        seniority_subsidy_fen=seniority_sub_fen,
        commission_pct=float(tier_info["commission_pct"]),
        performance_bonus_pct=float(tier_info["performance_bonus_pct"]),
    )

    # 人力成本约束 (若提供门店营收)
    ratio_estimated: Optional[float] = None
    within_budget: Optional[bool] = None
    if store_monthly_revenue_fen is not None and store_monthly_revenue_fen > 0:
        ratio_estimated, within_budget = estimate_labor_cost_ratio(
            total_gross_fen, store_monthly_revenue_fen,
        )

    # 置信度:精确命中 0.90 / 模糊命中 0.75 / 完全未知回落 0.60
    # match_quality 由 get_role_tier 直接返回,避免再次字符串匹配产生不一致。
    if match_quality == "exact":
        confidence = 0.90
    elif match_quality == "fuzzy":
        confidence = 0.75
    else:  # fallback
        confidence = 0.60

    reasoning = _generate_reasoning(
        role=role or "未指定",
        tier_info=tier_info,
        region_label=region_label,
        region_factor=region_factor,
        seniority_factor=seniority_factor,
        seniority_label=seniority_label,
        estimated_total_fen=total_gross_fen,
    )

    rec = SalaryRecommendation(
        role=role or "未指定",
        role_tier=tier_code,
        tier_label=tier_info["label"],
        region_code=region_code,
        region_factor=region_factor,
        years_of_service=max(0, int(years_of_service)),
        seniority_factor=seniority_factor,
        base_salary_fen=base_fen,
        position_bonus_fen=position_fen,
        seniority_subsidy_fen=seniority_sub_fen,
        commission_pct=float(tier_info["commission_pct"]),
        performance_bonus_pct=float(tier_info["performance_bonus_pct"]),
        estimated_total_gross_fen=total_gross_fen,
        salary_items=items,
        labor_cost_ratio_estimated=ratio_estimated,
        within_budget=within_budget,
        reasoning=reasoning,
        confidence=confidence,
    )

    logger.info(
        "ai_salary_advisor.recommend",
        role=role, tier=tier_code, region=region_code,
        years=years_of_service, total_fen=total_gross_fen,
        within_budget=within_budget, confidence=confidence,
    )

    return rec


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  批量推荐 + 门店薪酬预算核算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def batch_recommend(
    employees: List[Dict[str, Any]],
    store_monthly_revenue_fen: Optional[int] = None,
) -> Dict[str, Any]:
    """
    批量推荐多员工薪酬,并汇总门店总人力成本占比。

    Args:
        employees: [{role, region, years, employee_id?, employee_name?}, ...]
        store_monthly_revenue_fen: 门店月营收,用于占比校验

    Returns:
        {
          "recommendations": [SalaryRecommendation.to_dict(), ...],
          "summary": {
              "headcount": N,
              "total_gross_fen": sum,
              "store_revenue_fen": ...,
              "labor_cost_ratio": ratio,
              "within_budget": bool,
              "benchmark": {...}
          }
        }
    """

    recs: List[Dict[str, Any]] = []
    total_gross_fen = 0
    skipped: List[Dict[str, Any]] = []

    for idx, emp in enumerate(employees or []):
        # 单条脏数据不应拖垮整批,记录 skipped 供前端/运维排查
        try:
            years_raw = emp.get("years")
            years_int = int(years_raw) if years_raw is not None else 0
            if years_int < 0 or years_int > 60:
                raise ValueError(f"years {years_int} out of [0, 60]")

            rec = recommend_salary_structure(
                role=emp.get("role") or "",
                region=emp.get("region") or "tier2",
                years_of_service=years_int,
                store_monthly_revenue_fen=None,  # 单员工不做约束,最后统一算
            )
        except (ValueError, TypeError) as e:
            logger.warning(
                "ai_salary_advisor.batch_skip_bad_record",
                index=idx, emp=emp, error=str(e),
            )
            skipped.append({"index": idx, "input": dict(emp), "error": str(e)})
            continue

        d = rec.to_dict()
        # 回填员工标识 (便于前端渲染)
        if emp.get("employee_id"):
            d["employee_id"] = emp["employee_id"]
        if emp.get("employee_name"):
            d["employee_name"] = emp["employee_name"]
        recs.append(d)
        total_gross_fen += rec.estimated_total_gross_fen

    summary: Dict[str, Any] = {
        "headcount": len(recs),
        "skipped_count": len(skipped),
        "total_gross_fen": total_gross_fen,
        "store_revenue_fen": store_monthly_revenue_fen,
        "benchmark": dict(INDUSTRY_BENCHMARKS["labor_cost_ratio"]),
    }
    if skipped:
        summary["skipped_records"] = skipped

    if store_monthly_revenue_fen and store_monthly_revenue_fen > 0:
        ratio, within = estimate_labor_cost_ratio(total_gross_fen, store_monthly_revenue_fen)
        summary["labor_cost_ratio"] = ratio
        summary["within_budget"] = within

        # 超支时附加减薪建议百分比
        if not within:
            target = INDUSTRY_BENCHMARKS["labor_cost_ratio"]["target"]
            if ratio > INDUSTRY_BENCHMARKS["labor_cost_ratio"]["max"]:
                suggested_cut_pct = round((ratio - target) / ratio * 100, 2)
                summary["suggested_adjustment"] = {
                    "action": "reduce",
                    "pct": suggested_cut_pct,
                    "note": f"建议整体下调 {suggested_cut_pct}% 以回归目标 {target*100:.0f}%",
                }
            else:
                # 分母用 benchmark min 而非 ratio 本身,避免极小 ratio 导致百分比虚高后被硬 clamp。
                # 上限 30% 的设定合理范围是"从下限向目标爬升",非任意放大。
                floor_ratio = INDUSTRY_BENCHMARKS["labor_cost_ratio"]["min"]
                denom = max(ratio, floor_ratio)
                suggested_raise_pct = round((target - ratio) / denom * 100, 2)
                summary["suggested_adjustment"] = {
                    "action": "raise",
                    "pct": min(suggested_raise_pct, 30.0),  # 上限 30% 避免离谱
                    "note": "人力成本低于行业下限,可考虑提高投入提升服务质量",
                }

    logger.info(
        "ai_salary_advisor.batch_done",
        headcount=len(recs), total_fen=total_gross_fen,
        ratio=summary.get("labor_cost_ratio"),
    )

    return {"recommendations": recs, "summary": summary}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  元数据查询 (前端配置页用)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_role_tiers_catalog() -> Dict[str, Any]:
    """返回所有岗位档位的元信息 (前端 select 渲染用)。"""

    return {
        "tiers": [
            {
                "tier_code": tier_code,
                "label": info["label"],
                "base_salary_fen_baseline": info["base_salary_fen_baseline"],
                "position_bonus_fen": info["position_bonus_fen"],
                "commission_pct": info["commission_pct"],
                "performance_bonus_pct": info["performance_bonus_pct"],
                "example_roles": info["roles"],
            }
            for tier_code, info in ROLE_TIERS.items()
        ],
        "count": len(ROLE_TIERS),
    }


def get_region_factors_catalog() -> Dict[str, Any]:
    """返回所有区域系数表 (前端 select 渲染用)。"""

    return {
        "regions": [
            {
                "region_code": tier_code,
                "label": info["label"],
                "factor": info["factor"],
                "example_cities": info["cities"],
            }
            for tier_code, info in REGION_FACTORS.items()
        ],
        "count": len(REGION_FACTORS),
    }


def get_seniority_curve() -> Dict[str, Any]:
    """返回工龄系数曲线 (前端 chart/tooltip 渲染用)。"""

    return {"curve": list(SENIORITY_CURVE), "count": len(SENIORITY_CURVE)}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  可选 LLM 推理增强 (feature flag 默认关闭)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_ai_enhanced_reasoning(
    recommendation: SalaryRecommendation,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    (占位) 通过 tx-brain Claude API 生成深度推荐分析。
    当前版本返回 deterministic reasoning;启用 LLM 需接入 brain_client。

    TODO(Phase2): 接入 services/tx-brain 的 Claude API,
    基于 context 中的门店画像/岗位市场数据生成定制化分析。
    """

    # Feature flag 占位
    _ = context  # 目前未使用,保留接口

    return recommendation.reasoning + " (deterministic, 未启用 LLM 增强)"


__all__ = [
    "ROLE_TIERS",
    "REGION_FACTORS",
    "SENIORITY_CURVE",
    "SalaryRecommendation",
    "get_role_tier",
    "get_region_factor",
    "get_seniority_factor",
    "compute_base_salary_fen",
    "compute_seniority_subsidy_fen",
    "estimate_labor_cost_ratio",
    "recommend_salary_structure",
    "batch_recommend",
    "get_role_tiers_catalog",
    "get_region_factors_catalog",
    "get_seniority_curve",
    "get_ai_enhanced_reasoning",
]
