"""
Salary Item Models — 薪酬项定义与明细
支持薪酬公式的定义、计算和记录。

D12 扩展（z66）:
- SalaryItemDefinition 新增 tax_attribute 字段（税务属性）
- 新增 EmployeeSalaryItem  员工-薪酬项绑定（按生效时间窗）
- 新增 PayslipLine         工资条明细行（按 tax_attribute 聚合）

移植自 tunxiang-os tx-org.salary_item_library（71项精简版，对标 i人事 138 项）。
"""

import uuid
from datetime import date

from sqlalchemy import Boolean, Column, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID

from .base import Base, TimestampMixin


# ── 税务属性枚举（字符串常量，避免 DB 枚举的迁移负担） ──
#   pre_tax_add     税前加项（应税收入）：基本工资/岗位工资/绩效/提成/补贴大多数
#   pre_tax_deduct  税前扣项（税前扣除）：社保个人、公积金个人、补充医疗
#   after_tax_add   税后加项（非应税补发）：差旅费补发等
#   after_tax_deduct 税后扣项（税后扣款）：罚款、赔偿、借支扣回
#   non_tax         非税/免税收入：部分符合免税政策的补贴
TAX_ATTRIBUTES = (
    "pre_tax_add",
    "pre_tax_deduct",
    "after_tax_add",
    "after_tax_deduct",
    "non_tax",
)


class SalaryItemDefinition(Base, TimestampMixin):
    """
    薪酬项定义（品牌/门店级）
    每个薪酬项定义一个计算公式，按 calc_order 顺序执行
    """

    __tablename__ = "salary_item_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(String(50), nullable=False, index=True)
    store_id = Column(String(50), nullable=True, index=True)  # NULL=品牌通用

    item_name = Column(String(100), nullable=False)  # 应发工资/实发工资/绩效标准/工龄补贴...
    item_code = Column(String(50), nullable=True, index=True)  # 薪酬项编码（全局唯一）
    item_category = Column(String(30), nullable=False)  # attendance/leave/performance/commission/subsidy/deduction/social/welfare
    # z66 D12 新增：税务属性（驱动个税应税基数聚合）
    tax_attribute = Column(String(20), nullable=True, index=True)  # pre_tax_add/pre_tax_deduct/after_tax_add/after_tax_deduct/non_tax
    calc_order = Column(Integer, nullable=False, default=50)  # 计算顺序（1-99）
    formula = Column(Text, nullable=True)  # 公式表达式
    formula_type = Column(String(20), default="expression")  # expression/condition/fixed/lookup
    decimal_places = Column(Integer, default=2)
    is_active = Column(Boolean, default=True, nullable=False)
    effective_month = Column(String(7), nullable=True)  # 生效月份 YYYY-MM
    expire_month = Column(String(7), nullable=True)
    remark = Column(Text, nullable=True)

    def __repr__(self):
        return f"<SalaryItemDefinition(name='{self.item_name}', order={self.calc_order})>"


class SalaryItemRecord(Base, TimestampMixin):
    """
    员工月度薪酬项明细
    每个员工每月每个薪酬项一条记录
    """

    __tablename__ = "salary_item_records"
    __table_args__ = (UniqueConstraint("employee_id", "pay_month", "item_id", name="uq_salary_item_month"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(String(50), nullable=False, index=True)
    employee_id = Column(String(50), nullable=False, index=True)
    pay_month = Column(String(7), nullable=False, index=True)  # YYYY-MM
    item_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    item_name = Column(String(100), nullable=False)  # 冗余方便查询
    item_category = Column(String(30), nullable=False)
    amount_fen = Column(Integer, nullable=False, default=0)  # 金额（分）
    formula_snapshot = Column(Text, nullable=True)  # 计算时的公式快照
    calc_inputs = Column(JSON, nullable=True)  # 计算时的输入参数快照

    def __repr__(self):
        return f"<SalaryItemRecord(emp='{self.employee_id}', item='{self.item_name}', amount={self.amount_fen})>"


# ── z66 D12 新增表 ──────────────────────────────────────────


class EmployeeSalaryItem(Base, TimestampMixin):
    """
    员工-薪酬项分配（带生效时间窗）

    每条记录代表：某员工从 effective_from 起，在其月度工资中固定有这一项（金额可覆盖）。
    - amount_fen 为 NULL 时，按 SalaryItemDefinition 的默认值/公式计算
    - effective_to 为 NULL 表示长期有效；非 NULL 则严格 <= 失效（不含当月）
    """

    __tablename__ = "employee_salary_items"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "salary_item_id", "effective_from",
            name="uq_emp_salary_item_effective",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(String(50), ForeignKey("employees.id"), nullable=False, index=True)
    salary_item_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # 覆盖默认金额，NULL 表示使用项目默认值或公式
    amount_fen = Column(Integer, nullable=True)
    effective_from = Column(Date, nullable=False, default=date.today)
    effective_to = Column(Date, nullable=True)
    remark = Column(Text, nullable=True)

    def __repr__(self):
        return f"<EmployeeSalaryItem(emp='{self.employee_id}', item_id='{self.salary_item_id}')>"


class PayslipLine(Base, TimestampMixin):
    """
    工资条明细行 — payroll_engine_v3 计算后写入

    与 SalaryItemRecord 的区别：
    - SalaryItemRecord 为旧版公式引擎的中间结果
    - PayslipLine 为按 tax_attribute 分类后的最终工资条展示行，驱动前端工资条/报税
    """

    __tablename__ = "payslip_lines"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "pay_month", "salary_item_id",
            name="uq_payslip_line",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payroll_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # 关联 payroll_records.id
    store_id = Column(String(50), nullable=False, index=True)
    employee_id = Column(String(50), nullable=False, index=True)
    pay_month = Column(String(7), nullable=False, index=True)  # YYYY-MM
    salary_item_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    item_code = Column(String(50), nullable=False)
    item_name = Column(String(100), nullable=False)
    item_category = Column(String(30), nullable=False)
    tax_attribute = Column(String(20), nullable=False, index=True)
    amount_fen = Column(Integer, nullable=False, default=0)
    # 计算依据快照：{"formula": "...", "inputs": {...}, "source": "manual/formula/default"}
    calc_basis = Column(JSON, nullable=True)

    def __repr__(self):
        return f"<PayslipLine(emp='{self.employee_id}', {self.pay_month}, item='{self.item_code}', amount={self.amount_fen})>"
