"""v303 — 客户触达SOP: 旅程模板 + 步骤 + 注册实例 + 步骤日志

四张表:
  1. customer_journey_templates — 旅程模板(触发类型/受众过滤/优先级)
  2. customer_journey_steps — 旅程步骤(延迟/渠道/内容模板/条件分支)
  3. customer_journey_enrollments — 客户注册实例(状态机/下次执行时间)
  4. customer_journey_step_logs — 步骤执行日志(发送状态/时间戳)

Revision ID: v303_customer_journey_sop
Revises: v302_material_library
Create Date: 2026-04-24
"""
from alembic import op

revision = "v303_customer_journey_sop"
down_revision = "v302_material_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. customer_journey_templates ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS customer_journey_templates (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            template_name       VARCHAR(200) NOT NULL,
            description         TEXT,
            trigger_type        VARCHAR(50) NOT NULL
                                CHECK (trigger_type IN (
                                    'post_payment', 'first_payment', 'birthday',
                                    'anniversary', 'dormancy', 'stored_value_low',
                                    'member_joined', 'group_joined', 'wecom_added',
                                    'manual'
                                )),
            trigger_config      JSONB NOT NULL DEFAULT '{}'::jsonb,
            audience_filter     JSONB NOT NULL DEFAULT '{}'::jsonb,
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            priority            INTEGER NOT NULL DEFAULT 0,
            max_concurrent      INTEGER NOT NULL DEFAULT 1,
            created_by          UUID,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cj_templates_tenant_trigger
            ON customer_journey_templates (tenant_id, trigger_type, is_active)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE customer_journey_templates ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS cj_templates_tenant_isolation ON customer_journey_templates;
        CREATE POLICY cj_templates_tenant_isolation ON customer_journey_templates
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 2. customer_journey_steps ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS customer_journey_steps (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            template_id         UUID NOT NULL REFERENCES customer_journey_templates(id),
            step_order          INTEGER NOT NULL,
            step_name           VARCHAR(200) NOT NULL,
            delay_minutes       INTEGER NOT NULL DEFAULT 0,
            channel             VARCHAR(30) NOT NULL
                                CHECK (channel IN (
                                    'wecom_private', 'wecom_group', 'sms',
                                    'push', 'wechat_template'
                                )),
            content_template    JSONB NOT NULL DEFAULT '{}'::jsonb,
            condition           JSONB,
            skip_if_responded   BOOLEAN NOT NULL DEFAULT FALSE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cj_steps_template
            ON customer_journey_steps (template_id, step_order)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE customer_journey_steps ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS cj_steps_tenant_isolation ON customer_journey_steps;
        CREATE POLICY cj_steps_tenant_isolation ON customer_journey_steps
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 3. customer_journey_enrollments ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS customer_journey_enrollments (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            template_id         UUID NOT NULL REFERENCES customer_journey_templates(id),
            customer_id         UUID NOT NULL,
            store_id            UUID NOT NULL,
            trigger_event       JSONB,
            current_step_id     UUID REFERENCES customer_journey_steps(id),
            status              VARCHAR(20) NOT NULL DEFAULT 'active'
                                CHECK (status IN (
                                    'active', 'completed', 'paused',
                                    'cancelled', 'expired'
                                )),
            next_action_at      TIMESTAMPTZ,
            started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cj_enrollments_pending
            ON customer_journey_enrollments (tenant_id, next_action_at)
            WHERE status = 'active' AND is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cj_enrollments_customer
            ON customer_journey_enrollments (tenant_id, customer_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cj_enrollments_template
            ON customer_journey_enrollments (tenant_id, template_id, status)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE customer_journey_enrollments ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS cj_enrollments_tenant_isolation ON customer_journey_enrollments;
        CREATE POLICY cj_enrollments_tenant_isolation ON customer_journey_enrollments
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 4. customer_journey_step_logs ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS customer_journey_step_logs (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            enrollment_id       UUID NOT NULL REFERENCES customer_journey_enrollments(id),
            step_id             UUID NOT NULL REFERENCES customer_journey_steps(id),
            channel             VARCHAR(30) NOT NULL,
            content_sent        JSONB,
            send_status         VARCHAR(20) NOT NULL DEFAULT 'pending'
                                CHECK (send_status IN (
                                    'pending', 'sent', 'delivered', 'read',
                                    'responded', 'failed', 'skipped'
                                )),
            coupon_instance_id  UUID,
            failure_reason      TEXT,
            sent_at             TIMESTAMPTZ,
            delivered_at        TIMESTAMPTZ,
            read_at             TIMESTAMPTZ,
            responded_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cj_step_logs_enrollment
            ON customer_journey_step_logs (enrollment_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cj_step_logs_status
            ON customer_journey_step_logs (tenant_id, send_status)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE customer_journey_step_logs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS cj_step_logs_tenant_isolation ON customer_journey_step_logs;
        CREATE POLICY cj_step_logs_tenant_isolation ON customer_journey_step_logs
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS customer_journey_step_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS customer_journey_enrollments CASCADE")
    op.execute("DROP TABLE IF EXISTS customer_journey_steps CASCADE")
    op.execute("DROP TABLE IF EXISTS customer_journey_templates CASCADE")
