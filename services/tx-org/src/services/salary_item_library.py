"""
薪资项目库 -- 餐饮行业通用薪资项目定义（71项，对标i人事138项精简版）

7大分类：出勤(15)/假期(10)/绩效(12)/提成(10)/补贴(10)/扣款(8)/社保(6)。
金额单位统一为"分"（fen）。

Phase 1: 内存字典（向下兼容既有 compute_salary_by_items）
Phase 2: init_salary_items_for_tenant 写入 DB salary_item_templates 表
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import structlog
from services.payroll_engine import (
    compute_absence_deduction,
    compute_base_salary,
    compute_commission,
    compute_early_leave_deduction,
    compute_full_attendance_bonus,
    compute_late_deduction,
    compute_monthly_tax,
    compute_performance_bonus,
    compute_seniority_subsidy,
    derive_hourly_rate,
)

logger = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  数据结构
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class SalaryItem:
    item_code: str  # 如 "ATT_001"
    item_name: str  # 如 "基本工资"
    category: str  # attendance/leave/performance/commission/subsidy/deduction/social
    tax_type: str  # pre_tax_add / pre_tax_sub / other
    calc_rule: str  # fixed / formula / manual
    formula: str  # 计算公式（如有）
    is_required: bool  # 是否必填
    default_value_fen: int  # 默认值（分）
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7大分类定义 — 共 71 项
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SALARY_ITEMS: Dict[str, List[SalaryItem]] = {
    # ── 出勤类（15项） ──
    "attendance": [
        SalaryItem(
            "ATT_001", "基本工资", "attendance", "pre_tax_add", "fixed", "", True, 0, "月薪标准，按出勤比例折算"
        ),
        SalaryItem("ATT_002", "岗位工资", "attendance", "pre_tax_add", "fixed", "", False, 0, "岗位等级对应的固定工资"),
        SalaryItem("ATT_003", "出勤天数", "attendance", "other", "manual", "", True, 0, "当月实际出勤天数"),
        SalaryItem(
            "ATT_004",
            "应出勤天数",
            "attendance",
            "other",
            "formula",
            "work_days_in_month",
            True,
            0,
            "当月应出勤工作日数",
        ),
        SalaryItem(
            "ATT_005",
            "出勤工资",
            "attendance",
            "pre_tax_add",
            "formula",
            "base_salary_fen * attendance_days / work_days_in_month",
            True,
            0,
            "按出勤比例折算的实际基本工资",
        ),
        SalaryItem(
            "ATT_006",
            "日薪",
            "attendance",
            "other",
            "formula",
            "base_salary_fen / 21.75",
            False,
            0,
            "月薪按法定计薪日折算日薪",
        ),
        SalaryItem(
            "ATT_007",
            "时薪",
            "attendance",
            "other",
            "formula",
            "base_salary_fen / 21.75 / 8",
            False,
            0,
            "月薪按法定计薪日折算时薪",
        ),
        SalaryItem(
            "ATT_008",
            "计件工资",
            "attendance",
            "pre_tax_add",
            "formula",
            "piece_count * piece_rate_fen",
            False,
            0,
            "按件计薪（适用后厨切配等岗位）",
        ),
        SalaryItem(
            "ATT_009", "职级工资", "attendance", "pre_tax_add", "fixed", "", False, 0, "按职级体系确定的固定补充工资"
        ),
        SalaryItem(
            "ATT_010",
            "试用期工资",
            "attendance",
            "pre_tax_add",
            "formula",
            "base_salary_fen * 0.8",
            False,
            0,
            "试用期按基本工资80%发放",
        ),
        SalaryItem("ATT_011", "转正调薪", "attendance", "pre_tax_add", "manual", "", False, 0, "转正当月薪资差额补发"),
        SalaryItem("ATT_012", "实习补贴", "attendance", "pre_tax_add", "fixed", "", False, 0, "实习生固定补贴金额"),
        SalaryItem(
            "ATT_013",
            "兼职日薪",
            "attendance",
            "pre_tax_add",
            "formula",
            "parttime_days * parttime_daily_fen",
            False,
            0,
            "兼职人员按天计薪",
        ),
        SalaryItem(
            "ATT_014",
            "小时工时薪",
            "attendance",
            "pre_tax_add",
            "formula",
            "hourly_rate_fen * work_hours",
            False,
            0,
            "小时工按实际工时计算",
        ),
        SalaryItem(
            "ATT_015",
            "调休折算",
            "attendance",
            "pre_tax_sub",
            "formula",
            "comp_off_days * daily_rate_fen",
            False,
            0,
            "调休天数折算扣款",
        ),
    ],
    # ── 假期类（10项） ──
    "leave": [
        SalaryItem(
            "LV_001",
            "年假工资",
            "leave",
            "pre_tax_add",
            "formula",
            "annual_leave_days * daily_rate_fen",
            False,
            0,
            "带薪年假工资（按日薪计）",
        ),
        SalaryItem(
            "LV_002",
            "病假工资",
            "leave",
            "pre_tax_add",
            "formula",
            "sick_leave_days * daily_rate_fen * 0.6",
            False,
            0,
            "病假按日薪60%发放",
        ),
        SalaryItem(
            "LV_003",
            "事假扣款",
            "leave",
            "pre_tax_sub",
            "formula",
            "personal_leave_days * daily_rate_fen",
            False,
            0,
            "事假按日薪全额扣除",
        ),
        SalaryItem(
            "LV_004",
            "产假工资",
            "leave",
            "pre_tax_add",
            "formula",
            "maternity_leave_days * daily_rate_fen",
            False,
            0,
            "产假期间全薪发放",
        ),
        SalaryItem(
            "LV_005",
            "陪产假工资",
            "leave",
            "pre_tax_add",
            "formula",
            "paternity_leave_days * daily_rate_fen",
            False,
            0,
            "陪产假期间全薪发放",
        ),
        SalaryItem(
            "LV_006",
            "婚丧假工资",
            "leave",
            "pre_tax_add",
            "formula",
            "marriage_funeral_days * daily_rate_fen",
            False,
            0,
            "婚假/丧假期间全薪发放",
        ),
        SalaryItem(
            "LV_007",
            "工伤假工资",
            "leave",
            "pre_tax_add",
            "formula",
            "injury_leave_days * daily_rate_fen",
            False,
            0,
            "工伤假期间全薪发放",
        ),
        SalaryItem(
            "LV_008",
            "哺乳假工资",
            "leave",
            "pre_tax_add",
            "formula",
            "nursing_leave_days * daily_rate_fen",
            False,
            0,
            "哺乳假期间工资",
        ),
        SalaryItem(
            "LV_009",
            "育儿假工资",
            "leave",
            "pre_tax_add",
            "formula",
            "childcare_leave_days * daily_rate_fen",
            False,
            0,
            "育儿假期间全薪发放",
        ),
        SalaryItem(
            "LV_010",
            "护理假工资",
            "leave",
            "pre_tax_add",
            "formula",
            "care_leave_days * daily_rate_fen",
            False,
            0,
            "护理假期间全薪发放",
        ),
    ],
    # ── 绩效类（12项） ──
    "performance": [
        SalaryItem(
            "PERF_001",
            "KPI奖金",
            "performance",
            "pre_tax_add",
            "formula",
            "base_salary_fen * max(0, perf_coefficient - 100) / 100",
            False,
            0,
            "KPI考核系数超过100部分对应奖金",
        ),
        SalaryItem("PERF_002", "月度绩效", "performance", "pre_tax_add", "manual", "", False, 0, "月度绩效考核奖金"),
        SalaryItem("PERF_003", "季度绩效", "performance", "pre_tax_add", "manual", "", False, 0, "季度绩效考核奖金"),
        SalaryItem("PERF_004", "年终奖", "performance", "pre_tax_add", "manual", "", False, 0, "年度绩效奖金/年终奖"),
        SalaryItem(
            "PERF_005",
            "超额完成奖",
            "performance",
            "pre_tax_add",
            "formula",
            "exceed_amount_fen * exceed_bonus_rate",
            False,
            0,
            "超额完成业绩目标奖励",
        ),
        SalaryItem(
            "PERF_006", "团队协作奖", "performance", "pre_tax_add", "manual", "", False, 0, "团队协作表现突出奖金"
        ),
        SalaryItem(
            "PERF_007", "创新建议奖", "performance", "pre_tax_add", "manual", "", False, 0, "提出创新建议被采纳奖励"
        ),
        SalaryItem("PERF_008", "安全生产奖", "performance", "pre_tax_add", "fixed", "", False, 0, "当月无安全事故奖励"),
        SalaryItem("PERF_009", "节能达标奖", "performance", "pre_tax_add", "fixed", "", False, 0, "能耗指标达标奖励"),
        SalaryItem(
            "PERF_010",
            "全勤奖",
            "performance",
            "pre_tax_add",
            "fixed",
            "",
            False,
            30000,
            "当月无缺勤/迟到/早退发放，默认300元",
        ),
        SalaryItem(
            "PERF_011", "优秀员工奖", "performance", "pre_tax_add", "manual", "", False, 0, "月度/季度优秀员工评选奖金"
        ),
        SalaryItem(
            "PERF_012", "师带徒奖金", "performance", "pre_tax_add", "manual", "", False, 0, "新员工带教导师额外奖励"
        ),
    ],
    # ── 提成类（10项） ──
    "commission": [
        SalaryItem(
            "COMM_001",
            "营业额提成",
            "commission",
            "pre_tax_add",
            "formula",
            "sales_amount_fen * commission_rate",
            False,
            0,
            "按门店/个人营业额比例提成",
        ),
        SalaryItem(
            "COMM_002",
            "翻台率提成",
            "commission",
            "pre_tax_add",
            "formula",
            "turnover_bonus_per_table_fen * extra_turnover_count",
            False,
            0,
            "翻台率超标部分每桌奖励",
        ),
        SalaryItem(
            "COMM_003",
            "推菜提成",
            "commission",
            "pre_tax_add",
            "formula",
            "recommended_dish_amount_fen * recommend_rate",
            False,
            0,
            "主推菜品销售提成",
        ),
        SalaryItem(
            "COMM_004",
            "酒水提成",
            "commission",
            "pre_tax_add",
            "formula",
            "beverage_amount_fen * beverage_comm_rate",
            False,
            0,
            "酒水饮料销售提成",
        ),
        SalaryItem(
            "COMM_005",
            "加单提成",
            "commission",
            "pre_tax_add",
            "formula",
            "upsell_amount_fen * upsell_rate",
            False,
            0,
            "客户加单金额提成",
        ),
        SalaryItem(
            "COMM_006",
            "会员开卡提成",
            "commission",
            "pre_tax_add",
            "formula",
            "new_member_count * member_card_bonus_fen",
            False,
            0,
            "每成功开卡一位会员的奖励",
        ),
        SalaryItem(
            "COMM_007",
            "储值提成",
            "commission",
            "pre_tax_add",
            "formula",
            "stored_value_fen * stored_value_rate",
            False,
            0,
            "会员储值金额提成",
        ),
        SalaryItem(
            "COMM_008",
            "外卖提成",
            "commission",
            "pre_tax_add",
            "formula",
            "delivery_amount_fen * delivery_comm_rate",
            False,
            0,
            "外卖订单金额提成",
        ),
        SalaryItem(
            "COMM_009",
            "团购核销提成",
            "commission",
            "pre_tax_add",
            "formula",
            "groupon_verify_count * groupon_bonus_fen",
            False,
            0,
            "每核销一张团购券奖励",
        ),
        SalaryItem(
            "COMM_010",
            "宴席提成",
            "commission",
            "pre_tax_add",
            "formula",
            "banquet_amount_fen * banquet_comm_rate",
            False,
            0,
            "宴席订单金额提成",
        ),
    ],
    # ── 补贴类（10项） ──
    "subsidy": [
        SalaryItem(
            "SUB_001",
            "工龄补贴",
            "subsidy",
            "pre_tax_add",
            "formula",
            "seniority_subsidy(seniority_months)",
            False,
            0,
            "按工龄阶梯发放，满1年起",
        ),
        SalaryItem(
            "SUB_002", "交通补贴", "subsidy", "pre_tax_add", "fixed", "", False, 20000, "交通补贴，默认200元/月"
        ),
        SalaryItem("SUB_003", "餐补", "subsidy", "pre_tax_add", "fixed", "", False, 30000, "员工餐补贴，默认300元/月"),
        SalaryItem(
            "SUB_004",
            "住房补贴",
            "subsidy",
            "pre_tax_add",
            "fixed",
            "",
            False,
            50000,
            "未住员工宿舍的住宿补贴，默认500元/月",
        ),
        SalaryItem(
            "SUB_005",
            "高温补贴",
            "subsidy",
            "pre_tax_add",
            "fixed",
            "",
            False,
            30000,
            "6-9月高温补贴（厨师等高温岗位），默认300元/月",
        ),
        SalaryItem(
            "SUB_006",
            "夜班补贴",
            "subsidy",
            "pre_tax_add",
            "formula",
            "night_shift_days * night_shift_rate_fen",
            False,
            0,
            "夜班天数 x 每日夜班补贴",
        ),
        SalaryItem(
            "SUB_007",
            "技能补贴",
            "subsidy",
            "pre_tax_add",
            "fixed",
            "",
            False,
            0,
            "持证上岗技能补贴（厨师证/食品安全证等）",
        ),
        SalaryItem("SUB_008", "学历补贴", "subsidy", "pre_tax_add", "fixed", "", False, 0, "大专/本科/硕士等学历补贴"),
        SalaryItem(
            "SUB_009", "通讯补贴", "subsidy", "pre_tax_add", "fixed", "", False, 10000, "手机通讯补贴，默认100元/月"
        ),
        SalaryItem(
            "SUB_010",
            "出差补贴",
            "subsidy",
            "pre_tax_add",
            "formula",
            "business_trip_days * trip_daily_fen",
            False,
            0,
            "出差期间每日补贴",
        ),
    ],
    # ── 扣款类（8项） ──
    "deduction": [
        SalaryItem(
            "DED_001",
            "迟到扣款",
            "deduction",
            "pre_tax_sub",
            "formula",
            "late_count * late_deduction_per_time_fen",
            False,
            0,
            "迟到次数 x 每次扣款金额",
        ),
        SalaryItem(
            "DED_002",
            "早退扣款",
            "deduction",
            "pre_tax_sub",
            "formula",
            "early_leave_count * early_leave_deduction_per_time_fen",
            False,
            0,
            "早退次数 x 每次扣款金额",
        ),
        SalaryItem(
            "DED_003",
            "旷工扣款",
            "deduction",
            "pre_tax_sub",
            "formula",
            "base_salary_fen / work_days_in_month * absent_days * 3",
            False,
            0,
            "旷工按日薪3倍扣款",
        ),
        SalaryItem(
            "DED_004",
            "事假扣款",
            "deduction",
            "pre_tax_sub",
            "formula",
            "base_salary_fen / work_days_in_month * personal_leave_days",
            False,
            0,
            "事假按日薪扣除",
        ),
        SalaryItem("DED_005", "违规罚款", "deduction", "pre_tax_sub", "manual", "", False, 0, "违反公司规章制度处罚"),
        SalaryItem(
            "DED_006", "赔偿扣款", "deduction", "pre_tax_sub", "manual", "", False, 0, "餐具/设备损坏等赔偿扣款"
        ),
        SalaryItem("DED_007", "借支扣回", "deduction", "pre_tax_sub", "manual", "", False, 0, "预借工资扣回"),
        SalaryItem("DED_008", "预支扣回", "deduction", "pre_tax_sub", "manual", "", False, 0, "预支费用逐月扣回"),
    ],
    # ── 社保类（6项） ──
    "social": [
        SalaryItem(
            "SOC_001",
            "养老保险(个人)",
            "social",
            "pre_tax_sub",
            "formula",
            "social_base_fen * 0.08",
            True,
            0,
            "养老保险个人缴纳8%",
        ),
        SalaryItem(
            "SOC_002",
            "医疗保险(个人)",
            "social",
            "pre_tax_sub",
            "formula",
            "social_base_fen * 0.02",
            True,
            0,
            "医疗保险个人缴纳2%",
        ),
        SalaryItem(
            "SOC_003",
            "失业保险(个人)",
            "social",
            "pre_tax_sub",
            "formula",
            "social_base_fen * 0.005",
            True,
            0,
            "失业保险个人缴纳0.5%",
        ),
        SalaryItem(
            "SOC_004",
            "住房公积金(个人)",
            "social",
            "pre_tax_sub",
            "formula",
            "housing_fund_base_fen * housing_fund_rate",
            False,
            0,
            "住房公积金个人缴纳（5%-12%）",
        ),
        SalaryItem("SOC_005", "补充医疗(个人)", "social", "pre_tax_sub", "fixed", "", False, 0, "补充医疗保险个人部分"),
        SalaryItem(
            "SOC_006",
            "企业年金(个人)",
            "social",
            "pre_tax_sub",
            "formula",
            "social_base_fen * annuity_rate",
            False,
            0,
            "企业年金个人缴纳部分",
        ),
    ],
}

# 所有分类
CATEGORIES = {
    "attendance": "出勤类",
    "leave": "假期类",
    "performance": "绩效类",
    "commission": "提成类",
    "subsidy": "补贴类",
    "deduction": "扣款类",
    "social": "社保类",
}

# 门店模板配置：不同餐饮业态启用的默认薪资项目
STORE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "standard": {
        "name": "标准中餐",
        "description": "适用于中餐正餐门店",
        "enabled_items": [
            # 出勤
            "ATT_001",
            "ATT_002",
            "ATT_003",
            "ATT_004",
            "ATT_005",
            # 假期
            "LV_001",
            "LV_002",
            "LV_003",
            # 绩效
            "PERF_001",
            "PERF_002",
            "PERF_010",
            # 提成
            "COMM_001",
            "COMM_003",
            "COMM_004",
            "COMM_006",
            # 补贴
            "SUB_001",
            "SUB_002",
            "SUB_003",
            "SUB_006",
            # 扣款
            "DED_001",
            "DED_002",
            "DED_003",
            "DED_005",
            "DED_007",
            # 社保
            "SOC_001",
            "SOC_002",
            "SOC_003",
            "SOC_004",
        ],
        "default_overrides": {
            "ATT_001": 500000,  # 基本工资默认5000元
            "SUB_003": 30000,  # 餐补300元
            "SUB_002": 20000,  # 交通补贴200元
            "PERF_010": 30000,  # 全勤奖300元
        },
    },
    "seafood": {
        "name": "海鲜酒楼",
        "description": "适用于海鲜酒楼等高端餐饮",
        "enabled_items": [
            # 出勤
            "ATT_001",
            "ATT_002",
            "ATT_003",
            "ATT_004",
            "ATT_005",
            "ATT_009",
            # 假期
            "LV_001",
            "LV_002",
            "LV_003",
            "LV_004",
            "LV_005",
            "LV_006",
            # 绩效
            "PERF_001",
            "PERF_002",
            "PERF_003",
            "PERF_004",
            "PERF_005",
            "PERF_010",
            "PERF_011",
            # 提成
            "COMM_001",
            "COMM_002",
            "COMM_003",
            "COMM_004",
            "COMM_005",
            "COMM_006",
            "COMM_007",
            "COMM_010",
            # 补贴
            "SUB_001",
            "SUB_002",
            "SUB_003",
            "SUB_004",
            "SUB_005",
            "SUB_006",
            "SUB_007",
            "SUB_009",
            # 扣款
            "DED_001",
            "DED_002",
            "DED_003",
            "DED_005",
            "DED_006",
            "DED_007",
            # 社保
            "SOC_001",
            "SOC_002",
            "SOC_003",
            "SOC_004",
            "SOC_005",
        ],
        "default_overrides": {
            "ATT_001": 600000,  # 基本工资默认6000元
            "ATT_002": 100000,  # 岗位工资默认1000元
            "SUB_003": 50000,  # 餐补500元
            "SUB_002": 30000,  # 交通补贴300元
            "SUB_004": 50000,  # 住宿补贴500元
            "PERF_010": 50000,  # 全勤奖500元
        },
    },
    "fast_food": {
        "name": "快餐",
        "description": "适用于快餐、小吃等轻餐饮",
        "enabled_items": [
            # 出勤
            "ATT_001",
            "ATT_003",
            "ATT_004",
            "ATT_005",
            "ATT_014",
            # 假期
            "LV_001",
            "LV_002",
            "LV_003",
            # 绩效
            "PERF_001",
            "PERF_002",
            "PERF_010",
            # 提成
            "COMM_001",
            "COMM_008",
            # 补贴
            "SUB_002",
            "SUB_003",
            "SUB_001",
            # 扣款
            "DED_001",
            "DED_002",
            "DED_003",
            "DED_007",
            # 社保
            "SOC_001",
            "SOC_002",
            "SOC_003",
        ],
        "default_overrides": {
            "ATT_001": 380000,  # 基本工资默认3800元
            "SUB_003": 20000,  # 餐补200元
            "SUB_002": 15000,  # 交通补贴150元
            "PERF_010": 20000,  # 全勤奖200元
        },
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部索引
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _build_item_index() -> Dict[str, SalaryItem]:
    """构建 item_code -> SalaryItem 索引"""
    index: Dict[str, SalaryItem] = {}
    for items in SALARY_ITEMS.values():
        for item in items:
            index[item.item_code] = item
    return index


_ITEM_INDEX: Dict[str, SalaryItem] = _build_item_index()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  公共 API（内存查询）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_all_items() -> List[SalaryItem]:
    """获取完整薪资项目库"""
    result: List[SalaryItem] = []
    for items in SALARY_ITEMS.values():
        result.extend(items)
    return result


def get_items_by_category(category: str) -> List[SalaryItem]:
    """按分类获取薪资项目"""
    return list(SALARY_ITEMS.get(category, []))


def get_item_by_code(item_code: str) -> Optional[SalaryItem]:
    """按编码获取单个薪资项目"""
    return _ITEM_INDEX.get(item_code)


def get_categories() -> Dict[str, str]:
    """获取所有分类及其中文名"""
    return dict(CATEGORIES)


def init_store_salary_config(template: str = "standard") -> Dict[str, Any]:
    """为新门店初始化薪资配置（纯内存，不写DB）

    Args:
        template: standard(标准中餐) / seafood(海鲜酒楼) / fast_food(快餐)

    Returns:
        该模板启用的薪资项目列表 + 默认值
    """
    tpl = STORE_TEMPLATES.get(template)
    if tpl is None:
        raise ValueError(f"未知模板: {template}，可选: {list(STORE_TEMPLATES.keys())}")

    enabled_items: List[Dict[str, Any]] = []
    overrides = tpl.get("default_overrides", {})

    for code in tpl["enabled_items"]:
        item = _ITEM_INDEX.get(code)
        if item is None:
            continue
        item_dict = item.to_dict()
        # 应用模板默认值覆盖
        if code in overrides:
            item_dict["default_value_fen"] = overrides[code]
        enabled_items.append(item_dict)

    return {
        "template": template,
        "template_name": tpl["name"],
        "description": tpl["description"],
        "enabled_count": len(enabled_items),
        "enabled_items": enabled_items,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DB 持久化 API（写入 salary_item_templates 表）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def init_salary_items_for_tenant(
    db,
    tenant_id: str,
    template: str = "standard",
) -> Dict[str, Any]:
    """为新租户初始化标准薪资项到 DB salary_item_templates 表

    Args:
        db: asyncpg 连接或 SQLAlchemy AsyncSession
        tenant_id: 租户 UUID
        template: 模板类型

    Returns:
        初始化结果摘要
    """
    tpl = STORE_TEMPLATES.get(template)
    if tpl is None:
        raise ValueError(f"未知模板: {template}，可选: {list(STORE_TEMPLATES.keys())}")

    overrides = tpl.get("default_overrides", {})
    enabled_set = set(tpl["enabled_items"])

    # 检查是否已初始化
    check_sql = """
        SELECT COUNT(*) AS cnt FROM salary_item_templates
        WHERE tenant_id = $1 AND is_deleted = FALSE
    """
    row = await db.fetchrow(check_sql, uuid.UUID(tenant_id))
    if row and row["cnt"] > 0:
        logger.info("salary_items_already_initialized", tenant_id=tenant_id, count=row["cnt"])
        return {
            "initialized": False,
            "message": f"该租户已有 {row['cnt']} 个薪资项，跳过初始化",
            "existing_count": row["cnt"],
        }

    # 批量插入所有项目
    insert_sql = """
        INSERT INTO salary_item_templates
            (tenant_id, item_code, item_name, category, tax_type, calc_rule,
             formula, is_required, default_value_fen, is_system, is_enabled,
             sort_order, description)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        ON CONFLICT (tenant_id, item_code) DO NOTHING
    """

    inserted = 0
    all_items = get_all_items()

    for sort_idx, item in enumerate(all_items, start=1):
        is_enabled = item.item_code in enabled_set
        default_val = overrides.get(item.item_code, item.default_value_fen)

        await db.execute(
            insert_sql,
            uuid.UUID(tenant_id),
            item.item_code,
            item.item_name,
            item.category,
            item.tax_type,
            item.calc_rule,
            item.formula,
            item.is_required,
            default_val,
            True,  # is_system
            is_enabled,
            sort_idx,
            item.description,
        )
        inserted += 1

    logger.info(
        "salary_items_initialized",
        tenant_id=tenant_id,
        template=template,
        total=inserted,
        enabled=len(enabled_set),
    )

    return {
        "initialized": True,
        "template": template,
        "template_name": tpl["name"],
        "total_items": inserted,
        "enabled_items": len(enabled_set),
    }


async def get_tenant_salary_items(
    db,
    tenant_id: str,
    category: Optional[str] = None,
    enabled_only: bool = False,
) -> List[Dict[str, Any]]:
    """从 DB 读取租户薪资项列表"""
    sql = """
        SELECT id, item_code, item_name, category, tax_type, calc_rule,
               formula, is_required, default_value_fen, is_system, is_enabled,
               sort_order, description, created_at, updated_at
        FROM salary_item_templates
        WHERE tenant_id = $1 AND is_deleted = FALSE
    """
    params: list[Any] = [uuid.UUID(tenant_id)]
    idx = 2

    if category:
        sql += f" AND category = ${idx}"
        params.append(category)
        idx += 1
    if enabled_only:
        sql += " AND is_enabled = TRUE"

    sql += " ORDER BY sort_order, item_code"
    rows = await db.fetch(sql, *params)
    return [dict(r) for r in rows]


async def toggle_salary_item(
    db,
    tenant_id: str,
    item_code: str,
    is_enabled: bool,
) -> Dict[str, Any]:
    """启用/禁用租户的某个薪资项"""
    sql = """
        UPDATE salary_item_templates
        SET is_enabled = $1, updated_at = NOW()
        WHERE tenant_id = $2 AND item_code = $3 AND is_deleted = FALSE
        RETURNING id, item_code, item_name, is_enabled
    """
    row = await db.fetchrow(sql, is_enabled, uuid.UUID(tenant_id), item_code)
    if row is None:
        raise ValueError(f"薪资项 {item_code} 不存在")
    return dict(row)


async def create_custom_salary_item(
    db,
    tenant_id: str,
    item_code: str,
    item_name: str,
    category: str,
    tax_type: str = "pre_tax_add",
    calc_rule: str = "manual",
    formula: str = "",
    default_value_fen: int = 0,
    description: str = "",
) -> Dict[str, Any]:
    """创建自定义薪资项"""
    if category not in CATEGORIES:
        raise ValueError(f"无效分类: {category}，可选: {list(CATEGORIES.keys())}")

    sql = """
        INSERT INTO salary_item_templates
            (tenant_id, item_code, item_name, category, tax_type, calc_rule,
             formula, is_required, default_value_fen, is_system, is_enabled,
             sort_order, description)
        VALUES ($1, $2, $3, $4, $5, $6, $7, FALSE, $8, FALSE, TRUE, 999, $9)
        RETURNING id, item_code, item_name, category, is_enabled, created_at
    """
    try:
        row = await db.fetchrow(
            sql,
            uuid.UUID(tenant_id),
            item_code,
            item_name,
            category,
            tax_type,
            calc_rule,
            formula,
            default_value_fen,
            description,
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise ValueError(f"薪资项编码 {item_code} 已存在") from e
        raise
    return dict(row)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  工资计算（向下兼容）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_salary_by_items(
    employee_data: Dict[str, Any],
    enabled_items: List[str],
) -> Dict[str, Any]:
    """按启用的薪资项目计算工资

    Args:
        employee_data: 员工薪资数据，需要包含以下字段（按需）：
            - base_salary_fen: 基本工资（分）
            - position_salary_fen: 岗位工资（分）
            - attendance_days: 出勤天数
            - work_days_in_month: 应出勤天数
            - weekday_ot_hours: 工作日加班小时数
            - weekend_ot_hours: 休息日加班小时数
            - holiday_ot_hours: 节假日加班小时数
            - personal_leave_days: 事假天数
            - sick_leave_days: 病假天数
            - late_count: 迟到次数
            - late_deduction_per_time_fen: 每次迟到扣款（分）
            - early_leave_count: 早退次数
            - early_leave_deduction_per_time_fen: 每次早退扣款（分）
            - absent_days: 旷工天数
            - perf_coefficient: 绩效系数（100=标准）
            - sales_amount_fen: 销售额（分）
            - commission_rate: 提成比例
            - full_attendance_bonus_fen: 全勤奖金额（分）
            - seniority_months: 工龄月数
            - social_base_fen: 社保基数（分）
            - housing_fund_base_fen: 公积金基数（分）
            - housing_fund_rate: 公积金比例
            - cumulative_prev_taxable_income_yuan: 截至上月累计应税收入（元）
            - cumulative_prev_tax_yuan: 截至上月累计已预扣税额（元）
            - month_index: 当年第几个月
            - special_deduction_yuan: 专项附加扣除（元）
        enabled_items: 启用的薪资项目编码列表

    Returns:
        {
            "items": [{"item_code": str, "item_name": str, "amount_fen": int}, ...],
            "gross_fen": int,       # 应发合计
            "total_deduction_fen": int,  # 扣款合计（不含个税）
            "social_personal_fen": int,  # 社保个人合计
            "tax_fen": int,         # 个人所得税
            "net_fen": int,         # 实发工资
        }
    """
    d = employee_data
    base = d.get("base_salary_fen", 0)
    position_salary = d.get("position_salary_fen", 0)
    att_days = d.get("attendance_days", 0)
    work_days = d.get("work_days_in_month", 21.75)
    weekday_ot = d.get("weekday_ot_hours", 0)
    weekend_ot = d.get("weekend_ot_hours", 0)
    holiday_ot = d.get("holiday_ot_hours", 0)
    personal_leave = d.get("personal_leave_days", 0)
    sick_leave = d.get("sick_leave_days", 0)
    late_count = d.get("late_count", 0)
    late_ded_per = d.get("late_deduction_per_time_fen", 5000)
    early_count = d.get("early_leave_count", 0)
    early_ded_per = d.get("early_leave_deduction_per_time_fen", 5000)
    absent_days = d.get("absent_days", 0)
    perf_coeff = d.get("perf_coefficient", 100)
    sales_fen = d.get("sales_amount_fen", 0)
    comm_rate = d.get("commission_rate", 0.0)
    fa_bonus = d.get("full_attendance_bonus_fen", 30000)
    seniority = d.get("seniority_months", 0)
    social_base = d.get("social_base_fen", base)
    hf_base = d.get("housing_fund_base_fen", base)
    hf_rate = d.get("housing_fund_rate", 0.07)

    # 时薪
    hourly_rate = derive_hourly_rate(base, int(work_days)) if work_days > 0 else 0

    # 计算各项金额的映射
    enabled_set = set(enabled_items)
    result_items: List[Dict[str, Any]] = []
    gross_fen = 0
    deduction_fen = 0
    social_personal_fen = 0

    def _add(code: str, amount: int) -> None:
        nonlocal gross_fen, deduction_fen, social_personal_fen
        item = _ITEM_INDEX.get(code)
        if item is None:
            return
        result_items.append(
            {
                "item_code": code,
                "item_name": item.item_name,
                "amount_fen": amount,
            }
        )
        if item.tax_type == "pre_tax_add":
            gross_fen += amount
        elif item.tax_type == "pre_tax_sub":
            if item.category == "social":
                social_personal_fen += amount
            else:
                deduction_fen += amount

    # ── 出勤类 ──
    if "ATT_001" in enabled_set:
        _add("ATT_001", base)
    if "ATT_002" in enabled_set:
        _add("ATT_002", position_salary)
    if "ATT_005" in enabled_set:
        att_salary = compute_base_salary(base, att_days, int(work_days))
        _add("ATT_005", att_salary)

    # ── 绩效类 ──
    if "PERF_001" in enabled_set:
        perf_bonus = compute_performance_bonus(base, perf_coeff / 100.0)
        _add("PERF_001", perf_bonus)
    if "PERF_010" in enabled_set:
        absence_total = max(0, work_days - att_days) + personal_leave + sick_leave + absent_days
        fa = compute_full_attendance_bonus(absence_total, late_count, early_count, fa_bonus)
        _add("PERF_010", fa)

    # ── 提成类 ──
    if "COMM_001" in enabled_set and sales_fen > 0:
        commission = compute_commission(sales_fen, comm_rate)
        _add("COMM_001", commission)

    # ── 补贴类 ──
    if "SUB_003" in enabled_set:
        _add("SUB_003", d.get("meal_allowance_fen", 30000))
    if "SUB_002" in enabled_set:
        _add("SUB_002", d.get("transport_allowance_fen", 20000))
    if "SUB_004" in enabled_set:
        _add("SUB_004", d.get("housing_allowance_fen", 50000))
    if "SUB_005" in enabled_set:
        _add("SUB_005", d.get("high_temp_allowance_fen", 30000))
    if "SUB_001" in enabled_set:
        seniority_sub = compute_seniority_subsidy(seniority)
        _add("SUB_001", seniority_sub)
    if "SUB_006" in enabled_set:
        night_sub = d.get("night_shift_days", 0) * d.get("night_shift_rate_fen", 5000)
        _add("SUB_006", night_sub)

    # ── 扣款类 ──
    if "DED_001" in enabled_set and late_count > 0:
        late_ded = compute_late_deduction(late_count, late_ded_per)
        _add("DED_001", late_ded)
    if "DED_002" in enabled_set and early_count > 0:
        early_ded = compute_early_leave_deduction(early_count, early_ded_per)
        _add("DED_002", early_ded)
    if "DED_003" in enabled_set and absent_days > 0:
        absent_ded = int(compute_absence_deduction(base, absent_days, int(work_days)) * 3)
        _add("DED_003", absent_ded)
    if "DED_007" in enabled_set:
        borrow = d.get("borrow_deduction_fen", 0)
        if borrow > 0:
            _add("DED_007", borrow)

    # ── 假期扣款 ──
    if "LV_003" in enabled_set and personal_leave > 0:
        leave_ded = compute_absence_deduction(base, personal_leave, int(work_days))
        _add("LV_003", leave_ded)

    # ── 社保类 ──
    if "SOC_001" in enabled_set:
        pension_personal = int(social_base * 0.08)
        _add("SOC_001", pension_personal)
    if "SOC_002" in enabled_set:
        medical_personal = int(social_base * 0.02)
        _add("SOC_002", medical_personal)
    if "SOC_003" in enabled_set:
        unemployment_personal = int(social_base * 0.005)
        _add("SOC_003", unemployment_personal)
    if "SOC_004" in enabled_set:
        hf_personal = int(hf_base * hf_rate)
        _add("SOC_004", hf_personal)

    # ── 个税计算 ──
    taxable_yuan = max(0, gross_fen - deduction_fen - social_personal_fen) / 100.0
    cum_prev_income = d.get("cumulative_prev_taxable_income_yuan", 0.0)
    cum_prev_tax = d.get("cumulative_prev_tax_yuan", 0.0)
    month_idx = d.get("month_index", 1)
    special_ded = d.get("special_deduction_yuan", 0.0)

    monthly_tax_yuan = compute_monthly_tax(
        current_month_taxable_income_yuan=taxable_yuan,
        cumulative_prev_taxable_income_yuan=cum_prev_income,
        cumulative_prev_tax_yuan=cum_prev_tax,
        social_insurance_yuan=0.0,
        housing_fund_yuan=0.0,
        special_deduction_yuan=special_ded,
        month_index=month_idx,
    )
    tax_fen = int(monthly_tax_yuan * 100)

    # 实发 = 应发 - 扣款 - 社保个人 - 个税
    net_fen = gross_fen - deduction_fen - social_personal_fen - tax_fen

    return {
        "items": result_items,
        "gross_fen": gross_fen,
        "total_deduction_fen": deduction_fen,
        "social_personal_fen": social_personal_fen,
        "tax_fen": tax_fen,
        "net_fen": net_fen,
    }
