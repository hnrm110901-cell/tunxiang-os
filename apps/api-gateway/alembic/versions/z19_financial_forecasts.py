"""z19 — 智能财务预测引擎

Phase 5 Month 7

Tables:
  financial_forecasts — 门店级月度财务预测结果（4个预测类型，唯一约束 store+period+type）
"""

revision      = 'z19'
down_revision = 'z18'
branch_labels = None
depends_on    = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        'financial_forecasts',
        sa.Column('id',               sa.Integer,      primary_key=True),
        sa.Column('store_id',         sa.String(64),   nullable=False),
        sa.Column('target_period',    sa.String(7),    nullable=False),   # 被预测的月份 YYYY-MM
        sa.Column('forecast_type',    sa.String(32),   nullable=False),   # revenue/food_cost_rate/health_score/profit_margin
        sa.Column('predicted_value',  sa.Numeric(14, 4), nullable=True),
        sa.Column('lower_bound',      sa.Numeric(14, 4), nullable=True),
        sa.Column('upper_bound',      sa.Numeric(14, 4), nullable=True),
        sa.Column('confidence_pct',   sa.Numeric(5, 2),  nullable=True, server_default='95.0'),
        sa.Column('method',           sa.String(32),   nullable=False, server_default='weighted_moving_avg'),
        sa.Column('based_on_periods', sa.Integer,      nullable=True),    # 使用了几期历史数据
        # 事后验证字段（实际值出来后填充）
        sa.Column('actual_value',     sa.Numeric(14, 4), nullable=True),
        sa.Column('accuracy_pct',     sa.Numeric(5, 2),  nullable=True),
        sa.Column('computed_at',      sa.DateTime,     server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at',       sa.DateTime,     server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_unique_constraint(
        'uq_forecast_store_period_type',
        'financial_forecasts',
        ['store_id', 'target_period', 'forecast_type'],
    )
    op.create_index('ix_forecasts_store_period', 'financial_forecasts', ['store_id', 'target_period'])


def downgrade() -> None:
    op.drop_index('ix_forecasts_store_period', table_name='financial_forecasts')
    op.drop_constraint('uq_forecast_store_period_type', 'financial_forecasts', type_='unique')
    op.drop_table('financial_forecasts')
