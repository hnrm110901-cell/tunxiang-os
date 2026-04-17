"""
D12 合规 — 个税模型（累计预扣法）
-----------------------------------
新增：
  - PersonalTaxRecord       员工年度累计预扣明细（2019新税制必需）
  - SpecialAdditionalDeduction 专项附加扣除（6项）

说明：与既有 payroll.TaxDeclaration 并存 — TaxDeclaration 面向薪酬单，
PersonalTaxRecord 面向税局申报明细（含年度累计月份），二者字段侧重不同。
"""

import enum
import uuid

from sqlalchemy import Boolean, Column, Date, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID

from .base import Base, TimestampMixin


class SpecialDeductionType(str, enum.Enum):
    """专项附加扣除类型（6项）"""

    CHILD_EDUCATION = "child_education"  # 子女教育（¥2000/子女·月）
    CONTINUING_EDUCATION = "continuing_education"  # 继续教育（¥400/月）
    SERIOUS_ILLNESS = "serious_illness"  # 大病医疗（据实，年度¥80000封顶）
    HOUSING_LOAN_INTEREST = "housing_loan_interest"  # 住房贷款利息（¥1000/月）
    HOUSING_RENT = "housing_rent"  # 住房租金（¥800-1500/月 按城市）
    ELDERLY_SUPPORT = "elderly_support"  # 赡养老人（最高¥3000/月）


class PersonalTaxRecord(Base, TimestampMixin):
    """
    员工个税累计预扣记录（按员工·纳税年度·月份唯一）。

    核心字段来自《国家税务总局 2018 第61号公告》累计预扣预缴法：
      累计应纳税所得额 = 累计收入 - 累计免税收入 - 累计减除费用(5000×月数)
                       - 累计专项扣除(社保+公积金个人) - 累计专项附加扣除
      累计应纳税额     = 累计应纳税所得额 × 税率 - 速算扣除数
      本月应扣税额     = 累计应纳税额 - 累计已预扣
    """

    __tablename__ = "personal_tax_records"
    __table_args__ = (
        UniqueConstraint("employee_id", "tax_year", "tax_month_num", name="uq_ptax_emp_year_month"),
        Index("ix_ptax_store_year_month", "store_id", "tax_year", "tax_month_num"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(String(50), nullable=False, index=True)
    employee_id = Column(String(50), ForeignKey("employees.id"), nullable=False, index=True)

    tax_year = Column(Integer, nullable=False)  # 纳税年度
    tax_month_num = Column(Integer, nullable=False)  # 累计月份(1-12)
    pay_month = Column(String(7), nullable=False, index=True)  # YYYY-MM

    # 本月数据（分）
    monthly_income_fen = Column(Integer, nullable=False, default=0)
    monthly_tax_free_income_fen = Column(Integer, nullable=False, default=0)  # 免税收入
    monthly_si_personal_fen = Column(Integer, nullable=False, default=0)  # 社保+公积金个人
    monthly_special_deduction_fen = Column(Integer, nullable=False, default=0)  # 专项附加扣除

    # 累计数据（分）— 累计预扣核心
    cumulative_income_fen = Column(Integer, nullable=False, default=0)
    cumulative_tax_free_income_fen = Column(Integer, nullable=False, default=0)
    cumulative_basic_deduction_fen = Column(Integer, nullable=False, default=0)  # 累计减除费用 5000×月数
    cumulative_si_deduction_fen = Column(Integer, nullable=False, default=0)  # 累计社保公积金扣除
    cumulative_special_deduction_fen = Column(Integer, nullable=False, default=0)  # 累计专项附加
    cumulative_taxable_income_fen = Column(Integer, nullable=False, default=0)  # 累计应纳税所得额
    cumulative_tax_fen = Column(Integer, nullable=False, default=0)  # 累计应纳税额
    cumulative_prepaid_tax_fen = Column(Integer, nullable=False, default=0)  # 年初至上月累计已预扣

    # 本月应扣税额
    current_month_tax_fen = Column(Integer, nullable=False, default=0)

    # 税档快照（审计）
    tax_rate_pct = Column(Numeric(5, 2), nullable=True)
    quick_deduction_fen = Column(Integer, nullable=True)

    # 计算明细 JSON — 供员工查询和税局核对
    calculation_detail = Column(JSON, nullable=True)

    declared_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return (
            f"<PersonalTaxRecord(emp='{self.employee_id}', "
            f"{self.tax_year}-{self.tax_month_num:02d}, "
            f"tax={self.current_month_tax_fen/100:.2f}yuan)>"
        )

    @property
    def current_month_tax_yuan(self) -> float:
        return round(self.current_month_tax_fen / 100, 2)


class SpecialAdditionalDeduction(Base, TimestampMixin):
    """
    员工专项附加扣除配置（6项任选，按月定额或据实）。

    月定额示例：
      子女教育:   2000 × 子女数（单方或夫妻均摊50%）
      住房贷款:   1000
      住房租金:   800/1100/1500（按城市）
      赡养老人:   3000(独生) / 2000(非独生，均摊)
    """

    __tablename__ = "special_additional_deductions"
    __table_args__ = (
        Index("ix_sad_emp_active", "employee_id", "is_active"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(String(50), nullable=False, index=True)
    employee_id = Column(String(50), ForeignKey("employees.id"), nullable=False, index=True)

    deduction_type = Column(
        SAEnum(SpecialDeductionType, name="special_deduction_type"),
        nullable=False,
    )

    # 月定额（分）。大病医疗据实报销，此处记录本期累计额度
    monthly_amount_fen = Column(Integer, nullable=False, default=0)

    effective_month = Column(String(7), nullable=False)  # 起效月 YYYY-MM
    expire_month = Column(String(7), nullable=True)  # 终止月 YYYY-MM（null=长期）

    is_active = Column(Boolean, default=True, nullable=False)

    # 附加信息（子女姓名/贷款合同号/赡养人信息等）
    extra_info = Column(JSON, nullable=True)

    remark = Column(Text, nullable=True)

    def __repr__(self):
        return (
            f"<SpecialAdditionalDeduction(emp='{self.employee_id}', "
            f"type='{self.deduction_type}', "
            f"amount={self.monthly_amount_fen/100:.0f}yuan)>"
        )

    @property
    def monthly_amount_yuan(self) -> float:
        return round(self.monthly_amount_fen / 100, 2)
