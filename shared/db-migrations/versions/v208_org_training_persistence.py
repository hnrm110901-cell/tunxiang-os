"""门店借调持久化 — transfers._transfer_store 内存→DB

为 employee_transfers 表补全借调所需字段：
  employee_name  — 员工姓名（冗余存储，避免关联查询）
  from_store_name — 原门店名称（冗余存储）
  to_store_name   — 借调目标门店名称（冗余存储）
  start_date      — 借调开始日期
  end_date        — 借调结束日期
  approved_at     — 审批时间

Revision ID: v208
Revises: v207
Create Date: 2026-04-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'v208'
down_revision = 'v207'
branch_labels = None
depends_on = None

TABLE = 'employee_transfers'


def upgrade() -> None:
    # ─── 补全 employee_transfers 缺失字段 ──────────────────────────────────────
    op.add_column(TABLE, sa.Column(
        'employee_name', sa.VARCHAR(100), nullable=True,
        comment='员工姓名（冗余存储，避免关联查询）'
    ))
    op.add_column(TABLE, sa.Column(
        'from_store_name', sa.VARCHAR(100), nullable=True,
        comment='原门店名称（冗余存储）'
    ))
    op.add_column(TABLE, sa.Column(
        'to_store_name', sa.VARCHAR(100), nullable=True,
        comment='借调目标门店名称（冗余存储）'
    ))
    op.add_column(TABLE, sa.Column(
        'start_date', sa.Date(), nullable=True,
        comment='借调开始日期'
    ))
    op.add_column(TABLE, sa.Column(
        'end_date', sa.Date(), nullable=True,
        comment='借调结束日期'
    ))
    op.add_column(TABLE, sa.Column(
        'approved_at', sa.TIMESTAMP(timezone=True), nullable=True,
        comment='审批时间'
    ))

    # ─── 辅助索引（门店+时间范围查询） ───────────────────────────────────────────
    op.create_index(
        'idx_employee_transfers_store_dates',
        TABLE,
        ['tenant_id', 'from_store_id', 'to_store_id', 'start_date', 'end_date'],
        postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index('idx_employee_transfers_store_dates', table_name=TABLE)
    op.drop_column(TABLE, 'approved_at')
    op.drop_column(TABLE, 'end_date')
    op.drop_column(TABLE, 'start_date')
    op.drop_column(TABLE, 'to_store_name')
    op.drop_column(TABLE, 'from_store_name')
    op.drop_column(TABLE, 'employee_name')
