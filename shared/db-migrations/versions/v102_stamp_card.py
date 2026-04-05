"""v102: 集点卡 — 模板 / 实例 / 盖章记录三表

新建 3 张表：
  - stamp_card_templates  — 集点卡模板（名称/目标次数/奖励/有效期/门店范围）
  - stamp_card_instances  — 用户集点卡实例（当前印章数/状态/过期时间）
  - stamp_card_stamps     — 盖章记录（关联订单/门店/时间）

设计要点：
  - 一个模板可发行多个实例（每用户最多一张进行中的同模板卡）
  - stamp_card_instances.status 状态机：active → completed / expired
  - 盖章数通过 stamp_count 字段原子递增，避免 COUNT 查询

Revision ID: v102
Revises: v101
Create Date: 2026-04-01
"""

from alembic import op

revision = "v102b"
down_revision = "v102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. stamp_card_templates — 集点卡模板 ─────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stamp_card_templates (
            id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID         NOT NULL,
            name              VARCHAR(200) NOT NULL,
            description       TEXT,
            target_stamps     INT          NOT NULL DEFAULT 5,
            reward_type       VARCHAR(30)  NOT NULL DEFAULT 'coupon',
            reward_config     JSONB        NOT NULL DEFAULT '{}',
            validity_days     INT          NOT NULL DEFAULT 90,
            applicable_stores JSONB        NOT NULL DEFAULT '[]',
            min_order_fen     INT          NOT NULL DEFAULT 0,
            status            VARCHAR(20)  NOT NULL DEFAULT 'active',
            issued_count      INT          NOT NULL DEFAULT 0,
            completed_count   INT          NOT NULL DEFAULT 0,
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted        BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("ALTER TABLE stamp_card_templates ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY stamp_card_templates_rls ON stamp_card_templates
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    # Ensure is_deleted column exists (table may predate this migration)
    op.execute("""
        ALTER TABLE stamp_card_templates
            ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE
    """)
    # Ensure is_deleted column exists (table may predate this migration)
    op.execute("""
        ALTER TABLE stamp_card_instances
            ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_stamp_card_templates_tenant
            ON stamp_card_templates(tenant_id, status)
            WHERE is_deleted = false
    """)

    # ── 2. stamp_card_instances — 用户集点卡实例 ─────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stamp_card_instances (
            id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID         NOT NULL,
            template_id   UUID         NOT NULL REFERENCES stamp_card_templates(id),
            customer_id   UUID         NOT NULL,
            stamp_count   INT          NOT NULL DEFAULT 0,
            target_stamps INT          NOT NULL,
            status        VARCHAR(20)  NOT NULL DEFAULT 'active',
            expired_at    TIMESTAMPTZ  NOT NULL,
            completed_at  TIMESTAMPTZ,
            reward_issued BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted    BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("ALTER TABLE stamp_card_instances ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY stamp_card_instances_rls ON stamp_card_instances
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_stamp_card_instances_customer
            ON stamp_card_instances(tenant_id, customer_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_stamp_card_instances_template
            ON stamp_card_instances(tenant_id, template_id, status)
            WHERE is_deleted = false
    """)

    # ── 3. stamp_card_stamps — 盖章记录 ──────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stamp_card_stamps (
            id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID         NOT NULL,
            instance_id   UUID         NOT NULL REFERENCES stamp_card_instances(id),
            order_id      UUID,
            store_id      UUID,
            stamp_no      INT          NOT NULL,
            stamped_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted    BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("ALTER TABLE stamp_card_stamps ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY stamp_card_stamps_rls ON stamp_card_stamps
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_stamp_card_stamps_instance
            ON stamp_card_stamps(tenant_id, instance_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stamp_card_stamps CASCADE")
    op.execute("DROP TABLE IF EXISTS stamp_card_instances CASCADE")
    op.execute("DROP TABLE IF EXISTS stamp_card_templates CASCADE")
