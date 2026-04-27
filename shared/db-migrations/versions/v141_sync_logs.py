"""v141: 新增 sync_logs 表（品智POS数据同步历史记录）

每次自动同步（菜品/员工/桌台/订单/会员）完成后，
sync_scheduler 将结果写入此表，供运营查询和告警监控。

字段：
  id             — 主键 UUID
  tenant_id      — 租户ID（RLS 隔离）
  merchant_code  — 商户代码（czyz / zqx / sgc）
  sync_type      — 同步类型（dishes / tables / employees /
                   orders_incremental / members_incremental）
  status         — 状态（success / failed / partial）
  records_synced — 本次同步成功的记录数
  error_msg      — 错误信息（成功时为 NULL）
  started_at     — 任务开始时间
  finished_at    — 任务结束时间

RLS 策略与 v097/v101/v138/v139/v140 保持一致：
  NULLIF + WITH CHECK + FORCE ROW LEVEL SECURITY

Revision ID: v141
Revises: v140
Create Date: 2026-04-04
"""

import sqlalchemy as sa
from alembic import op

revision = "v141"
down_revision = "v140"
branch_labels = None
depends_on = None

_TABLE = "sync_logs"
_POLICY = "sync_logs_tenant_isolation"
_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "merchant_code",
            sa.String(20),
            nullable=False,
        ),
        sa.Column(
            "sync_type",
            sa.String(40),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="success",
        ),
        sa.Column(
            "records_synced",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "error_msg",
            sa.Text,
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 常用查询索引
    op.create_index("idx_sync_logs_tenant_merchant", _TABLE, ["tenant_id", "merchant_code"])
    op.create_index("idx_sync_logs_started_at", _TABLE, ["started_at"])
    op.create_index("idx_sync_logs_status", _TABLE, ["status"])

    # RLS — FORCE + 标准安全策略（NULLIF + WITH CHECK）
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {_POLICY} ON {_TABLE}
            USING ({_SAFE_CONDITION})
            WITH CHECK ({_SAFE_CONDITION})
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON {_TABLE}")
    op.execute(f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_sync_logs_status", _TABLE)
    op.drop_index("idx_sync_logs_started_at", _TABLE)
    op.drop_index("idx_sync_logs_tenant_merchant", _TABLE)
    op.drop_table(_TABLE)
