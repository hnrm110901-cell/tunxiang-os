"""门店借调持久化 — transfers._transfer_store 内存→DB

为 employee_transfers 表补全借调所需字段：
  employee_name  — 员工姓名（冗余存储，避免关联查询）
  from_store_name — 原门店名称（冗余存储）
  to_store_name   — 借调目标门店名称（冗余存储）
  start_date      — 借调开始日期（NOT NULL，业务必填）
  end_date        — 借调结束日期（NOT NULL，业务必填）
  approved_at     — 审批时间（nullable，待审批时为空）

Revision ID: v208
Revises: v207
Create Date: 2026-04-11
"""

import sqlalchemy as sa
from alembic import op

revision = "v287"
down_revision = "v207"
branch_labels = None
depends_on = None

TABLE = "employee_transfers"


def upgrade() -> None:
    # ─── 补全 employee_transfers 缺失字段 ──────────────────────────────────────
    op.add_column(
        TABLE, sa.Column("employee_name", sa.VARCHAR(100), nullable=True, comment="员工姓名（冗余存储，避免关联查询）")
    )
    op.add_column(TABLE, sa.Column("from_store_name", sa.VARCHAR(100), nullable=True, comment="原门店名称（冗余存储）"))
    op.add_column(
        TABLE, sa.Column("to_store_name", sa.VARCHAR(100), nullable=True, comment="借调目标门店名称（冗余存储）")
    )
    # 先用 server_default 回填历史行，再设 NOT NULL
    op.add_column(
        TABLE, sa.Column("start_date", sa.Date(), nullable=True, server_default="1970-01-01", comment="借调开始日期")
    )
    op.add_column(
        TABLE, sa.Column("end_date", sa.Date(), nullable=True, server_default="1970-01-01", comment="借调结束日期")
    )
    op.alter_column(TABLE, "start_date", nullable=False, server_default=None)
    op.alter_column(TABLE, "end_date", nullable=False, server_default=None)

    op.add_column(
        TABLE, sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="审批时间（待审批时为空）")
    )

    # ─── 索引：覆盖常用查询路径 ──────────────────────────────────────────────────
    # 门店+时间范围查询
    op.create_index(
        "idx_employee_transfers_store_dates",
        TABLE,
        ["tenant_id", "from_store_id", "start_date"],
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "idx_employee_transfers_to_store",
        TABLE,
        ["tenant_id", "to_store_id", "start_date"],
        postgresql_where=sa.text("is_deleted = false"),
    )
    # 员工维度查询（list_transfers 按 employee_id 过滤）
    op.create_index(
        "idx_employee_transfers_employee",
        TABLE,
        ["tenant_id", "employee_id", "created_at"],
        postgresql_where=sa.text("is_deleted = false"),
    )
    # 状态过滤查询
    op.create_index(
        "idx_employee_transfers_status",
        TABLE,
        ["tenant_id", "status", "created_at"],
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index("idx_employee_transfers_status", table_name=TABLE)
    op.drop_index("idx_employee_transfers_employee", table_name=TABLE)
    op.drop_index("idx_employee_transfers_to_store", table_name=TABLE)
    op.drop_index("idx_employee_transfers_store_dates", table_name=TABLE)
    op.drop_column(TABLE, "approved_at")
    op.drop_column(TABLE, "end_date")
    op.drop_column(TABLE, "start_date")
    op.drop_column(TABLE, "to_store_name")
    op.drop_column(TABLE, "from_store_name")
    op.drop_column(TABLE, "employee_name")
