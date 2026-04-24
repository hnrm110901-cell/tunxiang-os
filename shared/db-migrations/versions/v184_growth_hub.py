"""v184 — 增长中枢 Sprint 0（growth_hub）

创建 8 张表：
  customer_growth_profiles        — 客户增长画像（复购阶段 / 激活优先级 / 权益 / 投诉修复）
  growth_journey_templates        — 旅程模板定义
  growth_journey_template_steps   — 旅程模板步骤
  growth_journey_enrollments      — 客户旅程入列记录
  growth_touch_templates          — 触达消息模板
  growth_touch_executions         — 触达执行记录 + 归因
  growth_service_repair_cases     — 服务修复案例
  growth_agent_strategy_suggestions — Agent 策略建议（人机协同审批）

Revision: v184
"""

from alembic import op

revision = "v184"
down_revision = "v183"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. customer_growth_profiles ──────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS customer_growth_profiles (
            id                          UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id                   UUID        NOT NULL,
            customer_id                 UUID        NOT NULL,
            first_order_at              TIMESTAMPTZ,
            first_order_store_id        UUID,
            first_order_channel         TEXT,
            second_order_at             TIMESTAMPTZ,
            last_order_at               TIMESTAMPTZ,
            repurchase_stage            TEXT        NOT NULL DEFAULT 'not_started',
            reactivation_priority       TEXT        NOT NULL DEFAULT 'none',
            reactivation_reason         TEXT,
            has_active_owned_benefit    BOOLEAN     DEFAULT FALSE,
            owned_benefit_type          TEXT,
            owned_benefit_expire_at     TIMESTAMPTZ,
            service_repair_status       TEXT        NOT NULL DEFAULT 'none',
            service_repair_last_case_id UUID,
            service_repair_last_closed_at TIMESTAMPTZ,
            growth_opt_out              BOOLEAN     DEFAULT FALSE,
            marketing_pause_until       TIMESTAMPTZ,
            last_growth_touch_at        TIMESTAMPTZ,
            last_growth_touch_channel   TEXT,
            psych_distance_level        TEXT,
            super_user_level            TEXT,
            growth_milestone_stage      TEXT,
            referral_scenario           TEXT,
            is_deleted                  BOOLEAN     DEFAULT FALSE,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, customer_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cgp_tenant_customer ON customer_growth_profiles (tenant_id, customer_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cgp_reactivation "
        "ON customer_growth_profiles (tenant_id, reactivation_priority) "
        "WHERE reactivation_priority != 'none'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cgp_repair "
        "ON customer_growth_profiles (tenant_id, service_repair_status) "
        "WHERE service_repair_status != 'none'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cgp_repurchase ON customer_growth_profiles (tenant_id, repurchase_stage)"
    )
    op.execute("ALTER TABLE customer_growth_profiles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE customer_growth_profiles FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS customer_growth_profiles_tenant_isolation ON customer_growth_profiles")
    op.execute("""
        CREATE POLICY customer_growth_profiles_tenant_isolation ON customer_growth_profiles
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)

    # ── 2. growth_journey_templates ──────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS growth_journey_templates (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id               UUID        NOT NULL,
            code                    TEXT        NOT NULL,
            name                    TEXT        NOT NULL,
            journey_type            TEXT        NOT NULL,
            mechanism_family        TEXT        NOT NULL,
            target_segment_rule_id  UUID,
            entry_rule_json         JSONB       DEFAULT '{}'::jsonb,
            exit_rule_json          JSONB       DEFAULT '{}'::jsonb,
            pause_rule_json         JSONB       DEFAULT '{}'::jsonb,
            priority                INT         DEFAULT 100,
            is_active               BOOLEAN     DEFAULT TRUE,
            is_system               BOOLEAN     DEFAULT FALSE,
            is_deleted              BOOLEAN     DEFAULT FALSE,
            created_by              UUID,
            updated_by              UUID,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, code)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_gjt_tenant_type ON growth_journey_templates (tenant_id, journey_type)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gjt_tenant_active "
        "ON growth_journey_templates (tenant_id, is_active) "
        "WHERE is_active = true"
    )
    op.execute("ALTER TABLE growth_journey_templates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE growth_journey_templates FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS growth_journey_templates_tenant_isolation ON growth_journey_templates")
    op.execute("""
        CREATE POLICY growth_journey_templates_tenant_isolation ON growth_journey_templates
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)

    # ── 3. growth_journey_template_steps ─────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS growth_journey_template_steps (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id               UUID        NOT NULL,
            journey_template_id     UUID        NOT NULL REFERENCES growth_journey_templates(id),
            step_no                 INT         NOT NULL,
            step_type               TEXT        NOT NULL,
            mechanism_type          TEXT,
            wait_minutes            INT,
            decision_rule_json      JSONB,
            offer_rule_json         JSONB,
            touch_template_id       UUID,
            observe_window_hours    INT,
            success_next_step_no    INT,
            fail_next_step_no       INT,
            skip_next_step_no       INT,
            is_required             BOOLEAN     DEFAULT TRUE,
            is_deleted              BOOLEAN     DEFAULT FALSE,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, journey_template_id, step_no)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gjts_template ON growth_journey_template_steps (tenant_id, journey_template_id)"
    )
    op.execute("ALTER TABLE growth_journey_template_steps ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE growth_journey_template_steps FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS growth_journey_template_steps_tenant_isolation ON growth_journey_template_steps")
    op.execute("""
        CREATE POLICY growth_journey_template_steps_tenant_isolation ON growth_journey_template_steps
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)

    # ── 4. growth_journey_enrollments ────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS growth_journey_enrollments (
            id                          UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id                   UUID        NOT NULL,
            customer_id                 UUID        NOT NULL,
            journey_template_id         UUID        NOT NULL REFERENCES growth_journey_templates(id),
            enrollment_source           TEXT        NOT NULL,
            source_event_type           TEXT,
            source_event_id             TEXT,
            journey_state               TEXT        NOT NULL DEFAULT 'eligible',
            current_step_no             INT,
            entered_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            activated_at                TIMESTAMPTZ,
            paused_at                   TIMESTAMPTZ,
            completed_at                TIMESTAMPTZ,
            exited_at                   TIMESTAMPTZ,
            exit_reason                 TEXT,
            pause_reason                TEXT,
            next_execute_at             TIMESTAMPTZ,
            assigned_agent_suggestion_id UUID,
            is_deleted                  BOOLEAN     DEFAULT FALSE,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gje_poll "
        "ON growth_journey_enrollments (tenant_id, journey_state, next_execute_at) "
        "WHERE journey_state IN ('active','waiting_observe')"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_gje_customer ON growth_journey_enrollments (tenant_id, customer_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_gje_dedup "
        "ON growth_journey_enrollments (tenant_id, journey_template_id, customer_id) "
        "WHERE journey_state IN ('eligible','active','paused','waiting_observe') AND is_deleted = false"
    )
    op.execute("ALTER TABLE growth_journey_enrollments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE growth_journey_enrollments FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS growth_journey_enrollments_tenant_isolation ON growth_journey_enrollments")
    op.execute("""
        CREATE POLICY growth_journey_enrollments_tenant_isolation ON growth_journey_enrollments
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)

    # ── 5. growth_touch_templates ────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS growth_touch_templates (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id               UUID        NOT NULL,
            code                    TEXT        NOT NULL,
            name                    TEXT        NOT NULL,
            template_family         TEXT        NOT NULL,
            mechanism_type          TEXT        NOT NULL,
            channel                 TEXT        NOT NULL,
            tone                    TEXT        DEFAULT 'neutral',
            content_template        TEXT        NOT NULL,
            variables_schema_json   JSONB       DEFAULT '[]'::jsonb,
            forbidden_phrases_json  JSONB       DEFAULT '[]'::jsonb,
            requires_human_review   BOOLEAN     DEFAULT FALSE,
            is_system               BOOLEAN     DEFAULT FALSE,
            is_active               BOOLEAN     DEFAULT TRUE,
            is_deleted              BOOLEAN     DEFAULT FALSE,
            created_by              UUID,
            updated_by              UUID,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, code)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_gtt_family ON growth_touch_templates (tenant_id, template_family)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_gtt_mechanism ON growth_touch_templates (tenant_id, mechanism_type)")
    op.execute("ALTER TABLE growth_touch_templates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE growth_touch_templates FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS growth_touch_templates_tenant_isolation ON growth_touch_templates")
    op.execute("""
        CREATE POLICY growth_touch_templates_tenant_isolation ON growth_touch_templates
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)

    # ── 6. growth_touch_executions ───────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS growth_touch_executions (
            id                          UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id                   UUID        NOT NULL,
            customer_id                 UUID        NOT NULL,
            journey_enrollment_id       UUID        REFERENCES growth_journey_enrollments(id),
            journey_template_id         UUID,
            step_no                     INT,
            touch_template_id           UUID,
            channel                     TEXT        NOT NULL,
            mechanism_type              TEXT,
            execution_state             TEXT        NOT NULL DEFAULT 'pending',
            blocked_reason              TEXT,
            rendered_content            TEXT,
            rendered_variables_json     JSONB,
            sent_at                     TIMESTAMPTZ,
            delivered_at                TIMESTAMPTZ,
            opened_at                   TIMESTAMPTZ,
            clicked_at                  TIMESTAMPTZ,
            replied_at                  TIMESTAMPTZ,
            failed_at                   TIMESTAMPTZ,
            attribution_window_hours    INT         DEFAULT 168,
            attributed_order_id         UUID,
            attributed_revenue_fen      BIGINT,
            attributed_gross_profit_fen BIGINT,
            is_deleted                  BOOLEAN     DEFAULT FALSE,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gtexec_customer_time "
        "ON growth_touch_executions (tenant_id, customer_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gtexec_enrollment ON growth_touch_executions (tenant_id, journey_enrollment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gtexec_attribution "
        "ON growth_touch_executions (tenant_id, execution_state, created_at) "
        "WHERE attributed_order_id IS NULL AND execution_state = 'delivered'"
    )
    op.execute("ALTER TABLE growth_touch_executions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE growth_touch_executions FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS growth_touch_executions_tenant_isolation ON growth_touch_executions")
    op.execute("""
        CREATE POLICY growth_touch_executions_tenant_isolation ON growth_touch_executions
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)

    # ── 7. growth_service_repair_cases ───────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS growth_service_repair_cases (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id               UUID        NOT NULL,
            customer_id             UUID        NOT NULL,
            source_type             TEXT        NOT NULL,
            source_ref_id           TEXT,
            severity                TEXT        NOT NULL DEFAULT 'medium',
            repair_state            TEXT        NOT NULL DEFAULT 'opened',
            emotion_ack_at          TIMESTAMPTZ,
            compensation_plan_json  JSONB,
            compensation_selected   TEXT,
            compensation_sent_at    TIMESTAMPTZ,
            observe_until           TIMESTAMPTZ,
            recovered_at            TIMESTAMPTZ,
            failed_at               TIMESTAMPTZ,
            closed_at               TIMESTAMPTZ,
            owner_type              TEXT        DEFAULT 'auto',
            owner_id                UUID,
            summary                 TEXT,
            is_deleted              BOOLEAN     DEFAULT FALSE,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_gsrc_customer ON growth_service_repair_cases (tenant_id, customer_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gsrc_state "
        "ON growth_service_repair_cases (tenant_id, repair_state) "
        "WHERE repair_state NOT IN ('closed')"
    )
    op.execute("ALTER TABLE growth_service_repair_cases ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE growth_service_repair_cases FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS growth_service_repair_cases_tenant_isolation ON growth_service_repair_cases")
    op.execute("""
        CREATE POLICY growth_service_repair_cases_tenant_isolation ON growth_service_repair_cases
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)

    # ── 8. growth_agent_strategy_suggestions ─────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS growth_agent_strategy_suggestions (
            id                              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id                       UUID        NOT NULL,
            customer_id                     UUID,
            segment_package_id              UUID,
            journey_template_id             UUID,
            suggestion_type                 TEXT        NOT NULL,
            priority                        TEXT        NOT NULL DEFAULT 'medium',
            mechanism_type                  TEXT,
            recommended_offer_type          TEXT,
            recommended_channel             TEXT,
            recommended_touch_template_id   UUID,
            explanation_summary             TEXT        NOT NULL,
            risk_summary                    TEXT,
            expected_outcome_json           JSONB,
            review_state                    TEXT        NOT NULL DEFAULT 'draft',
            reviewer_id                     UUID,
            reviewer_note                   TEXT,
            revised_offer_type              TEXT,
            revised_channel                 TEXT,
            revised_template_id             UUID,
            reviewed_at                     TIMESTAMPTZ,
            published_at                    TIMESTAMPTZ,
            published_enrollment_id         UUID,
            requires_human_review           BOOLEAN     DEFAULT FALSE,
            created_by_agent                TEXT,
            is_deleted                      BOOLEAN     DEFAULT FALSE,
            created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gass_review "
        "ON growth_agent_strategy_suggestions (tenant_id, review_state, created_at DESC) "
        "WHERE review_state IN ('pending_review','approved')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gass_customer ON growth_agent_strategy_suggestions (tenant_id, customer_id)"
    )
    op.execute("ALTER TABLE growth_agent_strategy_suggestions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE growth_agent_strategy_suggestions FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS growth_agent_strategy_suggestions_tenant_isolation ON growth_agent_strategy_suggestions"
    )
    op.execute("""
        CREATE POLICY growth_agent_strategy_suggestions_tenant_isolation ON growth_agent_strategy_suggestions
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS growth_agent_strategy_suggestions")
    op.execute("DROP TABLE IF EXISTS growth_service_repair_cases")
    op.execute("DROP TABLE IF EXISTS growth_touch_executions")
    op.execute("DROP TABLE IF EXISTS growth_touch_templates")
    op.execute("DROP TABLE IF EXISTS growth_journey_enrollments")
    op.execute("DROP TABLE IF EXISTS growth_journey_template_steps")
    op.execute("DROP TABLE IF EXISTS growth_journey_templates")
    op.execute("DROP TABLE IF EXISTS customer_growth_profiles")
