"""v291 — 销售CRM模块

5张新表：
  - sales_targets           — 销售目标（年度/月度/周/日，按门店/品牌/员工）
  - sales_leads             — 销售线索（来源追踪/阶段管理/漏斗分析）
  - sales_tasks             — 销售任务（跟进/回访/生日提醒/沉默召回）
  - sales_visit_logs        — 拜访记录（电话/微信/到店/短信）
  - customer_profile_scores — 客户画像完整度评分

所有表启用 RLS 租户隔离。

Revision ID: v291
Revises: v290
Create Date: 2026-04-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "v291"
down_revision: Union[str, None] = "v290"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── sales_targets ──
    op.execute("""
    CREATE TABLE sales_targets (
        tenant_id              UUID          NOT NULL,
        id                     UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        store_id               UUID,
        brand_id               UUID,
        employee_id            UUID,
        target_type            VARCHAR(20)   NOT NULL CHECK (target_type IN ('annual', 'monthly', 'weekly', 'daily')),
        year                   INTEGER       NOT NULL,
        month                  INTEGER,
        target_revenue_fen     BIGINT        DEFAULT 0,
        target_orders          INTEGER       DEFAULT 0,
        target_new_customers   INTEGER       DEFAULT 0,
        target_reservations    INTEGER       DEFAULT 0,
        actual_revenue_fen     BIGINT        DEFAULT 0,
        actual_orders          INTEGER       DEFAULT 0,
        actual_new_customers   INTEGER       DEFAULT 0,
        actual_reservations    INTEGER       DEFAULT 0,
        achievement_rate       NUMERIC(5,2)  DEFAULT 0,
        created_at             TIMESTAMPTZ   DEFAULT now(),
        updated_at             TIMESTAMPTZ   DEFAULT now(),
        is_deleted             BOOLEAN       DEFAULT FALSE
    );

    ALTER TABLE sales_targets ENABLE ROW LEVEL SECURITY;
    CREATE POLICY sales_targets_tenant ON sales_targets
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

    CREATE INDEX ix_sales_targets_tenant_store_year
        ON sales_targets (tenant_id, store_id, year, month);
    CREATE INDEX ix_sales_targets_tenant_employee
        ON sales_targets (tenant_id, employee_id);
    """)

    # ── sales_leads ──
    op.execute("""
    CREATE TABLE sales_leads (
        tenant_id              UUID          NOT NULL,
        id                     UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        store_id               UUID          NOT NULL,
        customer_id            UUID,
        customer_name          VARCHAR(100),
        customer_phone         VARCHAR(20),
        lead_source            VARCHAR(30)   CHECK (lead_source IN ('walk_in', 'phone', 'wechat', 'meituan', 'douyin', 'referral', 'website', 'other')),
        lead_type              VARCHAR(30)   CHECK (lead_type IN ('dining', 'banquet', 'group_buy', 'corporate')),
        stage                  VARCHAR(30)   NOT NULL CHECK (stage IN ('new', 'contacted', 'qualified', 'proposal', 'negotiation', 'won', 'lost')) DEFAULT 'new',
        expected_revenue_fen   BIGINT,
        expected_date          DATE,
        assigned_to            UUID,
        priority               VARCHAR(10)   CHECK (priority IN ('low', 'medium', 'high', 'urgent')) DEFAULT 'medium',
        lost_reason            TEXT,
        won_order_id           UUID,
        notes                  TEXT,
        last_contacted_at      TIMESTAMPTZ,
        next_follow_up_at      TIMESTAMPTZ,
        created_at             TIMESTAMPTZ   DEFAULT now(),
        updated_at             TIMESTAMPTZ   DEFAULT now(),
        is_deleted             BOOLEAN       DEFAULT FALSE
    );

    ALTER TABLE sales_leads ENABLE ROW LEVEL SECURITY;
    CREATE POLICY sales_leads_tenant ON sales_leads
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

    CREATE INDEX ix_sales_leads_tenant_store_stage
        ON sales_leads (tenant_id, store_id, stage);
    CREATE INDEX ix_sales_leads_tenant_assigned
        ON sales_leads (tenant_id, assigned_to);
    CREATE INDEX ix_sales_leads_next_follow_up
        ON sales_leads (next_follow_up_at) WHERE next_follow_up_at IS NOT NULL;
    """)

    # ── sales_tasks ──
    op.execute("""
    CREATE TABLE sales_tasks (
        tenant_id              UUID          NOT NULL,
        id                     UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        store_id               UUID,
        employee_id            UUID          NOT NULL,
        task_type              VARCHAR(30)   NOT NULL CHECK (task_type IN (
            'follow_up', 'callback', 'visit', 'birthday_remind', 'anniversary_remind',
            'dormant_recall', 'new_customer_welcome', 'reservation_confirm',
            'post_meal_review', 'custom'
        )),
        related_lead_id        UUID,
        related_customer_id    UUID,
        title                  VARCHAR(200)  NOT NULL,
        description            TEXT,
        due_at                 TIMESTAMPTZ   NOT NULL,
        completed_at           TIMESTAMPTZ,
        status                 VARCHAR(20)   NOT NULL CHECK (status IN ('pending', 'in_progress', 'completed', 'overdue', 'cancelled')) DEFAULT 'pending',
        priority               VARCHAR(10)   DEFAULT 'medium',
        result                 TEXT,
        reminder_at            TIMESTAMPTZ,
        created_at             TIMESTAMPTZ   DEFAULT now(),
        updated_at             TIMESTAMPTZ   DEFAULT now(),
        is_deleted             BOOLEAN       DEFAULT FALSE
    );

    ALTER TABLE sales_tasks ENABLE ROW LEVEL SECURITY;
    CREATE POLICY sales_tasks_tenant ON sales_tasks
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

    CREATE INDEX ix_sales_tasks_tenant_employee_status
        ON sales_tasks (tenant_id, employee_id, status);
    CREATE INDEX ix_sales_tasks_tenant_due
        ON sales_tasks (tenant_id, due_at) WHERE status IN ('pending', 'in_progress');
    CREATE INDEX ix_sales_tasks_reminder
        ON sales_tasks (reminder_at) WHERE reminder_at IS NOT NULL AND status = 'pending';
    """)

    # ── sales_visit_logs ──
    op.execute("""
    CREATE TABLE sales_visit_logs (
        tenant_id              UUID          NOT NULL,
        id                     UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        store_id               UUID,
        employee_id            UUID          NOT NULL,
        customer_id            UUID          NOT NULL,
        visit_type             VARCHAR(20)   CHECK (visit_type IN ('phone', 'wechat', 'in_person', 'sms')),
        purpose                VARCHAR(30),
        summary                TEXT,
        customer_satisfaction  INTEGER,
        next_action            TEXT,
        next_action_date       DATE,
        created_at             TIMESTAMPTZ   DEFAULT now(),
        updated_at             TIMESTAMPTZ   DEFAULT now(),
        is_deleted             BOOLEAN       DEFAULT FALSE
    );

    ALTER TABLE sales_visit_logs ENABLE ROW LEVEL SECURITY;
    CREATE POLICY sales_visit_logs_tenant ON sales_visit_logs
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

    CREATE INDEX ix_sales_visit_logs_tenant_customer
        ON sales_visit_logs (tenant_id, customer_id, created_at DESC);
    CREATE INDEX ix_sales_visit_logs_tenant_employee
        ON sales_visit_logs (tenant_id, employee_id, created_at DESC);
    """)

    # ── customer_profile_scores ──
    op.execute("""
    CREATE TABLE customer_profile_scores (
        tenant_id              UUID          NOT NULL,
        id                     UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        customer_id            UUID          NOT NULL,
        has_name               BOOLEAN       DEFAULT FALSE,
        has_phone              BOOLEAN       DEFAULT FALSE,
        has_birthday           BOOLEAN       DEFAULT FALSE,
        has_anniversary        BOOLEAN       DEFAULT FALSE,
        has_company            BOOLEAN       DEFAULT FALSE,
        has_preference         BOOLEAN       DEFAULT FALSE,
        has_allergy            BOOLEAN       DEFAULT FALSE,
        has_service_req        BOOLEAN       DEFAULT FALSE,
        completeness_score     NUMERIC(5,2)  DEFAULT 0,
        scored_at              TIMESTAMPTZ   DEFAULT now(),
        created_at             TIMESTAMPTZ   DEFAULT now(),
        updated_at             TIMESTAMPTZ   DEFAULT now(),
        is_deleted             BOOLEAN       DEFAULT FALSE,
        UNIQUE (tenant_id, customer_id)
    );

    ALTER TABLE customer_profile_scores ENABLE ROW LEVEL SECURITY;
    CREATE POLICY customer_profile_scores_tenant ON customer_profile_scores
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

    CREATE INDEX ix_customer_profile_scores_completeness
        ON customer_profile_scores (tenant_id, completeness_score);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS customer_profile_scores CASCADE;")
    op.execute("DROP TABLE IF EXISTS sales_visit_logs CASCADE;")
    op.execute("DROP TABLE IF EXISTS sales_tasks CASCADE;")
    op.execute("DROP TABLE IF EXISTS sales_leads CASCADE;")
    op.execute("DROP TABLE IF EXISTS sales_targets CASCADE;")
