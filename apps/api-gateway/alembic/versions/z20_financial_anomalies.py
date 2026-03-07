"""z20 — 财务异常检测引擎

Phase 5 Month 8

Tables:
  financial_anomaly_records — 门店级财务指标异常记录
    （UNIQUE: store_id + period + metric，事后可回填实际值和解决状态）
"""

revision      = 'z20'
down_revision = 'z19'
branch_labels = None
depends_on    = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        'financial_anomaly_records',
        sa.Column('id',             sa.Integer,      primary_key=True),
        sa.Column('store_id',       sa.String(64),   nullable=False),
        sa.Column('period',         sa.String(7),    nullable=False),   # YYYY-MM
        sa.Column('metric',         sa.String(32),   nullable=False),   # revenue/food_cost_rate/profit_margin/health_score
        # 检测值
        sa.Column('actual_value',   sa.Numeric(14, 4), nullable=True),
        sa.Column('expected_value', sa.Numeric(14, 4), nullable=True),  # 历史均值 或 预测值
        sa.Column('deviation_pct',  sa.Numeric(8, 2),  nullable=True),  # (actual-expected)/|expected|*100
        sa.Column('z_score',        sa.Numeric(6, 3),  nullable=True),  # 标准化偏差
        # 判断结果
        sa.Column('is_anomaly',     sa.Boolean,      nullable=False, server_default='false'),
        sa.Column('severity',       sa.String(16),   nullable=False, server_default='normal'),  # normal/mild/moderate/severe
        sa.Column('detection_method', sa.String(32), nullable=False, server_default='z_score'),  # z_score/forecast_deviation/iqr
        sa.Column('description',    sa.Text,         nullable=True),    # 中文描述
        sa.Column('yuan_impact',    sa.Numeric(14, 2), nullable=True),  # ¥影响（收入维度有意义）
        # 状态
        sa.Column('resolved',       sa.Boolean,      nullable=False, server_default='false'),
        sa.Column('resolved_at',    sa.DateTime,     nullable=True),
        sa.Column('detected_at',    sa.DateTime,     server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at',     sa.DateTime,     server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_unique_constraint(
        'uq_anomaly_store_period_metric',
        'financial_anomaly_records',
        ['store_id', 'period', 'metric'],
    )
    op.create_index('ix_anomaly_store_period',   'financial_anomaly_records', ['store_id', 'period'])
    op.create_index('ix_anomaly_unresolved',     'financial_anomaly_records', ['store_id', 'is_anomaly', 'resolved'],
                    postgresql_where=sa.text("is_anomaly = true AND resolved = false"))


def downgrade() -> None:
    op.drop_index('ix_anomaly_unresolved',   table_name='financial_anomaly_records')
    op.drop_index('ix_anomaly_store_period', table_name='financial_anomaly_records')
    op.drop_constraint('uq_anomaly_store_period_metric', 'financial_anomaly_records', type_='unique')
    op.drop_table('financial_anomaly_records')
