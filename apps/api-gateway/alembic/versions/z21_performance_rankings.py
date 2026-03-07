"""z21 — 多店财务对标排名引擎

Phase 5 Month 9

Tables:
  store_performance_rankings — 门店逐月财务指标排名与百分位
    （UNIQUE: store_id + period + metric）

  store_benchmark_gaps — 门店与基准值（中位数/头部四分位/最优）的差距
    （UNIQUE: store_id + period + metric + benchmark_type）
"""

revision      = 'z21'
down_revision = 'z20'
branch_labels = None
depends_on    = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # ── 排名表 ──────────────────────────────────────────────────────────────
    op.create_table(
        'store_performance_rankings',
        sa.Column('id',            sa.Integer,      primary_key=True),
        sa.Column('store_id',      sa.String(64),   nullable=False),
        sa.Column('period',        sa.String(7),    nullable=False),   # YYYY-MM
        sa.Column('metric',        sa.String(32),   nullable=False),   # revenue/food_cost_rate/profit_margin/health_score
        sa.Column('value',         sa.Numeric(14, 4), nullable=True),
        sa.Column('rank',          sa.Integer,      nullable=False),   # 1-based，1 = best
        sa.Column('total_stores',  sa.Integer,      nullable=False),
        sa.Column('percentile',    sa.Numeric(5, 1), nullable=False),  # 0-100
        sa.Column('tier',          sa.String(16),   nullable=False, server_default='below_avg'),
        # top / above_avg / below_avg / laggard
        sa.Column('prev_rank',     sa.Integer,      nullable=True),
        sa.Column('rank_change',   sa.String(16),   nullable=True),    # improved/declined/stable/new
        sa.Column('computed_at',   sa.DateTime,     server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at',    sa.DateTime,     server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_unique_constraint(
        'uq_ranking_store_period_metric',
        'store_performance_rankings',
        ['store_id', 'period', 'metric'],
    )
    op.create_index('ix_ranking_period_metric', 'store_performance_rankings', ['period', 'metric'])
    op.create_index('ix_ranking_store',         'store_performance_rankings', ['store_id'])

    # ── 对标差距表 ───────────────────────────────────────────────────────────
    op.create_table(
        'store_benchmark_gaps',
        sa.Column('id',              sa.Integer,      primary_key=True),
        sa.Column('store_id',        sa.String(64),   nullable=False),
        sa.Column('period',          sa.String(7),    nullable=False),
        sa.Column('metric',          sa.String(32),   nullable=False),
        sa.Column('benchmark_type',  sa.String(16),   nullable=False),  # median/top_quartile/best
        sa.Column('store_value',     sa.Numeric(14, 4), nullable=True),
        sa.Column('benchmark_value', sa.Numeric(14, 4), nullable=True),
        sa.Column('gap_pct',         sa.Numeric(8, 2),  nullable=True),  # (store - benchmark) / |benchmark| * 100
        sa.Column('gap_direction',   sa.String(8),    nullable=True),    # above/below/equal
        sa.Column('yuan_potential',  sa.Numeric(14, 2), nullable=True),  # ¥潜力（如达到基准可省/赚多少）
        sa.Column('computed_at',     sa.DateTime,     server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_unique_constraint(
        'uq_gap_store_period_metric_benchmark',
        'store_benchmark_gaps',
        ['store_id', 'period', 'metric', 'benchmark_type'],
    )
    op.create_index('ix_gap_store_period', 'store_benchmark_gaps', ['store_id', 'period'])


def downgrade() -> None:
    op.drop_index('ix_gap_store_period',     table_name='store_benchmark_gaps')
    op.drop_constraint('uq_gap_store_period_metric_benchmark', 'store_benchmark_gaps', type_='unique')
    op.drop_table('store_benchmark_gaps')

    op.drop_index('ix_ranking_store',         table_name='store_performance_rankings')
    op.drop_index('ix_ranking_period_metric', table_name='store_performance_rankings')
    op.drop_constraint('uq_ranking_store_period_metric', 'store_performance_rankings', type_='unique')
    op.drop_table('store_performance_rankings')
