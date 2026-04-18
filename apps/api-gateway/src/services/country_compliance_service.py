"""
多国薪酬/税务规则引擎（独立引擎，不污染内地 tax_service）

覆盖：
- 内地 CN：复用现有 social_insurance_service + personal_tax_service（本文件不重算）
- 香港 HK：MPF 5%×2（月薪封顶 30,000 HKD）+ 薪俸税 4 级累进
- 新加坡 SG：CPF 按年龄分段 + 个税 0-22% 累进

返回统一结构：{gross_fen, employee_contribution_fen, employer_contribution_fen, tax_fen, net_fen, currency, details}
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.country_compliance import CountryPayrollRule
from src.models.employee import Employee
from src.models.tenant_locale import TenantLocaleConfig


# ── 规则常量（硬编码缺省值，DB 覆盖优先） ───────────────
# 香港 MPF：雇员 5% + 雇主 5%，月薪基数 7,100 ~ 30,000 HKD（2024 版）
HK_MPF = {
    "employee_rate": 0.05,
    "employer_rate": 0.05,
    "min_base": 7100_00,  # 分
    "max_base": 30000_00,
    "min_exempt_base": 7100_00,  # 低于此基数员工部分免缴
}

# 香港薪俸税（2024/25 标准税率 4 级累进，年度）
HK_SALARIES_TAX_BRACKETS = [
    (50000_00, 0.02),
    (50000_00, 0.06),
    (50000_00, 0.10),
    (50000_00, 0.14),
    (None, 0.17),
]
HK_BASIC_ALLOWANCE_YEARLY = 132000_00  # 基本免税额

# 新加坡 CPF（2024）简化：普通公民/PR ≤55岁 员工 20% 雇主 17%；月薪封顶 SGD 6,800
SG_CPF = {
    "under_55": {"employee_rate": 0.20, "employer_rate": 0.17},
    "55_to_60": {"employee_rate": 0.15, "employer_rate": 0.145},
    "60_to_65": {"employee_rate": 0.09, "employer_rate": 0.11},
    "over_65": {"employee_rate": 0.075, "employer_rate": 0.075},
    "max_base": 6800_00,  # 分
}

# 新加坡个税 2024 年度累进（简化）
SG_INCOME_TAX_BRACKETS = [
    (20000_00, 0.00),
    (10000_00, 0.02),
    (10000_00, 0.035),
    (40000_00, 0.07),
    (40000_00, 0.115),
    (40000_00, 0.15),
    (40000_00, 0.18),
    (40000_00, 0.19),
    (40000_00, 0.195),
    (180000_00, 0.20),
    (500000_00, 0.22),
    (None, 0.24),
]


@dataclass
class PayrollResult:
    gross_fen: int
    employee_contribution_fen: int
    employer_contribution_fen: int
    tax_fen: int
    net_fen: int
    currency: str
    country_code: str
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.__dict__,
            "gross_yuan": round(self.gross_fen / 100, 2),
            "employee_contribution_yuan": round(self.employee_contribution_fen / 100, 2),
            "employer_contribution_yuan": round(self.employer_contribution_fen / 100, 2),
            "tax_yuan": round(self.tax_fen / 100, 2),
            "net_yuan": round(self.net_fen / 100, 2),
        }


def _progressive_tax(taxable_fen: int, brackets: List[tuple]) -> int:
    """累进税计算，brackets = [(bracket_width_fen_or_None, rate), ...]"""
    if taxable_fen <= 0:
        return 0
    tax = 0
    remaining = taxable_fen
    for width, rate in brackets:
        if width is None or remaining <= width:
            tax += int(remaining * rate)
            return tax
        tax += int(width * rate)
        remaining -= width
    return tax


class CountryComplianceService:
    """多国合规薪酬计算"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_payroll_rules(
        self, country_code: str, as_of_date: Optional[date] = None
    ) -> List[CountryPayrollRule]:
        as_of = as_of_date or date.today()
        stmt = select(CountryPayrollRule).where(
            CountryPayrollRule.country_code == country_code,
            CountryPayrollRule.effective_from <= as_of,
        )
        rules = (await self.session.execute(stmt)).scalars().all()
        # 过滤未失效的
        return [r for r in rules if r.effective_to is None or r.effective_to >= as_of]

    async def _detect_country(self, employee: Employee) -> str:
        """根据 employee.tenant 的 locale_config 判定国家；默认 CN"""
        # 简化：通过 employee.store_id 关联 tenant；这里先尝试 Employee.locale_code 推断
        locale = getattr(employee, "locale_code", "zh-CN") or "zh-CN"
        if locale == "zh-TW":
            return "HK"
        if locale == "en-US":
            # 英语默认当作新加坡（海外场景）
            return "SG"
        return "CN"

    # ── 分国家引擎 ─────────────────────────────
    def calc_hk(self, gross_fen: int, pay_month_count: int = 1) -> PayrollResult:
        """香港 MPF + 薪俸税（按月折算）"""
        # MPF 员工部分：基数 < min_exempt 免缴员工；雇主按 min_base 以上计
        base = min(max(gross_fen, 0), HK_MPF["max_base"])
        employee_mpf = 0 if gross_fen < HK_MPF["min_exempt_base"] else int(base * HK_MPF["employee_rate"])
        employer_mpf = int(base * HK_MPF["employer_rate"])

        # 薪俸税：按年化估算后÷12
        yearly_income = gross_fen * 12
        taxable_yearly = max(0, yearly_income - HK_BASIC_ALLOWANCE_YEARLY - employee_mpf * 12)
        yearly_tax = _progressive_tax(taxable_yearly, HK_SALARIES_TAX_BRACKETS)
        monthly_tax = yearly_tax // 12

        net = gross_fen - employee_mpf - monthly_tax
        return PayrollResult(
            gross_fen=gross_fen,
            employee_contribution_fen=employee_mpf,
            employer_contribution_fen=employer_mpf,
            tax_fen=monthly_tax,
            net_fen=net,
            currency="HKD",
            country_code="HK",
            details={
                "mpf_base_fen": base,
                "mpf_employee_rate": HK_MPF["employee_rate"],
                "mpf_employer_rate": HK_MPF["employer_rate"],
                "yearly_taxable_fen": taxable_yearly,
                "yearly_tax_fen": yearly_tax,
            },
        )

    def calc_sg(self, gross_fen: int, age: int = 30) -> PayrollResult:
        """新加坡 CPF（按年龄分段） + 个税（年化累进）"""
        if age < 55:
            rates = SG_CPF["under_55"]
        elif age < 60:
            rates = SG_CPF["55_to_60"]
        elif age < 65:
            rates = SG_CPF["60_to_65"]
        else:
            rates = SG_CPF["over_65"]

        base = min(max(gross_fen, 0), SG_CPF["max_base"])
        employee_cpf = int(base * rates["employee_rate"])
        employer_cpf = int(base * rates["employer_rate"])

        # 个税：年化计算 → 月税 = 年税/12
        yearly_income = gross_fen * 12
        taxable_yearly = max(0, yearly_income - employee_cpf * 12)
        yearly_tax = _progressive_tax(taxable_yearly, SG_INCOME_TAX_BRACKETS)
        monthly_tax = yearly_tax // 12

        net = gross_fen - employee_cpf - monthly_tax
        return PayrollResult(
            gross_fen=gross_fen,
            employee_contribution_fen=employee_cpf,
            employer_contribution_fen=employer_cpf,
            tax_fen=monthly_tax,
            net_fen=net,
            currency="SGD",
            country_code="SG",
            details={
                "age_band": rates,
                "cpf_base_fen": base,
                "yearly_taxable_fen": taxable_yearly,
                "yearly_tax_fen": yearly_tax,
            },
        )

    async def calc_by_country(
        self, employee_id: str, pay_month: str, gross_fen: Optional[int] = None
    ) -> PayrollResult:
        """
        根据员工所在国家选择引擎。
        - CN：本方法不重复计算（返回占位，调用方走 payroll_service）
        - HK/SG：使用独立引擎
        """
        emp = await self.session.get(Employee, employee_id)
        if not emp:
            raise ValueError(f"Employee {employee_id} not found")

        country = await self._detect_country(emp)
        gross = gross_fen if gross_fen is not None else (emp.daily_wage_standard_fen or 0) * 22

        if country == "HK":
            return self.calc_hk(gross)
        if country == "SG":
            age = 30
            if getattr(emp, "birth_date", None):
                age = max(18, date.today().year - emp.birth_date.year)
            return self.calc_sg(gross, age=age)
        # CN：返回占位，提示调用方走本地服务
        return PayrollResult(
            gross_fen=gross,
            employee_contribution_fen=0,
            employer_contribution_fen=0,
            tax_fen=0,
            net_fen=gross,
            currency="CNY",
            country_code="CN",
            details={"note": "内地请走 social_insurance_service + personal_tax_service"},
        )
