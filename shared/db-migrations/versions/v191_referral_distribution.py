"""CRM三级分销体系

Revision ID: v191
Revises: v190
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'v191'
down_revision = 'v190'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── 1. referral_links — 推荐链接/码 ─────────────────────────────────────
    op.create_table(
        'referral_links',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('member_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='发起邀请的会员'),
        sa.Column('referral_code', sa.VARCHAR(20), nullable=False,
                  comment='推荐码，如TX8A3K'),
        sa.Column('channel', sa.VARCHAR(30), nullable=False, server_default='wechat',
                  comment='wechat/wecom/direct'),
        sa.Column('expires_at', sa.TIMESTAMP(timezone=True), nullable=True,
                  comment='有效期，NULL=永久'),
        sa.Column('click_count', sa.Integer(), nullable=False, server_default='0',
                  comment='点击次数'),
        sa.Column('convert_count', sa.Integer(), nullable=False, server_default='0',
                  comment='转化注册次数'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.UniqueConstraint('referral_code', name='uq_referral_links_code'),
    )
    op.create_index('idx_referral_links_tenant_id', 'referral_links', ['tenant_id'])
    op.create_index('idx_referral_links_member', 'referral_links', ['tenant_id', 'member_id'])
    # referral_code 已有 UNIQUE 约束覆盖高频查询，额外创建普通索引加速非唯一查询路径
    op.create_index('idx_referral_links_code', 'referral_links', ['referral_code'])

    # ─── 2. referral_relationships — 推荐关系树 ──────────────────────────────
    op.create_table(
        'referral_relationships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('referee_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='被推荐人/新会员'),
        sa.Column('level1_id', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='直接推荐人，一级'),
        sa.Column('level2_id', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='二级推荐人'),
        sa.Column('level3_id', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='三级推荐人'),
        sa.Column('referral_link_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('registered_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['referral_link_id'], ['referral_links.id'], ondelete='SET NULL',
        ),
    )
    op.create_index('idx_referral_relationships_tenant',
                    'referral_relationships', ['tenant_id'])
    op.create_index('idx_referral_relationships_referee',
                    'referral_relationships', ['tenant_id', 'referee_id'])
    op.create_index('idx_referral_relationships_level1',
                    'referral_relationships', ['tenant_id', 'level1_id'])

    # ─── 3. referral_rewards — 奖励记录 ──────────────────────────────────────
    op.create_table(
        'referral_rewards',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('member_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='获奖会员'),
        sa.Column('referee_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='因谁消费触发本次奖励'),
        sa.Column('reward_level', sa.Integer(), nullable=False,
                  comment='1/2/3，第几级奖励'),
        sa.Column('trigger_type', sa.VARCHAR(30), nullable=False,
                  server_default='first_order',
                  comment='first_order/order/recharge：首单/每单/充值触发'),
        sa.Column('reward_type', sa.VARCHAR(20), nullable=False,
                  server_default='coupon',
                  comment='coupon/points/cash：优惠券/积分/现金'),
        sa.Column('reward_value_fen', sa.BIGINT(), nullable=False, server_default='0',
                  comment='奖励金额/积分值，分'),
        sa.Column('status', sa.VARCHAR(20), nullable=False, server_default='pending',
                  comment='pending/issued/expired/cancelled'),
        sa.Column('order_id', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='触发订单'),
        sa.Column('issued_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('expires_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('idx_referral_rewards_tenant', 'referral_rewards', ['tenant_id'])
    op.create_index('idx_referral_rewards_member',
                    'referral_rewards', ['tenant_id', 'member_id'])
    op.create_index('idx_referral_rewards_status',
                    'referral_rewards', ['tenant_id', 'status'])

    # ─── RLS 策略（3张表） ────────────────────────────────────────────────────
    for table in ('referral_links', 'referral_relationships', 'referral_rewards'):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
        """)


def downgrade() -> None:
    for table in ('referral_links', 'referral_relationships', 'referral_rewards'):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.drop_table('referral_rewards')
    op.drop_table('referral_relationships')
    op.drop_table('referral_links')
