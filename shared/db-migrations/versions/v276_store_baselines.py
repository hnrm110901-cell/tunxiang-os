"""v276 — store_baselines（Phase S3: AI运营教练 — 门店基线）

新建表：
  - store_baselines: 门店基线数据（异常检测基准，按指标/星期/时段维度）

Revision ID: v276_store_baselines
Revises: v275_coaching_logs
Create Date: 2026-04-23
"""
from alembic import op

revision = "v276_store_baselines"
down_revision = "v275_coaching_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── store_baselines ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS store_baselines (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID NOT NULL,
            metric_code         TEXT NOT NULL,
            day_of_week         INT,
            slot_code           TEXT,
            baseline_value      FLOAT NOT NULL,
            std_deviation       FLOAT NOT NULL,
            sample_count        INT NOT NULL DEFAULT 0,
            min_value           FLOAT,
            max_value           FLOAT,
            last_updated        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN DEFAULT FALSE
        )
    """)

    # 索引：(store_id, metric_code) — 按门店+指标查询基线
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_baselines_store_metric
            ON store_baselines (store_id, metric_code)
    """)

    # 唯一约束（软删除友好）：同一门店+指标+星期+时段只允许一条有效基线
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_store_baselines_natural_key
            ON store_baselines (tenant_id, store_id, metric_code,
                                COALESCE(day_of_week, -1),
                                COALESCE(slot_code, '__all__'))
            WHERE NOT is_deleted
    """)

    # RLS
    op.execute("ALTER TABLE store_baselines ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS store_baselines_tenant ON store_baselines"
    )
    op.execute("""
        CREATE POLICY store_baselines_tenant ON store_baselines
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE store_baselines IS
            'Phase S3: 门店基线 — 各指标的历史均值和标准差，用于异常检测';
        COMMENT ON COLUMN store_baselines.metric_code IS
            '指标代码：lunch_covers / dinner_covers / food_cost_rate / labor_cost_rate / '
            'avg_ticket_fen / table_turnover / serve_time_min / waste_rate / '
            'takeout_count / customer_complaints';
        COMMENT ON COLUMN store_baselines.day_of_week IS
            '星期几(0=周一..6=周日)，NULL表示不区分';
        COMMENT ON COLUMN store_baselines.slot_code IS
            '时段代码，NULL表示全天';
        COMMENT ON COLUMN store_baselines.baseline_value IS
            '基线值（历史均值）';
        COMMENT ON COLUMN store_baselines.std_deviation IS
            '标准差（用于异常检测阈值：>2σ=warning, >3σ=critical）';
        COMMENT ON COLUMN store_baselines.sample_count IS
            '样本数量（用于增量更新权重计算）';
    """)


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS store_baselines_tenant ON store_baselines"
    )
    op.execute(
        "ALTER TABLE IF EXISTS store_baselines DISABLE ROW LEVEL SECURITY"
    )
    op.execute("DROP INDEX IF EXISTS uq_store_baselines_natural_key")
    op.execute("DROP INDEX IF EXISTS idx_store_baselines_store_metric")
    op.execute("DROP TABLE IF EXISTS store_baselines")
