"""z66 — D12 薪资项目库（移植自 tunxiang-os tx-org）

- 扩展 salary_item_definitions：新增 tax_attribute 列 + item_code 索引
- 新增 employee_salary_items：员工-薪资项目分配（带生效时间窗）
- 新增 payslip_lines：工资条明细行（按 tax_attribute 分类聚合）

模型：src/models/salary_item.py（SalaryItemDefinition/EmployeeSalaryItem/PayslipLine）

Revision ID: z66_d12_salary_item_library
Revises: z65_d5_d7_closing_access
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID


# revision identifiers, used by Alembic.
revision = "z66_d12_salary_item_library"
down_revision = "z65_d5_d7_closing_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ────────── 1) 扩展 salary_item_definitions ──────────
    with op.batch_alter_table("salary_item_definitions") as batch:
        batch.add_column(
            sa.Column("tax_attribute", sa.String(length=20), nullable=True)
        )
    op.create_index(
        "ix_salary_item_definitions_tax_attribute",
        "salary_item_definitions",
        ["tax_attribute"],
    )
    op.create_index(
        "ix_salary_item_definitions_item_code",
        "salary_item_definitions",
        ["item_code"],
    )

    # ────────── 2) employee_salary_items ──────────
    op.create_table(
        "employee_salary_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "employee_id",
            sa.String(length=50),
            sa.ForeignKey("employees.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("salary_item_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("amount_fen", sa.Integer(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "employee_id",
            "salary_item_id",
            "effective_from",
            name="uq_emp_salary_item_effective",
        ),
    )

    # ────────── 3) payslip_lines ──────────
    op.create_table(
        "payslip_lines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("payroll_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("store_id", sa.String(length=50), nullable=False, index=True),
        sa.Column("employee_id", sa.String(length=50), nullable=False, index=True),
        sa.Column("pay_month", sa.String(length=7), nullable=False, index=True),
        sa.Column("salary_item_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("item_code", sa.String(length=50), nullable=False),
        sa.Column("item_name", sa.String(length=100), nullable=False),
        sa.Column("item_category", sa.String(length=30), nullable=False),
        sa.Column("tax_attribute", sa.String(length=20), nullable=False, index=True),
        sa.Column("amount_fen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("calc_basis", JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "employee_id", "pay_month", "salary_item_id", name="uq_payslip_line"
        ),
    )


def downgrade() -> None:
    op.drop_table("payslip_lines")
    op.drop_table("employee_salary_items")
    op.drop_index(
        "ix_salary_item_definitions_item_code",
        table_name="salary_item_definitions",
    )
    op.drop_index(
        "ix_salary_item_definitions_tax_attribute",
        table_name="salary_item_definitions",
    )
    with op.batch_alter_table("salary_item_definitions") as batch:
        batch.drop_column("tax_attribute")
