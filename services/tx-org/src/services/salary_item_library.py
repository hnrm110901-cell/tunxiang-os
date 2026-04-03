"""
薪资项目库 -- 餐饮行业通用薪资项目定义（约70项）

参考商龙i人事138项薪资库，精简为餐饮行业通用项目。
7大分类：出勤/加班/假期/绩效/补贴/扣款/社保。
金额单位统一为"分"（fen）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from services.payroll_engine import (
    compute_absence_deduction,
    compute_base_salary,
    compute_commission,
    compute_early_leave_deduction,
    compute_full_attendance_bonus,
    compute_late_deduction,
    compute_monthly_tax,
    compute_overtime_pay,
    compute_performance_bonus,
    compute_seniority_subsidy,
    derive_hourly_rate,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  数据结构
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class SalaryItem:
    item_code: str          # 如 "BASE_001"
    item_name: str          # 如 "基本工资"
    category: str           # attendance/overtime/leave/performance/subsidy/deduction/social
    tax_type: str           # pre_tax_add / pre_tax_sub / other
    calc_rule: str          # fixed / formula / manual
    formula: str            # 计算公式（如有）
    is_required: bool       # 是否必填
    default_value_fen: int  # 默认值（分）
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7大分类定义
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SALARY_ITEMS: Dict[str, List[SalaryItem]] = {
    # ── 出勤类（10项） ──
    "attendance": [
        SalaryItem("ATT_001", "基本工资", "attendance", "pre_tax_add", "fixed", "", True, 0, "月薪标准，按出勤比例折算"),
        SalaryItem("ATT_002", "岗位工资", "attendance", "pre_tax_add", "fixed", "", False, 0, "岗位等级对应的固定工资"),
        SalaryItem("ATT_003", "出勤天数", "attendance", "other", "manual", "", True, 0, "当月实际出勤天数"),
        SalaryItem("ATT_004", "应出勤天数", "attendance", "other", "formula", "work_days_in_month", True, 0, "当月应出勤工作日数"),
        SalaryItem("ATT_005", "出勤工资", "attendance", "pre_tax_add", "formula", "base_salary_fen * attendance_days / work_days_in_month", True, 0, "按出勤比例折算的实际基本工资"),
        SalaryItem("ATT_006", "缺勤天数", "attendance", "other", "formula", "work_days_in_month - attendance_days", False, 0, "当月缺勤天数"),
        SalaryItem("ATT_007", "缺勤扣款", "attendance", "pre_tax_sub", "formula", "base_salary_fen * absence_days / work_days_in_month", False, 0, "按日薪扣除缺勤天数对应工资"),
        SalaryItem("ATT_008", "试用期工资", "attendance", "pre_tax_add", "formula", "base_salary_fen * 0.8", False, 0, "试用期按基本工资80%发放"),
        SalaryItem("ATT_009", "计件工资", "attendance", "pre_tax_add", "formula", "piece_count * piece_rate_fen", False, 0, "按件计薪（适用后厨切配等岗位）"),
        SalaryItem("ATT_010", "时薪工资", "attendance", "pre_tax_add", "formula", "hourly_rate_fen * work_hours", False, 0, "小时工按实际工时计算"),
    ],

    # ── 加班类（8项） ──
    "overtime": [
        SalaryItem("OT_001", "工作日加班时长", "overtime", "other", "manual", "", False, 0, "工作日加班小时数"),
        SalaryItem("OT_002", "工作日加班工资", "overtime", "pre_tax_add", "formula", "base_salary_fen / 21.75 / 8 * weekday_ot_hours * 1.5", False, 0, "工作日加班1.5倍工资"),
        SalaryItem("OT_003", "休息日加班时长", "overtime", "other", "manual", "", False, 0, "周末加班小时数"),
        SalaryItem("OT_004", "休息日加班工资", "overtime", "pre_tax_add", "formula", "base_salary_fen / 21.75 / 8 * weekend_ot_hours * 2.0", False, 0, "休息日加班2倍工资"),
        SalaryItem("OT_005", "节假日加班时长", "overtime", "other", "manual", "", False, 0, "法定节假日加班小时数"),
        SalaryItem("OT_006", "节假日加班工资", "overtime", "pre_tax_add", "formula", "base_salary_fen / 21.75 / 8 * holiday_ot_hours * 3.0", False, 0, "法定节假日加班3倍工资"),
        SalaryItem("OT_007", "加班费合计", "overtime", "pre_tax_add", "formula", "weekday_ot_pay + weekend_ot_pay + holiday_ot_pay", False, 0, "所有加班费汇总"),
        SalaryItem("OT_008", "加班调休抵扣", "overtime", "pre_tax_sub", "formula", "comp_off_hours * hourly_rate_fen * ot_multiplier", False, 0, "已调休的加班时长对应金额抵扣"),
    ],

    # ── 假期类（10项） ──
    "leave": [
        SalaryItem("LV_001", "事假天数", "leave", "other", "manual", "", False, 0, "当月事假天数"),
        SalaryItem("LV_002", "事假扣款", "leave", "pre_tax_sub", "formula", "base_salary_fen / work_days_in_month * personal_leave_days", False, 0, "事假按日薪扣除"),
        SalaryItem("LV_003", "病假天数", "leave", "other", "manual", "", False, 0, "当月病假天数"),
        SalaryItem("LV_004", "病假扣款", "leave", "pre_tax_sub", "formula", "base_salary_fen / work_days_in_month * sick_leave_days * 0.4", False, 0, "病假扣日薪40%"),
        SalaryItem("LV_005", "年假天数", "leave", "other", "manual", "", False, 0, "已使用年假天数（带薪）"),
        SalaryItem("LV_006", "年假未休补偿", "leave", "pre_tax_add", "formula", "base_salary_fen / 21.75 * unused_annual_days * 2", False, 0, "年假未休按日薪200%补偿"),
        SalaryItem("LV_007", "调休天数", "leave", "other", "manual", "", False, 0, "已使用调休天数（带薪）"),
        SalaryItem("LV_008", "婚假天数", "leave", "other", "manual", "", False, 0, "婚假天数（带薪）"),
        SalaryItem("LV_009", "产假/陪产假天数", "leave", "other", "manual", "", False, 0, "产假或陪产假天数"),
        SalaryItem("LV_010", "丧假天数", "leave", "other", "manual", "", False, 0, "丧假天数（带薪）"),
    ],

    # ── 绩效类（12项） ──
    "performance": [
        SalaryItem("PERF_001", "绩效系数", "performance", "other", "manual", "", False, 100, "绩效评分系数（100=标准，120=优秀）"),
        SalaryItem("PERF_002", "绩效奖金", "performance", "pre_tax_add", "formula", "base_salary_fen * max(0, perf_coefficient - 100) / 100", False, 0, "绩效系数超过100部分对应奖金"),
        SalaryItem("PERF_003", "销售提成", "performance", "pre_tax_add", "formula", "sales_amount_fen * commission_rate", False, 0, "按销售额比例提成"),
        SalaryItem("PERF_004", "服务员提成", "performance", "pre_tax_add", "formula", "service_revenue_fen * waiter_commission_rate", False, 0, "服务员个人服务流水提成"),
        SalaryItem("PERF_005", "厨师提成", "performance", "pre_tax_add", "formula", "kitchen_revenue_fen * chef_commission_rate", False, 0, "厨师出品量/菜品销售提成"),
        SalaryItem("PERF_006", "全勤奖", "performance", "pre_tax_add", "fixed", "", False, 30000, "当月无缺勤/迟到/早退发放，默认300元"),
        SalaryItem("PERF_007", "门店利润分红", "performance", "pre_tax_add", "formula", "store_profit_fen * profit_share_rate", False, 0, "店长/核心员工参与门店利润分红"),
        SalaryItem("PERF_008", "季度奖金", "performance", "pre_tax_add", "manual", "", False, 0, "季度考核奖金"),
        SalaryItem("PERF_009", "年终奖", "performance", "pre_tax_add", "manual", "", False, 0, "年度绩效奖金"),
        SalaryItem("PERF_010", "推荐奖", "performance", "pre_tax_add", "fixed", "", False, 0, "推荐新员工入职奖励"),
        SalaryItem("PERF_011", "优秀员工奖", "performance", "pre_tax_add", "manual", "", False, 0, "月度/季度优秀员工评选奖金"),
        SalaryItem("PERF_012", "阶梯提成", "performance", "pre_tax_add", "formula", "tiered_commission(sales_amount_fen, tiers)", False, 0, "销售额分段阶梯提成"),
    ],

    # ── 补贴类（10项） ──
    "subsidy": [
        SalaryItem("SUB_001", "餐补", "subsidy", "pre_tax_add", "fixed", "", False, 30000, "员工餐补贴，默认300元/月"),
        SalaryItem("SUB_002", "交通补贴", "subsidy", "pre_tax_add", "fixed", "", False, 20000, "交通补贴，默认200元/月"),
        SalaryItem("SUB_003", "住宿补贴", "subsidy", "pre_tax_add", "fixed", "", False, 50000, "未住员工宿舍的住宿补贴，默认500元/月"),
        SalaryItem("SUB_004", "高温补贴", "subsidy", "pre_tax_add", "fixed", "", False, 30000, "6-9月高温补贴（厨师等高温岗位），默认300元/月"),
        SalaryItem("SUB_005", "工龄补贴", "subsidy", "pre_tax_add", "formula", "seniority_subsidy(seniority_months)", False, 0, "按工龄阶梯发放，满1年起"),
        SalaryItem("SUB_006", "夜班补贴", "subsidy", "pre_tax_add", "formula", "night_shift_days * night_shift_rate_fen", False, 0, "夜班天数 x 每日夜班补贴"),
        SalaryItem("SUB_007", "通讯补贴", "subsidy", "pre_tax_add", "fixed", "", False, 10000, "手机通讯补贴，默认100元/月"),
        SalaryItem("SUB_008", "技能补贴", "subsidy", "pre_tax_add", "fixed", "", False, 0, "持证上岗技能补贴（厨师证/食品安全证等）"),
        SalaryItem("SUB_009", "节日福利", "subsidy", "pre_tax_add", "manual", "", False, 0, "节日慰问金/礼品折现"),
        SalaryItem("SUB_010", "生日福利", "subsidy", "pre_tax_add", "fixed", "", False, 20000, "员工生日当月福利，默认200元"),
    ],

    # ── 扣款类（10项） ──
    "deduction": [
        SalaryItem("DED_001", "迟到扣款", "deduction", "pre_tax_sub", "formula", "late_count * late_deduction_per_time_fen", False, 0, "迟到次数 x 每次扣款金额"),
        SalaryItem("DED_002", "早退扣款", "deduction", "pre_tax_sub", "formula", "early_leave_count * early_leave_deduction_per_time_fen", False, 0, "早退次数 x 每次扣款金额"),
        SalaryItem("DED_003", "旷工扣款", "deduction", "pre_tax_sub", "formula", "base_salary_fen / work_days_in_month * absent_days * 3", False, 0, "旷工按日薪3倍扣款"),
        SalaryItem("DED_004", "赔偿扣款", "deduction", "pre_tax_sub", "manual", "", False, 0, "餐具/设备损坏等赔偿扣款"),
        SalaryItem("DED_005", "借支扣款", "deduction", "pre_tax_sub", "manual", "", False, 0, "预借工资扣回"),
        SalaryItem("DED_006", "水电费扣款", "deduction", "pre_tax_sub", "fixed", "", False, 0, "住员工宿舍的水电分摊"),
        SalaryItem("DED_007", "违纪扣款", "deduction", "pre_tax_sub", "manual", "", False, 0, "违反公司规章制度处罚"),
        SalaryItem("DED_008", "卫生扣款", "deduction", "pre_tax_sub", "manual", "", False, 0, "卫生检查不达标处罚"),
        SalaryItem("DED_009", "服装扣款", "deduction", "pre_tax_sub", "fixed", "", False, 0, "工装费用扣除（离职结算）"),
        SalaryItem("DED_010", "其他扣款", "deduction", "pre_tax_sub", "manual", "", False, 0, "其他需要扣除的款项"),
    ],

    # ── 社保类（10项） ──
    "social": [
        SalaryItem("SOC_001", "养老保险-个人", "social", "pre_tax_sub", "formula", "social_base_fen * 0.08", True, 0, "养老保险个人缴纳8%"),
        SalaryItem("SOC_002", "医疗保险-个人", "social", "pre_tax_sub", "formula", "social_base_fen * 0.02", True, 0, "医疗保险个人缴纳2%"),
        SalaryItem("SOC_003", "失业保险-个人", "social", "pre_tax_sub", "formula", "social_base_fen * 0.005", True, 0, "失业保险个人缴纳0.5%"),
        SalaryItem("SOC_004", "公积金-个人", "social", "pre_tax_sub", "formula", "housing_fund_base_fen * housing_fund_rate", False, 0, "住房公积金个人缴纳（5%-12%）"),
        SalaryItem("SOC_005", "养老保险-企业", "social", "other", "formula", "social_base_fen * 0.16", True, 0, "养老保险企业缴纳16%"),
        SalaryItem("SOC_006", "医疗保险-企业", "social", "other", "formula", "social_base_fen * 0.08", True, 0, "医疗保险企业缴纳8%"),
        SalaryItem("SOC_007", "失业保险-企业", "social", "other", "formula", "social_base_fen * 0.005", True, 0, "失业保险企业缴纳0.5%"),
        SalaryItem("SOC_008", "工伤保险-企业", "social", "other", "formula", "social_base_fen * 0.004", True, 0, "工伤保险企业缴纳0.4%（餐饮行业）"),
        SalaryItem("SOC_009", "公积金-企业", "social", "other", "formula", "housing_fund_base_fen * housing_fund_rate", False, 0, "住房公积金企业缴纳（与个人同比例）"),
        SalaryItem("SOC_010", "大病医疗-个人", "social", "pre_tax_sub", "fixed", "", False, 0, "大病医疗补充保险个人部分（部分地区有）"),
    ],
}

# 所有分类
CATEGORIES = {
    "attendance": "出勤类",
    "overtime": "加班类",
    "leave": "假期类",
    "performance": "绩效类",
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
            "ATT_001", "ATT_003", "ATT_004", "ATT_005", "ATT_006", "ATT_007",
            # 加班
            "OT_001", "OT_002", "OT_003", "OT_004", "OT_007",
            # 假期
            "LV_001", "LV_002", "LV_003", "LV_004", "LV_005", "LV_007",
            # 绩效
            "PERF_001", "PERF_002", "PERF_003", "PERF_004", "PERF_005", "PERF_006",
            # 补贴
            "SUB_001", "SUB_002", "SUB_005", "SUB_006",
            # 扣款
            "DED_001", "DED_002", "DED_003", "DED_004", "DED_005", "DED_007",
            # 社保
            "SOC_001", "SOC_002", "SOC_003", "SOC_004", "SOC_005", "SOC_006", "SOC_007", "SOC_008", "SOC_009",
        ],
        "default_overrides": {
            "ATT_001": 500000,   # 基本工资默认5000元
            "SUB_001": 30000,    # 餐补300元
            "SUB_002": 20000,    # 交通补贴200元
            "PERF_006": 30000,   # 全勤奖300元
        },
    },
    "seafood": {
        "name": "海鲜酒楼",
        "description": "适用于海鲜酒楼等高端餐饮",
        "enabled_items": [
            # 出勤
            "ATT_001", "ATT_002", "ATT_003", "ATT_004", "ATT_005", "ATT_006", "ATT_007",
            # 加班
            "OT_001", "OT_002", "OT_003", "OT_004", "OT_005", "OT_006", "OT_007",
            # 假期
            "LV_001", "LV_002", "LV_003", "LV_004", "LV_005", "LV_006", "LV_007",
            # 绩效
            "PERF_001", "PERF_002", "PERF_003", "PERF_004", "PERF_005", "PERF_006",
            "PERF_007", "PERF_008", "PERF_012",
            # 补贴
            "SUB_001", "SUB_002", "SUB_003", "SUB_004", "SUB_005", "SUB_006",
            "SUB_007", "SUB_008",
            # 扣款
            "DED_001", "DED_002", "DED_003", "DED_004", "DED_005", "DED_006",
            "DED_007", "DED_008",
            # 社保
            "SOC_001", "SOC_002", "SOC_003", "SOC_004", "SOC_005", "SOC_006",
            "SOC_007", "SOC_008", "SOC_009", "SOC_010",
        ],
        "default_overrides": {
            "ATT_001": 600000,   # 基本工资默认6000元
            "ATT_002": 100000,   # 岗位工资默认1000元
            "SUB_001": 50000,    # 餐补500元
            "SUB_002": 30000,    # 交通补贴300元
            "SUB_003": 50000,    # 住宿补贴500元
            "PERF_006": 50000,   # 全勤奖500元
        },
    },
    "fast_food": {
        "name": "快餐",
        "description": "适用于快餐、小吃等轻餐饮",
        "enabled_items": [
            # 出勤
            "ATT_001", "ATT_003", "ATT_004", "ATT_005", "ATT_006", "ATT_007", "ATT_010",
            # 加班
            "OT_001", "OT_002", "OT_007",
            # 假期
            "LV_001", "LV_002", "LV_003", "LV_004",
            # 绩效
            "PERF_001", "PERF_002", "PERF_006",
            # 补贴
            "SUB_001", "SUB_002", "SUB_005",
            # 扣款
            "DED_001", "DED_002", "DED_003", "DED_005", "DED_007",
            # 社保
            "SOC_001", "SOC_002", "SOC_003", "SOC_005", "SOC_006", "SOC_007", "SOC_008",
        ],
        "default_overrides": {
            "ATT_001": 380000,   # 基本工资默认3800元
            "SUB_001": 20000,    # 餐补200元
            "SUB_002": 15000,    # 交通补贴150元
            "PERF_006": 20000,   # 全勤奖200元
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
#  公共 API
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
    """为新门店初始化薪资配置

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
        result_items.append({
            "item_code": code,
            "item_name": item.item_name,
            "amount_fen": amount,
        })
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
    if "ATT_007" in enabled_set:
        absence = max(0, work_days - att_days)
        absence_ded = compute_absence_deduction(base, absence, int(work_days))
        _add("ATT_007", absence_ded)

    # ── 加班类 ──
    weekday_ot_pay = 0
    weekend_ot_pay = 0
    holiday_ot_pay = 0
    if "OT_002" in enabled_set and weekday_ot > 0:
        weekday_ot_pay = compute_overtime_pay(hourly_rate, weekday_ot, "weekday")
        _add("OT_002", weekday_ot_pay)
    if "OT_004" in enabled_set and weekend_ot > 0:
        weekend_ot_pay = compute_overtime_pay(hourly_rate, weekend_ot, "weekend")
        _add("OT_004", weekend_ot_pay)
    if "OT_006" in enabled_set and holiday_ot > 0:
        holiday_ot_pay = compute_overtime_pay(hourly_rate, holiday_ot, "holiday")
        _add("OT_006", holiday_ot_pay)
    if "OT_007" in enabled_set:
        total_ot = weekday_ot_pay + weekend_ot_pay + holiday_ot_pay
        _add("OT_007", total_ot)

    # ── 假期类 ──
    if "LV_002" in enabled_set and personal_leave > 0:
        leave_ded = compute_absence_deduction(base, personal_leave, int(work_days))
        _add("LV_002", leave_ded)
    if "LV_004" in enabled_set and sick_leave > 0:
        sick_ded = int(compute_absence_deduction(base, sick_leave, int(work_days)) * 0.4)
        _add("LV_004", sick_ded)

    # ── 绩效类 ──
    if "PERF_002" in enabled_set:
        perf_bonus = compute_performance_bonus(base, perf_coeff / 100.0)
        _add("PERF_002", perf_bonus)
    if "PERF_003" in enabled_set and sales_fen > 0:
        commission = compute_commission(sales_fen, comm_rate)
        _add("PERF_003", commission)
    if "PERF_006" in enabled_set:
        absence_total = max(0, work_days - att_days) + personal_leave + sick_leave + absent_days
        fa = compute_full_attendance_bonus(absence_total, late_count, early_count, fa_bonus)
        _add("PERF_006", fa)

    # ── 补贴类 ──
    if "SUB_001" in enabled_set:
        _add("SUB_001", d.get("meal_allowance_fen", 30000))
    if "SUB_002" in enabled_set:
        _add("SUB_002", d.get("transport_allowance_fen", 20000))
    if "SUB_003" in enabled_set:
        _add("SUB_003", d.get("housing_allowance_fen", 50000))
    if "SUB_004" in enabled_set:
        _add("SUB_004", d.get("high_temp_allowance_fen", 30000))
    if "SUB_005" in enabled_set:
        seniority_sub = compute_seniority_subsidy(seniority)
        _add("SUB_005", seniority_sub)
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
    if "DED_005" in enabled_set:
        borrow = d.get("borrow_deduction_fen", 0)
        if borrow > 0:
            _add("DED_005", borrow)

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
    # 应税收入 = 应发 - 扣款 - 社保个人
    taxable_yuan = max(0, gross_fen - deduction_fen - social_personal_fen) / 100.0
    cum_prev_income = d.get("cumulative_prev_taxable_income_yuan", 0.0)
    cum_prev_tax = d.get("cumulative_prev_tax_yuan", 0.0)
    month_idx = d.get("month_index", 1)
    special_ded = d.get("special_deduction_yuan", 0.0)

    monthly_tax_yuan = compute_monthly_tax(
        current_month_taxable_income_yuan=taxable_yuan,
        cumulative_prev_taxable_income_yuan=cum_prev_income,
        cumulative_prev_tax_yuan=cum_prev_tax,
        social_insurance_yuan=0.0,  # 已在taxable_yuan中扣除
        housing_fund_yuan=0.0,      # 已在taxable_yuan中扣除
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
