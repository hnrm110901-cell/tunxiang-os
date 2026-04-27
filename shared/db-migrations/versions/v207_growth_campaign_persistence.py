"""报名抽奖持久化 — report_draw._report_entries 内存→DB

将 report_draw.py 中 _report_entries 模块级字典（重启即丢）迁移到
campaign_report_entries 表，支持多租户隔离和 RLS 策略。

新增表：
  campaign_report_entries — 活动报名记录（报名人/报名时间/是否中奖）

Revision ID: v207c
Revises: v206
Create Date: 2026-04-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v207c"
down_revision = 'v206'
branch_labels = None
depends_on = None

TABLE = 'campaign_report_entries'


def upgrade() -> None:
    # ─── campaign_report_entries — 报名抽奖报名记录 ──────────────────────────
    op.create_table(
        TABLE,
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()'),
                  comment='主键'),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='租户ID（RLS隔离）'),
        sa.Column('campaign_id', sa.VARCHAR(128), nullable=False,
                  comment='活动ID（对应 campaigns.id，允许非UUID格式的外部ID）'),
        sa.Column('customer_id', sa.VARCHAR(128), nullable=False,
                  comment='报名顾客ID'),
        sa.Column('is_winner', sa.Boolean(), nullable=False, server_default='false',
                  comment='是否中奖'),
        sa.Column('prize', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment='中奖奖项信息，NULL=未中奖'),
        sa.Column('registered_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False,
                  comment='报名时间'),
        sa.Column('drawn_at', sa.TIMESTAMP(timezone=True), nullable=True,
                  comment='开奖时间（NULL=未开奖）'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.UniqueConstraint('tenant_id', 'campaign_id', 'customer_id',
                            name='uq_report_entry_customer'),
    )
    op.create_index('idx_report_entries_tenant', TABLE, ['tenant_id'])
    op.create_index('idx_report_entries_campaign', TABLE,
                    ['tenant_id', 'campaign_id'],
                    postgresql_where=sa.text('is_deleted = false'))
    op.create_index('idx_report_entries_customer', TABLE,
                    ['tenant_id', 'customer_id'],
                    postgresql_where=sa.text('is_deleted = false'))
    op.create_index('idx_report_entries_winner', TABLE,
                    ['tenant_id', 'campaign_id', 'is_winner'],
                    postgresql_where=sa.text('is_winner = true'))
    # 开奖场景（ORDER BY random() LIMIT k）：覆盖未中奖、未开奖的候选行
    op.create_index('idx_report_entries_pending_draw', TABLE,
                    ['tenant_id', 'campaign_id', 'registered_at'],
                    postgresql_where=sa.text(
                        'is_winner = false AND drawn_at IS NULL AND is_deleted = false'
                    ))

    # ─── RLS 策略 ────────────────────────────────────────────────────────────
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
        USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
    """)


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE}")
    op.drop_index('idx_report_entries_pending_draw', table_name=TABLE)
    op.drop_index('idx_report_entries_winner', table_name=TABLE)
    op.drop_index('idx_report_entries_customer', table_name=TABLE)
    op.drop_index('idx_report_entries_campaign', table_name=TABLE)
    op.drop_index('idx_report_entries_tenant', table_name=TABLE)
    op.drop_table(TABLE)
