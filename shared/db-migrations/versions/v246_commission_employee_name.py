"""commission_records 增加 employee_name 冗余列

在月结时将员工姓名写入记录，避免跨服务查询以及员工离职后姓名丢失。

Revision ID: v246
Revises: v245
Create Date: 2026-04-13
"""

import sqlalchemy as sa
from alembic import op

revision = "v246"
down_revision = "v245"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # 只在列不存在时才添加（幂等）
    cols = {c["name"] for c in sa.inspect(conn).get_columns("commission_records")}
    if "employee_name" not in cols:
        op.add_column(
            "commission_records",
            sa.Column(
                "employee_name",
                sa.String(100),
                nullable=True,
                comment="员工姓名冗余（月结时从 employees 表快照，防止人员变动后历史记录无法显示姓名）",
            ),
        )
        op.create_index(
            "ix_commission_records_employee_name",
            "commission_records",
            ["employee_name"],
        )


def downgrade() -> None:
    op.drop_index("ix_commission_records_employee_name", "commission_records")
    op.drop_column("commission_records", "employee_name")
