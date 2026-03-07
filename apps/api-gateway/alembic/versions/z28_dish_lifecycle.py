"""z28 — 菜品生命周期管理引擎

Phase 6 Month 6

Table:
  dish_lifecycle_records — 每道菜每期所处生命阶段 + 趋势 + 行动建议
    UNIQUE: store_id + period + dish_id
    phase: launch / growth / peak / decline / exit
    phase_duration_months: 连续处于当前阶段的月数
    phase_changed: 本期是否发生阶段跃迁
"""

revision      = 'z28'
down_revision = 'z27'
branch_labels = None
depends_on    = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        'dish_lifecycle_records',
        sa.Column('id',           sa.Integer,      primary_key=True),
        sa.Column('store_id',     sa.String(64),   nullable=False),
        sa.Column('period',       sa.String(7),    nullable=False),   # YYYY-MM
        sa.Column('dish_id',      sa.String(128),  nullable=False),
        sa.Column('dish_name',    sa.String(128),  nullable=False),
        sa.Column('category',     sa.String(64),   nullable=True),
        # 当期快照
        sa.Column('bcg_quadrant',        sa.String(32),   nullable=True),
        sa.Column('order_count',         sa.Integer,      nullable=True),
        sa.Column('revenue_yuan',        sa.Numeric(14, 2), nullable=True),
        sa.Column('gross_profit_margin', sa.Numeric(6, 2),  nullable=True),
        sa.Column('food_cost_rate',      sa.Numeric(6, 2),  nullable=True),
        # 趋势（环比上期）
        sa.Column('revenue_trend_pct',   sa.Numeric(7, 2),  nullable=True),  # +/- %
        sa.Column('order_trend_pct',     sa.Numeric(7, 2),  nullable=True),
        sa.Column('fcr_trend_pp',        sa.Numeric(6, 2),  nullable=True),  # + bad
        # 生命阶段
        sa.Column('phase',               sa.String(16),   nullable=False),   # launch/growth/peak/decline/exit
        sa.Column('prev_phase',          sa.String(16),   nullable=True),
        sa.Column('phase_changed',       sa.Boolean,      nullable=False, server_default='false'),
        sa.Column('phase_duration_months', sa.Integer,    nullable=False, server_default='1'),
        # 行动建议
        sa.Column('recommended_action',  sa.String(32),   nullable=True),
        sa.Column('action_label',        sa.String(32),   nullable=True),
        sa.Column('action_description',  sa.String(200),  nullable=True),
        sa.Column('expected_impact_yuan', sa.Numeric(14, 2), nullable=True),
        sa.Column('confidence_pct',       sa.Numeric(5, 1),  nullable=True),
        # 时间
        sa.Column('computed_at', sa.DateTime, server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at',  sa.DateTime, server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_unique_constraint(
        'uq_dish_lifecycle_store_period_dish',
        'dish_lifecycle_records',
        ['store_id', 'period', 'dish_id'],
    )
    op.create_index('ix_dish_lifecycle_store_period',
                    'dish_lifecycle_records', ['store_id', 'period'])
    op.create_index('ix_dish_lifecycle_store_period_phase',
                    'dish_lifecycle_records', ['store_id', 'period', 'phase'])
    op.create_index('ix_dish_lifecycle_transitions',
                    'dish_lifecycle_records', ['store_id', 'period', 'phase_changed'])


def downgrade() -> None:
    op.drop_index('ix_dish_lifecycle_transitions',    table_name='dish_lifecycle_records')
    op.drop_index('ix_dish_lifecycle_store_period_phase', table_name='dish_lifecycle_records')
    op.drop_index('ix_dish_lifecycle_store_period',   table_name='dish_lifecycle_records')
    op.drop_constraint('uq_dish_lifecycle_store_period_dish',
                       'dish_lifecycle_records', type_='unique')
    op.drop_table('dish_lifecycle_records')
