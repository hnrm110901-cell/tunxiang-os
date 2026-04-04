"""Journey 触发引擎 — 三张核心表

新增 3 张表，支持事件驱动的旅程编排执行：
  journey_definitions    — 旅程定义模板（触发事件+条件+步骤）
  journey_enrollments    — 客户加入旅程记录（每个客户一条）
  journey_step_executions — 步骤执行记录（可审计）

设计要点：
  - journey_definitions.steps JSONB 存储步骤列表，支持等待/发消息/发券/打标签/条件分支
  - journey_enrollments 状态机：active → completed/exited/failed
  - journey_step_executions 记录每步执行结果，不可删改，仅追加
  - 全部表含 tenant_id，启用 RLS（v006+ 标准安全模式）

与现有表的关系：
  - journey_instances（v026）继续使用，新引擎使用 journey_enrollments 取代内存存储
  - journey_definitions 是 JourneyOrchestratorService._journeys 的 DB 持久化版本

RLS：全部使用 v006+ 标准安全模式（4 操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v088
Revises: v086
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v089"
down_revision = "v088"
branch_labels = None
depends_on = None

_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. journey_definitions — 旅程定义模板
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS journey_definitions (
            id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID         NOT NULL,
            name                VARCHAR(100) NOT NULL,
            description         TEXT,
            trigger_event       VARCHAR(50)  NOT NULL
                CHECK (trigger_event IN (
                    'first_visit',
                    '7day_inactive',
                    '15day_inactive',
                    '30day_inactive',
                    'birthday',
                    'post_order',
                    'low_repurchase_risk',
                    'banquet_completed',
                    'high_ltv',
                    'reservation_abandoned',
                    'new_dish_launch',
                    'manual'
                )),
            trigger_conditions  JSONB        NOT NULL DEFAULT '[]'::jsonb,
            steps               JSONB        NOT NULL DEFAULT '[]'::jsonb,
            target_segment      VARCHAR(100),
            is_active           BOOLEAN      NOT NULL DEFAULT FALSE,
            version             INTEGER      NOT NULL DEFAULT 1,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_journey_definitions_tenant ON journey_definitions(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_journey_definitions_active ON journey_definitions(tenant_id, is_active) WHERE is_active = TRUE")
    op.execute("CREATE INDEX IF NOT EXISTS idx_journey_definitions_event ON journey_definitions(tenant_id, trigger_event) WHERE is_active = TRUE")

    # RLS
    op.execute("ALTER TABLE journey_definitions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE journey_definitions FORCE ROW LEVEL SECURITY")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        if action == "INSERT":
            op.execute(f"""
            CREATE POLICY journey_definitions_{action.lower()}_tenant
            ON journey_definitions
            FOR {action}
            WITH CHECK ({_RLS_COND})
        """)
        else:
            op.execute(f"""
            CREATE POLICY journey_definitions_{action.lower()}_tenant
            ON journey_definitions
            FOR {action}
            USING ({_RLS_COND})
        """)

    # ─────────────────────────────────────────────────────────────────
    # 2. journey_enrollments — 客户加入旅程记录
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS journey_enrollments (
            id                       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                UUID         NOT NULL,
            journey_definition_id    UUID         NOT NULL,
            customer_id              UUID         NOT NULL,
            phone                    VARCHAR(20),
            current_step_id          VARCHAR(64),
            status                   VARCHAR(20)  NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'completed', 'exited', 'failed')),
            enrolled_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            completed_at             TIMESTAMPTZ,
            exited_at                TIMESTAMPTZ,
            context_data             JSONB        NOT NULL DEFAULT '{}'::jsonb,
            next_step_at             TIMESTAMPTZ,
            created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_journey_enrollments_tenant ON journey_enrollments(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_journey_enrollments_customer ON journey_enrollments(tenant_id, customer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_journey_enrollments_poll ON journey_enrollments(status, next_step_at) WHERE status = 'active'")
    op.execute("CREATE INDEX IF NOT EXISTS idx_journey_enrollments_def ON journey_enrollments(tenant_id, journey_definition_id)")
    # 防重入：同一客户在同一旅程中只能有一个 active 实例
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_enrollment_active
        ON journey_enrollments(tenant_id, journey_definition_id, customer_id)
        WHERE status = 'active'
    """)

    # RLS
    op.execute("ALTER TABLE journey_enrollments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE journey_enrollments FORCE ROW LEVEL SECURITY")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        if action == "INSERT":
            op.execute(f"""
            CREATE POLICY journey_enrollments_{action.lower()}_tenant
            ON journey_enrollments
            FOR {action}
            WITH CHECK ({_RLS_COND})
        """)
        else:
            op.execute(f"""
            CREATE POLICY journey_enrollments_{action.lower()}_tenant
            ON journey_enrollments
            FOR {action}
            USING ({_RLS_COND})
        """)

    # ─────────────────────────────────────────────────────────────────
    # 3. journey_step_executions — 步骤执行记录
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS journey_step_executions (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            enrollment_id   UUID         NOT NULL,
            step_id         VARCHAR(64)  NOT NULL,
            action_type     VARCHAR(50)  NOT NULL
                CHECK (action_type IN (
                    'wait',
                    'send_wecom',
                    'send_sms',
                    'send_miniapp_push',
                    'award_coupon',
                    'tag_customer',
                    'condition_branch',
                    'notify_staff'
                )),
            action_config   JSONB        NOT NULL DEFAULT '{}'::jsonb,
            status          VARCHAR(20)  NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'executing', 'completed', 'failed', 'skipped')),
            scheduled_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            executed_at     TIMESTAMPTZ,
            result          JSONB,
            error_message   TEXT,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_step_executions_tenant ON journey_step_executions(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_step_executions_enrollment ON journey_step_executions(enrollment_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_step_executions_poll ON journey_step_executions(status, scheduled_at) WHERE status = 'pending'")

    # RLS
    op.execute("ALTER TABLE journey_step_executions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE journey_step_executions FORCE ROW LEVEL SECURITY")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        if action == "INSERT":
            op.execute(f"""
            CREATE POLICY journey_step_executions_{action.lower()}_tenant
            ON journey_step_executions
            FOR {action}
            WITH CHECK ({_RLS_COND})
        """)
        else:
            op.execute(f"""
            CREATE POLICY journey_step_executions_{action.lower()}_tenant
            ON journey_step_executions
            FOR {action}
            USING ({_RLS_COND})
        """)


def downgrade() -> None:
    for table in ("journey_step_executions", "journey_enrollments", "journey_definitions"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
