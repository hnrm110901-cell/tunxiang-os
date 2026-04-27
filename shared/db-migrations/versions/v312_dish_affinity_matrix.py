"""v312 — 菜品亲和矩阵表: dish_affinity_matrix

基于订单明细共现分析，记录菜品对之间的关联强度：
co_occurrence_count(共现次数)、affinity_score(归一化亲和分0-1)、period(统计周期)。
用于AI智能推荐、加购提示、套餐组合建议。

Revision ID: v312_dish_affinity_matrix
Revises: v311_challenge_progress
Create Date: 2026-04-25
"""
from alembic import op

revision = "v312_dish_affinity_matrix"
down_revision = "v311_challenge_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS dish_affinity_matrix (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID NOT NULL,
            dish_a_id           UUID NOT NULL,
            dish_b_id           UUID NOT NULL,
            co_occurrence_count INT NOT NULL DEFAULT 0,
            affinity_score      FLOAT NOT NULL DEFAULT 0.0,
            period              VARCHAR(20) NOT NULL DEFAULT 'last_30d'
                                CHECK (period IN (
                                    'last_7d', 'last_30d', 'last_90d', 'all_time'
                                )),
            sample_order_count  INT NOT NULL DEFAULT 0,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_affinity_pair
                UNIQUE (tenant_id, store_id, dish_a_id, dish_b_id, period)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_affinity_matrix_dish_a
            ON dish_affinity_matrix(tenant_id, store_id, dish_a_id, affinity_score DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_affinity_matrix_dish_b
            ON dish_affinity_matrix(tenant_id, store_id, dish_b_id, affinity_score DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_affinity_matrix_period
            ON dish_affinity_matrix(tenant_id, store_id, period)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE dish_affinity_matrix ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS dish_affinity_matrix_tenant_isolation ON dish_affinity_matrix;
        CREATE POLICY dish_affinity_matrix_tenant_isolation ON dish_affinity_matrix
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE dish_affinity_matrix FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dish_affinity_matrix CASCADE")
