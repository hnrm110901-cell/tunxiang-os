"""个人所得税计算器 — 累计预扣法

2024年税率表（7级超额累进），适用于工资薪金所得。
月基本减除费用5000元。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple


# ── 2024年个税税率表（年度累计应纳税所得额，元）──────────────────────────────
# 格式：(级距上限元, 税率, 速算扣除数元)
# 最后一档上限为 inf
TAX_BRACKETS: List[Tuple[float, float, float]] = [
    (36_000, 0.03, 0),
    (144_000, 0.10, 2_520),
    (300_000, 0.20, 16_920),
    (420_000, 0.25, 31_920),
    (660_000, 0.30, 52_920),
    (960_000, 0.35, 85_920),
    (float("inf"), 0.45, 181_920),
]

# 月基本减除费用（元），可通过环境变量覆盖
BASIC_DEDUCTION: float = float(os.getenv("TAX_BASIC_DEDUCTION_YUAN", "5000"))


def _compute_annual_tax(annual_taxable_income_yuan: float) -> Tuple[float, float, float]:
    """计算年度累计应纳税额

    Args:
        annual_taxable_income_yuan: 年度累计应纳税所得额（元）

    Returns:
        (累计税额元, 适用税率, 速算扣除数元)
    """
    if annual_taxable_income_yuan <= 0:
        return (0.0, 0.0, 0.0)

    for upper, rate, quick_deduction in TAX_BRACKETS:
        if annual_taxable_income_yuan <= upper:
            tax = annual_taxable_income_yuan * rate - quick_deduction
            return (max(0.0, tax), rate, quick_deduction)

    # fallback（理论上不会走到这里，最后一档 upper=inf）
    rate, quick_deduction = 0.45, 181_920.0
    tax = annual_taxable_income_yuan * rate - quick_deduction
    return (max(0.0, tax), rate, quick_deduction)


class IncomeTaxCalculator:
    """个人所得税计算器 — 累计预扣法

    各月税款通过"全年累计税 - 已预缴税"计算，
    避免年末税款波动，跨月累计数据影响当月税率。
    """

    # 税率表（可在子类中覆盖，满足未来税率调整）
    TAX_BRACKETS = TAX_BRACKETS
    BASIC_DEDUCTION = BASIC_DEDUCTION

    def calculate_monthly(
        self,
        current_month_income: float,
        ytd_income: float,
        ytd_tax_paid: float,
        ytd_social_insurance: float,
        month_index: int,
        special_deduction_monthly: float = 0.0,
    ) -> Dict[str, Any]:
        """累计预扣法计算当月个税

        Args:
            current_month_income: 当月应税收入（元，已扣考勤等扣款）
            ytd_income: 年初至今（不含当月）累计收入（元）
            ytd_tax_paid: 年初至今已预缴税款（元）
            ytd_social_insurance: 年初至今（不含当月）社保+公积金个人部分（元）
            month_index: 当年第几个月（1-12），用于计算累计减除费用
            special_deduction_monthly: 月度专项附加扣除（元，子女教育/赡养老人等）

        Returns:
            {
                monthly_tax: 当月应预扣税额（元）,
                cumulative_income: 含当月的年度累计收入（元）,
                cumulative_taxable: 年度累计应纳税所得额（元）,
                cumulative_tax: 年度累计税额（元）,
                tax_rate: 适用税率,
                quick_deduction: 速算扣除数（元）,
            }
        """
        # 年度累计收入（含当月）
        cumulative_income = ytd_income + current_month_income

        # 年度累计减除费用（月基本减除 × 已过月份数）
        cumulative_basic_deduction = self.BASIC_DEDUCTION * month_index

        # 年度累计社保+专项附加扣除
        # ytd_social_insurance 是前几月之和，当月的社保在 current_month_income 已扣
        # 此处遵循税务局口径：社保当月计入当月扣除，但累计预扣法下需要正确归集
        # 实务中：累计扣除 = 前(month_index-1)月社保合计 + 当月社保
        # ytd_social_insurance 已含当月，直接使用
        cumulative_deductions = ytd_social_insurance + special_deduction_monthly * month_index

        # 年度累计应纳税所得额
        cumulative_taxable = max(
            0.0,
            cumulative_income - cumulative_basic_deduction - cumulative_deductions,
        )

        # 年度累计应纳税额
        cumulative_tax, tax_rate, quick_deduction = _compute_annual_tax(cumulative_taxable)

        # 当月应预扣 = 年度累计税 - 已预缴
        monthly_tax = max(0.0, cumulative_tax - ytd_tax_paid)

        return {
            "monthly_tax": round(monthly_tax, 2),
            "cumulative_income": round(cumulative_income, 2),
            "cumulative_taxable": round(cumulative_taxable, 2),
            "cumulative_tax": round(cumulative_tax, 2),
            "tax_rate": tax_rate,
            "quick_deduction": quick_deduction,
        }

    def calculate_from_annual(
        self,
        annual_taxable_income_yuan: float,
    ) -> Dict[str, Any]:
        """直接按年度应纳税所得额计算年税（用于年终汇算）

        Args:
            annual_taxable_income_yuan: 年度应纳税所得额（元）

        Returns:
            {annual_tax, tax_rate, quick_deduction}
        """
        annual_tax, tax_rate, quick_deduction = _compute_annual_tax(annual_taxable_income_yuan)
        return {
            "annual_tax": round(annual_tax, 2),
            "tax_rate": tax_rate,
            "quick_deduction": quick_deduction,
        }
