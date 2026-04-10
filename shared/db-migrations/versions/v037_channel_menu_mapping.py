"""v037: 渠道菜单独立管控 — 平台菜品映射 + 渠道菜单版本

新增表：
  platform_dish_mappings  — 持久化 平台SKU ⇄ 内部菜品映射
  channel_menu_versions   — 渠道菜单发布快照（支持回滚）

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v037
Revises: v036
Create Date: 2026-03-30
"""

from alembic import op

revision = "v037"
down_revision = "v036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. platform_dish_mappings — 平台SKU ⇄ 内部菜品持久化映射
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform_dish_mappings (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            store_id            UUID        NOT NULL,
            platform            VARCHAR(20) NOT NULL,
            platform_item_id    VARCHAR(100) NOT NULL,
            platform_item_name  VARCHAR(200),
            dish_id             UUID        REFERENCES dishes(id),
            platform_price_fen  INT,
            platform_sku_name   VARCHAR(200),
            is_active           BOOLEAN     NOT NULL DEFAULT true,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(tenant_id, store_id, platform, platform_item_id)
        );
    """)
    op.execute("ALTER TABLE platform_dish_mappings ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE platform_dish_mappings FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        if action == "INSERT":
            op.execute(f"""
            CREATE POLICY platform_dish_mappings_{action.lower()}_tenant ON platform_dish_mappings
            AS RESTRICTIVE FOR {action}
            WITH CHECK (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );

            """)
        else:
            op.execute(f"""
            CREATE POLICY platform_dish_mappings_{action.lower()}_tenant ON platform_dish_mappings
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );

            """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_platform_dish_mappings_store_platform
            ON platform_dish_mappings (tenant_id, store_id, platform);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_platform_dish_mappings_dish_id
            ON platform_dish_mappings (dish_id)
            WHERE dish_id IS NOT NULL;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_platform_dish_mappings_unmapped
            ON platform_dish_mappings (tenant_id, store_id, platform)
            WHERE dish_id IS NULL AND is_active = true;
    """)

    # ─────────────────────────────────────────────────────────────────
    # 2. channel_menu_versions — 渠道菜单发布快照
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS channel_menu_versions (
            id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID        NOT NULL,
            store_id       UUID        NOT NULL,
            channel_id     VARCHAR(50) NOT NULL,
            version_no     INT         NOT NULL,
            dish_overrides JSONB       NOT NULL DEFAULT '[]',
            published_at   TIMESTAMPTZ,
            published_by   UUID,
            status         VARCHAR(20) NOT NULL DEFAULT 'draft',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(tenant_id, store_id, channel_id, version_no)
        );
    """)
    op.execute("ALTER TABLE channel_menu_versions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE channel_menu_versions FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        if action == "INSERT":
            op.execute(f"""
            CREATE POLICY channel_menu_versions_{action.lower()}_tenant ON channel_menu_versions
            AS RESTRICTIVE FOR {action}
            WITH CHECK (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );

            """)
        else:
            op.execute(f"""
            CREATE POLICY channel_menu_versions_{action.lower()}_tenant ON channel_menu_versions
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );

            """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_channel_menu_versions_store_channel
            ON channel_menu_versions (tenant_id, store_id, channel_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_channel_menu_versions_published
            ON channel_menu_versions (tenant_id, store_id, channel_id, status)
            WHERE status = 'published';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS channel_menu_versions CASCADE;")
    op.execute("DROP TABLE IF EXISTS platform_dish_mappings CASCADE;")
