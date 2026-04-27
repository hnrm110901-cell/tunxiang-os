"""v266 — 销售目标与进度追踪

对应规划：docs/reservation-roadmap-2026-q2.md §6 Sprint R1
依据路线图任务：
  销售目标表 + API
  年 / 月 / 周 / 员工销售目标（金额 / 单数 / 桌数 / 单均 / 人均 / 新客）

本迁移只建表，不含业务路由。sales_coach Agent 在 Sprint R2 接入。

表清单：
  sales_targets   — 目标设定
  sales_progress  — 进度快照

金额单位：分（fen，整数，对齐 CLAUDE.md §15）
RLS：tenant_id = app.tenant_id（对齐 CLAUDE.md §14）
事件：SalesTargetEventType.SET / PROGRESS_UPDATED

Revision: v266
Revises: v265
Create Date: 2026-04-23
"""

from alembic import op

revision = "v266"
down_revision = "v265"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. 枚举类型
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE sales_period_type_enum AS ENUM (
                'year',
                'month',
                'week',
                'day'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE sales_metric_type_enum AS ENUM (
                'revenue_fen',
                'order_count',
                'table_count',
                'unit_avg_fen',
                'per_guest_avg_fen',
                'new_customer_count'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 2. sales_targets — 目标设定
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sales_targets (
            target_id      UUID                      NOT NULL DEFAULT gen_random_uuid(),
            tenant_id      UUID                      NOT NULL,
            store_id       UUID,
            employee_id    UUID                      NOT NULL,
            period_type    sales_period_type_enum    NOT NULL,
            period_start   DATE                      NOT NULL,
            period_end     DATE                      NOT NULL,
            metric_type    sales_metric_type_enum    NOT NULL,
            target_value   BIGINT                    NOT NULL,
            parent_target_id UUID,
            notes          VARCHAR(500),
            created_by     UUID,
            created_at     TIMESTAMPTZ               NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ               NOT NULL DEFAULT NOW(),
            CONSTRAINT sales_targets_pkey PRIMARY KEY (target_id),
            CONSTRAINT sales_targets_period_chk CHECK (period_end >= period_start),
            CONSTRAINT sales_targets_value_chk CHECK (target_value >= 0)
        )
        """
    )

    # 唯一约束：同一员工在同一周期类型 + 同一指标 + 同一起点不能重复设目标
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_targets_employee_period_metric
            ON sales_targets (tenant_id, employee_id, period_type, period_start, metric_type)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sales_targets_employee
            ON sales_targets (tenant_id, employee_id, period_start DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sales_targets_store_period
            ON sales_targets (tenant_id, store_id, period_type, period_start DESC)
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 3. sales_progress — 进度快照（定时/事件触发写入）
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sales_progress (
            progress_id       UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id         UUID            NOT NULL,
            target_id         UUID            NOT NULL,
            actual_value      BIGINT          NOT NULL DEFAULT 0,
            achievement_rate  NUMERIC(5, 4)   NOT NULL DEFAULT 0,
            snapshot_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            source_event_id   UUID,
            created_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            CONSTRAINT sales_progress_pkey PRIMARY KEY (progress_id),
            CONSTRAINT sales_progress_target_fk
                FOREIGN KEY (target_id)
                REFERENCES sales_targets (target_id)
                ON DELETE CASCADE,
            CONSTRAINT sales_progress_actual_chk CHECK (actual_value >= 0),
            CONSTRAINT sales_progress_rate_chk
                CHECK (achievement_rate >= 0 AND achievement_rate <= 9.9999)
        )
        """
    )

    # 索引：按目标查进度时间序列（用于画完成率曲线）
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sales_progress_target_snapshot
            ON sales_progress (tenant_id, target_id, snapshot_at DESC)
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 4. RLS 多租户隔离
    # ─────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE sales_targets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_targets FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sales_targets_tenant ON sales_targets")
    op.execute(
        """
        CREATE POLICY sales_targets_tenant ON sales_targets
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
        """
    )

    op.execute("ALTER TABLE sales_progress ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_progress FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sales_progress_tenant ON sales_progress")
    op.execute(
        """
        CREATE POLICY sales_progress_tenant ON sales_progress
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 5. 注释
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        "COMMENT ON TABLE sales_targets IS "
        "'销售目标设定（年/月/周/日 × 6 种指标，R1 新增）'"
    )
    op.execute(
        "COMMENT ON COLUMN sales_targets.metric_type IS "
        "'revenue_fen/order_count/table_count/unit_avg_fen/per_guest_avg_fen/new_customer_count'"
    )
    op.execute(
        "COMMENT ON COLUMN sales_targets.target_value IS "
        "'金额类目标单位为分（整数），其他为计数值'"
    )
    op.execute(
        "COMMENT ON COLUMN sales_targets.parent_target_id IS "
        "'上级目标（年→月→周→日 分解链）'"
    )
    op.execute(
        "COMMENT ON TABLE sales_progress IS '销售进度快照（事件/定时触发，R1 新增）'"
    )
    op.execute(
        "COMMENT ON COLUMN sales_progress.achievement_rate IS "
        "'达成率 0.0000~9.9999（允许超过 100%）'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sales_progress CASCADE")
    op.execute("DROP TABLE IF EXISTS sales_targets CASCADE")
    op.execute("DROP TYPE IF EXISTS sales_metric_type_enum")
    op.execute("DROP TYPE IF EXISTS sales_period_type_enum")
