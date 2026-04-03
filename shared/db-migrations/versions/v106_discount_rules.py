"""v106: 新建 discount_rules 和 checkout_discount_log 表 — 多优惠叠加规则引擎

新建 2 张表：
  discount_rules        — 可配置的折扣叠加规则（优先级/互斥/顺序）
  checkout_discount_log — 每次结账的折扣明细审计日志

设计要点：
  - discount_rules.can_stack_with 使用 TEXT[] 存储可叠加的 type 列表
  - apply_order 控制多折扣叠加时的计算顺序（数字小的先算）
  - priority 控制规则匹配优先级（数字小的优先）
  - store_id NULL 代表全品牌通用规则
  - checkout_discount_log.applied_discounts JSONB 存储完整折扣步骤
  - 金额统一存分值，规避浮点精度
  - RLS: NULLIF(app.tenant_id) 防 NULL 绕过

Revision ID: v106
Revises: v105
Create Date: 2026-04-02
"""

from alembic import op

revision = "v106"
down_revision = "v105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── discount_rules ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS discount_rules (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            store_id        UUID,
            name            VARCHAR(100) NOT NULL,
            priority        INTEGER      NOT NULL DEFAULT 100,
            type            TEXT         NOT NULL
                                CHECK (type IN (
                                    'member_discount',
                                    'platform_coupon',
                                    'manual_discount',
                                    'full_reduction'
                                )),
            can_stack_with  TEXT[]       NOT NULL DEFAULT '{}',
            apply_order     INTEGER      NOT NULL DEFAULT 10,
            is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
            description     TEXT,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE discount_rules ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY discount_rules_tenant_isolation ON discount_rules
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_discount_rules_tenant
            ON discount_rules(tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_discount_rules_store_priority
            ON discount_rules(tenant_id, store_id, priority)
            WHERE is_active = TRUE
    """)

    # ── checkout_discount_log ───────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS checkout_discount_log (
            id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID         NOT NULL,
            order_id            UUID         NOT NULL,
            base_amount_fen     INTEGER      NOT NULL,
            applied_discounts   JSONB        NOT NULL DEFAULT '[]',
            total_saved_fen     INTEGER      NOT NULL DEFAULT 0,
            final_amount_fen    INTEGER      NOT NULL,
            conflicts           JSONB        NOT NULL DEFAULT '[]',
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE checkout_discount_log ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY checkout_discount_log_tenant_isolation ON checkout_discount_log
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_checkout_discount_log_order
            ON checkout_discount_log(order_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_checkout_discount_log_tenant
            ON checkout_discount_log(tenant_id)
    """)

    # ── 预置默认规则（示范数据，is_active=FALSE 不影响生产）──────────────
    # （正式数据由管理后台写入，此处不插入任何租户数据）


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS checkout_discount_log CASCADE")
    op.execute("DROP TABLE IF EXISTS discount_rules CASCADE")
