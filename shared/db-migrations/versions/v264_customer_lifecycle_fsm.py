"""v264 — 客户生命周期状态机（四象限 FSM）

对应规划：docs/reservation-roadmap-2026-q2.md §6 Sprint R1
依据路线图任务：
  客户状态机 FSM + Event Sourcing
  4 象限（no_order/active/dormant/churned）+ 4 流量
  物化视图 mv_customer_lifecycle（后续 Sprint 补）

本迁移只建表，不含种子数据。Projector 与 API 在 R1 其他 PR 中引入。

表清单：
  customer_lifecycle_state — 客户当前状态单记录表

RLS：tenant_id = app.tenant_id（对齐 CLAUDE.md §14）
事件：CustomerLifecycleEventType.STATE_CHANGED

Revision: v264
Revises: v263
Create Date: 2026-04-23
"""

from alembic import op

revision = "v264b"
down_revision = "v263"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. 客户生命周期状态枚举类型
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE customer_lifecycle_state_enum AS ENUM (
                'no_order',
                'active',
                'dormant',
                'churned'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 2. customer_lifecycle_state — 每个 customer 当前状态单条记录
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS customer_lifecycle_state (
            customer_id              UUID                                  NOT NULL,
            tenant_id                UUID                                  NOT NULL,
            state                    customer_lifecycle_state_enum         NOT NULL DEFAULT 'no_order',
            since_ts                 TIMESTAMPTZ                           NOT NULL DEFAULT NOW(),
            last_transition_event_id UUID,
            previous_state           customer_lifecycle_state_enum,
            transition_count         INTEGER                               NOT NULL DEFAULT 0,
            updated_at               TIMESTAMPTZ                           NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, customer_id)
        )
        """
    )

    # 索引：按 (tenant_id, state) 做 4 象限聚合查询
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_customer_lifecycle_state_tenant_state
            ON customer_lifecycle_state (tenant_id, state)
        """
    )
    # 索引：按 customer_id 快速查询（跨租户扫描场景 Agent 决策留痕用）
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_customer_lifecycle_state_customer
            ON customer_lifecycle_state (customer_id)
        """
    )
    # 索引：按 since_ts 查询近期状态跃迁（流量分析）
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_customer_lifecycle_state_since
            ON customer_lifecycle_state (tenant_id, since_ts DESC)
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 3. RLS 多租户隔离
    # ─────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE customer_lifecycle_state ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE customer_lifecycle_state FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS customer_lifecycle_state_tenant ON customer_lifecycle_state"
    )
    op.execute(
        """
        CREATE POLICY customer_lifecycle_state_tenant ON customer_lifecycle_state
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 4. 注释
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        "COMMENT ON TABLE customer_lifecycle_state IS "
        "'客户生命周期状态机（四象限 FSM）— 支撑销售教练 Agent 与沉睡召回'"
    )
    op.execute(
        "COMMENT ON COLUMN customer_lifecycle_state.state IS "
        "'当前状态：no_order/active/dormant/churned'"
    )
    op.execute(
        "COMMENT ON COLUMN customer_lifecycle_state.since_ts IS '进入当前状态的起点时间'"
    )
    op.execute(
        "COMMENT ON COLUMN customer_lifecycle_state.last_transition_event_id IS "
        "'最近一次状态变更事件ID，指向 events 表'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS customer_lifecycle_state CASCADE")
    op.execute("DROP TYPE IF EXISTS customer_lifecycle_state_enum")
