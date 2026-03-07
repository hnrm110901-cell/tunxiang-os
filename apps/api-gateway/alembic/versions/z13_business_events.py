"""z13 — 业财税资金 Phase 5 Month 1: 经营事件中心 + 利润归因基础

Revision ID: z13
Revises: z12
Create Date: 2026-03-07

Adds:
  business_events       — 标准化经营事件流水（10种事件类型）
  event_mapping_rules   — POS/渠道事件 → 标准事件映射规则
  tax_rules             — 税务规则配置（税种/税率/适用场景）
  risk_tasks            — 结算风控待办任务
  profit_attribution_results — 利润归因计算结果缓存
"""
from alembic import op
import sqlalchemy as sa

revision = 'z13'
down_revision = 'z12'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 标准化经营事件流水 ──────────────────────────────────────────────────
    op.create_table(
        'business_events',
        sa.Column('id',           sa.String(36),  primary_key=True),
        sa.Column('store_id',     sa.String(36),  nullable=False),
        sa.Column('brand_id',     sa.String(36),  nullable=True),
        # 事件分类
        sa.Column('event_type',   sa.String(32),  nullable=False),
        # 10种: sale / refund / purchase / receipt / waste /
        #        invoice / payment / collection / expense / settlement
        sa.Column('event_subtype', sa.String(64),  nullable=True),
        # 来源系统
        sa.Column('source_system', sa.String(32),  nullable=False, server_default='manual'),
        # pos / meituan / eleme / wechat_pay / erp / manual
        sa.Column('source_event_id', sa.String(128), nullable=True),  # 原系统单号
        # 金额（分，避免浮点精度问题）
        sa.Column('amount_fen',   sa.BigInteger,  nullable=False, server_default='0'),
        sa.Column('amount_yuan',  sa.Numeric(14, 2), nullable=False, server_default='0'),
        # 扩展字段 JSON（商品明细、成本项等）
        sa.Column('payload',      sa.Text,        nullable=True),
        # 会计维度
        sa.Column('period',       sa.String(7),   nullable=True),   # YYYY-MM
        sa.Column('event_date',   sa.Date,        nullable=False),
        # 处理状态
        sa.Column('status',       sa.String(16),  nullable=False, server_default='raw'),
        # raw → mapped → attributed → archived
        sa.Column('mapped_at',    sa.DateTime(timezone=True), nullable=True),
        sa.Column('attributed_at', sa.DateTime(timezone=True), nullable=True),
        # 标准字段
        sa.Column('created_at',   sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',   sa.DateTime(timezone=True), server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )
    op.create_index('ix_be_store_date',    'business_events', ['store_id', 'event_date'])
    op.create_index('ix_be_type_date',     'business_events', ['event_type', 'event_date'])
    op.create_index('ix_be_period',        'business_events', ['period'])
    op.create_index('ix_be_source',        'business_events', ['source_system', 'source_event_id'],
                    postgresql_where=sa.text("source_event_id IS NOT NULL"))

    # ── 事件映射规则 ──────────────────────────────────────────────────────
    op.create_table(
        'event_mapping_rules',
        sa.Column('id',             sa.String(36), primary_key=True),
        sa.Column('source_system',  sa.String(32), nullable=False),
        sa.Column('source_event_type', sa.String(64), nullable=False),
        sa.Column('target_event_type', sa.String(32), nullable=False),
        sa.Column('target_subtype', sa.String(64),  nullable=True),
        # 转换规则 JSON（字段映射、金额换算系数等）
        sa.Column('transform_rules', sa.Text,       nullable=True),
        sa.Column('is_active',       sa.Boolean,    nullable=False, server_default='true'),
        sa.Column('priority',        sa.Integer,    nullable=False, server_default='100'),
        sa.Column('created_at',      sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('source_system', 'source_event_type', name='uq_emr_source'),
    )
    op.create_index('ix_emr_source_system', 'event_mapping_rules', ['source_system'])

    # ── 税务规则配置 ──────────────────────────────────────────────────────
    op.create_table(
        'tax_rules',
        sa.Column('id',           sa.String(36), primary_key=True),
        sa.Column('brand_id',     sa.String(36), nullable=True),   # NULL = 全局规则
        sa.Column('store_id',     sa.String(36), nullable=True),   # NULL = 品牌通用
        # 税种
        sa.Column('tax_type',     sa.String(32), nullable=False),
        # vat_general / vat_small / income_tax / stamp_duty / other
        sa.Column('tax_name',     sa.String(64), nullable=False),
        sa.Column('tax_rate',     sa.Numeric(6, 4), nullable=False),  # e.g. 0.0600 = 6%
        # 适用条件 JSON（月营业额区间、行业分类等）
        sa.Column('apply_conditions', sa.Text,  nullable=True),
        sa.Column('effective_from', sa.Date,    nullable=False),
        sa.Column('effective_to',   sa.Date,    nullable=True),    # NULL = 长期有效
        sa.Column('is_active',      sa.Boolean, nullable=False, server_default='true'),
        sa.Column('notes',          sa.Text,    nullable=True),
        sa.Column('created_at',     sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_tr_brand_type',  'tax_rules', ['brand_id', 'tax_type'])
    op.create_index('ix_tr_store',       'tax_rules', ['store_id'])

    # ── 结算风控待办任务 ──────────────────────────────────────────────────
    op.create_table(
        'risk_tasks',
        sa.Column('id',           sa.String(36), primary_key=True),
        sa.Column('store_id',     sa.String(36), nullable=True),
        sa.Column('brand_id',     sa.String(36), nullable=True),
        # 风险类型
        sa.Column('risk_type',    sa.String(32), nullable=False),
        # cash_gap / invoice_mismatch / overdue_payment / unusual_refund / tax_deviation
        sa.Column('severity',     sa.String(8),  nullable=False, server_default='medium'),
        # low / medium / high / critical
        sa.Column('title',        sa.String(256), nullable=False),
        sa.Column('description',  sa.Text,        nullable=True),
        # 关联事件 JSON数组（business_event_ids）
        sa.Column('related_event_ids', sa.Text,   nullable=True),
        # 涉及金额
        sa.Column('amount_yuan',  sa.Numeric(14, 2), nullable=True),
        # 处理状态
        sa.Column('status',       sa.String(16),  nullable=False, server_default='open'),
        # open → in_progress → resolved / ignored
        sa.Column('assigned_to',  sa.String(64),  nullable=True),
        sa.Column('resolved_at',  sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_note', sa.Text,     nullable=True),
        sa.Column('due_date',     sa.Date,        nullable=True),
        sa.Column('created_at',   sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',   sa.DateTime(timezone=True), server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )
    op.create_index('ix_rt_store_status',  'risk_tasks', ['store_id', 'status'])
    op.create_index('ix_rt_severity',      'risk_tasks', ['severity', 'status'])
    op.create_index('ix_rt_risk_type',     'risk_tasks', ['risk_type'])

    # ── 利润归因结果缓存 ──────────────────────────────────────────────────
    op.create_table(
        'profit_attribution_results',
        sa.Column('id',           sa.String(36),  primary_key=True),
        sa.Column('store_id',     sa.String(36),  nullable=False),
        sa.Column('period',       sa.String(7),   nullable=False),  # YYYY-MM
        sa.Column('calc_date',    sa.Date,        nullable=False),
        # 收入端（元）
        sa.Column('gross_revenue_yuan',   sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('refund_yuan',          sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('net_revenue_yuan',     sa.Numeric(14, 2), nullable=False, server_default='0'),
        # 成本端（元）
        sa.Column('food_cost_yuan',       sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('waste_cost_yuan',      sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('platform_commission_yuan', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('labor_cost_yuan',      sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('other_expense_yuan',   sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('total_cost_yuan',      sa.Numeric(14, 2), nullable=False, server_default='0'),
        # 利润
        sa.Column('gross_profit_yuan',    sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('profit_margin_pct',    sa.Numeric(6, 2),  nullable=True),
        # 归因分析 JSON（各成本项占收入比、环比变化）
        sa.Column('attribution_detail',   sa.Text,           nullable=True),
        # 数据来源事件数
        sa.Column('event_count',          sa.Integer,        nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('store_id', 'period', 'calc_date',
                            name='uq_par_store_period_date'),
    )
    op.create_index('ix_par_store_period', 'profit_attribution_results', ['store_id', 'period'])


def downgrade() -> None:
    op.drop_table('profit_attribution_results')
    op.drop_table('risk_tasks')
    op.drop_table('tax_rules')
    op.drop_table('event_mapping_rules')
    op.drop_table('business_events')
