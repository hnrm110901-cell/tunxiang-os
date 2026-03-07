"""z29 — 菜品销售预测引擎

Phase 6 Month 7

Table:
  dish_forecast_records — 下期菜品销量/营收预测 + 置信区间
    UNIQUE: store_id + forecast_period + dish_id
    forecast_period: 被预测的目标期（YYYY-MM）
    base_period:     预测所依据的最近完整期（YYYY-MM）
"""

revision      = 'z29'
down_revision = 'z28'
branch_labels = None
depends_on    = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        'dish_forecast_records',
        sa.Column('id',              sa.Integer,      primary_key=True),
        sa.Column('store_id',        sa.String(64),   nullable=False),
        sa.Column('forecast_period', sa.String(7),    nullable=False),  # 预测目标期
        sa.Column('base_period',     sa.String(7),    nullable=False),  # 预测所依据的最近期
        sa.Column('dish_id',         sa.String(128),  nullable=False),
        sa.Column('dish_name',       sa.String(128),  nullable=False),
        sa.Column('category',        sa.String(64),   nullable=True),
        sa.Column('lifecycle_phase', sa.String(16),   nullable=True),   # 预测时的生命阶段
        # 历史统计基础
        sa.Column('periods_used',         sa.Integer,        nullable=False),
        sa.Column('hist_avg_orders',      sa.Numeric(10, 1), nullable=True),
        sa.Column('hist_avg_revenue',     sa.Numeric(14, 2), nullable=True),
        sa.Column('trend_orders_pct',     sa.Numeric(7, 2),  nullable=True),  # 趋势斜率 %/期
        sa.Column('trend_revenue_pct',    sa.Numeric(7, 2),  nullable=True),
        sa.Column('lifecycle_adj_pct',    sa.Numeric(6, 2),  nullable=True),  # 阶段调整量 %
        # 预测值（点估计 + 置信区间）
        sa.Column('predicted_order_count',  sa.Numeric(10, 1), nullable=True),
        sa.Column('predicted_order_low',    sa.Numeric(10, 1), nullable=True),
        sa.Column('predicted_order_high',   sa.Numeric(10, 1), nullable=True),
        sa.Column('predicted_revenue_yuan', sa.Numeric(14, 2), nullable=True),
        sa.Column('predicted_revenue_low',  sa.Numeric(14, 2), nullable=True),
        sa.Column('predicted_revenue_high', sa.Numeric(14, 2), nullable=True),
        sa.Column('predicted_fcr',          sa.Numeric(6, 2),  nullable=True),
        sa.Column('predicted_gpm',          sa.Numeric(6, 2),  nullable=True),
        # 时间
        sa.Column('computed_at', sa.DateTime, server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at',  sa.DateTime, server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_unique_constraint(
        'uq_dish_forecast_store_period_dish',
        'dish_forecast_records',
        ['store_id', 'forecast_period', 'dish_id'],
    )
    op.create_index('ix_dish_forecast_store_period',
                    'dish_forecast_records', ['store_id', 'forecast_period'])
    op.create_index('ix_dish_forecast_store_period_phase',
                    'dish_forecast_records', ['store_id', 'forecast_period', 'lifecycle_phase'])


def downgrade() -> None:
    op.drop_index('ix_dish_forecast_store_period_phase',
                  table_name='dish_forecast_records')
    op.drop_index('ix_dish_forecast_store_period',
                  table_name='dish_forecast_records')
    op.drop_constraint('uq_dish_forecast_store_period_dish',
                       'dish_forecast_records', type_='unique')
    op.drop_table('dish_forecast_records')
