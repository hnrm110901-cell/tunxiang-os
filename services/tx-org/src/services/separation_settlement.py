"""离职结算服务 — N/N+1/2N 经济补偿金计算

依据《中华人民共和国劳动合同法》第四十六、四十七条。

补偿金规则：
  N = 工作年限（满6个月进1，不满6个月按0.5）
  基数 = 离职前12个月平均工资
  上限 = 当地社平工资3倍，且最多12年

  主动辞职(resign): 0
  过失性辞退(dismiss_fault): 0
  协商解除(mutual): N * 基数
  无过失性辞退(dismiss_no_fault): (N+1) * 基数（1个月代通知金）
  经济性裁员(layoff): N * 基数
  合同到期不续(contract_expire): N * 基数（企业不续签时）
  退休(retire): 0

离职经济补偿金个税：
  免税额 = 当地上年职工平均工资 * 3
  应税部分按单独计税（不并入综合所得）
  应税所得 / 工作年限（最多12年）= 折算月收入
  按月度税率表计税 * 工作年限

金额单位：分（fen）
"""

from __future__ import annotations

import math
from datetime import date
from typing import List, Optional, Tuple

import structlog

logger = structlog.get_logger()


# ── 离职类型 ──────────────────────────────────────────────────
SEPARATION_TYPES = {
    "resign": "主动辞职",
    "mutual": "协商解除",
    "dismiss_fault": "过失性辞退",
    "dismiss_no_fault": "无过失性辞退",
    "layoff": "经济性裁员",
    "contract_expire": "合同到期不续",
    "retire": "退休",
}

# 有经济补偿金的离职类型
COMPENSABLE_TYPES = {"mutual", "dismiss_no_fault", "layoff", "contract_expire"}

# 需要代通知金的类型（N+1 中的 +1）
NOTICE_PAY_TYPES = {"dismiss_no_fault"}

# ── 长沙市 2025 年社平工资（年/元） ──────────────────────────
# 参考湖南省 2024 年发布数据，2025 年约 ¥98,568/年
CHANGSHA_AVG_ANNUAL_SALARY_YUAN = 98_568
CHANGSHA_AVG_MONTHLY_SALARY_YUAN = CHANGSHA_AVG_ANNUAL_SALARY_YUAN // 12  # ≈ 8214

# 免税额 = 社平工资 * 3（年）
COMPENSATION_TAX_EXEMPTION_YUAN = CHANGSHA_AVG_ANNUAL_SALARY_YUAN * 3  # ≈ 295704

# ── 月度税率表（用于补偿金单独计税） ─────────────────────────
# (上限元, 税率, 速算扣除数元)
MONTHLY_TAX_BRACKETS: List[Tuple[float, float, float]] = [
    (3_000, 0.03, 0),
    (12_000, 0.10, 210),
    (25_000, 0.20, 1_410),
    (35_000, 0.25, 2_660),
    (55_000, 0.30, 4_410),
    (80_000, 0.35, 7_160),
    (float("inf"), 0.45, 15_160),
]

# ── 年假天数表（工龄 → 年假天数） ────────────────────────────
# 依据《职工带薪年休假条例》
ANNUAL_LEAVE_TABLE = [
    (1, 0),  # 不满1年：0天
    (10, 5),  # 1-9年：5天
    (20, 10),  # 10-19年：10天
    (999, 15),  # 20年以上：15天
]


def _compute_n_years(
    hire_date: date,
    last_work_date: date,
) -> float:
    """计算经济补偿N值（工作年限）

    满6个月不满1年的按1年算，不满6个月的按0.5年算。

    Args:
        hire_date: 入职日期
        last_work_date: 最后工作日

    Returns:
        N值（年）
    """
    total_days = (last_work_date - hire_date).days
    if total_days < 0:
        return 0.0

    full_years = total_days // 365
    remaining_days = total_days % 365

    if remaining_days >= 183:  # >= 6个月
        return float(full_years + 1)
    elif remaining_days > 0:
        return full_years + 0.5
    else:
        return float(full_years) if full_years > 0 else 0.5


def _compute_monthly_avg_salary_fen(
    last_12_months_salary_fen: list[int],
) -> int:
    """计算最近12个月平均月工资（分）

    Args:
        last_12_months_salary_fen: 最近12个月每月工资列表（分）

    Returns:
        平均月工资（分）
    """
    if not last_12_months_salary_fen:
        return 0
    return int(sum(last_12_months_salary_fen) / len(last_12_months_salary_fen))


def _cap_monthly_base(avg_monthly_fen: int) -> Tuple[int, bool]:
    """封顶月工资基数（不超过社平3倍）

    Args:
        avg_monthly_fen: 平均月工资（分）

    Returns:
        (封顶后的月工资分, 是否被封顶)
    """
    cap_fen = CHANGSHA_AVG_MONTHLY_SALARY_YUAN * 3 * 100  # 元转分
    if avg_monthly_fen > cap_fen:
        return cap_fen, True
    return avg_monthly_fen, False


def _cap_n_years(n: float, is_capped_salary: bool) -> float:
    """封顶N值（高薪人员最多12年）

    仅当月工资超过社平3倍时，N最多12年。

    Args:
        n: 原始N值
        is_capped_salary: 工资是否被封顶

    Returns:
        封顶后的N值
    """
    if is_capped_salary and n > 12:
        return 12.0
    return n


def _compute_compensation_tax_fen(
    compensation_fen: int,
    n_years: float,
) -> int:
    """计算经济补偿金个税（分）

    免税额 = 当地上年职工平均工资 * 3
    应税部分 / 工作年限(最多12) = 折算月收入
    按月度税率表计税 * 工作年限

    Args:
        compensation_fen: 经济补偿金（分）
        n_years: 工作年限N

    Returns:
        个税金额（分）
    """
    compensation_yuan = compensation_fen / 100
    exempt_yuan = COMPENSATION_TAX_EXEMPTION_YUAN

    taxable_yuan = compensation_yuan - exempt_yuan
    if taxable_yuan <= 0:
        return 0

    # 折算年限（最多12年）
    years_for_tax = min(math.ceil(n_years), 12)
    if years_for_tax <= 0:
        years_for_tax = 1

    monthly_taxable = taxable_yuan / years_for_tax

    # 按月度税率表计税
    monthly_tax = 0.0
    for upper, rate, quick_deduction in MONTHLY_TAX_BRACKETS:
        if monthly_taxable <= upper:
            monthly_tax = monthly_taxable * rate - quick_deduction
            break

    total_tax_yuan = max(0.0, monthly_tax) * years_for_tax
    return int(round(total_tax_yuan * 100))


def _get_annual_leave_days(total_work_years: float) -> int:
    """根据累计工龄获取法定年假天数

    Args:
        total_work_years: 累计工龄（年）

    Returns:
        年假天数
    """
    for threshold, days in ANNUAL_LEAVE_TABLE:
        if total_work_years < threshold:
            return days
    return 15


class SeparationSettlementService:
    """离职结算服务 — N/N+1/2N 经济补偿金计算"""

    def calculate_compensation(
        self,
        employee_id: str,
        separation_type: str,
        hire_date: date,
        last_work_date: date,
        last_12_months_salary_fen: list[int],
    ) -> dict:
        """计算经济补偿金

        Args:
            employee_id: 员工 ID
            separation_type: 离职类型
            hire_date: 入职日期
            last_work_date: 最后工作日
            last_12_months_salary_fen: 最近12个月每月工资（分）

        Returns:
            补偿金明细
        """
        if separation_type not in SEPARATION_TYPES:
            return {"ok": False, "error": f"未知离职类型: {separation_type}"}

        n_years = _compute_n_years(hire_date, last_work_date)
        avg_monthly_fen = _compute_monthly_avg_salary_fen(last_12_months_salary_fen)
        capped_monthly_fen, is_capped = _cap_monthly_base(avg_monthly_fen)
        capped_n = _cap_n_years(n_years, is_capped)

        # 计算补偿金
        if separation_type not in COMPENSABLE_TYPES:
            compensation_fen = 0
            notice_pay_fen = 0
        else:
            compensation_fen = int(capped_n * capped_monthly_fen)
            # 代通知金：dismiss_no_fault 额外加1个月
            notice_pay_fen = capped_monthly_fen if separation_type in NOTICE_PAY_TYPES else 0

        total_compensation_fen = compensation_fen + notice_pay_fen

        # 补偿金个税
        tax_fen = _compute_compensation_tax_fen(total_compensation_fen, n_years)

        result = {
            "ok": True,
            "employee_id": employee_id,
            "separation_type": separation_type,
            "separation_type_name": SEPARATION_TYPES[separation_type],
            "hire_date": hire_date.isoformat(),
            "last_work_date": last_work_date.isoformat(),
            "n_years": n_years,
            "capped_n": capped_n,
            "avg_monthly_salary_fen": avg_monthly_fen,
            "capped_monthly_salary_fen": capped_monthly_fen,
            "is_salary_capped": is_capped,
            "compensation_fen": compensation_fen,
            "notice_pay_fen": notice_pay_fen,
            "total_compensation_fen": total_compensation_fen,
            "compensation_tax_fen": tax_fen,
            "net_compensation_fen": total_compensation_fen - tax_fen,
        }

        logger.info(
            "compensation_calculated",
            employee_id=employee_id,
            separation_type=separation_type,
            n_years=n_years,
            compensation_fen=total_compensation_fen,
        )

        return result

    def calculate_final_pay(
        self,
        employee_id: str,
        last_work_date: date,
        monthly_salary_fen: int,
        work_days_in_month: int,
        worked_days: int,
        unused_annual_leave_days: float,
        daily_salary_fen: int,
        prorated_13th_month_fen: int = 0,
        social_insurance_deduction_fen: int = 0,
        housing_fund_deduction_fen: int = 0,
        other_deductions_fen: int = 0,
        compensation_result: Optional[dict] = None,
    ) -> dict:
        """计算最终结算薪资

        = 当月出勤工资 + 经济补偿金 + 未休年假折算 + 13薪折算 - 社保扣款 - 公积金 - 其他扣款

        Args:
            employee_id: 员工 ID
            last_work_date: 最后工作日
            monthly_salary_fen: 月薪标准（分）
            work_days_in_month: 当月应出勤天数
            worked_days: 当月实际出勤天数
            unused_annual_leave_days: 未休年假天数
            daily_salary_fen: 日薪标准（分），用于年假折算
            prorated_13th_month_fen: 折算13薪（分）
            social_insurance_deduction_fen: 社保个人扣款（分）
            housing_fund_deduction_fen: 公积金个人扣款（分）
            other_deductions_fen: 其他扣款（分）
            compensation_result: 经济补偿金计算结果（可选）

        Returns:
            最终结算明细
        """
        # 当月出勤工资（按比例）
        if work_days_in_month > 0:
            base_prorate_fen = int(monthly_salary_fen * worked_days / work_days_in_month)
        else:
            base_prorate_fen = 0

        # 未休年假折算（按日薪 * 200% 补偿，已含正常工资部分所以额外补 200%）
        leave_payout_fen = int(unused_annual_leave_days * daily_salary_fen * 2)

        # 补偿金
        compensation_fen = 0
        compensation_tax_fen = 0
        if compensation_result and compensation_result.get("ok"):
            compensation_fen = compensation_result.get("total_compensation_fen", 0)
            compensation_tax_fen = compensation_result.get("compensation_tax_fen", 0)

        # 总扣款
        total_deductions = (
            social_insurance_deduction_fen + housing_fund_deduction_fen + other_deductions_fen + compensation_tax_fen
        )

        # 净结算金额
        gross_final = base_prorate_fen + compensation_fen + leave_payout_fen + prorated_13th_month_fen
        net_final_pay = gross_final - total_deductions

        result = {
            "ok": True,
            "employee_id": employee_id,
            "last_work_date": last_work_date.isoformat(),
            "base_prorate_fen": base_prorate_fen,
            "compensation_fen": compensation_fen,
            "leave_payout_fen": leave_payout_fen,
            "prorated_13th_month_fen": prorated_13th_month_fen,
            "gross_final_fen": gross_final,
            "deductions": {
                "social_insurance": social_insurance_deduction_fen,
                "housing_fund": housing_fund_deduction_fen,
                "compensation_tax": compensation_tax_fen,
                "other": other_deductions_fen,
                "total": total_deductions,
            },
            "net_final_pay_fen": net_final_pay,
        }

        logger.info(
            "final_pay_calculated",
            employee_id=employee_id,
            gross=gross_final,
            deductions=total_deductions,
            net=net_final_pay,
        )

        return result

    def generate_settlement_document(
        self,
        employee_id: str,
        employee_name: str,
        compensation_result: dict,
        final_pay_result: dict,
    ) -> dict:
        """生成离职结算单

        Args:
            employee_id: 员工 ID
            employee_name: 员工姓名
            compensation_result: 补偿金计算结果
            final_pay_result: 最终结算结果

        Returns:
            结算单数据
        """
        return {
            "ok": True,
            "document_type": "separation_settlement",
            "employee_id": employee_id,
            "employee_name": employee_name,
            "separation_type": compensation_result.get("separation_type", ""),
            "separation_type_name": compensation_result.get("separation_type_name", ""),
            "hire_date": compensation_result.get("hire_date", ""),
            "last_work_date": compensation_result.get("last_work_date", ""),
            "service_years": compensation_result.get("n_years", 0),
            "compensation_detail": {
                "n_years": compensation_result.get("capped_n", 0),
                "monthly_base_fen": compensation_result.get("capped_monthly_salary_fen", 0),
                "compensation_fen": compensation_result.get("compensation_fen", 0),
                "notice_pay_fen": compensation_result.get("notice_pay_fen", 0),
                "total_fen": compensation_result.get("total_compensation_fen", 0),
            },
            "final_pay_detail": {
                "base_prorate_fen": final_pay_result.get("base_prorate_fen", 0),
                "leave_payout_fen": final_pay_result.get("leave_payout_fen", 0),
                "prorated_13th_month_fen": final_pay_result.get("prorated_13th_month_fen", 0),
                "gross_fen": final_pay_result.get("gross_final_fen", 0),
                "deductions_fen": final_pay_result.get("deductions", {}).get("total", 0),
                "net_fen": final_pay_result.get("net_final_pay_fen", 0),
            },
            "generated_at": date.today().isoformat(),
        }

    def get_separation_stats(
        self,
        separations: list[dict],
    ) -> dict:
        """离职统计分析

        Args:
            separations: 离职记录列表，每条包含 separation_type, n_years,
                         total_compensation_fen, hire_date, last_work_date

        Returns:
            统计摘要
        """
        total = len(separations)
        if total == 0:
            return {
                "total": 0,
                "by_type": {},
                "avg_tenure_years": 0.0,
                "avg_compensation_fen": 0,
                "turnover_count": 0,
            }

        by_type: dict[str, int] = {}
        total_tenure = 0.0
        total_compensation = 0
        compensated_count = 0

        for sep in separations:
            sep_type = sep.get("separation_type", "unknown")
            by_type[sep_type] = by_type.get(sep_type, 0) + 1
            total_tenure += sep.get("n_years", 0)
            comp = sep.get("total_compensation_fen", 0)
            if comp > 0:
                total_compensation += comp
                compensated_count += 1

        return {
            "total": total,
            "by_type": {k: {"count": v, "label": SEPARATION_TYPES.get(k, k)} for k, v in by_type.items()},
            "avg_tenure_years": round(total_tenure / total, 1),
            "avg_compensation_fen": int(total_compensation / compensated_count) if compensated_count > 0 else 0,
            "turnover_count": total,
        }
