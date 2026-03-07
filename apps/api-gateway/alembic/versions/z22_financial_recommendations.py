"""z22 — 财务智能建议引擎

Phase 5 Month 10

Tables:
  financial_recommendations — 门店财务行动建议（来源于异常/排名/预测/预算信号）
    UNIQUE: store_id + period + rec_type + metric
    （同一期对同一指标的同类建议只保留最新版本，幂等 upsert）
"""

revision      = 'z22'
down_revision = 'z21'
branch_labels = None
depends_on    = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        'financial_recommendations',
        sa.Column('id',                  sa.Integer,      primary_key=True),
        sa.Column('store_id',            sa.String(64),   nullable=False),
        sa.Column('period',              sa.String(7),    nullable=False),   # YYYY-MM
        # 建议元数据
        sa.Column('rec_type',            sa.String(32),   nullable=False),
        # anomaly_severe / anomaly_moderate / ranking_laggard /
        # forecast_decline / forecast_surge / budget_overrun
        sa.Column('metric',              sa.String(32),   nullable=False),
        # revenue / food_cost_rate / profit_margin / health_score
        sa.Column('title',               sa.String(100),  nullable=False),   # ≤50 字短标题
        sa.Column('description',         sa.Text,         nullable=True),    # ≤200 字说明
        sa.Column('action',              sa.Text,         nullable=True),    # 建议动作（1句话）
        # 量化评估
        sa.Column('expected_yuan_impact',sa.Numeric(14, 2), nullable=True),  # 预期¥影响
        sa.Column('confidence_pct',      sa.Numeric(5, 1),  nullable=False, server_default='70.0'),
        sa.Column('urgency',             sa.String(8),    nullable=False, server_default='medium'),
        # high / medium / low
        sa.Column('priority_score',      sa.Numeric(8, 2),  nullable=False, server_default='0.0'),
        # 来源追踪
        sa.Column('source_type',         sa.String(32),   nullable=True),
        # anomaly / ranking / forecast / budget
        sa.Column('source_ref',          sa.String(128),  nullable=True),
        # e.g. "anomaly:revenue:2024-07"
        # 状态
        sa.Column('status',              sa.String(16),   nullable=False, server_default='pending'),
        # pending / adopted / dismissed
        sa.Column('adopted_at',          sa.DateTime,     nullable=True),
        sa.Column('dismissed_at',        sa.DateTime,     nullable=True),
        sa.Column('created_at',          sa.DateTime,     server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at',          sa.DateTime,     server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_unique_constraint(
        'uq_rec_store_period_type_metric',
        'financial_recommendations',
        ['store_id', 'period', 'rec_type', 'metric'],
    )
    op.create_index('ix_rec_store_period',  'financial_recommendations', ['store_id', 'period'])
    op.create_index('ix_rec_pending',       'financial_recommendations', ['store_id', 'status'],
                    postgresql_where=sa.text("status = 'pending'"))


def downgrade() -> None:
    op.drop_index('ix_rec_pending',      table_name='financial_recommendations')
    op.drop_index('ix_rec_store_period', table_name='financial_recommendations')
    op.drop_constraint('uq_rec_store_period_type_metric', 'financial_recommendations', type_='unique')
    op.drop_table('financial_recommendations')
