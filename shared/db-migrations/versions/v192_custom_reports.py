"""品牌自定义报表框架

Revision ID: v192
Revises: v191
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'v192'
down_revision = 'v191'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── 1. report_configs — 报表配置 ─────────────────────────────────────────
    op.create_table(
        'report_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.VARCHAR(100), nullable=False,
                  comment='报表名称'),
        sa.Column('description', sa.TEXT(), nullable=True),
        sa.Column('report_type', sa.VARCHAR(30), nullable=False,
                  server_default='custom',
                  comment='standard/custom/ai_narrative'),
        sa.Column('data_source', sa.VARCHAR(50), nullable=True,
                  comment='orders/members/inventory/employees/finance'),
        sa.Column('dimensions', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default='[]',
                  comment='维度字段列表：[{"field": "store_id", "label": "门店", "type": "dimension"}]'),
        sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default='[]',
                  comment='指标字段列表：[{"field": "revenue_fen", "label": "营业额", "agg": "sum"}]'),
        sa.Column('filters', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default='[]',
                  comment='过滤条件：[{"field": "date", "op": "gte", "value": "today-7d"}]'),
        sa.Column('sort_by', sa.VARCHAR(50), nullable=True,
                  comment='默认排序字段'),
        sa.Column('sort_order', sa.VARCHAR(4), nullable=False, server_default='desc'),
        sa.Column('chart_type', sa.VARCHAR(20), nullable=False, server_default='table',
                  comment='table/bar/line/pie'),
        sa.Column('is_public', sa.Boolean(), nullable=False, server_default='false',
                  comment='是否可分享'),
        sa.Column('share_token', sa.VARCHAR(64), nullable=True, unique=True,
                  comment='分享token，is_public=true时生效'),
        sa.Column('schedule_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment='定时推送配置：{"cron": "0 9 * * *", "channels": ["wecom"], "recipients": [...]}'),
        sa.Column('is_favorite', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('idx_report_configs_tenant', 'report_configs', ['tenant_id'])
    op.create_index('idx_report_configs_type', 'report_configs', ['tenant_id', 'report_type'])
    op.create_index(
        'idx_report_configs_share_token', 'report_configs', ['share_token'],
        postgresql_where=sa.text('share_token IS NOT NULL'),
    )

    # ─── 2. report_executions — 报表执行记录 ──────────────────────────────────
    op.create_table(
        'report_executions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('report_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('executed_by', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='NULL=定时触发'),
        sa.Column('status', sa.VARCHAR(20), nullable=False, server_default='running',
                  comment='running/completed/failed'),
        sa.Column('row_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('execution_ms', sa.Integer(), nullable=True,
                  comment='执行耗时'),
        sa.Column('error_msg', sa.TEXT(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ['report_id'], ['report_configs.id'], ondelete='CASCADE',
        ),
    )
    op.create_index('idx_report_executions_tenant', 'report_executions', ['tenant_id'])
    op.create_index('idx_report_executions_report', 'report_executions', ['report_id'])

    # ─── 3. narrative_templates — AI叙事模板 ──────────────────────────────────
    op.create_table(
        'narrative_templates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.VARCHAR(100), nullable=False,
                  comment='如"徐记海鲜活鲜专报"'),
        sa.Column('brand_focus', sa.VARCHAR(100), nullable=True,
                  comment='核心关注点：如"活鲜销售/毛利"'),
        sa.Column('prompt_prefix', sa.TEXT(), nullable=True,
                  comment='叙事生成前缀提示词'),
        sa.Column('metrics_weights', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment='指标权重：{"revenue": 0.4, "seafood_revenue": 0.6}'),
        sa.Column('tone', sa.VARCHAR(20), nullable=False, server_default='professional',
                  comment='professional/casual/executive'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('idx_narrative_templates_tenant', 'narrative_templates', ['tenant_id'])

    # ─── RLS 策略（3张表） ────────────────────────────────────────────────────
    for table in ('report_configs', 'report_executions', 'narrative_templates'):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
        """)


def downgrade() -> None:
    for table in ('report_configs', 'report_executions', 'narrative_templates'):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.drop_table('report_executions')
    op.drop_table('report_configs')
    op.drop_table('narrative_templates')
