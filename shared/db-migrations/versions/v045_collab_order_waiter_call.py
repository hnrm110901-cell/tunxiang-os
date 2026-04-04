"""v045: 多人协同扫码点餐 + 呼叫服务员功能表

新增表：
  table_sessions  — 桌台协同会话（同桌多人扫码共享购物车）
  waiter_calls    — 服务员呼叫记录

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v045
Revises: v043
Create Date: 2026-03-30
"""

from alembic import op

revision = "v045"
down_revision = "v043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # table_sessions — 桌台协同会话
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS table_sessions (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            table_id        UUID        NOT NULL,
            order_id        UUID,
            session_token   VARCHAR(64) NOT NULL,
            participants    JSONB       NOT NULL DEFAULT '[]',
            cart_items      JSONB       NOT NULL DEFAULT '[]',
            status          VARCHAR(20) NOT NULL DEFAULT 'active',
            expires_at      TIMESTAMPTZ NOT NULL,
            submitted_at    TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(session_token),
            CONSTRAINT table_sessions_status_check
                CHECK (status IN ('active', 'submitted', 'expired'))
        );
    """)
    op.execute("ALTER TABLE table_sessions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE table_sessions FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        if action == "INSERT":
            op.execute(f"""
            CREATE POLICY table_sessions_{action.lower()}_tenant ON table_sessions
            AS RESTRICTIVE FOR {action}
            WITH CHECK (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );

            """)
        else:
            op.execute(f"""
            CREATE POLICY table_sessions_{action.lower()}_tenant ON table_sessions
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );

            """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_table_sessions_tenant_store
            ON table_sessions (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_table_sessions_tenant_table
            ON table_sessions (tenant_id, table_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_table_sessions_token
            ON table_sessions (session_token);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_table_sessions_status_expires
            ON table_sessions (status, expires_at);
    """)

    # ─────────────────────────────────────────────────────────────────
    # waiter_calls — 服务员呼叫记录
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS waiter_calls (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL,
            store_id          UUID        NOT NULL,
            table_id          UUID        NOT NULL,
            session_id        UUID        REFERENCES table_sessions(id),
            call_type         VARCHAR(30) NOT NULL DEFAULT 'general',
            note              TEXT        NOT NULL DEFAULT '',
            status            VARCHAR(20) NOT NULL DEFAULT 'pending',
            acknowledged_by   UUID,
            acknowledged_at   TIMESTAMPTZ,
            resolved_at       TIMESTAMPTZ,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT waiter_calls_call_type_check
                CHECK (call_type IN ('general', 'add_item', 'checkout', 'clean_table')),
            CONSTRAINT waiter_calls_status_check
                CHECK (status IN ('pending', 'acknowledged', 'resolved'))
        );
    """)
    op.execute("ALTER TABLE waiter_calls ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE waiter_calls FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        if action == "INSERT":
            op.execute(f"""
            CREATE POLICY waiter_calls_{action.lower()}_tenant ON waiter_calls
            AS RESTRICTIVE FOR {action}
            WITH CHECK (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );

            """)
        else:
            op.execute(f"""
            CREATE POLICY waiter_calls_{action.lower()}_tenant ON waiter_calls
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );

            """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_waiter_calls_tenant_store_status
            ON waiter_calls (tenant_id, store_id, status);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_waiter_calls_session
            ON waiter_calls (session_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS waiter_calls;")
    op.execute("DROP TABLE IF EXISTS table_sessions;")
