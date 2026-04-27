"""
薪资计算引擎 -- 纯函数实现（无 DB 依赖）

从 V2.x salary_formula_engine.py + payroll_service.py 迁移提取。
所有函数接受参数、返回结果，不依赖数据库或外部服务。

核心能力：
- 基本工资计算（按出勤比例）
- 加班费计算（工作日/周末/法定节假日倍率）
- 提成计算（阶梯/固定比例）
- 考勤扣款（缺勤/迟到/早退）
- 绩效奖金
- 工龄补贴（阶梯式）
- 全勤奖判定
- 个税累计预扣法（7 级超额累进税率）
- 薪资汇总
- 公式校验

金额单位统一为"分"（fen），与 V2.x 保持一致。
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

# ── 个税税率表（7 级超额累进，年度累计应纳税所得额，单位：元） ─────────
TAX_BRACKETS: List[Tuple[float, float, float]] = [
    (36_000, 0.03, 0),
    (144_000, 0.10, 2_520),
    (300_000, 0.20, 16_920),
    (420_000, 0.25, 31_920),
    (660_000, 0.30, 52_920),
    (960_000, 0.35, 85_920),
    (float("inf"), 0.45, 181_920),
]

# 每月基本减除费用（元）
MONTHLY_EXEMPTION_YUAN: float = 5_000

# 工龄补贴阶梯（月范围左闭右开 → 补贴分/月）
SENIORITY_SUBSIDY_TABLE: List[Tuple[int, int, int]] = [
    (13, 24, 5_000),  # 13-23 月: 50 元/月
    (24, 36, 10_000),  # 24-35 月: 100 元/月
    (36, 48, 15_000),  # 36-47 月: 150 元/月
    (48, 99_999, 20_000),  # 48 月以上: 200 元/月
]

# 金额上限：100_000_000 分 = 100 万元，超过视为公式异常
MAX_AMOUNT_FEN: int = 100_000_000

# 中文方括号变量正则（用于公式校验）
VARIABLE_PATTERN = re.compile(r"【(.+?)】")

# 所有已知变量名
KNOWN_VARIABLES = {
    "基本工资",
    "岗位补贴",
    "餐补",
    "交通补贴",
    "时薪",
    "绩效系数",
    "绩效标准",
    "月自然天数",
    "月工作日数",
    "总出勤天数",
    "工作日出勤天数",
    "法定节日出勤天数",
    "周末出勤天数",
    "缺勤天数",
    "迟到次数",
    "加班小时数",
    "请假天数",
    "月最低工资",
    "小时最低工资",
    "日薪标准",
    "司龄月数",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  基本工资
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_base_salary(
    base_salary_fen: int,
    attendance_days: float,
    work_days_in_month: int,
) -> int:
    """
    按出勤比例计算当月基本工资。

    Args:
        base_salary_fen: 月薪标准（分）
        attendance_days: 实际出勤天数
        work_days_in_month: 当月应出勤工作日数

    Returns:
        当月应发基本工资（分）
    """
    if work_days_in_month <= 0:
        return 0
    ratio = min(attendance_days / work_days_in_month, 1.0)
    return int(base_salary_fen * ratio)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  加班费
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_overtime_pay(
    hourly_rate_fen: int,
    overtime_hours: float,
    overtime_type: str = "weekday",
) -> int:
    """
    计算加班费。

    Args:
        hourly_rate_fen: 小时工资标准（分）
        overtime_hours: 加班小时数
        overtime_type: 加班类型 weekday(1.5x) / weekend(2.0x) / holiday(3.0x)

    Returns:
        加班费（分）
    """
    rate_map = {"weekday": 1.5, "weekend": 2.0, "holiday": 3.0}
    multiplier = rate_map.get(overtime_type, 1.5)
    return int(hourly_rate_fen * multiplier * overtime_hours)


def derive_hourly_rate(
    base_salary_fen: int,
    work_days_in_month: int,
    hours_per_day: int = 8,
) -> int:
    """
    从月薪推算时薪（分）。

    Args:
        base_salary_fen: 月薪标准（分）
        work_days_in_month: 当月工作日数
        hours_per_day: 每日标准工时

    Returns:
        时薪（分）
    """
    total_hours = work_days_in_month * hours_per_day
    if total_hours <= 0:
        return 0
    return int(base_salary_fen / total_hours)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  提成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_commission(
    sales_amount_fen: int,
    commission_rate: float,
) -> int:
    """
    固定比例提成。

    Args:
        sales_amount_fen: 销售额（分）
        commission_rate: 提成比例（如 0.05 表示 5%）

    Returns:
        提成金额（分）
    """
    return int(sales_amount_fen * commission_rate)


def compute_tiered_commission(
    sales_amount_fen: int,
    tiers: List[Tuple[int, float]],
) -> int:
    """
    阶梯提成：按销售额区间分段计算。

    Args:
        sales_amount_fen: 销售额（分）
        tiers: 阶梯列表 [(上限分, 该段费率), ...]
               需按上限升序排列，最后一档上限应足够大。
               例如: [(500_000, 0.03), (1_000_000, 0.05), (INF, 0.08)]

    Returns:
        提成金额（分）
    """
    if not tiers:
        return 0
    total = 0
    prev_upper = 0
    for upper_fen, rate in sorted(tiers, key=lambda t: t[0]):
        if sales_amount_fen <= prev_upper:
            break
        taxable = min(sales_amount_fen, upper_fen) - prev_upper
        if taxable > 0:
            total += int(taxable * rate)
        prev_upper = upper_fen
    return total


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  考勤扣款
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_absence_deduction(
    base_salary_fen: int,
    absence_days: float,
    work_days_in_month: int,
) -> int:
    """
    缺勤扣款 = 日薪 x 缺勤天数。

    Returns:
        扣款金额（分，正数）
    """
    if work_days_in_month <= 0:
        return 0
    daily_rate = int(base_salary_fen / work_days_in_month)
    return int(daily_rate * absence_days)


def compute_late_deduction(
    late_count: int,
    deduction_per_time_fen: int,
) -> int:
    """
    迟到扣款 = 迟到次数 x 每次扣款金额。

    Returns:
        扣款金额（分，正数）
    """
    return max(0, late_count * deduction_per_time_fen)


def compute_early_leave_deduction(
    early_leave_count: int,
    deduction_per_time_fen: int,
) -> int:
    """
    早退扣款 = 早退次数 x 每次扣款金额。

    Returns:
        扣款金额（分，正数）
    """
    return max(0, early_leave_count * deduction_per_time_fen)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  绩效奖金
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_performance_bonus(
    base_salary_fen: int,
    performance_coefficient: float,
) -> int:
    """
    绩效奖金 = 基本工资 x max(0, 绩效系数 - 1)。
    系数 > 1 才有奖金，等于或小于 1 时为 0。

    Args:
        base_salary_fen: 基本工资（分）
        performance_coefficient: 绩效系数（如 1.2 表示 120%）

    Returns:
        绩效奖金（分）
    """
    bonus_factor = max(0.0, performance_coefficient - 1.0)
    return int(base_salary_fen * bonus_factor)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  工龄补贴
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_seniority_subsidy(
    seniority_months: int,
    subsidy_table: Optional[List[Tuple[int, int, int]]] = None,
) -> int:
    """
    按工龄阶梯表计算每月工龄补贴。

    Args:
        seniority_months: 司龄月数
        subsidy_table: 阶梯表 [(起始月, 截止月, 补贴分/月), ...]
                       默认使用 SENIORITY_SUBSIDY_TABLE

    Returns:
        工龄补贴（分/月）
    """
    table = subsidy_table or SENIORITY_SUBSIDY_TABLE
    for lower, upper, amount_fen in table:
        if lower <= seniority_months < upper:
            return amount_fen
    return 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  全勤奖
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_full_attendance_bonus(
    absence_days: float,
    late_count: int,
    early_leave_count: int,
    bonus_fen: int,
) -> int:
    """
    全勤奖：无缺勤、无迟到、无早退时才发放。

    Args:
        absence_days: 缺勤天数
        late_count: 迟到次数
        early_leave_count: 早退次数
        bonus_fen: 全勤奖金额（分）

    Returns:
        全勤奖（分），不满足条件返回 0
    """
    if absence_days > 0 or late_count > 0 or early_leave_count > 0:
        return 0
    return bonus_fen


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  个税（累计预扣法）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_tax_yuan(
    cumulative_taxable_income_yuan: float,
) -> Tuple[float, float, float]:
    """
    根据年度累计应纳税所得额（元），计算累计应纳税额。

    Args:
        cumulative_taxable_income_yuan: 年度累计应纳税所得额（元）

    Returns:
        (累计税额元, 适用税率, 速算扣除数元)
    """
    if cumulative_taxable_income_yuan <= 0:
        return (0.0, 0.0, 0)
    for upper, rate, quick_deduction in TAX_BRACKETS:
        if cumulative_taxable_income_yuan <= upper:
            tax = cumulative_taxable_income_yuan * rate - quick_deduction
            return (max(0.0, tax), rate, quick_deduction)
    # fallback
    rate = 0.45
    quick_deduction = 181_920
    tax = cumulative_taxable_income_yuan * rate - quick_deduction
    return (max(0.0, tax), rate, quick_deduction)


def compute_monthly_tax(
    current_month_taxable_income_yuan: float,
    cumulative_prev_taxable_income_yuan: float,
    cumulative_prev_tax_yuan: float,
    social_insurance_yuan: float = 0.0,
    housing_fund_yuan: float = 0.0,
    special_deduction_yuan: float = 0.0,
    month_index: int = 1,
) -> float:
    """
    累计预扣法计算当月个税（元）。

    Args:
        current_month_taxable_income_yuan: 当月应税收入（元，已扣除考勤扣款等）
        cumulative_prev_taxable_income_yuan: 截至上月累计应税收入（元）
        cumulative_prev_tax_yuan: 截至上月累计已预扣税额（元）
        social_insurance_yuan: 当月社保个人缴纳（元）
        housing_fund_yuan: 当月公积金个人缴纳（元）
        special_deduction_yuan: 当月专项附加扣除（元）
        month_index: 当年第几个月（用于计算累计减除费用）

    Returns:
        当月应预扣税额（元），不低于 0
    """
    # 累计应税收入
    cumulative_income = cumulative_prev_taxable_income_yuan + current_month_taxable_income_yuan
    # 累计减除费用
    cumulative_exemption = MONTHLY_EXEMPTION_YUAN * month_index
    # 累计扣除
    cumulative_deductions = (social_insurance_yuan + housing_fund_yuan + special_deduction_yuan) * month_index
    # 累计应纳税所得额
    cumulative_taxable = cumulative_income - cumulative_exemption - cumulative_deductions
    cumulative_taxable = max(0.0, cumulative_taxable)

    cumulative_tax, _, _ = compute_tax_yuan(cumulative_taxable)
    monthly_tax = cumulative_tax - cumulative_prev_tax_yuan
    return max(0.0, monthly_tax)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  工作日计算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def count_work_days(year: int, month: int) -> int:
    """
    计算指定月份的工作日数量（周一至周五，不含法定节假日调整）。

    Args:
        year: 年
        month: 月

    Returns:
        工作日数
    """
    days_in_month = calendar.monthrange(year, month)[1]
    return sum(1 for d in range(1, days_in_month + 1) if date(year, month, d).weekday() < 5)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  薪资汇总
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def summarize_payroll(
    base_salary_fen: int,
    position_allowance_fen: int = 0,
    meal_allowance_fen: int = 0,
    transport_allowance_fen: int = 0,
    performance_bonus_fen: int = 0,
    overtime_pay_fen: int = 0,
    commission_fen: int = 0,
    reward_fen: int = 0,
    seniority_subsidy_fen: int = 0,
    full_attendance_bonus_fen: int = 0,
    absence_deduction_fen: int = 0,
    late_deduction_fen: int = 0,
    early_leave_deduction_fen: int = 0,
    penalty_fen: int = 0,
    social_insurance_fen: int = 0,
    housing_fund_fen: int = 0,
    tax_fen: int = 0,
) -> Dict[str, Any]:
    """
    汇总薪资各项，计算应发/扣款/实发。

    Returns:
        {
            "gross_salary_fen": int,      # 应发合计
            "total_deduction_fen": int,   # 扣款合计
            "net_salary_fen": int,        # 实发
            "gross_salary_yuan": float,
            "total_deduction_yuan": float,
            "net_salary_yuan": float,
        }
    """
    gross = (
        base_salary_fen
        + position_allowance_fen
        + meal_allowance_fen
        + transport_allowance_fen
        + performance_bonus_fen
        + overtime_pay_fen
        + commission_fen
        + reward_fen
        + seniority_subsidy_fen
        + full_attendance_bonus_fen
    )
    total_deduction = (
        absence_deduction_fen
        + late_deduction_fen
        + early_leave_deduction_fen
        + penalty_fen
        + social_insurance_fen
        + housing_fund_fen
        + tax_fen
    )
    net = gross - total_deduction
    return {
        "gross_salary_fen": gross,
        "total_deduction_fen": total_deduction,
        "net_salary_fen": net,
        "gross_salary_yuan": gross / 100,
        "total_deduction_yuan": total_deduction / 100,
        "net_salary_yuan": net / 100,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  公式校验（从 V2.x SalaryFormulaEngine.validate_formula 迁移）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def validate_formula(
    formula: str,
    available_variables: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    校验薪资公式语法和变量引用。

    Args:
        formula: 公式字符串（支持中文方括号变量引用 【变量名】）
        available_variables: 额外可用的变量名列表

    Returns:
        {"valid": bool, "errors": [...], "warnings": [...]}
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not formula or not formula.strip():
        return {"valid": True, "errors": [], "warnings": ["空公式，将返回0"]}

    formula = formula.strip()

    # 1. 检查变量引用
    all_vars = KNOWN_VARIABLES.copy()
    if available_variables:
        all_vars.update(available_variables)

    referenced_vars = VARIABLE_PATTERN.findall(formula)
    for var in referenced_vars:
        if var not in all_vars:
            errors.append(f"未知变量: 【{var}】")

    # 2. 括号 / 花括号配对
    brace_depth = 0
    paren_depth = 0
    for ch in formula:
        if ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
        elif ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth -= 1
        if brace_depth < 0:
            errors.append("语法错误: 多余的 }")
            break
        if paren_depth < 0:
            errors.append("语法错误: 多余的 )")
            break
    if brace_depth > 0:
        errors.append("语法错误: 未匹配的 {")
    if paren_depth > 0:
        errors.append("语法错误: 未匹配的 (")

    # 3. 条件表达式基本检查
    if formula.startswith("如果"):
        if "则" not in formula:
            errors.append("条件语法错误: 缺少 '则' 关键字")
        if "{" not in formula or "}" not in formula:
            errors.append("条件语法错误: 条件分支必须用 { } 包裹表达式")

    # 4. 简单表达式试解析
    if not formula.startswith("如果"):
        test_expr = VARIABLE_PATTERN.sub("1", formula).replace(" ", "")
        allowed = set("0123456789+-*/.()%")
        if not all(c in allowed for c in test_expr):
            bad_chars = [c for c in test_expr if c not in allowed]
            errors.append(f"表达式包含非法字符: {''.join(set(bad_chars))}")
        else:
            try:
                eval(test_expr)  # nosec: 只含数字和运算符  # noqa: S307 — pre-existing, eval on trusted template config
            except ZeroDivisionError:
                warnings.append("表达式可能出现除零（运行时将返回0并告警）")
            except SyntaxError:
                errors.append("表达式语法错误: 数学表达式不合法")
            except (TypeError, NameError, ArithmeticError):
                errors.append("表达式语法错误: 无法解析")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def safe_eval_expression(
    formula: str,
    variables: Dict[str, float],
) -> int:
    """
    安全求值简单数学表达式（含中文方括号变量替换）。

    Args:
        formula: 表达式字符串
        variables: 变量名 -> 值（分）

    Returns:
        计算结果（分），除零返回 0，负值兜底为 0，上限 MAX_AMOUNT_FEN
    """
    if not formula or not formula.strip():
        return 0

    def _replace_var(match: re.Match) -> str:
        var_name = match.group(1)
        return str(variables.get(var_name, 0))

    expr = VARIABLE_PATTERN.sub(_replace_var, formula.strip())
    expr = expr.replace(" ", "")

    # 安全检查：只允许数字和基本运算符
    allowed = set("0123456789+-*/.()%")
    if not all(c in allowed for c in expr):
        return 0

    try:
        result = eval(expr)  # nosec: 已经过滤非法字符  # noqa: S307 — pre-existing, eval on trusted template config
    except ZeroDivisionError:
        return 0
    except (SyntaxError, TypeError, NameError, ArithmeticError):
        return 0

    result = int(result)
    result = max(0, result)
    result = min(result, MAX_AMOUNT_FEN)
    return result
