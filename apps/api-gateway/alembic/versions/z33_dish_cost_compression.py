"""z33 — 菜品成本压缩机会引擎

Phase 6 Month 11

Table:
  dish_cost_compression — 逐道菜的 FCR 超标缺口与压缩机会量化
    fcr_gap             : current_fcr - target_fcr（正值 = 超标 = 有压缩机会）
    compression_opportunity_yuan : revenue × fcr_gap / 100（可节省 ¥）
    fcr_trend           : improving / stable / worsening
    compression_action  : renegotiate / reformulate / adjust_portion / monitor
    action_priority     : high / medium / low
    expected_saving_yuan: 年化预期节省额（12×单期压缩机会）
    UNIQUE: store_id + period + dish_id
"""

revision      = 'z33'
down_revision = 'z32'
branch_labels = None
depends_on    = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        'dish_cost_compression',
        sa.Column('id',          sa.Integer,    primary_key=True),
        sa.Column('store_id',    sa.String(64), nullable=False),
        sa.Column('period',      sa.String(7),  nullable=False),
        sa.Column('dish_id',     sa.String(128), nullable=False),
        sa.Column('dish_name',   sa.String(128), nullable=False),
        sa.Column('category',    sa.String(64),  nullable=True),
        # 当期盈利数据
        sa.Column('revenue_yuan',   sa.Numeric(14, 2), nullable=False),
        sa.Column('order_count',    sa.Integer,        nullable=False),
        sa.Column('current_fcr',    sa.Numeric(6, 2),  nullable=False),
        sa.Column('current_gpm',    sa.Numeric(6, 2),  nullable=True),
        # 目标成本率
        sa.Column('target_fcr',     sa.Numeric(6, 2),  nullable=False),
        sa.Column('store_avg_fcr',  sa.Numeric(6, 2),  nullable=True),
        # 缺口与机会
        sa.Column('fcr_gap',        sa.Numeric(6, 2),  nullable=False),  # >0 超标
        sa.Column('compression_opportunity_yuan', sa.Numeric(14, 2), nullable=False),
        sa.Column('expected_saving_yuan',         sa.Numeric(14, 2), nullable=True),
        # 趋势
        sa.Column('prev_fcr',    sa.Numeric(6, 2), nullable=True),
        sa.Column('fcr_trend',   sa.String(12),    nullable=False),  # improving/stable/worsening
        # 行动
        sa.Column('compression_action', sa.String(20), nullable=False),
        sa.Column('action_priority',    sa.String(8),  nullable=False),
        # 时间
        sa.Column('computed_at', sa.DateTime, server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at',  sa.DateTime, server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_unique_constraint(
        'uq_dish_cost_compression_store_period_dish',
        'dish_cost_compression',
        ['store_id', 'period', 'dish_id'],
    )
    op.create_index('ix_dcc_store_period',
                    'dish_cost_compression', ['store_id', 'period'])
    op.create_index('ix_dcc_store_period_action',
                    'dish_cost_compression', ['store_id', 'period', 'compression_action'])
    op.create_index('ix_dcc_store_period_priority',
                    'dish_cost_compression', ['store_id', 'period', 'action_priority'])


def downgrade() -> None:
    op.drop_index('ix_dcc_store_period_priority',  table_name='dish_cost_compression')
    op.drop_index('ix_dcc_store_period_action',    table_name='dish_cost_compression')
    op.drop_index('ix_dcc_store_period',           table_name='dish_cost_compression')
    op.drop_constraint('uq_dish_cost_compression_store_period_dish',
                       'dish_cost_compression', type_='unique')
    op.drop_table('dish_cost_compression')
