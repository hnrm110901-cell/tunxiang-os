"""z08 revenue sharing

Revision ID: z08
Revises: z07
Create Date: 2026-03-07
"""
from alembic import op

revision = 'z08'
down_revision = 'z07'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE revenue_share_records (
            id               VARCHAR(40)  PRIMARY KEY,
            developer_id     VARCHAR(40)  NOT NULL REFERENCES isv_developers(id),
            period           VARCHAR(7)   NOT NULL,
            installed_plugins INTEGER     NOT NULL DEFAULT 0,
            gross_revenue_fen INTEGER     NOT NULL DEFAULT 0,
            share_pct        FLOAT        NOT NULL DEFAULT 0,
            net_payout_fen   INTEGER      NOT NULL DEFAULT 0,
            status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            settled_at       TIMESTAMPTZ,
            UNIQUE(developer_id, period)
        )
    """)
    op.execute("CREATE INDEX ix_rsr_period    ON revenue_share_records(period)")
    op.execute("CREATE INDEX ix_rsr_status    ON revenue_share_records(status)")
    op.execute("CREATE INDEX ix_rsr_developer ON revenue_share_records(developer_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS revenue_share_records")
