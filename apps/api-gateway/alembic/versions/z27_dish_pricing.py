"""z27 — 菜品智能定价引擎

Phase 6 Month 5

Table:
  dish_pricing_records — 基于BCG/弹性/对标数据生成每道菜的定价建议
    UNIQUE: store_id + period + dish_id
    rec_action: increase / decrease / maintain
    elasticity_class: inelastic / moderate / elastic
    status: pending / adopted / dismissed
"""

revision      = 'z27'
down_revision = 'z26'
branch_labels = None
depends_on    = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        'dish_pricing_records',
        sa.Column('id',          sa.Integer,      primary_key=True),
        sa.Column('store_id',    sa.String(64),   nullable=False),
        sa.Column('period',      sa.String(7),    nullable=False),   # YYYY-MM
        sa.Column('dish_id',     sa.String(128),  nullable=False),
        sa.Column('dish_name',   sa.String(128),  nullable=False),
        sa.Column('category',    sa.String(64),   nullable=True),
        sa.Column('bcg_quadrant', sa.String(32),  nullable=True),
        # 当期快照
        sa.Column('current_price',        sa.Numeric(10, 2), nullable=True),
        sa.Column('order_count',          sa.Integer,        nullable=True),
        sa.Column('revenue_yuan',         sa.Numeric(14, 2), nullable=True),
        sa.Column('gross_profit_margin',  sa.Numeric(6, 2),  nullable=True),
        sa.Column('food_cost_rate',       sa.Numeric(6, 2),  nullable=True),
        # 定价建议
        sa.Column('rec_action',           sa.String(16),     nullable=False),  # increase/decrease/maintain
        sa.Column('suggested_price',      sa.Numeric(10, 2), nullable=True),
        sa.Column('price_change_pct',     sa.Numeric(6, 2),  nullable=True),   # +8.0 / -8.0
        sa.Column('elasticity_class',     sa.String(16),     nullable=True),   # inelastic/moderate/elastic
        sa.Column('expected_order_count', sa.Numeric(10, 1), nullable=True),
        sa.Column('expected_revenue_delta_yuan', sa.Numeric(14, 2), nullable=True),
        sa.Column('expected_profit_delta_yuan',  sa.Numeric(14, 2), nullable=True),
        sa.Column('confidence_pct',       sa.Numeric(5, 1),  nullable=True),
        sa.Column('reasoning',            sa.String(200),    nullable=True),
        # 执行跟踪
        sa.Column('status',               sa.String(16),     nullable=False, server_default='pending'),
        sa.Column('adopted_price',        sa.Numeric(10, 2), nullable=True),
        sa.Column('adopted_at',           sa.DateTime,       nullable=True),
        sa.Column('dismissed_at',         sa.DateTime,       nullable=True),
        # 时间
        sa.Column('computed_at', sa.DateTime, server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at',  sa.DateTime, server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_unique_constraint(
        'uq_dish_pricing_store_period_dish',
        'dish_pricing_records',
        ['store_id', 'period', 'dish_id'],
    )
    op.create_index('ix_dish_pricing_store_period',
                    'dish_pricing_records', ['store_id', 'period'])
    op.create_index('ix_dish_pricing_store_period_action',
                    'dish_pricing_records', ['store_id', 'period', 'rec_action'])
    op.create_index('ix_dish_pricing_store_period_status',
                    'dish_pricing_records', ['store_id', 'period', 'status'])


def downgrade() -> None:
    op.drop_index('ix_dish_pricing_store_period_status',
                  table_name='dish_pricing_records')
    op.drop_index('ix_dish_pricing_store_period_action',
                  table_name='dish_pricing_records')
    op.drop_index('ix_dish_pricing_store_period',
                  table_name='dish_pricing_records')
    op.drop_constraint('uq_dish_pricing_store_period_dish',
                       'dish_pricing_records', type_='unique')
    op.drop_table('dish_pricing_records')
