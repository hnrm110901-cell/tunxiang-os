"""z15 — 业财税资金 Phase 5 Month 3: 结算风控引擎 + 多门店驾驶舱

Revision ID: z15
Revises: z14
Create Date: 2026-03-07

Adds:
  settlement_records — 平台结算记录（美团/饿了么/微信支付/收钱吧等）
  settlement_items   — 结算明细行项（每笔可核销的收款/扣费项）
"""
from alembic import op
import sqlalchemy as sa

revision = 'z15'
down_revision = 'z14'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 平台结算主记录 ────────────────────────────────────────────────────────
    op.create_table(
        'settlement_records',
        sa.Column('id',            sa.String(36),  primary_key=True),
        sa.Column('store_id',      sa.String(36),  nullable=False),
        sa.Column('brand_id',      sa.String(36),  nullable=True),
        # 结算平台
        sa.Column('platform',      sa.String(32),  nullable=False),
        # meituan / eleme / wechat_pay / alipay / unionpay / cash / other
        sa.Column('period',        sa.String(7),   nullable=False),  # YYYY-MM
        sa.Column('settlement_no', sa.String(128), nullable=True,    unique=True),
        # 平台结算单号
        sa.Column('settle_date',   sa.Date,        nullable=False),  # 实际打款日
        sa.Column('cycle_start',   sa.Date,        nullable=True),   # 结算周期起
        sa.Column('cycle_end',     sa.Date,        nullable=True),   # 结算周期止
        # 金额
        sa.Column('gross_yuan',    sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('commission_yuan', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('refund_yuan',   sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('adjustment_yuan', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('net_yuan',      sa.Numeric(14, 2), nullable=False, server_default='0'),
        # 系统预期金额（从业务事件推算）
        sa.Column('expected_yuan', sa.Numeric(14, 2), nullable=True),
        sa.Column('deviation_yuan', sa.Numeric(14, 2), nullable=True),  # net - expected
        sa.Column('deviation_pct', sa.Numeric(6, 2),  nullable=True),
        # 风控状态
        sa.Column('risk_level',    sa.String(8),   nullable=False, server_default='low'),
        # 处理状态 FSM: pending → verified / disputed / auto_closed
        sa.Column('status',        sa.String(16),  nullable=False, server_default='pending'),
        sa.Column('verified_at',   sa.DateTime(timezone=True), nullable=True),
        sa.Column('verified_by',   sa.String(64),  nullable=True),
        sa.Column('notes',         sa.Text,        nullable=True),
        sa.Column('created_at',    sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',    sa.DateTime(timezone=True), server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )
    op.create_index('ix_sr_store_period',   'settlement_records', ['store_id', 'period'])
    op.create_index('ix_sr_platform',       'settlement_records', ['platform', 'settle_date'])
    op.create_index('ix_sr_risk_status',    'settlement_records', ['risk_level', 'status'])
    op.create_index(
        'ix_sr_pending_risk',
        'settlement_records',
        ['store_id', 'settle_date'],
        postgresql_where=sa.text("status = 'pending' AND risk_level != 'low'"),
    )

    # ── 结算明细行项 ──────────────────────────────────────────────────────────
    op.create_table(
        'settlement_items',
        sa.Column('id',              sa.String(36),  primary_key=True),
        sa.Column('settlement_id',   sa.String(36),
                  sa.ForeignKey('settlement_records.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('store_id',        sa.String(36),  nullable=False),
        sa.Column('item_type',       sa.String(32),  nullable=False),
        # sale_income / commission / refund_deduction / marketing_subsidy /
        # packaging_fee / tech_fee / adjustment / other
        sa.Column('item_desc',       sa.String(256), nullable=True),
        sa.Column('amount_yuan',     sa.Numeric(14, 2), nullable=False),
        # 关联原始事件
        sa.Column('ref_event_id',    sa.String(36),  nullable=True),
        # 核对状态
        sa.Column('reconciled',      sa.Boolean,     nullable=False, server_default='false'),
        sa.Column('reconciled_at',   sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at',      sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_si_settlement',  'settlement_items', ['settlement_id'])
    op.create_index('ix_si_store_type',  'settlement_items', ['store_id', 'item_type'])
    op.create_index(
        'ix_si_unreconciled',
        'settlement_items',
        ['store_id', 'created_at'],
        postgresql_where=sa.text("reconciled = false"),
    )


def downgrade() -> None:
    op.drop_table('settlement_items')
    op.drop_table('settlement_records')
