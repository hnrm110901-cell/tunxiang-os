"""member channel bindings for golden ID mapping

Revision ID: v201
Revises: v200
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = 'v201'
down_revision = 'v200'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── 1. member_channel_bindings — 外卖渠道绑定表 ────────────────────────────
    op.create_table(
        'member_channel_bindings',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', UUID(as_uuid=True), nullable=False,
                  comment='内部 Golden ID'),
        sa.Column('channel_type', sa.String(20), nullable=False,
                  comment='meituan/eleme/douyin/wechat'),
        sa.Column('channel_openid', sa.String(128), nullable=False),
        sa.Column('phone_hash', sa.String(64), nullable=True,
                  comment='sha256(phone+salt)，隐私保护'),
        sa.Column('binding_status', sa.String(20), nullable=False,
                  server_default='active',
                  comment='active/unbound/conflict'),
        sa.Column('conflict_resolved_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('conflict_resolved_by', sa.String(64), nullable=True),
        sa.Column('extra', JSONB, nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
    )

    # 索引
    op.create_index('ix_member_channel_bindings_tenant',
                    'member_channel_bindings', ['tenant_id'])
    op.create_index('ix_member_channel_bindings_customer',
                    'member_channel_bindings', ['customer_id'])
    op.create_index(
        'ix_member_channel_bindings_channel_unique',
        'member_channel_bindings',
        ['tenant_id', 'channel_type', 'channel_openid'],
        unique=True,
    )

    # RLS
    op.execute("ALTER TABLE member_channel_bindings ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY member_channel_bindings_tenant_isolation ON member_channel_bindings
        USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
    """)

    # ─── 2. golden_id_merge_logs — Golden ID 合并日志 ────────────────────────────
    op.create_table(
        'golden_id_merge_logs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False),
        sa.Column('source_customer_id', UUID(as_uuid=True), nullable=False),
        sa.Column('target_customer_id', UUID(as_uuid=True), nullable=False),
        sa.Column('merge_reason', sa.String(50), nullable=False,
                  comment='phone_match/manual/auto_rule'),
        sa.Column('merge_metadata', JSONB, nullable=True),
        sa.Column('operator_id', sa.String(64), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
    )

    # 索引
    op.create_index('ix_golden_id_merge_logs_tenant',
                    'golden_id_merge_logs', ['tenant_id'])
    op.create_index('ix_golden_id_merge_logs_source',
                    'golden_id_merge_logs', ['source_customer_id'])
    op.create_index('ix_golden_id_merge_logs_target',
                    'golden_id_merge_logs', ['target_customer_id'])

    # RLS
    op.execute("ALTER TABLE golden_id_merge_logs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY golden_id_merge_logs_tenant_isolation ON golden_id_merge_logs
        USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
    """)


def downgrade() -> None:
    # 删除 golden_id_merge_logs
    op.execute("DROP POLICY IF EXISTS golden_id_merge_logs_tenant_isolation ON golden_id_merge_logs")
    op.drop_index('ix_golden_id_merge_logs_target', table_name='golden_id_merge_logs')
    op.drop_index('ix_golden_id_merge_logs_source', table_name='golden_id_merge_logs')
    op.drop_index('ix_golden_id_merge_logs_tenant', table_name='golden_id_merge_logs')
    op.drop_table('golden_id_merge_logs')

    # 删除 member_channel_bindings
    op.execute("DROP POLICY IF EXISTS member_channel_bindings_tenant_isolation ON member_channel_bindings")
    op.drop_index('ix_member_channel_bindings_channel_unique', table_name='member_channel_bindings')
    op.drop_index('ix_member_channel_bindings_customer', table_name='member_channel_bindings')
    op.drop_index('ix_member_channel_bindings_tenant', table_name='member_channel_bindings')
    op.drop_table('member_channel_bindings')
