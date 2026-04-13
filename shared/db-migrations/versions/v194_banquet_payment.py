"""宴席支付状态机 — 定金/尾款闭环

Revision ID: v194
Revises: v193
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'v194'
down_revision = 'v193'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── 1. banquet_orders（宴席预订订单，如已存在则补字段）────────────────────
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'banquet_orders' not in existing_tables:
        op.create_table(
            'banquet_orders',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('contact_name', sa.VARCHAR(50), nullable=True),
            sa.Column('contact_phone', sa.VARCHAR(20), nullable=True),
            sa.Column('banquet_date', sa.DATE(), nullable=False),
            sa.Column('banquet_time', sa.TIME(), nullable=False),
            sa.Column('guest_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('table_ids', postgresql.JSONB(astext_type=sa.Text()),
                      nullable=False, server_default="'[]'"),
            sa.Column('total_fen', sa.BigInteger(), nullable=False, server_default='0'),
            sa.Column('deposit_rate', sa.NUMERIC(4, 2), nullable=False, server_default='0.30',
                      comment='定金比例，默认30%'),
            sa.Column('deposit_fen', sa.BigInteger(), nullable=False, server_default='0',
                      comment='定金金额=总额×deposit_rate，写入时计算'),
            sa.Column('balance_fen', sa.BigInteger(), nullable=False, server_default='0',
                      comment='尾款=总额-定金'),
            sa.Column('deposit_status', sa.VARCHAR(20), nullable=False, server_default='unpaid',
                      comment='unpaid/paid'),
            sa.Column('balance_status', sa.VARCHAR(20), nullable=False, server_default='unpaid',
                      comment='unpaid/paid'),
            sa.Column('payment_status', sa.VARCHAR(20), nullable=False, server_default='unpaid',
                      comment='unpaid/deposit_paid/fully_paid/refunded'),
            sa.Column('status', sa.VARCHAR(20), nullable=False, server_default='pending',
                      comment='pending/confirmed/in_progress/completed/cancelled'),
            sa.Column('notes', sa.TEXT(), nullable=True),
            sa.Column('cancel_reason', sa.TEXT(), nullable=True),
            sa.Column('cancelled_at', sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('NOW()'), nullable=False),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('NOW()'), nullable=False),
        )
        # RLS on new table
        op.execute("ALTER TABLE banquet_orders ENABLE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY banquet_orders_tenant_isolation ON banquet_orders
            USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
        """)
    else:
        # 已有 banquet_orders 表，补充缺失字段
        existing_cols = {c['name'] for c in inspector.get_columns('banquet_orders')}
        _add_col_if_missing = _make_add_col_fn(existing_cols)

        _add_col_if_missing('deposit_rate',
            sa.Column('deposit_rate', sa.NUMERIC(4, 2), nullable=False, server_default='0.30'))
        _add_col_if_missing('deposit_fen',
            sa.Column('deposit_fen', sa.BigInteger(), nullable=False, server_default='0'))
        _add_col_if_missing('balance_fen',
            sa.Column('balance_fen', sa.BigInteger(), nullable=False, server_default='0'))
        _add_col_if_missing('deposit_status',
            sa.Column('deposit_status', sa.VARCHAR(20), nullable=False, server_default='unpaid'))
        _add_col_if_missing('balance_status',
            sa.Column('balance_status', sa.VARCHAR(20), nullable=False, server_default='unpaid'))
        _add_col_if_missing('payment_status',
            sa.Column('payment_status', sa.VARCHAR(20), nullable=False, server_default='unpaid'))
        _add_col_if_missing('banquet_date',
            sa.Column('banquet_date', sa.DATE(), nullable=True))
        _add_col_if_missing('banquet_time',
            sa.Column('banquet_time', sa.TIME(), nullable=True))
        _add_col_if_missing('cancel_reason',
            sa.Column('cancel_reason', sa.TEXT(), nullable=True))
        _add_col_if_missing('cancelled_at',
            sa.Column('cancelled_at', sa.TIMESTAMP(timezone=True), nullable=True))

    # ─── 2. banquet_payments（宴席支付记录）─────────────────────────────────────
    op.create_table(
        'banquet_payments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('banquet_order_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='关联宴席订单'),
        sa.Column('payment_stage', sa.VARCHAR(20), nullable=False,
                  comment='deposit/balance/full：定金/尾款/全额'),
        sa.Column('amount_fen', sa.BigInteger(), nullable=False),
        sa.Column('payment_method', sa.VARCHAR(30), nullable=True,
                  comment='wechat/alipay/cash/card/transfer'),
        sa.Column('payment_status', sa.VARCHAR(20), nullable=False, server_default='pending',
                  comment='pending/paid/refunding/refunded/failed'),
        sa.Column('transaction_id', sa.VARCHAR(100), nullable=True,
                  comment='第三方支付流水号'),
        sa.Column('paid_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('refund_amount_fen', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('refunded_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('operator_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('notes', sa.TEXT(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
    )

    # ─── 3. 索引 ─────────────────────────────────────────────────────────────
    op.create_index('idx_banquet_payments_tenant', 'banquet_payments', ['tenant_id'])
    op.create_index('idx_banquet_payments_order', 'banquet_payments', ['banquet_order_id'])

    # banquet_orders 索引（CREATE INDEX IF NOT EXISTS 防止重复）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_banquet_orders_tenant
        ON banquet_orders(tenant_id)
    """)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='banquet_orders' AND column_name='banquet_date'
            ) THEN
                CREATE INDEX IF NOT EXISTS idx_banquet_orders_date
                ON banquet_orders(tenant_id, banquet_date);
            END IF;
        END$$;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_banquet_orders_status
        ON banquet_orders(tenant_id, payment_status)
    """)

    # ─── 4. RLS — banquet_payments ────────────────────────────────────────────
    op.execute("ALTER TABLE banquet_payments ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY banquet_payments_tenant_isolation ON banquet_payments
        USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
    """)


def _make_add_col_fn(existing_cols: set):
    """返回一个帮助函数：仅当列不存在时才添加。"""
    def _add(col_name: str, col_def: sa.Column) -> None:
        if col_name not in existing_cols:
            op.add_column('banquet_orders', col_def)
    return _add


def downgrade() -> None:
    # banquet_payments
    op.execute("DROP POLICY IF EXISTS banquet_payments_tenant_isolation ON banquet_payments")
    op.drop_table('banquet_payments')

    # banquet_orders（仅当本迁移新建了该表时才删除）
    # 安全起见：只删除本迁移添加的字段，不整体删表（可能已存在其他字段）
    for col in ('deposit_rate', 'deposit_fen', 'balance_fen',
                'deposit_status', 'balance_status', 'payment_status',
                'cancel_reason', 'cancelled_at'):
        op.execute(f"ALTER TABLE banquet_orders DROP COLUMN IF EXISTS {col}")
