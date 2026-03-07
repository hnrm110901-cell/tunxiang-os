"""z09 api usage logs and plugin ratings

Revision ID: z09
Revises: z08
Create Date: 2026-03-07
"""
from alembic import op

revision = 'z09'
down_revision = 'z08'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE api_usage_logs (
            id               VARCHAR(40)   PRIMARY KEY,
            developer_id     VARCHAR(40)   NOT NULL,
            api_key          VARCHAR(120),
            endpoint         VARCHAR(200)  NOT NULL,
            capability_level INTEGER       NOT NULL DEFAULT 1,
            is_billable      BOOLEAN       NOT NULL DEFAULT false,
            response_ms      INTEGER,
            called_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_aul_developer ON api_usage_logs(developer_id)")
    op.execute("CREATE INDEX ix_aul_called_at  ON api_usage_logs(called_at)")
    op.execute("CREATE INDEX ix_aul_billable   ON api_usage_logs(is_billable) WHERE is_billable = true")

    op.execute("""
        CREATE TABLE plugin_ratings (
            id         VARCHAR(40)   PRIMARY KEY,
            plugin_id  VARCHAR(40)   NOT NULL REFERENCES marketplace_plugins(id),
            store_id   VARCHAR(100)  NOT NULL,
            rating     INTEGER       NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment    VARCHAR(500),
            created_at TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            UNIQUE(plugin_id, store_id)
        )
    """)
    op.execute("CREATE INDEX ix_pr_plugin ON plugin_ratings(plugin_id)")
    op.execute("CREATE INDEX ix_pr_store  ON plugin_ratings(store_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS plugin_ratings")
    op.execute("DROP TABLE IF EXISTS api_usage_logs")
