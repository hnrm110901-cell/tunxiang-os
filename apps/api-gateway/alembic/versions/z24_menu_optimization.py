"""z24 — 菜单优化建议引擎

Phase 6 Month 2

Table:
  menu_optimization_records — 每道菜的优化建议（提价/降本/推广/下架/套餐捆绑）
    UNIQUE: store_id + period + dish_id + rec_type
    rec_type: price_increase / cost_reduction / promote / discontinue / bundle
"""

revision      = 'z24'
down_revision = 'z23'
branch_labels = None
depends_on    = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        'menu_optimization_records',
        sa.Column('id',          sa.Integer,     primary_key=True),
        sa.Column('store_id',    sa.String(64),  nullable=False),
        sa.Column('period',      sa.String(7),   nullable=False),   # YYYY-MM
        sa.Column('dish_id',     sa.String(64),  nullable=False),
        sa.Column('dish_name',   sa.String(128), nullable=False),
        sa.Column('category',    sa.String(64),  nullable=True),
        sa.Column('bcg_quadrant',sa.String(16),  nullable=True),
        # 建议类型与内容
        sa.Column('rec_type',    sa.String(32),  nullable=False),
        sa.Column('title',       sa.String(64),  nullable=False),
        sa.Column('description', sa.Text,        nullable=True),
        sa.Column('action',      sa.String(200), nullable=True),
        # ¥ 预期影响
        sa.Column('expected_revenue_impact_yuan', sa.Numeric(14, 2), nullable=True),
        sa.Column('expected_cost_impact_yuan',    sa.Numeric(14, 2), nullable=True),
        sa.Column('expected_profit_impact_yuan',  sa.Numeric(14, 2), nullable=True),
        sa.Column('confidence_pct',  sa.Numeric(5, 1), nullable=True),
        sa.Column('priority_score',  sa.Numeric(5, 1), nullable=True),
        sa.Column('urgency',         sa.String(16),    nullable=True),
        # 当期指标快照
        sa.Column('current_fcr',          sa.Numeric(6, 2),  nullable=True),   # 食材成本率 %
        sa.Column('current_gpm',          sa.Numeric(6, 2),  nullable=True),   # 毛利率 %
        sa.Column('current_order_count',  sa.Integer,        nullable=True),
        sa.Column('current_avg_price',    sa.Numeric(10, 2), nullable=True),
        sa.Column('current_revenue_yuan', sa.Numeric(14, 2), nullable=True),
        sa.Column('current_profit_yuan',  sa.Numeric(14, 2), nullable=True),
        # 状态
        sa.Column('status',       sa.String(16), nullable=False, server_default='pending'),
        sa.Column('adopted_at',   sa.DateTime,   nullable=True),
        sa.Column('dismissed_at', sa.DateTime,   nullable=True),
        sa.Column('computed_at',  sa.DateTime,   server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at',   sa.DateTime,   server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_unique_constraint(
        'uq_menu_opt_store_period_dish_type',
        'menu_optimization_records',
        ['store_id', 'period', 'dish_id', 'rec_type'],
    )
    op.create_index('ix_menu_opt_store_period', 'menu_optimization_records', ['store_id', 'period'])
    op.create_index('ix_menu_opt_status',       'menu_optimization_records', ['store_id', 'period', 'status'])
    op.create_index('ix_menu_opt_bcg',          'menu_optimization_records', ['store_id', 'period', 'bcg_quadrant'])


def downgrade() -> None:
    op.drop_index('ix_menu_opt_bcg',          table_name='menu_optimization_records')
    op.drop_index('ix_menu_opt_status',       table_name='menu_optimization_records')
    op.drop_index('ix_menu_opt_store_period', table_name='menu_optimization_records')
    op.drop_constraint('uq_menu_opt_store_period_dish_type', 'menu_optimization_records', type_='unique')
    op.drop_table('menu_optimization_records')
