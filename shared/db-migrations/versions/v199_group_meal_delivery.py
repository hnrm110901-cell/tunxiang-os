"""团餐企业客户 + 外卖自营配送

Revision ID: v199
Revises: v198
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'v199'
down_revision = 'v198'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── 1. corporate_customers — 企业客户主数据 ───────────────────────────────
    op.create_table(
        'corporate_customers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('company_name', sa.VARCHAR(100), nullable=False),
        sa.Column('company_code', sa.VARCHAR(30), unique=True, nullable=True,
                  comment='企业编码，全局唯一'),
        sa.Column('contact_name', sa.VARCHAR(50), nullable=True),
        sa.Column('contact_phone', sa.VARCHAR(20), nullable=True),
        sa.Column('billing_type', sa.VARCHAR(20), nullable=False,
                  server_default='monthly',
                  comment='monthly/weekly/immediate：月结/周结/即结'),
        sa.Column('credit_limit_fen', sa.BigInteger(), nullable=False,
                  server_default='0', comment='授信额度（分）'),
        sa.Column('used_credit_fen', sa.BigInteger(), nullable=False,
                  server_default='0', comment='已用授信（分）'),
        sa.Column('tax_no', sa.VARCHAR(30), nullable=True, comment='开票税号'),
        sa.Column('invoice_title', sa.VARCHAR(100), nullable=True, comment='发票抬头'),
        sa.Column('discount_rate', sa.NUMERIC(4, 3), nullable=False,
                  server_default='1.000', comment='企业专属折扣率，如0.900=九折'),
        sa.Column('approved_menu_ids', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='[]',
                  comment='允许点的菜品ID白名单，空=全部允许'),
        sa.Column('status', sa.VARCHAR(20), nullable=False, server_default='active'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
    )

    # 索引
    op.create_index('idx_corporate_customers_tenant',
                    'corporate_customers', ['tenant_id'])
    op.create_index('idx_corporate_customers_status',
                    'corporate_customers', ['tenant_id', 'status'])

    # RLS
    op.execute("ALTER TABLE corporate_customers ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY corporate_customers_tenant_isolation ON corporate_customers
        USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
    """)

    # ─── 2. delivery_orders — 自营配送单 ──────────────────────────────────────
    op.create_table(
        'self_delivery_orders',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('order_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='关联交易订单'),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('delivery_address', sa.Text(), nullable=False),
        sa.Column('delivery_lat', sa.NUMERIC(10, 7), nullable=True),
        sa.Column('delivery_lng', sa.NUMERIC(10, 7), nullable=True),
        sa.Column('distance_meters', sa.Integer(), nullable=True),
        sa.Column('estimated_minutes', sa.Integer(), nullable=True,
                  comment='预计配送时长（分钟）'),
        sa.Column('actual_minutes', sa.Integer(), nullable=True),
        sa.Column('rider_id', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='配送员ID'),
        sa.Column('rider_name', sa.VARCHAR(50), nullable=True),
        sa.Column('rider_phone', sa.VARCHAR(20), nullable=True),
        sa.Column('status', sa.VARCHAR(20), nullable=False,
                  server_default='pending',
                  comment='pending/assigned/picked_up/delivering/delivered/failed'),
        sa.Column('dispatch_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('picked_up_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('failed_reason', sa.Text(), nullable=True),
        sa.Column('delivery_fee_fen', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('tip_fen', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
    )

    # 索引
    op.create_index('idx_delivery_orders_tenant',
                    'self_delivery_orders', ['tenant_id'])
    op.create_index('idx_delivery_orders_order',
                    'self_delivery_orders', ['order_id'])
    op.create_index('idx_delivery_orders_rider',
                    'self_delivery_orders', ['tenant_id', 'rider_id'])
    op.create_index('idx_delivery_orders_status',
                    'self_delivery_orders', ['tenant_id', 'status'])

    # RLS
    op.execute("ALTER TABLE self_delivery_orders ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY self_delivery_orders_tenant_isolation ON self_delivery_orders
        USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
    """)


def downgrade() -> None:
    # 删除 self_delivery_orders
    op.execute("DROP POLICY IF EXISTS self_delivery_orders_tenant_isolation ON self_delivery_orders")
    op.drop_index('idx_delivery_orders_status', table_name='self_delivery_orders')
    op.drop_index('idx_delivery_orders_rider', table_name='self_delivery_orders')
    op.drop_index('idx_delivery_orders_order', table_name='self_delivery_orders')
    op.drop_index('idx_delivery_orders_tenant', table_name='self_delivery_orders')
    op.drop_table('self_delivery_orders')

    # 删除 corporate_customers
    op.execute("DROP POLICY IF EXISTS corporate_customers_tenant_isolation ON corporate_customers")
    op.drop_index('idx_corporate_customers_status', table_name='corporate_customers')
    op.drop_index('idx_corporate_customers_tenant', table_name='corporate_customers')
    op.drop_table('corporate_customers')
