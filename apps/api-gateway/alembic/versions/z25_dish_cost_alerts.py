"""z25 — 菜品成本预警引擎

Phase 6 Month 3

Table:
  dish_cost_alerts — 菜品成本/毛利/BCG象限环比异动告警
    UNIQUE: store_id + period + dish_id + alert_type
    alert_type: fcr_spike / margin_drop / bcg_downgrade
    severity:   critical / warning / info
"""

revision      = 'z25'
down_revision = 'z24'
branch_labels = None
depends_on    = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        'dish_cost_alerts',
        sa.Column('id',       sa.Integer,    primary_key=True),
        sa.Column('store_id', sa.String(64), nullable=False),
        sa.Column('period',   sa.String(7),  nullable=False),   # YYYY-MM (当期)
        sa.Column('dish_id',  sa.String(64), nullable=False),
        sa.Column('dish_name',sa.String(128),nullable=False),
        sa.Column('category', sa.String(64), nullable=True),
        # BCG 状态（当期 vs 上期）
        sa.Column('bcg_quadrant',      sa.String(16), nullable=True),
        sa.Column('prev_bcg_quadrant', sa.String(16), nullable=True),
        # 告警类型与严重度
        sa.Column('alert_type', sa.String(32), nullable=False),
        # fcr_spike / margin_drop / bcg_downgrade
        sa.Column('severity',   sa.String(16), nullable=False),
        # critical / warning / info
        # 量化数据
        sa.Column('current_value',     sa.Numeric(8, 2), nullable=True),  # 当期指标值
        sa.Column('prev_value',        sa.Numeric(8, 2), nullable=True),  # 上期指标值
        sa.Column('change_pp',         sa.Numeric(8, 2), nullable=True),  # 变化量（百分点）
        sa.Column('yuan_impact_yuan',  sa.Numeric(14, 2), nullable=True), # ¥影响估算
        sa.Column('message',           sa.Text, nullable=True),           # 告警描述 ≤150字
        # 状态
        sa.Column('status',      sa.String(16), nullable=False, server_default='open'),
        # open / resolved / suppressed
        sa.Column('resolved_at', sa.DateTime, nullable=True),
        sa.Column('computed_at', sa.DateTime, server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at',  sa.DateTime, server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_unique_constraint(
        'uq_dish_alert_store_period_dish_type',
        'dish_cost_alerts',
        ['store_id', 'period', 'dish_id', 'alert_type'],
    )
    op.create_index('ix_dish_alert_store_period',
                    'dish_cost_alerts', ['store_id', 'period'])
    op.create_index('ix_dish_alert_severity',
                    'dish_cost_alerts', ['store_id', 'period', 'severity'])
    op.create_index('ix_dish_alert_status',
                    'dish_cost_alerts', ['store_id', 'period', 'status'])


def downgrade() -> None:
    op.drop_index('ix_dish_alert_status',       table_name='dish_cost_alerts')
    op.drop_index('ix_dish_alert_severity',     table_name='dish_cost_alerts')
    op.drop_index('ix_dish_alert_store_period', table_name='dish_cost_alerts')
    op.drop_constraint('uq_dish_alert_store_period_dish_type',
                       'dish_cost_alerts', type_='unique')
    op.drop_table('dish_cost_alerts')
