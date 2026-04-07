"""多渠道菜单发布完善 + 付费会员卡产品化

Revision ID: v196
Revises: v195
Create Date: 2026-04-07

包含两张新表：
  1. channel_menu_overrides  — 门店/渠道菜单差价/上下架覆盖配置
  2. premium_membership_cards — 付费会员卡档案（月卡/季卡/年卡/终身卡）
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'v196'
down_revision = 'v195'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── 1. channel_menu_overrides — 门店渠道菜单覆盖 ──────────────────────────
    op.create_table(
        'channel_menu_overrides',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='哪个门店的覆盖'),
        sa.Column('dish_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='哪道菜'),
        sa.Column('channel', sa.VARCHAR(30), nullable=False,
                  comment='dine_in/takeaway/meituan/eleme/douyin/miniapp/all'),
        sa.Column('price_fen', sa.BIGINT(), nullable=True,
                  comment='覆盖价格（分），NULL=使用品牌标准价'),
        sa.Column('is_available', sa.Boolean(), nullable=False, server_default='true',
                  comment='是否在该渠道该门店可见'),
        sa.Column('available_from', sa.TIME(), nullable=True,
                  comment='时段限制：起始时间，NULL=全天'),
        sa.Column('available_until', sa.TIME(), nullable=True,
                  comment='时段限制：结束时间'),
        sa.Column('override_reason', sa.VARCHAR(100), nullable=True,
                  comment='覆盖原因：regional_price/stock/promotion'),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('effective_date', sa.DATE(), nullable=True),
        sa.Column('expires_date', sa.DATE(), nullable=True,
                  comment='NULL=永久有效'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.UniqueConstraint(
            'tenant_id', 'store_id', 'dish_id', 'channel',
            name='uq_channel_menu_overrides_store_dish_channel',
        ),
    )
    op.create_index(
        'idx_channel_menu_overrides_tenant',
        'channel_menu_overrides', ['tenant_id'],
    )
    op.create_index(
        'idx_channel_menu_overrides_store',
        'channel_menu_overrides', ['tenant_id', 'store_id'],
    )
    op.create_index(
        'idx_channel_menu_overrides_dish',
        'channel_menu_overrides', ['tenant_id', 'dish_id'],
    )
    op.create_index(
        'idx_channel_menu_overrides_lookup',
        'channel_menu_overrides', ['tenant_id', 'store_id', 'channel'],
        comment='查询门店渠道覆盖的主索引',
    )

    # ─── 2. premium_membership_cards — 付费会员卡档案 ────────────────────────
    op.create_table(
        'premium_membership_cards',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('card_no', sa.VARCHAR(30), nullable=False, unique=True,
                  comment='卡号：PMC-YYYYMM-XXXX'),
        sa.Column('member_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('card_type', sa.VARCHAR(30), nullable=False,
                  comment='monthly/quarterly/annual/lifetime：月卡/季卡/年卡/终身卡'),
        sa.Column('price_fen', sa.BIGINT(), nullable=False,
                  comment='购买价格（分）'),
        sa.Column('start_date', sa.DATE(), nullable=False),
        sa.Column('end_date', sa.DATE(), nullable=True,
                  comment='终身卡为NULL'),
        sa.Column('status', sa.VARCHAR(20), nullable=False, server_default='active',
                  comment='active/expired/cancelled/suspended'),
        sa.Column('benefits', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default='{}',
                  comment='权益包：{"discount_rate": 0.88, "free_dishes": ["招牌汤"], "priority_booking": true}'),
        sa.Column('purchase_channel', sa.VARCHAR(30), nullable=True,
                  comment='miniapp/pos/wecom'),
        sa.Column('refund_amount_fen', sa.BIGINT(), nullable=False, server_default='0'),
        sa.Column('refunded_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('auto_renew', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('notes', sa.TEXT(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index(
        'idx_premium_membership_cards_tenant',
        'premium_membership_cards', ['tenant_id'],
    )
    op.create_index(
        'idx_premium_membership_cards_member',
        'premium_membership_cards', ['tenant_id', 'member_id'],
    )
    op.create_index(
        'idx_premium_membership_cards_status',
        'premium_membership_cards', ['tenant_id', 'status'],
    )
    op.create_index(
        'idx_premium_membership_cards_end_date',
        'premium_membership_cards', ['tenant_id', 'end_date'],
        comment='到期预警查询',
    )

    # ─── RLS 策略（2张新表） ────────────────────────────────────────────────────
    for table in ('channel_menu_overrides', 'premium_membership_cards'):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
        """)


def downgrade() -> None:
    for table in ('channel_menu_overrides', 'premium_membership_cards'):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.drop_index('idx_channel_menu_overrides_lookup', table_name='channel_menu_overrides')
    op.drop_index('idx_channel_menu_overrides_dish', table_name='channel_menu_overrides')
    op.drop_index('idx_channel_menu_overrides_store', table_name='channel_menu_overrides')
    op.drop_index('idx_channel_menu_overrides_tenant', table_name='channel_menu_overrides')
    op.drop_table('channel_menu_overrides')

    op.drop_index('idx_premium_membership_cards_end_date', table_name='premium_membership_cards')
    op.drop_index('idx_premium_membership_cards_status', table_name='premium_membership_cards')
    op.drop_index('idx_premium_membership_cards_member', table_name='premium_membership_cards')
    op.drop_index('idx_premium_membership_cards_tenant', table_name='premium_membership_cards')
    op.drop_table('premium_membership_cards')
