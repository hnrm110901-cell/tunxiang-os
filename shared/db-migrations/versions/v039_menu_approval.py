"""v039: 集团菜单下发审批流 — menu_publish_requests + store_menu_permissions

新增表：
  menu_publish_requests   — 集团/品牌向门店下发菜单变更申请（审批流）
  store_menu_permissions  — 门店菜单自主修改权限配置

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v039
Revises: v038
Create Date: 2026-03-30
"""

from alembic import op

revision = "v039"
down_revision = "v038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # menu_publish_requests — 菜单下发申请表
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS menu_publish_requests (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID        NOT NULL,
            request_no       VARCHAR(32) NOT NULL,
            source_type      VARCHAR(20) NOT NULL,
            target_store_ids UUID[]      NOT NULL,
            change_type      VARCHAR(30) NOT NULL,
            change_payload   JSONB       NOT NULL DEFAULT '{}',
            status           VARCHAR(20) NOT NULL DEFAULT 'pending',
            approver_id      UUID,
            approver_note    TEXT,
            approved_at      TIMESTAMPTZ,
            applied_at       TIMESTAMPTZ,
            apply_error      TEXT,
            expires_at       TIMESTAMPTZ,
            created_by       UUID,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (request_no)
        );
    """)
    op.execute("ALTER TABLE menu_publish_requests ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE menu_publish_requests FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY menu_publish_requests_{action.lower()}_tenant ON menu_publish_requests
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_menu_publish_requests_tenant_status
            ON menu_publish_requests (tenant_id, status);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_menu_publish_requests_tenant_created
            ON menu_publish_requests (tenant_id, created_at DESC);
    """)

    # ─────────────────────────────────────────────────────────────────
    # store_menu_permissions — 门店菜单权限配置
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS store_menu_permissions (
            id                   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID         NOT NULL,
            store_id             UUID         NOT NULL,
            can_add_dish         BOOLEAN      NOT NULL DEFAULT FALSE,
            can_modify_price     BOOLEAN      NOT NULL DEFAULT FALSE,
            price_range_pct      DECIMAL(5,2) NOT NULL DEFAULT 10.0,
            can_deactivate_dish  BOOLEAN      NOT NULL DEFAULT TRUE,
            can_add_category     BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id)
        );
    """)
    op.execute("ALTER TABLE store_menu_permissions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE store_menu_permissions FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY store_menu_permissions_{action.lower()}_tenant ON store_menu_permissions
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_store_menu_permissions_tenant_store
            ON store_menu_permissions (tenant_id, store_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS store_menu_permissions;")
    op.execute("DROP TABLE IF EXISTS menu_publish_requests;")
