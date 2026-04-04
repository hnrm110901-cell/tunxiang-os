"""v043: 宴席定金在线支付 + 电子确认单

新增表：
  banquet_deposits       — 宴席定金记录（支持微信JSAPI支付）
  banquet_confirmations  — 宴席电子确认单（含菜单明细JSON、签字）

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v043
Revises: v042
Create Date: 2026-03-30
"""

from alembic import op

revision = "v043"
down_revision = "v042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # banquet_deposits — 宴席定金记录
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_deposits (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            banquet_id          UUID        NOT NULL,
            total_deposit_fen   INT         NOT NULL,
            paid_fen            INT         NOT NULL DEFAULT 0,
            payment_no          VARCHAR(64),
            wechat_prepay_id    VARCHAR(100),
            due_date            DATE,
            status              VARCHAR(20) NOT NULL DEFAULT 'pending',
            paid_at             TIMESTAMPTZ,
            refunded_at         TIMESTAMPTZ,
            refund_amount_fen   INT         NOT NULL DEFAULT 0,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("ALTER TABLE banquet_deposits ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE banquet_deposits FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        if action == "INSERT":
            op.execute(f"""
            CREATE POLICY banquet_deposits_{action.lower()}_tenant ON banquet_deposits
            AS RESTRICTIVE FOR {action}
            WITH CHECK (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );

            """)
        else:
            op.execute(f"""
            CREATE POLICY banquet_deposits_{action.lower()}_tenant ON banquet_deposits
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );

            """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_banquet_deposits_tenant_banquet
            ON banquet_deposits (tenant_id, banquet_id);
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uix_banquet_deposits_payment_no
            ON banquet_deposits (payment_no)
            WHERE payment_no IS NOT NULL;
    """)

    # ─────────────────────────────────────────────────────────────────
    # banquet_confirmations — 宴席电子确认单
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_confirmations (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,
            banquet_id              UUID        NOT NULL,
            confirmation_no         VARCHAR(32) NOT NULL UNIQUE,
            menu_items_json         JSONB       NOT NULL DEFAULT '[]',
            total_fen               INT         NOT NULL,
            guest_count             INT,
            special_requirements    TEXT        NOT NULL DEFAULT '',
            confirmed_by_name       VARCHAR(100),
            confirmed_by_phone      VARCHAR(20),
            signature_data          TEXT,
            confirmed_at            TIMESTAMPTZ,
            status                  VARCHAR(20) NOT NULL DEFAULT 'draft',
            expires_at              TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("ALTER TABLE banquet_confirmations ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE banquet_confirmations FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        if action == "INSERT":
            op.execute(f"""
            CREATE POLICY banquet_confirmations_{action.lower()}_tenant ON banquet_confirmations
            AS RESTRICTIVE FOR {action}
            WITH CHECK (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );

            """)
        else:
            op.execute(f"""
            CREATE POLICY banquet_confirmations_{action.lower()}_tenant ON banquet_confirmations
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );

            """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_banquet_confirmations_tenant_banquet
            ON banquet_confirmations (tenant_id, banquet_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_banquet_confirmations_no
            ON banquet_confirmations (confirmation_no);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_confirmations;")
    op.execute("DROP TABLE IF EXISTS banquet_deposits;")
