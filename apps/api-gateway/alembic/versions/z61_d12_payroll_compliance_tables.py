"""z61 — D12 绩效薪酬合规：社保/个税/银行代发 共 6 张表

共 6 张新表：
  1. social_insurance_configs       区域社保费率配置
  2. employee_social_insurances     员工参保方案
  3. payroll_si_records             月度社保缴费明细（按险种）
  4. personal_tax_records           个税累计预扣记录
  5. special_additional_deductions  专项附加扣除（6 项）
  6. salary_disbursements           银行代发批次

模型来源（只读、未修改）:
  src/models/social_insurance.py, src/models/tax.py,
  src/models/payroll_disbursement.py

Revision ID: z61_d12_payroll_compliance
Revises: z60_d1_d4_pos_crm_menu_tables
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID


# revision identifiers, used by Alembic.
revision = "z61_d12_payroll_compliance"
down_revision = "z60_d1_d4_pos_crm_menu_tables"
branch_labels = None
depends_on = None


# ─────────────── Enum values（全部显式 name=） ───────────────
INSURANCE_TYPE = ("pension", "medical", "unemployment", "injury", "maternity", "housing_fund")
SPECIAL_DEDUCTION_TYPE = (
    "child_education",
    "continuing_education",
    "serious_illness",
    "housing_loan_interest",
    "housing_rent",
    "elderly_support",
)
DISBURSEMENT_BANK = ("icbc", "ccb", "generic")
DISBURSEMENT_STATUS = ("generated", "uploaded", "paid", "failed", "cancelled")


def upgrade() -> None:
    # ─── 1. social_insurance_configs ───────────────────────────────
    op.create_table(
        "social_insurance_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("region_code", sa.String(20), nullable=False),
        sa.Column("region_name", sa.String(50), nullable=False),
        sa.Column("effective_year", sa.Integer, nullable=False),
        sa.Column("base_floor_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("base_ceiling_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pension_employer_pct", sa.Numeric(5, 2), server_default="16.00"),
        sa.Column("pension_employee_pct", sa.Numeric(5, 2), server_default="8.00"),
        sa.Column("medical_employer_pct", sa.Numeric(5, 2), server_default="8.00"),
        sa.Column("medical_employee_pct", sa.Numeric(5, 2), server_default="2.00"),
        sa.Column("unemployment_employer_pct", sa.Numeric(5, 2), server_default="0.70"),
        sa.Column("unemployment_employee_pct", sa.Numeric(5, 2), server_default="0.30"),
        sa.Column("injury_employer_pct", sa.Numeric(5, 2), server_default="0.40"),
        sa.Column("maternity_employer_pct", sa.Numeric(5, 2), server_default="0.00"),
        sa.Column("housing_fund_employer_pct", sa.Numeric(5, 2), server_default="8.00"),
        sa.Column("housing_fund_employee_pct", sa.Numeric(5, 2), server_default="8.00"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("remark", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("region_code", "effective_year", name="uq_si_region_year"),
    )
    op.create_index(
        "ix_social_insurance_configs_region_code",
        "social_insurance_configs",
        ["region_code"],
    )

    # ─── 2. employee_social_insurances ─────────────────────────────
    op.create_table(
        "employee_social_insurances",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", sa.String(50), nullable=False),
        sa.Column(
            "employee_id",
            sa.String(50),
            sa.ForeignKey("employees.id"),
            nullable=False,
        ),
        sa.Column(
            "config_id",
            UUID(as_uuid=True),
            sa.ForeignKey("social_insurance_configs.id"),
            nullable=False,
        ),
        sa.Column("effective_year", sa.Integer, nullable=False),
        sa.Column("personal_base_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("has_pension", sa.Boolean, server_default=sa.true()),
        sa.Column("has_medical", sa.Boolean, server_default=sa.true()),
        sa.Column("has_unemployment", sa.Boolean, server_default=sa.true()),
        sa.Column("has_injury", sa.Boolean, server_default=sa.true()),
        sa.Column("has_maternity", sa.Boolean, server_default=sa.true()),
        sa.Column("has_housing_fund", sa.Boolean, server_default=sa.true()),
        sa.Column("housing_fund_pct_override", sa.Numeric(5, 2), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("remark", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("employee_id", "effective_year", name="uq_emp_si_year"),
    )
    op.create_index(
        "ix_employee_social_insurances_store_id",
        "employee_social_insurances",
        ["store_id"],
    )
    op.create_index(
        "ix_employee_social_insurances_employee_id",
        "employee_social_insurances",
        ["employee_id"],
    )

    # ─── 3. payroll_si_records ─────────────────────────────────────
    op.create_table(
        "payroll_si_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", sa.String(50), nullable=False),
        sa.Column(
            "employee_id",
            sa.String(50),
            sa.ForeignKey("employees.id"),
            nullable=False,
        ),
        sa.Column("pay_month", sa.String(7), nullable=False),
        sa.Column(
            "insurance_type",
            sa.Enum(*INSURANCE_TYPE, name="insurance_type"),
            nullable=False,
        ),
        sa.Column("base_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("employer_amount_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("employee_amount_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("employer_rate_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("employee_rate_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("region_code", sa.String(20), nullable=True),
        sa.Column("remark", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "employee_id",
            "pay_month",
            "insurance_type",
            name="uq_payroll_si_emp_month_type",
        ),
    )
    op.create_index(
        "ix_payroll_si_records_store_id", "payroll_si_records", ["store_id"]
    )
    op.create_index(
        "ix_payroll_si_records_employee_id", "payroll_si_records", ["employee_id"]
    )
    op.create_index(
        "ix_payroll_si_records_pay_month", "payroll_si_records", ["pay_month"]
    )
    op.create_index(
        "ix_payroll_si_store_month", "payroll_si_records", ["store_id", "pay_month"]
    )

    # ─── 4. personal_tax_records ──────────────────────────────────
    op.create_table(
        "personal_tax_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", sa.String(50), nullable=False),
        sa.Column(
            "employee_id",
            sa.String(50),
            sa.ForeignKey("employees.id"),
            nullable=False,
        ),
        sa.Column("tax_year", sa.Integer, nullable=False),
        sa.Column("tax_month_num", sa.Integer, nullable=False),
        sa.Column("pay_month", sa.String(7), nullable=False),
        sa.Column("monthly_income_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "monthly_tax_free_income_fen",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "monthly_si_personal_fen", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column(
            "monthly_special_deduction_fen",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cumulative_income_fen", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column(
            "cumulative_tax_free_income_fen",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cumulative_basic_deduction_fen",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cumulative_si_deduction_fen",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cumulative_special_deduction_fen",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cumulative_taxable_income_fen",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column("cumulative_tax_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "cumulative_prepaid_tax_fen",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "current_month_tax_fen", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column("tax_rate_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("quick_deduction_fen", sa.Integer, nullable=True),
        sa.Column("calculation_detail", JSON, nullable=True),
        sa.Column("declared_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "employee_id", "tax_year", "tax_month_num", name="uq_ptax_emp_year_month"
        ),
    )
    op.create_index(
        "ix_personal_tax_records_store_id", "personal_tax_records", ["store_id"]
    )
    op.create_index(
        "ix_personal_tax_records_employee_id",
        "personal_tax_records",
        ["employee_id"],
    )
    op.create_index(
        "ix_personal_tax_records_pay_month", "personal_tax_records", ["pay_month"]
    )
    op.create_index(
        "ix_ptax_store_year_month",
        "personal_tax_records",
        ["store_id", "tax_year", "tax_month_num"],
    )

    # ─── 5. special_additional_deductions ─────────────────────────
    op.create_table(
        "special_additional_deductions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", sa.String(50), nullable=False),
        sa.Column(
            "employee_id",
            sa.String(50),
            sa.ForeignKey("employees.id"),
            nullable=False,
        ),
        sa.Column(
            "deduction_type",
            sa.Enum(*SPECIAL_DEDUCTION_TYPE, name="special_deduction_type"),
            nullable=False,
        ),
        sa.Column(
            "monthly_amount_fen", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column("effective_month", sa.String(7), nullable=False),
        sa.Column("expire_month", sa.String(7), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("extra_info", JSON, nullable=True),
        sa.Column("remark", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_special_additional_deductions_store_id",
        "special_additional_deductions",
        ["store_id"],
    )
    op.create_index(
        "ix_special_additional_deductions_employee_id",
        "special_additional_deductions",
        ["employee_id"],
    )
    op.create_index(
        "ix_sad_emp_active",
        "special_additional_deductions",
        ["employee_id", "is_active"],
    )

    # ─── 6. salary_disbursements ─────────────────────────────────
    op.create_table(
        "salary_disbursements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", sa.String(64), nullable=False, unique=True),
        sa.Column("store_id", sa.String(50), nullable=False),
        sa.Column("pay_month", sa.String(7), nullable=False),
        sa.Column(
            "bank",
            sa.Enum(*DISBURSEMENT_BANK, name="disbursement_bank"),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("file_format", sa.String(10), nullable=False, server_default="txt"),
        sa.Column("total_amount_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("employee_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Enum(*DISBURSEMENT_STATUS, name="disbursement_status"),
            nullable=False,
            server_default="generated",
        ),
        sa.Column("generated_at", sa.DateTime, nullable=True),
        sa.Column("uploaded_at", sa.DateTime, nullable=True),
        sa.Column("paid_at", sa.DateTime, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("remark", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_salary_disbursements_batch_id", "salary_disbursements", ["batch_id"]
    )
    op.create_index(
        "ix_salary_disbursements_store_id", "salary_disbursements", ["store_id"]
    )
    op.create_index(
        "ix_salary_disbursements_pay_month", "salary_disbursements", ["pay_month"]
    )
    op.create_index(
        "ix_salary_disbursement_store_month",
        "salary_disbursements",
        ["store_id", "pay_month"],
    )
    op.create_index(
        "ix_salary_disbursement_bank", "salary_disbursements", ["bank"]
    )


def downgrade() -> None:
    # 表
    op.drop_table("salary_disbursements")
    op.drop_table("special_additional_deductions")
    op.drop_table("personal_tax_records")
    op.drop_table("payroll_si_records")
    op.drop_table("employee_social_insurances")
    op.drop_table("social_insurance_configs")

    # Enum 类型
    bind = op.get_bind()
    for enum_name in (
        "disbursement_status",
        "disbursement_bank",
        "special_deduction_type",
        "insurance_type",
    ):
        bind.execute(sa.text(f"DROP TYPE IF EXISTS {enum_name}"))
