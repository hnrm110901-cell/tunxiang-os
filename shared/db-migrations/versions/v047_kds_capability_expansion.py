"""v047: KDS能力扩展 — 停菜/抢单/泳道/绩效/预制量/档口毛利

新增字段（kds_tasks）：
  is_paused     — 停菜控制标记
  paused_at     — 停菜时间
  grabbed_by    — 抢单时记录抢单厨师ID

新增表：
  production_steps        — 工序定义（泳道模式，每道菜可配多个工序步骤）
  kds_task_steps          — 工序实例（每个任务的工序执行记录）
  chef_performance_daily  — 厨师绩效日汇总（计件核算基础表）
  soldout_records         — 沽清记录（后厨标记→前台/小程序全链路同步）

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v047
Revises: v046
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa

revision = "v047"
down_revision = "v046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. kds_tasks 新增字段：停菜控制 + 抢单
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE kds_tasks
            ADD COLUMN IF NOT EXISTS is_paused   BOOLEAN     NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS paused_at   TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS grabbed_by  UUID;

        COMMENT ON COLUMN kds_tasks.is_paused  IS '停菜标记：半成品已做好但暂缓出品';
        COMMENT ON COLUMN kds_tasks.paused_at  IS '停菜时间';
        COMMENT ON COLUMN kds_tasks.grabbed_by IS '抢单厨师ID（抢单模式下记录谁抢了这张单）';
    """)

    # ─────────────────────────────────────────────────────────────────
    # 2. production_steps — 工序定义（泳道模式核心）
    #    每道菜可配置多个工序步骤，用于泳道看板的横向流转
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS production_steps (
            id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    UUID        NOT NULL,
            store_id     UUID        NOT NULL,
            dept_id      UUID        NOT NULL,
            step_name    VARCHAR(50) NOT NULL,
            step_order   INT         NOT NULL DEFAULT 1,
            color        VARCHAR(20) NOT NULL DEFAULT '#4A90D9',
            is_active    BOOLEAN     NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted   BOOLEAN     NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_production_steps_dept_order
                UNIQUE (tenant_id, dept_id, step_order)
        );

        COMMENT ON TABLE production_steps IS
            '工序步骤定义：每个档口的生产流水线工序（如切配→烹饪→装盘→传菜）';

        CREATE INDEX IF NOT EXISTS ix_production_steps_tenant_dept
            ON production_steps (tenant_id, dept_id)
            WHERE is_deleted = FALSE;
    """)

    # RLS: production_steps
    op.execute("""
        ALTER TABLE production_steps ENABLE ROW LEVEL SECURITY;
        ALTER TABLE production_steps FORCE ROW LEVEL SECURITY;

        CREATE POLICY production_steps_tenant_isolation ON production_steps
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)

    # ─────────────────────────────────────────────────────────────────
    # 3. kds_task_steps — 工序实例（每个KDS任务在每道工序的执行记录）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS kds_task_steps (
            id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    UUID        NOT NULL,
            task_id      UUID        NOT NULL,
            step_id      UUID        NOT NULL,
            step_order   INT         NOT NULL,
            status       VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'in_progress', 'done', 'skipped')),
            operator_id  UUID,
            started_at   TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted   BOOLEAN     NOT NULL DEFAULT FALSE
        );

        COMMENT ON TABLE kds_task_steps IS
            '工序执行实例：每条kds_task在泳道中各工序的实际执行状态';

        CREATE INDEX IF NOT EXISTS ix_kds_task_steps_task_id
            ON kds_task_steps (task_id);
        CREATE INDEX IF NOT EXISTS ix_kds_task_steps_tenant_step
            ON kds_task_steps (tenant_id, step_id, status);
    """)

    # RLS: kds_task_steps
    op.execute("""
        ALTER TABLE kds_task_steps ENABLE ROW LEVEL SECURITY;
        ALTER TABLE kds_task_steps FORCE ROW LEVEL SECURITY;

        CREATE POLICY kds_task_steps_tenant_isolation ON kds_task_steps
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)

    # ─────────────────────────────────────────────────────────────────
    # 4. chef_performance_daily — 厨师绩效日汇总
    #    每日每厨师的出品数量和金额汇总，用于绩效计件
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS chef_performance_daily (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            dept_id         UUID        NOT NULL,
            operator_id     UUID        NOT NULL,
            perf_date       DATE        NOT NULL,
            dish_count      INT         NOT NULL DEFAULT 0,
            dish_amount     NUMERIC(12,2) NOT NULL DEFAULT 0,
            avg_cook_sec    INT         NOT NULL DEFAULT 0,
            rush_handled    INT         NOT NULL DEFAULT 0,
            remake_count    INT         NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_chef_perf_daily
                UNIQUE (tenant_id, operator_id, dept_id, perf_date)
        );

        COMMENT ON TABLE chef_performance_daily IS
            '厨师绩效日汇总：每日每人每档口的出品数量/金额，支持计件绩效核算';

        CREATE INDEX IF NOT EXISTS ix_chef_perf_tenant_date
            ON chef_performance_daily (tenant_id, perf_date);
        CREATE INDEX IF NOT EXISTS ix_chef_perf_operator
            ON chef_performance_daily (tenant_id, operator_id, perf_date);
    """)

    # RLS: chef_performance_daily
    op.execute("""
        ALTER TABLE chef_performance_daily ENABLE ROW LEVEL SECURITY;
        ALTER TABLE chef_performance_daily FORCE ROW LEVEL SECURITY;

        CREATE POLICY chef_performance_daily_tenant_isolation ON chef_performance_daily
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)

    # ─────────────────────────────────────────────────────────────────
    # 5. soldout_records — 沽清记录（全链路同步基础）
    #    后厨在KDS上标记沽清后，同步到POS菜单/小程序菜单/前台显示
    # ─────────────────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS soldout_records (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            dish_id         UUID        NOT NULL,
            dish_name       VARCHAR(100) NOT NULL,
            soldout_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            restore_at      TIMESTAMPTZ,
            is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
            reason          VARCHAR(200),
            reported_by     UUID,
            source          VARCHAR(20) NOT NULL DEFAULT 'kds'
                CHECK (source IN ('kds', 'pos', 'admin', 'supply')),
            sync_status     JSONB       NOT NULL DEFAULT '{"pos"\:false,"miniapp"\:false,"kds"\:false}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        );

        COMMENT ON TABLE soldout_records IS
            '沽清记录：后厨KDS标记沽清后的全链路同步状态跟踪（POS/小程序/KDS同步状态）';

        CREATE INDEX IF NOT EXISTS ix_soldout_tenant_active
            ON soldout_records (tenant_id, store_id, is_active)
            WHERE is_active = TRUE;
        CREATE INDEX IF NOT EXISTS ix_soldout_dish_store
            ON soldout_records (tenant_id, dish_id, store_id);
    """))

    # RLS: soldout_records
    op.execute("""
        ALTER TABLE soldout_records ENABLE ROW LEVEL SECURITY;
        ALTER TABLE soldout_records FORCE ROW LEVEL SECURITY;

        CREATE POLICY soldout_records_tenant_isolation ON soldout_records
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS soldout_records_tenant_isolation ON soldout_records;")
    op.execute("DROP TABLE IF EXISTS soldout_records;")

    op.execute("DROP POLICY IF EXISTS chef_performance_daily_tenant_isolation ON chef_performance_daily;")
    op.execute("DROP TABLE IF EXISTS chef_performance_daily;")

    op.execute("DROP POLICY IF EXISTS kds_task_steps_tenant_isolation ON kds_task_steps;")
    op.execute("DROP TABLE IF EXISTS kds_task_steps;")

    op.execute("DROP POLICY IF EXISTS production_steps_tenant_isolation ON production_steps;")
    op.execute("DROP TABLE IF EXISTS production_steps;")

    op.execute("""
        ALTER TABLE kds_tasks
            DROP COLUMN IF EXISTS is_paused,
            DROP COLUMN IF EXISTS paused_at,
            DROP COLUMN IF EXISTS grabbed_by;
    """)
