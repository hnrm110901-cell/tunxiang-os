"""z18 — CFO工作台·财务报告快照

Phase 5 Month 6

Tables:
  financial_report_snapshots — 品牌级月度CFO报告快照（可持久化，唯一约束 brand_id+period+type）
"""

revision      = 'z18'
down_revision = 'z17'
branch_labels = None
depends_on    = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def upgrade() -> None:
    op.create_table(
        'financial_report_snapshots',
        sa.Column('id',                    sa.Integer,      primary_key=True),
        sa.Column('brand_id',              sa.String(64),   nullable=False),
        sa.Column('period',                sa.String(7),    nullable=False),   # '2026-03'
        sa.Column('report_type',           sa.String(32),   nullable=False, server_default='cfo_monthly'),
        sa.Column('narrative',             sa.Text,         nullable=True),
        sa.Column('store_count',           sa.Integer,      nullable=True),
        sa.Column('avg_health_score',      sa.Numeric(5, 2), nullable=True),
        sa.Column('brand_grade',           sa.String(1),    nullable=True),
        sa.Column('open_alerts_count',     sa.Integer,      nullable=True),
        sa.Column('critical_alerts_count', sa.Integer,      nullable=True),
        sa.Column('budget_achievement_pct',sa.Numeric(5, 2), nullable=True),
        sa.Column('content_json',          JSONB,           nullable=True),
        sa.Column('generated_at',          sa.DateTime,     server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at',            sa.DateTime,     server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_unique_constraint(
        'uq_report_snapshot_brand_period_type',
        'financial_report_snapshots',
        ['brand_id', 'period', 'report_type'],
    )
    op.create_index('ix_report_snapshots_brand_period', 'financial_report_snapshots', ['brand_id', 'period'])


def downgrade() -> None:
    op.drop_index('ix_report_snapshots_brand_period', table_name='financial_report_snapshots')
    op.drop_constraint('uq_report_snapshot_brand_period_type', 'financial_report_snapshots', type_='unique')
    op.drop_table('financial_report_snapshots')
